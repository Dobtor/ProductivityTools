# -*- coding: utf-8 -*-
"""可執行簽核流程 — DESIGN_MODULE_SPLIT.md §3.2、DESIGN.md §3.1。

疊在 dobtor_bpmn 的純設計圖之上的「執行規格」。
- linked：結構即時讀來源設計圖 XML，執行規格在 node_config_ids（overlay）。
- forked：複製來源 XML 到自身 xml，可獨立增刪節點。
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
ODOO_NS = 'http://dobtor.com/schema/bpmn/odoo'

# 解析時 localname → node_config.node_type
_TAG_TO_NODE_TYPE = {
    'startEvent': 'start',
    'endEvent': 'end',
    'userTask': 'user_task',
    'serviceTask': 'service_task',
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

    source_diagram_id = fields.Many2one(
        'bpmn.diagram', string='來源設計圖', ondelete='restrict',
        help='對應 dobtor_bpmn 的純設計圖')
    link_mode = fields.Selection([
        ('linked', '連動：追蹤來源設計（不可改結構，只加執行規格）'),
        ('forked', '分支：複製來源後獨立延伸（可增刪節點）'),
    ], string='延伸模式', default='forked', required=True)

    xml = fields.Text(string='執行用 BPMN XML',
                      help='forked 模式存自身 XML；linked 模式渲染時合併來源')

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

    @api.depends('instance_ids')
    def _compute_instance_count(self):
        data = self.env['bpmn.process.instance'].read_group(
            [('process_id', 'in', self.ids)], ['process_id'], ['process_id'])
        mapping = {d['process_id'][0]: d['process_id_count'] for d in data}
        for rec in self:
            rec.instance_count = mapping.get(rec.id, 0)

    # ------------------------------------------------------------------
    # XML 來源（linked vs forked）
    # ------------------------------------------------------------------
    def _effective_xml(self):
        """回傳實際用於解析/執行的 XML。"""
        self.ensure_one()
        if self.link_mode == 'linked' and self.source_diagram_id:
            return self.source_diagram_id.get_xml()
        return self.xml or (self.source_diagram_id.get_xml()
                            if self.source_diagram_id else '')

    def action_pull_from_source(self):
        """從來源設計圖重新拉取結構。"""
        for rec in self:
            if not rec.source_diagram_id:
                raise UserError(_('流程「%s」未設定來源設計圖。', rec.name))
            src_xml = rec.source_diagram_id.get_xml()
            if rec.link_mode == 'forked':
                rec.xml = src_xml
            # linked 模式不存 xml，渲染時即時讀
            rec._sync_node_configs_from_xml(src_xml)
        return True

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

    def _odoo_attr(self, el, name):
        """讀 odoo: 命名空間屬性（同時容忍無命名空間前綴）。"""
        val = el.get('{%s}%s' % (ODOO_NS, name))
        if val is None:
            val = el.get('odoo:%s' % name)
        return val

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
        """解析 XML，回傳此流程用到的能力 key set（守門用）。"""
        self.ensure_one()
        xml = self._effective_xml()
        if not xml:
            return set()
        root = self._parse_xml(xml)
        used = set()
        for tag, el in self._iter_elements(root):
            qname = 'bpmn:%s' % tag
            feat = FR.NODE_FEATURE.get(qname)
            if feat:
                used.add(feat)
            # 會簽 / 加簽屬性
            mode = self._odoo_attr(el, 'approvalMode')
            if mode in ('all', 'sequential'):
                used.add('cosign')
            if self._odoo_attr(el, 'allowEscalation') in ('true', '1', 'True'):
                used.add('escalation')
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
        for cfg in configs.filtered(lambda c: c.node_type == 'service_task'):
            if not cfg.server_action_id and not cfg.bound_method:
                raise UserError(_(
                    '系統動作節點「%(node)s」尚未綁定 Server Action 或方法。',
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
        root = self._parse_xml(self._effective_xml())
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
