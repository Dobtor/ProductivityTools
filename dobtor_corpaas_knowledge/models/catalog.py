# -*- coding: utf-8 -*-
"""能力、情境、示範資料包、素材、圈選提案。"""
import html as html_mod
import logging
import json
import re

from ..services import search_lib

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)


def glossary_text(value):
    """AI 回的用語對照 → 「原詞=情境用語」一行一組。

    ★ 只收真的是對照的格式（字串、{原詞: 用語}、[{"from","to"}]）；名詞解釋
      （[{"term","definition"}]）不是對照，丟掉——套用時會把原詞整個換成一段解釋。
      ☠️ 實機：提示沒講格式，AI 回了名詞解釋，核准時整段被丟、情境沒有用語對照。"""
    if isinstance(value, str):
        return value.strip() or False
    pairs = []
    if isinstance(value, dict):
        pairs = [(k, v) for k, v in value.items() if isinstance(v, str)]
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, dict) and isinstance(item.get('from'), str) \
                    and isinstance(item.get('to'), str):
                pairs.append((item['from'], item['to']))
    lines = ['%s=%s' % (a.strip(), b.strip()) for a, b in pairs
             if a.strip() and b.strip() and '=' not in a and len(b.strip()) <= 20]
    return '\n'.join(lines) or False

#: 起草／修正示範資料的共同規則（2026-10 實機：AI 起草 82 筆有 36 筆錯、89 個畫面 52 個空白，
#: 錯在重複建產品變體、日記帳缺必填、完全沒有確認／過帳步驟）
SEED_RULES = (
    "★ 產品只建 product.product（範本會自動產生），不要同一個產品再建 product.template。\n"
    "★ 單據頭與明細分開成兩筆（sale.order 與 sale.order.line 各自一個 xmlid，明細用 order_id 參照頭）。\n"
    "★ 不要建會計科目、日記帳、稅、付款條件這類系統已有的設定，沿用系統既有的。\n"
    "★ 狀態不要直接寫 state，用動作步驟推進：{\"xmlid\":\"so_01_confirm\",\"model\":\"sale.order\","
    "\"call\":\"action_confirm\",\"ref\":\"so_01\"}；可用的有 sale.order action_confirm、"
    "purchase.order button_confirm、account.move action_post、account.payment action_post、"
    "stock.picking action_confirm／button_validate、stock.scrap action_validate。"
    "每類單據要有草稿、已確認、已完成各至少一筆，清單才看得到不同狀態。\n"
    "★ 單據的負責人指定角色帳號（可用：%(roles)s），例如 \"user_id\": \"__ref__:user_sales\"。\n"
    "★ 公司與倉庫改成情境裡的名稱：{\"xmlid\":\"base.main_company\",\"model\":\"res.company\","
    "\"values\":{\"name\":…}}、stock.warehouse0 同理。\n"
    "★ 角色帳號的聯絡人可用 __ref__:user_<角色>_partner 參照（例如 __ref__:user_member_partner）。"
    "方案有網站會員（user_member）時，替會員的聯絡人建 2–3 張已確認的銷售訂單與已過帳的發票"
    "（partner_id 用 __ref__:user_member_partner），前台「我的訂單／我的發票」才有內容。\n")

#: 會改變畫面（多出公司切換、幣別欄位）的設定群組：拍照角色一律不給，免得截圖跟一般租戶看到的不同
SCREEN_CHANGING_GROUPS = ('base.group_multi_company', 'base.group_multi_currency')

def seed_contract_errors(records):
    """示範資料腳本的結構契約（AI 回覆先過這關，不符就帶著錯誤重問）。"""
    errs = []
    if not isinstance(records, list):
        return ['seed 必須是清單']
    for r in records:
        if not isinstance(r, dict) or not r.get('xmlid'):
            errs.append('每筆都要有 xmlid：%s' % str(r)[:60])
            continue
        if r.get('call'):
            if not re.match(r'^(action|button)_[a-z0-9_]+$', str(r['call'])) or not r.get('ref'):
                errs.append('%s：動作步驟要有 ref，方法名以 action_／button_ 開頭' % r['xmlid'])
            continue
        if not r.get('model'):
            errs.append('%s：缺 model' % r['xmlid'])
        if r.get('model') == 'product.template':
            errs.append('%s：產品請建 product.product，不要建 product.template' % r['xmlid'])
        if r.get('model') == 'res.company' and r['xmlid'] != 'base.main_company':
            # ☠️ 實機：AI 想改公司名卻用了新 xmlid，多出一家公司，記錄規則把單據擋成存取錯誤
            errs.append('%s：不要新建公司，改名請用 xmlid base.main_company' % r['xmlid'])
        if 'state' in (r.get('values') or {}):
            errs.append('%s：不要直接寫 state，用動作步驟推進' % r['xmlid'])
    return errs


#: 重播檢查有問題時 AI 自動修正的次數上限
MAX_SEED_REPAIRS = 2

SEED_CHECK_STATES = [('queued', '排隊中'), ('running', '檢查中'), ('ok', '通過'),
                     ('issues', '有問題'), ('failed', '檢查失敗')]


def qualify_seed_record(rec, module, leaf_module, role_names=()):
    """把一筆示範資料的短名（自己、參照、動作對象）展開成完整 xmlid。

    module：這筆資料所屬來源（資料包或情境）的命名空間；角色帳號 user_<code> 例外，
    建在 leaf_module（最末端情境）。"""
    def full(x):
        if '.' in x:
            return x
        return '%s.%s' % (leaf_module if x in role_names else module, x)

    def ref(v):
        if isinstance(v, str) and v.startswith('__ref__:'):
            return '__ref__:' + full(v[8:])
        if isinstance(v, list) and v and all(
                isinstance(x, str) and x.startswith('__ref__:') for x in v):
            return ['__ref__:' + full(x[8:]) for x in v]
        return v

    out = dict(rec, xmlid=full(rec['xmlid']))
    if rec.get('ref'):
        out['ref'] = full(rec['ref'])
    if 'values' in rec:
        out['values'] = {k: ref(v) for k, v in (rec.get('values') or {}).items()}
    return out


COLORS = [
    ('native', '原生'),
    ('dobtor', 'Dobtor 標準'),
    ('tuning', '設定微調'),
    ('custom', '客製'),
    ('as_is', '沿用現況'),
]


class KnowledgeCapability(models.Model):
    _name = 'corpaas.knowledge.capability'
    _description = '能力（業務語言的賣點／報價單位）'
    _inherit = ['corpaas.knowledge.content.mixin']
    _order = 'sequence, name'

    sequence = fields.Integer(default=10)
    name = fields.Char(required=True, tracking=True)
    code = fields.Char(help='穩定代碼，章節對應與商品頁錨點用；沒填自動產生')
    feature_ids = fields.Many2many(
        'corpaas.knowledge.feature', 'corpaas_knowledge_capability_feature_rel',
        'capability_id', 'feature_id', string='功能點')
    flow_ids = fields.One2many('corpaas.knowledge.flow', 'capability_id', string='流程')
    required_module_names = fields.Text(string='必要模組', help='一行一個技術名')
    scenario_ids = fields.Many2many('corpaas.knowledge.scenario', string='適用情境')
    package_ids = fields.Many2many(
        'infrastructure.solution.package', 'corpaas_knowledge_capability_package_rel',
        'capability_id', 'package_id', string='方案')
    roles = fields.Char(string='適用角色')
    # 價值
    pain = fields.Text(string='解決的痛點')
    outcome = fields.Text(string='帶來的成果')
    differentiator = fields.Text(string='差異化')
    color = fields.Selection(COLORS, string='四色分類', default='native')
    # 估算與成本（proposal 出口使用；核心只存資料）
    master_data_models = fields.Text(string='需要的主資料模型',
                                     help='一行一個 model；情境腳本建立時自動補')
    third_party_costs = fields.Text(string='第三方費用說明')
    resource_profile = fields.Text(string='資源特徵', help='JSON：heavy_cron / storage_per_record_kb / extra_worker_mb')
    ai_points_monthly = fields.Float(string='每月 AI 點數估計')

    _sql_constraints = [('code_unique', 'unique(code)', '能力代碼重複')]

    def _knowledge_revision_fields(self):
        return ['name', 'pain', 'outcome', 'differentiator', 'color']

    @api.model_create_multi
    def create(self, vals_list):
        """★ 能力一定要有 code：AI 歸類只能用 code 指名既有能力，沒有 code 的能力
        AI 永遠指名不到，下次又提一個新的——重複就是這樣累積出來的。"""
        recs = super().create(vals_list)
        for rec in recs.filtered(lambda r: not r.code):
            rec.code = rec._knowledge_make_code()
        return recs

    def _knowledge_make_code(self):
        self.ensure_one()
        base = re.sub(r'[^a-z0-9]+', '_', (self.name or '').lower()).strip('_')
        code = base if base and len(base) >= 3 else 'cap_%s' % self.id
        if self.search_count([('code', '=', code), ('id', '!=', self.id)]):
            code = '%s_%s' % (code, self.id)
        return code

    def _knowledge_flow_outlines(self, package):
        """這個能力在方案裡的已核准流程（有業務名稱的）精簡結構，給出口展開步驟（K26）。"""
        self.ensure_one()
        flows = self.sudo().flow_ids.filtered(
            lambda f: f.ai_name and (not package or package in f.package_ids))
        return [f.as_outline() for f in flows.sorted(lambda f: -f.usage_score)]

    def action_approve_proposals(self):
        """批次層：一次核准所有「歸入這個能力」的待審功能提案。"""
        props = self.env['corpaas.knowledge.selection'].search([
            ('capability_id', 'in', self.ids), ('state', '=', 'proposed')])
        return props.action_approve()

    @api.model
    def _knowledge_find_by_name(self, name):
        """名稱正規化後相同的既有能力（「訂單 管理」＝「訂單管理」）。"""
        key = search_lib.normalize_name(name)
        if not key:
            return self.browse()
        return self.search([]).filtered(
            lambda c: search_lib.normalize_name(c.name) == key)[:1]

    @api.model
    def _knowledge_similar(self, name, limit=3, threshold=0.4):
        """名稱相近的既有能力（核准新能力前的查重提示），相似度高的在前。"""
        if not name:
            return self.browse()
        scored = [(c, search_lib.similarity(name, c.name)) for c in self.search([])]
        scored = [x for x in scored if x[1] >= threshold]
        scored.sort(key=lambda x: -x[1])
        return self.browse([c.id for c, _s in scored[:limit]])

    def required_modules(self):
        self.ensure_one()
        return {m.strip() for m in (self.required_module_names or '').splitlines()
                if m.strip()}

    def availability_for(self, package):
        """('available'|'addon'|'missing', 缺的模組集合)。

        ★ 可用性由系統算：方案 BOM 包含必要模組、功能點都在且沒有消失 → available；
          只缺可單獨販售的模組 → addon（加購可得）；其他 → missing。
        """
        self.ensure_one()
        have = package._knowledge_available_modules()
        need = self.required_modules() | set(self.feature_ids.mapped('module'))
        lacking = need - have
        if not lacking:
            if any(f.missing for f in self.feature_ids):
                return 'missing', set()
            return 'available', set()
        sellable = self.env['infrastructure.repository.module'].sudo().search([
            ('technical_name', 'in', list(lacking)), ('is_sellable', '=', True)])
        if set(sellable.mapped('technical_name')) >= lacking:
            return 'addon', lacking
        return 'missing', lacking


