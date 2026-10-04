# -*- coding: utf-8 -*-
"""服務建議書：痛點 → 能力對應 → 工項估算 → 建議書／報價單 → 送出凍結 → 工時回寫校正。

★ 價格不自己算：訂閱費一律呼叫 dobtor_corpaas_product 的
  `product.template.compute_package_price()`（與 dobtor_corpaas_sale 的 SO 行計價同一支），
  週期取變體的 recurring_rule_type（與 `sale.order.line._paas_cycle()` 同一來源），
  報價與實收才不會對不上。
★ 送出後唯讀：write() 擋下（子記錄在 corpaas.knowledge.proposal.child 擋）；
  金額與成本（stored compute）送出後一律讀快照，工時回寫校正範本、牌價調整都不會改到已寄出的數字。
★ 報價單不會自動開通：確認時先擋住，由業務按「確認開通」選新平台／疊加／換層級
  （見 sale_order.py）。
"""
import json
import logging
import re

from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.misc import format_amount

from odoo.addons.dobtor_corpaas_knowledge.models.catalog import COLORS
from odoo.addons.dobtor_corpaas_knowledge.services import hub_client
from odoo.addons.dobtor_infrastructure.models.environment import SERVICE_TIER_SELECTION

from ..services import calc
from .effort import ACTIVITIES, ACTIVITY_ALIASES

_logger = logging.getLogger(__name__)

STATES = [('draft', '草稿'), ('sent', '已送出'), ('won', '成交'), ('lost', '未成交')]
CYCLES = [('monthly', '月繳'), ('quarterly', '季繳'), ('yearly', '年繳')]
COLOR_BADGE = {
    'native': 'text-bg-success', 'dobtor': 'text-bg-primary', 'tuning': 'text-bg-warning',
    'custom': 'text-bg-danger', 'as_is': 'text-bg-secondary',
}
#: 送出後仍可寫的欄位（報價單連結、工時回寫時間）
FROZEN_WRITABLE = {'sale_order_id', 'feedback_date'}
#: 只有送出／成交／未成交按鈕能寫（草稿時也一樣）
INTERNAL_ONLY = {'state', 'snapshot_json'}
INTERNAL_CTX = 'corpaas_proposal_internal'


class _InternalToken(str):
    __slots__ = ()


#: ☠️ RPC 能送任意 context，普通的旗標值（True／字串）擋不住；比對的是這個物件本身（is）。
INTERNAL_TOKEN = _InternalToken(INTERNAL_CTX)


def is_internal(env):
    return env.context.get(INTERNAL_CTX) is INTERNAL_TOKEN
#: 送出後金額／成本欄位從快照的哪一段讀
SNAPSHOT_PRICE_FIELDS = ('subscription_monthly', 'subscription_amount', 'addon_amount',
                         'implementation_days', 'implementation_amount', 'custom_days',
                         'custom_amount', 'total', 'pricing_note')
SNAPSHOT_COST_FIELDS = ('labor_cost', 'infra_monthly_cost', 'third_party_monthly',
                        'ai_monthly_cost', 'internal_cost', 'margin', 'margin_rate',
                        'cost_is_estimate', 'cost_note')
#: 工時比對的斷詞：空白與括號／標點（保留 _ 與 -，能力 code 常用）
_TOKEN_SPLIT = re.compile(r'[\s\[\]【】()（）{}<>《》「」,，、;；:：/／|#＃]+')
#: 通用工項（範本沒有能力）的明確標記
GENERIC_TOKENS = {'通用', 'general', 'common'}

AI_MATCH_PROMPT = """任務：把客戶痛點對應到方案的能力，作為服務建議書的「痛點對應表」。

規則：
1. 每個痛點對應 0～3 個能力；方案沒有合適能力時，capability_id 填 null（仍要給一筆，color 用 custom 或 as_is）。
2. color 只能是：native（原生）、dobtor（Dobtor 標準）、tuning（設定微調）、custom（客製開發）、as_is（沿用現況，不處理）。
   能力本身即可解決 → 用該能力的 color；需要調設定或小幅調整 → tuning；方案沒有能力可解決 → custom。
3. color 為 tuning 或 custom 時，custom_days 給客製參考人天區間 [低, 高]（數字，以 0.5 為單位）；其他顏色給 null。
4. 售前填的 color_hint、module_hint、quote_note 只是參考，以能力資料為準。
5. note 用一兩句說明這個痛點怎麼被解決；不要寫網址。
6. capability_id 只能用下面清單裡的 id；不要自創能力。
7. 能力的 feature_classes 是它在方案裡的功能分類：主要靠「標準功能」解決 → native；
   「專用功能」→ dobtor；需要「標準進階／專用進階」（設定頁開啟的功能）→ tuning。

輸入：
```json
%s
```

輸出格式：
```json
{"mappings": [{"pain_id": 1, "capability_id": 2, "color": "native", "custom_days": null, "note": "..."}]}
```
"""


