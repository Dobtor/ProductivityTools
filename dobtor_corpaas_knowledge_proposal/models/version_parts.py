# -*- coding: utf-8 -*-
"""版本的各個組成：報價基礎、需求核對、範圍、前提、期程、驗收與付款、條款、效益。

這些是報價規格書（以賽亞 v2.0、預建 v6.0、SKF 7.4 …）每一份都有、而以前的建議書沒有存的東西。
它們是**版本資料**：文件（Word／PDF）只是它們的投影，不是反過來 —— 改內容改這裡，
重新輸出就得到新版文件；送出後一律凍結，要改就複製新版。

★ 全部繼承 `corpaas.knowledge.proposal.child`：送出後寫、建、刪都擋。
"""
import json
import logging
import math
from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from odoo.addons.dobtor_corpaas_knowledge.services import hub_client

from ..services import clauses as clause_lib
from ..services import versioning
from .effort import ACTIVITIES

_logger = logging.getLogger(__name__)

AI_PAIN_PROMPT = """任務：從會議記錄與筆記，萃取客戶提到的營運痛點，作為服務建議書的「痛點」清單。

規則：
1. 只萃取客戶（或客戶端人員）表達的困難、需求、期待；不要把內部報價討論、底價、成本當成痛點。
2. 一個痛點一筆，description 用一兩句話寫成「現況困難或期待」，不要寫解法。
3. evidence 寫出處：來源標題與一句關鍵原話（不超過 60 字）。
4. department 能判斷就填部門（財務、業務、倉管…），不確定填 null。
5. existing_pains 已經有的痛點不要重複；沒有新痛點就回空清單。
6. 不要編造來源沒有的內容。

輸入：
```json
%s
```

輸出格式：
```json
{"pains": [{"department": "財務", "description": "...", "evidence": "..."}]}
```
"""

#: 階段的預設里程碑（取自既有報價規格書的慣用說法）
PHASE_MILESTONES = {
    'requirements': '需求規格雙方簽認',
    'tuning': '設定微調確認',
    'custom': '客製項目驗收',
    'migration': '資料核對表通過',
    'training': '教育訓練完成',
    'golive': '正式上線與驗收簽認',
    'pm': '',
}
PHASE_ORDER = ['requirements', 'tuning', 'custom', 'migration', 'training', 'golive']


