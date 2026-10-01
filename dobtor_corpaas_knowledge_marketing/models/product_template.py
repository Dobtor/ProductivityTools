# -*- coding: utf-8 -*-
import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)

SHOWN_STATES = ('published', 'stale')


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    knowledge_pitch_ids = fields.One2many('corpaas.knowledge.pitch', 'product_tmpl_id',
                                          string='能力卡片')
    knowledge_release_note_ids = fields.One2many('corpaas.knowledge.release_note',
                                                 'product_tmpl_id', string='本期新增')

    def _knowledge_package(self, variant=None):
        """商品頁對應的方案。

        ★ 與 /corpaas/solution/<product.product id> 同一套解析：變體專屬的套件優先，
          其次整個 template 通用的那一份；已上架（published_version_id 有值）優先。
          有變體時只看同分支（branch_name）——同一個商品的 17／18 版是不同方案，
          加購可得、本期新增都不能混。
        """
        self.ensure_one()
        tmpl = self.sudo()
        pkgs = tmpl._corpaas_solution_packages() \
            if hasattr(tmpl, '_corpaas_solution_packages') else tmpl.infra_modules_integ_ids
        if variant:
            variant = variant.sudo()
            branch = variant.branch_name if 'branch_name' in variant._fields else False
            pkgs = pkgs.filtered(
                lambda p: p.product_id == variant
                or (not p.product_id) or (branch and p.product_id.branch_name == branch))
            pkgs = pkgs.sorted(lambda p: (p.product_id != variant, not p.product_id))
        published = pkgs.filtered('published_version_id')
        return (published or pkgs)[:1]

    def _knowledge_upsell_capabilities(self, package=None):
        """[{capability, modules}]：方案缺、但缺的模組都能單獨販售的能力（加購可得）。

        ★ 只看掛在這個方案上的能力（`package.knowledge_capability_ids`），不做全域搜尋：
          哪些加購要推給這個方案的客戶，由產品負責人把能力掛到方案上決定。
        ★ 只列已核准上線過的能力（published／stale）；草稿能力不上商品頁。
        ★ 判斷規則與 `capability.availability_for()` 相同（缺的模組全部可單獨販售＝addon），
          但整頁只查一次模組：商品頁是公開頁，不能每張能力卡各打一次搜尋。
        """
        self.ensure_one()
        package = package or self._knowledge_package()
        if not package:
            return []
        package = package.sudo()
        caps = package.knowledge_capability_ids.filtered(lambda c: c.state in SHOWN_STATES)
        if not caps:
            return []
        have = set(package._provision_module_names())
        lacking = {}
        for cap in caps:
            need = cap.required_modules() | set(filter(None, cap.feature_ids.mapped('module')))
            if need - have:
                lacking[cap] = need - have
        if not lacking:
            return []
        names = set().union(*lacking.values())
        sellable, picked = self._knowledge_sellable_index(package, names)
        out = []
        for cap, missing in lacking.items():
            if missing <= sellable:
                mods = self.env['infrastructure.repository.module'].sudo()
                for name in sorted(missing):
                    mods |= picked.get(name, mods.browse())
                out.append({'capability': cap, 'modules': mods})
        return out

    def _knowledge_sellable_index(self, package, technical_names):
        """(可單獨販售的技術名 set, {技術名: 有產品的 repository.module})；一次查詢。

        同名多分支時挑與方案同分支的產品。
        """
        Module = self.env['infrastructure.repository.module'].sudo()
        if not technical_names:
            return set(), {}
        mods = Module.search([('technical_name', 'in', sorted(technical_names)),
                              ('is_sellable', '=', True)])
        branch = package.branch_name or package.product_tmpl_id.product_variant_id.branch_name
        picked = {}
        for name in technical_names:
            same = mods.filtered(lambda m, n=name: m.technical_name == n and m.product_id)
            best = (same.filtered(lambda m: branch and m.product_id.branch_name == branch)
                    or same)[:1]
            if best:
                picked[name] = best
        return set(mods.mapped('technical_name')), picked

    def _knowledge_marketing_values(self, variant=None):
        """商品頁區塊的資料（sudo；只讀核准上線的快照）。

        ☠️ 公開頁：這裡出錯會讓整張商品頁 500，所以吞掉例外只記 log，區塊不顯示。
        """
        self.ensure_one()
        empty = {'pitches': [], 'release_note': False, 'addons': []}
        try:
            with self.env.cr.savepoint():
                return self._knowledge_marketing_values_unsafe(variant)
        except Exception:  # noqa: BLE001
            _logger.exception('[knowledge] 商品頁行銷區塊組裝失敗：%s', self.id)
            return empty

    def _knowledge_marketing_values_unsafe(self, variant=None):
        self.ensure_one()
        tmpl = self.sudo()
        package = tmpl._knowledge_package(variant)
        scope = [('product_tmpl_id', '=', tmpl.id)]
        if package:
            # ★ 只顯示這個方案的內容（舊資料沒指定方案的也算）
            scope += ['|', ('package_id', '=', package.id), ('package_id', '=', False)]
        pitches = self.env['corpaas.knowledge.pitch'].sudo().search(
            scope + [('live_json', '!=', False), ('state', '!=', 'retired')],
            order='sequence, id')
        # ★ 本期新增顯示最近一篇上線過的快照（改稿送審中也照舊顯示上線版）；
        #   快照提到的功能已從方案消失（失效）就跳過，下架的不顯示。
        notes = self.env['corpaas.knowledge.release_note'].sudo().search(
            scope + [('live_json', '!=', False), ('state', '!=', 'retired')],
            order='published_date desc, id desc')
        note = notes._marketing_first_showable(package)
        addons = []
        for item in tmpl._knowledge_upsell_capabilities(package):
            cap = item['capability']
            addons.append({
                'anchor': 'kb-addon-%s' % (cap.code or cap.id),
                'name': cap.name, 'outcome': cap.outcome or '',
                'modules': [{'name': m.product_id.name,
                             'url': '/module/content/%s' % m.product_id.id}
                            for m in item['modules']],
            })
        return {'pitches': pitches._website_cards(package),
                'release_note': note._website_note() if note else False,
                'addons': addons}