class KnowledgeProposal(models.Model):
    _name = 'corpaas.knowledge.proposal'
    _description = '服務建議書'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(string='編號', required=True, copy=False, readonly=True, default='/')
    partner_id = fields.Many2one('res.partner', string='客戶', required=True, tracking=True)
    user_id = fields.Many2one('res.users', string='業務', default=lambda s: s.env.user)
    company_id = fields.Many2one('res.company', required=True,
                                 default=lambda s: s.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    product_tmpl_id = fields.Many2one(
        'product.template', string='訂閱方案', tracking=True,
        domain="[('is_package', '=', True)]")
    package_id = fields.Many2one(
        'infrastructure.solution.package', string='方案套件',
        domain="[('product_tmpl_id', '=', product_tmpl_id)]")
    scenario_id = fields.Many2one(
        'corpaas.knowledge.scenario', string='情境',
        help='決定情境敘事與資料移轉檢核表；留空＝方案所有情境。')
    tier = fields.Selection(SERVICE_TIER_SELECTION, string='服務層級', required=True,
                            default='shared', tracking=True)
    ccu = fields.Integer(string='CCU', default=1)
    billing_cycle = fields.Selection(CYCLES, string='繳費週期', default='monthly',
                                     required=True)
    storage_gb = fields.Integer(string='儲存（GB）')
    committed_qty = fields.Integer(string='承諾筆數')
    committed_usage = fields.Integer(string='每月用量')
    # 驅動因子
    company_count = fields.Integer(string='公司數', default=1)
    user_count = fields.Integer(string='使用者數')
    role_count = fields.Integer(string='角色數')
    integration_count = fields.Integer(string='串接數')
    training_sessions = fields.Integer(string='訓練場次', default=1)

    state = fields.Selection(STATES, default='draft', required=True, copy=False,
                             tracking=True, index=True)
    snapshot_json = fields.Text(string='送出快照', readonly=True, copy=False)
    sale_order_id = fields.Many2one('sale.order', string='報價單', copy=False,
                                    readonly=True)
    feedback_date = fields.Datetime(string='工時回寫時間', readonly=True, copy=False)
    html = fields.Html(string='建議書內容', copy=False, readonly=True)

    pain_ids = fields.One2many('corpaas.knowledge.pain', 'proposal_id', string='痛點',
                               copy=True)
    mapping_ids = fields.One2many('corpaas.knowledge.mapping', 'proposal_id',
                                  string='對應')
    estimate_line_ids = fields.One2many('corpaas.knowledge.estimate_line', 'proposal_id',
                                        string='估算明細')
    master_data_ids = fields.One2many('corpaas.knowledge.proposal.master_data',
                                      'proposal_id', string='資料移轉檢核表', copy=True)

    # 金額（首年）
    subscription_monthly = fields.Monetary(string='訂閱月費', compute='_compute_amounts',
                                           store=True)
    subscription_amount = fields.Monetary(string='訂閱費（首年）', compute='_compute_amounts',
                                          store=True)
    addon_amount = fields.Monetary(string='加購模組（首年）', compute='_compute_amounts',
                                   store=True)
    implementation_days = fields.Float(string='導入人天', compute='_compute_amounts',
                                       store=True)
    implementation_amount = fields.Monetary(string='導入服務', compute='_compute_amounts',
                                            store=True)
    custom_days = fields.Float(string='客製人天', compute='_compute_amounts', store=True)
    custom_amount = fields.Monetary(string='客製開發', compute='_compute_amounts', store=True)
    total = fields.Monetary(string='首年總額', compute='_compute_amounts', store=True)
    pricing_note = fields.Char(string='計價說明', compute='_compute_amounts', store=True)
    # 成本（首年）
    labor_cost = fields.Monetary(string='人力成本', compute='_compute_amounts', store=True)
    infra_monthly_cost = fields.Monetary(string='基礎設施月成本', compute='_compute_amounts',
                                         store=True)
    third_party_monthly = fields.Monetary(string='第三方月費', compute='_compute_amounts',
                                          store=True)
    ai_monthly_cost = fields.Monetary(string='AI 點數月成本', compute='_compute_amounts',
                                      store=True)
    internal_cost = fields.Monetary(string='內部成本（首年）', compute='_compute_amounts',
                                    store=True)
    margin = fields.Monetary(string='毛利', compute='_compute_amounts', store=True)
    margin_rate = fields.Float(string='毛利率（%）', compute='_compute_amounts', store=True)
    cost_is_estimate = fields.Boolean(string='估算值', compute='_compute_amounts', store=True,
                                      help='資源特徵或工時範本尚未校準；成本僅供參考。')
    cost_note = fields.Text(string='成本說明', compute='_compute_amounts', store=True)
    cost_html = fields.Html(string='成本頁', compute='_compute_cost_html', sanitize=False)

    # ------------------------------------------------------------------
    # 基本
    # ------------------------------------------------------------------
    def _internal(self):
        return self.with_context(**{INTERNAL_CTX: INTERNAL_TOKEN})

    @api.model_create_multi
    def create(self, vals_list):
        seq = self.env['ir.sequence']
        for vals in vals_list:
            if not is_internal(self.env) and (
                    vals.get('state', 'draft') != 'draft' or vals.get('snapshot_json')):
                raise UserError(_('建議書只能從草稿建立；狀態與送出快照由「送出」按鈕產生。'))
            if vals.get('name', '/') == '/':
                vals['name'] = seq.next_by_code('corpaas.knowledge.proposal') or '/'
        return super().create(vals_list)

    def write(self, vals):
        if not is_internal(self.env):
            internal_only = INTERNAL_ONLY & set(vals)
            if internal_only:
                raise UserError(_('「%s」只能經由送出／成交／未成交按鈕變更。')
                                % '、'.join(self._fields[k].string for k in sorted(internal_only)))
            frozen = self.filtered(lambda p: p.state != 'draft')
            blocked = {k for k in vals if k not in FROZEN_WRITABLE
                       and not k.startswith(('message_', 'activity_'))}
            if frozen and blocked:
                raise UserError(_('建議書「%(n)s」已送出，不可修改：%(f)s。請按「複製新版」。',
                                  n=frozen[0].name, f=', '.join(sorted(blocked))))
            if vals.get('state') == 'draft' and frozen:
                raise UserError(_('已送出的建議書不能退回草稿；請複製新版。'))
        return super().write(vals)

    def unlink(self):
        if self.filtered(lambda p: p.state != 'draft'):
            raise UserError(_('已送出的建議書不能刪除。'))
        return super().unlink()

    def copy(self, default=None):
        default = dict(default or {}, state='draft')
        return super().copy(default)

    def _ensure_draft(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('建議書「%s」已送出，不能再變更。') % rec.name)

    @api.onchange('product_tmpl_id')
    def _onchange_product_tmpl_id(self):
        tmpl = self.product_tmpl_id
        if not tmpl:
            self.package_id = False
            return
        if self.package_id.product_tmpl_id == tmpl:
            return
        pkgs = tmpl.sudo()._corpaas_solution_packages() \
            if hasattr(tmpl, '_corpaas_solution_packages') else tmpl.sudo().infra_modules_integ_ids
        published = pkgs.filtered(lambda p: 'published_version_id' in p._fields
                                  and p.published_version_id)
        self.package_id = (published or pkgs)[:1]
        allowed = tmpl.sudo()._allowed_tier_list() if hasattr(tmpl, '_allowed_tier_list') else []
        if allowed and self.tier not in allowed:
            self.tier = allowed[0]

    def _ccu_limits(self):
        """(下限, 上限)：方案在這個層級的 CCU 範圍；0＝不限。

        ★ 與 dobtor_corpaas_sale 一致：下限一律套用（`_corpaas_apply_ccu_floor`，拓撲屬性），
          上限只對按 CCU 計費的方案（`_check_ccu_bounds`），非 CCU 計費的方案不取上限。
        """
        self.ensure_one()
        tmpl = self.product_tmpl_id.sudo()
        if not tmpl or not hasattr(tmpl, '_ccu_bounds'):
            return 0, 0
        lo, hi = tmpl._ccu_bounds(self.tier)
        return lo or 0, (hi or 0) if getattr(tmpl, 'bill_by_ccu', False) else 0

    def _effective_ccu(self):
        """報價與報價單用的 CCU：低於下限就拉到下限（報價單行建立時也會被拉上去）。"""
        self.ensure_one()
        return max(self.ccu or 0, self._ccu_limits()[0])

    def _check_ccu_bounds(self):
        for rec in self:
            hi = rec._ccu_limits()[1]
            if hi and rec._effective_ccu() > hi:
                raise UserError(_('方案「%(p)s」在「%(t)s」層的 CCU 上限為 %(h)s，目前 %(c)s。',
                                  p=rec.product_tmpl_id.display_name,
                                  t=dict(SERVICE_TIER_SELECTION).get(rec.tier, rec.tier),
                                  h=hi, c=rec.ccu))

    @api.onchange('product_tmpl_id', 'tier', 'ccu')
    def _onchange_ccu_floor(self):
        if self.product_tmpl_id and (self.ccu or 0) < self._effective_ccu():
            self.ccu = self._effective_ccu()

    @api.onchange('package_id')
    def _onchange_package_id(self):
        if self.scenario_id and self.scenario_id not in self.package_id.knowledge_scenario_ids:
            self.scenario_id = False

    @api.model
    def _settings(self):
        return self.env['res.config.settings'].proposal_settings()

    @api.model
    def _service_product(self):
        pid = self._settings().get('service_product_id')
        prod = self.env['product.product'].sudo().browse(pid).exists() if pid else None
        return prod or self.env.ref(
            'dobtor_corpaas_knowledge_proposal.product_implementation_service',
            raise_if_not_found=False) or self.env['product.product']

    # ------------------------------------------------------------------
    # 查詢輔助
    # ------------------------------------------------------------------
    def _active_mappings(self):
        """進估算與報價的對應：已確認、且不是沿用現況。"""
        self.ensure_one()
        return self.mapping_ids.filtered(lambda m: m.confirmed and m.color != 'as_is')

    def _capabilities(self):
        self.ensure_one()
        return self._active_mappings().mapped('capability_id')

    def _package_capabilities(self):
        self.ensure_one()
        return self.package_id.sudo().knowledge_capability_ids.filtered(
            lambda c: c.state != 'retired')

    def _scenarios(self):
        self.ensure_one()
        if self.scenario_id:
            return self.scenario_id
        return self.package_id.sudo().knowledge_scenario_ids

    def _master_models(self):
        """資料移轉檢核表的模型：情境示範資料用到的模型 ＋ 能力宣告的主資料模型。"""
        self.ensure_one()
        models_ = self._scenario_seed_models()
        for cap in self._capabilities().sudo():
            models_ += [m.strip() for m in (cap.master_data_models or '').splitlines()
                        if m.strip()]
        seen, out = set(), []
        for m in models_:
            if m not in seen:
                seen.add(m)
                out.append(m)
        return out

    def _scenario_seed_models(self):
        self.ensure_one()
        out = []
        for sc in self._scenarios().sudo():
            try:
                out += sc.seed_models()
            except (ValueError, KeyError, TypeError) as e:
                _logger.warning('情境 %s 的示範資料腳本無法解析：%s', sc.code, e)
        return out

    def _records_for(self, capability=None):
        """主資料筆數：指定能力時只算它宣告的模型，否則全部。

        ★ 能力沒宣告主資料模型時，退回情境示範資料用到的模型（資料移轉檢核表的來源），
          不然 records_100 驅動的工項永遠是 0 筆。
        """
        self.ensure_one()
        lines = self.master_data_ids
        if capability:
            wanted = {m.strip() for m in (capability.sudo().master_data_models or '').splitlines()
                      if m.strip()} or set(self._scenario_seed_models())
            lines = lines.filtered(lambda l: l.model in wanted)
        return sum(lines.mapped('record_count'))

    def _driver_qty(self, driver, capability=None):
        self.ensure_one()
        if driver == 'records_100':
            return self._records_for(capability) / 100.0
        return float({
            'companies': self.company_count, 'users': self.user_count,
            'roles': self.role_count, 'integrations': self.integration_count,
            'sessions': self.training_sessions,
        }.get(driver, 0) or 0)

    def _package_variant(self):
        """報價單上的方案變體（與 SO 行實收、開通解析套件同一個變體）。

        ★ 先從方案套件本身取：套件指定了變體（變體專屬）就是它；只掛 template 的通用套件
          才用 template 的變體。☠️ 不能直接拿 template 第一個變體——同一個商品的 17／18 分支
          是不同變體，拿錯會報成另一個版本、開通時也解析到另一個套件。
        ★ 週期兄弟變體只在同一個 branch_name 裡找（`_corpaas_cycle_variant` 不看分支）。
        """
        self.ensure_one()
        tmpl = self.product_tmpl_id.sudo()
        pkg = self.package_id.sudo()
        variant = pkg.product_id if pkg and pkg.product_id else tmpl.product_variant_ids[:1]
        cycle = self.billing_cycle
        if not variant or 'paas_billing_cycle' not in variant._fields:
            return variant
        if cycle and variant.paas_billing_cycle and variant.paas_billing_cycle != cycle:
            branch = variant.branch_name or False
            sibling = variant.product_tmpl_id.product_variant_ids.filtered(
                lambda p: p.paas_billing_cycle == cycle and (p.branch_name or False) == branch)
            variant = sibling[:1] or variant
        return variant

    def _effective_cycle(self, variant):
        rrt = variant.recurring_rule_type if variant and 'recurring_rule_type' in variant._fields \
            else False
        return rrt if rrt in ('monthly', 'quarterly', 'yearly') else 'monthly'

    def _addon_products(self):
        self.ensure_one()
        return self._active_mappings().mapped('addon_product_ids')

    @api.model
    def _addon_first_year_for(self, prod):
        """加購模組的首年金額：訂閱產品依週期換算成一年；報價表每一列與合計用同一支。"""
        prod = prod.sudo()
        if getattr(prod, 'subscription_product', False):
            return prod.lst_price * calc.periods_per_year(
                getattr(prod, 'recurring_rule_type', 'monthly'))
        return prod.lst_price

    # ------------------------------------------------------------------
    # 金額與成本
    # ------------------------------------------------------------------
    def _subscription_price(self):
        """(月費, 首年, 說明)；呼叫 compute_package_price，不自己算。"""
        self.ensure_one()
        tmpl = self.product_tmpl_id.sudo()
        if not tmpl or not hasattr(tmpl, 'compute_package_price'):
            return 0.0, 0.0, _('未選訂閱方案')
        variant = self._package_variant()
        cycle = self._effective_cycle(variant)
        res = tmpl.compute_package_price(
            self.tier, concurrent_users=self._effective_ccu(), committed_qty=self.committed_qty or 0,
            storage_gb=self.storage_gb or 0, cycle=cycle,
            committed_usage=self.committed_usage or 0)
        months = res.get('months') or 1
        note = _('compute_package_price(%(t)s, CCU %(c)s, %(cy)s)',
                 t=self.tier, c=res.get('concurrent_users'), cy=cycle)
        if cycle != self.billing_cycle:
            note += _('；方案沒有「%s」變體，依實際收費週期計') % dict(CYCLES)[self.billing_cycle]
        return res.get('effective_monthly', 0.0), res.get('cycle_total', 0.0) * 12.0 / months, note

    def _addon_first_year(self):
        return sum(self._addon_first_year_for(p) for p in self._addon_products())

    def _infra_base_monthly(self, s):
        """CCU 對應的主機月成本：優先用 dobtor_infrastructure_cost 算出的可信每 CCU 成本。"""
        self.ensure_one()
        Env = self.env['infrastructure.environment'].sudo()
        tmpl = self.product_tmpl_id.sudo()
        if 'cost_per_ccu' in Env._fields and tmpl and hasattr(tmpl, '_tier_ccu_config') \
                and self.tier == 'shared':
            line = tmpl._tier_ccu_config(self.tier)
            envs = line.environment_ids.filtered(
                lambda e: e.cost_reliability == 'ok' and e.cost_per_ccu) if line else Env
            if envs:
                per = sum(envs.mapped('cost_per_ccu')) / len(envs)
                return per * self._effective_ccu(), True
        return self._effective_ccu() * s['cost_per_ccu_monthly'], False

    @api.depends('estimate_line_ids.amount', 'estimate_line_ids.internal_cost',
                 'estimate_line_ids.days', 'estimate_line_ids.is_custom',
                 'estimate_line_ids.template_id.calibration_count',
                 'mapping_ids.confirmed', 'mapping_ids.color', 'mapping_ids.capability_id',
                 'mapping_ids.addon_product_ids', 'master_data_ids.record_count',
                 'product_tmpl_id', 'product_tmpl_id.ccu_tier_line_ids.ccu_min',
                 'package_id', 'tier', 'ccu', 'billing_cycle', 'storage_gb',
                 'committed_qty', 'committed_usage', 'state', 'snapshot_json')
    def _compute_amounts(self):
        s = self._settings()
        for rec in self:
            # ★ 送出後只讀快照：工時回寫會改 calibration_count、牌價會調，
            #   已寄給客戶的金額不能跟著重算。
            if rec.state != 'draft' and rec._apply_snapshot_amounts():
                continue
            try:
                monthly, first_year, note = rec._subscription_price()
            except Exception as e:  # noqa: BLE001 — 價格設定錯誤不能讓整張表單打不開
                _logger.warning('建議書 %s 訂閱計價失敗：%s', rec.name, e)
                monthly, first_year, note = 0.0, 0.0, _('訂閱計價失敗：%s') % e
            lines = rec.estimate_line_ids
            custom = lines.filtered('is_custom')
            impl = lines - custom
            rec.subscription_monthly = monthly
            rec.subscription_amount = first_year
            rec.addon_amount = rec._addon_first_year()
            rec.implementation_days = sum(impl.mapped('days'))
            rec.implementation_amount = sum(impl.mapped('amount'))
            rec.custom_days = sum(custom.mapped('days'))
            rec.custom_amount = sum(custom.mapped('amount'))
            rec.total = rec.subscription_amount + rec.addon_amount \
                + rec.implementation_amount + rec.custom_amount
            rec.pricing_note = note

            reasons = []
            infra, reliable = rec._infra_base_monthly(s)
            if not reliable:
                reasons.append(_('主機成本以設定頁「每 CCU 月成本」估算'))
            infra += (rec.storage_gb or 0) * s['cost_per_gb_monthly']
            third, ai_points = 0.0, 0.0
            uncalibrated = []
            for cap in rec._capabilities().sudo():
                profile = calc.parse_resource_profile(cap.resource_profile)
                if not profile.get('calibrated'):
                    uncalibrated.append(cap.name)
                infra += calc.infra_monthly_for_profile(
                    profile, rec._records_for(cap), s['cost_per_gb_monthly'],
                    s['cost_per_worker_monthly'], s['worker_mb'])
                amount, guessed = calc.parse_third_party_monthly(
                    cap.third_party_costs, s['third_party_default_monthly'])
                third += amount
                if guessed:
                    reasons.append(_('「%s」的第三方費用未寫金額，以預設月費估') % cap.name)
                ai_points += cap.ai_points_monthly or 0.0
            if uncalibrated:
                reasons.append(_('資源特徵未校準：%s') % '、'.join(uncalibrated))
            if lines.filtered(lambda l: l.template_id and not l.template_id.calibration_count):
                reasons.append(_('部分工時範本尚未以實際工時校正'))
            if custom:
                reasons.append(_('客製人天為 AI／人工估計區間的中位數'))
            rec.labor_cost = sum(lines.mapped('internal_cost'))
            rec.infra_monthly_cost = infra
            rec.third_party_monthly = third
            rec.ai_monthly_cost = ai_points * s['ai_point_cost']
            rec.internal_cost = rec.labor_cost + 12.0 * (
                infra + third + rec.ai_monthly_cost)
            rec.margin = rec.total - rec.internal_cost
            rec.margin_rate = rec.margin / rec.total * 100.0 if rec.total else 0.0
            rec.cost_is_estimate = bool(reasons)
            rec.cost_note = '\n'.join(reasons) or False

    def _apply_snapshot_amounts(self):
        self.ensure_one()
        try:
            snap = json.loads(self.snapshot_json or '{}')
        except ValueError:
            return False
        prices, cost = snap.get('prices'), snap.get('cost')
        if not isinstance(prices, dict) or not isinstance(cost, dict):
            return False
        text_fields = ('pricing_note', 'cost_note', 'cost_is_estimate')
        for source, names in ((prices, SNAPSHOT_PRICE_FIELDS), (cost, SNAPSHOT_COST_FIELDS)):
            for name in names:
                value = source.get(name)
                self[name] = (value or False) if name in text_fields else (value or 0.0)
        return True

    def _money(self, amount):
        # ☠️ 新建表單還沒存檔時，非多公司使用者的畫面沒有 company_id 欄位（groups 隱藏），
        #   onchange 帶不到值 → currency_id 是空的，format_amount 在 round() 的
        #   ensure_one 當場炸（管理員有多公司群組所以測不出來）。
        return format_amount(self.env, amount or 0.0,
                             self.currency_id or self.env.company.currency_id)

    @api.depends('internal_cost', 'margin', 'cost_note', 'cost_is_estimate')
    def _compute_cost_html(self):
        for rec in self:
            rec.cost_html = rec._render_cost_html()

    def _render_cost_html(self):
        self.ensure_one()
        rows = [
            (_('人力成本（估算明細 × 內部人天成本）'), self.labor_cost),
            (_('基礎設施（每月 %s × 12）') % self._money(self.infra_monthly_cost),
             self.infra_monthly_cost * 12),
            (_('第三方（每月 %s × 12）') % self._money(self.third_party_monthly),
             self.third_party_monthly * 12),
            (_('AI 點數（每月 %s × 12）') % self._money(self.ai_monthly_cost),
             self.ai_monthly_cost * 12),
            (_('內部成本合計'), self.internal_cost),
            (_('首年營收'), self.total),
            (_('毛利'), self.margin),
        ]
        out = Markup('<h3>%s') % _('成本與毛利（內部）')
        if self.cost_is_estimate:
            out += Markup(' <span class="badge text-bg-warning">%s</span>') % _('估算值')
        out += Markup('</h3>')
        if self.cost_is_estimate:
            out += Markup('<div class="s_alert alert alert-info">%s</div>') % Markup(
                '<br/>').join(escape(r) for r in (self.cost_note or '').splitlines())
        out += Markup('<table class="table table-bordered table-striped align-middle">'
                      '<thead class="table-light"><tr><th>%s</th><th>%s</th></tr></thead><tbody>'
                      ) % (_('項目'), _('金額'))
        for label, amount in rows:
            out += Markup('<tr><td>%s</td><td>%s</td></tr>') % (label, self._money(amount))
        out += Markup('<tr><td>%s</td><td>%.1f%%</td></tr></tbody></table>') % (
            _('毛利率'), self.margin_rate)
        return out

    # ------------------------------------------------------------------
    # AI 比對能力
    # ------------------------------------------------------------------
    def _ai_match_check(self):
        self.ensure_one()
        self._ensure_draft()
        if not self.package_id:
            raise UserError(_('請先選方案套件。'))
        caps = self._package_capabilities()
        if not caps:
            raise UserError(_('方案「%s」還沒有任何能力，無法比對。') % self.package_id.display_name)
        if not self.pain_ids:
            raise UserError(_('請先輸入或匯入痛點。'))
        return caps

    def action_ai_match(self):
        """★ AI 不在 HTTP 請求裡跑：排入佇列（corpaas.knowledge.ai.enqueue），完成後寫進紀錄。"""
        self.ensure_one()
        self._ai_match_check()
        return self.env['corpaas.knowledge.ai'].enqueue(
            self, '_ai_match_run', self.package_id.sudo(), note=_('AI 比對能力'))

    def _ai_match_run(self):
        """佇列作業入口。失敗就 raise：作業記成失敗並貼到建議書紀錄（呼叫帳由 ask() 另開游標記下）。"""
        self.ensure_one()
        caps = self._ai_match_check()
        pains = self.pain_ids
        payload = {
            'pains': [{
                'pain_id': p.id, 'department': p.department or '',
                'description': p.description, 'current_state': p.current_state or '',
                'color_hint': p.color_hint or '', 'module_hint': p.module_hint or '',
                'quote_note': p.quote_note or '',
            } for p in pains],
            'capabilities': [{
                'capability_id': c.id, 'name': c.name, 'code': c.code or '',
                'pain': c.pain or '', 'outcome': c.outcome or '', 'color': c.color,
                'availability': c.availability_for(self.package_id.sudo())[0],
                'feature_classes': self._feature_classes(c),
            } for c in caps.sudo()],
        }
        prompt = AI_MATCH_PROMPT % json.dumps(payload, ensure_ascii=False, indent=1)
        try:
            result = self.env['corpaas.knowledge.ai'].ask(
                'proposal_match', prompt, package=self.package_id.sudo(), record=self)
        except hub_client.BudgetExceeded as e:
            raise UserError(_('AI 預算已用完，請稍後再試：%s') % e) from e
        except hub_client.HubError as e:
            raise UserError(_('AI 比對失敗：%s') % e) from e
        count = self._apply_ai_mappings(result, caps)
        self.message_post(body=_('AI 提議了 %s 筆對應，請逐筆確認。') % count)
        return count

    def _apply_ai_mappings(self, result, caps):
        """把 AI 的 JSON 寫成 mapping；舊的「未確認 AI 提議」先清掉，已確認的保留。"""
        self.ensure_one()
        items = result.get('mappings') if isinstance(result, dict) else result
        if not isinstance(items, list):
            raise UserError(_('AI 回覆格式不對：缺少 mappings 清單。'))
        pains = {p.id: p for p in self.pain_ids}
        caps_by_id = {c.id: c for c in caps}
        colors = dict(COLORS)
        pkg = self.package_id.sudo()
        self.mapping_ids.filtered(lambda m: m.source == 'ai' and not m.confirmed).unlink()
        Mapping = self.env['corpaas.knowledge.mapping']
        count = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            pain = pains.get(_as_int(item.get('pain_id')))
            if not pain:
                continue
            cap = caps_by_id.get(_as_int(item.get('capability_id')))
            color = item.get('color')
            if color not in colors:
                color = cap.color if cap else 'custom'
            notes = [str(item.get('note') or '').strip()]
            vals = {'pain_id': pain.id, 'capability_id': cap.id if cap else False,
                    'color': color, 'source': 'ai'}
            days = item.get('custom_days')
            if color in ('tuning', 'custom') and isinstance(days, (list, tuple)) and days:
                low = _as_float(days[0])
                high = _as_float(days[-1])
                low, high = min(low, high), max(low, high)
                vals.update(custom_days_low=low, custom_days_high=high)
                notes.append(_('客製參考人天：%(l)s～%(h)s 天', l=low, h=high))
            if cap:
                availability, lacking = cap.sudo().availability_for(pkg)
                if availability == 'addon':
                    products, no_product = self._addon_products_for(pkg, lacking)
                    vals['addon_product_ids'] = [(6, 0, products.ids)]
                    notes.append(_('需加購模組：%s') % '、'.join(sorted(lacking)))
                    if no_product:
                        notes.append(_('下列模組可單賣但沒有產品，請人工報價：%s')
                                     % '、'.join(sorted(no_product)))
                elif availability == 'missing':
                    notes.append(_('方案目前不含此能力（缺：%s）') % (
                        '、'.join(sorted(lacking)) or _('功能點已消失')))
            vals['note'] = '\n'.join(n for n in notes if n)
            Mapping.create(vals)
            count += 1
        return count

    def _addon_products_for(self, package, technical_names):
        """缺的模組 → 可單獨販售的產品（每個技術名一個，同名多分支挑與方案同分支的）。

        回傳 (product.product, 找不到產品的技術名 set)。
        """
        mods = self.env['infrastructure.repository.module'].sudo().search([
            ('technical_name', 'in', sorted(technical_names)), ('is_sellable', '=', True),
            ('product_id', '!=', False)])
        branch = package.branch_name if package else False
        products = self.env['product.product']
        missing = set()
        for name in sorted(technical_names):
            same = mods.filtered(lambda m, n=name: m.technical_name == n)
            best = (same.filtered(lambda m: branch and m.product_id.branch_name == branch)
                    or same)[:1]
            if best:
                products |= best.product_id
            else:
                missing.add(name)
        return products, missing

    def _notify(self, message, kind='info'):
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'message': message, 'type': kind, 'sticky': kind != 'success',
                           'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'}}}

    # ------------------------------------------------------------------
    # 計算估算
    # ------------------------------------------------------------------
    def _sync_master_data(self):
        self.ensure_one()
        have = set(self.master_data_ids.mapped('model'))
        new = [m for m in self._master_models() if m not in have]
        if new:
            self.env['corpaas.knowledge.proposal.master_data'].create([
                {'proposal_id': self.id, 'model': m, 'sequence': 10 + i}
                for i, m in enumerate(new)])

    def _estimate_vals(self):
        """依已確認的對應與工時範本產生估算明細 vals。"""
        self.ensure_one()
        s = self._settings()
        Template = self.env['corpaas.knowledge.effort_template'].sudo()
        base = {'proposal_id': self.id, 'day_rate': s['day_rate'],
                'internal_day_cost': s['internal_day_cost']}
        vals, done_caps = [], set()
        for m in self._active_mappings():
            cap = m.capability_id
            templates = Template.search([('capability_id', '=', cap.id)]) if cap else Template
            if cap and cap.id not in done_caps:
                done_caps.add(cap.id)
                for tpl in templates:
                    qty = self._driver_qty(tpl.driver, cap)
                    vals.append(dict(base, mapping_id=m.id, template_id=tpl.id,
                                     capability_id=cap.id, activity=tpl.activity,
                                     driver_qty=qty, days=tpl.days_for(qty)))
            # ★ 設定微調：能力已有工時範本就用範本（範本本來就是「導入這個能力要調的設定」），
            #   不再疊一筆 AI 區間中位數——兩個都算就重複計價。客製開發是範本以外的新工作，照算。
            if m.color == 'tuning' and templates:
                continue
            if m.color in ('tuning', 'custom') and (m.custom_days_low or m.custom_days_high):
                low, high = m.custom_days_low, m.custom_days_high or m.custom_days_low
                vals.append(dict(
                    base, mapping_id=m.id, capability_id=cap.id if cap else False,
                    activity=m.color, days=(low + high) / 2.0,
                    is_custom=m.color == 'custom',
                    note=(m.pain_id.description or '').splitlines()[0][:120]))
        if vals:
            for tpl in Template.search([('capability_id', '=', False)]):
                qty = self._driver_qty(tpl.driver)
                vals.append(dict(base, template_id=tpl.id, activity=tpl.activity,
                                 driver_qty=qty, days=tpl.days_for(qty)))
        return vals

    def action_compute_estimate(self):
        self.ensure_one()
        self._ensure_draft()
        if not self._active_mappings():
            raise UserError(_('還沒有已確認的痛點對應；請先確認對應再計算估算。'))
        self._sync_master_data()
        self.estimate_line_ids.unlink()
        self.env['corpaas.knowledge.estimate_line'].create(self._estimate_vals())
        self.action_render_html()
        return True

    # ------------------------------------------------------------------
    # 建議書 HTML
    # ------------------------------------------------------------------
    def _pitches_for(self, capability):
        """行銷層已核准上線的 pitch（有上線快照的；編輯中／送審中的也照用上線版）。"""
        if 'corpaas.knowledge.pitch' not in self.env:
            return []
        Pitch = self.env['corpaas.knowledge.pitch'].sudo()
        domain = [('capability_id', '=', capability.id), ('live_json', '!=', False),
                  ('state', '!=', 'retired')]
        if self.product_tmpl_id:
            domain += [('product_tmpl_id', '=', self.product_tmpl_id.id)]
        pitches = Pitch.search(domain)
        if self.package_id and 'package_id' in Pitch._fields:
            pitches = pitches.filtered(
                lambda p: not p.package_id or p.package_id == self.package_id) or pitches
        if self.scenario_id:
            scoped = pitches.filtered(lambda p: p.scenario_id == self.scenario_id)
            pitches = scoped or pitches.filtered(lambda p: not p.scenario_id)
        return pitches[:1]

    def _feature_classes(self, cap):
        """{分類: 功能點數}，加上是否含方案核心。"""
        out = {}
        pkg = self.package_id.sudo()
        if not pkg:
            return out
        for c in self.env['corpaas.knowledge.feature.class'].sudo().search([
                ('package_id', '=', pkg.id), ('feature_id', 'in', cap.feature_ids.ids)]):
            out[c.classification] = out.get(c.classification, 0) + 1
            if c.core:
                out['core'] = True
        return out

    def _flow_html(self, cap):
        """能力底下的作業流程（K26）：已核准的流程依步驟列出，給客戶看「實際怎麼走」。"""
        outlines = cap._knowledge_flow_outlines(self.package_id.sudo())
        if not outlines:
            return Markup('')
        out = Markup('<p><strong>%s</strong></p>') % _('作業流程：')
        for fl in outlines:
            steps = [s['label'] for s in fl['steps'] if s.get('on_statusbar')] \
                or [s['label'] for s in fl['steps']]
            out += Markup('<p>%s：%s</p>') % (fl['name'], ' → '.join(steps))
        return out

    @staticmethod
    def _pitch_live(pitch):
        """★ 只讀核准快照，絕不讀草稿欄位（headline／body_html 可能是還沒核准的改寫）。"""
        live = pitch._live() if hasattr(pitch, '_live') else {}
        return live.get('headline') or '', live.get('body_html') or '', \
            pitch._live_claims() if hasattr(pitch, '_live_claims') else live.get('claims') or []

    def _render_html(self):
        self.ensure_one()
        tier_label = dict(SERVICE_TIER_SELECTION).get(self.tier, self.tier)
        color_label = dict(COLORS)
        table = Markup('<table class="table table-bordered table-striped align-middle">'
                       '<thead class="table-light"><tr>%s</tr></thead><tbody>')

        def head(*cols):
            return table % Markup('').join(Markup('<th>%s</th>') % c for c in cols)

        def row(*cells):
            return Markup('<tr>%s</tr>') % Markup('').join(Markup('<td>%s</td>') % c for c in cells)

        def para(text):
            return Markup('<br/>').join(escape(t) for t in (text or '').splitlines())

        def badge(color):
            return Markup('<span class="badge %s">%s</span>') % (
                COLOR_BADGE.get(color, 'text-bg-secondary'), color_label.get(color, color))

        out = Markup('<h1>%s</h1>') % _('服務建議書')
        out += Markup('<p>%s</p>') % _('%(p)s ／ %(pkg)s（%(t)s，%(c)s CCU）',
                                       p=self.partner_id.display_name,
                                       pkg=self.product_tmpl_id.display_name or '',
                                       t=tier_label, c=self._effective_ccu())
        narratives = [sc.narrative for sc in self._scenarios().sudo() if sc.narrative]
        if narratives:
            out += Markup('<div class="s_alert alert alert-info">%s</div>') % para(narratives[0])

        out += Markup('<h2>%s</h2>') % _('一、痛點與解決方式')
        out += head(_('部門'), _('痛點'), _('對應能力'), _('分類'), _('說明'))
        for pain in self.pain_ids:
            maps = pain.mapping_ids.filtered('confirmed') or pain.mapping_ids
            if not maps:
                out += row(pain.department or '', para(pain.description), '', '', '')
            for m in maps:
                out += row(pain.department or '', para(pain.description),
                           m.capability_id.name or _('客製'), badge(m.color), para(m.note))
        out += Markup('</tbody></table>')

        caps = self._capabilities().sudo()
        if caps:
            out += Markup('<h2>%s</h2>') % _('二、方案能力')
            for cap in caps:
                pitch = self._pitches_for(cap)
                if pitch:
                    headline, body, claims = self._pitch_live(pitch)
                    out += Markup('<h3>%s</h3>') % (headline or cap.name)
                    out += Markup(body)
                    if claims:
                        out += Markup('<ul>%s</ul>') % Markup('').join(
                            Markup('<li>%s</li>') % c for c in claims)
                    out += self._flow_html(cap)
                    continue
                out += Markup('<h3>%s %s</h3>') % (cap.name, badge(cap.color))
                if cap.pain:
                    out += Markup('<p><strong>%s</strong>%s</p>') % (_('解決的痛點：'), para(cap.pain))
                if cap.outcome:
                    out += Markup('<p><strong>%s</strong>%s</p>') % (_('帶來的成果：'),
                                                                    para(cap.outcome))
                out += self._flow_html(cap)

        out += Markup('<h2>%s</h2>') % _('三、報價')
        out += head(_('項目'), _('內容'), _('金額（首年）'))
        out += row(_('訂閱方案'), _('%(pkg)s・%(t)s・%(c)s CCU・月費 %(m)s',
                                  pkg=self.product_tmpl_id.display_name or '', t=tier_label,
                                  c=self._effective_ccu(),
                                  m=self._money(self.subscription_monthly)),
                   self._money(self.subscription_amount))
        for prod in self._addon_products():
            out += row(_('加購模組'), prod.display_name,
                       self._money(self._addon_first_year_for(prod)))
        labels = dict(self.env['corpaas.knowledge.estimate_line']._fields['activity'].selection)
        for line in self.estimate_line_ids.filtered(lambda l: not l.is_custom):
            out += row(_('導入服務'), _('%(c)s／%(a)s：%(d)s 人天',
                                      c=line.capability_id.name or _('通用'),
                                      a=labels.get(line.activity), d=line.days),
                       self._money(line.amount))
        for line in self.estimate_line_ids.filtered('is_custom'):
            out += row(_('客製開發'), _('%(n)s：%(d)s 人天', n=line.note or line.capability_id.name
                                      or '', d=line.days), self._money(line.amount))
        out += row(Markup('<strong>%s</strong>') % _('合計'), '',
                   Markup('<strong>%s</strong>') % self._money(self.total))
        out += Markup('</tbody></table>')
        rate = self.estimate_line_ids[:1].day_rate or self._settings()['day_rate']
        out += Markup('<p>%s</p>') % (_('導入服務以人天計價，日費率 %s；客製開發為估計區間中位數，'
                                       '確認規格後另行報價。') % self._money(rate))

        if self.master_data_ids:
            out += Markup('<h2>%s</h2>') % _('四、需要貴公司提供的資料（資料移轉檢核表）')
            out += head(_('資料'), _('系統模型'), _('預估筆數'), _('已提供'))
            for md in self.master_data_ids:
                out += row(md.model_label or md.model, md.model, md.record_count or '',
                           _('是') if md.provided else '')
            out += Markup('</tbody></table>')
        return out

    def action_render_html(self):
        for rec in self:
            rec._ensure_draft()
            rec.html = rec._render_html()
        return True

    # ------------------------------------------------------------------
    # 報價單、送出、成交
    # ------------------------------------------------------------------
    def action_create_sale_order(self):
        self.ensure_one()
        if self.sale_order_id:
            return self.action_open_sale_order()
        if not self.product_tmpl_id:
            raise UserError(_('請先選訂閱方案。'))
        self._check_ccu_bounds()
        if self.state != 'draft':
            self._check_snapshot_prices()
        service = self._service_product()
        if self.estimate_line_ids and not service:
            raise UserError(_('請先在設定頁指定「導入服務產品」。'))
        # ★ 不標 is_to_create_paas：建議書來的報價單確認時不自動開通（既有客戶多半是
        #   疊加或換層級，預設開一座新平台是錯的）。確認後由業務按「確認開通」選模式。
        order = self.env['sale.order'].create({
            'partner_id': self.partner_id.id, 'origin': self.name,
            'user_id': self.user_id.id, 'company_id': self.company_id.id,
            'knowledge_proposal_id': self.id, 'knowledge_provision_state': 'hold'})
        Line = self.env['sale.order.line']
        pkg_vals = {'order_id': order.id, 'product_id': self._package_variant().id,
                    'product_uom_qty': 1}
        for field, value in (('package_tier', self.tier),
                             ('concurrent_users', self._effective_ccu()),
                             ('storage_gb', self.storage_gb),
                             ('committed_qty', self.committed_qty),
                             ('committed_usage', self.committed_usage)):
            if field in Line._fields:
                pkg_vals[field] = value
        vals_list = [pkg_vals]
        for prod in self._addon_products():
            vals_list.append({'order_id': order.id, 'product_id': prod.id, 'product_uom_qty': 1})
        labels = dict(self.env['corpaas.knowledge.estimate_line']._fields['activity'].selection)
        for line in self.estimate_line_ids.sorted(lambda l: (l.is_custom, l.id)):
            if not line.days:
                continue
            name = _('%(k)s：%(c)s／%(a)s', k=_('客製開發') if line.is_custom else _('導入服務'),
                     c=line.capability_id.name or _('通用'), a=labels.get(line.activity))
            if line.note:
                name += '（%s）' % line.note
            vals_list.append({'order_id': order.id, 'product_id': service.id, 'name': name,
                              'product_uom_qty': line.days, 'price_unit': line.day_rate})
        Line.create(vals_list)
        self.sale_order_id = order.id
        self.message_post(body=_('已建立報價單 %s') % order.name)
        return self.action_open_sale_order()

    def _check_snapshot_prices(self):
        """已送出的建議書建報價單：牌價若已調整，報價單會跟寄出的金額對不上 → 擋下。

        ★ 不把快照價硬寫進報價單行：dobtor_corpaas_sale 的自計費方案行 `_compute_price_unit`
          不理會手動價，CCU／數量／層級一有變動（連建行時的 CCU 下限拉高都算）就依牌價重算蓋掉；
          寫了也守不住。導入服務行用的是估算明細凍結的日費率，本來就與快照一致。
        """
        self.ensure_one()
        try:
            prices = json.loads(self.snapshot_json or '{}').get('prices') or {}
        except ValueError:
            prices = {}
        cur = self.currency_id or self.env.company.currency_id
        diffs = []
        _monthly, first_year, _note = self._subscription_price()
        for label, live, key in ((_('訂閱費'), first_year, 'subscription_amount'),
                                 (_('加購模組'), self._addon_first_year(), 'addon_amount')):
            sent = prices.get(key) or 0.0
            if cur.compare_amounts(live, sent):
                diffs.append(_('%(l)s：送出時 %(s)s，現在 %(n)s',
                               l=label, s=self._money(sent), n=self._money(live)))
        if diffs:
            raise UserError(_('建議書「%(n)s」送出後牌價已調整，報價單會與寄給客戶的金額不同：\n%(d)s\n'
                              '請按「複製新版」重新送出後再建立報價單。',
                              n=self.name, d='\n'.join(diffs)))

    def action_open_sale_order(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'sale.order',
                'res_id': self.sale_order_id.id, 'view_mode': 'form', 'target': 'current'}

    def _snapshot(self):
        self.ensure_one()
        caps = self._capabilities().sudo()
        return {
            'sent_at': fields.Datetime.to_string(fields.Datetime.now()),
            'partner': self.partner_id.display_name,
            'product': self.product_tmpl_id.display_name or False,
            'package_id': self.package_id.id or False,
            'tier': self.tier, 'ccu': self._effective_ccu(), 'billing_cycle': self.billing_cycle,
            'drivers': {'companies': self.company_count, 'users': self.user_count,
                        'roles': self.role_count, 'integrations': self.integration_count,
                        'sessions': self.training_sessions},
            'narrative': [sc.narrative for sc in self._scenarios().sudo() if sc.narrative],
            'capabilities': [{'id': c.id, 'code': c.code, 'name': c.name, 'color': c.color,
                              'pain': c.pain, 'outcome': c.outcome,
                              'rev_no': c.rev_no} for c in caps],
            'pains': [{'department': p.department, 'description': p.description,
                       'mappings': [{'capability': m.capability_id.name or False,
                                     'color': m.color, 'confirmed': m.confirmed,
                                     'addon_products': m.addon_product_ids.mapped('display_name'),
                                     'custom_days': [m.custom_days_low, m.custom_days_high],
                                     'note': m.note} for m in p.mapping_ids]}
                      for p in self.pain_ids],
            'lines': [{'capability': l.capability_id.name or False, 'activity': l.activity,
                       'template_id': l.template_id.id or False, 'driver_qty': l.driver_qty,
                       'days': l.days, 'day_rate': l.day_rate,
                       'internal_day_cost': l.internal_day_cost, 'amount': l.amount,
                       'internal_cost': l.internal_cost, 'is_custom': l.is_custom,
                       'note': l.note} for l in self.estimate_line_ids],
            'master_data': [{'model': m.model, 'records': m.record_count,
                             'provided': m.provided} for m in self.master_data_ids],
            'prices': {k: self[k] for k in (
                'subscription_monthly', 'subscription_amount', 'addon_amount',
                'implementation_days', 'implementation_amount', 'custom_days',
                'custom_amount', 'total', 'pricing_note')},
            'cost': {k: self[k] for k in (
                'labor_cost', 'infra_monthly_cost', 'third_party_monthly', 'ai_monthly_cost',
                'internal_cost', 'margin', 'margin_rate', 'cost_is_estimate', 'cost_note')},
            'html': str(self.html or ''),
        }

    def action_send(self):
        for rec in self:
            rec._ensure_draft()
            if not rec.estimate_line_ids and not rec.product_tmpl_id:
                raise UserError(_('建議書沒有方案也沒有估算，無法送出。'))
            rec._check_ccu_bounds()
            if rec.ccu != rec._effective_ccu():
                rec.ccu = rec._effective_ccu()
            rec.action_render_html()
            rec.flush_recordset()
            snap = json.dumps(rec._snapshot(), ensure_ascii=False, default=str)
            rec._internal().write({'state': 'sent', 'snapshot_json': snap})
        return True

    def action_mark_won(self):
        self.filtered(lambda p: p.state == 'sent')._internal().write({'state': 'won'})
        return True

    def action_mark_lost(self):
        self.filtered(lambda p: p.state == 'sent')._internal().write({'state': 'lost'})
        return True

    def action_copy_new_version(self):
        self.ensure_one()
        new = self.copy()
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': new.id,
                'view_mode': 'form', 'target': 'current'}

    def action_open_import(self):
        self.ensure_one()
        self._ensure_draft()
        return {'type': 'ir.actions.act_window', 'name': _('匯入售前痛點'),
                'res_model': 'corpaas.knowledge.proposal.import', 'view_mode': 'form',
                'target': 'new', 'context': {'default_proposal_id': self.id}}

    # ------------------------------------------------------------------
    # 工時回寫
    # ------------------------------------------------------------------
    def _timesheet_rows(self):
        """[(說明文字, 小時, [任務標籤])]：報價單關聯專案的 timesheet。"""
        self.ensure_one()
        AAL = self.env['account.analytic.line'].sudo()
        order = self.sale_order_id.sudo()
        projects = self.env['project.project'].sudo()
        if 'project_ids' in order._fields:
            projects |= order.project_ids
        if 'project_id' in order._fields:
            projects |= order.project_id
        if 'reinvoiced_sale_order_id' in projects._fields:
            projects |= projects.search([('reinvoiced_sale_order_id', '=', order.id)])
        lines = AAL.search([('project_id', 'in', projects.ids)]) if projects else AAL
        if 'so_line' in AAL._fields and order.order_line:
            lines |= AAL.search([('so_line', 'in', order.order_line.ids),
                                 ('project_id', '!=', False)])
        rows = []
        for l in lines:
            task = l.task_id
            text = ' '.join(filter(None, [l.name, task.name]))
            rows.append((text, l.unit_amount, task.tag_ids.mapped('name')))
        return rows

    @staticmethod
    def _tokens(text, tags=()):
        """比對用的詞：說明／任務名依空白與括號標點斷開，任務標籤整個當一個詞；一律小寫。

        ☠️ 不用子字串比對：能力 code「pm」會命中「npm」、「event」會命中「event_reg」。
        """
        words = {w.strip().lower() for w in _TOKEN_SPLIT.split(text or '') if w.strip()}
        words |= {str(t).strip().lower() for t in tags or () if str(t).strip()}
        return words

    def _actuals_from_rows(self, rows):
        """{(capability_id|False, activity): 實際人天}。

        能力：詞裡有能力 code（完整一個詞）；工項：詞裡有工項代碼、中文名稱或別名。
        ★ 沒有能力 code 的工時不列入（歸不到任何能力的範本）；通用工項要明確標「通用」。
          對不到工項的工時也不列入。
        """
        self.ensure_one()
        hours_per_day = self._settings()['hours_per_day'] or 8.0
        caps = self.estimate_line_ids.mapped('capability_id').filtered('code')
        codes = {c.code.strip().lower(): c.id for c in caps}
        acts = {}
        for key, label in ACTIVITIES:
            for word in (key, label) + ACTIVITY_ALIASES.get(key, ()):
                acts.setdefault(word.lower(), key)
        out = {}
        for row in rows:
            text, hours = row[0], row[1]
            tags = row[2] if len(row) > 2 else ()
            words = self._tokens(text, tags)
            found = {acts[w] for w in words if w in acts}
            if len(found) != 1:
                # 沒寫工項，或同一筆寫了兩個工項（分不出來）→ 不列入
                continue
            activity = found.pop()
            cap_ids = {codes[w] for w in words if w in codes}
            if len(cap_ids) == 1:
                cap_id = cap_ids.pop()
            elif not cap_ids and words & GENERIC_TOKENS:
                cap_id = False
            else:
                continue
            key = (cap_id, activity)
            out[key] = out.get(key, 0.0) + float(hours or 0.0) / hours_per_day
        return out

    def _apply_actuals(self, actuals):
        """依實際人天校正工時範本；同一建議書對同一範本只校正一次。"""
        self.ensure_one()
        window = self._settings()['calibration_window']
        Calibration = self.env['corpaas.knowledge.effort_calibration'].sudo()
        done = 0
        for line in self.estimate_line_ids.filtered(lambda l: l.template_id and not l.is_custom):
            key = (line.capability_id.id or False, line.activity)
            if key not in actuals:
                continue
            tpl = line.template_id.sudo()
            if Calibration.search_count([('template_id', '=', tpl.id),
                                         ('proposal_id', '=', self.id)]):
                continue
            tpl.calibrate(actuals[key], line.driver_qty, proposal=self, window=window)
            done += 1
        return done

    def action_feedback_actuals(self):
        self.ensure_one()
        if self.state not in ('sent', 'won'):
            raise UserError(_('只有已送出或成交的建議書可以回寫工時。'))
        if not self.sale_order_id:
            raise UserError(_('這張建議書還沒有報價單，找不到專案工時。'))
        if 'account.analytic.line' not in self.env \
                or 'project_id' not in self.env['account.analytic.line']._fields:
            raise UserError(_('需要安裝工時表（hr_timesheet）才能回寫工時。'))
        actuals = self._actuals_from_rows(self._timesheet_rows())
        done = self._apply_actuals(actuals)
        self.feedback_date = fields.Datetime.now()
        self.message_post(body=_('工時回寫：校正了 %s 個工時範本。') % done)
        return self._notify(_('校正了 %s 個工時範本。') % done,
                            'success' if done else 'warning')


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _as_float(value):
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0