class KnowledgeScenario(models.Model):
    _name = 'corpaas.knowledge.scenario'
    _description = '情境（示範資料＋應用背景）'
    _inherit = ['corpaas.knowledge.content.mixin']
    _order = 'sequence, name'

    sequence = fields.Integer(default=10)
    name = fields.Char(required=True, tracking=True)
    code = fields.Char(required=True, help='英數底線；示範資料的 xmlid 命名空間 '
                                          '__doc_scenario_<code>')
    parent_id = fields.Many2one('corpaas.knowledge.scenario', string='繼承自',
                                ondelete='restrict')
    is_base = fields.Boolean(string='基底情境')
    package_ids = fields.Many2many(
        'infrastructure.solution.package', 'corpaas_knowledge_scenario_package_rel',
        'scenario_id', 'package_id', string='引用的方案')
    required_module_names = fields.Text(string='必要模組', help='一行一個技術名')
    glossary = fields.Text(string='用語對照', help='一行一組：原詞=情境用語')
    narrative = fields.Text(string='情境敘事')
    role_ids = fields.Many2many('corpaas.knowledge.role', string='角色')
    seed_json = fields.Text(string='示範資料腳本',
                            help='[{"xmlid","model","values"}]；__ref__:<xmlid> 參照')
    seed_error = fields.Text(string='最近一次重播錯誤', readonly=True)
    pack_ids = fields.Many2many(
        'corpaas.knowledge.seed_pack', 'corpaas_knowledge_scenario_pack_rel',
        'scenario_id', 'pack_id', string='示範資料包',
        help='情境＝選哪些資料包＋用語＋敘事（A3）。資料包先重播（含它依賴的包），'
             '再重播情境自己的腳本；同 xmlid 以後者為準。')
    seed_check_state = fields.Selection(SEED_CHECK_STATES, string='重播檢查', readonly=True,
                                        copy=False)
    seed_check_at = fields.Datetime(string='檢查時間', readonly=True, copy=False)
    seed_check_report = fields.Text(readonly=True, copy=False,
                                    help='{"errors": [...], "counts": {功能鍵: 筆數}, "labels": {...}}')
    seed_check_html = fields.Html(string='重播檢查結果', compute='_compute_seed_check_html',
                                  sanitize=False)
    shot_gaps = fields.Text(string='拍照空白畫面', readonly=True, copy=False,
                            help='上一次拍照時「畫面是空白引導頁」的畫面名稱（JSON 清單）；'
                                 'AI 組裝／修正示範資料時優先補這些')
    seed_auto_repairs = fields.Integer(string='自動修正次數', readonly=True, copy=False,
                                       help='重播檢查有錯時 AI 自動修正的次數（每份起草只修一次）')
    clean_approvals = fields.Integer(string='連續無修改核准次數', readonly=True)
    auto_text_after = fields.Integer(string='連續幾次後文字改寫免審', default=5)

    _sql_constraints = [('code_unique', 'unique(code)', '情境代碼重複')]

    @property
    def xml_module(self):
        return '__doc_scenario_%s' % self.code

    def _knowledge_revision_fields(self):
        return ['name', 'glossary', 'narrative', 'seed_json', 'required_module_names',
                'pack_ids']

    def _knowledge_requires_review(self, change):
        self.ensure_one()
        if change == 'shot':
            return False
        # ★ 被兩個以上方案引用的情境：錯了會同時汙染多個 channel，一律核准。
        return len(self.package_ids) >= 2 or self.is_base or change in ('new', 'restore')

    def note_article_review(self, clean):
        """文章（屬於這個情境）審核結果回報：核准且核准者沒改文字＝+1，否則歸零。

        ★ 免審條件是「這個情境的文字連續 N 次核准都沒被改」——計的是文章的審核，
          不是情境記錄本身的審核（兩者很少一起發生，計情境自己等於永遠不會達標）。
        """
        for rec in self:
            rec.sudo().clean_approvals = rec.clean_approvals + 1 if clean else 0

    def action_reject(self, reason=None):
        self.sudo().write({'clean_approvals': 0})
        return super().action_reject(reason=reason)

    @api.constrains('code')
    def _check_code(self):
        for rec in self:
            if not re.match(r'^[a-z0-9_]+$', rec.code or ''):
                raise UserError(_('情境代碼只能用小寫英數與底線（它是 xmlid 命名空間）：%s')
                                % rec.code)

    def _live_seed_json(self):
        """已核准版本的示範資料腳本：上線中的修訂快照；從沒核准過就是 None。"""
        self.ensure_one()
        # ★ 一律取上線修訂的快照，不看目前欄位：已發佈的情境被直接改了 seed_json
        #   （沒送審）時，欄位已經不是核准過的內容。
        snap = self._last_published_snapshot()
        return (snap.get('seed_json') or '[]') if snap else None

    def _seed_sources(self, draft=False):
        """重播順序：資料包（依賴在前）→ 祖先情境 → 自己。

        ★ 上線版用各情境「上線快照」裡的資料包清單：情境改選資料包、還沒核准前，
          說明庫不能先用新的組合。"""
        self.ensure_one()
        chain = self.lineage()
        Pack = self.env['corpaas.knowledge.seed_pack'].sudo()
        packs = Pack
        for sc in chain:
            if draft:
                packs |= sc.pack_ids
            else:
                packs |= Pack.browse((sc._last_published_snapshot() or {}).get('pack_ids')
                                     or []).exists()
        return packs._closure_ordered(draft) + chain

    def live_seed(self, draft=False):
        """含資料包與祖先、只用核准版本的示範資料（說明庫重建只用這個）。

        draft=True：用目前欄位（還沒核准的版本），只給送審前的重播檢查用。
        ★ 參照一律展開成完整 xmlid：資料包與祖先情境的短名參照屬於它自己的命名空間，
          交給 seed_script 補前綴會補成重播當下那個情境的（指到不存在的記錄）。
          角色帳號 user_<code> 例外：帳號建在最末端情境的命名空間。
        """
        self.ensure_one()
        roles = {'user_%s' % r.code for r in self.all_roles()}
        merged, order = {}, []
        for src in self._seed_sources(draft):
            raw = (src.seed_json or '[]') if draft else src._live_seed_json()
            if raw is None:
                raise UserError(_('「%s」的示範資料還沒有核准過的版本，不能拿來拍對外的圖。')
                                % src.display_name)
            for rec in json.loads(raw or '[]'):
                rec = qualify_seed_record(rec, src.xml_module, self.xml_module, roles)
                key = rec['xmlid']
                if key not in merged:
                    order.append(key)
                merged[key] = rec
        return [merged[k] for k in order]

    def seed_revisions(self):
        """說明庫輸入簽章用：每個示範資料來源的上線修訂。"""
        self.ensure_one()
        return [[src._name, src.id, src.published_rev_no] for src in self._seed_sources()]

    # ------------------------------------------------------------------
    # 送審前自動重播檢查（A3）
    # ------------------------------------------------------------------
    def knowledge_propose(self, change, note=None):
        # ★ 先判斷再送審：單一方案引用的情境改文字會直接上線，上線後快照就是新版，
        #   事後已比不出差異——而沒人審的那種更需要自動檢查。
        changed = self.filtered(lambda r: r._seed_changed())
        res = super().knowledge_propose(change, note=note)
        for rec in changed:
            rec._enqueue_seed_check()
        return res

    def _seed_changed(self):
        self.ensure_one()
        live = self._last_published_snapshot()
        if not live:
            return True
        return (live.get('seed_json') or '[]') != (self.seed_json or '[]') \
            or sorted(live.get('pack_ids') or []) != sorted(self.pack_ids.ids)

    def _knowledge_auto_draft_seed(self):
        """核准圈選提案後自動接續：沒有示範資料的情境排 AI 起草；排不了只記一筆，不擋核准。"""
        for sc in self.filtered(lambda r: not r.seed_json and r.package_ids):
            try:
                with self.env.cr.savepoint():
                    sc.sudo().action_ai_draft_seed()
            except Exception as e:  # noqa: BLE001 — 母體沒準備好之類：人可以之後再按
                _logger.warning('[knowledge] 情境 %s 自動起草示範資料略過：%s', sc.code, e)
        return True

    def action_approve(self):
        """核准示範資料後自動接續：排一次全量更新（建說明庫、拍照、起草說明）。

        ★ 只在人工核准時接續：AI 修補示範資料在更新中途自動上線，再觸發更新會循環。"""
        seeded = self.filtered(lambda r: r._seed_changed())
        res = super().action_approve()
        seeded._knowledge_refresh_packages()
        return res

    def _knowledge_refresh_packages(self, reason='seed_approved'):
        packages = self.mapped('package_ids').filtered('knowledge_enabled')
        if not packages:
            return packages
        try:
            with self.env.cr.savepoint():
                packages.sudo().knowledge_enqueue_refresh(full=True, reason=reason)
        except Exception as e:  # noqa: BLE001 — 排不了只記一筆，核准照樣成立
            _logger.warning('[knowledge] 示範資料核准後排更新失敗：%s', e)
        return packages

    def action_seed_check(self):
        self.ensure_one()
        self._enqueue_seed_check(raise_if_no_package=True)
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'type': 'info', 'title': _('已排入佇列'),
                           'message': _('會在一座臨時說明庫重播示範資料，並檢查各畫面有沒有資料。')}}

    def _enqueue_seed_check(self, raise_if_no_package=False):
        """排一張佇列單：複製黃金庫 → 重播目前（待核）的示範資料 → 數各畫面筆數 → 刪庫。"""
        self.ensure_one()
        package = self.package_ids[:1]
        if not package:
            if raise_if_no_package:
                raise UserError(_('情境「%s」還沒有被任何方案引用，沒有黃金庫可以重播。') % self.name)
            return False
        self.sudo().write({'seed_check_state': 'queued', 'seed_check_report': False})
        # ★ params 帶修訂號：檢查有錯 → AI 修正 → 再送審，是在「同一張還在跑的檢查單」裡排下一張；
        #   params 相同會被佇列去重吃掉（實機：修正後的第二次檢查從沒跑，狀態一直停在排隊中）
        q = self.env['corpaas.queue'].sudo()._enqueue(
            package, 'knowledge_sandbox',
            {'scenario_id': self.id, 'op': 'check', 'rev': self.rev_no})
        q.channel = 'knowledge'
        return q

    def _compute_seed_check_html(self):
        for rec in self:
            rec.seed_check_html = rec._seed_check_render()

    def _seed_check_render(self):
        self.ensure_one()
        if not self.seed_check_state:
            return False
        esc = html_mod.escape
        label = dict(SEED_CHECK_STATES).get(self.seed_check_state)
        try:
            data = json.loads(self.seed_check_report or '{}')
        except ValueError:
            data = {}
        parts = ['<p><b>%s</b>%s</p>' % (esc(label), (' · %s' % esc(
            fields.Datetime.to_string(self.seed_check_at))) if self.seed_check_at else '')]
        if data.get('error'):
            parts.append('<p class="text-danger">%s</p>' % esc(data['error']))
        errors = data.get('errors') or []
        if errors:
            parts.append('<p>%s</p><ul>%s</ul>' % (
                esc(_('重播失敗 %s 筆：') % len(errors)),
                ''.join('<li><code>%s</code>（%s）：%s</li>' % (
                    esc(e.get('xmlid') or ''), esc(e.get('model') or ''),
                    esc(e.get('error') or '')) for e in errors[:50])))
        counts, labels = data.get('counts') or {}, data.get('labels') or {}
        if counts:
            empty = sorted(k for k, v in counts.items() if v == 0)
            parts.append('<p>%s</p>' % esc(_('檢查 %(n)s 個畫面：%(e)s 個沒有資料（%(p)s%%，上限 %(m)s%%）',
                                             n=len(counts), e=len(empty),
                                             p=data.get('empty_pct', '?'),
                                             m=data.get('empty_max_pct', '?'))))
            if empty:
                parts.append('<ul>%s</ul>' % ''.join(
                    '<li>%s</li>' % esc(labels.get(k) or k) for k in empty))
            parts.append('<p class="text-muted small">%s</p>' % esc(_(
                '以管理者身分、套用選單動作本身的篩選條件計數；畫面預設的「我的」篩選'
                '沒有套用，實際截圖仍可能是空的。')))
        return ''.join(parts)

    # ------------------------------------------------------------------
    # AI 起草情境示範資料（AI 應用第 5 項）
    # ------------------------------------------------------------------
    def action_ai_draft_seed(self):
        """依引用方案的功能與能力起草示範資料腳本（排入佇列；結果送審）。"""
        self.ensure_one()
        package = self.package_ids[:1]
        if not package:
            raise UserError(_('情境「%s」還沒有被任何方案引用，無法判斷要準備哪些資料。') % self.name)
        package._knowledge_master()
        return self.env['corpaas.knowledge.ai'].enqueue(
            self, '_ai_draft_seed_run', package, note=_('AI 起草示範資料：%s') % self.name)

    def _ai_draft_seed_run(self):
        """有已核准的資料包 → AI 挑包＋只補缺口；沒有才從零起草（通用化第一階段）。

        ★ 實機：AI 從零起草最好做到 1 錯、89 個畫面 21 個空白；手寫 v10 是 0 錯、9 個空白。
          v10 拆成資料包後，新情境由 AI 挑包、換公司名，只對資料包沒涵蓋的畫面補記錄。"""
        self.ensure_one()
        packs = self.env['corpaas.knowledge.seed_pack'].sudo().search(
            [('published_rev_no', '>', 0)])
        if packs:
            return self._ai_compose_seed_run(packs)
        return self._ai_draft_seed_from_scratch()

    def _ai_compose_seed_run(self, packs):
        """AI 從資料包目錄挑包，回公司／倉庫名稱與補缺口的記錄；結果送審（會自動重播檢查）。"""
        self.ensure_one()
        from collections import Counter
        package = self.package_ids[:1]
        catalog = []
        for pk in packs:
            recs = json.loads(pk._live_seed_json() or '[]')
            names = [str((r.get('values') or {}).get('name')) for r in recs
                     if not r.get('call') and (r.get('values') or {}).get('name')
                     and r.get('model') in ('res.partner', 'product.product')]
            catalog.append({
                'names': names[:30],
                'code': pk.code, 'name': pk.name, 'description': pk.description or '',
                'depends': pk._live_depends().mapped('code'),
                'models': dict(Counter(r.get('model') for r in recs if not r.get('call'))),
                'records': ['%s.%s' % (pk.xml_module, r['xmlid']) for r in recs
                            if not r.get('call')][:80]})
        items, labels = package._knowledge_probe_items()
        Feature = self.env['corpaas.knowledge.feature'].sudo()
        screens = [{'name': labels[k], 'model': f.model} for k, _x in items
                   for f in Feature.search([('feature_key', '=', k)], limit=1)]
        gaps = json.loads(self.shot_gaps or '[]')
        roles = ['user_%s' % r.code for r in self.all_roles()]
        codes = {pk.code for pk in packs}
        prompt = (
            "請為情境「%s」組裝 Odoo 18 示範資料。\n情境敘事：%s\n\n"
            "做法：(1) 從「資料包目錄」挑出這個方案需要的資料包（依賴會自動帶入），資料包內容"
            "不能改；(2) 給這家虛構公司與它的倉庫取名（不得與真實公司或品牌同名）；"
            "(3) 只對資料包沒涵蓋、但「方案畫面」需要的模型補記錄，可用 \"__ref__:<完整 xmlid>\" "
            "參照資料包的記錄。\n%s%s"
            "(4) 依挑中的資料包與公司名重寫情境敘事 narrative（150–300 字）：只能提資料包裡真的有的"
            "客戶、供應商、產品（用它們的名稱），不要編資料裡沒有的人名或產品。\n"
            "格式：{\"packs\":[code],\"company\":\"公司名稱\",\"warehouse\":\"倉庫名稱\","
            "\"narrative\":\"…\",\"seed\":[{\"xmlid\":\"短名\",\"model\":…,\"values\":{…}}]}\n\n"
            "資料包目錄：%s\n\n方案畫面：%s"
        ) % (self.name, self.narrative or '',
             self._seed_rules_text(roles),
             ('上次拍照時沒有資料的畫面（優先補）：%s\n' % '、'.join(gaps)) if gaps else '',
             json.dumps(catalog, ensure_ascii=False)[:60000],
             json.dumps(screens, ensure_ascii=False)[:20000])

        def check(data):
            errs = []
            chosen = (data or {}).get('packs')
            if not isinstance(chosen, list) or not chosen:
                errs.append('packs 至少要挑一個資料包')
            else:
                errs += ['沒有代碼為 %s 的資料包' % c for c in chosen if c not in codes]
            for k in ('company', 'warehouse'):
                if not isinstance((data or {}).get(k), str) or not data[k].strip():
                    errs.append('%s 要給名稱' % k)
            errs += seed_contract_errors((data or {}).get('seed') or [])
            return errs

        data, problems = self.env['corpaas.knowledge.ai'].ask_checked(
            'scenario_seed', prompt, check, package=package, record=self)
        chosen = packs.filtered(lambda p: p.code in set((data or {}).get('packs') or []))
        if not chosen:
            raise UserError(_('AI 沒有挑出可用的資料包：%s') % '；'.join(problems[:3]))
        identity = [
            {'xmlid': 'base.main_company', 'model': 'res.company',
             'values': {'name': (data.get('company') or self.name).strip()}},
            {'xmlid': 'stock.warehouse0', 'model': 'stock.warehouse',
             'values': {'name': (data.get('warehouse') or _('總倉')).strip()}},
        ]
        extra = [r for r in (data.get('seed') or [])
                 if isinstance(r, dict) and r.get('xmlid') and not seed_contract_errors([r])]
        vals = {'pack_ids': [(6, 0, chosen.ids)],
                'seed_json': json.dumps(identity + extra, ensure_ascii=False, indent=1),
                'seed_auto_repairs': 0}
        if isinstance(data.get('narrative'), str) and len(data['narrative'].strip()) >= 30:
            # ★ 敘事跟著實際資料走：圈選時寫的敘事可能提到資料裡沒有的產品與人名，
            #   文章的情境說明照敘事寫，就會出現截圖裡看不到的東西
            vals['narrative'] = data['narrative'].strip()
        self.write(vals)
        self.knowledge_propose('new' if not self.published_rev_no else 'text',
                               note=_('AI 組裝示範資料（資料包 %s 個＋補 %s 筆）')
                               % (len(chosen), len(extra)))
        return True

    def _ai_draft_seed_from_scratch(self):
        """黃金庫唯讀取欄位定義 → AI 產生 seed JSON → 寫入並送審（人核准前說明庫不會用）。"""
        self.ensure_one()
        from ..services import remote, scripts
        package = self.package_ids[:1]
        master = package._knowledge_master()
        golden = master._corpaas_golden_db()
        features = self.env['corpaas.knowledge.feature'].search(
            [('package_ids', 'in', package.id), ('model', '!=', False)]).sorted(
            lambda f: -(f.attr_for(package, 'usage_score') or 0))[:60]
        models = set(features.mapped('model')) | {'res.partner'}
        for cap in package.knowledge_capability_ids:
            models |= {m.strip() for m in (cap.master_data_models or '').splitlines() if m.strip()}
        models -= {'res.config.settings'}
        fields_info = remote.shell_json(self.env, golden.instance_id, golden.name,
                                        scripts.fields_script(sorted(models)))
        parent_seed = self.parent_id.live_seed() if self.parent_id else []
        roles = ['user_%s' % r.code for r in self.all_roles()]
        prompt = (
            "請為情境「%s」起草 Odoo 18 示範資料腳本。\n情境敘事：%s\n用語對照：%s\n"
            "規則：只用下方列出的模型與欄位；必填欄位一定要給值；關聯欄位用 "
            "\"__ref__:<xmlid>\" 參照腳本內或繼承情境的記錄（清單用字串陣列）；"
            "資料要像真實但完全虛構（不得用真實公司或個人姓名、電話、統編）；"
            "每個主要模型 3–8 筆，足以讓清單與表單畫面有內容。\n"
            "不要重複繼承情境已有的記錄（可參照它們）。\n%s"
            "格式：{\"seed\":[{\"xmlid\":\"短名\",\"model\":…,\"values\":{…}}]}\n\n"
            "繼承情境已有記錄（xmlid）：%s\n\n欄位定義：%s"
        ) % (self.name, self.narrative or '', json.dumps(self.glossary_map(), ensure_ascii=False),
             self._seed_rules_text(roles),
             json.dumps([r['xmlid'] for r in parent_seed], ensure_ascii=False),
             json.dumps(fields_info, ensure_ascii=False)[:150000])
        data = self.env['corpaas.knowledge.ai'].ask('scenario_seed', prompt, package=package,
                                                    record=self)
        seed = (data or {}).get('seed')
        if not isinstance(seed, list) or not seed:
            raise UserError(_('AI 沒有回傳可用的示範資料腳本。'))
        self.write({'seed_json': json.dumps(seed, ensure_ascii=False, indent=1),
                    'seed_auto_repairs': 0})
        self.knowledge_propose('new' if not self.published_rev_no else 'text',
                               note=_('AI 起草示範資料'))
        return True

    def _ai_fill_gaps(self, package, features, token=None, notes=None):
        """示範資料缺口修補器：只針對拍出來空白的畫面補記錄（只新增，說明庫疊加即可）。

        回傳新增筆數。新增的記錄 xmlid 不可與既有重複（重複的丟掉）——改既有記錄就得重建說明庫。"""
        self.ensure_one()
        live = self.live_seed(draft=True)
        existing = {r['xmlid'] for r in live}
        by_model = {}
        for r in live:
            if not r.get('call'):
                by_model.setdefault(r.get('model'), []).append(r['xmlid'])
        conditions = self._screen_conditions(package, features)
        screens = [{'name': f.name, 'model': f.model, 'action': f.action_xmlid,
                    'existing': by_model.get(f.model, [])[:8],
                    'conditions': conditions.get(f.action_xmlid) or {}} for f in features]
        roles = ['user_%s' % r.code for r in self.all_roles()]
        prompt = (
            "情境「%s」的 Odoo 18 說明庫裡，下列畫面拍出來是空白的（沒有資料，或預設篩選濾掉了）。"
            "請只「新增」記錄讓這些畫面在預設篩選下有內容；可用 \"__ref__:<完整 xmlid>\" 參照"
            "既有記錄，不要改既有記錄。需要的話加動作步驟把單據推到對的狀態（例如追加銷售訂單要"
            "已確認、且交貨數量大於訂購數量的訂單）。做不到的畫面（例如要上傳檔案）就略過，"
            "列在 skipped 並說明原因。每個畫面附了 conditions（動作 domain、預設篩選、記錄規則）："
            "新增的記錄一定要符合這些條件，日期篩選要落在今天附近，記錄規則限本人的要用該角色建立。\n%s"
            "格式：{\"seed\":[…],\"skipped\":[{\"screen\":…,\"reason\":…}]}\n\n"
            "空白畫面：%s%s"
        ) % (self.name, self._seed_rules_text(roles),
             json.dumps(screens, ensure_ascii=False),
             ('\n\n流程路徑沒有資料（要有單據走到這些狀態）：%s' % '；'.join(notes)) if notes else '')

        def check(data):
            seed = (data or {}).get('seed')
            if not isinstance(seed, list):
                return ['seed 要是清單']
            errs = seed_contract_errors(seed)
            dup = [r.get('xmlid') for r in seed if isinstance(r, dict)
                   and qualify_seed_record(r, self.xml_module, self.xml_module)['xmlid'] in existing]
            if dup:
                errs.append('這些 xmlid 已存在，只能新增不能改：%s' % '、'.join(map(str, dup[:10])))
            return errs

        data, _problems = self.env['corpaas.knowledge.ai'].ask_checked(
            'seed_gap_fill', prompt, check, package=package, record=self, refresh_token=token)
        new = [r for r in (data or {}).get('seed') or []
               if isinstance(r, dict) and not seed_contract_errors([r])
               and qualify_seed_record(r, self.xml_module, self.xml_module)['xmlid'] not in existing]
        if not new:
            return 0
        own = json.loads(self.seed_json or '[]')
        self.write({'seed_json': json.dumps(own + new, ensure_ascii=False, indent=1)})
        self.knowledge_propose('text', note=_('AI 補示範資料缺口 %s 筆') % len(new))
        return len(new)

    def _screen_conditions(self, package, features):
        """空白畫面的顯示條件（在黃金庫讀，唯讀）；讀不到就空的，照舊補資料。"""
        actions = [f.action_xmlid for f in features if f.action_xmlid]
        if not actions or not package:
            return {}
        try:
            from ..services import remote, scripts
            golden = package._knowledge_master()._corpaas_golden_db()
            return remote.shell_json(self.env, golden.instance_id, golden.name,
                                     scripts.screen_filter_script(actions)) or {}
        except Exception as e:  # noqa: BLE001
            _logger.warning('[knowledge] 情境 %s 讀取畫面條件失敗：%s', self.code, e)
            return {}

    def _ai_repair_seed_from_check(self, report):
        """重播檢查有錯：請 AI 依錯誤與空畫面修一次腳本，再送審（會自動再檢查一次）。

        ★ 最多自動修兩次（MAX_SEED_REPAIRS）：修完仍有錯就留給人，避免 AI 來回燒預算。"""
        self.ensure_one()
        package = self.package_ids[:1]
        labels = report.get('labels') or {}
        empty = [labels.get(k, k) for k, v in (report.get('counts') or {}).items() if v == 0]
        records = json.loads(self.seed_json or '[]')
        full = lambda x: x if '.' in x else '%s.%s' % (self.xml_module, x)  # noqa: E731
        own = {full(r['xmlid']) for r in records if isinstance(r, dict) and r.get('xmlid')}
        errors = [e for e in report.get('errors') or [] if e.get('xmlid') in own]
        if not errors and not empty:
            return False   # 錯誤都在資料包裡（資料包要另外修）
        bad = {e['xmlid'] for e in errors}
        broken = [r for r in records if full(r['xmlid']) in bad]
        packs = self.pack_ids.mapped('code')
        # ★ 附上出錯模型的真實欄位：方案自有模型 AI 沒看過，只給錯誤訊息它只能再猜一次
        #   ☠️ 實機：dobtor.referral.visit 修兩次都還在寫不存在的 partner_id
        fields_info = {}
        bad_models = sorted({e.get('model') for e in errors if e.get('model')}
                            - {'res.config.settings'})
        if bad_models:
            try:
                from ..services import remote, scripts
                golden = package._knowledge_master()._corpaas_golden_db()
                fields_info = remote.shell_json(self.env, golden.instance_id, golden.name,
                                                scripts.fields_script(bad_models))
            except Exception as e:  # noqa: BLE001 — 拿不到欄位就照舊只給錯誤訊息
                _logger.warning('[knowledge] 情境 %s 讀取欄位定義失敗：%s', self.code, e)
        # ★ 只送出錯的記錄＋其餘記錄的 xmlid 清單：實機每次送整份腳本，修三次花 1.45 美元
        prompt = (
            "情境「%s」的 Odoo 18 示範資料在測試庫重播時有問題。請修正「出錯的記錄」，並為"
            "「沒有資料的畫面」新增記錄；回傳修正後的出錯記錄（同 xmlid）加上新增的記錄，"
            "其他記錄不用回傳、不要改。欄位只能用「出錯模型的欄位定義」裡有的；"
            "對已經是確認／過帳狀態的記錄不要再呼叫確認或過帳。%s\n%s"
            "格式：{\"seed\":[…]}\n\n重播錯誤：%s\n\n出錯的記錄：%s\n\n"
            "沒有資料的畫面：%s\n\n其餘記錄（只列 xmlid，可參照）：%s\n\n出錯模型的欄位定義：%s"
        ) % (self.name,
             ('資料包（%s）會先重播、內容不能改；可用完整 xmlid 參照它們的記錄。' % '、'.join(packs))
             if packs else '',
             self._seed_rules_text(['user_%s' % r.code for r in self.all_roles()]),
             json.dumps(errors[:60], ensure_ascii=False),
             json.dumps(broken, ensure_ascii=False),
             json.dumps(empty[:80], ensure_ascii=False),
             json.dumps([r['xmlid'] for r in records if full(r['xmlid']) not in bad][:300],
                        ensure_ascii=False),
             json.dumps(fields_info, ensure_ascii=False)[:60000])

        def check(data):
            seed = (data or {}).get('seed')
            if not isinstance(seed, list) or not seed:
                return ['seed 要是非空清單']
            return seed_contract_errors(seed)

        data, _problems = self.env['corpaas.knowledge.ai'].ask_checked(
            'seed_repair', prompt, check, package=package, record=self)
        patch = [r for r in (data or {}).get('seed') or []
                 if isinstance(r, dict) and not seed_contract_errors([r])]
        if not patch:
            return False
        by_key = {full(r['xmlid']): r for r in patch}
        merged = [by_key.pop(full(r['xmlid']), r) for r in records]
        seed = merged + list(by_key.values())
        self.write({'seed_json': json.dumps(seed, ensure_ascii=False, indent=1),
                    'seed_auto_repairs': self.seed_auto_repairs + 1})
        self.knowledge_propose('new' if not self.published_rev_no else 'text',
                               note=_('AI 依重播檢查修正示範資料'))
        return True

    def _prune_failed_seed(self, report):
        """AI 修兩次仍重播失敗：把自己（不含資料包）出錯的記錄連同依賴它們的記錄拿掉，再送審。

        ☠️ 實機：補缺口的 AI 一再加進重播不過的記錄（直運、加購、批次已完成…），自動上線後
          正式說明庫每次重建都失敗，連帶截圖、說明書新頁全部停擺。重播不過的記錄本來就載不進
          說明庫，拿掉不會少任何畫面；缺口照舊留著給人。回傳拿掉幾筆。"""
        self.ensure_one()
        records = json.loads(self.seed_json or '[]')
        full = lambda x: x if '.' in x else '%s.%s' % (self.xml_module, x)  # noqa: E731
        own = {full(r['xmlid']) for r in records if isinstance(r, dict) and r.get('xmlid')}
        doomed = {e['xmlid'] for e in report.get('errors') or [] if e.get('xmlid') in own}
        if not doomed:
            return 0
        while True:
            names = doomed | {x.split('.', 1)[1] for x in doomed if '.' in x}
            more = set()
            for r in records:
                key = full(r['xmlid'])
                if key in doomed:
                    continue
                text = json.dumps(r, ensure_ascii=False)
                if any(('__ref__:%s"' % n) in text or ('"%s"' % n) in text for n in names):
                    more.add(key)
            if not more:
                break
            doomed |= more
        kept = [r for r in records if full(r['xmlid']) not in doomed]
        self.write({'seed_json': json.dumps(kept, ensure_ascii=False, indent=1)})
        self.knowledge_propose('text', note=_('重播仍失敗：移除 %s 筆記錄（%s）') % (
            len(doomed), '、'.join(sorted(x.split('.')[-1] for x in doomed)[:10])))
        return len(doomed)

    def text_review_waived(self):
        """文字改寫是否可免審（使用者定案：連續 N 次核准無修改後）。"""
        self.ensure_one()
        return self.auto_text_after and self.clean_approvals >= self.auto_text_after

    def lineage(self):
        """自己＋所有祖先（祖先在前）。"""
        self.ensure_one()
        chain, cur = [], self
        while cur:
            if cur in chain:
                raise UserError(_('情境繼承出現循環：%s') % cur.name)
            chain.insert(0, cur)
            cur = cur.parent_id
        return chain

    def full_seed(self):
        """含資料包與祖先的示範資料（目前欄位，未核准的也算）：AI 起草與欄位盤點用。"""
        self.ensure_one()
        return self.live_seed(draft=True)

    def all_roles(self):
        self.ensure_one()
        roles = self.env['corpaas.knowledge.role']
        for sc in self.lineage():
            roles |= sc.role_ids
        return roles

    def _seed_rules_text(self, roles):
        """示範資料規則＝內建 SEED_RULES＋環境規則表的「示範資料提示」（提示用，計畫第 24、33 項）。

        ★ 對應的驗證版（例如「不建第二家公司」）在重播時由系統執行，不靠 AI 照做。"""
        text = SEED_RULES % {'roles': '、'.join(roles) or '（無）'}
        package = self.package_ids[:1] if 'package_ids' in self._fields else None
        extra = self.env['corpaas.knowledge.rule'].values('seed_prompt', package or None)
        return text + ''.join('★ %s\n' % t for t in extra)

    def glossary_map(self):
        self.ensure_one()
        out = {}
        for sc in self.lineage():
            for line in (sc.glossary or '').splitlines():
                if '=' in line:
                    a, b = line.split('=', 1)
                    out[a.strip()] = b.strip()
        return out

    def seed_models(self):
        self.ensure_one()
        return sorted({r['model'] for r in self.full_seed()})

    @api.constrains('package_ids', 'required_module_names')
    def _check_modules(self):
        for rec in self:
            need = {m.strip() for m in (rec.required_module_names or '').splitlines()
                    if m.strip()}
            if not need:
                continue
            for pkg in rec.package_ids:
                lacking = need - pkg._knowledge_available_modules()
                if lacking:
                    raise UserError(_('方案「%(p)s」缺少情境「%(s)s」需要的模組：%(m)s',
                                      p=pkg.display_name, s=rec.name,
                                      m=', '.join(sorted(lacking))))


