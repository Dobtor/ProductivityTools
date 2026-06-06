import base64
import json

from odoo import _, fields, models
from odoo.exceptions import UserError


class BpmnDiagramImportWizard(models.TransientModel):
    _name = 'bpmn.diagram.import.wizard'
    _description = '匯入流程設計圖（多檔上傳）'

    files_json = fields.Text(
        string='檔案',
        help='由前端多檔上傳 widget 寫入的 JSON 陣列 [{name, data(base64)}]')
    diagram_type = fields.Selection([
        ('auto', '自動偵測'),
        ('bpmn', 'BPMN 流程圖'),
        ('dmn', 'DMN 決策表/DRD'),
    ], string='圖類型', default='auto', required=True)
    purpose = fields.Selection([
        ('documentation', '既有 Odoo 模組流程記錄 (as-is)'),
        ('blueprint', '客戶專案規格藍圖 (to-be，尚未實作)'),
        ('template', '可複用樣板'),
        ('executable_src', '供擴充模組衍生可執行流程的來源'),
    ], string='用途', default='documentation', required=True)
    category_id = fields.Many2one('bpmn.diagram.category', string='目錄/分類')
    tag_ids = fields.Many2many('bpmn.diagram.tag', string='標籤')

    def _detect_type(self, filename, content):
        """依副檔名或內容判斷 bpmn / dmn。"""
        fn = (filename or '').lower()
        if fn.endswith('.dmn'):
            return 'dmn'
        if fn.endswith('.bpmn'):
            return 'bpmn'
        low = (content or '').lower()
        # DMN 命名空間 / 元素特徵
        if 'spec/dmn' in low or 'dmndi' in low or '<decision' in low or 'decisiontable' in low:
            return 'dmn'
        return 'bpmn'

    def _strip_ext(self, name):
        for ext in ('.bpmn', '.dmn', '.xml'):
            if name.lower().endswith(ext):
                return name[:-len(ext)]
        return name

    def action_import(self):
        self.ensure_one()
        try:
            files = json.loads(self.files_json or '[]')
        except (ValueError, TypeError):
            files = []
        if not files:
            raise UserError(_('請至少選擇一個檔案。'))
        Diagram = self.env['bpmn.diagram']
        created = Diagram
        for f in files:
            name = f.get('name') or _('未命名')
            try:
                content = base64.b64decode(f.get('data') or '').decode(
                    'utf-8', errors='replace')
            except Exception:
                content = ''
            if self.diagram_type != 'auto':
                dtype = self.diagram_type
            else:
                dtype = self._detect_type(name, content)
            created |= Diagram.create({
                'name': self._strip_ext(name),
                'diagram_type': dtype,
                'xml': content or False,
                'purpose': self.purpose,
                'category_id': self.category_id.id or False,
                'tag_ids': [(6, 0, self.tag_ids.ids)],
            })
        return {
            'type': 'ir.actions.act_window',
            'name': _('已匯入的設計圖'),
            'res_model': 'bpmn.diagram',
            'view_mode': 'kanban,list,form',
            'domain': [('id', 'in', created.ids)],
        }
