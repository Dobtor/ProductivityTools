# -*- coding: utf-8 -*-
"""功能點（自動盤點）、畫面指紋、失效事件、改名候選。"""
import json

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

FEATURE_KINDS = [
    # ★ 'menu' 只留給舊資料：自 18.0.1.1.0 起選單是畫面（action）的入口，不再是功能點。
    ('menu', '選單（舊）'),
    ('action', '畫面'),
    ('client', '非視窗頁面'),
    ('button', '按鈕'),
    ('wizard', '精靈'),
    ('setting', '設定'),
    ('report', '報表'),
    ('route', '前台路由'),
]


class KnowledgeFeature(models.Model):
    _name = 'corpaas.knowledge.feature'
    _description = '功能點'
    _order = 'module, kind, name'

    feature_key = fields.Char(required=True, index=True, readonly=True,
                              help='D3：<模組>.<種類>:<錨點>，建立後不變')
    module = fields.Char(required=True, index=True, readonly=True)
    # ★ 方案自有模組 vs Odoo 官方模組（相依帶進來的 sale、account…）。官方功能點只盤
    #   選單與選單動作；AI 歸類排在自有之後；說明書不自動為它寫文章。盤點時寫入。
    module_origin = fields.Selection(
        [('custom', '專用'), ('odoo', '標準')], string='模組來源',
        default='custom', required=True, index=True, readonly=True)
    kind = fields.Selection(FEATURE_KINDS, required=True, readonly=True)
    anchor = fields.Char(required=True, readonly=True)
    name = fields.Char(required=True)
    model = fields.Char(readonly=True)
    view_mode = fields.Char(readonly=True)
    view_xmlid = fields.Char(readonly=True)
    action_xmlid = fields.Char(readonly=True)
    button_name = fields.Char(readonly=True)
    menu_path = fields.Char()
    group_xmlids = fields.Char(readonly=True, help='逗號分隔')
    entry_ids = fields.One2many('corpaas.knowledge.feature.entry', 'feature_id',
                                string='入口', readonly=True)
    entry_count = fields.Integer(compute='_compute_entry_count', string='入口數')
    # 指紋增量重算（K3）
    view_modules = fields.Char(readonly=True,
                               help='畫面（含繼承）涉及的模組，逗號分隔；變動模組有交集才重算指紋')
    # 官方畫面被我們改過嗎（K19）：自有模組在它的繼承鏈上加了欄位或按鈕
    customized = fields.Boolean(
        string='專用模組改過', readonly=True, index=True,
        help='官方畫面：有自有模組的繼承視圖加了欄位或按鈕。沒改過的官方畫面不寫文章、'
             '說明連到 Odoo 官方文件；改過的只寫差異。')
    custom_modules = fields.Char(string='改動的自有模組', readonly=True)
    custom_elements = fields.Text(string='自有模組加的元素', readonly=True,
                                  help='JSON：["field:x_foo", "button:action_bar", …]')
    fp_dirty = fields.Boolean(readonly=True,
                              help='盤點時入口路徑或視圖設定變了：下次指紋一定重算')
    intents = fields.Text(string='問法與同義詞', help='一行一個；AI 產生，help_search 使用')
    prerequisite_ids = fields.Many2many(
        'corpaas.knowledge.feature', 'corpaas_knowledge_feature_prereq_rel',
        'feature_id', 'prereq_id', string='前置功能')
    capability_ids = fields.Many2many(
        'corpaas.knowledge.capability', 'corpaas_knowledge_capability_feature_rel',
        'feature_id', 'capability_id', string='能力')
    # ★ 存在與否是「每個方案」各自的事：同一個模組在 A 方案的分支還有、在 B 方案的
    #   分支已經拿掉，是正常的。只有一個全域旗標時，兩個方案輪流更新會讓它來回翻，
    #   每次都重發「消失」事件、把別的方案的說明一起下架。
    package_ids = fields.Many2many(
        'infrastructure.solution.package', 'corpaas_knowledge_feature_package_rel',
        'feature_id', 'package_id', string='存在於方案', readonly=True)
    missing_package_ids = fields.Many2many(
        'infrastructure.solution.package', 'corpaas_knowledge_feature_missing_rel',
        'feature_id', 'package_id', string='已從這些方案消失', readonly=True)
    missing = fields.Boolean(string='所有方案都已消失', compute='_compute_missing',
                             store=True, index=True)
    first_seen = fields.Datetime(readonly=True, default=fields.Datetime.now)
    last_seen = fields.Datetime(readonly=True)
    fingerprint_ids = fields.One2many('corpaas.knowledge.fingerprint', 'feature_id')
    classify_pending = fields.Boolean(string='待 AI 歸類', readonly=True, index=True,
                                      help='新增到某方案後還沒歸入能力；下一次更新接續')
    ai_classified = fields.Boolean(
        string='AI 已歸類過', readonly=True,
        help='任一方案已請 AI 歸類過（同義詞是全域的）：加入別的方案時沿用，不再請 AI')
    usage_score = fields.Float(string='租戶使用量', readonly=True,
                               help='依 dobtor_database_activity_stats；決定 AI 優先順序')
    usage_source = fields.Selection(
        [('model', '模型層級'), ('measured', '實測'), ('estimated', '推估')],
        string='使用量來源', readonly=True,
        help='實測：租戶的畫面開啟／按鈕呼叫次數；推估：由狀態轉換次數分攤；'
             '模型層級：只知道這個模型有多少異動，同模型的功能點分數相同')
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('key_unique', 'unique(feature_key)', '功能點鍵重複'),
    ]

    def _knowledge_add_intents(self, lines):
        """加入問法／同義詞：正規化後去重，保留原有順序。所有寫入點都走這裡。"""
        from ..services import search_lib
        for rec in self:
            merged = search_lib.merge_lines(rec.intents, lines)
            if merged != (rec.intents or ''):
                rec.intents = merged or False

    def _compute_entry_count(self):
        for rec in self:
            rec.entry_count = len(rec.entry_ids)

    def visible_to(self, groups):
        """使用者群組（xmlid 集合）看得到這個功能嗎：畫面本身的群組＋至少一個入口看得到。

        沒有入口的畫面（只從程式或其他畫面打開）只看畫面群組。
        """
        self.ensure_one()
        have = set(groups or ())
        if self.group_xmlids and not have & set(self.group_xmlids.split(',')):
            return False
        if not self.entry_ids:
            return True
        return any(not e.group_xmlids or have & set(e.group_xmlids.split(','))
                   for e in self.entry_ids)

    @api.depends('package_ids', 'missing_package_ids')
    def _compute_missing(self):
        for rec in self:
            rec.missing = bool(rec.missing_package_ids) and not rec.package_ids

    def is_present_in(self, package):
        self.ensure_one()
        return package in self.package_ids

    @api.model
    def make_key(self, module, kind, anchor):
        return '%s.%s:%s' % (module, kind, anchor)

    def _compute_display_name(self):
        for rec in self:
            rec.display_name = '%s（%s）' % (rec.name, rec.feature_key)

    def views_for_fingerprint(self):
        """[[view_xmlid|False, view_type], …]：送進 fingerprint 腳本的 get_views 參數。"""
        self.ensure_one()
        if self.kind in ('menu', 'action'):
            modes = [m for m in (self.view_mode or 'list,form').split(',')
                     if m in ('list', 'form', 'kanban')]
            views = [[False, m] for m in modes] or [[False, 'form']]
            if self.view_xmlid and views:
                views[0][0] = self.view_xmlid
            return views
        if self.kind == 'button':
            vt = self.view_mode if self.view_mode in ('form', 'list', 'kanban') else 'form'
            return [[self.view_xmlid or False, vt]]
        if self.kind in ('wizard', 'setting'):
            return [[False, 'form']]
        return []

    def help_fingerprint(self, package):
        """給租戶端（D5）重算並比對的參數。

        ★ 傳「所有角色」的 scope_hash：主控台依角色各算一份，租戶使用者的群組不一定
          剛好等於某個情境角色。只要租戶算出來的雜湊落在其中之一就不算分歧，
          只挑一個角色會讓群組較多的使用者一律被誤報。
        """
        self.ensure_one()
        fps = self.fingerprint_ids.filtered(
            lambda f: f.package_id == package and f.current and f.scope_hash)
        if not fps:
            return {}
        first = fps[:1]
        return {
            'model': self.model, 'views': self.views_for_fingerprint(),
            'menu_path': self.menu_path or '', 'view_mode': self.view_mode or '',
            'elements': first.elements(), 'lang': first.lang or 'zh_TW',
            'version': first.fp_version,
            'scope_hashes': sorted(set(fps.mapped('scope_hash'))),
            'scope_hash': first.scope_hash,
        }

    def action_mark_used_in(self, packages):
        for rec in self:
            rec.package_ids = [(4, p.id) for p in packages]


