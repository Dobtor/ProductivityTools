# -*- coding: utf-8 -*-
"""版本的組成：工時制計價、驗收單元與款別、階段、條款、版本差異。"""
import json

from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger

from ..services import clauses, versioning


@tagged('post_install', '-at_install')
class TestVersioningPure(TransactionCase):

    def _snap(self, pains, **prices):
        return {'pains': pains, 'prices': prices}

    def test_diff_reports_added_removed_and_changed_pains(self):
        old = self._snap([
            {'description': '月結要三天', 'mappings': [
                {'capability': '自動對帳', 'color': 'native', 'confirmed': True}]},
            {'description': '發票格式', 'mappings': []}],
            implementation_days=10, custom_days=0, total=100000)
        new = self._snap([
            {'description': '月結 要三天', 'mappings': [        # 只差空白＝同一個痛點
                {'capability': '自動對帳', 'color': 'dobtor', 'confirmed': True}]},
            {'description': '多公司合併報表', 'mappings': [
                {'capability': '合併報表', 'color': 'custom', 'confirmed': True}]}],
            implementation_days=12, custom_days=3, total=150000)
        items = versioning.diff_snapshots(old, new, color_labels={
            'native': '原生', 'dobtor': 'Dobtor現有', 'custom': '客製'})
        text = '\n'.join('%s | %s' % (i['demand'], i['handling']) for i in items)
        self.assertIn('新增痛點：多公司合併報表', text)
        self.assertIn('合併報表（客製）', text)
        self.assertIn('移除痛點：發票格式', text)
        self.assertIn('調整對應：月結', text)
        self.assertIn('Dobtor現有', text)
        self.assertIn('導入人天 10 → 12', text)
        self.assertIn('客製人天 0 → 3', text)
        self.assertIn('+50.0%', text)
        self.assertEqual(len([i for i in items if i['demand'].startswith('新增')]), 1,
                         '改個空白不能算新痛點')

    def test_diff_is_empty_when_nothing_changed(self):
        snap = self._snap([{'description': 'x', 'mappings': []}], total=1)
        self.assertEqual(versioning.diff_snapshots(snap, snap), [])

    def test_diff_reports_pricing_model_change(self):
        old = {'pains': [], 'prices': {}, 'pricing': {'model': 'subscription',
                                                       'model_label': '訂閱＋一次性導入'}}
        new = {'pains': [], 'prices': {}, 'pricing': {'model': 'time_budget',
                                                       'model_label': '工時制固定預算'}}
        items = versioning.diff_snapshots(old, new)
        self.assertEqual(items[0]['demand'], '計價方式變更')
        self.assertIn('工時制固定預算', items[0]['handling'])

    def test_clause_render_keeps_unknown_variables_visible(self):
        text = '有效期 {validity_days} 天，{unknown} 另計，範例 {A}。'
        out = clauses.render(text, {'validity_days': 60})
        self.assertEqual(out, '有效期 60 天，{unknown} 另計，範例 {A}。')
        self.assertEqual(clauses.unresolved(out), ['A', 'unknown'])
        # 值是 0 也要換（保固 0 個月是有意義的）
        self.assertEqual(clauses.render('{n} 個月', {'n': 0}), '0 個月')

    def test_clause_conditions(self):
        flags = {'subscription', 'custom_dev'}
        self.assertTrue(clauses.applies('always', flags))
        self.assertTrue(clauses.applies('custom_dev', flags))
        self.assertFalse(clauses.applies('time_budget', flags))
        self.assertTrue(clauses.applies(False, flags))