class KnowledgeSeedPack(models.Model):
    """示範資料包（A3）：一組可重複使用的示範資料（聯絡人、產品、銷售流程…）。

    情境挑選資料包再加上自己的用語與敘事；資料包和情境一樣要核准才會被說明庫使用。
    """
    _name = 'corpaas.knowledge.seed_pack'
    _description = '示範資料包'
    _inherit = ['corpaas.knowledge.content.mixin']
    _order = 'sequence, name'

    sequence = fields.Integer(default=10)
    name = fields.Char(required=True, tracking=True)
    code = fields.Char(required=True, help='英數底線；資料包的 xmlid 命名空間 __doc_pack_<code>')
    description = fields.Text(string='說明')
    depend_ids = fields.Many2many(
        'corpaas.knowledge.seed_pack', 'corpaas_knowledge_seed_pack_dep_rel',
        'pack_id', 'depend_id', string='依賴資料包',
        help='重播前先重播這些資料包（例如銷售流程依賴聯絡人與產品）')
    required_module_names = fields.Text(string='必要模組', help='一行一個技術名')
    seed_json = fields.Text(string='示範資料腳本',
                            help='[{"xmlid","model","values"}]；__ref__:<xmlid> 參照；'
                                 '其他資料包的記錄用完整 xmlid（__doc_pack_<code>.<名>）')
    scenario_ids = fields.Many2many(
        'corpaas.knowledge.scenario', 'corpaas_knowledge_scenario_pack_rel',
        'pack_id', 'scenario_id', string='使用的情境', readonly=True)
    record_count = fields.Integer(string='筆數', compute='_compute_record_count')

    _sql_constraints = [('code_unique', 'unique(code)', '資料包代碼重複')]

    @property
    def xml_module(self):
        return '__doc_pack_%s' % self.code

    def _knowledge_revision_fields(self):
        return ['name', 'seed_json', 'depend_ids', 'required_module_names']

    def _knowledge_requires_review(self, change):
        # ★ 資料包自動核准（使用者決定，2026-10-06）：資料包是驗證過的共用庫，只有人會改它
        #   （AI 不改資料包）；品質由「用到它的情境」送審前的重播檢查把關，不靠逐包人工核准。
        return False

    @api.constrains('code')
    def _check_code(self):
        for rec in self:
            if not re.match(r'^[a-z0-9_]+$', rec.code or ''):
                raise UserError(_('資料包代碼只能用小寫英數與底線（它是 xmlid 命名空間）：%s')
                                % rec.code)

    @api.constrains('seed_json')
    def _check_seed_json(self):
        for rec in self.filtered('seed_json'):
            try:
                data = json.loads(rec.seed_json)
            except ValueError as e:
                raise UserError(_('資料包「%(n)s」的腳本不是合法 JSON：%(e)s', n=rec.name, e=e))
            if not isinstance(data, list) or any(
                    not isinstance(r, dict) or not r.get('xmlid') for r in data):
                raise UserError(_('資料包「%s」的腳本必須是 [{"xmlid", "model", ...}] 清單。')
                                % rec.name)

    def _compute_record_count(self):
        for rec in self:
            try:
                rec.record_count = len(json.loads(rec.seed_json or '[]'))
            except ValueError:
                rec.record_count = 0

    def _live_seed_json(self):
        self.ensure_one()
        snap = self._last_published_snapshot()
        return (snap.get('seed_json') or '[]') if snap else None

    def _live_depends(self, draft=False):
        self.ensure_one()
        if draft:
            return self.depend_ids
        ids = (self._last_published_snapshot() or {}).get('depend_ids') or []
        return self.browse(ids).exists()

    def _closure_ordered(self, draft=False):
        """這些資料包加上所有依賴，依賴在前（拓樸排序；同層照 sequence）。"""
        out, seen, stack = [], set(), set()

        def visit(pack):
            if pack.id in seen:
                return
            if pack.id in stack:
                raise UserError(_('資料包依賴出現循環：%s') % pack.name)
            stack.add(pack.id)
            for dep in pack._live_depends(draft).sorted(lambda p: (p.sequence, p.id)):
                visit(dep)
            stack.discard(pack.id)
            seen.add(pack.id)
            out.append(pack)

        for pack in self.sorted(lambda p: (p.sequence, p.id)):
            visit(pack)
        return out

    def action_approve(self):
        res = super().action_approve()
        self.mapped('scenario_ids')._knowledge_refresh_packages(reason='pack_approved')
        return res

    @api.model
    def import_bundle(self, name='native_erp_v10'):
        """載入模組內附的資料包庫（data/seed_packs/<name>.json）；資料包自動核准上線。

        已有同代碼的資料包：內容不同才改寫。
        回傳 {code: '新建'|'更新'|'相同'}。"""
        import os
        if not re.match(r'^[a-z0-9_]+$', name or ''):
            raise UserError(_('資料包庫名稱不合法：%s') % name)
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'seed_packs',
                            '%s.json' % name)
        with open(path, encoding='utf-8') as fh:
            bundle = json.load(fh)
        Pack = self.sudo()
        out, made = {}, {}
        for seq, (code, spec) in enumerate(bundle.items(), start=1):
            seed = json.dumps(spec['seed'], ensure_ascii=False, indent=1)
            pack = Pack.search([('code', '=', code)], limit=1)
            if not pack:
                pack = Pack.create({'code': code, 'name': spec['name'], 'sequence': seq * 10,
                                    'description': spec.get('description'), 'seed_json': seed})
                out[code] = '新建'
            elif pack.seed_json != seed:
                pack.write({'seed_json': seed, 'description': spec.get('description')})
                out[code] = '更新'
            else:
                out[code] = '相同'
            made[code] = pack
        for code, spec in bundle.items():
            deps = [made[d].id for d in spec.get('depends') or [] if d in made]
            if set(made[code].depend_ids.ids) != set(deps):
                made[code].depend_ids = [(6, 0, deps)]
                if out[code] == '相同':
                    out[code] = '更新'
        for code, pack in made.items():
            if out[code] != '相同' and pack.state in ('draft', 'stale', 'published'):
                pack.knowledge_propose('new' if not pack.published_rev_no else 'text',
                                       note=_('載入資料包庫 %s') % name)
        return out

    def knowledge_propose(self, change, note=None):
        """資料包改了（自動上線）：用到它的情境各自重播檢查一次，並排更新重拍（A3）。"""
        res = super().knowledge_propose(change, note=note)
        scenarios = self.mapped('scenario_ids')
        for sc in scenarios:
            sc._enqueue_seed_check()
        scenarios.filtered(lambda s: s.published_rev_no)._knowledge_refresh_packages(
            reason='pack_updated')
        return res


