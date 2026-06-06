# -*- coding: utf-8 -*-
"""流程實例 + token 執行引擎 — DESIGN.md §3.5、§5.3、§6.1。

核心引擎：
- _kickoff(): 在 start 節點放 token，推進至第一個 user_task。
- _enter_node(): 依節點型別分派（user_task→產生活動；service_task→執行 action；
  gateway→路由；end→收斂）。
- _on_link_approved/_on_link_rejected(): 活動完成回呼，依 approval_mode 推進。
- _replay_pending_action(): 核准後回放原 Odoo action（Action 介入閉環）。
"""
import json
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)

_MAX_STEPS = 200  # 單次推進的安全上限，防圖環造成無窮迴圈


class BpmnProcessInstance(models.Model):
    _name = 'bpmn.process.instance'
    _description = 'BPMN 流程實例'
    _inherit = ['mail.thread']
    _order = 'id desc'

    name = fields.Char(string='實例名稱', compute='_compute_name', store=True)
    process_id = fields.Many2one('bpmn.executable.process', string='流程定義',
                                 required=True, ondelete='restrict', index=True)
    definition_version = fields.Integer(string='定義版本', readonly=True)
    state = fields.Selection([
        ('running', '進行中'),
        ('approved', '核准完成'),
        ('rejected', '駁回'),
        ('cancelled', '取消'),
        ('incident', '異常'),
    ], string='狀態', default='running', tracking=True, index=True)

    applicant_user_id = fields.Many2one('res.users', string='申請人',
                                        default=lambda s: s.env.user)
    res_model = fields.Char(string='單據模型', index=True)
    res_id = fields.Integer(string='單據 ID', index=True)
    res_name = fields.Char(string='單據名稱', compute='_compute_res_name')

    token_ids = fields.One2many('bpmn.token', 'instance_id', string='Tokens')
    activity_link_ids = fields.One2many('bpmn.activity.link', 'instance_id',
                                        string='簽核活動')
    pending_action = fields.Text(string='待回放動作 (JSON)')
    incident_message = fields.Text(string='異常訊息')

    @api.depends('process_id', 'applicant_user_id')
    def _compute_name(self):
        for rec in self:
            rec.name = '%s / %s #%s' % (
                rec.process_id.name or '',
                rec.applicant_user_id.name or '',
                rec.id or '')

    @api.depends('res_model', 'res_id')
    def _compute_res_name(self):
        for rec in self:
            if rec.res_model and rec.res_id and rec.res_model in self.env:
                record = self.env[rec.res_model].browse(rec.res_id).exists()
                rec.res_name = record.display_name if record else False
            else:
                rec.res_name = False

    def _get_res_record(self):
        self.ensure_one()
        if self.res_model and self.res_id and self.res_model in self.env:
            return self.env[self.res_model].browse(self.res_id).exists()
        return False

    # ------------------------------------------------------------------
    # 啟動
    # ------------------------------------------------------------------
    def _kickoff(self):
        self.ensure_one()
        start_id = self.process_id._start_element_id()
        if not start_id:
            self._set_incident(_('找不到開始節點'))
            return
        token = self.env['bpmn.token'].create({
            'instance_id': self.id,
            'bpmn_element_id': start_id,
            'state': 'active',
        })
        self._advance_token(token)

    # ------------------------------------------------------------------
    # token 推進
    # ------------------------------------------------------------------
    def _advance_token(self, token):
        """從 token 當前節點往後走，直到抵達會「停住」的節點（user_task / end）。"""
        self.ensure_one()
        nodes, flows = self.process_id._build_graph()
        steps = 0
        current = token
        while current and current.state == 'active':
            steps += 1
            if steps > _MAX_STEPS:
                self._set_incident(_('推進步數超過上限，疑似流程有環'))
                return
            element_id = current.bpmn_element_id
            node = nodes.get(element_id)
            if not node:
                self._set_incident(_('找不到節點 %s') % element_id)
                return
            node_type = node['node_type']

            if node_type == 'start':
                current = self._move_to_next(current, nodes, flows)

            elif node_type == 'end':
                current.consume()
                self._check_completion()
                return

            elif node_type == 'user_task':
                # 停住：產生簽核活動，等人簽
                self._enter_user_task(current)
                return

            elif node_type == 'service_task':
                self._execute_service_task(current)
                if self.state != 'running':
                    return
                current = self._move_to_next(current, nodes, flows)

            elif node_type == 'exclusive_gw':
                current = self._route_exclusive(current, nodes, flows)

            elif node_type in ('parallel_gw', 'inclusive_gw'):
                # 簡化：依出線數展開多 token（T3 能力）。join 由 _check_completion 收斂。
                current = self._route_parallel(current, nodes, flows)
                return
            else:
                self._set_incident(_('未支援的節點型別 %s') % node_type)
                return

    def _outgoing_flows(self, element_id, flows):
        return [f for f in flows if f['source'] == element_id]

    def _move_to_next(self, token, nodes, flows):
        """單一出線：移動 token 到下一節點；無出線則消耗。"""
        outs = self._outgoing_flows(token.bpmn_element_id, flows)
        if not outs:
            token.consume()
            self._check_completion()
            return False
        target = outs[0]['target']
        token.write({'bpmn_element_id': target,
                     'node_name': nodes.get(target, {}).get('name')})
        return token

    def _route_exclusive(self, token, nodes, flows):
        """互斥閘道：依條件選一條出線。無條件成立則走預設/第一條。"""
        outs = self._outgoing_flows(token.bpmn_element_id, flows)
        record = self._get_res_record()
        chosen = None
        default = None
        for flow in outs:
            cond = flow.get('condition')
            if not cond:
                default = default or flow
                continue
            ctx = {'record': record, 'applicant': self.applicant_user_id,
                   'env': self.env}
            try:
                if safe_eval(cond, ctx):
                    chosen = flow
                    break
            except Exception as exc:
                _logger.warning('exclusive gateway 條件求值失敗: %s', exc)
        flow = chosen or default or (outs[0] if outs else None)
        if not flow:
            token.consume()
            self._check_completion()
            return False
        token.write({'bpmn_element_id': flow['target'],
                     'node_name': nodes.get(flow['target'], {}).get('name')})
        return token

    def _route_parallel(self, token, nodes, flows):
        """並行閘道：每條出線一個 token，原 token 消耗後逐一推進。"""
        outs = self._outgoing_flows(token.bpmn_element_id, flows)
        token.consume()
        for flow in outs:
            new_token = self.env['bpmn.token'].create({
                'instance_id': self.id,
                'bpmn_element_id': flow['target'],
                'node_name': nodes.get(flow['target'], {}).get('name'),
                'state': 'active',
            })
            self._advance_token(new_token)
        return False

    # ------------------------------------------------------------------
    # User Task → 簽核活動
    # ------------------------------------------------------------------
    def _enter_user_task(self, token):
        """token 抵達簽核節點：解析簽核人、產生 mail.activity + link。"""
        self.ensure_one()
        cfg = self.process_id._config_for(token.bpmn_element_id)
        if not cfg or not cfg.role_id:
            self._set_incident(_('簽核節點 %s 未綁定角色') % token.bpmn_element_id)
            return
        approvers = cfg.role_id.resolve(self)
        if not approvers:
            self._set_incident(_(
                '簽核節點「%s」解析不到任何簽核人') % (cfg.name or token.bpmn_element_id))
            return

        mode = cfg.approval_mode or 'any'
        Link = self.env['bpmn.activity.link']
        if mode == 'sequential':
            # 只先產生第一位的活動，其餘待依序
            ordered = list(approvers)
            first = ordered[0]
            activity = self._create_approval_activity(token.bpmn_element_id, first)
            link = Link.create(self._link_vals(token, cfg, first, activity, seq=10))
            # 其餘建 pending link（無活動，依序喚起）
            for idx, user in enumerate(ordered[1:], start=2):
                Link.create(self._link_vals(token, cfg, user, False, seq=idx * 10))
        else:
            # any / all：一次產生所有人的活動
            for idx, user in enumerate(approvers, start=1):
                activity = self._create_approval_activity(token.bpmn_element_id, user)
                Link.create(self._link_vals(token, cfg, user, activity, seq=idx * 10))

    def _link_vals(self, token, cfg, user, activity, seq=10):
        return {
            'instance_id': self.id,
            'token_id': token.id,
            'bpmn_element_id': token.bpmn_element_id,
            'activity_id': activity.id if activity else False,
            'approver_user_id': user.id,
            'decision': 'pending',
            'sequence': seq,
        }

    def _create_approval_activity(self, element_id, user, summary_suffix=''):
        """在原單據（或實例自身）上建立一張簽核 mail.activity。"""
        self.ensure_one()
        cfg = self.process_id._config_for(element_id)
        node_name = cfg.name or element_id
        activity_type = self.env.ref(
            'dobtor_approval.activity_type_approval', raise_if_not_found=False)
        # 掛在原單據上；若無單據則掛在實例本身
        if self.res_model and self.res_id:
            res_model = self.res_model
            res_id = self.res_id
        else:
            res_model = self._name
            res_id = self.id
        vals = {
            'res_model_id': self.env['ir.model']._get(res_model).id,
            'res_id': res_id,
            'user_id': user.id,
            'summary': _('[簽核] %(node)s%(suffix)s',
                         node=node_name, suffix=summary_suffix),
            'note': _('流程「%(proc)s」需要您的簽核。',
                      proc=self.process_id.name),
        }
        if activity_type:
            vals['activity_type_id'] = activity_type.id
        return self.env['mail.activity'].create(vals)

    # ------------------------------------------------------------------
    # 簽核結果回呼
    # ------------------------------------------------------------------
    def _on_link_approved(self, link):
        """某簽核活動核准後：依 approval_mode 判斷該節點是否完成 → 推進 token。"""
        self.ensure_one()
        token = link.token_id
        if not token or token.state != 'active':
            return
        element_id = link.bpmn_element_id
        cfg = self.process_id._config_for(element_id)
        mode = cfg.approval_mode or 'any'
        node_links = self.activity_link_ids.filtered(
            lambda l: l.token_id == token and l.bpmn_element_id == element_id
            and l.decision != 'escalated')

        if mode == 'any':
            # 任一核准即過 → 取消其餘待簽活動，推進
            self._cancel_pending_siblings(node_links, exclude=link)
            self._proceed_after_node(token)

        elif mode == 'all':
            pending = node_links.filtered(lambda l: l.decision == 'pending')
            if not pending:
                self._proceed_after_node(token)

        elif mode == 'sequential':
            nxt = node_links.filtered(lambda l: l.decision == 'pending') \
                .sorted('sequence')[:1]
            if nxt:
                # 喚起下一位的活動
                if not nxt.activity_id:
                    activity = self._create_approval_activity(
                        element_id, nxt.approver_user_id)
                    nxt.activity_id = activity.id
            else:
                self._proceed_after_node(token)

    def _cancel_pending_siblings(self, node_links, exclude=None):
        for l in node_links:
            if l == exclude:
                continue
            if l.decision == 'pending':
                if l.activity_id and l.activity_id.active:
                    l.activity_id.action_cancel()
                l.decision = 'approved'  # 視為連帶通過（any 模式）

    def _proceed_after_node(self, token):
        """節點完成 → token 往下走。"""
        nodes, flows = self.process_id._build_graph()
        token = self._move_to_next(token, nodes, flows)
        if token:
            self._advance_token(token)

    def _on_link_rejected(self, link):
        """任一簽核駁回 → 整個實例駁回；若指定駁回去向節點則退回該關重簽。"""
        self.ensure_one()
        # 取消所有待簽活動
        for l in self.activity_link_ids.filtered(lambda x: x.decision == 'pending'):
            if l.activity_id and l.activity_id.active:
                l.activity_id.action_cancel()

        # 退回指定關卡（駁回到節點）— best-effort，僅當目標為人工簽核節點
        target = link.reject_to_element
        if target and link.token_id:
            cfg = self.process_id._config_for(target)
            if cfg and cfg.node_type == 'user_task':
                try:
                    token = link.token_id
                    token.write({'bpmn_element_id': target, 'state': 'active'})
                    self.message_post(body=_(
                        '流程經 %(user)s 駁回，退回關卡「%(node)s」重簽。',
                        user=self.env.user.name, node=cfg.name or target))
                    self._enter_user_task(token)
                    return
                except Exception:  # noqa: BLE001 退回失敗則改整案駁回
                    _logger.exception('駁回退回節點失敗，改整案駁回')

        # 預設：整案駁回
        self.token_ids.filtered(lambda t: t.state == 'active').consume()
        self.write({'state': 'rejected'})
        self.message_post(body=_(
            '流程遭 %(user)s 駁回。', user=self.env.user.name))

    # ------------------------------------------------------------------
    # Service Task
    # ------------------------------------------------------------------
    def _execute_service_task(self, token):
        self.ensure_one()
        cfg = self.process_id._config_for(token.bpmn_element_id)
        record = self._get_res_record()
        try:
            if cfg.server_action_id:
                action_ctx = dict(self.env.context,
                                  active_model=self.res_model,
                                  active_id=self.res_id,
                                  active_ids=[self.res_id] if self.res_id else [],
                                  bpmn_approved=True)
                cfg.server_action_id.with_context(**action_ctx).run()
            elif cfg.bound_method and record:
                getattr(record.with_context(bpmn_approved=True), cfg.bound_method)()
        except Exception as exc:
            self._set_incident(_('系統動作執行失敗：%s') % exc)

    # ------------------------------------------------------------------
    # 完成 / 異常
    # ------------------------------------------------------------------
    def _check_completion(self):
        """所有 token 消耗 → 實例核准完成 → 回放 pending action。"""
        self.ensure_one()
        if self.state != 'running':
            return
        if self.token_ids.filtered(lambda t: t.state == 'active'):
            return  # 還有活躍 token
        self.write({'state': 'approved'})
        self.message_post(body=_('流程核准完成。'))
        self._replay_pending_action()

    def _set_incident(self, message):
        self.ensure_one()
        self.write({'state': 'incident', 'incident_message': message})
        self.message_post(body=_('流程異常：%s') % message)
        _logger.warning('bpmn.process.instance %s incident: %s', self.id, message)

    # ------------------------------------------------------------------
    # Action 介入回放 — DESIGN.md §5.3
    # ------------------------------------------------------------------
    def _replay_pending_action(self):
        self.ensure_one()
        if not self.pending_action:
            return
        try:
            data = json.loads(self.pending_action)
        except (ValueError, TypeError):
            return
        model = data.get('model')
        method = data.get('method')
        res_ids = data.get('res_ids') or ([data['res_id']] if data.get('res_id') else [])
        if not (model and method and res_ids and model in self.env):
            return
        records = self.env[model].browse(res_ids).exists()
        if not records:
            return
        # 標記放行，避免再次被攔截
        try:
            getattr(records.with_context(bpmn_approved=True), method)()
        except Exception as exc:
            self._set_incident(_('回放原動作失敗：%s') % exc)
            return
        # 清掉 pending（已回放）
        self.pending_action = False

    def _replay_pending_action_cron(self):
        """骨架：T5 incident 重試用，可掛 cron 重放 incident 實例。TODO。"""
        return True

    # ------------------------------------------------------------------
    # 管理動作
    # ------------------------------------------------------------------
    def action_cancel_instance(self):
        for rec in self.filtered(lambda r: r.state == 'running'):
            for l in rec.activity_link_ids.filtered(lambda x: x.decision == 'pending'):
                if l.activity_id and l.activity_id.active:
                    l.activity_id.action_cancel()
            rec.token_ids.filtered(lambda t: t.state == 'active').consume()
            rec.write({'state': 'cancelled'})
            rec.message_post(body=_('流程已取消。'))
        return True

    def action_view_activities(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('簽核活動'),
            'res_model': 'mail.activity',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.activity_link_ids.activity_id.ids)],
        }

    def action_open_document(self):
        self.ensure_one()
        record = self._get_res_record()
        if not record:
            raise UserError(_('此實例沒有關聯單據。'))
        return {
            'type': 'ir.actions.act_window',
            'res_model': self.res_model,
            'res_id': self.res_id,
            'view_mode': 'form',
            'target': 'current',
        }

    # ------------------------------------------------------------------
    # 占位：DESIGN.md 提及但屬骨架的方法
    # ------------------------------------------------------------------
    def _enter_user_task_token(self, token):
        """別名以符合 DESIGN.md 命名；委派 _enter_user_task。"""
        return self._enter_user_task(token)

    def _advance(self, token):
        """別名以符合 DESIGN.md 命名；委派 _advance_token。"""
        return self._advance_token(token)
