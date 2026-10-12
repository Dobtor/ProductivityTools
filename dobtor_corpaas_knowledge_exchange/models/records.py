# -*- coding: utf-8 -*-
"""交換模組的資料表（計畫 6.3）：對端、發佈清單、送件匣、入庫紀錄、上收提案。"""
import json
import secrets

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from ..lib import protocol

KIND_SEL = [(k, k) for k in protocol.ORDER]


class KnowledgeExchangePeer(models.Model):
    _name = 'corpaas.knowledge.exchange.peer'
    _description = '知識交換對端主控台'
    _order = 'role, code'

    name = fields.Char(required=True)
    code = fields.Char(string='主控台代碼', required=True, help='對方的主控台代碼（例如 dobtor）')
    role = fields.Selection([('replica', '從屬（對方向我查詢、送件）'), ('master', '主體（我向它查詢、送件）')],
                            required=True, default='replica')
    url = fields.Char(string='主體網址', help='主體的主控台網址（例如 https://admin.corpaas.com）；只有主體需要')
    key = fields.Char(string='交換金鑰', copy=False, groups='dobtor_corpaas_knowledge.group_knowledge_manager',
                      help='主體為每個從屬發一把；從屬把同一把填在「主體」那筆。只能查詢與送件，不能改主體紀錄')
    allowed_ips = fields.Char(string='允許來源 IP', help='逗號分隔；空白＝不限（只用在從屬那筆）')
    active = fields.Boolean(default=True)
    feed_cursor = fields.Integer(string='發佈清單游標', readonly=True, help='從屬：已拉到主體發佈清單的哪一筆')
    last_ok = fields.Datetime(string='上次成功', readonly=True)
    last_error = fields.Char(string='上次錯誤', readonly=True)

    _sql_constraints = [('code_role_uniq', 'unique(code, role)', '同一個主控台只能登記一次。')]

    def action_generate_key(self):
        if not self.env.user.has_group('dobtor_corpaas_knowledge.group_knowledge_manager'):
            raise AccessError(_('只有知識管理者可以產生交換金鑰。'))
        for rec in self:
            rec.sudo().key = secrets.token_urlsafe(32)
        return True

    def _ip_allowed(self, ip):
        self.ensure_one()
        allowed = [x.strip() for x in (self.allowed_ips or '').split(',') if x.strip()]
        return not allowed or ip in allowed


class KnowledgeExchangeFeed(models.Model):
    """主體的發佈清單：入庫、核准、本地內容變更都寫一筆；從屬依游標（id）拉。"""
    _name = 'corpaas.knowledge.exchange.feed'
    _description = '知識發佈清單'
    _order = 'id'

    kind = fields.Selection(KIND_SEL, required=True, index=True)
    res_model = fields.Char(required=True)
    res_id = fields.Integer(required=True)
    kb_uid = fields.Char(index=True)
    content_hash = fields.Char()
    op = fields.Selection([('upsert', '新增／更新'), ('retract', '作廢')], default='upsert', required=True)


class KnowledgeExchangeOutbox(models.Model):
    """從屬的送件匣。"""
    _name = 'corpaas.knowledge.exchange.outbox'
    _description = '知識送件匣'
    _order = 'id desc'

    kind = fields.Selection(KIND_SEL, required=True, index=True)
    res_model = fields.Char(required=True)
    res_id = fields.Integer(required=True, index=True)
    name = fields.Char(string='項目')
    kb_uid = fields.Char(index=True)
    content_hash = fields.Char(index=True)
    payload = fields.Text(string='內容快照')
    state = fields.Selection([('pending', '待送'), ('ingested', '已入庫'), ('exists', '主體已有'),
                              ('review', '待主體審核'), ('rejected', '退回'), ('error', '送件失敗')],
                             default='pending', required=True, index=True)
    attempts = fields.Integer(readonly=True)
    next_try = fields.Datetime(readonly=True)
    reason = fields.Char(string='原因', readonly=True)

    _sql_constraints = [('item_uniq', 'unique(res_model, res_id, content_hash)', '同一版內容只送一次。')]

    def record(self):
        self.ensure_one()
        return self.env[self.res_model].sudo().browse(self.res_id).exists()


