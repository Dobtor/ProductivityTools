# -*- coding: utf-8 -*-
import base64
from unittest.mock import patch

from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged

from odoo.addons.dobtor_corpaas_knowledge.services import hub_client

# 1x1 PNG
PNG = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==')


@tagged('post_install', '-at_install')
class TestKnowledgeMarketing(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.Ai = type(env['corpaas.knowledge.ai'])
        cls.Cap = type(env['corpaas.knowledge.capability'])
        cls.Pkg = type(env['infrastructure.solution.package'])
        cls.Tmpl = type(env['product.template'])
        env['ir.config_parameter'].sudo().set_param(
            'corpaas_knowledge.public_base_url', 'https://docs.example.com/')
        cls.tmpl = env['product.template'].create({'name': 'KB 行銷測試方案', 'type': 'service'})
        cls.package = env['infrastructure.solution.package'].create(
            {'product_tmpl_id': cls.tmpl.id})
        Feature = env['corpaas.knowledge.feature']

        def feature(anchor, name):
            return Feature.create({
                'feature_key': Feature.make_key('kb_mkt_test', 'action', anchor),
                'module': 'kb_mkt_test', 'kind': 'action', 'anchor': anchor, 'name': name,
                'package_ids': [(6, 0, cls.package.ids)]})

        cls.f_signup = feature('signup', '線上報名')
        cls.f_pay = feature('pay', '線上收費')
        cls.cap = env['corpaas.knowledge.capability'].create({
            'name': '報名收費一條龍', 'code': 'signup_pay',
            'pain': '報名表與收款對不起來', 'outcome': '報名即收款',
            'feature_ids': [(6, 0, (cls.f_signup | cls.f_pay).ids)],
            'package_ids': [(6, 0, cls.package.ids)]})
        cls.scenario = env['corpaas.knowledge.scenario'].create(
            {'name': '協會年會', 'code': 'kb_mkt_assoc', 'glossary': '客戶=會員'})
        cls.asset = cls._make_asset('signup.png')

    @classmethod
    def _make_asset(cls, name):
        att = cls.env['ir.attachment'].create({'name': name, 'raw': PNG,
                                               'mimetype': 'image/png'})
        return cls.env['corpaas.knowledge.asset'].create({
            'name': '報名表', 'shot_name': 'signup_form', 'feature_id': cls.f_signup.id,
            'scenario_id': cls.scenario.id, 'attachment_id': att.id})

    def _ai(self, data):
        return patch.object(self.Ai, 'ask', return_value=data)

    def _capture_enqueue(self):
        calls = []

        def fake(model_self, record, method_name, package, note=''):
            calls.append((record, method_name, package))
            return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {}}
        return patch.object(self.Ai, 'enqueue', fake), calls

    def _pitch(self):
        pitch = self.env['corpaas.knowledge.pitch'].create({
            'capability_id': self.cap.id, 'product_tmpl_id': self.tmpl.id,
            'headline': '報名就收到錢', 'body_html': '<p>痛點到成果</p>',
            'asset_ids': [(6, 0, self.asset.ids)]})
        pitch._replace_claims([{'text': '報名後立即線上付款', 'features': [self.f_pay.feature_key]},
                               {'text': '報名表自動建檔', 'features': [self.f_signup.feature_key]}])
        return pitch

    def _publish(self, rec):
        rec.knowledge_propose('claim')
        rec.action_approve()
        self.assertEqual(rec.state, 'published')

    def _event(self, etype, feature, token='tok-1', package=None):
        return self.env['corpaas.knowledge.event'].create({
            'type': etype, 'package_id': (package or self.package).id,
            'feature_id': feature.id, 'refresh_token': token})

    def _dispatch(self, events, token='tok-1', package=None):
        self.env['corpaas.knowledge.hooks']._knowledge_dispatch_events(
            package or self.package, events, {'token': token, 'full': False})

    def _remove(self, feature, package=None):
        """模擬核心盤點：功能從這個方案消失（per-package presence）。"""
        package = package or self.package
        feature.write({'package_ids': [(3, package.id)],
                       'missing_package_ids': [(4, package.id)]})

    # ------------------------------------------------------------------
    def test_package_resolution(self):
        pitch = self._pitch()
        self.assertEqual(self.tmpl._knowledge_package(), self.package)
        self.assertEqual(self.tmpl._knowledge_package(self.tmpl.product_variant_id), self.package)
        self.assertEqual(pitch.package_id, self.package, '建立時帶入商品頁對應的方案')

    def test_review_always_required(self):
        pitch = self._pitch()
        for change in ('shot', 'text', 'claim', 'new', 'restore'):
            self.assertTrue(pitch._knowledge_requires_review(change))
        pitch.knowledge_propose('shot')
        self.assertEqual(pitch.state, 'review')
        self.assertFalse(pitch.live_json, '沒核准不能有上線快照')
        note = self.env['corpaas.knowledge.release_note'].create(
            {'product_tmpl_id': self.tmpl.id, 'title': 'x'})
        note.knowledge_propose('shot')
        self.assertEqual(note.state, 'review')

    def test_live_snapshot_isolates_unapproved_edits(self):
        pitch = self._pitch()
        self._publish(pitch)
        pitch.headline = '還沒核准的新標題'
        card = self.tmpl._knowledge_marketing_values()['pitches'][0]
        self.assertEqual(card['headline'], '報名就收到錢')
        self.assertEqual(len(card['images']), 1)
        self.assertIn('access_token=', card['images'][0]['url'])

    def test_guard_live_fields(self):
        pitch = self._pitch()
        for vals in ({'state': 'published'}, {'live_json': '{"headline": "x"}'},
                     {'images_hidden': True}):
            with self.assertRaises(UserError):
                pitch.write(vals)
        with self.assertRaises(UserError):
            self.env['corpaas.knowledge.pitch'].create({
                'capability_id': self.cap.id, 'product_tmpl_id': self.tmpl.id,
                'state': 'published'})
        with self.assertRaises(UserError):
            pitch.claim_ids[:1].write({'state': 'check'})
        note = self.env['corpaas.knowledge.release_note'].create(
            {'product_tmpl_id': self.tmpl.id, 'title': 'x'})
        with self.assertRaises(UserError):
            note.write({'live_json': '{}'})
        self._publish(pitch)
        self.assertEqual(pitch.copy().state, 'draft')

    def test_resubmit_published(self):
        pitch = self._pitch()
        self._publish(pitch)
        pitch.headline = '新的標題'
        pitch.action_submit()
        self.assertEqual(pitch.state, 'review')
        self.assertEqual(self.tmpl._knowledge_marketing_values()['pitches'][0]['headline'],
                         '報名就收到錢', '核准前前台仍是上線版')
        pitch.action_approve()
        self.assertEqual(self.tmpl._knowledge_marketing_values()['pitches'][0]['headline'],
                         '新的標題')

    def test_claim_anchoring_feature_removed(self):
        pitch = self._pitch()
        self._publish(pitch)
        pay_claim = pitch.claim_ids.filtered(lambda c: self.f_pay in c.feature_ids)
        signup_claim = pitch.claim_ids - pay_claim
        self._remove(self.f_pay)
        with self._ai({}) as ask:
            self._dispatch(self._event('feature_removed', self.f_pay))
            ask.assert_not_called()
        self.assertEqual(pay_claim.state, 'check')
        self.assertIn('線上收費', pay_claim.reason)
        self.assertEqual(signup_claim.state, 'ok')
        self.assertEqual(pitch.state, 'stale')
        self.assertTrue(pitch.images_hidden)
        card = self.tmpl._knowledge_marketing_values()['pitches'][0]
        self.assertEqual(card['images'], [], '失效期間前台不顯示圖')
        self.assertEqual(card['headline'], '報名就收到錢', '舊版仍在線上')
        self.assertEqual(card['claims'], ['報名表自動建檔'], '待查的宣稱不上商品頁')
        self.assertTrue(self.env['corpaas.knowledge.hooks']._knowledge_check_feature_ref(self.f_pay))

    def test_removal_is_per_package(self):
        pitch = self._pitch()
        self._publish(pitch)
        other = self.env['infrastructure.solution.package'].create(
            {'product_tmpl_id': self.tmpl.id})
        self.f_pay.package_ids = [(4, other.id)]
        # 另一個方案拿掉了 → 這個方案的卡片不動
        self._remove(self.f_pay, other)
        self._dispatch(self._event('feature_removed', self.f_pay, package=other), package=other)
        self.assertEqual(pitch.state, 'published')
        self.assertEqual(pitch.claim_check_count, 0)
        # 事件說消失、但功能在這個方案其實還在 → 不動
        self._dispatch(self._event('feature_removed', self.f_signup))
        self.assertEqual(pitch.state, 'published')

    def test_rename_candidate_is_not_removal(self):
        pitch = self._pitch()
        self._publish(pitch)
        self._remove(self.f_pay)
        self.env['corpaas.knowledge.rename'].create({
            'old_feature_id': self.f_pay.id, 'new_feature_id': self.f_signup.id,
            'similarity': 0.9})
        self._dispatch(self._event('feature_removed', self.f_pay))
        self.assertEqual(pitch.state, 'published')
        self.assertEqual(pitch.claim_check_count, 0)

    def test_scope_changed_only_swaps_images(self):
        pitch = self._pitch()
        self._publish(pitch)
        new = self._make_asset('signup-v2.png')
        self.asset.state = 'superseded'
        self._dispatch(self._event('scope_changed', self.f_signup))
        self.assertEqual(pitch.state, 'published')
        self.assertEqual(pitch.claim_check_count, 0)
        self.assertFalse(pitch.images_hidden)
        self.assertEqual(pitch.asset_ids, new)
        self.assertEqual(pitch._live()['asset_ids'], new.ids)
        card = self.tmpl._knowledge_marketing_values()['pitches'][0]
        self.assertIn('/web/image/%s?' % new.attachment_id.id, card['images'][0]['url'])

    def test_form_changed_does_not_flag(self):
        pitch = self._pitch()
        self._publish(pitch)
        self._dispatch(self._event('form_changed', self.f_signup))
        self.assertEqual(pitch.state, 'published')
        self.assertEqual(pitch.claim_check_count, 0)

    def test_publish_requires_resolved_claims(self):
        pitch = self._pitch()
        self._publish(pitch)
        self._remove(self.f_pay)
        self._dispatch(self._event('feature_removed', self.f_pay))
        pay_claim = pitch.claim_ids.filtered(lambda c: c.state == 'check')
        pitch.action_submit()
        with self.assertRaises(UserError):
            pitch.action_approve()
        self.assertEqual(pay_claim.state, 'check', '核准失敗不能把待查洗掉')
        with self.assertRaises(UserError):
            pay_claim.action_mark_ok()
        # 改錨定到方案裡還在的功能 → 自動回正常
        pay_claim.feature_ids = [(6, 0, self.f_signup.ids)]
        self.assertEqual(pay_claim.state, 'ok')
        pitch.action_approve()
        self.assertEqual(pitch.state, 'published')
        self.assertFalse(pitch.images_hidden)

    def test_publish_blocked_when_anchor_not_in_package(self):
        pitch = self._pitch()
        self._remove(self.f_pay)
        pitch.knowledge_propose('claim')
        with self.assertRaises(UserError):
            pitch.action_approve()
        pitch.claim_ids.filtered(lambda c: self.f_pay in c.feature_ids).unlink()
        pitch.action_approve()
        self.assertEqual(pitch.state, 'published')

    def test_release_note_from_feature_added(self):
        new = self.env['corpaas.knowledge.feature'].create({
            'feature_key': 'kb_mkt_test.action:refund', 'module': 'kb_mkt_test',
            'kind': 'action', 'anchor': 'refund', 'name': '線上退費',
            'package_ids': [(6, 0, self.package.ids)]})
        unclassified = self.env['corpaas.knowledge.feature'].create({
            'feature_key': 'kb_mkt_test.action:misc', 'module': 'kb_mkt_test',
            'kind': 'action', 'anchor': 'misc', 'name': '雜項'})
        self.env['corpaas.knowledge.selection'].create({
            'package_id': self.package.id, 'kind': 'feature', 'feature_id': new.id,
            'capability_id': self.cap.id})
        events = self._event('feature_added', new) | self._event('feature_added', unclassified)
        reply = {'title': '報名可以線上退費了', 'body_html': '<p>退費</p><script>x</script>'}
        with self._ai(reply) as ask:
            self._dispatch(events)
            self.assertEqual(ask.call_count, 1)
            self.assertIn('線上退費', ask.call_args.args[1])
            self.assertNotIn('雜項', ask.call_args.args[1])
        note = self.env['corpaas.knowledge.release_note'].search(
            [('package_id', '=', self.package.id), ('refresh_token', '=', 'tok-1')])
        self.assertEqual(len(note), 1)
        self.assertEqual(note.feature_ids, new)
        self.assertEqual(note.state, 'review')
        self.assertEqual(note.pending_change, 'claim')
        self.assertNotIn('script', note.body_html)
        with self._ai(reply) as ask:
            self._dispatch(events)
            ask.assert_not_called()
        self.assertEqual(self.env['corpaas.knowledge.release_note'].search_count(
            [('package_id', '=', self.package.id)]), 1, '同一次 refresh 不重複起草')
        # 發佈後，功能又從方案消失 → 失效、商品頁撤下
        note.action_approve()
        self.assertTrue(self.tmpl._knowledge_marketing_values()['release_note'])
        self._remove(new)
        self._dispatch(self._event('feature_removed', new, token='tok-3'), token='tok-3')
        self.assertEqual(note.state, 'stale')
        self.assertFalse(self.tmpl._knowledge_marketing_values()['release_note'])

    def test_release_note_budget_exceeded_retries_next_refresh(self):
        self.f_pay.capability_ids = [(4, self.cap.id)]
        self.package.knowledge_capability_ids = [(4, self.cap.id)]
        with patch.object(self.Ai, 'ask', side_effect=hub_client.BudgetExceeded('滿了')):
            self._dispatch(self._event('feature_added', self.f_pay))
        note = self.env['corpaas.knowledge.release_note'].search(
            [('package_id', '=', self.package.id)])
        self.assertTrue(note.ai_pending)
        self.assertEqual(note.state, 'draft')
        with self._ai({'title': '新增線上收費', 'body_html': '<p>ok</p>'}):
            self._dispatch(self.env['corpaas.knowledge.event'], token='tok-2')
        self.assertFalse(note.ai_pending)
        self.assertEqual(note.state, 'review')

    def test_release_note_notify_subscribers(self):
        note = self.env['corpaas.knowledge.release_note'].create(
            {'product_tmpl_id': self.tmpl.id, 'package_id': self.package.id,
             'title': '本期新增：線上退費', 'body_html': '<p>退費</p>'})
        with self.assertRaises(UserError):
            note.action_notify_subscribers()
        self._publish(note)
        subscriber = self.env['res.partner'].create({'name': '訂戶', 'email': 'sub@example.com'})
        with patch.object(type(note), '_marketing_subscriber_partners',
                          lambda s: subscriber):
            action = note.action_notify_subscribers()
        ctx = action['context']
        self.assertEqual(action['res_model'], 'mail.compose.message')
        self.assertEqual(ctx['default_composition_mode'], 'mass_mail')
        self.assertEqual(ctx['default_res_ids'], subscriber.ids)
        self.assertEqual(ctx['default_subject'], '本期新增：線上退費')
        self.assertIn('退費', str(ctx['default_body']))

    def test_subscriber_partners_from_contracts(self):
        if 'dobtor.contract.line' not in self.env:
            self.skipTest('沒有合約模組')
        note = self.env['corpaas.knowledge.release_note'].create(
            {'product_tmpl_id': self.tmpl.id, 'package_id': self.package.id, 'title': 'x'})
        active = self.env['res.partner'].create({'name': '在用', 'email': 'a@example.com'})
        closed = self.env['res.partner'].create({'name': '已退', 'email': 'b@example.com'})
        variant = self.tmpl.product_variant_id
        for partner, state in ((active, 'inprogress'), (closed, 'closed')):
            order = self.env['sale.order'].create({'partner_id': partner.id})
            contract = self.env['dobtor.contract'].create({'partner_id': partner.id})
            self.env['dobtor.contract.line'].create({
                'order_id': order.id, 'name': variant.name, 'product_id': variant.id,
                'subscription_product_line_id': contract.id, 'state': state})
        self.assertEqual(note._marketing_subscriber_partners(), active)

    def _upsell_patches(self, sellable=('kb_mkt_x',)):
        index = patch.object(self.Tmpl, '_knowledge_sellable_index', autospec=True,
                             return_value=(set(sellable), {}))
        mods = patch.object(self.Pkg, '_provision_module_names', lambda s: ['kb_mkt_test'])
        return index, mods

    def test_upsell_scoped_to_package(self):
        hooks = self.env['corpaas.knowledge.hooks']
        self.cap.write({'state': 'published', 'required_module_names': 'kb_mkt_x'})
        # 沒掛在這個方案上的能力：就算是 addon 也不推
        stranger = self.env['corpaas.knowledge.capability'].create({
            'name': '外部能力', 'code': 'stranger', 'required_module_names': 'kb_mkt_x'})
        stranger.write({'state': 'published'})
        index, mods = self._upsell_patches()
        with index as idx, mods:
            caps = [i['capability'] for i in self.tmpl._knowledge_upsell_capabilities(self.package)]
            self.assertEqual(caps, [self.cap])
            self.assertEqual(idx.call_count, 1, '整頁只查一次可販售模組')
            links = hooks._knowledge_help_links(self.package, [(self.f_pay, 1.0)], None, {})
            upsell = [link for link in links if link['kind'] == 'upsell']
            self.assertEqual(len(upsell), 1)
            self.assertEqual(upsell[0]['feature_key'], self.f_pay.feature_key)
            self.assertEqual(
                upsell[0]['url'], 'https://docs.example.com/corpaas/solution/%s#kb-addon-signup_pay'
                % self.tmpl.product_variant_id.id)
            by_query = hooks._knowledge_help_links(self.package, [], '報名收費', {})
            self.assertTrue([link for link in by_query if link['kind'] == 'upsell'])
            unrelated = hooks._knowledge_help_links(self.package, [], 'zzzz', {})
            self.assertFalse([link for link in unrelated if link['kind'] == 'upsell'])
            addons = self.tmpl._knowledge_marketing_values()['addons']
            self.assertEqual([a['name'] for a in addons], ['報名收費一條龍'])
        # 缺的模組不能單獨販售 → 不是 addon
        index, mods = self._upsell_patches(sellable=())
        with index, mods:
            self.assertFalse(self.tmpl._knowledge_upsell_capabilities(self.package))

    def test_upsell_skips_unpublished_capability(self):
        self.cap.required_module_names = 'kb_mkt_x'
        index, mods = self._upsell_patches()
        with index, mods:
            links = self.env['corpaas.knowledge.hooks']._knowledge_help_links(
                self.package, [(self.f_pay, 1.0)], None, {})
        self.assertFalse([link for link in links if link['kind'] == 'upsell'])

    def test_ai_draft_pitch_from_capability(self):
        self.cap.scenario_ids = [(6, 0, self.scenario.ids)]
        reply = {'headline': '會員報名即收款',
                 'body_html': '<p>痛點</p><a href="https://x">連結</a>',
                 'claims': [{'text': '會員報名後可立即付款', 'features': [self.f_pay.feature_key]},
                            {'text': '沒標功能點的宣稱', 'features': ['nope.action:x']},
                            {'text': '', 'features': []}]}
        enqueue, calls = self._capture_enqueue()
        with enqueue, self._ai(reply) as ask:
            self.cap.action_ai_draft_pitch()
            ask.assert_not_called()
            self.assertEqual(len(calls), 1, '按鈕只排入佇列，不在請求裡呼叫 AI')
            record, method, package = calls[0]
            self.assertEqual((method, package), ('_ai_draft_run', self.package))
            getattr(record, method)()
            prompt = ask.call_args.args[1]
        self.assertIn('客戶', prompt)
        self.assertIn('會員', prompt)
        pitch = self.cap.pitch_ids
        self.assertEqual(len(pitch), 1)
        self.assertEqual(pitch.state, 'review')
        self.assertEqual(pitch.headline, '會員報名即收款')
        self.assertNotIn('href', pitch.body_html)
        self.assertEqual(pitch.scenario_id, self.scenario)
        self.assertEqual(pitch.package_id, self.package)
        self.assertEqual(pitch.asset_ids, self.asset)
        claims = pitch.claim_ids.sorted('sequence')
        self.assertEqual(len(claims), 2)
        self.assertEqual(claims[0].feature_ids, self.f_pay)
        self.assertEqual(claims[1].feature_ids, self.f_signup | self.f_pay, '對不上就錨定整個能力')
        enqueue, calls = self._capture_enqueue()
        with enqueue:
            self.cap.action_ai_draft_pitch()
        self.assertEqual(len(self.cap.pitch_ids), 1, '同一方案改寫同一張卡片')

    def test_ai_buttons_enqueue(self):
        pitch = self._pitch()
        note = self.env['corpaas.knowledge.release_note'].create(
            {'product_tmpl_id': self.tmpl.id, 'package_id': self.package.id, 'title': 'x',
             'feature_ids': [(6, 0, self.f_pay.ids)]})
        enqueue, calls = self._capture_enqueue()
        with enqueue, self._ai({}) as ask:
            pitch.action_ai_draft()
            note.action_ai_draft()
            ask.assert_not_called()
        self.assertEqual([(r, m, p) for r, m, p in calls],
                         [(pitch, '_ai_draft_run', self.package),
                          (note, '_ai_draft_run', self.package)])
        orphan = self.env['corpaas.knowledge.release_note'].create(
            {'product_tmpl_id': self.tmpl.id, 'title': 'y'})
        with self.assertRaises(UserError):
            orphan.action_ai_draft()

    def test_restore_revision_rebuilds_claims(self):
        pitch = self._pitch()
        self._publish(pitch)
        rev = self.env['corpaas.knowledge.revision'].search(
            [('res_model', '=', pitch._name), ('res_id', '=', pitch.id),
             ('was_published', '=', True)], limit=1)
        pitch.claim_ids[:1].unlink()
        pitch.action_restore_revision(rev)
        self.assertEqual(len(pitch.claim_ids), 2)
        self.assertEqual(pitch.state, 'review')

    # ------------------------------------------------------------------
    def _editor(self):
        return new_test_user(self.env, 'kb_mkt_editor', groups=(
            'base.group_user,dobtor_corpaas_knowledge.group_knowledge_editor'))

    def test_guard_context_key_cannot_be_forged(self):
        """RPC 能送任意 context：編輯者帶舊的 context 鍵也不能改上線欄位。"""
        pitch = self._pitch()
        self._publish(pitch)
        forged = pitch.with_user(self._editor()).with_context(knowledge_marketing_publish=True)
        for vals in ({'state': 'published'}, {'live_json': '{"headline": "偷渡"}'},
                     {'images_hidden': True}):
            with self.assertRaises(UserError):
                forged.write(vals)
        with self.assertRaises(UserError):
            forged.claim_ids[:1].write({'state': 'check'})
        note = self.env['corpaas.knowledge.release_note'].create(
            {'product_tmpl_id': self.tmpl.id, 'title': 'x'})
        with self.assertRaises(UserError):
            note.with_user(self._editor()).with_context(
                knowledge_marketing_publish='knowledge_marketing_publish').write(
                {'state': 'published', 'live_json': '{}'})

    def test_editor_cannot_retire(self):
        pitch = self._pitch()
        self._publish(pitch)
        with self.assertRaises(AccessError):
            pitch.with_user(self._editor()).action_retire()
        self.assertEqual(pitch.state, 'published')
        self.assertTrue(pitch.live_json)
        # 系統流程（事件派送）的下架不看使用者權限，但一樣能過上線欄位防護
        pitch.with_user(self._editor())._knowledge_retire()
        self.assertEqual(pitch.state, 'retired')
        self.assertFalse(pitch.live_json)

    def test_deleted_check_claim_not_reexposed(self):
        pitch = self._pitch()
        self._publish(pitch)
        self._remove(self.f_pay)
        self._dispatch(self._event('feature_removed', self.f_pay))
        pitch.claim_ids.filtered(lambda c: c.state == 'check').unlink()
        card = self.tmpl._knowledge_marketing_values()['pitches'][0]
        self.assertEqual(card['claims'], ['報名表自動建檔'], '刪掉待查宣稱不能讓快照那句重新上線')

    def test_live_claim_hidden_when_snapshot_anchor_gone(self):
        pitch = self._pitch()
        self._publish(pitch)
        # 還沒派送事件（宣稱仍是正常），但快照錨定的功能已不在方案裡
        self._remove(self.f_pay)
        card = self.tmpl._knowledge_marketing_values()['pitches'][0]
        self.assertEqual(card['claims'], ['報名表自動建檔'])

    def test_resubmitted_release_note_stays_visible(self):
        note = self.env['corpaas.knowledge.release_note'].create(
            {'product_tmpl_id': self.tmpl.id, 'package_id': self.package.id,
             'title': '上線版標題', 'feature_ids': [(6, 0, self.f_pay.ids)]})
        self.assertFalse(self.tmpl._knowledge_marketing_values()['release_note'],
                         '從未上線的不顯示')
        self._publish(note)
        note.title = '改稿中'
        note.action_submit()
        self.assertEqual(note.state, 'review')
        shown = self.tmpl._knowledge_marketing_values()['release_note']
        self.assertEqual(shown['title'], '上線版標題', '送審中照舊顯示上線快照')
        note.action_retire()
        self.assertFalse(self.tmpl._knowledge_marketing_values()['release_note'])

    def _query_count(self, fn):
        self.env.flush_all()
        self.env.invalidate_all()
        before = self.cr.sql_log_count
        fn()
        return self.cr.sql_log_count - before

    def test_product_page_queries_constant(self):
        def page():
            return self.tmpl._knowledge_marketing_values()
        pitches = self.env['corpaas.knowledge.pitch']
        for _i in range(5):
            pitch = self._pitch()
            self._publish(pitch)
            pitches |= pitch
        # 截圖被重拍取代：每張卡片都要跟到最新版（最容易變成逐張查詢的路徑）
        self.asset.state = 'superseded'
        new = self._make_asset('signup-v2.png')
        page()  # 暖機：access token 等一次性寫入
        five = self._query_count(page)
        cards = page()['pitches']
        self.assertEqual(len(cards), 5)
        self.assertTrue(all('/web/image/%s?' % new.attachment_id.id in c['images'][0]['url']
                            for c in cards))
        pitches[1:].action_retire()
        page()
        one = self._query_count(page)
        self.assertEqual(len(page()['pitches']), 1)
        self.assertLessEqual(five, one + 4, '查詢數不能跟卡片數成正比（1 張 %s、5 張 %s）'
                             % (one, five))
