# -*- coding: utf-8 -*-
"""三個出口共用的內容狀態機與修訂（D4）。

    draft ──送審──▶ review ──核准──▶ published ──失效事件──▶ stale
      ▲             │                  │  ▲                   │ │
      └────退回─────┘                  │  └──純重拍成功（自動）─┘ │
      └──────────────需改文字─────────────────────────────────────┘
                         published / stale ──功能消失──▶ retired

★ stale 時舊版仍在線上：用戶不會看到空頁。出口在 `_knowledge_publish()` 裡把內容
  推到對外位置（slide、商品頁…），`_knowledge_unpublish()` 撤下。
★ 發佈閘門：`_knowledge_requires_review(change)` 由出口覆寫。
"""
import contextvars
import difflib
import json

import odoo.service.model as _rpc_model
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

#: 外部 RPC（/jsonrpc、/xmlrpc）這次呼叫的模型方法名；不是外部 RPC 時為 None。
#: ☠️ Odoo 18 的 dispatch_rpc 用 borrow_request() 把 request 暫時拿掉才執行模型方法，
#:   所以靠 request 判斷「用戶端直接寫入」對外部 RPC 完全無效（實機：RPC 改已上線情境的
#:   示範資料，狀態沒有退回草稿、上線快照也沒變——靜默無效）。在派送入口記下方法名。
_EXTERNAL_RPC_METHOD = contextvars.ContextVar('kb_external_rpc_method', default=None)


def _wrap_rpc_dispatch():
    orig = _rpc_model.dispatch
    if getattr(orig, '_kb_wrapped', False):
        return

    def dispatch(method, params):
        name = None
        if method in ('execute', 'execute_kw') and len(params) > 4:
            name = params[4]
        token = _EXTERNAL_RPC_METHOD.set(name or method)
        try:
            return orig(method, params)
        finally:
            _EXTERNAL_RPC_METHOD.reset(token)
    dispatch._kb_wrapped = True
    _rpc_model.dispatch = dispatch


_wrap_rpc_dispatch()

STATES = [
    ('draft', '草稿'),
    ('review', '待核'),
    ('published', '已發佈'),
    ('stale', '失效'),
    ('retired', '下架'),
]

CHANGE_KINDS = [
    ('new', '新內容'),
    ('text', '文字改寫'),
    ('shot', '純重拍截圖'),
    ('claim', '行銷宣稱'),
    ('restore', '還原修訂'),
]


class KnowledgeRevision(models.Model):
    _name = 'corpaas.knowledge.revision'
    _description = '知識內容修訂'
    _order = 'res_model, res_id, rev_no desc'

    res_model = fields.Char(required=True, index=True)
    res_id = fields.Integer(required=True, index=True)
    rev_no = fields.Integer(required=True)
    change_kind = fields.Selection(CHANGE_KINDS, required=True)
    snapshot = fields.Text(required=True, help='內容欄位的 JSON 快照')
    note = fields.Char()
    author_id = fields.Many2one('res.users', default=lambda s: s.env.user)
    was_published = fields.Boolean(help='這一版曾經上線（可還原的對象）')

    _sql_constraints = [
        ('rev_unique', 'unique(res_model, res_id, rev_no)', '修訂編號重複'),
    ]

    def _data(self):
        self.ensure_one()
        return json.loads(self.snapshot or '{}')


