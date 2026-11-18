# -*- coding: utf-8 -*-
import uuid
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class XMindTopic(models.Model):
    _name = 'xmind.topic'
    _description = 'Mind Map Topic'
    _parent_name = 'parent_id'
    _parent_store = True
    _order = 'parent_path, sequence'

    name = fields.Char('Name', related='title', store=True)
    title = fields.Char('Title', required=True)
    sequence = fields.Integer('Sequence', default=10)

    sheet_id = fields.Many2one('xmind.sheet', string='Sheet', ondelete='cascade', required=True)
    component_id = fields.Char('Component ID', default=lambda self: str(uuid.uuid4()), index=True)

    # Hierarchy
    parent_id = fields.Many2one('xmind.topic', string='Parent Topic', ondelete='cascade', index=True)
    child_ids = fields.One2many('xmind.topic', 'parent_id', string='Child Topics')
    parent_path = fields.Char(index=True)

    # Display
    expanded = fields.Boolean('Expanded', default=True)

    # Content
    note = fields.Text('Note')
    labels = fields.Char('Labels (comma separated)')
    hyperlink = fields.Char('Hyperlink')
    hyperlink_title = fields.Char('Hyperlink Title')

    # Attachments
    attachment_ids = fields.One2many('xmind.attachment', 'topic_id', string='Attachments')
    has_attachment = fields.Boolean('Has Attachment', compute='_compute_has_attachment', store=True)
    has_note = fields.Boolean('Has Note', compute='_compute_has_note', store=True)
    has_hyperlink = fields.Boolean('Has Hyperlink', compute='_compute_has_hyperlink', store=True)

    @api.depends('attachment_ids')
    def _compute_has_attachment(self):
        for record in self:
            record.has_attachment = bool(record.attachment_ids)

    @api.depends('note')
    def _compute_has_note(self):
        for record in self:
            record.has_note = bool(record.note and record.note.strip())

    @api.depends('hyperlink')
    def _compute_has_hyperlink(self):
        for record in self:
            record.has_hyperlink = bool(record.hyperlink and record.hyperlink.strip())

    # Styling (XMind 2 features)
    background_color = fields.Char('Background Color')
    text_color = fields.Char('Text Color')
    font_size = fields.Integer('Font Size', default=14)
    font_weight = fields.Selection([
        ('normal', 'Normal'),
        ('bold', 'Bold'),
    ], string='Font Weight', default='normal')
    border_color = fields.Char('Border Color')
    border_width = fields.Integer('Border Width', default=1)
    shape = fields.Selection([
        ('rectangle', 'Rectangle'),
        ('rounded', 'Rounded Rectangle'),
        ('ellipse', 'Ellipse'),
        ('circle', 'Circle'),
        ('underline', 'Underline'),
        ('diamond', 'Diamond'),
        ('parallelogram', 'Parallelogram'),
        ('hexagon', 'Hexagon'),
        ('cloud', 'Cloud'),
        ('noBorder', 'No Border'),
        ('fishhead_left', 'Fishhead Left'),
        ('fishhead_right', 'Fishhead Right'),
        ('stroke', 'Stroke Circle'),
    ], string='Shape', default='rounded')
    font_family = fields.Char('Font Family')
    font_style = fields.Selection([
        ('normal', 'Normal'),
        ('italic', 'Italic'),
    ], string='Font Style', default='normal')
    text_decoration = fields.Char('Text Decoration')
    text_align = fields.Selection([
        ('left', 'Left'),
        ('center', 'Center'),
        ('right', 'Right'),
    ], string='Text Alignment', default='left')

    # Branch connection line style
    line_type = fields.Char('Connection Line Type')  # curved, straight, roundedElbow, angular, none
    line_color = fields.Char('Connection Line Color')
    line_width = fields.Integer('Connection Line Width', default=0)  # 0 = inherit from theme
    line_style = fields.Char('Connection Line Pattern')  # solid, dashed, dotted
    # True when the user deliberately picked a branch line type in the panel, so the
    # renderer honours it over the layout-mode default (even when chosen type == default).
    line_type_explicit = fields.Boolean('Line Type Explicitly Set', default=False)

    # Per-topic child numbering format (none / 1 / a / A / i / I / 1.1)
    numbering = fields.Char('Numbering Format')

    # Stable link to the project.task this topic syncs with (1:1, map ⇄ project).
    task_id = fields.Many2one('project.task', string='Project Task',
                              ondelete='set null', index=True, copy=False)
    # True once a topic was created/managed by a project→map sync. Survives the task
    # being deleted (which nulls task_id), so a re-sync can detect "its source task is
    # gone" and remove it (without affecting purely map-authored topics).
    project_managed = fields.Boolean('Managed by Project', default=False, copy=False)

    # Structure
    structure_class = fields.Char('Structure Class', default='')
    right_number = fields.Integer('Right Number', default=-2)  # -2=not set, -1=all right, N=first N go right
    is_summary_node = fields.Boolean('Is Summary Node', default=False)

    # Markers
    marker_ids = fields.One2many('xmind.topic.marker', 'topic_id', string='Markers')

    # Task Info (XMind 8 "Task Information")
    task_start_date = fields.Date('Task Start')
    task_end_date = fields.Date('Task End')
    task_progress = fields.Integer('Progress %', default=0)  # 0..100
    task_assignee = fields.Char('Assignee')
    # Optional time-of-day for the deadline ("HH:MM"); when empty the sync uses 17:00.
    task_deadline_time = fields.Char('Deadline Time')
    has_task = fields.Boolean('Has Task Info', compute='_compute_has_task', store=True)

    # 這顆主題展開成的子圖（xmind.sheet.anchor_topic_id 的反向，一對一）。
    sub_sheet_id = fields.Many2one(
        'xmind.sheet', string='Sub Sheet', compute='_compute_sub_sheet_id',
        inverse='_inverse_sub_sheet_id', search='_search_sub_sheet_id')

    # Computed fields
    level = fields.Integer('Level', compute='_compute_level', store=True)
    has_children = fields.Boolean('Has Children', compute='_compute_has_children', store=True)

    @api.depends('task_start_date', 'task_end_date', 'task_progress', 'task_assignee')
    def _compute_has_task(self):
        for record in self:
            record.has_task = bool(
                record.task_start_date or record.task_end_date
                or record.task_progress or record.task_assignee
            )

    def _compute_sub_sheet_id(self):
        subs = self.env['xmind.sheet'].search([('anchor_topic_id', 'in', self.ids)])
        by_anchor = {s.anchor_topic_id.id: s for s in subs}
        for record in self:
            record.sub_sheet_id = by_anchor.get(record.id, False)

    def _inverse_sub_sheet_id(self):
        Sheet = self.env['xmind.sheet']
        for record in self:
            current = Sheet.search([('anchor_topic_id', '=', record.id)])
            if current and current != record.sub_sheet_id:
                current.write({'sheet_role': 'idea', 'anchor_topic_id': False})
            if record.sub_sheet_id and record.sub_sheet_id.anchor_topic_id != record:
                record.sub_sheet_id.write({'sheet_role': 'sub', 'anchor_topic_id': record.id})

    def _search_sub_sheet_id(self, operator, value):
        Sheet = self.env['xmind.sheet']
        if operator in ('=', '!=') and not value:
            anchors = Sheet.search([('anchor_topic_id', '!=', False)]).anchor_topic_id.ids
            return [('id', 'not in' if operator == '=' else 'in', anchors)]
        return [('id', 'in', Sheet.search([('id', operator, value)]).anchor_topic_id.ids)]

    def _is_sub_sheet_proxy_root(self):
        """子圖的中心主題只是錨點的「代理」：標題與錨點同步、永遠不變成任務。

        設計取捨：每張分頁都有自己一列根主題（編輯器、摘要、存檔都以此為前提），
        若讓子圖直接沒有根、或根就是錨點那一列，會牽動整條載入／存檔路徑。
        所以保留這一列，但把它當成錨點的鏡像 —— 存子圖時根標題回寫錨點、
        改錨點標題時同步到子圖根（見 write），同步專案時跳過它。
        """
        self.ensure_one()
        return (not self.parent_id and self.sheet_id.sheet_role == 'sub'
                and bool(self.sheet_id.anchor_topic_id))

    def write(self, vals):
        res = super().write(vals)
        if 'title' in vals and not self.env.context.get('_syncing_name'):
            mirror = self.with_context(_syncing_name=True)
            for record in self:
                if not record.parent_id:
                    sheet = record.sheet_id
                    workbook = sheet.workbook_id
                    if not workbook:
                        continue
                    if sheet.sheet_role == 'sub' and sheet.anchor_topic_id:
                        # 子圖代理根 → 錨點
                        if sheet.anchor_topic_id.title != vals['title']:
                            sheet.anchor_topic_id.with_context(_syncing_name=True).write(
                                {'title': vals['title']})
                        continue
                    main = workbook._get_main_sheet()
                    if main and sheet == main:
                        workbook.with_context(_syncing_name=True).write(
                            {'name': vals['title']}
                        )
            # 錨點 → 子圖代理根
            subs = self.env['xmind.sheet'].search([('anchor_topic_id', 'in', self.ids)])
            for sub in subs:
                root = sub._get_root_topic()
                if root and root.title != sub.anchor_topic_id.title:
                    mirror.browse(root.id).write({'title': sub.anchor_topic_id.title})
        if 'sheet_id' in vals:
            # 主題被搬到別張分頁：它若是子圖的錨點，重新檢查子圖規則（成環／層數）
            subs = self.env['xmind.sheet'].search([('anchor_topic_id', 'in', self.ids)])
            subs._check_sheet_tree()
        return res

    def unlink(self):
        # 錨點是 restrict：先給看得懂的訊息，而不是資料庫的外鍵錯誤。
        # parent_id 是資料庫層 cascade，子孫不會經過這裡 —— 所以把整棵子樹一起查。
        subtree = self.search([('id', 'child_of', self.ids)])
        subs = self.env['xmind.sheet'].search([('anchor_topic_id', 'in', subtree.ids)])
        if subs:
            raise UserError(_(
                'Topic "%(topic)s" is expanded into sub sheet "%(sheet)s". '
                'Delete that sub sheet first.',
                topic=subs[0].anchor_topic_id.title, sheet=subs[0].name))
        return super().unlink()

    @api.depends('parent_path')
    def _compute_level(self):
        for record in self:
            if record.parent_path:
                record.level = record.parent_path.count('/') - 1
            else:
                record.level = 0

    @api.depends('child_ids')
    def _compute_has_children(self):
        for record in self:
            record.has_children = bool(record.child_ids)


class XMindTopicMarker(models.Model):
    _name = 'xmind.topic.marker'
    _description = 'Topic Marker Assignment'

    topic_id = fields.Many2one('xmind.topic', string='Topic', ondelete='cascade', required=True)
    marker_id = fields.Many2one('xmind.marker', string='Marker', ondelete='cascade', required=True)