ENTRY_KINDS = [
    ('menu', '選單'),
    ('button', '按鈕'),
    ('smart_button', '智慧按鈕'),
]


class KnowledgeFeatureEntry(models.Model):
    """走進一個畫面的入口：選單、按鈕（type=action）、智慧按鈕。盤點時同步。"""
    _name = 'corpaas.knowledge.feature.entry'
    _description = '功能點入口'
    _order = 'feature_id, kind, path'

    feature_id = fields.Many2one('corpaas.knowledge.feature', required=True,
                                 ondelete='cascade', index=True)
    kind = fields.Selection(ENTRY_KINDS, required=True)
    anchor = fields.Char(required=True, help='選單 xmlid，或 <視圖xmlid>/button[名稱]')
    module = fields.Char(required=True, index=True)
    name = fields.Char()
    path = fields.Char(help='選單完整路徑，或按鈕所在的視圖')
    group_xmlids = fields.Char(help='逗號分隔')
    last_seen = fields.Datetime()

    _sql_constraints = [
        ('entry_unique', 'unique(feature_id, kind, anchor)', '入口重複'),
    ]


class KnowledgeRole(models.Model):
    _name = 'corpaas.knowledge.role'
    _description = '情境角色'
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    code = fields.Char(required=True, help='英數，建帳號用：doc_<code>')
    name = fields.Char(required=True)
    group_xmlids = fields.Text(required=True, help='一行一個群組 xmlid')

    _sql_constraints = [('code_unique', 'unique(code)', '角色代碼重複')]

    def as_payload(self):
        return [{'code': r.code, 'name': r.name,
                 'groups': [g.strip() for g in (r.group_xmlids or '').splitlines()
                            if g.strip()]} for r in self]