class KnowledgeAsset(models.Model):
    _name = 'corpaas.knowledge.asset'
    _description = '素材（原圖＋元素座標）'
    _order = 'id desc'

    name = fields.Char(required=True)
    shot_name = fields.Char(required=True, index=True)
    feature_id = fields.Many2one('corpaas.knowledge.feature', required=True,
                                 ondelete='cascade', index=True)
    scenario_id = fields.Many2one('corpaas.knowledge.scenario', required=True,
                                  ondelete='cascade', index=True)
    scope_hash = fields.Char(index=True)
    owner_model = fields.Char(index=True, help='產生它的出口記錄（如 shot_binding）')
    owner_id = fields.Integer(index=True)
    attachment_id = fields.Many2one('ir.attachment', ondelete='set null')
    regions_json = fields.Text(help='[{n,x,y,w,h}]，CSS 像素（device_scale_factor 前）')
    phash = fields.Char(index=True)
    width = fields.Integer()
    height = fields.Integer()
    state = fields.Selection([('current', '使用中'), ('superseded', '已被取代')],
                             default='current', index=True)
    superseded_at = fields.Datetime()
    url = fields.Char(compute='_compute_url')

    def _compute_url(self):
        for rec in self:
            rec.url = rec.attachment_id and '/web/content/%s' % rec.attachment_id.id or False

    def regions(self):
        self.ensure_one()
        return json.loads(self.regions_json or '[]')

    @api.model
    def _gc_superseded(self, days=30):
        limit = fields.Datetime.subtract(fields.Datetime.now(), days=days)
        old = self.search([('state', '=', 'superseded'), ('superseded_at', '<', limit)])
        old.mapped('attachment_id').unlink()
        old.unlink()
        return len(old)