class KnowledgeContentMixin(models.AbstractModel):
    _name = 'corpaas.knowledge.content.mixin'
    _description = '知識內容狀態機'
    _inherit = ['mail.thread']

    state = fields.Selection(STATES, default='draft', required=True, tracking=True,
                             index=True)
    pending_change = fields.Selection(CHANGE_KINDS, string='待核變更', copy=False)
    stale_reason = fields.Char(string='失效原因', copy=False)
    reject_reason = fields.Char(string='退回原因', copy=False)
    rev_no = fields.Integer(string='修訂', default=0, copy=False, readonly=True)
    published_rev_no = fields.Integer(string='上線修訂', copy=False, readonly=True)
    revision_count = fields.Integer(compute='_compute_revision_count')
    review_diff = fields.Html(compute='_compute_review_diff', sanitize=False,
                              string='文字差異')

    # ------------------------------------------------------------------
    # 出口覆寫點
    # ------------------------------------------------------------------
    def _knowledge_revision_fields(self):
        """要進修訂快照的欄位（文字內容）。"""
        return []

    def _knowledge_requires_review(self, change):
        """這次變更是否要人工核准。預設：只有純重拍不用。"""
        self.ensure_one()
        return change != 'shot'

    def _knowledge_publish(self):
        """把內容推到對外位置。出口覆寫。"""
        return True

    def _knowledge_unpublish(self):
        return True

    # ------------------------------------------------------------------
    def _compute_revision_count(self):
        Rev = self.env['corpaas.knowledge.revision'].sudo()
        for rec in self:
            rec.revision_count = Rev.search_count(
                [('res_model', '=', rec._name), ('res_id', '=', rec.id)]) if rec.id else 0

    def _snapshot(self):
        self.ensure_one()
        data = {}
        for name in self._knowledge_revision_fields():
            value = self[name]
            if isinstance(value, models.BaseModel):
                value = value.ids
            data[name] = value
        return data

    def _last_published_snapshot(self):
        self.ensure_one()
        rev = self.env['corpaas.knowledge.revision'].sudo().search(
            [('res_model', '=', self._name), ('res_id', '=', self.id),
             ('was_published', '=', True)], limit=1)
        return rev._data() if rev else {}

    def _compute_review_diff(self):
        for rec in self:
            if not rec.id:
                rec.review_diff = False
                continue
            old = rec._last_published_snapshot()
            new = rec._snapshot()
            rows = []
            for name in rec._knowledge_revision_fields():
                a = str(old.get(name) or '')
                b = str(new.get(name) or '')
                if a == b:
                    continue
                label = rec._fields[name].string
                table = difflib.HtmlDiff(wrapcolumn=70).make_table(
                    a.splitlines(), b.splitlines(), _('上線版'), _('本次'),
                    context=True, numlines=2)
                rows.append('<h5>%s</h5>%s' % (label, table))
            rec.review_diff = ''.join(rows) or '<p>%s</p>' % _('文字沒有變動')

    def _record_revision(self, change, note=None, published=False):
        self.ensure_one()
        self.rev_no += 1
        self.env['corpaas.knowledge.revision'].sudo().create({
            'res_model': self._name, 'res_id': self.id, 'rev_no': self.rev_no,
            'change_kind': change, 'snapshot': json.dumps(self._snapshot(),
                                                          ensure_ascii=False, default=str),
            'note': note, 'was_published': published,
        })

    def _check_approver(self):
        if not self.env.user.has_group('dobtor_corpaas_knowledge.group_knowledge_approver'):
            raise AccessError(_('只有知識內容核准者可以核准或退回。'))

    # ------------------------------------------------------------------
    # 狀態轉換
    # ------------------------------------------------------------------
    def knowledge_propose(self, change, note=None):
        """內容剛被（AI 或人）改過後呼叫：依閘門決定直接上線或送審。"""
        for rec in self:
            if rec._knowledge_requires_review(change):
                rec.write({'state': 'review', 'pending_change': change,
                           'reject_reason': False})
                rec._record_revision(change, note=note)
                rec.message_post(body=_('送審：%s') % dict(CHANGE_KINDS).get(change))
            else:
                rec._do_publish(change, note=note)
        return True

    def action_submit(self):
        for rec in self:
            if rec.state not in ('draft', 'stale'):
                raise UserError(_('只有草稿或失效的內容可以送審。'))
        # ★ 從沒上線過的內容一律當「新內容」送審：當成 'text' 的話，單一方案引用的
        #   情境等閘門較寬的內容會不經核准直接上線。
        for rec in self:
            rec.knowledge_propose('text' if rec.published_rev_no else 'new', note=_('手動送審'))
        return True

    def action_approve(self):
        self._check_approver()
        for rec in self:
            if rec.state != 'review':
                raise UserError(_('「%s」不在待核狀態。') % rec.display_name)
            change = rec.pending_change or 'text'
            rec._do_publish(change, note=_('核准'))
            rec._after_approved(change)
        return True

    def _after_approved(self, change):
        """出口可覆寫：例如情境的「連續 N 次核准無修改」計數。"""
        return True

    def _do_publish(self, change, note=None):
        self.ensure_one()
        self._knowledge_publish()
        self.write({'state': 'published', 'pending_change': False,
                    'stale_reason': False, 'reject_reason': False})
        self._record_revision(change, note=note, published=True)
        self.published_rev_no = self.rev_no

    def action_reject(self, reason=None):
        self._check_approver()
        reason = reason or self.env.context.get('reject_reason')
        if not reason:
            raise UserError(_('退回必須填寫理由。'))
        for rec in self:
            rec.write({'state': 'draft', 'pending_change': False, 'reject_reason': reason})
            rec.message_post(body=_('退回：%s') % reason)
        return True

    def knowledge_mark_stale(self, reason):
        for rec in self.filtered(lambda r: r.state == 'published'):
            rec.write({'state': 'stale', 'stale_reason': reason})
        return True

    def knowledge_reshoot_done(self):
        """stale 且只換了截圖 → 回到 published；出口要求純重拍也審（行銷）就送審。"""
        for rec in self.filtered(lambda r: r.state in ('stale', 'published')):
            if rec._knowledge_requires_review('shot'):
                rec.knowledge_propose('shot', note=_('純重拍成功'))
            else:
                rec._do_publish('shot', note=_('純重拍成功'))
        return True

    def knowledge_needs_rewrite(self, reason):
        for rec in self.filtered(lambda r: r.state in ('published', 'stale')):
            rec.write({'state': 'draft', 'stale_reason': reason})
        return True

    def action_retire(self):
        # ★ 下架會把內容從對外位置撤掉，和發佈一樣要核准權限（按鈕限制不算數，RPC 叫得到）。
        self._check_approver()
        return self._knowledge_retire()

    def _knowledge_retire(self):
        """系統流程用的下架（功能消失、方案不再引用）：不檢查使用者權限。

        ☠️ 系統流程不能呼叫 action_retire：佇列作業以「觸發者」身分執行，觸發改版的
          基礎建設人員不是知識核准者，整個出口步驟會當場 AccessError。
        """
        for rec in self:
            rec._knowledge_unpublish()
            rec.state = 'retired'
        return True

    # ------------------------------------------------------------------
    # 用戶端直接寫入的防護
    # ------------------------------------------------------------------
    _KB_PROTECTED = ('state', 'rev_no', 'published_rev_no', 'pending_change')

    @staticmethod
    def _kb_client_write():
        """這次寫入是否直接來自網頁用戶端／外部 RPC 的 write／create／web_save。

        ★ 只擋這一條路：按鈕（call_button）、排程、佇列、伺服端流程都照常。
          用 context 旗標擋不住——RPC 呼叫端自己就能帶 context。
        """
        rpc_method = _EXTERNAL_RPC_METHOD.get()
        if rpc_method:
            return rpc_method in ('write', 'create', 'web_save', 'web_save_multi')
        try:
            from odoo.http import request
            req = request
            if not req or not getattr(req, 'httprequest', None):
                return False
            path = req.httprequest.path or ''
            if not path.startswith(('/web/dataset/call_kw', '/json/', '/jsonrpc', '/xmlrpc')):
                return False
            method = (req.params or {}).get('method') or ''
            return method in ('write', 'create', 'web_save', 'web_save_multi') \
                or path.startswith(('/jsonrpc', '/xmlrpc', '/json/'))
        except Exception:  # noqa: BLE001 - 沒有請求脈絡＝伺服端流程
            return False

    def write(self, vals):
        if self._kb_client_write():
            if set(vals) & set(self._KB_PROTECTED):
                raise AccessError(_('狀態只能經由送審／核准／退回變更。'))
            text_fields = set(self._knowledge_revision_fields())
            if text_fields & set(vals):
                # ★ 直接改了已上線或失效內容的文字：退回草稿，重新核准前對外仍是上一版。
                #   不退回的話，下一次「純重拍」會把沒審過的文字一起發佈出去。
                live = self.filtered(lambda r: r.state in ('published', 'stale'))
                res = super().write(vals)
                if live:
                    super(KnowledgeContentMixin, live).write(
                        {'state': 'draft', 'stale_reason': _('上線後被直接修改，需重新送審')})
                return res
        return super().write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        if self._kb_client_write():
            for vals in vals_list:
                if set(vals) & set(self._KB_PROTECTED) - {'state'} \
                        or vals.get('state') not in (None, False, 'draft'):
                    raise AccessError(_('新內容只能從草稿開始。'))
        return super().create(vals_list)

    def action_open_reject(self):
        return {
            'type': 'ir.actions.act_window', 'name': _('退回'),
            'res_model': 'corpaas.knowledge.reject.wizard', 'view_mode': 'form',
            'target': 'new',
            'context': {'default_res_model': self._name,
                        'default_res_ids': ','.join(str(i) for i in self.ids)},
        }

    def action_open_revisions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('修訂'),
            'res_model': 'corpaas.knowledge.revision',
            'view_mode': 'list,form',
            'domain': [('res_model', '=', self._name), ('res_id', '=', self.id)],
        }

    def action_restore_revision(self, revision):
        self.ensure_one()
        revision = self.env['corpaas.knowledge.revision'].browse(
            revision if isinstance(revision, int) else revision.id)
        if revision.res_model != self._name or revision.res_id != self.id:
            raise UserError(_('修訂不屬於這筆內容。'))
        vals = {}
        for name, value in revision._data().items():
            field = self._fields.get(name)
            if not field:
                continue
            if field.type in ('many2many', 'one2many'):
                value = [(6, 0, value or [])]
            vals[name] = value
        self.write(vals)
        return self.knowledge_propose('restore', note=_('還原到修訂 %s') % revision.rev_no)


class KnowledgeRevisionRestore(models.Model):
    _inherit = 'corpaas.knowledge.revision'

    def action_restore(self):
        self.ensure_one()
        target = self.env[self.res_model].browse(self.res_id).exists()
        if not target:
            raise UserError(_('原內容已不存在。'))
        return target.action_restore_revision(self)

    @api.model
    def _gc_keep_last(self, keep=5):
        """保留政策：每筆內容保留最近 keep 版（上線過的至少留最新一版）。"""
        # ★ 最新一版「上線過」的修訂永遠保留：它是還原與審核差異比對的基準，
        #   就算它排在第 keep 版之外也不能刪。
        self.env.cr.execute("""
            SELECT id FROM (
                SELECT id, was_published,
                       row_number() OVER (PARTITION BY res_model, res_id
                                          ORDER BY rev_no DESC) AS rn,
                       row_number() OVER (PARTITION BY res_model, res_id, was_published
                                          ORDER BY rev_no DESC) AS prn
                FROM corpaas_knowledge_revision) t
            WHERE rn > %s AND NOT (was_published AND prn = 1)
        """, (keep,))
        ids = [r[0] for r in self.env.cr.fetchall()]
        if ids:
            self.browse(ids).unlink()
        return len(ids)
