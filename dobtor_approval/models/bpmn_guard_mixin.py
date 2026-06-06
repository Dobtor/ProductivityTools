# -*- coding: utf-8 -*-
"""後端 Action 介入守門 — DESIGN.md §5.2-B / §5.3。

安全底線：即使繞過前端 JS 攔截（直接 RPC / API / server action），後端仍會檢查
gate。實作方式：override base 的 _register_hook，於 registry 建好後，對所有
bpmn.action.gate 設定的 (model, method) 動態包裝該 method —— 包裝層先檢查 gate，
未核准則起實例並丟例外擋下；context 帶 bpmn_approved=True 時直接放行（回放閉環）。
"""
import logging

from odoo import api, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class BpmnPendingApproval(UserError):
    """以 UserError 呈現「已送簽」提示，阻止原動作。"""
    pass


def _make_guarded(original_method, method_name):
    """產生包裝後的方法：先守門再呼叫原方法。"""

    def guarded(self, *args, **kwargs):
        # 放行條件：context 已標記核准、或正在 install/update 等情境
        if self.env.context.get('bpmn_approved') or self.env.context.get('install_mode'):
            return original_method(self, *args, **kwargs)
        # 找對應 gate
        try:
            gate = self.env['bpmn.action.gate']._match(self._name, method_name, self)
        except Exception:
            gate = self.env['bpmn.action.gate'].browse()
        if gate and not self.env['bpmn.process.instance'].search_count([
            ('process_id', '=', gate.process_id.id),
            ('res_model', '=', self._name),
            ('res_id', 'in', self.ids),
            ('state', '=', 'approved'),
        ]):
            # 是否已有進行中的實例（避免重複起）
            running = self.env['bpmn.process.instance'].search_count([
                ('process_id', '=', gate.process_id.id),
                ('res_model', '=', self._name),
                ('res_id', 'in', self.ids),
                ('state', '=', 'running'),
            ])
            if not running:
                for record in self:
                    gate.process_id.start(
                        res_model=self._name,
                        res_id=record.id,
                        applicant=self.env.user,
                        pending_action={
                            'model': self._name,
                            'method': method_name,
                            'res_ids': self.ids,
                        },
                    )
            raise BpmnPendingApproval(_(
                '此動作需經簽核。已送出簽核流程「%s」，核准後將自動執行。',
                gate.process_id.name))
        return original_method(self, *args, **kwargs)

    guarded.__name__ = method_name
    guarded._bpmn_guarded = True
    return guarded


class BpmnGuardBase(models.AbstractModel):
    """掛在 base 上，registry 建好後動態包裝受管方法。"""
    _inherit = 'base'

    def _register_hook(self):
        res = super()._register_hook()
        try:
            self._bpmn_install_guards()
        except Exception:
            _logger.exception('BPMN guard 安裝失敗（不影響啟動）')
        return res

    @api.model
    def _bpmn_install_guards(self):
        """讀 bpmn.action.gate 設定，對每個 (model, method) 包裝守門。"""
        # 模組未完整安裝時 gate 表可能不存在
        if 'bpmn.action.gate' not in self.env:
            return
        try:
            gates = self.env['bpmn.action.gate'].sudo().search([('active', '=', True)])
        except Exception:
            return
        wrapped = set()
        for gate in gates:
            model_name = gate.model_name
            method_name = gate.method_name
            if not model_name or not method_name:
                continue
            key = (model_name, method_name)
            if key in wrapped:
                continue
            Model = self.env.get(model_name)
            if Model is None:
                continue
            ModelClass = type(Model)
            current = getattr(ModelClass, method_name, None)
            if current is None or not callable(current):
                continue
            if getattr(current, '_bpmn_guarded', False):
                wrapped.add(key)
                continue
            setattr(ModelClass, method_name, _make_guarded(current, method_name))
            wrapped.add(key)
            _logger.info('BPMN guard 已包裝 %s.%s', model_name, method_name)