class KnowledgeExchangeIngest(models.Model):
    """主體的入庫紀錄（稽核：誰、何時、哪個從屬、哪一筆、結果）。"""
    _name = 'corpaas.knowledge.exchange.ingest'
    _description = '知識入庫紀錄'
    _order = 'id desc'

    peer_id = fields.Many2one('corpaas.knowledge.exchange.peer', string='從屬', required=True, ondelete='restrict')
    kind = fields.Selection(KIND_SEL, required=True, index=True)
    key_text = fields.Char(string='交換鍵')
    kb_uid = fields.Char(index=True)
    content_hash = fields.Char()
    result = fields.Selection([(protocol.EXISTS, '已有'), (protocol.INGESTED, '入庫'),
                               (protocol.REVIEW, '待審'), (protocol.REJECTED, '退回')], required=True)
    reason = fields.Char()
    res_model = fields.Char()
    res_id = fields.Integer()


class KnowledgeExchangePromotion(models.Model):
    """上收提案（範本類）與修改意見（對主體知識）——都要人工審核。"""
    _name = 'corpaas.knowledge.exchange.promotion'
    _description = '知識上收提案'
    _inherit = ['mail.thread']
    _order = 'state, id desc'

    type = fields.Selection([('promotion', '上收提案'), ('feedback', '修改意見')], required=True,
                            default='promotion')
    peer_id = fields.Many2one('corpaas.knowledge.exchange.peer', string='從屬', required=True, ondelete='restrict')
    kind = fields.Selection(KIND_SEL, required=True)
    kb_uid = fields.Char(index=True)
    name = fields.Char(string='項目', required=True)
    payload = fields.Text(string='提案內容')
    note = fields.Text(string='說明')
    similar_text = fields.Text(string='相似的既有項目', readonly=True,
                               help='名稱相近的既有項目（只是提示人工合併；有 kb_uid 後不再以名稱自動對應）')
    state = fields.Selection([('pending', '待審'), ('approved', '核准'), ('merged', '併入既有'),
                              ('rejected', '退回'), ('done', '已處理')], default='pending', required=True,
                             tracking=True)
    merged_into_uid = fields.Char(string='併入項目的全域識別')
    reviewer_id = fields.Many2one('res.users', readonly=True)
    reviewed_at = fields.Datetime(readonly=True)
    result_model = fields.Char(readonly=True)
    result_id = fields.Integer(readonly=True)

    def _check_manager(self):
        if not self.env.user.has_group('dobtor_corpaas_knowledge.group_knowledge_manager'):
            raise AccessError(_('只有知識管理者可以審核上收提案。'))

    def _done(self, state, **vals):
        self.write(dict(vals, state=state, reviewer_id=self.env.user.id, reviewed_at=fields.Datetime.now()))

    def action_approve(self):
        """核准：用從屬給的全域識別在主體建成正式項目 → 發佈 → 從屬那筆變成指向上游的鏡像（不留兩份）。"""
        self._check_manager()
        for rec in self.filtered(lambda r: r.type == 'promotion' and r.state == 'pending'):
            payload = json.loads(rec.payload or '{}')
            Model = self.env[protocol.KINDS[rec.kind]['model']]
            res = Model._kb_upsert(payload, state='local', trust='replica', origin=rec.peer_id.code)
            rec._done('approved', result_model=res._name, result_id=res.id)
        return True

    def action_merge(self):
        """併入既有：填「併入項目的全域識別」後按。從屬那筆會收到退回並指出要改用的項目。"""
        self._check_manager()
        for rec in self.filtered(lambda r: r.state == 'pending'):
            if not rec.merged_into_uid:
                raise UserError(_('請先填「併入項目的全域識別」。'))
            target = self.env[protocol.KINDS[rec.kind]['model']].sudo().search(
                [('kb_uid', '=', rec.merged_into_uid)], limit=1)
            if not target:
                raise UserError(_('找不到全域識別 %s 的項目。') % rec.merged_into_uid)
            rec._done('merged', result_model=target._name, result_id=target.id)
        return True

    def action_reject(self):
        self._check_manager()
        self.filtered(lambda r: r.state == 'pending')._done('rejected')
        return True

    def action_mark_done(self):
        self._check_manager()
        self.filtered(lambda r: r.type == 'feedback' and r.state == 'pending')._done('done')
        return True

    @api.model
    def _similar(self, kind, name):
        """名稱相近的既有項目（#4：名稱比對只當提示）。"""
        Model = self.env[protocol.KINDS[kind]['model']].sudo()
        if 'name' not in Model._fields or not name:
            return ''
        words = [w for w in name.replace('、', ' ').split() if len(w) > 1][:3] or [name[:4]]
        dom = ['|'] * (len(words) - 1) + [('name', 'ilike', w) for w in words]
        found = Model.search(dom + [('kb_sync_state', '!=', 'mirror')], limit=8)
        return '\n'.join('%s（%s）' % (r.display_name, r.kb_uid) for r in found)
