# -*- coding: utf-8 -*-
"""案件與版本：版號、前版指標、商機（直接依賴 sale_crm）、舊資料遷移。"""
import json
from datetime import date

from psycopg2 import IntegrityError

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged('post_install', '-at_install')
class TestCase(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        icp = cls.env['ir.config_parameter'].sudo()
        for key, value in {'day_rate': 10000, 'internal_day_cost': 4000,
                           'cost_per_ccu_monthly': 100, 'hours_per_day': 8}.items():
            icp.set_param('corpaas_proposal.%s' % key, value)
        cls.partner = cls.env['res.partner'].create({'name': '案件客戶'})
        cls.cap = cls.env['corpaas.knowledge.capability'].create({
            'name': '案件能力', 'code': 'case_cap', 'color': 'native'})
        cls.env['corpaas.knowledge.effort_template'].create({
            'capability_id': cls.cap.id, 'activity': 'requirements', 'base_days': 3})
        cls.Proposal = cls.env['corpaas.knowledge.proposal']

    def _ready(self, **vals):
        """一份有確認對應、算好估算、可以送出的建議書。"""
        prop = self.Proposal.create(dict({'partner_id': self.partner.id}, **vals))
        pain = self.env['corpaas.knowledge.pain'].create({
            'proposal_id': prop.id, 'description': '要一個系統'})
        self.env['corpaas.knowledge.mapping'].create({
            'pain_id': pain.id, 'capability_id': self.cap.id, 'color': 'native',
            'confirmed': True})
        prop.action_compute_estimate()
        return prop

    # ------------------------------------------------------------------
    def test_every_proposal_belongs_to_a_case(self):
        prop = self.Proposal.create({'partner_id': self.partner.id})
        self.assertTrue(prop.case_id)
        self.assertEqual((prop.version_major, prop.version_minor, prop.version_no),
                         (1, 0, 'v1.0'))
        self.assertEqual(prop.case_id.partner_id, self.partner)
        self.assertTrue(prop.case_id.name.startswith('CAS/'))
        self.assertIn('v1.0', prop.display_name)

    def test_copy_is_the_next_version_of_the_same_case(self):
        v10 = self._ready()
        v10.action_send()
        v11 = self.Proposal.browse(v10.action_copy_new_version()['res_id'])
        self.assertEqual(v11.case_id, v10.case_id)
        self.assertEqual(v11.version_no, 'v1.1')
        self.assertEqual(v11.supersedes_id, v10)
        self.assertEqual(v11.state, 'draft')
        self.assertEqual(v11.version_date, date.today())
        self.assertIn(v11, v10.superseded_by_ids)
        # 從舊版再複製：接在案件最大版號後面，不會又一個 v1.1
        v12 = self.Proposal.browse(v10.action_copy_new_version()['res_id'])
        self.assertEqual(v12.version_no, 'v1.2')
        self.assertEqual(v12.supersedes_id, v10)

    def test_major_version(self):
        v10 = self._ready()
        v10.action_send()
        v11 = self.Proposal.browse(v10.action_copy_new_version()['res_id'])
        v20 = self.Proposal.browse(v11.action_copy_major_version()['res_id'])
        self.assertEqual(v20.version_no, 'v2.0')
        v21 = self.Proposal.browse(v20.action_copy_new_version()['res_id'])
        self.assertEqual(v21.version_no, 'v2.1')
        self.assertEqual(v10.case_id.version_count, 4)
        self.assertEqual(v10.case_id.current_version_id, v21)

    def test_version_number_is_unique_within_a_case(self):
        prop = self.Proposal.create({'partner_id': self.partner.id})
        with self.assertRaises(IntegrityError), mute_logger('odoo.sql_db'):
            with self.env.cr.savepoint():
                self.Proposal.create({
                    'partner_id': self.partner.id, 'case_id': prop.case_id.id,
                    'version_major': 1, 'version_minor': 0})

    def test_new_proposal_on_an_existing_case_gets_the_next_number(self):
        prop = self.Proposal.create({'partner_id': self.partner.id})
        again = self.Proposal.create({
            'partner_id': self.partner.id, 'case_id': prop.case_id.id})
        self.assertEqual(again.version_no, 'v1.1')

    def test_case_state_and_quoted_total(self):
        v10 = self._ready()
        case = v10.case_id
        self.assertEqual(case.state, 'open')
        self.assertFalse(case.quoted_version_id)        # 草稿還不算客戶手上的版本
        v10.action_send()
        self.assertEqual(case.quoted_version_id, v10)
        self.assertEqual(case.quoted_total, v10.total)
        v11 = self.Proposal.browse(v10.action_copy_new_version()['res_id'])
        self.assertEqual(case.quoted_version_id, v10, '新版是草稿，客戶手上還是 v1.0')
        v10.action_mark_won()
        self.assertEqual(case.state, 'won')
        self.assertEqual(v11.case_id, case)

    def test_case_is_lost_only_when_every_version_is_lost(self):
        v10 = self._ready()
        v10.action_send()
        v10.action_mark_lost()
        self.assertEqual(v10.case_id.state, 'lost')
        v11 = self.Proposal.browse(v10.action_copy_new_version()['res_id'])
        self.assertEqual(v10.case_id.state, 'open', '有一個草稿新版＝案件還沒結束')
        self.assertEqual(v11.state, 'draft')

    def test_frozen_version_cannot_be_renumbered_or_moved(self):
        v10 = self._ready()
        v10.action_send()
        other = self.Proposal.create({'partner_id': self.partner.id}).case_id
        for vals in ({'case_id': other.id}, {'version_minor': 9}, {'doc_purpose': '改掉'}):
            with self.assertRaises(UserError):
                v10.write(vals)

    def test_snapshot_carries_the_version(self):
        v10 = self._ready(doc_purpose='業務報價範圍參考')
        v10.action_send()
        snap = json.loads(v10.snapshot_json)
        self.assertEqual(snap['version']['no'], 'v1.0')
        self.assertEqual(snap['version']['purpose'], '業務報價範圍參考')
        self.assertEqual(snap['case']['name'], v10.case_id.name)
        v11 = self.Proposal.browse(v10.action_copy_new_version()['res_id'])
        v11.action_compute_estimate()
        v11.action_send()
        self.assertEqual(json.loads(v11.snapshot_json)['version']['supersedes'], 'v1.0')

    # ------------------------------------------------------------------
    # 商機（直接依賴 sale_crm）
    # ------------------------------------------------------------------
    def _lead(self, name='某商機'):
        return self.env['crm.lead'].create({
            'name': name, 'type': 'opportunity', 'partner_id': self.partner.id})

    def test_one_opportunity_can_have_several_cases(self):
        lead = self._lead()
        first = lead.action_create_knowledge_case()
        second = lead.action_create_knowledge_case()
        self.assertNotEqual(first['res_id'], second['res_id'])
        self.assertEqual(lead.knowledge_case_count, 2)
        action = lead.action_view_knowledge_cases()
        self.assertEqual(action['view_mode'], 'list,form', '多個案件列清單，不直接開其中一個')
        self.assertEqual(self.env['corpaas.knowledge.case'].browse(first['res_id'])
                         .opportunity_id, lead)

    def test_create_case_from_lead_needs_a_customer(self):
        lead = self.env['crm.lead'].create({'name': '沒客戶', 'type': 'opportunity'})
        with self.assertRaises(UserError):
            lead.action_create_knowledge_case()

    def test_follow_up_case_points_to_the_original(self):
        original = self.Proposal.create({'partner_id': self.partner.id}).case_id
        extra = self.env['corpaas.knowledge.case'].create({
            'partner_id': self.partner.id, 'parent_case_id': original.id,
            'title': '追加開發'})
        self.assertEqual(original.child_case_ids, extra)

    def test_sale_order_carries_the_opportunity(self):
        lead = self._lead()
        case = self.env['corpaas.knowledge.case'].browse(
            lead.action_create_knowledge_case()['res_id'])
        prop = self._ready(case_id=case.id)
        prop.product_tmpl_id = self.env['product.template'].create(
            {'name': 'KB 案件方案', 'type': 'service'})
        prop.action_create_sale_order()
        # ★ 以前建單沒帶商機：sale_crm 的收入回填與專案回寫商機都是斷的
        self.assertEqual(prop.sale_order_id.opportunity_id, lead)

    def test_send_updates_lead_revenue_across_cases(self):
        lead = self._lead()
        Case = self.env['corpaas.knowledge.case']
        case_a = Case.browse(lead.action_create_knowledge_case()['res_id'])
        case_b = Case.browse(lead.action_create_knowledge_case()['res_id'])
        a = self._ready(case_id=case_a.id)
        b = self._ready(case_id=case_b.id)
        self.assertTrue(a.total and b.total)
        a.action_send()
        self.assertEqual(lead.expected_revenue, a.total)
        b.action_send()
        # ★ 後送出的不能把前一案蓋掉：商機收入是兩案合計
        self.assertEqual(lead.expected_revenue, a.total + b.total)
        self.assertTrue(lead.message_ids.filtered(
            lambda m: '已送出' in (m.body or '') and case_a.name in (m.body or '')))
        # 失敗的案件不再算進收入；成交／失敗從不自動搬商機階段，也不封存商機
        stage = lead.stage_id
        a.action_mark_lost()
        self.assertEqual(lead._knowledge_revenue_from_cases(), b.total)
        b.action_mark_won()
        self.assertEqual(lead.stage_id, stage)
        self.assertTrue(lead.active)

    def test_lead_revenue_sync_can_be_turned_off(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'corpaas_proposal.sync_lead_revenue', 'False')
        lead = self._lead()
        lead.expected_revenue = 123
        case = self.env['corpaas.knowledge.case'].browse(
            lead.action_create_knowledge_case()['res_id'])
        prop = self._ready(case_id=case.id)
        prop.action_send()
        self.assertEqual(lead.expected_revenue, 123, '關掉就不碰收入')
        self.assertTrue(lead.message_ids.filtered(lambda m: '已送出' in (m.body or '')),
                        '但進展留言還是要有')

    def test_settings_bool_is_not_fooled_by_the_string_false(self):
        icp = self.env['ir.config_parameter'].sudo()
        settings = self.env['res.config.settings']
        icp.set_param('corpaas_proposal.sync_lead_revenue', 'False')
        self.assertFalse(settings.proposal_settings()['sync_lead_revenue'])
        icp.set_param('corpaas_proposal.sync_lead_revenue', 'True')
        self.assertTrue(settings.proposal_settings()['sync_lead_revenue'])
        icp.set_param('corpaas_proposal.sync_lead_revenue', '')
        self.assertTrue(settings.proposal_settings()['sync_lead_revenue'], '沒設＝預設開')

    # ------------------------------------------------------------------
    # 舊資料遷移
    # ------------------------------------------------------------------
    def test_legacy_proposals_become_cases(self):
        sent = self._ready()
        sent.action_send()
        draft = self.Proposal.create({'partner_id': self.partner.id})
        # 模擬 1.x 的資料：沒有案件、沒有版號
        self.env.cr.execute(
            "UPDATE corpaas_knowledge_proposal SET case_id = NULL, version_major = 0, "
            "version_minor = 0 WHERE id IN %s", [(sent.id, draft.id)])
        self.env.invalidate_all()
        moved = self.env['corpaas.knowledge.case']._migrate_legacy_proposals()
        self.assertEqual(moved, 2)
        for prop in (sent, draft):
            self.assertTrue(prop.case_id)
            self.assertEqual(prop.version_no, 'v1.0')
        self.assertNotEqual(sent.case_id, draft.case_id, '不替舊資料猜「同一案件」')
        self.assertEqual(sent.state, 'sent', '送出的版本照樣是送出的')
        self.assertEqual(self.env['corpaas.knowledge.case']._migrate_legacy_proposals(), 0,
                         '再跑一次不重複遷移')


@tagged('post_install', '-at_install')
class TestLeadSources(TransactionCase):
    """商機「會議與筆記」→ 報價基礎。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({'name': '來源客戶'})
        cls.lead = cls.env['crm.lead'].create({
            'name': '來源商機', 'type': 'opportunity', 'partner_id': cls.partner.id})
        cls.n_cust = cls.env['note.note'].create({'memo': '<p>客戶訪談</p><p>月結太慢</p>'})
        cls.n_int = cls.env['note.note'].create({'memo': '<p>內部討論底價</p>'})
        Src = cls.env['corpaas.knowledge.lead_source']
        cls.s_cust = Src.create({'lead_id': cls.lead.id, 'note_id': cls.n_cust.id})
        cls.s_int = Src.create({'lead_id': cls.lead.id, 'note_id': cls.n_int.id,
                                'role': 'internal'})
        cls.case = cls.env['corpaas.knowledge.case'].create({
            'partner_id': cls.partner.id, 'opportunity_id': cls.lead.id})

    def _version(self):
        return self.env['corpaas.knowledge.proposal'].create({
            'partner_id': self.partner.id, 'case_id': self.case.id})

    def test_internal_defaults_out_of_basis(self):
        self.assertTrue(self.s_cust.include_in_basis)
        self.assertFalse(self.s_int.include_in_basis)
        self.assertEqual(self.s_cust.note_title, '客戶訪談')

    def test_new_version_pulls_basis_titles_only(self):
        v = self._version()
        self.assertEqual(v.basis_ids.note_id, self.n_cust)
        self.assertEqual(v.basis_ids.kind, 'meeting')
        self.assertNotIn('月結太慢', v.basis_ids.title + (v.basis_ids.note or ''))

    def test_unique_link(self):
        with self.assertRaises(IntegrityError), mute_logger('odoo.sql_db'):
            self.env['corpaas.knowledge.lead_source'].create({
                'lead_id': self.lead.id, 'note_id': self.n_cust.id})

    def test_attachment_becomes_file_basis(self):
        att = self.env['ir.attachment'].create({
            'name': '需求.xlsx', 'res_model': 'crm.lead', 'res_id': self.lead.id,
            'raw': b'x'})
        v = self._version()
        row = v.basis_ids.filtered(lambda b: b.ref_model == 'ir.attachment')
        self.assertEqual(row.ref_id, att.id)
        v.action_sync_sources()
        self.assertEqual(len(v.basis_ids.filtered(lambda b: b.ref_id == att.id)), 1)

    def test_changed_note_flagged_in_next_version(self):
        v1 = self._version()
        self.assertFalse(v1.basis_ids.content_changed)
        self.n_cust.memo = '<p>客戶訪談</p><p>月結太慢，另要合併報表</p>'
        self.assertTrue(v1.basis_ids.content_changed)
        v1.action_sync_sources()
        self.assertFalse(v1.basis_ids.content_changed)
        self.n_cust.memo = '<p>客戶訪談</p><p>再改一次</p>'
        v2 = v1.copy()
        self.assertTrue(v2.basis_ids.content_changed)

    def test_wizard_defaults_to_event_notes(self):
        n_ev = self.env['note.note'].create({'memo': '<p>會議</p>'})
        event = self.env['calendar.event'].create({
            'name': '需求會議', 'start': '2026-10-01 02:00:00', 'stop': '2026-10-01 03:00:00',
            'opportunity_id': self.lead.id})
        n_ev.calendar_event_ids = [(4, event.id)]
        wiz = self.env['corpaas.knowledge.lead_source.wizard'].with_context(
            default_lead_id=self.lead.id).create({'lead_id': self.lead.id})
        self.assertEqual(wiz.note_ids, n_ev)
        wiz.action_confirm()
        link = self.lead.knowledge_source_ids.filtered(lambda s: s.note_id == n_ev)
        self.assertEqual(link.note_date.isoformat(), '2026-10-01')

    # ---- 優化項 ----
    def test_ai_readable_defaults_and_texts(self):
        self.assertTrue(self.s_cust.ai_readable)
        self.assertFalse(self.s_int.ai_readable)
        texts = (self.s_cust | self.s_int)._ai_texts()
        self.assertEqual([t for t, _x in texts], ['客戶訪談'])
        self.assertIn('月結太慢', texts[0][1])
        self.s_int.ai_readable = True
        self.assertEqual(len((self.s_cust | self.s_int)._ai_texts()), 2)

    def test_ai_extract_pains_dedupes_and_marks_source(self):
        from unittest.mock import patch
        v = self._version()
        v.pain_ids = [(0, 0, {'description': '月結 太慢'})]
        answer = {'pains': [
            {'department': '財務', 'description': '月結太慢', 'evidence': '重複'},
            {'department': '業務', 'description': '報價要手工做', 'evidence': '客戶訪談：…'},
            {'description': '報價要手工做'}, 'junk', {'description': ''}]}
        Ai = type(self.env['corpaas.knowledge.ai'])
        with patch.object(Ai, 'ask', return_value=answer) as ask:
            self.assertEqual(v._ai_extract_pains_run(), 1)
        self.assertEqual(ask.call_args.args[0], 'proposal_pains')
        prompt = ask.call_args.args[1]
        self.assertIn('月結太慢', prompt)
        self.assertNotIn('內部討論底價', prompt)       # 內部討論預設 AI 不可讀
        new = v.pain_ids.filtered(lambda p: p.source == 'ai_source')
        self.assertEqual(new.description, '報價要手工做')
        self.assertEqual(new.department, '業務')

    def test_ai_extract_needs_readable_sources(self):
        self.s_cust.ai_readable = False
        with self.assertRaises(UserError):
            self._version().action_ai_extract_pains()

    def test_sync_prune_removes_only_synced_rows(self):
        v = self._version()
        manual = self.env['corpaas.knowledge.basis'].create({
            'proposal_id': v.id, 'title': '手動列'})
        self.s_cust.include_in_basis = False
        v.action_sync_sources()
        self.assertTrue(v.basis_ids.filtered('note_id'))      # 一般帶入不刪
        v.action_sync_sources_prune()
        self.assertFalse(v.basis_ids.filtered('note_id'))
        self.assertIn(manual, v.basis_ids)

    def test_sync_follows_note_rename(self):
        v = self._version()
        self.n_cust.memo = '<p>改名後的標題</p><p>月結太慢</p>'
        v.action_sync_sources()
        self.assertEqual(self.s_cust.note_title, '改名後的標題')
        self.assertEqual(v.basis_ids.title, '改名後的標題')

    def test_snapshot_keeps_basis_fingerprint(self):
        v = self._version()
        snap = v._snapshot()
        self.assertTrue(snap['basis'][0]['fingerprint'])

    def test_draft_scope_from_mappings(self):
        cap = self.env['corpaas.knowledge.capability'].create({
            'name': '自動對帳', 'code': 'sc_cap', 'color': 'native'})
        v = self._version()
        pains = self.env['corpaas.knowledge.pain'].create([
            {'proposal_id': v.id, 'description': '對帳慢'},
            {'proposal_id': v.id, 'description': '維持舊報表'},
            {'proposal_id': v.id, 'description': '尚未確認的需求'}])
        Mapping = self.env['corpaas.knowledge.mapping']
        Mapping.create([
            {'pain_id': pains[0].id, 'capability_id': cap.id, 'color': 'native',
             'confirmed': True},
            {'pain_id': pains[1].id, 'color': 'as_is', 'confirmed': True},
            {'pain_id': pains[2].id, 'capability_id': cap.id, 'color': 'native'}])
        v.action_draft_scope()
        by_kind = {(s.kind, s.name) for s in v.scope_ids}
        self.assertIn(('in', '自動對帳'), by_kind)
        self.assertIn(('out', '維持舊報表'), by_kind)
        self.assertIn(('out', '尚未確認的需求'), by_kind)
        with self.assertRaises(UserError):
            v.action_draft_scope()

    def test_ai_extract_needs_package(self):
        v = self._version()
        v.package_id = False
        with self.assertRaises(UserError):
            v.action_ai_extract_pains()

    def test_draft_scope_survives_blank_pain(self):
        v = self._version()
        pain = self.env['corpaas.knowledge.pain'].create({
            'proposal_id': v.id, 'description': '   '})
        self.env['corpaas.knowledge.mapping'].create({
            'pain_id': pain.id, 'color': 'as_is', 'confirmed': True})
        v.action_draft_scope()
        self.assertEqual(v.scope_ids.kind, 'out')
