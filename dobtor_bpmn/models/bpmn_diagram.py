import base64
import logging
import xml.etree.ElementTree as ET

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


def _ln(tag):
    """取 XML 標籤 localname（去命名空間）。"""
    return tag.rsplit('}', 1)[-1]


def _esc(text):
    return (text or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def build_preview_svg(xml):
    """由 BPMN/DMN XML 的 DI（版面）資訊產生基本預覽 SVG。
    解析 BPMNShape/DMNShape 的 Bounds 與 BPMNEdge/DMNEdge 的 waypoint，
    依元素類型畫事件(圓)/閘道(菱形)/工作(圓角矩形)/其他(矩形)與連線。
    無 DI 或解析失敗回傳 False。"""
    if not xml:
        return False
    try:
        root = ET.fromstring(xml.encode('utf-8') if isinstance(xml, str) else xml)
    except Exception:
        return False

    id_type, id_name = {}, {}
    for el in root.iter():
        eid = el.get('id')
        if eid:
            id_type[eid] = _ln(el.tag)
            if el.get('name'):
                id_name[eid] = el.get('name')

    shapes, edges = [], []
    for el in root.iter():
        ln = _ln(el.tag)
        if ln in ('BPMNShape', 'DMNShape'):
            ref = el.get('bpmnElement') or el.get('dmnElementRef')
            bounds = next((c for c in el if _ln(c.tag) == 'Bounds'), None)
            if bounds is None:
                continue
            try:
                x = float(bounds.get('x', 0)); y = float(bounds.get('y', 0))
                w = float(bounds.get('width', 0)); h = float(bounds.get('height', 0))
            except (TypeError, ValueError):
                continue
            shapes.append((ref, x, y, w, h))
        elif ln in ('BPMNEdge', 'DMNEdge'):
            pts = []
            for c in el:
                if _ln(c.tag) == 'waypoint':
                    try:
                        pts.append((float(c.get('x', 0)), float(c.get('y', 0))))
                    except (TypeError, ValueError):
                        pass
            if len(pts) >= 2:
                edges.append(pts)

    if not shapes:
        return False

    # 邊界
    xs = [x for _r, x, _y, _w, _h in shapes] + [p[0] for e in edges for p in e]
    ys = [y for _r, _x, y, _w, _h in shapes] + [p[1] for e in edges for p in e]
    xe = [x + w for _r, x, _y, w, _h in shapes] + [p[0] for e in edges for p in e]
    ye = [y + h for _r, _x, y, _w, h in shapes] + [p[1] for e in edges for p in e]
    pad = 16
    minx, miny = min(xs) - pad, min(ys) - pad
    width = (max(xe) - minx) + pad
    height = (max(ye) - miny) + pad
    if width <= 0 or height <= 0:
        return False

    parts = []
    # 連線
    for pts in edges:
        d = ' '.join('%.1f,%.1f' % (px, py) for px, py in pts)
        parts.append(
            '<polyline points="%s" fill="none" stroke="#888" stroke-width="2" '
            'marker-end="url(#arrow)"/>' % d)
    # 形狀
    for ref, x, y, w, h in shapes:
        t = id_type.get(ref, '')
        cx, cy = x + w / 2, y + h / 2
        if 'Event' in t:
            r = min(w, h) / 2
            parts.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="#fff" '
                         'stroke="#22863a" stroke-width="2"/>' % (cx, cy, r))
        elif 'Gateway' in t:
            r = min(w, h) / 2
            pts = '%.1f,%.1f %.1f,%.1f %.1f,%.1f %.1f,%.1f' % (
                cx, cy - r, cx + r, cy, cx, cy + r, cx - r, cy)
            parts.append('<polygon points="%s" fill="#fff8e1" stroke="#b08800" '
                         'stroke-width="2"/>' % pts)
        elif any(k in t for k in ('Task', 'Activity', 'SubProcess', 'CallActivity')):
            parts.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="8" '
                         'fill="#e8f0fe" stroke="#1a73e8" stroke-width="2"/>'
                         % (x, y, w, h))
        else:
            parts.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" '
                         'fill="#f5f5f5" stroke="#9e9e9e" stroke-width="1.5"/>'
                         % (x, y, w, h))
        name = id_name.get(ref)
        if name:
            label = name if len(name) <= 18 else name[:17] + '…'
            parts.append('<text x="%.1f" y="%.1f" font-size="12" text-anchor="middle" '
                         'dominant-baseline="middle" fill="#333">%s</text>'
                         % (cx, cy, _esc(label)))

    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="%.1f %.1f %.1f %.1f" '
        'width="%.0f" height="%.0f" font-family="sans-serif">'
        '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" '
        'orient="auto"><path d="M0,0 L7,3 L0,6 z" fill="#888"/></marker></defs>'
        '<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="#ffffff"/>'
        '%s</svg>'
    ) % (minx, miny, width, height, min(width, 1200), min(height, 900),
         minx, miny, width, height, ''.join(parts))
    return svg

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
        ('executable_src', '供簽核引擎衍生可執行流程的來源'),
    ], string='用途', default='documentation', required=True, index=True, tracking=True)

    category_id = fields.Many2one('bpmn.diagram.category', string='分類')
    # 專案／客戶（可在視覺編輯器上方直接編輯，並供左側 search panel 依此瀏覽/篩選）
    project_id = fields.Many2one('project.project', string='專案', index=True, tracking=True)
    partner_id = fields.Many2one('res.partner', string='客戶', index=True, tracking=True)
    project_ref = fields.Char(string='關聯專案/客戶（文字）', help='blueprint 用；自由文字備註')
    odoo_module = fields.Char(string='關聯 Odoo 模組技術名', help='documentation 用，如 sale')
    tag_ids = fields.Many2many('bpmn.diagram.tag', string='標籤')
    active = fields.Boolean(default=True)

    # 嵌入關聯：哪些記錄（res_model,res_id）在其 HTML 欄位以 "/" 插入了本設計圖
    embed_ids = fields.One2many('bpmn.diagram.embed', 'diagram_id', string='嵌入於')

    # kanban 卡片預覽縮圖：由存檔時寫入的 svg 轉成 data URI（非儲存，隨 svg 變動）
    thumbnail = fields.Char(string='預覽縮圖', compute='_compute_thumbnail')

    @api.depends('svg')
    def _compute_thumbnail(self):
        for diagram in self:
            if diagram.svg:
                b64 = base64.b64encode(diagram.svg.encode('utf-8')).decode('ascii')
                diagram.thumbnail = 'data:image/svg+xml;base64,' + b64
            else:
                diagram.thumbnail = False

    # ---- 專案 → 客戶連動 ----
    # 規則：有專案時「客戶」＝專案的客戶（唯讀，專案客戶為空則一併清空）；
    #       無專案時「客戶」可自由選填。
    @api.onchange('project_id')
    def _onchange_project_id_partner(self):
        if self.project_id:
            self.partner_id = self.project_id.partner_id

    @api.model
    def _enforce_project_partner(self, vals):
        """設定專案時，強制客戶＝該專案的客戶（可能為空）。清除/未帶專案時不動客戶。"""
        if vals.get('project_id'):
            proj = self.env['project.project'].browse(vals['project_id'])
            vals['partner_id'] = proj.partner_id.id or False
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('xml'):
                vals['xml'] = self._default_xml(vals.get('diagram_type', 'bpmn'))
            self._enforce_project_partner(vals)
        return super().create(vals_list)

    def write(self, vals):
        self._enforce_project_partner(vals)
        return super().write(vals)

    @api.model
    def _default_xml(self, diagram_type):
        return EMPTY_DMN_XML if diagram_type == 'dmn' else EMPTY_BPMN_XML

    @api.onchange('diagram_type')
    def _onchange_diagram_type(self):
        # 切換類型且 XML 仍為空/預設時，套用對應空白範本
        if not self.xml or self.xml in (EMPTY_BPMN_XML, EMPTY_DMN_XML):
            self.xml = self._default_xml(self.diagram_type)

    # ---- 對外 API（handoff 至簽核引擎 dobtor_approval）----
    def get_xml(self):
        """取得設計 XML（單筆）。"""
        self.ensure_one()
        return self.xml or self._default_xml(self.diagram_type)

    def action_create_executable_process(self):
        """把本設計圖複製 XML，建立 dobtor_approval 的可執行簽核流程（forked），
        並開啟該流程表單。需安裝 dobtor_approval（本模組依賴它）。"""
        self.ensure_one()
        process = self.env['bpmn.executable.process'].create({
            'name': self.name or _('簽核流程'),
            'xml': self.get_xml(),
        })
        # 立即依 XML 同步節點執行規格，使流程一落地即有 node_config 列可設定，
        # 不必等使用者另外開編輯器或發佈才同步。
        process._sync_node_configs_from_xml(process.xml)
        return {
            'type': 'ir.actions.act_window',
            'name': _('簽核流程'),
            'res_model': 'bpmn.executable.process',
            'res_id': process.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_create_dmn_definition(self):
        """DMN 設計圖 → 複製 XML 建立 dobtor_approval 的可執行 DMN 決策集（forked），
        並開啟其決策編輯器。需安裝 dobtor_approval（本模組依賴它）。"""
        self.ensure_one()
        if self.diagram_type != 'dmn':
            raise UserError(_('僅 DMN 類型的設計圖可建立決策集。'))
        defn = self.env['dmn.definitions'].create({
            'name': self.name or _('DMN 決策集'),
            'dmn_xml': self.get_xml(),
        })
        # create 已觸發 _parse_dmn，決策集一落地即有 shadow 可設定/試算。
        return defn.action_open_editor()

    def action_freeze(self):
        """定版：凍結設計，狀態轉 frozen。"""
        for diagram in self:
            if diagram.state == 'frozen':
                continue
            diagram.write({'state': 'frozen'})
        return True

    def _ensure_preview_svg(self, force=False):
        """為缺少 svg（或 force）的設計圖，由 xml 產生基本預覽 svg。
        回傳實際更新的筆數。供 migration 與按鈕共用。"""
        updated = 0
        for diagram in self:
            if diagram.svg and not force:
                continue
            if not diagram.xml:
                continue
            try:
                svg = build_preview_svg(diagram.xml)
            except Exception:
                _logger.exception('產生預覽 svg 失敗 (id=%s)', diagram.id)
                svg = False
            if svg:
                diagram.svg = svg
                updated += 1
        return updated

    def action_regenerate_thumbnail(self):
        """由目前 XML 重新產生預覽縮圖（手動，會覆蓋現有 svg）。"""
        n = self._ensure_preview_svg(force=True)
        msg = _('已重新產生 %s 張預覽縮圖。', n) if n else _(
            '無法產生預覽：XML 缺少版面(DI)資訊或無內容。')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': _('預覽縮圖'), 'message': msg,
                       'type': 'success' if n else 'warning', 'sticky': False},
        }

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

    @api.model
    def action_new_and_open_editor(self):
        """建立一筆空白設計圖並「直接開啟編輯器」，跳過 form view。
        供 kanban 的 on_create 使用（點「新增」即進編輯器）。name 為 required
        且無 default，故在此帶預設名稱；xml 由 create() 依 diagram_type 補上。"""
        rec = self.create({'name': _('未命名流程設計圖')})
        return rec.action_open_editor()

    # ---- HTML 編輯器嵌入關聯（"/" 插入設計圖）----
    @api.model
    def register_embed(self, diagram_id, res_model, res_id):
        """Upsert the association between this diagram and a host record.

        Called by the HTML-editor embedded component when it mounts on a saved
        host record. Idempotent: does nothing if the pair already exists, so
        re-opening a record with an embedded diagram never duplicates rows.
        Requires read access to the diagram (embedding it is a read-level use).
        """
        if not diagram_id or not res_model or not res_id:
            return False
        diagram = self.browse(int(diagram_id))
        if not diagram.exists() or not diagram.has_access('read'):
            return False
        Embed = self.env['bpmn.diagram.embed'].sudo()
        exists = Embed.search_count([
            ('diagram_id', '=', diagram.id),
            ('res_model', '=', res_model),
            ('res_id', '=', int(res_id)),
        ])
        if not exists:
            Embed.create({
                'diagram_id': diagram.id,
                'res_model': res_model,
                'res_id': int(res_id),
            })
        return True

    def get_embed_names(self):
        """Return the display names of records embedding this diagram.

        Used by the editor's project bar to render "關聯物件：a、b、c".
        Deduplicated and stripped of dangling references (deleted records).
        """
        self.ensure_one()
        names = []
        seen = set()
        for embed in self.embed_ids:
            name = embed.res_name
            if name and name not in seen:
                seen.add(name)
                names.append(name)
        return names

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