class ProposalBasis(models.Model):
    _name = 'corpaas.knowledge.basis'
    _description = '建議書：報價基礎'
    _inherit = ['corpaas.knowledge.proposal.child']
    _order = 'proposal_id, sequence, id'

    proposal_id = fields.Many2one('corpaas.knowledge.proposal', required=True,
                                  ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    kind = fields.Selection([
        ('file', '客戶提供檔案'), ('meeting', '會議'), ('mail', '來信／訊息'),
        ('other', '其他')], string='類型', default='file', required=True)
    date = fields.Date(string='日期')
    title = fields.Char(string='內容', required=True,
                        help='例如「Requirements 匯出檔（45 欄含實際資料）」「四張畫面截圖」。')
    # 軟關聯：會議筆記、附件等；不依賴那些模組，只存模型與編號
    ref_model = fields.Char(string='來源模型')
    ref_id = fields.Integer(string='來源記錄')
    note = fields.Text(string='備註')
    # 會議／筆記來源（商機「會議與筆記」帶入）。note_id 刪筆記時只清掉連結，基礎列留著。
    note_id = fields.Many2one('note.note', string='會議／筆記', ondelete='set null')
    fingerprint = fields.Char(string='內容指紋', readonly=True,
                              help='帶入當下筆記內容的雜湊；之後筆記被改過就會標示。')
    is_new = fields.Boolean(string='本版新增', compute='_compute_source_flags')
    content_changed = fields.Boolean(string='內容已更新', compute='_compute_source_flags')

    @api.depends('note_id', 'note_id.memo', 'fingerprint',
                 'proposal_id.supersedes_id.basis_ids.note_id',
                 'ref_model', 'ref_id')
    def _compute_source_flags(self):
        for rec in self:
            prev = rec.proposal_id.supersedes_id
            known = prev.basis_ids if prev else prev.browse()
            if rec.note_id:
                rec.is_new = bool(prev) and rec.note_id not in known.note_id
                current = self.env['corpaas.knowledge.lead_source']._note_fingerprint(rec.note_id)
                rec.content_changed = bool(rec.fingerprint and current != rec.fingerprint)
            else:
                rec.is_new = bool(prev) and bool(rec.ref_model) and not any(
                    k.ref_model == rec.ref_model and k.ref_id == rec.ref_id for k in known)
                rec.content_changed = False


class ProposalChangeLine(models.Model):
    _name = 'corpaas.knowledge.change_line'
    _description = '建議書：需求核對與本版處理'
    _inherit = ['corpaas.knowledge.proposal.child']
    _order = 'proposal_id, sequence, id'

    proposal_id = fields.Many2one('corpaas.knowledge.proposal', required=True,
                                  ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    ref_no = fields.Char(string='#')
    demand = fields.Text(string='貴公司核對項', required=True)
    handling = fields.Text(string='本版處理')
    chapter_ref = fields.Char(string='對應章節')
    basis_id = fields.Many2one('corpaas.knowledge.basis', string='出處',
                               domain="[('proposal_id', '=', proposal_id)]",
                               ondelete='set null')
    origin = fields.Selection([('manual', '手動'), ('diff', '版本差異')],
                              string='來源', default='manual', required=True)


class ProposalScopeItem(models.Model):
    _name = 'corpaas.knowledge.scope_item'
    _description = '建議書：範圍界線'
    _inherit = ['corpaas.knowledge.proposal.child']
    _order = 'proposal_id, kind, sequence, id'

    proposal_id = fields.Many2one('corpaas.knowledge.proposal', required=True,
                                  ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    kind = fields.Selection([
        ('in', '涵蓋範圍'), ('out', '不涵蓋（另行估列）'),
        ('excluded', '排除（不建議開發）'), ('optional', '選配（另行報價）'),
    ], string='類別', required=True, default='in')
    name = fields.Char(string='項目', required=True)
    detail = fields.Text(string='說明')


class ProposalObligation(models.Model):
    _name = 'corpaas.knowledge.obligation'
    _description = '建議書：前提與客戶配合事項'
    _inherit = ['corpaas.knowledge.proposal.child']
    _order = 'proposal_id, kind, sequence, id'

    proposal_id = fields.Many2one('corpaas.knowledge.proposal', required=True,
                                  ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    kind = fields.Selection([
        ('client', '客戶須提供／配合'), ('assumption', '專案假設'),
        ('precondition', '前提條件'),
    ], string='類別', required=True, default='client')
    text = fields.Text(string='內容', required=True)


class ProposalPhase(models.Model):
    _name = 'corpaas.knowledge.phase'
    _description = '建議書：導入階段'
    _inherit = ['corpaas.knowledge.proposal.child']
    _order = 'proposal_id, sequence, id'

    proposal_id = fields.Many2one('corpaas.knowledge.proposal', required=True,
                                  ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    code = fields.Char(string='代號', help='P1、S2 …；文件裡的階段欄。')
    name = fields.Char(string='階段', required=True)
    content = fields.Text(string='內容')
    milestone = fields.Char(string='里程碑')
    activity = fields.Selection(ACTIVITIES + [('tuning', '設定微調'), ('custom', '客製開發')],
                                string='工項',
                                help='這個階段主要對應哪一類工項；之後建專案時用來歸類任務。')
    week_from = fields.Integer(string='起（週）')
    week_to = fields.Integer(string='迄（週）')
    hours = fields.Float(string='工時（小時）')
    weeks = fields.Integer(string='週數', compute='_compute_weeks')
    density = fields.Float(string='投入密度（時／週）', compute='_compute_weeks')

    @api.depends('week_from', 'week_to', 'hours')
    def _compute_weeks(self):
        for rec in self:
            rec.weeks = (rec.week_to - rec.week_from + 1) \
                if rec.week_from and rec.week_to >= rec.week_from else 0
            rec.density = rec.hours / rec.weeks if rec.weeks else 0.0

    @api.constrains('week_from', 'week_to')
    def _check_weeks(self):
        for rec in self:
            if rec.week_from and rec.week_to and rec.week_to < rec.week_from:
                raise ValidationError(_('階段「%s」的結束週不能早於開始週。') % rec.name)


class ProposalAcceptanceUnit(models.Model):
    """驗收單元＝預算大類：金額按它涵蓋的估算明細歸屬，沒歸屬的明細（專案管理等）依比例攤。"""
    _name = 'corpaas.knowledge.acceptance_unit'
    _description = '建議書：驗收單元（預算大類）'
    _inherit = ['corpaas.knowledge.proposal.child']
    _order = 'proposal_id, sequence, id'

    proposal_id = fields.Many2one('corpaas.knowledge.proposal', required=True,
                                  ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    name = fields.Char(string='單元', required=True)
    criteria = fields.Text(string='驗收標準', help='須全數通過；每行一條。')
    capability_ids = fields.Many2many(
        'corpaas.knowledge.capability', 'kb_acceptance_unit_capability_rel',
        'unit_id', 'capability_id', string='涵蓋能力')
    is_custom_bucket = fields.Boolean(
        string='客製開發類', help='客製開發的估算明細歸到這一類（不論它對應哪個能力）。')
    line_ids = fields.One2many('corpaas.knowledge.estimate_line', 'acceptance_unit_id',
                               string='歸屬的估算明細')
    currency_id = fields.Many2one(related='proposal_id.currency_id')
    hours = fields.Float(string='工時（小時）', compute='_compute_share')
    ratio = fields.Float(string='占比（%）', compute='_compute_share')
    amount = fields.Monetary(string='金額', compute='_compute_share')

    @api.depends('line_ids.days', 'line_ids.amount', 'proposal_id.estimate_line_ids.days',
                 'proposal_id.estimate_line_ids.amount',
                 'proposal_id.estimate_line_ids.acceptance_unit_id')
    def _compute_share(self):
        """歸屬明細全額計入；沒歸屬的明細依各單元的直接工時比例攤。

        ★ 所以不論怎麼歸類，各單元金額加總＝估算總額（四捨五入除外）—— 預算配比表的
          合計不會和報價總額對不上。
        """
        by_proposal = defaultdict(lambda: self.browse())
        for unit in self:
            by_proposal[unit.proposal_id] |= unit
        for proposal, units in by_proposal.items():
            hpd = proposal._settings()['hours_per_day'] or 8.0
            all_units = proposal.unit_ids
            lines = proposal.estimate_line_ids
            spread = lines.filtered(lambda l: not l.acceptance_unit_id)
            spread_days, spread_amount = sum(spread.mapped('days')), sum(spread.mapped('amount'))
            direct = {u.id: (sum(u.line_ids.mapped('days')), sum(u.line_ids.mapped('amount')))
                      for u in all_units}
            direct_total = sum(d for d, _a in direct.values())
            total_days = sum(lines.mapped('days'))
            for unit in units:
                days, amount = direct.get(unit.id, (0.0, 0.0))
                share = (days / direct_total) if direct_total else (
                    1.0 / len(all_units) if all_units else 0.0)
                unit.hours = (days + spread_days * share) * hpd
                unit.amount = amount + spread_amount * share
                unit.ratio = ((days + spread_days * share) / total_days * 100.0) \
                    if total_days else 0.0


class ProposalPaymentTerm(models.Model):
    _name = 'corpaas.knowledge.payment_term'
    _description = '建議書：付款款別'
    _inherit = ['corpaas.knowledge.proposal.child']
    _order = 'proposal_id, sequence, id'

    proposal_id = fields.Many2one('corpaas.knowledge.proposal', required=True,
                                  ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    name = fields.Char(string='款別', required=True)
    trigger = fields.Char(string='時點', help='例如「合約簽署後 10 日內」「該單元驗收簽認後 10 日內」。')
    ratio = fields.Float(string='比例（%）', required=True, default=100.0)
    unit_id = fields.Many2one('corpaas.knowledge.acceptance_unit', string='計算基準單元',
                              domain="[('proposal_id', '=', proposal_id)]",
                              ondelete='set null',
                              help='留空＝以整份報價總額為基準；選了單元＝以該單元金額為基準。')
    currency_id = fields.Many2one(related='proposal_id.currency_id')
    amount = fields.Monetary(string='金額', compute='_compute_amount')

    @api.depends('ratio', 'unit_id.amount', 'proposal_id.total')
    def _compute_amount(self):
        for rec in self:
            base = rec.unit_id.amount if rec.unit_id else rec.proposal_id.total
            rec.amount = (base or 0.0) * (rec.ratio or 0.0) / 100.0


class ProposalClauseTemplate(models.Model):
    """條款庫：從既有報價規格書歸納出的備註、免責、範圍與付款條款。"""
    _name = 'corpaas.knowledge.clause_template'
    _description = '建議書條款庫'
    _order = 'category, sequence, id'

    code = fields.Char(string='代號', required=True)
    sequence = fields.Integer(default=10)
    category = fields.Selection([
        ('disclaimer', '備註與免責'), ('scope', '範圍與變更'), ('data', '資料與移轉'),
        ('technical', '技術與授權'), ('payment', '付款與驗收'),
        ('warranty', '保固與服務'), ('security', '資訊安全'),
    ], string='分類', required=True, default='disclaimer')
    text = fields.Text(string='條款', required=True,
                       help='變數用 {名稱}：customer、version_no、date、validity_days、'
                            'warranty_months、payment_days、day_rate、hourly_rate、total、hours。')
    condition = fields.Selection(clause_lib.CONDITIONS, string='適用條件', required=True,
                                 default='always')
    capability_ids = fields.Many2many(
        'corpaas.knowledge.capability', 'kb_clause_template_capability_rel',
        'template_id', 'capability_id', string='限定能力',
        help='有指定時，版本涵蓋其中任一能力才載入。')
    note = fields.Char(string='來源／說明')
    active = fields.Boolean(default=True)

    _sql_constraints = [('code_uniq', 'unique(code)', '條款代號不能重複。')]


class ProposalClauseLine(models.Model):
    _name = 'corpaas.knowledge.clause_line'
    _description = '建議書：條款'
    _inherit = ['corpaas.knowledge.proposal.child']
    _order = 'proposal_id, category, sequence, id'

    proposal_id = fields.Many2one('corpaas.knowledge.proposal', required=True,
                                  ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    template_id = fields.Many2one('corpaas.knowledge.clause_template', string='條款庫',
                                  ondelete='set null')
    category = fields.Selection(related='template_id.category', store=True)
    text = fields.Text(string='條款', required=True)
    included = fields.Boolean(string='列入', default=True)


class ProposalBenefitItem(models.Model):
    _name = 'corpaas.knowledge.benefit_item'
    _description = '建議書：效益評估'
    _inherit = ['corpaas.knowledge.proposal.child']
    _order = 'proposal_id, sequence, id'

    proposal_id = fields.Many2one('corpaas.knowledge.proposal', required=True,
                                  ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    name = fields.Char(string='作業項目', required=True)
    current_manual = fields.Char(string='現況人工')
    after = fields.Char(string='導入後')
    annual_saving = fields.Monetary(string='年化節省估算（假設）')
    assumption = fields.Text(string='假設說明')
    currency_id = fields.Many2one(related='proposal_id.currency_id')


class ProposalEstimateLineUnit(models.Model):
    _inherit = 'corpaas.knowledge.estimate_line'

    acceptance_unit_id = fields.Many2one(
        'corpaas.knowledge.acceptance_unit', string='驗收單元', ondelete='set null',
        domain="[('proposal_id', '=', proposal_id)]")


class KnowledgeProposalParts(models.Model):
    _inherit = 'corpaas.knowledge.proposal'

    basis_ids = fields.One2many('corpaas.knowledge.basis', 'proposal_id',
                                string='報價基礎', copy=True)
    change_ids = fields.One2many('corpaas.knowledge.change_line', 'proposal_id',
                                 string='需求核對與本版處理', copy=False)
    scope_ids = fields.One2many('corpaas.knowledge.scope_item', 'proposal_id',
                                string='範圍界線', copy=True)
    obligation_ids = fields.One2many('corpaas.knowledge.obligation', 'proposal_id',
                                     string='前提與客戶配合事項', copy=True)
    phase_ids = fields.One2many('corpaas.knowledge.phase', 'proposal_id',
                                string='導入階段', copy=True)
    unit_ids = fields.One2many('corpaas.knowledge.acceptance_unit', 'proposal_id',
                               string='驗收單元', copy=True)
    payment_ids = fields.One2many('corpaas.knowledge.payment_term', 'proposal_id',
                                  string='付款款別', copy=True)
    clause_ids = fields.One2many('corpaas.knowledge.clause_line', 'proposal_id',
                                 string='條款', copy=True)
    benefit_ids = fields.One2many('corpaas.knowledge.benefit_item', 'proposal_id',
                                  string='效益評估', copy=True)

    total_hours = fields.Float(string='預估總工時', compute='_compute_hours_payments')
    weeks_total = fields.Integer(string='預估週數', compute='_compute_hours_payments')
    fte_ratio = fields.Float(string='投入人力（FTE）', compute='_compute_hours_payments',
                             help='總工時 ÷（週數 × 每週 40 小時）。')
    payment_total = fields.Monetary(string='款別合計', compute='_compute_hours_payments')
    payment_gap = fields.Monetary(string='款別與總額差異', compute='_compute_hours_payments',
                                  help='首年總額減款別合計；不為 0 表示款別沒有涵蓋全部金額。')
    benefit_total = fields.Monetary(string='年化節省合計', compute='_compute_hours_payments')

    @api.depends('estimate_line_ids.days', 'phase_ids.week_to', 'payment_ids.amount',
                 'benefit_ids.annual_saving', 'total')
    def _compute_hours_payments(self):
        for rec in self:
            hpd = rec._settings()['hours_per_day'] or 8.0
            rec.total_hours = sum(rec.estimate_line_ids.mapped('days')) * hpd
            rec.weeks_total = max(rec.phase_ids.mapped('week_to') or [0])
            rec.fte_ratio = rec.total_hours / (rec.weeks_total * 40.0) \
                if rec.weeks_total else 0.0
            rec.payment_total = sum(rec.payment_ids.mapped('amount'))
            rec.payment_gap = (rec.total - rec.payment_total) if rec.payment_ids else 0.0
            rec.benefit_total = sum(rec.benefit_ids.mapped('annual_saving'))

    # ------------------------------------------------------------------
    # 複製新版：款別的計算基準單元要指到新版自己的單元
    # ------------------------------------------------------------------
    def copy(self, default=None):
        new = super().copy(default)
        if len(self) == 1 and new.unit_ids and new.payment_ids:
            # 單元與款別是一起複製的，款別的 unit_id 還指著舊版的單元；依順序對回新版的
            old_units = self.unit_ids.sorted(lambda u: (u.sequence, u.id))
            new_units = new.unit_ids.sorted(lambda u: (u.sequence, u.id))
            mapping = dict(zip(old_units.ids, new_units.ids))
            for term in new.payment_ids:
                if term.unit_id.id in mapping:
                    term.unit_id = mapping[term.unit_id.id]
        return new

    # ------------------------------------------------------------------
    # 驗收單元與付款
    # ------------------------------------------------------------------
    def action_suggest_units(self):
        """每個確認的能力一個驗收單元，另加一個客製開發類。已有單元就不動。"""
        self.ensure_one()
        self._ensure_draft()
        if self.unit_ids:
            raise UserError(_('已經有驗收單元了；要重來請先刪除既有的。'))
        Unit = self.env['corpaas.knowledge.acceptance_unit']
        vals = [{'proposal_id': self.id, 'sequence': 10 + i * 10, 'name': cap.name,
                 'capability_ids': [(6, 0, cap.ids)]}
                for i, cap in enumerate(self._capabilities())]
        if self.estimate_line_ids.filtered('is_custom'):
            vals.append({'proposal_id': self.id, 'sequence': 10 + len(vals) * 10,
                         'name': _('客製開發'), 'is_custom_bucket': True})
        Unit.create(vals)
        self.action_assign_units()
        return True

    def action_assign_units(self):
        """把估算明細歸到驗收單元：客製明細進客製類；其餘依單元涵蓋的能力。"""
        self.ensure_one()
        self._ensure_draft()
        for line in self.estimate_line_ids:
            unit = self.env['corpaas.knowledge.acceptance_unit']
            if line.is_custom:
                unit = self.unit_ids.filtered('is_custom_bucket')[:1]
            if not unit and line.capability_id:
                unit = self.unit_ids.filtered(
                    lambda u: line.capability_id in u.capability_ids)[:1]
            line.acceptance_unit_id = unit.id or False
        return True

    def action_suggest_payments(self):
        """動員款＋各單元驗收款（取自既有規格書最常見的款別）。已有款別就不動。"""
        self.ensure_one()
        self._ensure_draft()
        if self.payment_ids:
            raise UserError(_('已經有付款款別了；要重來請先刪除既有的。'))
        s = self._settings()
        days = s['payment_days']
        mob = s['mobilization_ratio']
        vals = [{'proposal_id': self.id, 'sequence': 10, 'name': _('動員款'), 'ratio': mob,
                 'trigger': _('合約簽署後 %s 日內') % days}]
        units = self.unit_ids
        if units:
            for i, unit in enumerate(units):
                vals.append({'proposal_id': self.id, 'sequence': 20 + i * 10,
                             'name': _('%s驗收款') % unit.name, 'ratio': 100.0 - mob,
                             'unit_id': unit.id,
                             'trigger': _('%(u)s驗收簽認後 %(d)s 日內', u=unit.name, d=days)})
        else:
            vals.append({'proposal_id': self.id, 'sequence': 20, 'name': _('驗收款'),
                         'ratio': 100.0 - mob,
                         'trigger': _('驗收簽認後 %s 日內') % days})
        self.env['corpaas.knowledge.payment_term'].create(vals)
        return True

    # ------------------------------------------------------------------
    # 階段
    # ------------------------------------------------------------------
    def action_suggest_phases(self):
        """依估算明細的工項產生階段；專案管理橫跨全程。取代既有階段。

        ★ 週數是啟發式：每階段工時 ÷ 每週投入工時（設定頁，預設 20 小時＝約 0.5 FTE，
          與既有規格書的投入密度相當）。它是起點，不是承諾 —— 人要看過再送出。
        """
        self.ensure_one()
        self._ensure_draft()
        if not self.estimate_line_ids:
            raise UserError(_('還沒有估算明細，無法產生階段；請先計算估算。'))
        s = self._settings()
        hpd, per_week = s['hours_per_day'] or 8.0, s['hours_per_week'] or 20.0
        days = defaultdict(float)
        caps = defaultdict(list)
        for line in self.estimate_line_ids:
            key = 'custom' if line.is_custom else line.activity
            days[key] += line.days
            name = line.capability_id.name
            if name and name not in caps[key]:
                caps[key].append(name)
        labels = dict(ACTIVITIES, tuning=_('設定微調'), custom=_('客製開發'))
        self.phase_ids.unlink()
        vals, week = [], 1
        for i, key in enumerate(k for k in PHASE_ORDER if days.get(k)):
            hours = days[key] * hpd
            weeks = max(1, math.ceil(hours / per_week - 1e-9))
            vals.append({
                'proposal_id': self.id, 'sequence': 10 + i * 10, 'code': 'P%s' % (i + 1),
                'name': labels[key], 'activity': key, 'hours': hours,
                'week_from': week, 'week_to': week + weeks - 1,
                'milestone': PHASE_MILESTONES.get(key, ''),
                'content': _('涵蓋：%s') % '、'.join(caps[key]) if caps[key] else False})
            week += weeks
        if days.get('pm'):
            vals.append({
                'proposal_id': self.id, 'sequence': 10 + len(vals) * 10, 'code': 'PM',
                'name': _('專案管理（全程分攤）'), 'activity': 'pm', 'hours': days['pm'] * hpd,
                'week_from': 1, 'week_to': max(week - 1, 1)})
        self.env['corpaas.knowledge.phase'].create(vals)
        return True

    # ------------------------------------------------------------------
    # 條款
    # ------------------------------------------------------------------
    def _clause_flags(self):
        """這個版本具備哪些特徵（決定哪些條款適用）。"""
        self.ensure_one()
        flags = {self.pricing_model}
        if self.estimate_line_ids.filtered('is_custom') or \
                self._active_mappings().filtered(lambda m: m.color == 'custom'):
            flags.add('custom_dev')
        if self.master_data_ids or self.estimate_line_ids.filtered(
                lambda l: l.activity == 'migration'):
            flags.add('data_migration')
        if self.integration_count:
            flags.add('integration')
        if self.company_count > 1:
            flags.add('multi_company')
        return flags

    def _clause_values(self):
        self.ensure_one()
        s = self._settings()
        hpd = s['hours_per_day'] or 8.0
        return {
            'customer': self.partner_id.display_name,
            'version_no': self.version_no,
            'date': fields.Date.to_string(self.version_date) if self.version_date else '',
            'validity_days': s['validity_days'],
            'warranty_months': s['warranty_months'],
            'payment_days': s['payment_days'],
            'acceptance_days': s['acceptance_days'],
            'payment_summary': self._payment_summary(s),
            'day_rate': self._money(self._day_rate(s)),
            'hourly_rate': self._money(self._day_rate(s) / hpd),
            'total': self._money(self.total),
            'hours': round(self.total_hours, 2),
        }

    def _payment_summary(self, settings=None):
        """付款條款的一句話：有填款別就照款別，沒有就用「簽約／驗收上線」兩期的預設。"""
        self.ensure_one()
        if not self.payment_ids:
            mob = (settings or self._settings())['mobilization_ratio']
            return _('簽約 %(a)g%%／驗收上線 %(b)g%%', a=mob, b=100.0 - mob)
        parts = []
        for term in self.payment_ids.sorted(lambda t: (t.sequence, t.id)):
            label = '%s %g%%' % (term.name, term.ratio)
            if term.trigger:
                label += '（%s）' % term.trigger
            parts.append(label)
        return '／'.join(parts)

    def action_load_clauses(self):
        """依這個版本的特徵載入條款庫。取代既有條款（人工改過的也會被取代）。"""
        self.ensure_one()
        self._ensure_draft()
        flags, values = self._clause_flags(), self._clause_values()
        caps = self._capabilities()
        vals = []
        for tpl in self.env['corpaas.knowledge.clause_template'].sudo().search([]):
            if not clause_lib.applies(tpl.condition, flags):
                continue
            if tpl.capability_ids and not (tpl.capability_ids & caps):
                continue
            vals.append({'proposal_id': self.id, 'template_id': tpl.id,
                         'sequence': tpl.sequence,
                         'text': clause_lib.render(tpl.text, values)})
        self.clause_ids.unlink()
        self.env['corpaas.knowledge.clause_line'].create(vals)
        return True

    # ------------------------------------------------------------------
    # 版本差異
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # 報價基礎：從商機的「會議與筆記」與附件帶入
    # ------------------------------------------------------------------
    def action_sync_sources(self):
        """把商機上列入報價基礎的會議／筆記與附件補進「報價基礎」。

        ★ 只放標題與日期，不放內容；已經有的不重複建立，筆記內容被改過的只更新指紋，
          筆記改名則連結列與沿用舊標題的基礎列一起改名。手動輸入的基礎列不動。
          複製新版時不更新舊指紋，「內容已更新」的標示才看得到；按這個按鈕才算「看過了」。
        """
        return self._sync_sources(prune=False)

    def action_sync_sources_prune(self):
        """同上，另外移除「商機上已取消列入或已刪除」的來源列（只動帶入的，不動手動列）。"""
        return self._sync_sources(prune=True)

    def _sync_sources(self, prune=False):
        Basis = self.env['corpaas.knowledge.basis']
        LeadSource = self.env['corpaas.knowledge.lead_source']
        keep_flag = self.env.context.get('sources_keep_flag')
        for rec in self:
            lead = rec.case_id.opportunity_id
            if not lead or rec.state != 'draft':
                continue
            included = lead.knowledge_source_ids.filtered('include_in_basis')
            renamed = {} if keep_flag else lead.knowledge_source_ids._refresh_titles()
            for (note_id, old_title), new_title in renamed.items():
                rec.basis_ids.filtered(lambda b: b.note_id.id == note_id
                                       and b.title == old_title).title = new_title
            if prune:
                rec.basis_ids.filtered(
                    lambda b: b.note_id and b.note_id not in included.note_id).unlink()
            start = max(rec.basis_ids.mapped('sequence') or [0])
            vals_list = []
            have_notes = rec.basis_ids.note_id
            for src in included:
                if src.note_id in have_notes:
                    row = rec.basis_ids.filtered(lambda b: b.note_id == src.note_id)[:1]
                    current = LeadSource._note_fingerprint(src.note_id)
                    if row.fingerprint != current and not keep_flag:
                        row.fingerprint = current
                    continue
                vals_list.append({
                    'proposal_id': rec.id, 'kind': 'meeting', 'date': src.note_date,
                    'title': src.note_title or _('會議記錄'), 'note_id': src.note_id.id,
                    'fingerprint': LeadSource._note_fingerprint(src.note_id),
                    'note': src.remark or False})
            attachments = self.env['ir.attachment'].sudo().search([
                ('res_model', '=', 'crm.lead'), ('res_id', '=', lead.id)])
            if prune:
                rec.basis_ids.filtered(
                    lambda b: b.ref_model == 'ir.attachment'
                    and b.ref_id not in attachments.ids).unlink()
            have_files = {b.ref_id for b in rec.basis_ids if b.ref_model == 'ir.attachment'}
            for att in attachments:
                if att.id not in have_files:
                    vals_list.append({
                        'proposal_id': rec.id, 'kind': 'file',
                        'date': fields.Date.to_date(att.create_date), 'title': att.name,
                        'ref_model': 'ir.attachment', 'ref_id': att.id})
            for i, vals in enumerate(vals_list):
                vals['sequence'] = start + 10 * (i + 1)
            Basis.create(vals_list)
        return True

    # ------------------------------------------------------------------
    # AI：從商機的會議與筆記萃取痛點
    # ------------------------------------------------------------------
    def action_ai_extract_pains(self):
        """★ 和「AI 比對能力」一樣排入佇列；只讀勾了「AI 可讀」的來源。"""
        self.ensure_one()
        self._ensure_draft()
        if not self.package_id:
            raise UserError(_('請先選方案套件；AI 工作需要掛在方案上排隊與記帳。'))
        if not self._ai_source_texts():
            raise UserError(_('商機上沒有勾選「AI 可讀」且有內容的會議或筆記。'))
        return self.env['corpaas.knowledge.ai'].enqueue(
            self, '_ai_extract_pains_run', self.package_id.sudo(), note=_('AI 萃取痛點'))

    def _ai_source_texts(self):
        lead = self.case_id.opportunity_id
        return lead.knowledge_source_ids._ai_texts() if lead else []

    def _ai_extract_pains_run(self):
        self.ensure_one()
        self._ensure_draft()
        texts = self._ai_source_texts()
        if not texts:
            raise UserError(_('沒有可讀的會議或筆記內容。'))
        payload = {'sources': [{'title': t, 'text': x} for t, x in texts],
                   'existing_pains': [p.description for p in self.pain_ids]}
        prompt = AI_PAIN_PROMPT % json.dumps(payload, ensure_ascii=False, indent=1)
        try:
            result = self.env['corpaas.knowledge.ai'].ask(
                'proposal_pains', prompt, package=self.package_id.sudo() or None, record=self)
        except hub_client.BudgetExceeded as e:
            raise UserError(_('AI 預算已用完，請稍後再試：%s') % e) from e
        except hub_client.HubError as e:
            raise UserError(_('AI 萃取失敗：%s') % e) from e
        items = result.get('pains') if isinstance(result, dict) else result
        if not isinstance(items, list):
            raise UserError(_('AI 回覆格式不對：缺少 pains 清單。'))
        seen = {versioning._key(p.description) for p in self.pain_ids}
        start = max(self.pain_ids.mapped('sequence') or [0])
        vals_list = []
        for item in items:
            if not isinstance(item, dict):
                continue
            desc = str(item.get('description') or '').strip()
            key = versioning._key(desc)
            if not desc or key in seen:
                continue
            seen.add(key)
            vals_list.append({
                'proposal_id': self.id, 'description': desc, 'source': 'ai_source',
                'sequence': start + 10 * (len(vals_list) + 1),
                'department': str(item.get('department') or '').strip() or False,
                'current_state': str(item.get('evidence') or '').strip() or False})
        self.env['corpaas.knowledge.pain'].create(vals_list)
        self.message_post(body=_('AI 從商機的會議與筆記萃取了 %s 個新痛點，請逐筆確認。')
                          % len(vals_list))
        return len(vals_list)

    # ------------------------------------------------------------------
    # 範圍草稿：由確認的對應推導
    # ------------------------------------------------------------------
    def action_draft_scope(self):
        """涵蓋＝確認、有能力、方案現有的對應；選配＝需加購；不涵蓋＝沿用現況／未確認／方案不含。

        只在還沒有任何範圍列時動作（不覆蓋人工整理過的範圍）。
        """
        self.ensure_one()
        self._ensure_draft()
        if self.scope_ids:
            raise UserError(_('已經有範圍項目了；要重來請先刪除既有的。'))
        pkg = self.package_id.sudo()
        rows, seen = [], set()

        def add(kind, name, detail):
            if (kind, name) not in seen:
                seen.add((kind, name))
                rows.append({'proposal_id': self.id, 'kind': kind, 'name': name,
                             'detail': detail or False,
                             'sequence': 10 * (len(rows) + 1)})
        for m in self.mapping_ids.sorted(lambda m: (m.pain_id.sequence, m.id)):
            pain = ((m.pain_id.description or '').strip().splitlines() or [''])[0][:80]
            cap = m.capability_id
            if not m.confirmed or m.color == 'as_is' or not cap:
                add('out', pain, _('沿用現況或尚未確認，不在本案範圍。'))
                continue
            availability = cap.sudo().availability_for(pkg)[0] if pkg else 'native'
            if availability == 'missing':
                add('out', cap.name, _('方案目前不含此能力。'))
            elif availability == 'addon':
                add('optional', cap.name, m.note)
            else:
                add('in', cap.name, pain)
        self.env['corpaas.knowledge.scope_item'].create(rows)
        return True

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.filtered(lambda r: r.state == 'draft').with_context(
            sources_keep_flag=True).action_sync_sources()
        return records

    def action_draft_changes(self):
        """以前一版的凍結快照為基準，替「本版處理」起一份差異草稿。

        只取代「版本差異」來源的列；手動輸入的客戶核對項不動。
        """
        self.ensure_one()
        self._ensure_draft()
        previous = self.supersedes_id
        if not previous or not previous.snapshot_json:
            raise UserError(_('這一版沒有已送出的前一版可以比較。'))
        old = json.loads(previous.snapshot_json)
        labels = dict(self.env['corpaas.knowledge.mapping']._fields['color'].selection)
        items = versioning.diff_snapshots(old, self._snapshot(), money=self._money,
                                          color_labels=labels)
        for b in self.basis_ids.filtered(lambda b: b.is_new or b.content_changed):
            items.append({
                'demand': _('新增參考資料：%s') % b.title if b.is_new
                else _('參考資料內容已更新：%s') % b.title,
                'handling': ''})
        self.change_ids.filtered(lambda c: c.origin == 'diff').unlink()
        start = max(self.change_ids.mapped('sequence') or [0])
        self.env['corpaas.knowledge.change_line'].create([
            {'proposal_id': self.id, 'sequence': start + 10 * (i + 1), 'origin': 'diff',
             'demand': item['demand'], 'handling': item['handling']}
            for i, item in enumerate(items)])
        return True