class KnowledgeSelection(models.Model):
    """AI 圈選提案：方案要說明哪些情境、哪些功能。"""
    _name = 'corpaas.knowledge.selection'
    _description = 'AI 圈選提案'
    _order = 'package_id, score desc'

    package_id = fields.Many2one('infrastructure.solution.package', required=True,
                                 ondelete='cascade', index=True)
    kind = fields.Selection([('scenario', '情境'), ('feature', '功能'),
                             ('capability', '能力'), ('flow', '流程')], required=True)
    flow_id = fields.Many2one('corpaas.knowledge.flow', ondelete='cascade')
    scenario_id = fields.Many2one('corpaas.knowledge.scenario', ondelete='cascade')
    feature_id = fields.Many2one('corpaas.knowledge.feature', ondelete='cascade')
    capability_id = fields.Many2one('corpaas.knowledge.capability', ondelete='cascade')
    proposal_json = fields.Text(help='新情境／新能力的提議內容（尚未建立時）')
    score = fields.Float()
    reason = fields.Text()
    state = fields.Selection([('proposed', '提議'), ('approved', '核准'),
                              ('excluded', '排除')], default='proposed', index=True)
    source = fields.Selection([('ai', 'AI 提議'), ('reuse', '沿用其他方案'),
                               ('manual', '人工')], default='ai', required=True)
    auto_approved = fields.Boolean(readonly=True, help='依核准分級自動核准（不經人工）')
    approved_date = fields.Datetime(readonly=True)
    proposal_name = fields.Char(compute='_compute_proposal_name', string='新項目名稱')
    similar_capability_ids = fields.Many2many(
        'corpaas.knowledge.capability', compute='_compute_similar_capabilities',
        string='相近的既有能力', help='新能力提案：名稱相近的既有能力，核准前先確認是否重複')

    proposal_feature_ids = fields.Many2many(
        'corpaas.knowledge.feature', string='包含的功能點', compute='_compute_proposal_features',
        help='新能力提案：AI 歸進這個能力的功能點；流程提案：流程上的功能點')
    proposal_feature_count = fields.Integer(string='功能點數', compute='_compute_proposal_features')
    proposal_outcome = fields.Text(string='帶來的成果', compute='_compute_proposal_features')

    @api.depends('proposal_json', 'kind', 'flow_id', 'feature_id')
    def _compute_proposal_features(self):
        Feature = self.env['corpaas.knowledge.feature']
        for rec in self:
            try:
                data = json.loads(rec.proposal_json or '{}')
            except ValueError:
                data = {}
            data = data if isinstance(data, dict) else {}
            feats = Feature
            if rec.kind == 'flow':
                feats = rec.flow_id.feature_ids
            elif rec.kind == 'capability':
                keys = [k for k in data.get('features') or [] if isinstance(k, str)]
                feats = Feature.search([('feature_key', 'in', keys)]) if keys else Feature
            elif rec.feature_id:
                feats = rec.feature_id
            rec.proposal_feature_ids = feats
            rec.proposal_feature_count = len(feats)
            outcome = data.get('outcome') or data.get('summary') or data.get('narrative') or ''
            roles = [r for r in data.get('roles') or [] if isinstance(r, dict)]
            if roles:
                outcome += '\n\n' + _('角色：') + '、'.join(
                    '%s（%s）' % (r.get('name') or r.get('code'), r.get('code')) for r in roles)
            rec.proposal_outcome = outcome.strip() or False

    @api.depends('proposal_json', 'kind')
    def _compute_proposal_name(self):
        for rec in self:
            try:
                data = json.loads(rec.proposal_json or '{}')
            except ValueError:
                data = {}
            if not isinstance(data, dict):
                rec.proposal_name = False
            elif rec.kind == 'flow':
                rec.proposal_name = data.get('new_capability') or False
            else:
                rec.proposal_name = data.get('new_capability') or data.get('name')

    @api.depends('proposal_name', 'capability_id')
    def _compute_similar_capabilities(self):
        Cap = self.env['corpaas.knowledge.capability']
        for rec in self:
            rec.similar_capability_ids = Cap._knowledge_similar(rec.proposal_name) \
                if rec.proposal_name and not rec.capability_id and rec.state == 'proposed' \
                else Cap

    # ------------------------------------------------------------------
    @api.model
    def _knowledge_key(self, vals):
        name = ''
        if vals.get('proposal_json') and not vals.get('capability_id'):
            try:
                data = json.loads(vals['proposal_json'])
                if isinstance(data, dict):
                    name = data.get('new_capability') or data.get('name') or ''
            except ValueError:
                pass
        return (vals.get('package_id'), vals.get('kind'), vals.get('feature_id') or False,
                vals.get('scenario_id') or False, vals.get('capability_id') or False,
                search_lib.normalize_name(name), vals.get('flow_id') or False)

    @api.model
    def _knowledge_upsert(self, vals):
        """建立提案，但同方案同對象已有提案就不重複：

        · 已有「提議」→ 更新理由與分數（新能力提案再合併功能點清單）；
        · 已「核准」或「排除」→ 不再提（被排除的不能每次更新又冒出來）。
        """
        key = self._knowledge_key(vals)
        candidates = self.search([('package_id', '=', key[0]), ('kind', '=', key[1]),
                                  ('feature_id', '=', key[2]), ('scenario_id', '=', key[3]),
                                  ('flow_id', '=', key[6])])
        if key[1] == 'flow':
            # 流程提案以流程為單位：同一個流程只留一筆待審（內容以最新一次為準）
            same = candidates
        else:
            candidates = candidates.filtered(lambda r: r.capability_id.id == (key[4] or False))
            same = candidates.filtered(lambda r: self._knowledge_key({
                'package_id': r.package_id.id, 'kind': r.kind,
                'feature_id': r.feature_id.id, 'scenario_id': r.scenario_id.id,
                'capability_id': r.capability_id.id, 'proposal_json': r.proposal_json,
                'flow_id': r.flow_id.id}) == key)
        if not same:
            return self.create(vals)
        rec = same.sorted(lambda r: r.state != 'proposed')[:1]
        if rec.state != 'proposed':
            return rec
        upd = {k: vals[k] for k in ('reason', 'score') if vals.get(k) is not None}
        if key[1] == 'flow':
            upd.update({k: vals.get(k) or False for k in ('proposal_json', 'capability_id')})
            rec.write(upd)
            return rec
        if vals.get('proposal_json') and rec.proposal_json:
            try:
                old, new = json.loads(rec.proposal_json), json.loads(vals['proposal_json'])
                if isinstance(old, dict) and isinstance(new, dict):
                    feats = list(dict.fromkeys((old.get('features') or [])
                                               + (new.get('features') or [])))
                    if feats:
                        old['features'] = feats
                        upd['proposal_json'] = json.dumps(old, ensure_ascii=False)
            except ValueError:
                pass
        rec.write(upd)
        return rec

    def action_use_similar(self):
        """新能力提案改指最相近的既有能力（仍待核准）：避免核准出重複的能力。"""
        for rec in self.filtered(lambda r: r.state == 'proposed' and r.similar_capability_ids):
            rec.capability_id = rec.similar_capability_ids[:1]
        return True

    def action_approve(self):
        if not self.env.user.has_group('dobtor_corpaas_knowledge.group_knowledge_approver'):
            raise AccessError(_('只有知識核准者可以核准圈選提案。'))
        return self._knowledge_approve()

    def _knowledge_auto_approve(self):
        """核准分級的「自動」層：沿用其他方案已核准的歸類。系統流程呼叫，不檢查群組。"""
        # 只自動核准「能力已在這個方案上」的：能力掛不掛方案（商品頁賣點）是產品負責人的決定，
        # 系統不替他把能力加進方案。
        recs = self.filtered(lambda r: r.state == 'proposed' and r.source == 'reuse'
                             and r.capability_id in r.package_id.knowledge_capability_ids)
        recs._knowledge_approve()
        recs.write({'auto_approved': True})
        return recs

    #: 批次核准的順序：先建能力，流程與功能才掛得上既有能力（否則流程提案各自另建一個）
    _APPROVE_ORDER = {'capability': 0, 'scenario': 1, 'feature': 2, 'flow': 3}

    def _knowledge_approve(self):
        todo = self.filtered(lambda r: r.state == 'proposed').sorted(
            lambda r: (self._APPROVE_ORDER.get(r.kind, 9), r.id))
        for rec in todo:
            if rec.kind == 'scenario':
                sc = rec.scenario_id or rec._create_proposed_scenario()
                if sc:
                    sc.package_ids = [(4, rec.package_id.id)]
                    rec.scenario_id = sc
                    # ★ 自動接續：新情境還沒有示範資料 → 直接排 AI 起草（結果送審）
                    sc._knowledge_auto_draft_seed()
            elif rec.kind == 'capability':
                cap = rec.capability_id or rec._create_proposed_capability()
                if cap:
                    cap.package_ids = [(4, rec.package_id.id)]
                    rec.capability_id = cap
            elif rec.kind == 'flow' and rec.flow_id:
                rec._knowledge_apply_flow()
            elif rec.kind == 'feature' and rec.feature_id:
                cap = rec.capability_id or rec._create_proposed_capability()
                if cap:
                    cap.feature_ids = [(4, rec.feature_id.id)]
                    cap.package_ids = [(4, rec.package_id.id)]
                    rec.capability_id = cap
            rec.write({'state': 'approved', 'approved_date': fields.Datetime.now()})
        return True

    def _knowledge_apply_flow(self):
        """核准流程提案：寫入業務名稱與摘要；有能力就把流程上的功能點一次掛進去。"""
        self.ensure_one()
        try:
            data = json.loads(self.proposal_json or '{}')
        except ValueError:
            data = {}
        data = data if isinstance(data, dict) else {}
        flow = self.flow_id.sudo()
        vals = {'named_hash': flow.structure_hash}
        if data.get('name'):
            vals['ai_name'] = data['name']
        if data.get('summary'):
            vals['summary'] = data['summary']
        # ★ 流程提案的 name 是流程名稱，不是能力名稱：只有明確提了 new_capability 才建能力。
        # ★ 流程上的功能點過半已屬於本方案某個能力 → 掛那個能力，不另建：實機 11 個流程提案
        #   核准後多出「銷售管理」「採購管理」「財務會計」等 6 個與既有能力重複的能力。
        cap = self.capability_id or self._knowledge_flow_owner(flow) or (
            self._create_proposed_capability() if data.get('new_capability') else self.capability_id)
        if cap:
            vals['capability_id'] = cap.id
            mine = flow.feature_ids.filtered(lambda f: self.package_id in f.package_ids)
            cap.feature_ids = [(4, f.id) for f in mine]
            cap.package_ids = [(4, self.package_id.id)]
            self.capability_id = cap
        flow.write(vals)

    def _knowledge_flow_owner(self, flow):
        """流程的功能點有過半屬於本方案的同一個能力 → 回傳那個能力。"""
        self.ensure_one()
        feats = flow.feature_ids.filtered(lambda f: self.package_id in f.package_ids)
        caps = self.package_id.knowledge_capability_ids
        if not feats or not caps:
            return self.env['corpaas.knowledge.capability']
        votes = {}
        for f in feats:
            for c in f.capability_ids & caps:
                votes[c] = votes.get(c, 0) + 1
        if not votes:
            return self.env['corpaas.knowledge.capability']
        best = max(votes, key=lambda c: (votes[c], -c.id))
        return best if votes[best] * 2 >= len(feats) else self.env['corpaas.knowledge.capability']

    def _create_proposed_scenario(self):
        """AI 提議的新情境：建立草稿（示範資料另外起草、走情境自己的核准）。"""
        self.ensure_one()
        data = json.loads(self.proposal_json or '{}')
        if not isinstance(data, dict) or not data.get('name'):
            return self.env['corpaas.knowledge.scenario']
        Sc = self.env['corpaas.knowledge.scenario'].sudo()
        code = re.sub(r'[^a-z0-9_]+', '_', (data.get('code') or '').lower()).strip('_') \
            or 'sc_%s_%s' % (self.package_id.id, self.id)
        parent = Sc.search([('code', '=', data.get('extends') or data.get('parent'))], limit=1)
        existing = Sc.search([('code', '=', code)], limit=1)
        if existing:
            return existing
        sc = Sc.create({
            'name': data['name'], 'code': code, 'parent_id': parent.id or False,
            'narrative': data.get('narrative') or data.get('reason'),
            'glossary': glossary_text(data.get('glossary'))})
        sc.role_ids = [(6, 0, self._knowledge_proposed_roles(data).ids)]
        return sc

    def _knowledge_proposed_roles(self, data):
        """提案裡的角色 → 角色記錄（同代碼沿用既有的，不改它的群組）；一定補上 admin。"""
        Role = self.env['corpaas.knowledge.role'].sudo()
        roles = Role
        items = [r for r in data.get('roles') or [] if isinstance(r, dict)]
        if not any(r.get('code') == 'admin' for r in items):
            items.append({'code': 'admin', 'name': '系統管理員', 'groups': ['base.group_system']})
        # ★ 方案有網站前台頁：依要寫的使用者類型補角色——會員（網站入口）拍「我的帳戶／訂單」，
        #   網站管理（內部使用者）拍前台的「編輯此內容」與網站編輯器
        from .feature import ROUTE_ROLE_DEFS, route_audience
        fronts = self.env['corpaas.knowledge.feature'].sudo().search([
            ('package_ids', 'in', self.package_id.id), ('kind', '=', 'route')])
        needed = {route_audience(f.anchor) for f in fronts}
        for code, (name, groups) in ROUTE_ROLE_DEFS.items():
            if code in needed and not any(r.get('code') == code for r in items):
                items.append({'code': code, 'name': name, 'groups': groups})
        for r in items:
            code = re.sub(r'[^a-z0-9_]+', '_', str(r.get('code') or '').lower()).strip('_')
            groups = [g for g in r.get('groups') or []
                      if isinstance(g, str) and re.fullmatch(r'[a-z0-9_]+\.[a-z0-9_]+', g)
                      and g not in SCREEN_CHANGING_GROUPS]
            if not code or not groups:
                continue
            role = Role.search([('code', '=', code)], limit=1) or Role.create({
                'code': code, 'name': r.get('name') or code,
                'group_xmlids': '\n'.join(groups),
                'sequence': len(roles) + 1})
            roles |= role
        return roles

    def _create_proposed_capability(self):
        """AI 提議的新能力：核准時才真的建立（草稿，另外走能力自己的核准）。"""
        self.ensure_one()
        data = json.loads(self.proposal_json or '{}')
        if not isinstance(data, dict):
            return self.env['corpaas.knowledge.capability']
        name = data.get('new_capability') or data.get('name')
        if not name:
            return self.env['corpaas.knowledge.capability']
        Cap = self.env['corpaas.knowledge.capability'].sudo()
        cap = Cap._knowledge_find_by_name(name) or Cap.create({
            'name': name, 'pain': data.get('pain'), 'outcome': data.get('outcome'),
            'package_ids': [(4, self.package_id.id)]})
        keys = [k for k in data.get('features') or [] if isinstance(k, str)]
        if keys:
            feats = self.env['corpaas.knowledge.feature'].search([('feature_key', 'in', keys)])
            cap.feature_ids = [(4, f.id) for f in feats]
        return cap

    def action_exclude(self):
        self.write({'state': 'excluded'})
        return True


