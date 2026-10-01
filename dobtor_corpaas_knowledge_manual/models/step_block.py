# -*- coding: utf-8 -*-
"""步驟區塊：功能 × 腳本範圍指紋。跨情境、跨方案共用的「怎麼操作」。

★ 鍵＝(feature_id, fingerprint)。畫面改版 → 依新指紋分岔一份（derived_from_id），
  舊方案仍引用舊的那份；之後兩條線若又收斂到同一個指紋 → 提議合併。
★ anchor 建立後不變；分岔沿用母區塊的 anchor，外部連結的 #錨點 才不會斷。
"""
import difflib

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..services import manual_lib
from .placement import sync_batch


class KnowledgeStepBlock(models.Model):
    _name = 'corpaas.knowledge.step_block'
    _description = '操作說明：步驟區塊'
    _inherit = ['corpaas.knowledge.content.mixin']
    _order = 'feature_id, sequence, id'

    name = fields.Char(string='標題', required=True, tracking=True)
    feature_id = fields.Many2one('corpaas.knowledge.feature', required=True,
                                 ondelete='cascade', index=True, tracking=True)
    fingerprint = fields.Char(string='腳本範圍指紋', index=True,
                              help='寫這份步驟時的 scope_hash')
    html = fields.Html(string='步驟')
    anchor = fields.Char(readonly=True, copy=False, index=True,
                         help='穩定鍵（slug），建立後不變；步驟標題 id 以此為前綴')
    derived_from_id = fields.Many2one('corpaas.knowledge.step_block', string='分岔自',
                                      ondelete='set null', index=True)
    derived_ids = fields.One2many('corpaas.knowledge.step_block', 'derived_from_id',
                                  string='分岔')
    sequence = fields.Integer(default=10)
    article_ids = fields.Many2many(
        'corpaas.knowledge.article', 'corpaas_knowledge_article_step_block_rel',
        'step_block_id', 'article_id', string='引用的文章')
    article_count = fields.Integer(compute='_compute_article_count')

    def _knowledge_revision_fields(self):
        return ['name', 'html']

    def _compute_article_count(self):
        for rec in self:
            rec.article_count = len(rec.article_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('anchor'):
                continue
            parent = self.browse(vals.get('derived_from_id') or [])
            if parent:
                vals['anchor'] = parent.anchor
            else:
                feature = self.env['corpaas.knowledge.feature'].browse(vals.get('feature_id'))
                vals['anchor'] = self._unique_anchor(manual_lib.make_anchor(feature.feature_key))
        return super().create(vals_list)

    def write(self, vals):
        vals.pop('anchor', None)
        return super().write(vals)

    @api.model
    def _unique_anchor(self, base):
        anchor, n = base, 2
        while self.with_context(active_test=False).search_count(
                [('anchor', '=', anchor), ('derived_from_id', '=', False)]):
            anchor = '%s-%s' % (base, n)
            n += 1
        return anchor

    def _manual_live_source(self):
        """前台用的 (標題, HTML)：一律取最後一次核准上線的快照。

        ☠️ 沒審過的文字絕不上前台（B3）：從沒上線過 → 空字串；上線後又被改（不論狀態，
          伺服端流程改了也沒退回草稿的也算）→ 仍是上線那一版。
        """
        self.ensure_one()
        if not self.published_rev_no:
            return self.name, ''
        snap = self._last_published_snapshot()
        if not snap:
            # 舊資料沒有上線快照：只有乾淨的已發佈狀態才信目前欄位
            return self.name, (self.html or '') if self.state == 'published' else ''
        return snap.get('name') or self.name, snap.get('html') or ''

    def action_approve(self):
        self._check_approver()
        with sync_batch(self.env) as env:
            return super(KnowledgeStepBlock, self.with_env(env)).action_approve()

    def _knowledge_publish(self):
        # ★ 真正的推送在 _do_publish 之後：這裡被呼叫時 state／published_rev_no 還是舊的，
        #   _manual_live_source() 會把剛核准的區塊當成未上線而略過。
        return True

    def _do_publish(self, change, note=None):
        res = super()._do_publish(change, note=note)
        # 步驟區塊是共用的：上線後把引用它、有上線版的文章重新推到 slide（送審中、草稿中的
        # 也推：前台只用各自的上線快照組裝，推的仍是上線那一版）。
        live = self.mapped('article_ids').filtered(
            lambda a: a.published_rev_no and a.state != 'retired')
        if live:
            live._manual_push()
        return res

    def _manual_ancestors(self):
        """自己往上的分岔鏈（不含自己）。"""
        self.ensure_one()
        out, cur = self.browse(), self.derived_from_id
        while cur and cur not in out and cur != self:
            out |= cur
            cur = cur.derived_from_id
        return out

    def action_open_articles(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('引用的文章'),
            'res_model': 'corpaas.knowledge.article', 'view_mode': 'list,form',
            'domain': [('id', 'in', self.article_ids.ids)],
        }

    @api.model
    def _find_converged(self, features=None):
        """同功能、同指紋、仍在用的區塊有兩份以上 → [(keep, others)]。"""
        domain = [('state', '!=', 'retired'), ('fingerprint', '!=', False)]
        if features is not None:
            domain.append(('feature_id', 'in', features.ids))
        groups = {}
        for blk in self.search(domain, order='id'):
            groups.setdefault((blk.feature_id.id, blk.fingerprint), self.browse())
            groups[(blk.feature_id.id, blk.fingerprint)] |= blk
        out = []
        for blocks in groups.values():
            if len(blocks) < 2:
                continue
            published = blocks.filtered(lambda b: b.published_rev_no)
            keep = (published or blocks)[:1]
            out.append((keep, blocks - keep))
        return out


class KnowledgeStepBlockMerge(models.Model):
    """指紋收斂的合併提案：人工確認後併回一份、引用改指。"""
    _name = 'corpaas.knowledge.step_block.merge'
    _description = '操作說明：步驟區塊合併提案'
    _order = 'id desc'

    feature_id = fields.Many2one('corpaas.knowledge.feature', required=True,
                                 ondelete='cascade')
    fingerprint = fields.Char(required=True)
    keep_id = fields.Many2one('corpaas.knowledge.step_block', string='保留',
                              required=True, ondelete='cascade')
    merge_ids = fields.Many2many('corpaas.knowledge.step_block',
                                 'corpaas_knowledge_step_block_merge_rel',
                                 'merge_id', 'step_block_id', string='併入')
    state = fields.Selection([('proposed', '待確認'), ('done', '已合併'),
                              ('rejected', '不合併')], default='proposed', index=True)
    diff_html = fields.Html(compute='_compute_diff_html', sanitize=False, string='內容差異')

    @api.depends('keep_id.html', 'merge_ids.html')
    def _compute_diff_html(self):
        for rec in self:
            parts = []
            for other in rec.merge_ids:
                table = difflib.HtmlDiff(wrapcolumn=70).make_table(
                    (rec.keep_id.html or '').splitlines(), (other.html or '').splitlines(),
                    rec.keep_id.display_name, other.display_name, context=True, numlines=2)
                parts.append(table)
            rec.diff_html = ''.join(parts) or False

    @api.model
    def _propose(self, keep, others):
        """同一組已有待確認提案就不重複建立；人工判定「不合併」過的不再提。"""
        rejected = self.search([('keep_id', '=', keep.id), ('state', '=', 'rejected')])
        others -= rejected.mapped('merge_ids')
        if not others:
            return self.browse()
        existing = self.search([('keep_id', '=', keep.id), ('state', '=', 'proposed')])
        if existing:
            existing.merge_ids = [(4, b.id) for b in others]
            return existing
        return self.create({'feature_id': keep.feature_id.id,
                            'fingerprint': keep.fingerprint, 'keep_id': keep.id,
                            'merge_ids': [(6, 0, others.ids)]})

    def action_merge(self):
        for rec in self.filtered(lambda r: r.state == 'proposed'):
            if rec.keep_id.state == 'retired':
                raise UserError(_('保留的步驟區塊已下架，不能合併。'))
            for blk in rec.merge_ids:
                arts = blk.article_ids
                arts.write({'step_block_ids': [(3, blk.id), (4, rec.keep_id.id)]})
                if rec.keep_id.published_rev_no:
                    arts._manual_swap_live_block(blk, rec.keep_id)
                blk.derived_ids.write({'derived_from_id': rec.keep_id.id})
                live = arts.filtered(lambda a: a.state in ('published', 'stale'))
                if live:
                    live._manual_push()
            rec.merge_ids.action_retire()
            rec.state = 'done'
        return True

    def action_reject(self):
        self.write({'state': 'rejected'})
        return True
