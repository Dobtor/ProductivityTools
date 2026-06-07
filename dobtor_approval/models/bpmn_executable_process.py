# -*- coding: utf-8 -*-
"""可執行簽核流程 — DESIGN.md §3.1。

自身持有執行用 BPMN XML（forked）：可由 dobtor_bpmn 設計圖複製帶入後獨立增刪節點，
執行規格在 node_config_ids（overlay）。
action_publish() 解析 XML → 校驗 node/role → 守門能力開關 → 凍結版本。
"""
import json
import logging

from lxml import etree

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

from . import feature_registry as FR

_logger = logging.getLogger(__name__)

BPMN_NS = 'http://www.omg.org/spec/BPMN/20100524/MODEL'

# 從零新建流程的空白 BPMN 範本（含起始事件 + DI 版面），確保編輯器可開啟設計。
EMPTY_BPMN_XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"
                  xmlns:dc="http://www.omg.org/spec/DD/20100524/DC"
                  xmlns:odoo="http://www.dobtor.com/schema/bpmn/odoo"
                  id="Definitions_1"
                  targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="Process_1" isExecutable="false">
    <bpmn:startEvent id="StartEvent_1"/>
  </bpmn:process>
  <bpmndi:BPMNDiagram id="BPMNDiagram_1">
    <bpmndi:BPMNPlane id="BPMNPlane_1" bpmnElement="Process_1">
      <bpmndi:BPMNShape id="_BPMNShape_StartEvent_2" bpmnElement="StartEvent_1">
        <dc:Bounds x="173" y="102" width="36" height="36"/>
      </bpmndi:BPMNShape>
    </bpmndi:BPMNPlane>
  </bpmndi:BPMNDiagram>
