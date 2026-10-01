# -*- coding: utf-8 -*-
"""行銷內容的上線欄位防護（pitch、release note 共用）。

★ 「宣稱一律核准」只有在狀態與上線快照改不動時才成立：編輯者從表單／RPC 直接寫
  `state='published'` 或 `live_json`，就能把沒核准的宣稱推上商品頁。所以這些欄位只允許
  狀態機（送審、核准、退回、失效、下架）與事件派送帶著 `GUARD_TOKEN` 寫入。
☠️ 標記不能是普通的 context 值：RPC 可以送任意 context（`{'knowledge_marketing_publish': true}`），
  所以比對的是模組內這一個物件本身（`is`）。RPC 傳進來的只會是 JSON 反序列化出的 str／bool，
  永遠不會是同一個物件；str 子類只是讓 context 被序列化時不會炸。
☠️ 狀態機方法（knowledge_propose、_do_publish…）在核心 mixin 裡直接 write：
  本模型要排在 mixin 前面（`_inherit` 本模型即可），覆寫後帶上 context 再 super。
"""
from odoo import _, api, models
from odoo.exceptions import UserError

GUARD_CTX = 'knowledge_marketing_publish'


class _GuardToken(str):
    __slots__ = ()


GUARD_TOKEN = _GuardToken(GUARD_CTX)


def guard_ctx():
    return {GUARD_CTX: GUARD_TOKEN}


def is_guarded(env):
    return env.context.get(GUARD_CTX) is GUARD_TOKEN


class KnowledgeMarketingGuarded(models.AbstractModel):
    _name = 'corpaas.knowledge.marketing.guarded'
    _description = '行銷內容（上線欄位防護）'
    _inherit = ['corpaas.knowledge.content.mixin']

    #: 只能由狀態機／事件派送寫入的欄位（子類可加）
    _marketing_guarded_fields = ('state', 'live_json')

    def _marketing_sys(self):
        return self.with_context(**guard_ctx())

    def _marketing_check_guard(self, vals, creating=False):
        if is_guarded(self.env):
            return
        bad = {k for k in vals if k in self._marketing_guarded_fields}
        if creating and vals.get('state', 'draft') == 'draft':
            bad.discard('state')
        if bad:
            raise UserError(_('「%s」只能經由送審／核准流程變更，不能直接修改。')
                            % '、'.join(self._fields[k].string for k in sorted(bad)))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._marketing_check_guard(vals, creating=True)
        return super().create(vals_list)

    def write(self, vals):
        self._marketing_check_guard(vals)
        return super().write(vals)

    def copy_data(self, default=None):
        # ★ 複製一律從草稿開始（state 在 mixin 上是 copy=True）
        default = dict(default or {}, state='draft')
        return super().copy_data(default)

    # ------------------------------------------------------------------
    # 狀態機：帶上 GUARD_TOKEN
    # ------------------------------------------------------------------
    def knowledge_propose(self, change, note=None):
        return super(KnowledgeMarketingGuarded, self._marketing_sys()).knowledge_propose(
            change, note=note)

    def action_approve(self):
        return super(KnowledgeMarketingGuarded, self._marketing_sys()).action_approve()

    def action_reject(self, reason=None):
        return super(KnowledgeMarketingGuarded, self._marketing_sys()).action_reject(reason)

    def knowledge_mark_stale(self, reason):
        return super(KnowledgeMarketingGuarded, self._marketing_sys()).knowledge_mark_stale(
            reason)

    def knowledge_reshoot_done(self):
        return super(KnowledgeMarketingGuarded, self._marketing_sys()).knowledge_reshoot_done()

    def knowledge_needs_rewrite(self, reason):
        return super(KnowledgeMarketingGuarded, self._marketing_sys()).knowledge_needs_rewrite(
            reason)

    def action_retire(self):
        # ★ 下架＝把上線內容從商品頁撤掉，與核准同級（核心也會擋，這裡不依賴核心版本）
        self._check_approver()
        return super(KnowledgeMarketingGuarded, self._marketing_sys()).action_retire()

    def _knowledge_retire(self):
        """系統流程的下架（不檢查權限）：寫 state 一樣要帶標記。"""
        return super(KnowledgeMarketingGuarded, self._marketing_sys())._knowledge_retire()

    def _marketing_resubmit_change(self):
        return 'claim'

    def action_submit(self):
        """★ 已上線的內容改過後可以再送審（上線版照舊顯示，核准後才換）。"""
        published = self.filtered(lambda r: r.state == 'published')
        if published:
            published.knowledge_propose(self._marketing_resubmit_change(),
                                        note=_('修改上線內容後送審'))
        rest = self - published
        if rest:
            super(KnowledgeMarketingGuarded, rest._marketing_sys()).action_submit()
        return True
