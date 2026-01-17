# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.tools import html2plaintext


class NoteNote(models.Model):
    """筆記本 - 個人筆記管理

    提供類似便利貼的筆記功能，支援：
    - 階段式看板管理
    - 標籤分類
    - 待辦整合
    - 封存機制
    """
    _name = 'note.note'
    _description = '筆記本'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'sequence, id desc'

    # ===== 基本欄位 =====
    name = fields.Text(
        string='筆記摘要',
        compute='_compute_name',
        store=True,
    )
    user_id = fields.Many2one(
        'res.users',
        string='擁有者',
        default=lambda self: self.env.uid,
        index=True,
    )
    memo = fields.Html(
        string='筆記內容',
    )
    sequence = fields.Integer(
        string='順序',
        default=0,
    )
    color = fields.Integer(
        string='顏色索引',
        default=0,
    )
    active = fields.Boolean(
        string='啟用',
        default=True,
        help="取消勾選可封存此筆記，封存後不會顯示在列表中。",
    )

    # ===== 階段欄位 =====
    stage_id = fields.Many2one(
        'note.stage',
        string='階段',
        compute='_compute_stage_id',
        inverse='_inverse_stage_id',
        store=True,
        default=lambda self: self._get_default_stage_id(),
        group_expand='_read_group_stage_ids',
    )
    stage_ids = fields.Many2many(
        'note.stage',
        'note_note_stage_rel',
        'note_id',
        'stage_id',
        string='用戶階段',
        default=lambda self: self._get_default_stage_id(),
    )

    # ===== 狀態欄位 =====
    open = fields.Boolean(
        string='開啟中',
        default=True,
    )
    date_done = fields.Date(
        string='完成日期',
    )

    # ===== 標籤欄位 =====
    tag_ids = fields.Many2many(
        'note.tag',
        'note_note_tag_rel',
        'note_id',
        'tag_id',
        string='標籤',
    )
    main_tag_id = fields.Many2one(
        'note.tag',
        string='主要標籤',
        compute='_compute_main_tag_id',
        store=True,
        help="筆記的第一個標籤，用於左側樹狀篩選面板。",
    )

    # ===== 待辦關聯欄位 =====
    activity_ids = fields.One2many(
        'mail.activity',
        'note_id',
        string='關聯待辦',
    )
    activity_count = fields.Integer(
        string='待辦數量',
        compute='_compute_activity_count',
    )
    active_activity_count = fields.Integer(
        string='進行中待辦',
        compute='_compute_activity_count',
    )

    # ===== 計算方法 =====
    @api.depends('memo')
    def _compute_name(self):
        """從筆記內容的第一行取得筆記名稱"""
        for note in self:
            text = html2plaintext(note.memo) if note.memo else ''
            note.name = text.strip().replace('*', '').split("\n")[0]

    @api.depends('tag_ids')
    def _compute_main_tag_id(self):
        """取得第一個標籤作為主要標籤"""
        for note in self:
            note.main_tag_id = note.tag_ids[:1]

    @api.depends('activity_ids', 'activity_ids.active')
    def _compute_activity_count(self):
        """計算關聯待辦數量"""
        for note in self:
            activities = self.env['mail.activity'].with_context(active_test=False).search([
                ('note_id', '=', note.id)
            ])
            note.activity_count = len(activities)
            note.active_activity_count = len(activities.filtered('active'))

    @api.depends('stage_ids')
    def _compute_stage_id(self):
        """計算當前用戶的階段"""
        first_user_stage = self.env['note.stage'].search(
            [('user_id', '=', self.env.uid)],
            limit=1,
        )
        for note in self:
            user_stages = note.stage_ids.filtered(
                lambda stage: stage.user_id == self.env.user
            )
            note.stage_id = user_stages[:1] or first_user_stage

    def _inverse_stage_id(self):
        """更新用戶階段關聯"""
        for note in self.filtered('stage_id'):
            other_user_stages = note.stage_ids.filtered(
                lambda stage: stage.user_id != self.env.user
            )
            note.stage_ids = note.stage_id | other_user_stages

    # ===== 預設值方法 =====
    def _get_default_stage_id(self):
        """取得當前用戶的預設階段"""
        return self.env['note.stage'].search(
            [('user_id', '=', self.env.uid)],
            limit=1,
        )

    @api.model
    def _read_group_stage_ids(self, stages, domain, order=None):
        """看板視圖階段展開 - 顯示當前用戶的所有階段"""
        return self.env['note.stage'].search([('user_id', '=', self.env.uid)])

    # ===== CRUD 方法 =====
    @api.model
    def name_create(self, name):
        """從名稱快速建立筆記"""
        return self.create({'memo': name}).name_get()[0]

    # ===== 動作方法 =====
    def action_close(self):
        """關閉筆記"""
        return self.write({
            'open': False,
            'date_done': fields.Date.today(),
        })

    def action_open(self):
        """重新開啟筆記"""
        return self.write({
            'open': True,
            'date_done': False,
        })

    def action_view_activities(self):
        """查看關聯待辦"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('關聯待辦'),
            'res_model': 'mail.activity',
            'view_mode': 'tree,form',
            'domain': [('note_id', '=', self.id)],
            'context': {'active_test': False},
        }

    # ===== API 方法 =====
    def get_related_documents(self):
        """取得關聯文件（CRM/Task）- API 方法

        Returns:
            list: 包含關聯文件資訊的字典列表
        """
        self.ensure_one()
        activities = self.env['mail.activity'].with_context(active_test=False).search([
            ('note_id', '=', self.id),
            ('is_transferred', '=', True),
        ])

        documents = []
        seen = set()
        for activity in activities:
            key = (activity.res_model, activity.res_id)
            if key not in seen:
                seen.add(key)
                documents.append({
                    'res_model': activity.res_model,
                    'res_id': activity.res_id,
                    'res_name': activity.res_name,
                    'activity_summary': activity.summary,
                    'activity_state': 'active' if activity.active else 'done',
                })

        return documents
