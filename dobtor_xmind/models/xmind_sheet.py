# -*- coding: utf-8 -*-
import uuid
from odoo import models, fields

from .xmind_digest import digest_payload


class XMindSheet(models.Model):
    _name = 'xmind.sheet'
    _description = 'Mind Map Sheet'
    _order = 'sequence, id'

    name = fields.Char('Sheet Name', required=True, default='Sheet 1')
    sequence = fields.Integer('Sequence', default=10)
    workbook_id = fields.Many2one('xmind.workbook', string='Workbook', ondelete='cascade', required=True)

    component_id = fields.Char('Component ID', default=lambda self: str(uuid.uuid4()))

    topic_ids = fields.One2many('xmind.topic', 'sheet_id', string='Topics')
    relationship_ids = fields.One2many('xmind.relationship', 'sheet_id', string='Relationships')
    boundary_ids = fields.One2many('xmind.boundary', 'sheet_id', string='Boundaries')
    summary_ids = fields.One2many('xmind.summary', 'sheet_id', string='Summaries')
    floating_topic_ids = fields.One2many('xmind.floating.topic', 'sheet_id', string='Floating Topics')

    # Layout settings
    layout_type = fields.Selection([
        ('map', '心智圖'),
        ('org_chart_down', '組織圖 (向下)'),
        ('org_chart_up', '組織圖 (向上)'),
        ('tree_right', '樹狀圖 (向右)'),
        ('tree_left', '樹狀圖 (向左)'),
        ('logic_right', '邏輯圖 (向右)'),
        ('logic_left', '邏輯圖 (向左)'),
        ('timeline_horizontal', '時間軸 - 水平'),
        ('timeline_vertical', '時間軸 - 垂直'),
        # 注意：_layoutFishbone(dir=-1)=fishbone_left 渲染為「頭向右」，dir=1=fishbone_right 渲染為「頭向左」
        ('fishbone_right', '魚骨圖 (頭向左)'),
        ('fishbone_left', '魚骨圖 (頭向右)'),
        # 注意：_layoutMatrixH 渲染為「直行」(欄)，_layoutMatrixV 渲染為「橫列」(列)
        ('matrix_vertical', '表格圖 (橫列)'),
        ('matrix_horizontal', '表格圖 (直行)'),
        ('matrix', '表格圖 (橫列)'),  # legacy alias → matrix_vertical
    ], string='Layout Type', default='map')

    # Theme
    theme = fields.Selection([
        ('default', 'Default'),
        ('primary', 'Primary'),
        ('warning', 'Warning'),
        ('danger', 'Danger'),
        ('success', 'Success'),
        ('info', 'Info'),
        ('greensea', 'Green Sea'),
        ('nephrite', 'Nephrite'),
        ('belizehole', 'Belize Hole'),
        ('wisteria', 'Wisteria'),
        ('asphalt', 'Asphalt'),
        ('orange', 'Orange'),
        ('pumpkin', 'Pumpkin'),
        ('pomegranate', 'Pomegranate'),
        ('clouds', 'Clouds'),
        ('asbestos', 'Asbestos'),
    ], string='Theme', default='primary')

    # Spacing (XMind 2 layout properties)
    spacing_major = fields.Integer('Major Spacing (H)', default=30,
                                   help='Horizontal space between parent and child nodes')
    spacing_minor = fields.Integer('Minor Spacing (V)', default=20,
                                   help='Vertical space between sibling nodes')
    line_corner = fields.Integer('Line Corner Radius', default=5,
                                 help='Corner radius for elbow connections')

    # Branch connection style
    branch_line_class = fields.Selection([
        ('straight', 'Straight'),
        ('roundedElbow', 'Rounded Elbow'),
        ('curve', 'Curve'),
        ('arrowedCurve', 'Arrowed Curve'),
    ], string='Branch Line Style', default='curve')

    # ------------------------------------------------------------------
    # 內容摘要（樂觀鎖）
    # ------------------------------------------------------------------
    #: 納入摘要的主題欄位（文字、樣式、專案連結）。★ 不含 expanded 與原始 sequence：
    #: 前者是檢視狀態；後者改用「同層名次」（見 _content_digest），這樣把 sequence
    #: 正規化（0..n-1）不會改變摘要。
    _DIGEST_TOPIC_FIELDS = [
        'component_id', 'parent_id', 'sequence', 'title', 'note', 'labels',
        'hyperlink', 'hyperlink_title', 'background_color', 'text_color',
        'font_size', 'font_weight', 'font_style', 'font_family', 'border_color',
        'border_width', 'shape', 'text_align', 'text_decoration', 'line_type',
        'line_color', 'line_width', 'line_style', 'numbering', 'structure_class',
        'right_number', 'is_summary_node', 'task_id', 'project_managed',
        'task_start_date', 'task_end_date', 'task_progress', 'task_assignee',
        'task_deadline_time',
    ]

    def _content_digest(self):
        """這張分頁目前內容的指紋（見 ``xmind_digest``）。

        ★ 以呼叫者的權限讀取（不 sudo）：能存檔的人必然讀得到這些資料。
        ★ 同層順序用 (sequence, id) 排出名次 —— ``child_ids`` 的資料庫順序是
          ``parent_path, sequence``，兄弟的 parent_path 各不相同，所以**不能**
          拿它當順序。
        ★ 一律用 search 而不是 ``self.xxx_ids``：存檔流程剛 unlink／create 過，
          One2many 快取在同一個交易內不可靠。
        """
        self.ensure_one()
        env = self.env
        rows = env['xmind.topic'].search_read(
            [('sheet_id', '=', self.id)], self._DIGEST_TOPIC_FIELDS, order='id')
        cid_of = {r['id']: (r['component_id'] or '#%s' % r['id']) for r in rows}
        siblings = {}
        for r in rows:
            siblings.setdefault(r['parent_id'][0] if r['parent_id'] else 0, []).append(r)
        rank = {}
        for group in siblings.values():
            for index, r in enumerate(sorted(group, key=lambda x: (x['sequence'] or 0, x['id']))):
                rank[r['id']] = index

        topic_ids = [r['id'] for r in rows]
        markers, attachments = {}, {}
        if topic_ids:
            for m in env['xmind.topic.marker'].search_read(
                    [('topic_id', 'in', topic_ids)], ['topic_id', 'marker_id']):
                markers.setdefault(m['topic_id'][0], []).append(
                    m['marker_id'][1] if m['marker_id'] else '')
            for a in env['xmind.attachment'].search_read(
                    [('topic_id', 'in', topic_ids)], ['topic_id', 'name', 'attachment_type']):
                attachments.setdefault(a['topic_id'][0], []).append(
                    '%s|%s' % (a['attachment_type'], a['name']))

        topics = []
        for r in rows:
            row = {k: v for k, v in r.items()
                   if k not in ('id', 'parent_id', 'sequence', 'component_id', 'task_id')}
            row['cid'] = cid_of[r['id']]
            row['parent'] = cid_of.get(r['parent_id'][0], '') if r['parent_id'] else ''
            row['rank'] = rank[r['id']]
            row['task'] = r['task_id'][0] if r['task_id'] else 0
            row['markers'] = sorted(markers.get(r['id'], []))
            row['attachments'] = sorted(attachments.get(r['id'], []))
            topics.append(row)
        topics.sort(key=lambda x: x['cid'])

        def cids(records):
            return sorted(cid_of.get(t.id, '#%s' % t.id) for t in records)

        Domain = [('sheet_id', '=', self.id)]
        feature = {
            'relationships': sorted(
                [cid_of.get(r.source_topic_id.id, ''), cid_of.get(r.target_topic_id.id, ''),
                 r.title or '', r.line_type or '', r.line_style or '', r.line_color or '',
                 r.line_width, r.arrow_begin or '', r.arrow_end or '', r.arrow_size or '']
                for r in env['xmind.relationship'].search(Domain)),
            'boundaries': sorted(
                [cids(b.topic_ids), b.title or '', b.shape or '', b.fill_color or '',
                 b.border_color or '', b.border_width, b.border_style or '']
                for b in env['xmind.boundary'].search(Domain)),
            'summaries': sorted(
                [cids(s.topic_ids),
                 cid_of.get(s.summary_topic_id.id, '') if s.summary_topic_id else '',
                 s.title or '', s.line_type or '', s.line_color or '', s.line_width,
                 s.fill_color or '', s.text_color or '', s.font_size]
                for s in env['xmind.summary'].search(Domain)),
            'callouts': sorted(
                [cid_of.get(c.topic_id.id, ''), c.title or '', c.note or '',
                 c.background_color or '', c.border_color or '', c.shape or '']
                for c in env['xmind.callout'].search([('topic_id', 'in', topic_ids)])),
            'floating': sorted(
                [f.component_id or '', f.title or '', f.note or '', f.background_color or '',
                 f.text_color or '', f.font_size, f.font_weight or '']
                for f in env['xmind.floating.topic'].search(Domain)),
        }
        return digest_payload({'topics': topics, 'features': feature})

    def _touch_for_lock(self):
        """取得這張分頁的列鎖（見 ``save_mindmap_data`` 的說明）。"""
        self.ensure_one()
        self.env.cr.execute(
            "UPDATE xmind_sheet SET write_date = (now() AT TIME ZONE 'UTC') WHERE id = %s",
            (self.id,))
        self.invalidate_recordset(['write_date'])