class KnowledgeFingerprint(models.Model):
    _name = 'corpaas.knowledge.fingerprint'
    _description = '畫面指紋'
    _order = 'computed_at desc'

    feature_id = fields.Many2one('corpaas.knowledge.feature', required=True,
                                 ondelete='cascade', index=True)
    package_id = fields.Many2one('infrastructure.solution.package', required=True,
                                 ondelete='cascade', index=True)
    role_code = fields.Char(required=True, index=True)
    form_hash = fields.Char(readonly=True)
    scope_hash = fields.Char(readonly=True, index=True)
    elements_json = fields.Text(help='腳本範圍元素（由截圖腳本範本提供）')
    found_json = fields.Text(readonly=True)
    signature_json = fields.Text(readonly=True, help='改名偵測用的元素簽章')
    error = fields.Char(readonly=True)
    code_manifest = fields.Text(readonly=True)
    fp_version = fields.Integer(readonly=True)
    lang = fields.Char(readonly=True, help='計算時用的語言（黃金庫沒有 zh_TW 時退回 en_US）')
    computed_at = fields.Datetime(readonly=True)
    current = fields.Boolean(default=True, index=True)

    def elements(self):
        self.ensure_one()
        return json.loads(self.elements_json or '[]')

    @api.model
    def _gc(self, days=30):
        """舊指紋（非 current）與處理過的事件：每次全量更新都會新增，不清會一直長。"""
        limit = fields.Datetime.subtract(fields.Datetime.now(), days=days)
        old = self.search([('current', '=', False), ('computed_at', '<', limit)])
        old.unlink()
        ev = self.env['corpaas.knowledge.event'].search(
            [('processed', '=', True), ('create_date', '<', fields.Datetime.subtract(
                fields.Datetime.now(), days=days * 3))])
        ev.unlink()
        return len(old) + len(ev)


