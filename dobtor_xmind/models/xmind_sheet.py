# -*- coding: utf-8 -*-
import uuid
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

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

    # ------------------------------------------------------------------
    # 分頁角色（主圖／子圖／發想）
    # ------------------------------------------------------------------
    # main：唯一一張，從它的中心主題往下同步成專案任務；
    # sub ：掛在某顆「錨點主題」底下的展開圖，同步時它的主題視為錨點的子任務；
    # idea：純發想，永遠不同步。
    sheet_role = fields.Selection([
        ('main', 'Main Sheet'),
        ('sub', 'Sub Sheet'),
        ('idea', 'Idea Sheet'),
    ], string='Sheet Role', default='idea', required=True)
    # 子圖的錨點（在主圖或上一層子圖裡的一顆主題）。restrict：錨點不可被直接刪掉，
    # 否則子圖會變成無主的孤兒 —— 要先刪子圖或解除錨點。
    anchor_topic_id = fields.Many2one(
        'xmind.topic', string='Anchor Topic', ondelete='restrict', index=True, copy=False)
    parent_sheet_id = fields.Many2one(
        'xmind.sheet', string='Parent Sheet', related='anchor_topic_id.sheet_id',
        store=True, readonly=True)

    _sql_constraints = [
        # 一顆主題最多展開一張子圖（NULL 不受 UNIQUE 限制，一般分頁不受影響）
        ('anchor_topic_uniq', 'unique(anchor_topic_id)',
         'A topic can be expanded into at most one sub sheet.'),
    ]

    #: 子圖最多幾層（主圖 → 子圖 1 → 子圖 2 → 子圖 3）
    _MAX_SUB_DEPTH = 3

    @api.model_create_multi
    def create(self, vals_list):
        # 工作簿的第一張分頁（或還沒有主圖時新建的那張）自動成為主圖；
        # 之後新增的分頁預設是發想頁。同一批建立多張時只給第一張。
        claimed = set()
        for vals in vals_list:
            wb_id = vals.get('workbook_id')
            if not wb_id or 'sheet_role' in vals or wb_id in claimed:
                continue
            has_main = self.with_context(active_test=False).search_count(
                [('workbook_id', '=', wb_id), ('sheet_role', '=', 'main')], limit=1)
            if not has_main:
                vals['sheet_role'] = 'main'
                claimed.add(wb_id)
        return super().create(vals_list)

    def unlink(self):
        to_delete = set(self.ids)
        # 1) 要刪的分頁裡若有主題是「別張（不在這次刪除範圍內）子圖」的錨點 → 擋下並說明
        dependents = self.search([
            ('anchor_topic_id.sheet_id', 'in', self.ids), ('id', 'not in', self.ids)])
        if dependents:
            raise UserError(_(
                'Sheet "%(sheet)s" contains the anchor topic of sub sheet "%(sub)s". '
                'Delete that sub sheet first.',
                sheet=dependents[0].parent_sheet_id.name, sub=dependents[0].name))
        # 2) 刪主圖：工作簿已同步過專案時不允許（主圖承載所有任務）；否則把下一張
        #    發想頁升為主圖，維持「每本工作簿恰好一張主圖」。
        promote = self.browse()
        for sheet in self.filtered(lambda s: s.sheet_role == 'main'):
            remaining = sheet.workbook_id.sheet_ids.filtered(lambda s: s.id not in to_delete)
            if not remaining:
                continue
            if sheet.workbook_id.project_locked:
                raise UserError(_(
                    'The main sheet of mind map "%(map)s" cannot be deleted: its topics are '
                    'synced with project tasks.', map=sheet.workbook_id.name))
            candidate = remaining.filtered(lambda s: s.sheet_role == 'idea').sorted(
                lambda s: (s.sequence, s.id))[:1]
            promote |= candidate
        # 3) 一起被刪的子圖：先清掉錨點（SQL，避開約束），否則 cascade 刪主題時
        #    會撞到 restrict 外鍵（同一個 DELETE 內的刪除順序不保證）。
        anchored = self.filtered('anchor_topic_id')
        if anchored:
            self.env.cr.execute(
                "UPDATE xmind_sheet SET anchor_topic_id = NULL, parent_sheet_id = NULL "
                "WHERE id IN %s", (tuple(anchored.ids),))
            anchored.invalidate_recordset(['anchor_topic_id', 'parent_sheet_id'])
        res = super().unlink()
        if promote:
            promote.with_context(_xmind_skip_role_check=True).write({'sheet_role': 'main'})
        return res

    @api.constrains('sheet_role', 'workbook_id', 'anchor_topic_id')
    def _check_sheet_role(self):
        if self.env.context.get('_xmind_skip_role_check'):
            return
        for workbook in self.mapped('workbook_id'):
            mains = workbook.sheet_ids.filtered(lambda s: s.sheet_role == 'main')
            if workbook.sheet_ids and len(mains) != 1:
                raise ValidationError(_(
                    'Mind map "%(map)s" must have exactly one main sheet.', map=workbook.name))
        for sheet in self:
            sheet._check_sheet_tree()

    def _check_sheet_tree(self):
        """子圖的錨點規則：同一本工作簿、不是中心主題、不成環、最多三層。"""
        for sheet in self:
            if sheet.sheet_role != 'sub':
                if sheet.anchor_topic_id:
                    raise ValidationError(_(
                        'Only sub sheets can have an anchor topic (sheet "%s").', sheet.name))
                continue
            anchor = sheet.anchor_topic_id
            if not anchor:
                raise ValidationError(_('Sub sheet "%s" needs an anchor topic.', sheet.name))
            if anchor.sheet_id.workbook_id != sheet.workbook_id:
                raise ValidationError(_(
                    'The anchor topic of sub sheet "%s" must belong to the same mind map.',
                    sheet.name))
            if not anchor.parent_id:
                raise ValidationError(_(
                    'A central topic cannot be expanded into a sub sheet (sheet "%s").',
                    sheet.name))
            depth = 0
            current = anchor.sheet_id
            seen = set()
            while current:
                if current == sheet or current.id in seen:
                    raise ValidationError(_(
                        'Sub sheet "%s" would create a cycle.', sheet.name))
                seen.add(current.id)
                depth += 1 if current.sheet_role == 'sub' else 0
                current = current.anchor_topic_id.sheet_id if current.sheet_role == 'sub' else False
            if depth + 1 > self._MAX_SUB_DEPTH:
                raise ValidationError(_(
                    'Sub sheets can be nested at most %(max)s levels (sheet "%(sheet)s").',
                    max=self._MAX_SUB_DEPTH, sheet=sheet.name))

    def _get_root_topic(self):
        """這張分頁的中心主題（沒有父主題的那顆；有多顆時取 sequence/id 最小者）。"""
        self.ensure_one()
        return self.env['xmind.topic'].search(
            [('sheet_id', '=', self.id), ('parent_id', '=', False)],
            order='sequence, id', limit=1)

    def _set_as_main(self):
        """把這張設為主圖、原主圖改為發想頁（一次完成，不會短暫違反「恰好一張」）。"""
        self.ensure_one()
        if self.sheet_role == 'main':
            return
        if self.workbook_id.project_locked:
            raise UserError(_(
                'The main sheet cannot be changed after the mind map was synced with a project.'))
        old = self.workbook_id.sheet_ids.filtered(lambda s: s.sheet_role == 'main')
        old.with_context(_xmind_skip_role_check=True).write({'sheet_role': 'idea'})
        self.write({'sheet_role': 'main', 'anchor_topic_id': False})

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
