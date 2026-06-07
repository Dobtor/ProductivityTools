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
    dmn_outputs = fields.Text(
        string='DMN 決策輸出 (JSON)',
        help='businessRuleTask 求值結果，供後續 instance_ctx 綁定 / 閘道條件引用')

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

            elif node_type == 'business_rule':
                self._execute_business_rule(current)
                if self.state != 'running':
                    return
                current = self._move_to_next(current, nodes, flows)

            elif node_type == 'exclusive_gw':
                current = self._route_exclusive(current, nodes, flows)

            elif node_type == 'inclusive_gw':
                # join（多入線）：分支同步；未到齊則 park 等待。
                if self._is_join(current.bpmn_element_id, flows) and \
                        not self._gateway_join_ready(current, flows, 'inclusive_gw'):
                    return
                current = self._route_inclusive(current, nodes, flows)
                return

            elif node_type == 'parallel_gw':
                # join（多入線）：所有入線到齊才 split 出線。
                if self._is_join(current.bpmn_element_id, flows) and \
                        not self._gateway_join_ready(current, flows, 'parallel_gw'):
                    return
                current = self._route_parallel(current, nodes, flows)
                return
            else:
                self._set_incident(_('未支援的節點型別 %s') % node_type)
                return

    def _outgoing_flows(self, element_id, flows):
        return [f for f in flows if f['source'] == element_id]

    def _incoming_flows(self, element_id, flows):
        return [f for f in flows if f['target'] == element_id]

    def _is_join(self, element_id, flows):
        """多入線（>1）閘道＝join，需同步分支。"""
        return len(self._incoming_flows(element_id, flows)) > 1

    def _join_ready_peek(self, token, flows, node_type):
        """非消耗式判斷 join 是否可推進。

        - parallel_gw：所有入線到齊（parked 數 >= 入線數）→ 精確、無死結、無 over-sync。
        - inclusive_gw：到齊 或 別處已無 active token（部分分支啟動時的收斂）；
          別處仍有 token 時 park，待其結束由 `_resume_joins` 重掃喚醒 → 不死結。
        """
        element_id = token.bpmn_element_id
        active = self.token_ids.filtered(lambda t: t.state == 'active')
        here = active.filtered(lambda t: t.bpmn_element_id == element_id)
        incoming = len(self._incoming_flows(element_id, flows))
        if node_type == 'parallel_gw':
            return len(here) >= incoming
        elsewhere = active.filtered(lambda t: t.bpmn_element_id != element_id)
        return len(here) >= incoming or not elsewhere

    def _gateway_join_ready(self, token, flows, node_type):
        """ready 時消耗本閘道其餘 parked token，回 True 由本 token 續走（唯一消耗點）。"""
        if not self._join_ready_peek(token, flows, node_type):
            return False
        here = self.token_ids.filtered(
            lambda t: t.state == 'active' and t.bpmn_element_id == token.bpmn_element_id)
        (here - token).consume()
        return True

    def _resume_joins(self):
        """重掃停在 join 閘道、現已可推進的 parked token（避免 inclusive over-sync 死結）。
        以非消耗式 peek 判斷，再交 `_advance_token` 做唯一的消耗式推進。"""
        self.ensure_one()
        if self.state != 'running':
            return
        nodes, flows = self.process_id._build_graph()
        for tok in self.token_ids.filtered(lambda t: t.state == 'active'):
            data = nodes.get(tok.bpmn_element_id)
            if not data or data['node_type'] not in ('parallel_gw', 'inclusive_gw'):
                continue
            if not self._is_join(tok.bpmn_element_id, flows):
                continue
            if self._join_ready_peek(tok, flows, data['node_type']):
                self._advance_token(tok)
                return  # 狀態已變；後續收斂點會再觸發重掃

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

    def _build_gateway_ctx(self, token, record):
        """組閘道條件 ctx + row-builder 條件表。閘道綁 DMN 時注入 dmn_result/輸出欄。"""
        base_ctx = {'record': record, 'applicant': self.applicant_user_id,
                    'env': self.env}
        cfg = self.process_id._config_for(token.bpmn_element_id)
        if cfg and cfg.dmn_decision_id:
            try:
                res = cfg.dmn_decision_id.definitions_id.evaluate_decision(
                    cfg.dmn_decision_id.dmn_id, record, self.applicant_user_id, self)
                base_ctx['dmn_result'] = res
                if isinstance(res, dict):
                    base_ctx.update(res)
            except Exception as exc:
                _logger.warning('gateway DMN 決策求值失敗: %s', exc)
        fconds = {}
        if cfg and cfg.flow_conditions:
            try:
                fconds = json.loads(cfg.flow_conditions)
            except (ValueError, TypeError):
                fconds = {}
        return base_ctx, fconds

    def _flow_passes(self, flow, fconds, base_ctx, record):
        """回傳 True/False＝條件成立與否；None＝無條件（預設候選線）。"""
        cond = flow.get('condition')
        rows = fconds.get(flow['target'])
        if not cond and not rows:
            return None
        try:
            if cond:
                return bool(safe_eval(cond, dict(base_ctx)))
            return self._eval_cond_rows(rows, base_ctx, record)
        except Exception as exc:
            _logger.warning('gateway 條件求值失敗: %s', exc)
            return False

    def _route_exclusive(self, token, nodes, flows):
        """互斥閘道：依條件選一條出線（首條成立）。皆不成立則走預設/第一條。"""
        outs = self._outgoing_flows(token.bpmn_element_id, flows)
        record = self._get_res_record()
        base_ctx, fconds = self._build_gateway_ctx(token, record)
        chosen = None
        default = None
        for flow in outs:
            res = self._flow_passes(flow, fconds, base_ctx, record)
            if res is None:
                default = default or flow
            elif res:
                chosen = flow
                break
        flow = chosen or default or (outs[0] if outs else None)
        if not flow:
            token.consume()
            self._check_completion()
            return False
        token.write({'bpmn_element_id': flow['target'],
                     'node_name': nodes.get(flow['target'], {}).get('name')})
        return token

    def _route_inclusive(self, token, nodes, flows):
        """包容閘道(OR)：split 所有條件成立的出線；皆不成立則走預設/第一條。"""
        outs = self._outgoing_flows(token.bpmn_element_id, flows)
        record = self._get_res_record()
        base_ctx, fconds = self._build_gateway_ctx(token, record)
        passing, default = [], None
        for flow in outs:
            res = self._flow_passes(flow, fconds, base_ctx, record)
            if res is None:
                default = default or flow
            elif res:
                passing.append(flow)
        targets = passing or ([default] if default else (outs[:1] if outs else []))
        token.consume()
        for flow in targets:
            nt = self.env['bpmn.token'].create({
                'instance_id': self.id,
                'bpmn_element_id': flow['target'],
                'node_name': nodes.get(flow['target'], {}).get('name'),
                'state': 'active',
            })
            self._advance_token(nt)
        if not targets:
            self._check_completion()
        return False

    @staticmethod
    def _as_num(v):
        if isinstance(v, bool) or v is None:
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None

    def _cmp_row(self, left, op, val):
        """單一條件比較（數值優先，否則字串）。"""
        if op == 'set':
            return bool(left)
        if op == 'in':
            opts = [v.strip() for v in (val or '').split(',') if v.strip()]
            return str(left) in opts
        lnum, rnum = self._as_num(left), self._as_num(val)
        if lnum is not None and rnum is not None:
            l, r = lnum, rnum
        else:
            l = '' if left is None else str(left)
            r = val or ''
        return {
            '=': l == r, '!=': l != r,
            '>': l > r, '>=': l >= r, '<': l < r, '<=': l <= r,
        }.get(op, False)

    def _row_left(self, row, ctx, record):
        """條件左運算元：先查 ctx（如 dmn_result），再查單據欄位（m2o 取 id）。"""
        field = (row.get('field') or '').strip()
        left = ctx.get(field)
        if left is None and record and field in record._fields:
            left = record[field]
            if hasattr(left, '_name'):
                left = left.id
        return left

    def _eval_cond_rows(self, rows, ctx, record):
        """求值 row-builder 條件 [{field, op, value, join}]。
        row.join=='or' 起新 OR 群組；群組內 AND、群組間 OR。"""
        groups, cur = [], []
        for row in rows or []:
            if not (row.get('field') or '').strip():
                continue
            if (row.get('join') or 'and') == 'or' and cur:
                groups.append(cur)
                cur = []
            cur.append(row)
        if cur:
            groups.append(cur)
        if not groups:
            return True
        for group in groups:
            if all(self._cmp_row(self._row_left(row, ctx, record),
                                 row.get('op') or '=', row.get('value'))
                   for row in group):
                return True
        return False

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

        # 決策型（核決權限表 / DMN 決策）：分階（同階會簽、跨階依序）—
        # 獨立路徑，不影響 any/all/sequential
        if cfg.role_id.resolver_type in self._PHASED_RESOLVERS:
            return self._enter_decision_node(token, cfg)

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

    # 走分階逐關引擎的 resolver 型別（同階會簽、跨階依序）
    _PHASED_RESOLVERS = ('authority_matrix', 'dmn_decision')

    def _build_phased_chain(self, cfg):
        """回傳依階排序的 [(phase, users)]。核決權限表＝規則列序；DMN＝approver 鏈 phase。"""
        role = cfg.role_id
        record = self._get_res_record()
        applicant = self.applicant_user_id
        Users = self.env['res.users']
        if role.resolver_type == 'authority_matrix':
            matrix = role.matrix_id
            chain = matrix.resolve_approvers(record, applicant) if matrix else []
            return [(i, users) for i, (_line, users) in enumerate(chain, start=1) if users]
        if role.resolver_type == 'dmn_decision' and role.decision_id:
            defn = role.decision_id.definitions_id
            items = defn.resolve_approver_chain(
                role.decision_id.dmn_id, record, applicant, self)
            by_phase = {}
            for n, item in enumerate(items, start=1):
                ph = item.get('phase') or n
                users = role._resolve_chain_item(item, self)
                if users:
                    by_phase[ph] = (by_phase.get(ph) or Users) | users
            return [(ph, by_phase[ph]) for ph in sorted(by_phase)]
        return []

    def _enter_decision_node(self, token, cfg):
        """決策型節點：依命中鏈分階建立 link（phase 正規化為 1..N）。
        第 1 階立即產生活動（同階會簽），其餘階待前階全部簽完再喚起（跨階依序）。"""
        chain = self._build_phased_chain(cfg)
        if not chain:
            self._set_incident(_(
                '決策節點「%s」解析不到任何簽核人') % (cfg.name or token.bpmn_element_id))
            return
        Link = self.env['bpmn.activity.link']
        for order, (_ph, users) in enumerate(chain, start=1):
            for idx, user in enumerate(users):
                activity = (self._create_approval_activity(token.bpmn_element_id, user)
                            if order == 1 else False)
                vals = self._link_vals(token, cfg, user, activity, seq=order * 100 + idx)
                vals['phase'] = order
                Link.create(vals)

    # 向後相容別名
    def _enter_matrix_node(self, token, cfg):
        return self._enter_decision_node(token, cfg)

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

        # 決策型分階節點：同階會簽、跨階依序（獨立路徑）
        if cfg and cfg.role_id and cfg.role_id.resolver_type in self._PHASED_RESOLVERS:
            return self._on_matrix_link_approved(link, token, cfg, node_links)

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

    def _on_matrix_link_approved(self, link, token, cfg, node_links):
        """核決權限表分階推進：本階全簽完（會簽）才喚起下一階；無下一階則節點完成。"""
        if not link.phase:
            # 非分階 link（如會辦/徵詢 phase=0）不推進核決鏈
            return
        cur = link.phase
        if node_links.filtered(lambda l: l.phase == cur and l.decision == 'pending'):
            return  # 本級尚有人未簽 → 等待會簽
        nxt = node_links.filtered(lambda l: l.phase > cur)
        if nxt:
            np = min(nxt.mapped('phase'))
            for l in nxt.filtered(lambda l: l.phase == np and not l.activity_id):
                activity = self._create_approval_activity(
                    link.bpmn_element_id, l.approver_user_id)
                l.activity_id = activity.id
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
    # Business Rule Task（DMN 求值寫回）
    # ------------------------------------------------------------------
    def _execute_business_rule(self, token):
        """求值綁定的 DMN 決策 → 輸出存進實例 ctx（dmn_outputs JSON），
        可選寫回單據同名欄位。輸出供後續 instance_ctx 綁定 / 閘道條件引用。"""
        self.ensure_one()
        cfg = self.process_id._config_for(token.bpmn_element_id)
        dec = cfg.dmn_decision_id if cfg else False
        if not dec:
            self._set_incident(_('商業規則節點「%s」未綁定 DMN 決策')
                               % (cfg.name if cfg else token.bpmn_element_id))
            return
        record = self._get_res_record()
        try:
            value = dec.definitions_id.evaluate_decision(
                dec.dmn_id, record, self.applicant_user_id, self)
        except Exception as exc:
            self._set_incident(_('商業規則求值失敗：%s') % exc)
            return
        outputs = value if isinstance(value, dict) else {dec.name: value}
        # 併入實例 ctx（Decimal/date 以 default=str 轉存）
        merged = {}
        if self.dmn_outputs:
            try:
                merged = json.loads(self.dmn_outputs)
            except (ValueError, TypeError):
                merged = {}
        merged.update(outputs)
        self.dmn_outputs = json.dumps(merged, default=str)
        # 寫回單據同名欄位（依欄位型別轉換）
        if cfg.dmn_write_to_record and record:
            to_write = {k: self._coerce_for_field(record, k, v)
                        for k, v in outputs.items() if k in record._fields}
            if to_write:
                try:
                    record.with_context(bpmn_approved=True).write(to_write)
                except Exception as exc:
                    _logger.warning('商業規則寫回單據失敗: %s', exc)
        self.message_post(body=_('商業規則「%(d)s」求值：%(o)s',
                                 d=dec.name, o=str(outputs)))

    def _coerce_for_field(self, record, fname, value):
        """把 DMN 輸出值依目標欄位型別轉換（Decimal/date 等 → 欄位可寫型別）。"""
        field = record._fields.get(fname)
        if field is None or value is None:
            return value
        try:
            if field.type in ('float', 'monetary'):
                return float(value)
            if field.type == 'integer':
                return int(value)
            if field.type == 'boolean':
                return bool(value)
            if field.type in ('char', 'text', 'html'):
                v = value
                if not isinstance(v, str):
                    v = ('%f' % v).rstrip('0').rstrip('.') if isinstance(v, float) else str(v)
                return v
        except (ValueError, TypeError):
            return value
        return value

    def get_ctx_value(self, key):
        """取實例 DMN 輸出 ctx 值（供 dmn.input.binding 的 instance_ctx 來源）。"""
        self.ensure_one()
        if not self.dmn_outputs:
            return None
        try:
            return json.loads(self.dmn_outputs).get(key)
        except (ValueError, TypeError):
            return None

    # ------------------------------------------------------------------
    # 完成 / 異常
    # ------------------------------------------------------------------
    def _check_completion(self):
        """所有 token 消耗 → 實例核准完成 → 回放 pending action。"""
        self.ensure_one()
        if self.state != 'running':
            return
        # 先喚醒因 over-sync 而 park 在 join 閘道、現已可推進的 token（避免死結）
        self._resume_joins()
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
