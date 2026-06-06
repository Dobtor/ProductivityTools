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
        skipped = []          # 被略過的重複檔名
        seen_in_batch = set()  # 同批次重複偵測
        for f in files:
            raw_name = f.get('name') or _('未命名')
            name = self._strip_ext(raw_name)
            key = name.strip().lower()
            # 同批次重複，或與既有設計圖同名 → 略過
            if key in seen_in_batch or Diagram.search_count([('name', '=', name)]):
                skipped.append(raw_name)
                continue
            seen_in_batch.add(key)
            try:
                content = base64.b64decode(f.get('data') or '').decode(
                    'utf-8', errors='replace')
            except Exception:
                content = ''
            dtype = self.diagram_type if self.diagram_type != 'auto' \
                else self._detect_type(name, content)
            created |= Diagram.create({
                'name': name,
                'diagram_type': dtype,
                'xml': content or False,
                'purpose': self.purpose,
                'category_id': self.category_id.id or False,
                'tag_ids': [(6, 0, self.tag_ids.ids)],
            })

        # 後續動作：有匯入 → 導向清單；全部重複 → 關閉精靈
        if created:
            next_action = {
                'type': 'ir.actions.act_window',
                'name': _('已匯入的設計圖'),
                'res_model': 'bpmn.diagram',
                'view_mode': 'kanban,list,form',
                'domain': [('id', 'in', created.ids)],
            }
        else:
            next_action = {'type': 'ir.actions.act_window_close'}

        # 沒有任何重複 → 直接導向清單
        if not skipped:
            return next_action

        # 有重複 → 先提示被略過的檔名，再執行 next_action
        if created:
            message = _(
                '已匯入 %(ok)s 個；略過 %(n)s 個重複檔名：%(names)s',
                ok=len(created), n=len(skipped), names='、'.join(skipped))
        else:
            message = _(
                '全部 %(n)s 個檔名皆重複，未匯入：%(names)s',
                n=len(skipped), names='、'.join(skipped))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('匯入結果'),
                'message': message,
                'type': 'warning',
                'sticky': True,
                'next': next_action,
            },
        }