EVENT_TYPES = [
    ('feature_added', '新增功能點'),
    ('feature_removed', '功能點消失'),
    ('scope_changed', '畫面指紋改變'),
    ('form_changed', '表單變動（僅檢查）'),
    ('scenario_changed', '情境變動'),
    ('rename_candidate', '改名候選'),
    ('divergence', '租戶畫面分歧'),
    ('code_changed', '程式碼改版'),
    ('modules_changed', '盤點模組範圍變動'),
    ('toggle_changed', '設定開關變動'),
    ('class_changed', '功能分類變動'),
]


class KnowledgeEvent(models.Model):
    _name = 'corpaas.knowledge.event'
    _description = '失效事件'
    _order = 'id desc'

    type = fields.Selection(EVENT_TYPES, required=True, index=True)
    package_id = fields.Many2one('infrastructure.solution.package', index=True,
                                 ondelete='cascade')
    feature_id = fields.Many2one('corpaas.knowledge.feature', index=True,
                                 ondelete='cascade')
    scenario_id = fields.Many2one('corpaas.knowledge.scenario', index=True,
                                  ondelete='cascade')
    role_code = fields.Char()
    payload = fields.Text()
    refresh_token = fields.Char(index=True, help='哪一次 refresh 產生的')
    processed = fields.Boolean(index=True)
    note = fields.Char()

    def payload_dict(self):
        self.ensure_one()
        return json.loads(self.payload or '{}')


class KnowledgeRenameCandidate(models.Model):
    _name = 'corpaas.knowledge.rename'
    _description = '功能點改名候選（D3）'
    _order = 'id desc'

    old_feature_id = fields.Many2one('corpaas.knowledge.feature', required=True,
                                     ondelete='cascade')
    new_feature_id = fields.Many2one('corpaas.knowledge.feature', required=True,
                                     ondelete='cascade')
    similarity = fields.Float(digits=(3, 2))
    state = fields.Selection([('proposed', '待確認'), ('accepted', '已確認'),
                              ('rejected', '不是改名')], default='proposed', index=True)

    def _check_approver(self):
        if not self.env.user.has_group('dobtor_corpaas_knowledge.group_knowledge_approver'):
            raise AccessError(_('只有知識核准者可以確認或否決改名候選。'))

    def action_accept(self):
        """把引用舊功能點的一切轉到新功能點。出口以 `_knowledge_rename_feature` 參與。"""
        self._check_approver()
        for rec in self.filtered(lambda r: r.state == 'proposed'):
            old, new = rec.old_feature_id, rec.new_feature_id
            new._knowledge_add_intents(old.intents)
            new.write({'capability_ids': [(4, c.id) for c in old.capability_ids]})
            self.env['corpaas.knowledge.hooks']._knowledge_rename_feature(old, new)
            old.active = False
            rec.state = 'accepted'
        return True

    def action_reject(self):
        self._check_approver()
        self.write({'state': 'rejected'})
        # 不是改名 → 舊功能點照「消失」處理
        for rec in self:
            self.env['corpaas.knowledge.hooks']._knowledge_feature_gone(
                rec.old_feature_id)
        return True