</bpmn:definitions>"""

# 解析時 localname → node_config.node_type
_TAG_TO_NODE_TYPE = {
    'startEvent': 'start',
    'endEvent': 'end',
    'userTask': 'user_task',
    'serviceTask': 'service_task',
    'businessRuleTask': 'business_rule',
    'exclusiveGateway': 'exclusive_gw',
    'parallelGateway': 'parallel_gw',
    'inclusiveGateway': 'inclusive_gw',
}


class BpmnExecutableProcess(models.Model):
    _name = 'bpmn.executable.process'
    _description = '可執行簽核流程'
    _inherit = ['mail.thread']
    _order = 'name, id'

    name = fields.Char(string='流程名稱', required=True, tracking=True)
    code = fields.Char(string='流程代碼', help='攔截時可用代碼比對')
    active = fields.Boolean(default=True)

    xml = fields.Text(string='執行用 BPMN XML',
                      help='本流程自身的 BPMN XML（可由設計圖複製帶入後獨立編輯）')

    state = fields.Selection([
        ('draft', '草稿'),
        ('published', '已發佈'),
        ('archived', '封存'),
    ], string='狀態', default='draft', tracking=True)
    definition_version = fields.Integer(string='定義版本', default=0, readonly=True,
                                        tracking=True)
    capability_level = fields.Selection([
        ('T0', 'T0 入門'), ('T1', 'T1'), ('T2', 'T2'), ('T3', 'T3'),
        ('T4', 'T4'), ('T5', 'T5'), ('T6', 'T6'),
    ], string='能力上限', default='T0',
        help='本流程可使用的最高 Tier，不可超過公司全域已開的最高 Tier')

    node_config_ids = fields.One2many('bpmn.node.config', 'process_id',
                                      string='節點執行規格')
    role_ids = fields.One2many('bpmn.role', 'process_id', string='簽核角色')
    gate_ids = fields.One2many('bpmn.action.gate', 'process_id', string='Action 閘門')
    instance_ids = fields.One2many('bpmn.process.instance', 'process_id',
                                   string='流程實例')

    instance_count = fields.Integer(compute='_compute_instance_count',
                                    string='實例數')

    @api.model_create_multi
    def create(self, vals_list):
        # 從零新建的流程預設帶入空白 BPMN（含起始事件），確保編輯器可直接開啟設計。
        for vals in vals_list:
            if not vals.get('xml'):
                vals['xml'] = EMPTY_BPMN_XML
        return super().create(vals_list)

    @api.depends('instance_ids')
    def _compute_instance_count(self):
        data = self.env['bpmn.process.instance']._read_group(
            [('process_id', 'in', self.ids)], ['process_id'], ['__count'])
        mapping = {process.id: count for process, count in data}
        for rec in self:
            rec.instance_count = mapping.get(rec.id, 0)

    # ------------------------------------------------------------------
    # XML 來源
    # ------------------------------------------------------------------
    def _effective_xml(self):
        """回傳實際用於解析/執行的 XML。"""
        self.ensure_one()
        return self.xml or ''

    # ------------------------------------------------------------------
    # 發佈
    # ------------------------------------------------------------------
    def action_publish(self):
        for rec in self:
            xml = rec._effective_xml()
            if not xml:
                raise UserError(_('流程「%s」沒有可發佈的 BPMN XML。', rec.name))
            # 1) 解析並重建/校驗 node config
            rec._sync_node_configs_from_xml(xml)
            # 2) 結構校驗（必有 start / end、user_task 須綁角色）
            rec._validate_structure()
            # 3) 能力開關守門
            used = rec._scan_used_features()
            enabled = rec.env.company._bpmn_enabled_features()
            missing = used - enabled
            if missing:
                raise UserError(_(
                    "此流程用到尚未啟用的功能：%s。請先至『設定 → BPMN 簽核』開啟，"
                    "或移除這些元素。",
                    ", ".join(FR.FEATURE_LABELS.get(f, f) for f in sorted(missing))))
            # 4) 凍結版本
            rec.write({
                'state': 'published',
                'definition_version': rec.definition_version + 1,
            })
            rec.message_post(body=_('流程已發佈，版本 v%s。', rec.definition_version))
        return True

    def action_archive_process(self):
        self.write({'state': 'archived', 'active': False})
        return True

    def action_set_draft(self):
        self.write({'state': 'draft'})
        return True

    # ------------------------------------------------------------------
    # XML 解析
    # ------------------------------------------------------------------
    def _parse_xml(self, xml):
        """回傳 lxml root；失敗丟 UserError。"""
        try:
            return etree.fromstring(xml.encode('utf-8') if isinstance(xml, str) else xml)
        except etree.XMLSyntaxError as exc:
            raise UserError(_('BPMN XML 解析失敗：%s', exc))

    def _iter_elements(self, root):
        """yield (localname, element)。"""
        for el in root.iter():
            tag = etree.QName(el).localname
            yield tag, el

    def _sync_node_configs_from_xml(self, xml):
        """解析 XML 中的節點 → 建立/更新 bpmn.node.config（keyed by element id）。

        保留使用者已在 node_config 上手動設定的執行規格（role/mode/action）；
        僅補建缺漏節點、更新 name/node_type，不覆蓋人工欄位。
        """
        self.ensure_one()
        root = self._parse_xml(xml)
        existing = {c.bpmn_element_id: c for c in self.node_config_ids}
        seen = set()
        Config = self.env['bpmn.node.config']
        for tag, el in self._iter_elements(root):
            node_type = _TAG_TO_NODE_TYPE.get(tag)
            if not node_type:
                continue
            element_id = el.get('id')
            if not element_id:
                continue
            seen.add(element_id)
            name = el.get('name') or element_id
            if element_id in existing:
                cfg = existing[element_id]
                vals = {}
                if cfg.name != name:
                    vals['name'] = name
                if cfg.node_type != node_type:
                    vals['node_type'] = node_type
                if vals:
                    cfg.write(vals)
            else:
                Config.create({
                    'process_id': self.id,
                    'bpmn_element_id': element_id,
                    'name': name,
                    'node_type': node_type,
                })
        # 移除已不存在於 XML 的節點規格
        stale = self.node_config_ids.filtered(
            lambda c: c.bpmn_element_id not in seen)
        if stale:
            stale.unlink()

    def _scan_used_features(self):
        """回傳此流程用到的能力 key set（守門用）。

        - 結構性能力（閘道型別等）：由 XML 節點標籤判定。
        - 屬性性能力（會簽 cosign / 加簽 escalation）：由 node_config 判定——
          編輯器將節點設定存於 bpmn.node.config（非 XML odoo: 屬性），故以此為準。
        """
        self.ensure_one()
        used = set()
        xml = self._effective_xml()
        if xml:
            root = self._parse_xml(xml)
            for tag, el in self._iter_elements(root):
                feat = FR.NODE_FEATURE.get('bpmn:%s' % tag)
                if feat:
                    used.add(feat)
        for cfg in self.node_config_ids:
            if cfg.approval_mode in ('all', 'sequential'):
                used.add('cosign')
            if cfg.allow_escalation:
                used.add('escalation')
            # 閘道綁 DMN 決策 → 需要決策表能力（business_rule 由 XML tag 掃描覆蓋）
            if cfg.dmn_decision_id and cfg.node_type in (
                    'exclusive_gw', 'inclusive_gw'):
                used.add('dmn_decision_table')
        # 簽核人解析方式 → 進階解析能力（field_on_record / expression）
        for role in self.role_ids:
            feat = FR.RESOLVER_FEATURE.get(role.resolver_type)
            if feat:
                used.add(feat)
        return used

    def _validate_structure(self):
        """發佈前結構校驗。"""
        self.ensure_one()
        configs = self.node_config_ids
        if not configs.filtered(lambda c: c.node_type == 'start'):
            raise UserError(_('流程「%s」缺少開始節點。', self.name))
        if not configs.filtered(lambda c: c.node_type == 'end'):
            raise UserError(_('流程「%s」缺少結束節點。', self.name))
        for cfg in configs.filtered(lambda c: c.node_type == 'user_task'):
            if not cfg.role_id:
                raise UserError(_(
                    '簽核節點「%(node)s」尚未綁定簽核角色。',
                    node=cfg.name or cfg.bpmn_element_id))
            role = cfg.role_id
            if role.resolver_type == 'authority_matrix':
                if not role.matrix_id:
                    raise UserError(_(
                        '簽核節點「%(node)s」選了核決權限表但未綁定。',
                        node=cfg.name or cfg.bpmn_element_id))
                matrix_errs = role.matrix_id.validate_for_publish()
                if matrix_errs:
                    raise UserError('\n'.join(matrix_errs))
            if role.resolver_type == 'dmn_decision' and not role.decision_id:
                raise UserError(_(
                    '簽核節點「%(node)s」選了 DMN 決策但未綁定。',
                    node=cfg.name or cfg.bpmn_element_id))
        for cfg in configs.filtered(lambda c: c.node_type == 'service_task'):
            if not cfg.server_action_id and not cfg.bound_method:
                raise UserError(_(
                    '系統動作節點「%(node)s」尚未綁定 Server Action 或方法。',
                    node=cfg.name or cfg.bpmn_element_id))
        for cfg in configs.filtered(lambda c: c.node_type == 'business_rule'):
            if not cfg.dmn_decision_id:
                raise UserError(_(
                    '商業規則節點「%(node)s」尚未綁定 DMN 決策。',
                    node=cfg.name or cfg.bpmn_element_id))

    # ------------------------------------------------------------------
    # 圖結構查詢（給執行引擎用）
    # ------------------------------------------------------------------
    def _build_graph(self):
        """回傳 (nodes, flows)。
        nodes: {element_id: {'type': localname, 'name':...}}
        flows: list of {'id','source','target','condition'}
        """
        self.ensure_one()
        xml = self._effective_xml()
        if not xml:
            return {}, []
        root = self._parse_xml(xml)
        nodes = {}
        flows = []
        for tag, el in self._iter_elements(root):
            if tag == 'sequenceFlow':
                cond = None
                for child in el:
                    if etree.QName(child).localname == 'conditionExpression':
                        cond = (child.text or '').strip()
                flows.append({
                    'id': el.get('id'),
                    'source': el.get('sourceRef'),
                    'target': el.get('targetRef'),
                    'condition': cond,
                })
            elif tag in _TAG_TO_NODE_TYPE:
                nodes[el.get('id')] = {
                    'type': tag,
                    'name': el.get('name') or el.get('id'),
                    'node_type': _TAG_TO_NODE_TYPE[tag],
                }
        return nodes, flows

    def _start_element_id(self):
        nodes, _flows = self._build_graph()
        for eid, data in nodes.items():
            if data['node_type'] == 'start':
                return eid
        return False

    def _config_for(self, element_id):
        """取某 element 的執行規格（若無則回空 recordset）。"""
        self.ensure_one()
        return self.node_config_ids.filtered(
            lambda c: c.bpmn_element_id == element_id)[:1]

    # ------------------------------------------------------------------
    # 起實例
    # ------------------------------------------------------------------
    def start(self, res_model=False, res_id=False, applicant=False,
              pending_action=None):
        """建立並啟動一個流程實例。

        :param applicant: res.users，預設為當前使用者
        :param pending_action: dict {model, method, args}（Action 介入回放用）
        :return: bpmn.process.instance
        """
        self.ensure_one()
        if self.state != 'published':
            raise UserError(_('流程「%s」尚未發佈，無法啟動實例。', self.name))
        applicant = applicant or self.env.user
        instance = self.env['bpmn.process.instance'].create({
            'process_id': self.id,
            'definition_version': self.definition_version,
            'applicant_user_id': applicant.id,
            'res_model': res_model or False,
            'res_id': res_id or False,
            'state': 'running',
            'pending_action': json.dumps(pending_action) if pending_action else False,
        })
        instance._kickoff()
        return instance
