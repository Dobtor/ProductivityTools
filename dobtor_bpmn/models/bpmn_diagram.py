from odoo import _, api, fields, models
from odoo.exceptions import UserError

# 空白 BPMN 2.0 圖（bpmn-js importXML 可直接開啟）
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

# 空白 DMN 1.3 決策（dmn-js 可直接開啟）
EMPTY_DMN_XML = """<?xml version="1.0" encoding="UTF-8"?>
<definitions xmlns="https://www.omg.org/spec/DMN/20191111/MODEL/"
             xmlns:dmndi="https://www.omg.org/spec/DMN/20191111/DMNDI/"
             xmlns:dc="http://www.omg.org/spec/DMN/20180521/DC/"
             id="Definitions_1" name="Definitions" namespace="http://camunda.org/schema/1.0/dmn">
  <decision id="Decision_1" name="決策">
    <decisionTable id="DecisionTable_1">
      <input id="Input_1" label="輸入">
        <inputExpression id="InputExpression_1" typeRef="string"><text></text></inputExpression>
      </input>
      <output id="Output_1" label="輸出" typeRef="string"/>
    </decisionTable>
  </decision>
  <dmndi:DMNDI>
    <dmndi:DMNDiagram>
      <dmndi:DMNShape dmnElementRef="Decision_1">
        <dc:Bounds height="80" width="180" x="160" y="100"/>
      </dmndi:DMNShape>
    </dmndi:DMNDiagram>
  </dmndi:DMNDI>
</definitions>"""


class BpmnDiagram(models.Model):
    _name = 'bpmn.diagram'
    _description = '流程設計圖（純設計，無執行語意）'
    _inherit = ['mail.thread']
    _order = 'name'

    name = fields.Char(required=True, tracking=True)
    code = fields.Char(string='代碼', copy=False)
    diagram_type = fields.Selection(
        [('bpmn', 'BPMN 流程圖'), ('dmn', 'DMN 決策表/DRD')],
        string='圖類型', required=True, default='bpmn', tracking=True)
    xml = fields.Text(string='設計 XML')
    svg = fields.Text(string='縮圖 SVG')
    version = fields.Integer(string='版本', default=1, readonly=True, copy=False)
    state = fields.Selection(
        [('draft', '草稿'), ('reviewed', '已審閱'), ('frozen', '定版')],
        string='狀態', default='draft', required=True, tracking=True, copy=False)

    # 用途分類（三大使用情境）
    purpose = fields.Selection([
        ('documentation', '既有 Odoo 模組流程記錄 (as-is)'),
        ('blueprint', '客戶專案規格藍圖 (to-be，尚未實作)'),
        ('template', '可複用樣板'),
        ('executable_src', '供擴充模組衍生可執行流程的來源'),
    ], string='用途', default='documentation', required=True, index=True, tracking=True)

    category_id = fields.Many2one('bpmn.diagram.category', string='分類')
    project_ref = fields.Char(string='關聯專案/客戶', help='blueprint 用')
    odoo_module = fields.Char(string='關聯 Odoo 模組技術名', help='documentation 用，如 sale')
    tag_ids = fields.Many2many('bpmn.diagram.tag', string='標籤')
    active = fields.Boolean(default=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('xml'):
                vals['xml'] = self._default_xml(vals.get('diagram_type', 'bpmn'))
        return super().create(vals_list)

    @api.model
    def _default_xml(self, diagram_type):
        return EMPTY_DMN_XML if diagram_type == 'dmn' else EMPTY_BPMN_XML

    @api.onchange('diagram_type')
    def _onchange_diagram_type(self):
        # 切換類型且 XML 仍為空/預設時，套用對應空白範本
        if not self.xml or self.xml in (EMPTY_BPMN_XML, EMPTY_DMN_XML):
            self.xml = self._default_xml(self.diagram_type)

    # ---- 對外 API（給擴充模組 dobtor_approval 使用）----
    def get_xml(self):
        """取得設計 XML（單筆）。"""
        self.ensure_one()
        return self.xml or self._default_xml(self.diagram_type)

    def clone_for_extension(self, target_model=None):
        """衍生一份副本給擴充模組（forked 模式）。回傳新的 bpmn.diagram record。"""
        self.ensure_one()
        copy = self.copy({
            'name': _('%s (副本)', self.name),
            'state': 'draft',
            'version': 1,
        })
        return copy

    def action_freeze(self):
        """定版：凍結設計，狀態轉 frozen。"""
        for diagram in self:
            if diagram.state == 'frozen':
                continue
            diagram.write({'state': 'frozen'})
        return True

    def action_open_editor(self):
        """開啟全螢幕視覺編輯器（client action，非 form notebook 內嵌）。"""
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'dobtor_bpmn.bpmn_editor',
            'name': self.name or _('流程設計圖'),
            'params': {
                'diagram_id': self.id,
            },
            'target': 'current',
        }

    def action_set_draft(self):
        for diagram in self:
            diagram.write({'state': 'draft'})
        return True

    def action_bump_version(self):
        """手動升版（定版後要再改時）。"""
        for diagram in self:
            if diagram.state == 'frozen':
                raise UserError(_('已定版的設計圖請先「設為草稿」再升版。'))
            diagram.version += 1
        return True
