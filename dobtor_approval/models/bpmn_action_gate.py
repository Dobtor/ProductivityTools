# -*- coding: utf-8 -*-
"""Action 簽核閘門 — DESIGN.md §5.1 / §5.2-B。

把簽核流程掛到某個 Odoo (model, method) 上。攔截時 _match() 找出對應 gate，
condition 成立且尚未核准 → 起實例擋下原動作；核准後回放。
"""
import logging
import re

from odoo import api, fields, models, _
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)


class BpmnActionGate(models.Model):
    _name = 'bpmn.action.gate'
    _description = 'Action 簽核閘門'
    _order = 'sequence, id'

    name = fields.Char(string='名稱', required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    model_id = fields.Many2one('ir.model', string='目標模型', required=True,
                               ondelete='cascade')
    model_name = fields.Char(related='model_id.model', store=True, index=True,
                             string='模型技術名')
    method_name = fields.Char(string='攔截的方法/按鈕', required=True,
                              help="如 action_confirm / action_post / button_approve")

    # gate 綁定的可執行流程（攔截後要起哪條簽核）
    process_id = fields.Many2one('bpmn.executable.process', string='簽核流程',
                                 required=True, ondelete='cascade')

    execution_mode = fields.Selection([
        ('auto_replay', '核准後自動連動執行（預設）'),
        ('manual_by_submitter', '核准後交回送簽人手動執行'),
    ], string='核准後執行方式', default='auto_replay', required=True,
        help='auto_replay：實例核准即以申請人身分自動回放原動作（含變動防護）；'
             'manual_by_submitter：核准後通知申請人、原按鈕恢復由其手動執行（高風險動作建議）')
    snapshot_fields = fields.Char(
        string='變動防護欄位',
        help='逗號分隔的欄位名；送簽時快照、回放前比對，變動則不自動執行。'
             '留空＝以條件運算式涉及的欄位為準（無條件則不防護）')

    condition = fields.Text(
        string='觸發條件 (Python 運算式)',
        help="可用變數：record、user、env。留空=總是觸發。例：record.amount_total > 10000")

    # ------------------------------------------------------------------
    # 攔截匹配
    # ------------------------------------------------------------------
    def _snapshot_field_names(self):
        """變動防護要快照的欄位：優先 snapshot_fields；否則取條件運算式涉及的 record 欄位。"""
        self.ensure_one()
        if self.snapshot_fields:
            return [f.strip() for f in self.snapshot_fields.split(',') if f.strip()]
        if self.condition:
            return sorted(set(re.findall(r'record\.(\w+)', self.condition)))
        return []

    def _snapshot(self, record):
        """回傳 {field: 可序列化值} 快照（m2o→id，date→iso）。"""
        self.ensure_one()
        snap = {}
        for fname in self._snapshot_field_names():
            if fname not in record._fields:
                continue
            val = record[fname]
            if hasattr(val, '_name'):           # recordset/m2o
                val = val.id if len(val) <= 1 else val.ids
            elif hasattr(val, 'isoformat'):     # date/datetime
                val = val.isoformat()
            snap[fname] = val
        return snap

    def _snapshot_changed(self, record, snapshot):
        """回放前比對：快照欄位是否已變動（回 True＝變動，不應自動執行）。"""
        self.ensure_one()
        current = self._snapshot(record)
        for k, v in (snapshot or {}).items():
            if current.get(k) != v:
                return True
        return False

    @api.model
    def _match(self, model, method, records):
        """回傳第一個符合（model, method）且 condition 成立的 active gate。

        :param records: 被呼叫方法的目標 recordset（用於 condition 求值）
        :return: bpmn.action.gate recordset (0 或 1 筆)
        """
        if not self.env.company._bpmn_feature_enabled('action_gate'):
            return self.browse()
        gates = self.search([
            ('model_name', '=', model),
            ('method_name', '=', method),
            ('active', '=', True),
        ])
        for gate in gates:
            if gate._condition_matches(records):
                return gate
        return self.browse()

    def _condition_matches(self, records):
        self.ensure_one()
        if not self.condition:
            return True
        # 對 recordset 中任一 record 成立即觸發（保守：逐筆）
        for record in records:
            ctx = {'record': record, 'user': self.env.user, 'env': self.env}
            try:
                if safe_eval(self.condition, ctx):
                    return True
            except Exception as exc:
                _logger.warning('bpmn.action.gate 條件求值失敗 (gate=%s): %s',
                                self.id, exc)
        return False