@tagged('post_install', '-at_install')
class TestVersionParts(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        icp = cls.env['ir.config_parameter'].sudo()
        for key, value in {'day_rate': 10000, 'internal_day_cost': 4000, 'hours_per_day': 8,
                           'cost_per_ccu_monthly': 100, 'hours_per_week': 20,
                           'validity_days': 60, 'warranty_months': 3, 'payment_days': 10,
                           'mobilization_ratio': 30}.items():
            icp.set_param('corpaas_proposal.%s' % key, value)
        cls.partner = cls.env['res.partner'].create({'name': '版本客戶'})
        Cap = cls.env['corpaas.knowledge.capability']
        cls.cap_a = Cap.create({'name': '財務', 'code': 'fin', 'color': 'native'})
        cls.cap_b = Cap.create({'name': '人資', 'code': 'hr', 'color': 'dobtor'})
        Tpl = cls.env['corpaas.knowledge.effort_template']
        Tpl.create({'capability_id': cls.cap_a.id, 'activity': 'requirements', 'base_days': 3})
        Tpl.create({'capability_id': cls.cap_b.id, 'activity': 'requirements', 'base_days': 2})
        Tpl.create({'activity': 'pm', 'base_days': 2})
        cls.Proposal = cls.env['corpaas.knowledge.proposal']

    def _ready(self, **vals):
        """兩個能力（3 與 2 人天）＋客製 4 人天＋專案管理 2 人天（通用）。"""
        prop = self.Proposal.create(dict({'partner_id': self.partner.id}, **vals))
        Pain = self.env['corpaas.knowledge.pain']
        Mapping = self.env['corpaas.knowledge.mapping']
        p1 = Pain.create({'proposal_id': prop.id, 'description': '財務要自動化'})
        p2 = Pain.create({'proposal_id': prop.id, 'description': '人資要請假'})
        p3 = Pain.create({'proposal_id': prop.id, 'description': '要客製報表'})
        Mapping.create([
            {'pain_id': p1.id, 'capability_id': self.cap_a.id, 'color': 'native',
             'confirmed': True},
            {'pain_id': p2.id, 'capability_id': self.cap_b.id, 'color': 'dobtor',
             'confirmed': True},
            {'pain_id': p3.id, 'color': 'custom', 'custom_days_low': 3, 'custom_days_high': 5,
             'confirmed': True}])
        prop.action_compute_estimate()
        return prop

    # ------------------------------------------------------------------
    # 工時制
    # ------------------------------------------------------------------
    def test_time_budget_prices_hours_without_subscription(self):
        prop = self._ready(pricing_model='time_budget', hourly_rate=2500)
        prop.action_compute_estimate()
        self.assertEqual(set(prop.estimate_line_ids.mapped('day_rate')), {20000.0},
                         '每小時 2,500 × 每人天 8 小時')
        self.assertEqual(prop.subscription_amount, 0)
        self.assertEqual(prop.addon_amount, 0)
        self.assertEqual(prop.total, (3 + 2 + 2 + 4) * 20000)
        self.assertEqual(prop.total_hours, 11 * 8)
        self.assertEqual(prop.infra_monthly_cost, 0, '工時制沒有我們代管的主機')
        self.assertIn('88.0', prop.pricing_note)
        self.assertIn('小時', prop.pricing_note)

    def test_hourly_rate_defaults_to_day_rate_over_hours(self):
        prop = self._ready(pricing_model='time_budget')
        self.assertEqual(set(prop.estimate_line_ids.mapped('day_rate')), {10000.0})

    def test_subscription_model_is_unchanged(self):
        prop = self._ready()
        self.assertEqual(set(prop.estimate_line_ids.mapped('day_rate')), {10000.0})
        self.assertGreater(prop.infra_monthly_cost, 0)

    def test_budget_gap_warns_when_over_budget(self):
        prop = self._ready(pricing_model='time_budget', hourly_rate=2500, budget_cap=200000)
        self.assertEqual(prop.budget_gap, 200000 - prop.total)
        self.assertLess(prop.budget_gap, 0)
        prop.budget_cap = 0
        self.assertEqual(prop.budget_gap, 0)

    def test_time_budget_quotation_has_no_package_and_no_provisioning(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'corpaas_proposal.service_product_id',
            self.env.ref('dobtor_corpaas_knowledge_proposal.product_implementation_service').id)
        prop = self._ready(pricing_model='time_budget', hourly_rate=2500)
        prop.action_create_sale_order()          # 沒有訂閱方案也能建
        order = prop.sale_order_id
        self.assertEqual(order.knowledge_provision_state, 'none')
        self.assertFalse(order._knowledge_provision_held())
        self.assertEqual(len(order.order_line), len(prop.estimate_line_ids))
        self.assertEqual(sum(order.order_line.mapped('price_subtotal')), prop.total)
        # 一般方案的報價單照舊：沒有方案就不能建
        sub = self._ready()
        with self.assertRaises(UserError):
            sub.action_create_sale_order()

    # ------------------------------------------------------------------
    # 驗收單元與款別
    # ------------------------------------------------------------------
    def test_units_cover_the_whole_total_and_spread_generic_lines(self):
        prop = self._ready(pricing_model='time_budget', hourly_rate=2500)
        prop.action_suggest_units()
        names = prop.unit_ids.mapped('name')
        self.assertEqual(sorted(names), sorted(['財務', '人資', '客製開發']))
        # 每個明細都歸到單元，除了沒有能力的專案管理
        unassigned = prop.estimate_line_ids.filtered(lambda l: not l.acceptance_unit_id)
        self.assertEqual(unassigned.mapped('activity'), ['pm'])
        by_name = {u.name: u for u in prop.unit_ids}
        # 財務 3 天直接 + 專案管理 2 天 ×（3/9）
        self.assertAlmostEqual(by_name['財務'].amount, 3 * 20000 + 2 * 20000 * 3 / 9, places=2)
        self.assertAlmostEqual(by_name['客製開發'].amount, 4 * 20000 + 2 * 20000 * 4 / 9,
                               places=2)
        # ★ 不論怎麼歸類，各單元金額加總＝總額；占比加總＝100
        self.assertAlmostEqual(sum(prop.unit_ids.mapped('amount')), prop.total, places=2)
        self.assertAlmostEqual(sum(prop.unit_ids.mapped('ratio')), 100.0, places=6)
        self.assertAlmostEqual(sum(prop.unit_ids.mapped('hours')), prop.total_hours, places=6)

    def test_payments_default_to_mobilization_plus_unit_acceptance(self):
        prop = self._ready(pricing_model='time_budget', hourly_rate=2500)
        prop.action_suggest_units()
        prop.action_suggest_payments()
        mobilization = prop.payment_ids[:1]
        self.assertEqual(mobilization.ratio, 30)
        self.assertAlmostEqual(mobilization.amount, prop.total * 0.3, places=2)
        self.assertIn('10 日內', mobilization.trigger)
        self.assertEqual(len(prop.payment_ids), 1 + len(prop.unit_ids))
        # 動員款 30% ＋ 各單元驗收款 70% ＝ 全額
        self.assertAlmostEqual(prop.payment_total, prop.total, places=2)
        self.assertAlmostEqual(prop.payment_gap, 0.0, places=2)
        prop.payment_ids[1:2].ratio = 50
        self.assertNotEqual(round(prop.payment_gap, 2), 0.0, '款別沒蓋滿要被看見')

    def test_suggestions_do_not_overwrite_existing_rows(self):
        prop = self._ready()
        prop.action_suggest_units()
        with self.assertRaises(UserError):
            prop.action_suggest_units()
        prop.action_suggest_payments()
        with self.assertRaises(UserError):
            prop.action_suggest_payments()

    def test_copy_points_payments_at_the_new_versions_units(self):
        v10 = self._ready(pricing_model='time_budget', hourly_rate=2500)
        v10.action_suggest_units()
        v10.action_suggest_payments()
        v10.action_send()
        v11 = self.Proposal.browse(v10.action_copy_new_version()['res_id'])
        self.assertEqual(len(v11.unit_ids), len(v10.unit_ids))
        self.assertFalse(set(v11.unit_ids.ids) & set(v10.unit_ids.ids))
        for term in v11.payment_ids:
            if term.unit_id:
                self.assertEqual(term.unit_id.proposal_id, v11,
                                 '款別的基準單元要指到新版自己的單元，不是舊版的')
        # 舊版沒被動到
        for term in v10.payment_ids:
            if term.unit_id:
                self.assertEqual(term.unit_id.proposal_id, v10)

    # ------------------------------------------------------------------
    # 階段
    # ------------------------------------------------------------------
    def test_phases_follow_the_estimate(self):
        prop = self._ready(pricing_model='time_budget', hourly_rate=2500)
        prop.action_suggest_phases()
        phases = {p.activity: p for p in prop.phase_ids}
        self.assertEqual(set(phases), {'requirements', 'custom', 'pm'})
        self.assertEqual(phases['requirements'].hours, 5 * 8)
        self.assertEqual(phases['custom'].hours, 4 * 8)
        # 20 小時／週：需求 40 小時＝2 週（第 1–2 週），客製 32 小時＝2 週（第 3–4 週）
        self.assertEqual((phases['requirements'].week_from, phases['requirements'].week_to),
                         (1, 2))
        self.assertEqual((phases['custom'].week_from, phases['custom'].week_to), (3, 4))
        # 專案管理橫跨全程
        self.assertEqual((phases['pm'].week_from, phases['pm'].week_to), (1, 4))
        self.assertEqual(prop.weeks_total, 4)
        self.assertAlmostEqual(sum(prop.phase_ids.mapped('hours')), prop.total_hours)
        self.assertEqual(phases['requirements'].milestone, '需求規格雙方簽認')
        self.assertIn('財務', phases['requirements'].content)
        # 再按一次是取代，不是疊加
        prop.action_suggest_phases()
        self.assertEqual(len(prop.phase_ids), 3)

    def test_phase_weeks_must_not_run_backwards(self):
        prop = self._ready()
        with self.assertRaises(ValidationError):
            self.env['corpaas.knowledge.phase'].create({
                'proposal_id': prop.id, 'name': '倒著走', 'week_from': 5, 'week_to': 2})

    # ------------------------------------------------------------------
    # 條款
    # ------------------------------------------------------------------
    def _templates(self):
        Tpl = self.env['corpaas.knowledge.clause_template'].sudo()
        Tpl.search([]).unlink()
        return {
            'always': Tpl.create({'code': 't_always', 'condition': 'always',
                                  'text': '有效期 {validity_days} 天（{customer}）'}),
            'custom': Tpl.create({'code': 't_custom', 'condition': 'custom_dev',
                                  'text': '客製項目以 {hourly_rate} 計', 'category': 'scope'}),
            'time': Tpl.create({'code': 't_time', 'condition': 'time_budget',
                                'text': '共 {hours} 小時'}),
            'sub': Tpl.create({'code': 't_sub', 'condition': 'subscription',
                               'text': '訂閱含更新'}),
            'cap_b': Tpl.create({'code': 't_cap_b', 'condition': 'always',
                                 'capability_ids': [(6, 0, self.cap_b.ids)],
                                 'text': '人資限定'}),
            'cap_other': Tpl.create({
                'code': 't_cap_other', 'condition': 'always', 'text': '別的能力',
                'capability_ids': [(6, 0, self.env['corpaas.knowledge.capability'].create(
                    {'name': '沒用到', 'code': 'unused', 'color': 'native'}).ids)]}),
            'bad': Tpl.create({'code': 't_bad', 'condition': 'always',
                               'text': '含 {未知變數} 與 {A}'}),
        }

    def test_clauses_load_by_condition_and_render_variables(self):
        self._templates()
        prop = self._ready(pricing_model='time_budget', hourly_rate=2500)
        prop.action_load_clauses()
        texts = prop.clause_ids.mapped('text')
        self.assertIn('有效期 60 天（版本客戶）', texts)
        self.assertTrue(any(t.startswith('客製項目以') and '2,500' in t for t in texts),
                        '時薪變數要換成金額')
        self.assertIn('共 88.0 小時', texts)
        self.assertNotIn('訂閱含更新', texts, '工時制不載入訂閱條款')
        self.assertIn('人資限定', texts, '涵蓋該能力才載入')
        self.assertNotIn('別的能力', texts)
        # 缺的變數原樣留著，讓人看得到
        self.assertIn('含 {未知變數} 與 {A}', texts)

    def test_reloading_clauses_replaces_and_a_subscription_gets_its_own(self):
        self._templates()
        prop = self._ready()
        prop.action_load_clauses()
        first = prop.clause_ids.ids
        self.assertIn('訂閱含更新', prop.clause_ids.mapped('text'))
        self.assertNotIn('共 88.0 小時', prop.clause_ids.mapped('text'))
        prop.action_load_clauses()
        self.assertFalse(set(first) & set(prop.clause_ids.ids))
        self.assertEqual(len(prop.clause_ids), len(first))

    def test_shipped_library_renders_without_leftover_variables(self):
        """出貨的條款庫：所有變數都要能被解析，否則客戶文件裡會出現 {xxx}。"""
        Tpl = self.env['corpaas.knowledge.clause_template'].sudo()
        shipped = Tpl.with_context(active_test=False).search(
            [('note', '!=', False)]).filtered(
            lambda t: t.get_external_id().get(t.id, '').startswith(
                'dobtor_corpaas_knowledge_proposal.clause_'))
        self.assertGreaterEqual(len(shipped), 30, '條款庫沒有出貨')
        self.assertTrue(shipped.filtered(lambda t: not t.active),
                        '法務性質的條款預設要停用')
        # 具備所有特徵的版本：工時制＋客製＋資料移轉＋串接＋多公司
        prop = self._ready(pricing_model='time_budget', hourly_rate=2500,
                           integration_count=2, company_count=3)
        prop.action_suggest_units()
        prop.action_suggest_payments()
        for tpl in shipped:                       # 連停用的也一起驗
            rendered = clauses.render(tpl.text, prop._clause_values())
            self.assertFalse(clauses.unresolved(rendered),
                             '%s 還有沒換掉的變數：%s' % (tpl.code, clauses.unresolved(rendered)))

    def test_default_library_loads_the_right_clauses_for_each_pricing_model(self):
        prop = self._ready(pricing_model='time_budget', hourly_rate=2500)
        prop.action_load_clauses()
        codes = set(prop.clause_ids.mapped('template_id.code'))
        self.assertIn('estimate_cap', codes)
        self.assertIn('time_report', codes)
        self.assertIn('custom_spec_baseline', codes, '有客製明細就載入客製規格條款')
        self.assertNotIn('subscription_includes', codes)
        self.assertNotIn('liability_cap', codes, '停用的條款不自動載入')
        sub = self._ready()
        sub.action_load_clauses()
        sub_codes = set(sub.clause_ids.mapped('template_id.code'))
        self.assertIn('subscription_includes', sub_codes)
        self.assertNotIn('estimate_cap', sub_codes)

    def test_payment_clause_follows_the_payment_table(self):
        prop = self._ready(pricing_model='time_budget', hourly_rate=2500)
        prop.action_load_clauses()
        default = prop.clause_ids.filtered(lambda c: c.template_id.code == 'payment_terms')
        self.assertIn('簽約 30%／驗收上線 70%', default.text)
        prop.action_suggest_units()
        prop.action_suggest_payments()
        prop.action_load_clauses()
        text = prop.clause_ids.filtered(lambda c: c.template_id.code == 'payment_terms').text
        self.assertIn('動員款 30%（合約簽署後 10 日內）', text)
        self.assertIn('財務驗收款 70%', text)

    def test_clause_code_is_unique(self):
        self._templates()
        with self.assertRaises(Exception), mute_logger('odoo.sql_db'):
            with self.env.cr.savepoint():
                self.env['corpaas.knowledge.clause_template'].create(
                    {'code': 't_always', 'text': '重複'})

    # ------------------------------------------------------------------
    # 版本差異草稿
    # ------------------------------------------------------------------
    def test_draft_changes_from_the_previous_version(self):
        v10 = self._ready()
        v10.action_send()
        v11 = self.Proposal.browse(v10.action_copy_new_version()['res_id'])
        # v1.1：多一個痛點、移除一個
        v11.pain_ids.filtered(lambda p: p.description == '人資要請假').unlink()
        pain = self.env['corpaas.knowledge.pain'].create({
            'proposal_id': v11.id, 'description': '要串接 LINE'})
        self.env['corpaas.knowledge.mapping'].create({
            'pain_id': pain.id, 'color': 'custom', 'custom_days_low': 2,
            'custom_days_high': 2, 'confirmed': True})
        v11.action_compute_estimate()
        manual = self.env['corpaas.knowledge.change_line'].create({
            'proposal_id': v11.id, 'demand': '客戶要求加串接', 'origin': 'manual'})
        v11.action_draft_changes()
        diff_lines = v11.change_ids.filtered(lambda c: c.origin == 'diff')
        text = '\n'.join(diff_lines.mapped('demand'))
        self.assertIn('新增痛點：要串接 LINE', text)
        self.assertIn('移除痛點：人資要請假', text)
        self.assertIn('報價金額與人天變動', text)
        # 再按一次只取代差異列，手動輸入的客戶核對項不動
        v11.action_draft_changes()
        self.assertIn(manual, v11.change_ids)
        self.assertEqual(len(v11.change_ids.filtered(lambda c: c.origin == 'diff')),
                         len(diff_lines))

    def test_draft_changes_needs_a_previous_version(self):
        with self.assertRaises(UserError):
            self._ready().action_draft_changes()

    # ------------------------------------------------------------------
    # 複製與凍結
    # ------------------------------------------------------------------
    def _fill_parts(self, prop):
        Basis = self.env['corpaas.knowledge.basis']
        Basis.create({'proposal_id': prop.id, 'kind': 'file', 'title': 'Requirements 匯出檔'})
        self.env['corpaas.knowledge.scope_item'].create(
            {'proposal_id': prop.id, 'kind': 'out', 'name': 'App 開發'})
        self.env['corpaas.knowledge.obligation'].create(
            {'proposal_id': prop.id, 'kind': 'client', 'text': '提供科目表'})
        self.env['corpaas.knowledge.benefit_item'].create(
            {'proposal_id': prop.id, 'name': '月結對帳', 'annual_saving': 120000})
        self.env['corpaas.knowledge.change_line'].create(
            {'proposal_id': prop.id, 'demand': '核對項'})

    def test_new_version_carries_the_parts_but_not_the_change_log(self):
        v10 = self._ready()
        self._fill_parts(v10)
        v10.action_send()
        v11 = self.Proposal.browse(v10.action_copy_new_version()['res_id'])
        self.assertEqual(v11.basis_ids.mapped('title'), ['Requirements 匯出檔'])
        self.assertEqual(v11.scope_ids.mapped('name'), ['App 開發'])
        self.assertEqual(v11.obligation_ids.mapped('text'), ['提供科目表'])
        self.assertEqual(v11.benefit_total, 120000)
        self.assertFalse(v11.change_ids, '每一版自己的需求核對，不繼承上一版的')
        self.assertEqual(v11.pricing_model, v10.pricing_model)

    def test_sent_version_freezes_every_part(self):
        prop = self._ready(pricing_model='time_budget', hourly_rate=2500)
        self._fill_parts(prop)
        prop.action_suggest_units()
        prop.action_suggest_payments()
        prop.action_suggest_phases()
        self._templates()
        prop.action_load_clauses()
        prop.action_send()
        for rec in (prop.basis_ids[:1], prop.scope_ids[:1], prop.obligation_ids[:1],
                    prop.benefit_ids[:1], prop.change_ids[:1], prop.phase_ids[:1],
                    prop.unit_ids[:1], prop.payment_ids[:1], prop.clause_ids[:1]):
            with self.assertRaises(UserError, msg=rec._name):
                rec.write({'sequence': 99})
            with self.assertRaises(UserError, msg=rec._name):
                rec.unlink()
        with self.assertRaises(UserError):
            self.env['corpaas.knowledge.scope_item'].create(
                {'proposal_id': prop.id, 'name': '送出後新增'})
        with self.assertRaises(UserError):
            prop.write({'pricing_model': 'subscription'})

    def test_snapshot_freezes_the_parts(self):
        self._templates()
        prop = self._ready(pricing_model='time_budget', hourly_rate=2500,
                           doc_purpose='導入範圍確認與預算配比')
        self._fill_parts(prop)
        prop.action_suggest_units()
        prop.action_suggest_payments()
        prop.action_suggest_phases()
        prop.action_load_clauses()
        prop.action_send()
        snap = json.loads(prop.snapshot_json)
        self.assertEqual(snap['pricing']['model'], 'time_budget')
        self.assertEqual(snap['pricing']['model_label'], '工時制固定預算')
        self.assertEqual(snap['pricing']['hourly_rate'], 2500)
        self.assertEqual([b['title'] for b in snap['basis']], ['Requirements 匯出檔'])
        self.assertEqual(snap['scope'][0]['kind'], 'out')
        self.assertEqual(len(snap['units']), 3)
        self.assertAlmostEqual(sum(u['amount'] for u in snap['units']), prop.total, places=2)
        self.assertAlmostEqual(sum(p['amount'] for p in snap['payments']), prop.total, places=2)
        self.assertEqual(len(snap['phases']), 3)
        self.assertTrue(snap['clauses'])
        self.assertEqual(snap['benefits'][0]['saving'], 120000)
        self.assertEqual(snap['changes'][0]['demand'], '核對項')

    def test_excluded_clauses_are_not_in_the_snapshot(self):
        self._templates()
        prop = self._ready()
        prop.action_load_clauses()
        prop.clause_ids[:1].included = False
        count = len(prop.clause_ids)
        prop.action_send()
        self.assertEqual(len(json.loads(prop.snapshot_json)['clauses']), count - 1)

    def test_new_settings_have_defaults(self):
        settings = self.env['res.config.settings'].proposal_settings()
        self.assertEqual(settings['validity_days'], 60)
        self.assertEqual(settings['warranty_months'], 3)
        self.assertEqual(settings['payment_days'], 10)
        self.assertEqual(settings['mobilization_ratio'], 30.0)
        self.assertEqual(settings['hours_per_week'], 20.0)