class KnowledgeAiCall(models.Model):
    """每一次 AI 呼叫的帳：成本與預算（營運規格）。"""
    _name = 'corpaas.knowledge.ai.call'
    _description = 'AI 呼叫紀錄'
    _order = 'id desc'

    purpose = fields.Char(required=True, index=True)
    refresh_token = fields.Char(index=True)
    package_id = fields.Many2one('infrastructure.solution.package', ondelete='set null')
    run_id = fields.Integer()
    cost_usd = fields.Float(digits=(10, 4))
    ok = fields.Boolean()
    error = fields.Text()
    res_model = fields.Char()
    res_id = fields.Integer()
    prompt_hash = fields.Char(index=True, help='purpose＋prompt 的雜湊（快取鍵）')
    response_text = fields.Text(help='可快取用途的原始回應')
    cached = fields.Boolean(help='命中快取，沒有實際呼叫 AI')
    hub_cost_known = fields.Boolean(help='這次呼叫 AI Hub 有回報今日剩餘額度')
    hub_cost_left = fields.Float(string='Hub 今日剩餘（USD）', digits=(10, 4),
                                 help='成本規劃器（D3）以今天最後一筆為準')

    @api.model
    def _gc_cache(self):
        """過了快取期限的原始回應清掉（帳務欄位保留）；命中快取的零成本紀錄留 90 天。"""
        days = int(self.env['ir.config_parameter'].sudo().get_param(
            'corpaas_knowledge.ai_cache_days') or 30)
        old = fields.Datetime.subtract(fields.Datetime.now(), days=max(days, 1))
        stale = self.search([('response_text', '!=', False), ('create_date', '<', old)])
        stale.write({'response_text': False})
        hits = self.search([('cached', '=', True), ('create_date', '<', fields.Datetime.subtract(
            fields.Datetime.now(), days=90))])
        n = len(hits)
        hits.unlink()
        return len(stale) + n
