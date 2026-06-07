import json
import logging
from xml.sax.saxutils import quoteattr

from lxml import etree

from odoo import _, api, models, Command
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# ServiceTask / 動作節點型別（可掛動作插入點）
_ACTION_NODE_TYPES = ('service_task',)
# 常見可攔截方法白名單（補充 form 按鈕掃描）
_METHOD_WHITELIST = [
    'action_confirm', 'action_post', 'action_done', 'action_approve',
    'action_validate', 'button_confirm', 'button_approve', 'action_cancel',
]


class BpmnExecutableProcessEditor(models.Model):
    """全版簽核設定編輯器的後端 API（DESIGN_APPROVAL_EDITOR.md）。"""
    _inherit = 'bpmn.executable.process'

    # ------------------------------------------------------------------
    # 開啟編輯器
    # ------------------------------------------------------------------
    def action_open_process_editor(self):
        self.ensure_one()
        # 確保每個 BPMN 元素都有 config 列（非破壞性）
        xml = self._effective_xml()
        if xml:
            self._sync_node_configs_from_xml(xml)
        return {
            'type': 'ir.actions.client',
            'tag': 'dobtor_approval.process_editor',
            'name': self.name or _('簽核設定'),
            'params': {'process_id': self.id},
            'target': 'current',
        }

    # ------------------------------------------------------------------
    # 載入編輯器資料
    # ------------------------------------------------------------------
    @api.model
    def _selection_options(self, model, field):
        try:
            return self.env[model]._fields[field]._description_selection(self.env)
        except Exception:  # noqa: BLE001
            return []

    def get_editor_data(self):
        self.ensure_one()
        xml = self._effective_xml()
        if xml:
            self._sync_node_configs_from_xml(xml)
        outgoing, walk_order, names = self._parse_flows(xml)
        nodes = []
        for cfg in self.node_config_ids:
            role = cfg.role_id
            try:
                fconds = json.loads(cfg.flow_conditions or '{}')
            except (ValueError, TypeError):
                fconds = {}
            eid = cfg.bpmn_element_id
            nodes.append({
                'element_id': eid,
                'name': cfg.name,
                'node_type': cfg.node_type,
                'approval_mode': cfg.approval_mode or 'any',
                'allow_escalation': cfg.allow_escalation,
                'gate_timing': cfg.gate_timing or '',
                'gate_model_id': cfg.gate_model_id.id or False,
                'gate_method': cfg.gate_method or '',
                'sla_hours': cfg.sla_hours or 0.0,
                'sla_action': cfg.sla_action or '',
                'resolver_type': role.resolver_type if role else '',
                'level': role.level if role else 1,
                'specific_department_id': role.specific_department_id.id if role else False,
                'job_id': role.job_id.id if role else False,
                'group_id': role.group_id.id if role else False,
                'user_ids': role.user_ids.ids if role else [],
                'record_field': role.record_field if role else '',
                'expression': role.expression if role else '',
                'matrix_id': role.matrix_id.id if role else False,
                'decision_id': role.decision_id.id if role else False,
                # business_rule / 閘道 DMN
                'dmn_decision_id': cfg.dmn_decision_id.id or False,
                'dmn_write_to_record': cfg.dmn_write_to_record,
                # gateway 出線（含目標名稱）+ 已存條件
                'outgoing': [
                    {'target_id': t, 'target_name': names.get(t, t),
                     'rows': fconds.get(t, [])}
                    for t in outgoing.get(eid, [])
                ],
            })
        return {
            'process': {
                'id': self.id, 'name': self.name, 'state': self.state,
                'capability_level': self.capability_level, 'xml': xml or '',
            },
            'nodes': nodes,
            'walk_order': walk_order,
            'enabled_features': sorted(self.env.company._bpmn_enabled_features()),
            'options': {
                'resolver_types': self._selection_options('bpmn.role', 'resolver_type'),
                'approval_modes': self._selection_options('bpmn.node.config', 'approval_mode'),
                'gate_timings': self._selection_options('bpmn.node.config', 'gate_timing'),
                'sla_actions': self._selection_options('bpmn.node.config', 'sla_action'),
                'operators': [
                    ['=', '等於'], ['!=', '不等於'], ['>', '大於'], ['>=', '大於等於'],
                    ['<', '小於'], ['<=', '小於等於'], ['in', '屬於'], ['set', '已設定'],
                ],
                'departments': self._name_options('hr.department'),
                'jobs': self._name_options('hr.job'),
                'groups': self._name_options('res.groups'),
                'users': self._name_options('res.users'),
                'models': self._name_options('ir.model', field='model', limit=1000),
                'matrices': self._name_options('bpmn.authority.matrix'),
                'decisions': [
                    {'id': d.id, 'name': '%s / %s' % (
                        d.definitions_id.name or '', d.name or d.dmn_id)}
                    for d in self.env['dmn.decision'].search(
                        [('definitions_id.company_id', 'in',
                          [self.env.company.id, False])], limit=500)
                ],
            },
        }

    def _parse_flows(self, xml):
        """回傳 (outgoing{src:[target...]}, walk_order[元素id...], names{id:name})。"""
        outgoing, names = {}, {}
        start_id = None
        if not xml:
            return outgoing, [], names
        try:
            root = etree.fromstring(xml.encode('utf-8') if isinstance(xml, str) else xml)
        except Exception:  # noqa: BLE001
            return outgoing, [], names
        flows = []
        for el in root.iter():
            tag = etree.QName(el).localname
            if el.get('id'):
                names[el.get('id')] = el.get('name') or el.get('id')
            if tag == 'sequenceFlow':
                s, t = el.get('sourceRef'), el.get('targetRef')
                if s and t:
                    flows.append((s, t))
                    outgoing.setdefault(s, []).append(t)
            elif tag == 'startEvent' and not start_id:
                start_id = el.get('id')
        # walk_order：自 start 沿第一條出線線性走訪（best-effort）
        walk, seen = [], set()
        cur = start_id
        while cur and cur not in seen:
            walk.append(cur)
            seen.add(cur)
            nxts = outgoing.get(cur)
            cur = nxts[0] if nxts else None
        return outgoing, walk, names

    @api.model
    def _name_options(self, model, field=None, limit=500):
        recs = self.env[model].search([], limit=limit)
        out = []
        for r in recs:
            label = r[field] if field and field in r._fields else r.display_name
            out.append({'id': r.id, 'name': label})
        return out

    # ------------------------------------------------------------------
    # 儲存單一節點設定（overlay + 角色）
    # ------------------------------------------------------------------
    _CONFIG_KEYS = ('approval_mode', 'allow_escalation', 'gate_timing',
                    'gate_model_id', 'gate_method', 'gate_condition',
                    'flow_conditions', 'sla_hours', 'sla_action',
                    'dmn_decision_id', 'dmn_write_to_record')
    _ROLE_KEYS = ('resolver_type', 'level', 'specific_department_id', 'job_id',
                  'group_id', 'user_ids', 'record_field', 'expression', 'matrix_id',
                  'decision_id')

    def set_node_config(self, element_id, vals):
        self.ensure_one()
        cfg = self.node_config_ids.filtered(
            lambda c: c.bpmn_element_id == element_id)
        if not cfg:
            cfg = self.env['bpmn.node.config'].create({
                'process_id': self.id,
                'bpmn_element_id': element_id,
                'name': vals.get('name') or element_id,
                'node_type': vals.get('node_type') or 'user_task',
            })
        cfg = cfg[:1]

        config_vals = {k: vals[k] for k in self._CONFIG_KEYS if k in vals}
        if config_vals:
            cfg.write(config_vals)

        role_vals = {k: vals[k] for k in self._ROLE_KEYS if k in vals}
        if role_vals and role_vals.get('resolver_type'):
            if 'user_ids' in role_vals:
                role_vals['user_ids'] = [Command.set(role_vals['user_ids'] or [])]
            role = cfg.role_id
            if not role:
                role = self.env['bpmn.role'].create({
                    'process_id': self.id,
                    'name': cfg.name or element_id,
                    **role_vals,
                })
                cfg.role_id = role.id
            else:
                role.write(role_vals)
        return True

    def save_xml(self, xml):
        """把編輯器 modeler 目前的 BPMN XML 存回（結構編輯持久化）。

        讓 dobtor_approval 能獨立設計流程結構（增刪節點/連線），而非只覆蓋設定。
        僅草稿可改；存回後同步 node_config（補建新節點、移除已刪節點）。
        """
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('流程「%s」非草稿狀態，不可修改結構。', self.name))
        xml = xml or ''
        if xml:
            # 先驗證 well-formed：畸形 XML 於此擲錯，避免先寫入壞值再失敗
            self._parse_xml(xml)
        self.xml = xml
        if xml:
            self._sync_node_configs_from_xml(xml)
        return True

    # ------------------------------------------------------------------
    # L1 簡易精靈：由設定產生線性簽核流程（自寫 OWL 前端呼叫）
    # ------------------------------------------------------------------
    _TIER_ORDER = ['T0', 'T1', 'T2', 'T3', 'T4', 'T5', 'T6']

    @api.model
    def generate_from_wizard(self, payload):
        """由精靈 payload 產生一條線性簽核流程，回傳開啟其編輯器的 action。

        payload = {
            'name': str,
            'steps': [{label, resolver, level, job_id, user_ids[], mode, escalate}],
            'advanced': {model_id, method, sla_hours, sla_action},
        }
        """
        name = (payload.get('name') or '').strip()
        if not name:
            raise UserError(_('請輸入流程名稱。'))
        steps = payload.get('steps') or []
        if not steps:
            raise UserError(_('請至少新增一個簽核關卡。'))
        adv = payload.get('advanced') or {}

        # 1) 產生線性 BPMN XML（含 DI 版面）
        xml, task_ids = self._wizard_build_xml(steps)

        # 2) 能力上限：依選項推算所需最高 tier
        cap = 'T0'
        for s in steps:
            if s.get('mode') in ('all', 'sequential'):
                cap = self._max_tier(cap, 'T1')
            if s.get('escalate'):
                cap = self._max_tier(cap, 'T3')

        # 3) 建流程 + 同步 node_config（建立 start/end/usertask 列）
        process = self.create({'name': name, 'xml': xml, 'capability_level': cap})
        process._sync_node_configs_from_xml(xml)

        # 4) 逐關設定 role + node_config
        sla_hours = adv.get('sla_hours') or 0.0
        sla_action = adv.get('sla_action') or False
        for idx, (s, task_id) in enumerate(zip(steps, task_ids)):
            role = self.env['bpmn.role'].create(self._wizard_role_vals(process, s, idx))
            cfg = process.node_config_ids.filtered(
                lambda c: c.bpmn_element_id == task_id)[:1]
            vals = {
                'role_id': role.id,
                'approval_mode': s.get('mode') or 'any',
                'allow_escalation': bool(s.get('escalate')),
            }
            # 僅在有設期限時才寫 SLA（sla_action 須為合法 selection 值）
            if sla_hours > 0:
                vals['sla_hours'] = sla_hours
                if sla_action:
                    vals['sla_action'] = sla_action
            cfg.write(vals)

        # 5) 綁定單據（選填）：前端傳模型技術名，後端解析成 ir.model
        if adv.get('model') and adv.get('method'):
            imodel = self.env['ir.model'].search(
                [('model', '=', adv['model'])], limit=1)
            if not imodel:
                raise UserError(_('找不到模型「%s」，請確認技術名稱。', adv['model']))
            self.env['bpmn.action.gate'].create({
                'name': name,
                'process_id': process.id,
                'model_id': imodel.id,
                'method_name': adv['method'],
            })

        # 6) 直接開啟簽核設定編輯器，立即可微調 / 發佈
        return process.action_open_process_editor()

    @api.model
    def _max_tier(self, a, b):
        return a if self._TIER_ORDER.index(a) >= self._TIER_ORDER.index(b) else b

    @api.model
    def preview_wizard_approvers(self, step, applicant_id):
        """精靈內「誰會簽」dry-run：給單一關卡設定 + 申請人，回傳簽核人姓名清單。
        重用 bpmn.role 的解析邏輯（以 NewId 暫存記錄，不落地）。"""
        rtype = step.get('resolver') or 'direct_manager'
        if rtype == 'specific_user':
            users = self.env['res.users'].browse(step.get('user_ids') or [])
            return users.mapped('name')
        if not applicant_id:
            return []
        role = self.env['bpmn.role'].new({
            'name': 'preview',
            'resolver_type': rtype,
            'level': max(1, int(step.get('level') or 1)),
            'job_id': step.get('job_id') or False,
            'apply_substitute': False,
        })
        instance = self.env['bpmn.process.instance'].new({
            'applicant_user_id': applicant_id,
        })
        try:
            return role.resolve(instance).mapped('name')
        except Exception:  # noqa: BLE001 — 預覽不可中斷 UI
            return []

    def _wizard_role_vals(self, process, step, idx):
        rtype = step.get('resolver') or 'direct_manager'
        vals = {
            'process_id': process.id,
            'name': step.get('label') or _('第 %s 關', idx + 1),
            'sequence': (idx + 1) * 10,
            'resolver_type': rtype,
        }
        if rtype == 'manager_level':
            vals['level'] = max(1, int(step.get('level') or 1))
        elif rtype == 'job_position':
            vals['job_id'] = step.get('job_id') or False
        elif rtype == 'specific_user':
            vals['user_ids'] = [Command.set(step.get('user_ids') or [])]
        return vals

    @api.model
    def _wizard_build_xml(self, steps):
        """組出線性 BPMN（Start → UserTask×N → End）+ DI 版面。
        回傳 (xml, task_ids)。"""
        n = len(steps)
        start_id = 'StartEvent_1'
        end_id = 'Event_end'
        task_ids = ['Activity_%d' % (i + 1) for i in range(n)]
        order = [start_id] + task_ids + [end_id]
        flow_ids = ['Flow_%d' % (i + 1) for i in range(len(order) - 1)]

        # bounds: {id: (x, y, w, h)}；由左而右排版，垂直置中於 y_center
        y_center = 140
        bounds = {}
        x = 150
        bounds[start_id] = (x, y_center - 18, 36, 36)
        x += 36 + 70
        for tid in task_ids:
            bounds[tid] = (x, y_center - 40, 110, 80)
            x += 110 + 70
        bounds[end_id] = (x, y_center - 18, 36, 36)

        def incoming_outgoing(node):
            i = order.index(node)
            inc = flow_ids[i - 1] if i > 0 else None
            out = flow_ids[i] if i < len(flow_ids) else None
            return inc, out

        # ---- process 元素 ----
        pe = []
        inc, out = incoming_outgoing(start_id)
        pe.append('    <bpmn:startEvent id="%s" name="申請">' % start_id)
        pe.append('      <bpmn:outgoing>%s</bpmn:outgoing>' % out)
        pe.append('    </bpmn:startEvent>')
        for i, tid in enumerate(task_ids):
            inc, out = incoming_outgoing(tid)
            label = steps[i].get('label') or (_('第%s關') % (i + 1))
            pe.append('    <bpmn:userTask id="%s" name=%s>' % (tid, quoteattr(label)))
            pe.append('      <bpmn:incoming>%s</bpmn:incoming>' % inc)
            pe.append('      <bpmn:outgoing>%s</bpmn:outgoing>' % out)
            pe.append('    </bpmn:userTask>')
        inc, out = incoming_outgoing(end_id)
        pe.append('    <bpmn:endEvent id="%s" name="完成">' % end_id)
        pe.append('      <bpmn:incoming>%s</bpmn:incoming>' % inc)
        pe.append('    </bpmn:endEvent>')
        for i, fid in enumerate(flow_ids):
            pe.append('    <bpmn:sequenceFlow id="%s" sourceRef="%s" targetRef="%s"/>'
                      % (fid, order[i], order[i + 1]))

        # ---- DI 圖形 ----
        di = []
        for eid, (bx, by, bw, bh) in bounds.items():
            di.append('      <bpmndi:BPMNShape id="%s_di" bpmnElement="%s">' % (eid, eid))
            di.append('        <dc:Bounds x="%d" y="%d" width="%d" height="%d"/>'
                      % (bx, by, bw, bh))
            di.append('      </bpmndi:BPMNShape>')
        for i, fid in enumerate(flow_ids):
            sx, sy, sw, sh = bounds[order[i]]
            tx, ty, tw, th = bounds[order[i + 1]]
            x1, y1 = sx + sw, sy + sh // 2
            x2, y2 = tx, ty + th // 2
            di.append('      <bpmndi:BPMNEdge id="%s_di" bpmnElement="%s">' % (fid, fid))
            di.append('        <di:waypoint x="%d" y="%d"/>' % (x1, y1))
            di.append('        <di:waypoint x="%d" y="%d"/>' % (x2, y2))
            di.append('      </bpmndi:BPMNEdge>')

        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"\n'
            '                  xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"\n'
            '                  xmlns:dc="http://www.omg.org/spec/DD/20100524/DC"\n'
            '                  xmlns:di="http://www.omg.org/spec/DD/20100524/DI"\n'
            '                  xmlns:odoo="http://www.dobtor.com/schema/bpmn/odoo"\n'
            '                  id="Definitions_wizard" targetNamespace="http://bpmn.io/schema/bpmn">\n'
            '  <bpmn:process id="Process_1" isExecutable="false">\n'
            + '\n'.join(pe) + '\n'
            '  </bpmn:process>\n'
            '  <bpmndi:BPMNDiagram id="BPMNDiagram_1">\n'
            '    <bpmndi:BPMNPlane id="BPMNPlane_1" bpmnElement="Process_1">\n'
            + '\n'.join(di) + '\n'
            '    </bpmndi:BPMNPlane>\n'
            '  </bpmndi:BPMNDiagram>\n'
            '</bpmn:definitions>'
        )
        return xml, task_ids

    # ------------------------------------------------------------------
    # dry-run：誰會簽
    # ------------------------------------------------------------------
    def preview_approvers(self, element_id, applicant_id):
        self.ensure_one()
        cfg = self.node_config_ids.filtered(
            lambda c: c.bpmn_element_id == element_id)[:1]
        if not cfg or not cfg.role_id:
            return []
        users = cfg.role_id.resolve_preview(applicant_id or False)
        return [{'id': u.id, 'name': u.name} for u in users]

    # ------------------------------------------------------------------
    # 掃描某模型可攔截的動作（form 按鈕 + server action + 白名單）
    # ------------------------------------------------------------------
    @api.model
    def scan_model_actions(self, model_name):
        """回傳可攔截的方法/按鈕清單 [{name, label, source}]，供 UI 下拉選取（取代手打方法名）。

        來源：① 預設 form（含繼承合併）的 type=object 按鈕 ② 該模型所有 form view 的 object 按鈕
        ③ 白名單中模型確實存在的方法。以 name 去重，有中文 string 優先。
        """
        if not model_name or model_name not in self.env:
            return []
        found = {}

        def _scan_arch(arch):
            try:
                root = etree.fromstring(arch.encode('utf-8'))
            except Exception:  # noqa: BLE001
                return
            for btn in root.iter('button'):
                name = btn.get('name')
                if btn.get('type') == 'object' and name and not name.startswith('%'):
                    label = btn.get('string') or btn.get('aria-label') or name
                    cur = found.get(name)
                    # 有中文/較長 label 的覆蓋純方法名
                    if not cur or (cur['label'] == name and label != name):
                        found[name] = {'name': name, 'label': label, 'source': 'button'}

        # ① 預設合併 form（含 inherit）
        try:
            _scan_arch(self.env[model_name].get_view(view_type='form')['arch'])
        except Exception:  # noqa: BLE001
            pass
        # ② 該模型所有 form view（特殊/次要視圖的按鈕）
        for view in self.env['ir.ui.view'].sudo().search(
                [('model', '=', model_name), ('type', '=', 'form')], limit=50):
            _scan_arch(view.arch or '')
        # ③ 白名單方法
        Model = self.env[model_name]
        for m in _METHOD_WHITELIST:
            if m not in found and hasattr(Model, m):
                found[m] = {'name': m, 'label': '%s（常用）' % m, 'source': 'whitelist'}
        return sorted(found.values(), key=lambda d: d['label'])
