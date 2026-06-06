import json
import logging

from lxml import etree

from odoo import _, api, models

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
                    'flow_conditions', 'sla_hours', 'sla_action')
    _ROLE_KEYS = ('resolver_type', 'level', 'specific_department_id', 'job_id',
                  'group_id', 'user_ids', 'record_field', 'expression')

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
                role_vals['user_ids'] = [(6, 0, role_vals['user_ids'] or [])]
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
        if not model_name or model_name not in self.env:
            return []
        found = {}
        # 1) form 按鈕 type=object
        try:
            arch = self.env[model_name].get_view(view_type='form')['arch']
            root = etree.fromstring(arch.encode('utf-8'))
            for btn in root.iter('button'):
                if btn.get('type') == 'object' and btn.get('name'):
                    found[btn.get('name')] = {
                        'name': btn.get('name'),
                        'label': btn.get('string') or btn.get('name'),
                        'source': 'button',
                    }
        except Exception:  # noqa: BLE001
            pass
        # 2) 白名單中模型確實有的方法
        Model = self.env[model_name]
        for m in _METHOD_WHITELIST:
            if m not in found and hasattr(Model, m):
                found[m] = {'name': m, 'label': m, 'source': 'whitelist'}
        return sorted(found.values(), key=lambda d: d['label'])