class KnowledgeHooks(models.AbstractModel):
    """出口掛勾的集中點：出口模組 _inherit 這個 AbstractModel 覆寫。

    ★ 用一個 AbstractModel 而不是散在各模型：核心需要「通知所有出口」時只呼叫
      這裡，出口模組各自 super() 串起來，裝了幾個出口就跑幾個。
    """
    _name = 'corpaas.knowledge.hooks'
    _description = '知識出口掛勾'

    @api.model
    def _knowledge_rename_feature(self, old, new):
        return True

    @api.model
    def _knowledge_feature_gone(self, feature):
        return True

    @api.model
    def _knowledge_dispatch_events(self, package, events, ctx):
        """refresh 最後一步：把事件交給各出口。ctx 帶 sandbox 取得器、預算等。"""
        return True

    @api.model
    def _knowledge_elements_for(self, feature, package):
        """指紋要看哪些元素：由截圖腳本範本提供（manual 模組覆寫）。"""
        return []

    @api.model
    def _knowledge_help_links(self, package, matches, query, ctx):
        """help API：把命中的功能點轉成連結。回傳 list of dict。

        核心提供：沒被改過的官方畫面 → 已核准的 Odoo 官方文件（K21）。出口模組 super()
        後接著加自己的連結。
        """
        out = []
        if not matches:
            return out
        docs = self.env['corpaas.knowledge.official_doc'].sudo().search([
            ('feature_id', 'in', [f.id for f, _s in matches]), ('state', '=', 'approved')])
        by_feature = {d.feature_id.id: d for d in docs}
        for feature, _score in matches:
            doc = by_feature.get(feature.id)
            if doc and not feature.attr_for(package, 'customized'):
                out.append({'feature_key': feature.feature_key,
                            'title': doc.title or feature.name, 'url': doc.url,
                            'kind': 'official', 'scenario': '', 'anchor': '',
                            'fingerprint': {}})
        return out

    @api.model
    def _knowledge_scenarios_needing_shots(self, package, events):
        """哪些情境要重建說明庫並拍攝（manual 模組覆寫）。"""
        return self.env['corpaas.knowledge.scenario']

    @api.model
    def _knowledge_shoot(self, package, sandbox, events, ctx):
        """在說明庫拍攝（manual 模組覆寫）。"""
        return True

    @api.model
    def _knowledge_fix_gaps_before_sandbox(self, package, ctx):
        """迭代：說明庫準備前要先做的修補（例如補示範資料）。出口覆寫。"""
        return True

    @api.model
    def _knowledge_check_screens(self, package, sandbox, items):
        """送審前重播檢查：各畫面有沒有資料。回傳 {功能鍵: 筆數}（0＝空白、-1＝打不開）。

        核心用唯讀腳本數「動作條件下的筆數」（管理者身分）；出口可覆寫成跟拍照同一套的
        真實探測（同角色、同預設篩選）——兩者不同時，檢查過了也不保證拍得到。"""
        from ..services import scripts
        return sandbox._shell(scripts.data_probe_script(items)) if items else {}

    @api.model
    def _knowledge_fingerprint_rebaselined(self, feature, package, role_code, old, new):
        """腳本範圍元素換了（例如第一次建立截圖範本、AI 修過範本）→ 指紋的「定義」變了，
        畫面沒變。出口把引用 old 的東西改指 new，不分岔、不重拍、不送審。"""
        return True

    @api.model
    def _knowledge_covered_features(self, package, features):
        """覆蓋率報表：這些功能點裡，哪些在這個方案有上線中的說明（出口覆寫）。回傳 id 集合。"""
        return set()

    @api.model
    def _knowledge_check_feature_ref(self, feature):
        """feature 還被出口引用嗎（決定消失時要不要下架）。"""
        return False
