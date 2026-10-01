# -*- coding: utf-8 -*-
"""能力、情境、素材、圈選提案。"""
import json
import re

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

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
    code = fields.Char(help='穩定代碼，章節對應與商品頁錨點用')
    feature_ids = fields.Many2many(
        'corpaas.knowledge.feature', 'corpaas_knowledge_capability_feature_rel',
        'capability_id', 'feature_id', string='功能點')
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

    def _knowledge_revision_fields(self):
        return ['name', 'pain', 'outcome', 'differentiator', 'color']

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
        have = set(package._provision_module_names())
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
    clean_approvals = fields.Integer(string='連續無修改核准次數', readonly=True)
    auto_text_after = fields.Integer(string='連續幾次後文字改寫免審', default=5)

    _sql_constraints = [('code_unique', 'unique(code)', '情境代碼重複')]

    @property
    def xml_module(self):
        return '__doc_scenario_%s' % self.code

    def _knowledge_revision_fields(self):
        return ['name', 'glossary', 'narrative', 'seed_json', 'required_module_names']

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

    def live_seed(self):
        """含祖先、只用核准版本的示範資料（說明庫重建只用這個）。"""
        self.ensure_one()
        merged, order = {}, []
        for sc in self.lineage():
            raw = sc._live_seed_json()
            if raw is None:
                raise UserError(_('情境「%s」的示範資料還沒有核准過的版本，不能拿來拍對外的圖。')
                                % sc.name)
            for rec in json.loads(raw or '[]'):
                key = rec['xmlid'] if '.' in rec['xmlid'] else '%s.%s' % (
                    sc.xml_module, rec['xmlid'])
                rec = dict(rec, xmlid=key)
                if key not in merged:
                    order.append(key)
                merged[key] = rec
        return [merged[k] for k in order]

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
        """黃金庫唯讀取欄位定義 → AI 產生 seed JSON → 寫入並送審（人核准前說明庫不會用）。"""
        self.ensure_one()
        from ..services import remote, scripts
        package = self.package_ids[:1]
        master = package._knowledge_master()
        golden = master._corpaas_golden_db()
        features = self.env['corpaas.knowledge.feature'].search(
            [('package_ids', 'in', package.id), ('model', '!=', False)],
            order='usage_score desc', limit=60)
        models = set(features.mapped('model')) | {'res.partner'}
        for cap in package.knowledge_capability_ids:
            models |= {m.strip() for m in (cap.master_data_models or '').splitlines() if m.strip()}
        models -= {'res.config.settings'}
        fields_info = remote.shell_json(self.env, golden.instance_id, golden.name,
                                        scripts.fields_script(sorted(models)))
        parent_seed = self.parent_id.live_seed() if self.parent_id else []
        prompt = (
            "請為情境「%s」起草 Odoo 示範資料腳本。\n情境敘事：%s\n用語對照：%s\n"
            "規則：只用下方列出的模型與欄位；必填欄位一定要給值；關聯欄位用 "
            "\"__ref__:<xmlid>\" 參照腳本內或繼承情境的記錄（清單用字串陣列）；"
            "資料要像真實但完全虛構（不得用真實公司或個人姓名、電話、統編）；"
            "每個主要模型 3–8 筆，足以讓清單與表單畫面有內容。\n"
            "不要重複繼承情境已有的記錄（可參照它們）。\n"
            "格式：{\"seed\":[{\"xmlid\":\"短名\",\"model\":…,\"values\":{…}}]}\n\n"
            "繼承情境已有記錄（xmlid）：%s\n\n欄位定義：%s"
        ) % (self.name, self.narrative or '', json.dumps(self.glossary_map(), ensure_ascii=False),
             json.dumps([r['xmlid'] for r in parent_seed], ensure_ascii=False),
             json.dumps(fields_info, ensure_ascii=False)[:150000])
        data = self.env['corpaas.knowledge.ai'].ask('scenario_seed', prompt, package=package,
                                                    record=self)
        seed = (data or {}).get('seed')
        if not isinstance(seed, list) or not seed:
            raise UserError(_('AI 沒有回傳可用的示範資料腳本。'))
        self.seed_json = json.dumps(seed, ensure_ascii=False, indent=1)
        self.knowledge_propose('new' if not self.published_rev_no else 'text',
                               note=_('AI 起草示範資料'))
        return True

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
        """含祖先的示範資料：祖先先建，子情境可覆寫同 xmlid。"""
        self.ensure_one()
        merged, order = {}, []
        for sc in self.lineage():
            for rec in json.loads(sc.seed_json or '[]'):
                key = rec['xmlid'] if '.' in rec['xmlid'] else '%s.%s' % (
                    sc.xml_module, rec['xmlid'])
                rec = dict(rec, xmlid=key)
                if key not in merged:
                    order.append(key)
                merged[key] = rec
        return [merged[k] for k in order]

    def all_roles(self):
        self.ensure_one()
        roles = self.env['corpaas.knowledge.role']
        for sc in self.lineage():
            roles |= sc.role_ids
        return roles

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
            for pkg in rec.package_ids:
                lacking = need - set(pkg._provision_module_names())
                if lacking:
                    raise UserError(_('方案「%(p)s」缺少情境「%(s)s」需要的模組：%(m)s',
                                      p=pkg.display_name, s=rec.name,
                                      m=', '.join(sorted(lacking))))


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
                             ('capability', '能力')], required=True)
    scenario_id = fields.Many2one('corpaas.knowledge.scenario', ondelete='cascade')
    feature_id = fields.Many2one('corpaas.knowledge.feature', ondelete='cascade')
    capability_id = fields.Many2one('corpaas.knowledge.capability', ondelete='cascade')
    proposal_json = fields.Text(help='新情境／新能力的提議內容（尚未建立時）')
    score = fields.Float()
    reason = fields.Text()
    state = fields.Selection([('proposed', '提議'), ('approved', '核准'),
                              ('excluded', '排除')], default='proposed', index=True)

    def action_approve(self):
        if not self.env.user.has_group('dobtor_corpaas_knowledge.group_knowledge_approver'):
            raise AccessError(_('只有知識核准者可以核准圈選提案。'))
        for rec in self.filtered(lambda r: r.state == 'proposed'):
            if rec.kind == 'scenario':
                sc = rec.scenario_id or rec._create_proposed_scenario()
                if sc:
                    sc.package_ids = [(4, rec.package_id.id)]
                    rec.scenario_id = sc
            elif rec.kind == 'capability':
                cap = rec.capability_id or rec._create_proposed_capability()
                if cap:
                    cap.package_ids = [(4, rec.package_id.id)]
                    rec.capability_id = cap
            elif rec.kind == 'feature' and rec.feature_id:
                cap = rec.capability_id or rec._create_proposed_capability()
                if cap:
                    cap.feature_ids = [(4, rec.feature_id.id)]
                    cap.package_ids = [(4, rec.package_id.id)]
                    rec.capability_id = cap
            rec.state = 'approved'
        return True

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
        return Sc.search([('code', '=', code)], limit=1) or Sc.create({
            'name': data['name'], 'code': code, 'parent_id': parent.id or False,
            'narrative': data.get('narrative') or data.get('reason'),
            'glossary': data.get('glossary') if isinstance(data.get('glossary'), str) else False})

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
        cap = Cap.search([('name', '=', name)], limit=1) or Cap.create({
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
