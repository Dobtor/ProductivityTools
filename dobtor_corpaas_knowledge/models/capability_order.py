# -*- coding: utf-8 -*-
"""能力的歸屬與先後：功能點／流程落在哪一章、章節依做事的上下游排序。

☠️ 實機：銷售訂單的三個畫面同時列在「採購」與「銷售」兩個能力（採購能力為了「依銷售單採購」
  也收了它們），取第一個能力 → 銷售訂單說明全放進採購章；流程「銷售訂單流程」也因多數決
  歸到採購。歸屬改看模組：功能點／流程的模組在哪個能力裡最多，就屬於那個能力。
☠️ 實機：AI 分群出來的能力 sequence 全是 10 → 章節依名稱排，庫存排第一、銷售排最後。
  全部相同（沒人排過）時依主要模組的上下游先後自動排；有人排過就不動。
"""
from collections import Counter

from odoo import models

#: 模組的上下游先後（同一組同一名次）；不在清單的（儀表板、報表類）排最後。
#: 每組第二項是自訂模組的名稱關鍵字（方案自己的模組沒列在這裡，看名字歸組）。
#: ☠️ 實機：社群電商方案的推薦佣金、會員、客服、網站各章都不在清單 → 全排最後（又因順序值
#:   重複被擠到最前面），驗收「章節依上下游排序」不過。
MODULE_ORDER = [
    (('contacts', 'mail', 'base', 'calendar'), ()),
    (('product', 'uom'), ()),
    (('website', 'website_blog', 'website_event', 'website_slides'), ('website', 'blog', 'theme')),
    (('portal', 'auth_signup', 'auth_oauth'),
     ('signup', 'sso', 'login', 'portal', 'member', 'user_profile', 'user_apps')),
    (('crm',), ()),
    (('sale', 'sale_management', 'sales_team', 'sale_stock', 'loyalty', 'sale_loyalty',
      'website_sale'), ('checkout', 'shop', 'cart')),
    ((), ('commission', 'referral', 'promote', 'affiliate', 'reward')),
    (('purchase', 'purchase_requisition', 'purchase_stock'), ()),
    (('mrp',), ()),
    (('stock', 'stock_account', 'stock_picking_batch', 'stock_landed_costs', 'delivery',
      'stock_dropshipping'), ()),
    (('account', 'account_payment', 'payment'), ('invoice', 'wallet', 'payment')),
    (('im_livechat', 'website_livechat', 'helpdesk'), ('livechat', 'helpdesk', 'support')),
]
_RANK = {m: i for i, (group, _kw) in enumerate(MODULE_ORDER) for m in group}
LAST_RANK = len(MODULE_ORDER) + 1


def module_rank(module):
    """模組的上下游名次：官方模組查表；自訂模組看名稱關鍵字；都不中排最後。"""
    if module in _RANK:
        return _RANK[module]
    name = (module or '').lower()
    for i, (_group, words) in enumerate(MODULE_ORDER):
        if any(w in name for w in words):
            return i
    return LAST_RANK


class KnowledgeCapability(models.Model):
    _inherit = 'corpaas.knowledge.capability'

    def _knowledge_module_score(self, module):
        """這個能力裡有幾個功能點屬於這個模組。"""
        self.ensure_one()
        return sum(1 for f in self.feature_ids if f.module == module)

    def _knowledge_main_module(self):
        self.ensure_one()
        counts = Counter(f.module for f in self.feature_ids if f.module)
        return counts.most_common(1)[0][0] if counts else ''

    def _knowledge_rank(self):
        self.ensure_one()
        return module_rank(self._knowledge_main_module())


class SolutionPackage(models.Model):
    _inherit = 'infrastructure.solution.package'

    def _knowledge_best_capability(self, feature, caps=None):
        """功能點同時屬於多個能力時，取它的模組最多的那個（同分取能力順序在前的）。"""
        self.ensure_one()
        caps = caps if caps is not None else self.knowledge_capability_ids
        mine = feature.capability_ids & caps
        if len(mine) <= 1:
            return mine
        return max(mine, key=lambda c: (c._knowledge_module_score(feature.module),
                                        -c.sequence, -c.id))

    def _knowledge_flow_module(self, flow):
        """流程的主要模組：打開這個模型的功能點的模組（沒有就用流程上全部功能點）。"""
        feats = flow.feature_ids.filtered(lambda f: f.model == flow.model) or flow.feature_ids
        counts = Counter(f.module for f in feats if f.module)
        return counts.most_common(1)[0][0] if counts else ''

    def _knowledge_flow_capability(self, flow):
        """依模組判斷流程屬於本方案哪個能力；判斷不出來回空。"""
        self.ensure_one()
        module = self._knowledge_flow_module(flow)
        caps = self.knowledge_capability_ids
        if not module or not caps:
            return self.env['corpaas.knowledge.capability']
        best = max(caps, key=lambda c: (c._knowledge_module_score(module), -c.sequence, -c.id))
        return best if best._knowledge_module_score(module) else \
            self.env['corpaas.knowledge.capability']

    def _knowledge_tidy_capabilities(self):
        """每次更新：流程改掛到模組相符的能力；章節順序沒人排過就依上下游排。回傳統計。"""
        self.ensure_one()
        stats = {'flows_moved': 0, 'caps_ordered': 0}
        caps = self.knowledge_capability_ids
        Flow = self.env['corpaas.knowledge.flow'].sudo()
        for flow in Flow.search([('package_ids', 'in', self.id)]):
            best = self._knowledge_flow_capability(flow)
            cur = flow.capability_id
            if not best or best == cur:
                continue
            module = self._knowledge_flow_module(flow)
            if cur and cur in caps and cur._knowledge_module_score(module) >= \
                    best._knowledge_module_score(module):
                continue
            if cur and cur not in caps:
                continue   # 別的方案的能力：不動
            flow.capability_id = best
            stats['flows_moved'] += 1
        # 沒人排過（順序值有重複：AI 新增的能力都是預設 10）就依上下游排；人排過的值不會重複
        if len(caps) > 1 and len(set(caps.mapped('sequence'))) < len(caps):
            ordered = caps.sorted(lambda c: (c._knowledge_rank(), c.sequence, c.id))
            for i, cap in enumerate(ordered, start=1):
                cap.sudo().sequence = i * 10
            stats['caps_ordered'] = len(ordered)
        return stats


class KnowledgeSelection(models.Model):
    _inherit = 'corpaas.knowledge.selection'

    def _knowledge_flow_owner(self, flow):
        """流程核准時的歸屬：先看模組（銷售訂單流程 → 銷售），判斷不出來才用多數決。"""
        self.ensure_one()
        by_module = self.package_id._knowledge_flow_capability(flow)
        return by_module or super()._knowledge_flow_owner(flow)
