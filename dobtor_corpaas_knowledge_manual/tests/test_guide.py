# -*- coding: utf-8 -*-
"""說明書改善：開始之前（本說明怎麼用、開始前必設定）、章末（狀態速查、訊息與狀況對照）、
步驟寫法（開始前要先有／完成後會看到）、情境說明舉示範資料的實際數字、流程位置。"""
import json
from unittest.mock import patch

from odoo.tests.common import tagged

from ..services import guide_lib, prompts
from .common import ManualCase
from .test_hooks import FakeSandbox


@tagged('post_install', '-at_install')
class TestGuide(ManualCase):

    def setUp(self):
        super().setUp()
        self.f3.capability_ids = [(5,)]
        self.cap_b.feature_ids = [(5,)]
        self.cap_a.feature_ids = [(6, 0, (self.f1 | self.f2 | self.f3).ids)]
        self.Ai = self.env['corpaas.knowledge.ai']

    def _flow(self):
        Flow = self.env['corpaas.knowledge.flow'].sudo()
        flow = Flow.create({
            'model': 'res.partner', 'model_name': '報名', 'state_field': 'kbg_state',
            'field_type': 'selection', 'capability_id': self.cap_a.id,
            'package_ids': [(4, self.pkg.id)], 'feature_ids': [(6, 0, (self.f1 | self.f2).ids)]})
        for i, (v, label) in enumerate([('draft', '草稿'), ('done', '完成')]):
            self.env['corpaas.knowledge.flow.step'].sudo().create({
                'flow_id': flow.id, 'sequence': i, 'value': v, 'label': label,
                'on_statusbar': True})
        self.env['corpaas.knowledge.flow.transition'].sudo().create({
            'flow_id': flow.id, 'from_value': 'draft', 'to_value': 'done',
            'button_name': 'action_confirm', 'button_label': '確認',
            'button_feature_id': self.f2.id})
        self.f2.kind = 'button'
        return flow

    def _publish_three(self):
        arts = [self._article(f, self.cap_a, name=n) for f, n in
                ((self.f1, '甲 建立報名'), (self.f2, '乙 報名確認'), (self.f3, '丙 收款'))]
        self._publish(*arts)
        return arts

    def _section(self):
        return self._channel().knowledge_section_ids.filtered(
            lambda s: s.capability_id == self.cap_a)

    def _guide(self, section, kind):
        return section.guide_slide_ids.filtered(lambda g: g.kind == kind).slide_id

    # ------------------------------------------------------------------
    def test_front_section_first_with_howto(self):
        self._publish_three()
        channel = self._channel()
        front = self.env['corpaas.knowledge.channel_section'].search(
            [('channel_id', '=', channel.id), ('kind', '=', 'front')])
        self.assertEqual(front.name, '開始之前')
        self.assertNotIn(front, channel.knowledge_section_ids, '章節清單不含開始之前')
        howto = self._guide(front, 'howto')
        self.assertTrue(howto.is_published)
        self.assertEqual(howto.category_id, front.slide_id)
        self.assertLess(front.slide_id.sequence, self._section().slide_id.sequence,
                        '開始之前排在所有章節前面')
        self.assertIn('線上報名', howto.html_content, '列出各章')
        self.assertFalse(self._guide(front, 'setup'), '沒有探測資料就不放開始前必設定')

    def test_setup_page_from_probe_data(self):
        self.pkg.manual_setup_json = json.dumps({
            'items': [dict(guide_lib.SETUP_ITEMS[0], count=1, names=['新苗貿易'], menu='設定 › 公司',
                           ok=True),
                      dict(guide_lib.SETUP_ITEMS[2], count=0, names=[], menu='庫存 › 倉庫', ok=False)],
            'roles': [{'name': '業務', 'groups': ['銷售 / 管理員']}],
            'toggles': [{'path': '銷售 › 設定 › 報價範本', 'features': ['報價範本']}]},
            ensure_ascii=False)
        self._publish_three()
        front = self.env['corpaas.knowledge.channel_section'].search(
            [('channel_id', '=', self._channel().id), ('kind', '=', 'front')])
        setup = self._guide(front, 'setup')
        html = setup.html_content
        self.assertTrue(setup.is_published)
        for text in ('新苗貿易', '尚未設定', '沒有倉庫就無法收貨', '銷售 / 管理員', '報價範本',
                     'accordion-item', 'card-title'):
            self.assertIn(text, html)
        self.assertIn('fa-angle-right', html, '去哪裡設定用選單路徑樣式')
        howto = self._guide(front, 'howto')
        self.assertIn(setup.website_url, howto.html_content, '導讀連到開始前必設定')

    def test_status_page_after_articles(self):
        self._flow()
        self._publish_three()
        section = self._section()
        status = self._guide(section, 'status')
        self.assertTrue(status.is_published)
        self.assertEqual(status.name, '線上報名：狀態速查')
        self.assertIn('btn btn-sm btn-primary', status.html_content, '按鈕名稱用按鈕外觀')
        self.assertIn('accordion-button', status.html_content, '每個流程一個手風琴項目')
        arts = self.env['corpaas.knowledge.placement'].search(
            [('channel_id', '=', self._channel().id)]).mapped('slide_id')
        self.assertGreater(status.sequence, max(arts.mapped('sequence')), '狀態速查排在章末')
        self.assertFalse(self._guide(section, 'messages'), '沒有訊息就不放對照表')

    def test_messages_page_and_unchanged_not_rewritten(self):
        flow = self._flow()
        self.pkg.manual_messages_json = json.dumps([{
            'flow': flow.id, 'button': 'action_confirm', 'label': '確認', 'from': 'draft',
            'variant': 'empty', 'message': '請先加入至少一筆明細<b>', 'when': '在「草稿」狀態按「確認」',
            'cause': '單據沒有明細', 'fix': '回到單據加入明細後再確認'}], ensure_ascii=False)
        self._publish_three()
        msgs = self._guide(self._section(), 'messages')
        self.assertIn('請先加入至少一筆明細&lt;b&gt;', msgs.html_content, '訊息原文照樣、跳脫')
        self.assertIn('回到單據加入明細後再確認', msgs.html_content)
        stamp = msgs.date_published
        self._channel()._knowledge_renumber()
        self.assertEqual(msgs.date_published, stamp, '內容沒變不重設「新」標記')

    def test_probe_stores_data_and_skips_same_sandbox(self):
        flow = self._flow()
        sb = FakeSandbox(self.scenario)
        sb.base_sig, sb.seed_applied = 'b1', 's1'
        calls = []

        def shell(s, script):
            calls.append(script)
            if 'GROUPS' in script:
                return {'items': {'company': {'count': 1, 'names': ['新苗'], 'menu': '設定/公司'}},
                        'groups': {}}
            return [{'flow': flow.id, 'button': 'action_confirm', 'label': '確認', 'from': 'draft',
                     'variant': 'as_is', 'message': '缺少客戶'}]
        with patch.object(type(sb), '_shell', shell, create=True):
            self.assertTrue(self.hooks._manual_guide_probe(self.pkg, sb))
            self.assertFalse(self.hooks._manual_guide_probe(self.pkg, sb), '說明庫沒變不重跑')
        self.assertEqual(len(calls), 2)
        setup = json.loads(self.pkg.manual_setup_json)
        self.assertEqual(setup['items'][0]['menu'], '設定 › 公司')
        msgs = json.loads(self.pkg.manual_messages_json)
        self.assertEqual(msgs[0]['when'], '在「草稿」狀態按「確認」')

    def test_ai_fills_meanings_and_message_help(self):
        flow = self._flow()
        self.pkg.manual_messages_json = json.dumps(
            [{'flow': flow.id, 'message': '缺少客戶', 'when': '按「確認」'}], ensure_ascii=False)

        def ask(purpose, prompt, **kw):
            if purpose == 'manual_flow_meaning':
                return {'flows': [{'model': 'res.partner', 'steps': [
                    {'value': 'draft', 'meaning': '還沒確認的報名'},
                    {'value': 'done', 'meaning': '这是简体'}]}]}
            return {'items': [{'id': 0, 'cause': '報名沒有填客戶', 'fix': '回到報名填上客戶再確認'}]}
        with patch.object(type(self.Ai), 'ask', side_effect=ask):
            self.hooks._manual_guide_ai(self.pkg, 'tok', {'ai': False})
        steps = {s.value: s.meaning for s in flow.step_ids}
        self.assertEqual(steps['draft'], '還沒確認的報名')
        self.assertFalse(steps['done'], '簡體字的短文不用')
        self.assertEqual(json.loads(self.pkg.manual_messages_json)[0]['fix'], '回到報名填上客戶再確認')

    # ------------------------------------------------------------------
    def test_step_prompt_has_flow_and_finish(self):
        self._flow()
        ctx = self.hooks._manual_flow_context(self.f2)
        self.assertEqual(ctx[0]['按之後的狀態'], '完成')
        text = prompts.step_block_prompt({'name': '報名確認', 'key': 'k'}, [], [], [], flow_ctx=ctx)
        self.assertIn('完成後會看到', text)
        self.assertIn('開始前要先有', text)
        self.assertIn('按之前的狀態', text)
        screen = self.hooks._manual_flow_context(self.f1)
        self.assertEqual(screen[0]['狀態順序'], '草稿 → 完成', '入口畫面帶出狀態順序')

    def test_scenario_prompt_has_demo_values(self):
        seed = [{'xmlid': 'x.so_1', 'model': 'sale.order', 'values': {
                    'partner_id': '__ref__:x.cust', 'state': 'draft'}},
                {'xmlid': 'x.cust', 'model': 'res.partner', 'values': {'name': '宏達文具'}},
                {'xmlid': 'x.l1', 'model': 'sale.order.line', 'values': {
                    'order_id': '__ref__:x.so_1', 'product_uom_qty': 20, 'price_unit': 480}}]
        tmpl = self.env['corpaas.knowledge.shot_template'].sudo().create({
            'feature_id': self.f1.id, 'fingerprint': 'h1', 'login_role': 'admin',
            'steps_json': '[{"shot": "main"}]'})
        self.env['corpaas.knowledge.shot_binding'].sudo().create({
            'template_id': tmpl.id, 'scenario_id': self.scenario.id, 'state': 'ok',
            'bindings_json': json.dumps({'so': 'x.so_1'})})
        with patch.object(type(self.hooks), '_manual_seed', lambda s, sc: seed):
            demo = self.hooks._manual_demo_examples(self.scenario, self.f1)
            text = self.hooks._manual_scenario_prompt(self.pkg, self.scenario, self.f1,
                                                      self.cap_a, self.Block)
        self.assertEqual(demo[0]['values']['partner_id'], '宏達文具', '參照換成名稱')
        self.assertEqual(demo[0]['lines'][0]['price_unit'], 480, '帶出明細數字')
        self.assertIn('宏達文具', text)

    def test_article_shows_flow_position(self):
        self._flow()
        art = self._article(self.f2, self.cap_a, name='報名確認')
        html = art.render_html(preview=True)
        self.assertIn('o_kb_flowpos', html)
        self.assertIn('text-bg-primary">完成', html, '按完到達的狀態用實心徽章')
        self.assertIn('按「確認」', html)

    def test_redraft_review_rewrites_drafts(self):
        tmpl = self.env['corpaas.knowledge.shot_template'].sudo().create({
            'feature_id': self.f1.id, 'fingerprint': 'h1', 'login_role': 'admin',
            'steps_json': '[{"shot": "main"}]'})
        binding = self.env['corpaas.knowledge.shot_binding'].sudo().create({
            'template_id': tmpl.id, 'scenario_id': self.scenario.id, 'state': 'ok'})
        block = self._block(self.f1)
        block.knowledge_propose('new')
        art = self._article(self.f1, self.cap_a, block=block, shot_binding_id=binding.id)
        art.knowledge_propose('new')
        self.assertEqual(art.state, 'review')

        def ask(purpose, prompt, **kw):
            if purpose == 'manual_step_block':
                return {'title': '建立報名', 'steps': [
                    {'title': '開啟', 'html': '<p>開始前要先有：年會。</p>'},
                    {'title': '完成後會看到', 'html': '<p>報名變成草稿。</p>'}]}
            return {'title': '建立年會報名', 'html': '<p>會員宏達報名 2 人。</p>'}
        with patch.object(type(self.Ai), 'ask', side_effect=ask):
            nb, na = self.hooks._manual_redraft_review(self.pkg)
        self.assertEqual((nb, na), (1, 1))
        self.assertIn('完成後會看到', block.html)
        self.assertIn('宏達', art.scenario_html)
        self.assertEqual(art.state, 'review')


@tagged('post_install', '-at_install')
class TestTutorial(ManualCase):

    def setUp(self):
        super().setUp()
        self.f3.capability_ids = [(5,)]
        self.cap_b.feature_ids = [(5,)]
        self.cap_a.feature_ids = [(6, 0, (self.f1 | self.f2 | self.f3).ids)]
        Flow = self.env['corpaas.knowledge.flow'].sudo()
        self.flow = Flow.create({
            'model': 'res.partner', 'model_name': '報名單', 'state_field': 'kbt_state',
            'field_type': 'selection', 'capability_id': self.cap_a.id,
            'package_ids': [(4, self.pkg.id)], 'feature_ids': [(6, 0, (self.f1 | self.f2).ids)]})
        for i, (v, label) in enumerate([('draft', '草稿'), ('sent', '已送出'), ('done', '完成'),
                                        ('cancel', '取消')]):
            self.env['corpaas.knowledge.flow.step'].sudo().create({
                'flow_id': self.flow.id, 'sequence': i, 'value': v, 'label': label,
                'on_statusbar': v != 'cancel'})
        T = self.env['corpaas.knowledge.flow.transition'].sudo()
        for fr, to, name, label, opens in [('draft', 'sent', 'action_submit', '送出', False),
                                           ('draft', 'done', 'action_skip', '直接完成', False),
                                           ('sent', 'done', 'action_wizard', '精靈', 'x.wizard'),
                                           ('sent', 'done', 'action_done', '完成', False),
                                           ('done', 'draft', 'action_draft', '重設', False)]:
            T.create({'flow_id': self.flow.id, 'from_value': fr, 'to_value': to,
                      'button_name': name, 'button_label': label, 'opens_model': opens,
                      'button_feature_id': self.f2.id if name == 'action_done' else False})
        self.Tutorial = self.env['corpaas.knowledge.tutorial'].sudo()

    def test_path_follows_statusbar_without_wizards(self):
        path = self.Tutorial._path(self.flow)
        self.assertEqual([(t.button_name, a, b) for t, a, b in path],
                         [('action_submit', 'draft', 'sent'), ('action_done', 'sent', 'done')],
                         '一步一格往下走；開精靈的、往回的不走')

    def test_path_assumes_next_state_and_skips_recorded_later(self):
        T = self.env['corpaas.knowledge.flow.transition'].sudo()
        self.flow.transition_ids.unlink()
        # 草稿沒記到按鈕；「確認」只記了從「已送出」起（實際上草稿也看得到）；「核實」終點不明
        T.create({'flow_id': self.flow.id, 'from_value': 'sent', 'to_value': 'done',
                  'button_name': 'action_confirm', 'button_label': '確認'})
        T.create({'flow_id': self.flow.id, 'from_value': 'draft', 'to_value': 'sent',
                  'button_name': 'print_quotation', 'button_label': '列印'})
        path = self.Tutorial._path(self.flow)
        self.assertEqual([(t.button_name, a, b) for t, a, b in path],
                         [('action_confirm', 'draft', 'done')], '列印不走；下一格才記到的當成現在按得到')
        self.flow.transition_ids.unlink()
        T.create({'flow_id': self.flow.id, 'from_value': 'draft', 'to_value': False,
                  'button_name': 'button_validate', 'button_label': '核實'})
        path = self.Tutorial._path(self.flow)
        self.assertEqual([(a, b) for _t, a, b in path], [('draft', 'sent')], '終點不明先假設下一格')

    def test_pick_record_prefers_first_state_with_lines(self):
        seed = [{'xmlid': 'x.r1', 'model': 'res.partner', 'values': {'kbt_state': 'done'}},
                {'xmlid': 'x.r2', 'model': 'res.partner', 'values': {'name': '甲'}},
                {'xmlid': 'x.r3', 'model': 'res.partner', 'values': {'name': '乙', 'kbt_state': 'draft'}},
                {'xmlid': 'x.l', 'model': 'res.partner.line', 'values': {'p': '__ref__:x.r3'}}]
        self.assertEqual(self.Tutorial._pick_record(self.flow, seed, 'draft')['xmlid'], 'x.r3')

    def test_shoot_and_publish_tutorial(self):
        from odoo.addons.dobtor_corpaas_knowledge.services import shooter
        seed = [{'xmlid': 'x.r3', 'model': 'res.partner', 'values': {'name': '宏達報名', 'kbt_state': 'draft'}}]
        sb = FakeSandbox(self.scenario)
        sb.dirty = False
        jobs_seen = []

        def run(env, sandbox, jobs, settings):
            from .common import png
            jobs_seen.extend(jobs)
            out, files = {}, {}
            for j in jobs:
                names = [st['shot'] for st in j['steps'] if 'shot' in st]
                out[j['id']] = {'ok': True, 'images': [
                    {'name': n, 'file': '%s/%s.png' % (j['id'], n), 'regions': []} for n in names],
                    'transitions': [{'button': 'action_done', 'from': 'sent', 'to': 'done'}]}
                for n in names:
                    files['%s/%s.png' % (j['id'], n)] = png()
            return {'shots': out}, files
        with patch.object(type(self.hooks), '_manual_seed', lambda s, sc: seed), \
                patch.object(shooter, 'run_shots', run), \
                patch.object(type(self.hooks), '_manual_wizard_confirms', lambda s, sb_, m: {}), \
                patch.object(type(self.hooks), '_manual_tutorial_copies',
                             lambda s, sb_, r: {x: [m, 99] for x, (m, _i) in r.items()}), \
                patch.object(type(self.env['res.config.settings']), 'knowledge_shot_settings',
                             lambda s: {}, create=True):
            n = self.hooks._manual_shoot_tutorials(self.pkg, sb)
            again = self.hooks._manual_shoot_tutorials(self.pkg, sb)
        self.assertEqual((n, again), (1, 0), '輸入沒變不重拍')
        self.assertEqual(len(jobs_seen), 1, '整條教學一個拍攝工作（同一個瀏覽器一路點下去）')
        clicks = [st['click']['button'] for st in jobs_seen[0]['steps'] if 'click' in st]
        opens = [st['open']['res_id'] for st in jobs_seen[0]['steps'] if 'open' in st]
        self.assertEqual(set(opens), {99}, '教學用複本，不用一般截圖可能按過的原單據')
        self.assertEqual(clicks, ['action_submit', 'action_done'])
        self.assertTrue(all(st.get('optional') for st in jobs_seen[0]['steps'] if 'click' in st),
                        '每一步都是選用：按鈕沒出現就略過那一組')
        self.assertTrue(sb.dirty, '按過按鈕：說明庫要重建')
        tut = self.Tutorial.search([('flow_id', '=', self.flow.id)])
        self.assertEqual((tut.state, len(tut.steps()), tut.record_label), ('ok', 2, '宏達報名'))
        arts = [self._article(f, self.cap_a, name=nm) for f, nm in
                ((self.f1, '甲'), (self.f2, '乙 完成報名'), (self.f3, '丙'))]
        self._publish(*arts)
        section = self._channel().knowledge_section_ids.filtered(
            lambda s: s.capability_id == self.cap_a)
        slide = section.guide_slide_ids.filtered(lambda g: g.kind == 'tutorial').slide_id
        self.assertTrue(slide.is_published)
        self.assertEqual(slide.name, '線上報名：情境教學')
        html = slide.html_content
        self.assertIn('報名單：已送出 → 完成', html)
        self.assertIn('狀態列變成', html)
        self.assertIn('col-md-6', html, '按之前／按之後並排')
        self.assertIn('乙 完成報名', html, '連到那一步的參考篇')
        art_seqs = self.env['corpaas.knowledge.placement'].search(
            [('channel_id', '=', self._channel().id)]).mapped('slide_id.sequence')
        self.assertLess(slide.sequence, min(art_seqs), '教學排在參考篇之前')

    def test_plan_follows_handoff_to_downstream(self):
        Flow = self.env['corpaas.knowledge.flow'].sudo()
        pick = Flow.create({'model': 'stock.picking', 'model_name': '調撥', 'state_field': 'state',
                            'field_type': 'selection', 'package_ids': [(4, self.pkg.id)]})
        for i, v in enumerate(['draft', 'assigned', 'done']):
            self.env['corpaas.knowledge.flow.step'].sudo().create(
                {'flow_id': pick.id, 'sequence': i, 'value': v, 'label': v, 'on_statusbar': True})
        T = self.env['corpaas.knowledge.flow.transition'].sudo()
        T.create({'flow_id': pick.id, 'from_value': 'assigned', 'to_value': 'done',
                  'button_name': 'button_validate', 'button_label': '驗證'})
        self.flow.model = 'sale.order'
        T.create({'flow_id': self.flow.id, 'from_value': 'done', 'button_name': 'action_view_delivery',
                  'button_label': '交貨', 'opens_flow_id': pick.id})
        plan = self.hooks._manual_tutorial_plan(self.flow, self.pkg)
        kinds = [(p['kind'], p['button']) for p in plan]
        self.assertIn(('open', 'action_view_delivery'), kinds, '沿交接打開下游單據')
        self.assertEqual(plan[-1]['button'], 'button_validate')
        self.assertEqual(plan[-1]['req'], [kinds.index(('open', 'action_view_delivery'))],
                         '下游的步驟要先打開下游單據成功')
        auth = {self.flow.id: ('doc_sales', 'pw'), pick.id: ('doc_stock', 'pw')}
        steps = self.hooks._manual_tutorial_steps(plan, 'sale.order', 7, {}, auth)
        core = lambda st: {k: v for k, v in st.items() if k not in ('optional', 'grp', 'req')}  # noqa: E731
        self.assertEqual(core(steps[0]), {'login': {'user': 'doc_sales', 'password': 'pw'}},
                         '每一組先用那張單據的負責角色登入')
        self.assertEqual(core(steps[1]), {'open': {'model': 'sale.order', 'res_id': 7}})
        opened = kinds.index(('open', 'action_view_delivery'))
        self.assertIn({'remember': 'g%s' % opened},
                      [core(st) for st in steps if st.get('grp') == 's%s' % opened])
        last = [core(st) for st in steps if st.get('grp') == 's%s' % (len(plan) - 1)]
        self.assertEqual(last[0], {'login': {'user': 'doc_stock', 'password': 'pw'}}, '換倉管')
        self.assertEqual(last[1], {'recall': 'g%s' % opened}, '回到剛才打開的出貨單')


@tagged('post_install', '-at_install')
class TestHandoff(ManualCase):

    def test_upstream_view_button_is_not_handoff(self):
        Flow = self.env['corpaas.knowledge.flow'].sudo()
        po = Flow.create({'model': 'purchase.order', 'model_name': '採購單', 'state_field': 'state',
                          'field_type': 'selection', 'package_ids': [(4, self.pkg.id)]})
        so = Flow.create({'model': 'sale.order', 'model_name': '銷售單', 'state_field': 'state',
                          'field_type': 'selection', 'package_ids': [(4, self.pkg.id)]})
        T = self.env['corpaas.knowledge.flow.transition'].sudo()
        back = T.create({'flow_id': po.id, 'button_name': 'action_view_sale_orders',
                         'button_label': '銷售', 'opens_flow_id': so.id})
        fwd = T.create({'flow_id': so.id, 'button_name': 'action_view_purchase_orders',
                        'button_label': '494', 'opens_flow_id': po.id,
                        'button_feature_id': self.f3.id})
        self.assertFalse(back.is_handoff(), '採購單回頭看銷售單是查看關聯')
        self.assertTrue(fwd.is_handoff())
        self.assertEqual(fwd.display_label(), self.f3.name, '只有編號的按鈕名稱改用功能點名稱')
        self.f2.write({'model': 'purchase.order'})
        back.button_feature_id = self.f2.id
        self.assertFalse(self.hooks._manual_flow_context(self.f2), '查看上游的按鈕不寫成流程上的一步')
        self.f1.write({'model': 'purchase.order'})
        self.assertNotIn('後續單據', str(self.hooks._manual_flow_context(self.f1)))


@tagged('post_install', '-at_install')
class TestRound2(ManualCase):
    """第二輪比較的修正：歸屬看模組、章節排序、狀態速查、章內分組、角色對章節、文字檢查、觀念頁。"""

    def test_shared_feature_goes_to_module_capability(self):
        # f1 同時在 A、B；B 的功能點多數跟 f1 同模組 → 歸 B
        self.cap_b.feature_ids = [(4, self.f1.id)]
        self.f3.module = 'kbtest'
        self.f2.module = 'other'
        cands = self.hooks._manual_candidates(self.pkg)
        self.assertEqual(cands[self.f1], self.cap_b)

    def test_tidy_orders_capabilities_and_moves_flows(self):
        Cap = self.env['corpaas.knowledge.capability'].sudo()
        self.cap_a.sequence = self.cap_b.sequence = 10
        sale = self.Feature.create({'feature_key': 'kbtest.action:so', 'module': 'sale', 'kind': 'action',
                                    'anchor': 'kbtest.so', 'name': '訂單', 'model': 'sale.order',
                                    'package_ids': [(6, 0, self.pkg.ids)]})
        stock = self.Feature.create({'feature_key': 'kbtest.action:pk', 'module': 'stock',
                                     'kind': 'action', 'anchor': 'kbtest.pk', 'name': '調撥',
                                     'model': 'stock.picking', 'package_ids': [(6, 0, self.pkg.ids)]})
        self.cap_a.feature_ids = [(6, 0, stock.ids)]
        self.cap_b.feature_ids = [(6, 0, (sale | stock).ids)]
        flow = self.env['corpaas.knowledge.flow'].sudo().create({
            'model': 'sale.order', 'state_field': 'state', 'capability_id': self.cap_a.id,
            'package_ids': [(4, self.pkg.id)], 'feature_ids': [(6, 0, sale.ids)]})
        stats = self.pkg._knowledge_tidy_capabilities()
        self.assertEqual(flow.capability_id, self.cap_b, '銷售訂單流程歸到有 sale 模組的能力')
        self.assertEqual(stats['caps_ordered'], 2)
        self.assertLess(self.cap_b.sequence, self.cap_a.sequence, '主要模組 sale 排在 stock 前面')
        self.cap_a.sequence = 99
        self.assertFalse(self.pkg._knowledge_tidy_capabilities()['caps_ordered'], '有人排過就不動')

    def test_status_excludes_print_and_splits_cancel(self):
        flow = self.env['corpaas.knowledge.flow'].sudo().create({
            'model': 'res.partner', 'model_name': '調撥', 'state_field': 'kbr_state',
            'field_type': 'selection', 'capability_id': self.cap_a.id,
            'package_ids': [(4, self.pkg.id)]})
        for i, (v, label) in enumerate([('draft', '草稿'), ('ready', '準備好'), ('done', '完成'),
                                        ('cancel', '已取消')]):
            self.env['corpaas.knowledge.flow.step'].sudo().create({
                'flow_id': flow.id, 'sequence': i, 'value': v, 'label': label,
                'on_statusbar': v != 'cancel'})
        T = self.env['corpaas.knowledge.flow.transition'].sudo()
        for fr, to, name, label in [('ready', 'done', 'button_validate', '驗證'),
                                    ('ready', 'cancel', 'do_print_picking', '列印'),
                                    ('ready', 'cancel', 'action_cancel', '取消'),
                                    ('draft', 'ready', 'action_confirm', 'action_confirm')]:
            T.create({'flow_id': flow.id, 'from_value': fr, 'to_value': to, 'button_name': name,
                      'button_label': label})
        data = self.env['corpaas.knowledge.channel_section']._manual_status_data(flow, self.pkg)
        rows = {r['label']: r for r in data[0]['steps']}
        self.assertEqual(rows['準備好']['next'], ['按「驗證」→ 完成'])
        self.assertEqual(rows['準備好']['back'], ['按「取消」→ 已取消'], '列印不列；取消另一欄')
        self.assertFalse(rows['草稿']['next'], '方法名稱不是給人看的按鈕名稱')
        html = guide_lib.render_status(data)
        self.assertIn('取消或退回', html)

    def test_config_articles_after_daily(self):
        from ..models.placement import article_group
        self.f1.menu_path = '報名/配置/年會類型'
        self.f2.menu_path = '報名/報告/分析'
        self.assertEqual([article_group(f) for f in (self.f1, self.f2, self.f3)], [2, 1, 0])
        self.f3.capability_ids = [(5,)]
        self.cap_b.feature_ids = [(5,)]
        self.cap_a.feature_ids = [(6, 0, (self.f1 | self.f2 | self.f3).ids)]
        arts = [self._article(f, self.cap_a, name=n) for f, n in
                ((self.f1, '甲 設定'), (self.f2, '乙 報表'), (self.f3, '丙 日常'))]
        self._publish(*arts)
        seq = {a.name: a.placement_ids.slide_id.sequence for a in arts}
        self.assertLess(seq['丙 日常'], seq['乙 報表'])
        self.assertLess(seq['乙 報表'], seq['甲 設定'])
        journey = self._channel().knowledge_section_ids.filtered(
            lambda s: s.capability_id == self.cap_a).journey_slide_id
        self.assertIn('設定（通常只在導入時做一次）', journey.html_content)

    def test_lint_flags_demo_name_and_prerequisite(self):
        art = self._article(self.f1, self.cap_a, name='核對宏達文具發票')
        art.step_block_ids.html = '<p>開始前要先有：至少一筆範本，才能在列表中看到範例。</p>'
        with patch.object(type(self.hooks), '_manual_seed', lambda s, sc: [
                {'xmlid': 'x.p', 'model': 'res.partner', 'values': {'name': '宏達文具'}}]):
            problems = art._manual_text_problems()
        self.assertTrue(any('示範資料名稱' in p for p in problems))
        self.assertTrue(any('開始前要先有' in p for p in problems))

    def test_concept_drafted_reviewed_then_shown(self):
        self.f3.capability_ids = [(5,)]
        self.cap_b.feature_ids = [(5,)]
        self.cap_a.feature_ids = [(6, 0, (self.f1 | self.f2 | self.f3).ids)]
        flow = self.env['corpaas.knowledge.flow'].sudo().create({
            'model': 'res.partner', 'model_name': '報名', 'state_field': 'kbc_state',
            'field_type': 'selection', 'capability_id': self.cap_a.id,
            'package_ids': [(4, self.pkg.id)]})
        for i, v in enumerate(['draft', 'done']):
            self.env['corpaas.knowledge.flow.step'].sudo().create(
                {'flow_id': flow.id, 'sequence': i, 'value': v, 'label': v, 'on_statusbar': True})
        self.cap_a._do_publish('new')
        html = '<p>報名從草稿到完成，' + '說明' * 60 + '</p>'
        with patch.object(type(self.env['corpaas.knowledge.ai']), 'ask', return_value={'html': html}):
            self.assertEqual(self.hooks._manual_draft_concepts(self.pkg, 'tok', {'ai': False}), 1)
        self.assertEqual(self.cap_a.state, 'review')
        arts = [self._article(f, self.cap_a, name=n) for f, n in
                ((self.f1, '甲'), (self.f2, '乙'), (self.f3, '丙'))]
        self._publish(*arts)
        section = self._channel().knowledge_section_ids.filtered(lambda s: s.capability_id == self.cap_a)
        self.assertFalse(section.guide_slide_ids.filtered(lambda g: g.kind == 'concept').slide_id,
                         '沒核准不出現')
        self.cap_a._do_publish('text')
        self._channel()._knowledge_renumber()
        slide = section.guide_slide_ids.filtered(lambda g: g.kind == 'concept').slide_id
        self.assertTrue(slide.is_published)
        self.assertEqual(slide.name, '線上報名：先懂這幾個觀念')
        self.assertLess(slide.sequence, min(a.placement_ids.slide_id.sequence for a in arts))


@tagged('post_install', '-at_install')
class TestRound3(ManualCase):

    def test_published_placement_follows_new_capability(self):
        art = self._article(self.f1, self.cap_a, name='甲')
        self._publish(art)
        pl = art.placement_ids
        self.assertEqual(pl.capability_id, self.cap_a)
        self.cap_a.feature_ids = [(3, self.f1.id)]
        self.cap_b.feature_ids = [(4, self.f1.id)]
        self.assertEqual(self.hooks._manual_realign_chapters(self.pkg), 1)
        self.assertEqual(pl.capability_id, self.cap_b)

    def test_pick_record_skips_moved_by_call(self):
        flow = self.env['corpaas.knowledge.flow'].sudo().create(
            {'model': 'res.partner', 'state_field': 'kbm_state'})
        seed = [{'xmlid': 'x.so_1', 'model': 'res.partner', 'values': {}},
                {'xmlid': 'x.so_1_confirm', 'model': 'res.partner', 'call': 'action_confirm',
                 'ref': 'x.so_1'},
                {'xmlid': 'x.so_2', 'model': 'res.partner', 'values': {}}]
        rec = self.env['corpaas.knowledge.tutorial']._pick_record(flow, seed, 'draft')
        self.assertEqual(rec['xmlid'], 'x.so_2', '被動作記錄推過的不挑')

    def test_status_middle_state_not_marked_end_and_lists_unknown_buttons(self):
        rows = [{'label': '報價', 'meaning': '', 'next': [], 'back': [], 'roles': []},
                {'label': '完成', 'meaning': '', 'next': [], 'back': [], 'roles': []}]
        html = guide_lib.render_status([{'name': 'f', 'steps': rows}])
        self.assertEqual(html.count('流程終點'), 1, '只有最後一個狀態是終點')

    def test_full_width_punctuation(self):
        from ..models.concept import full_width
        self.assertEqual(full_width('<p>報價單,寄給客戶;等回覆</p>'), '<p>報價單，寄給客戶；等回覆</p>')
        self.assertEqual(full_width('<p>v1,2 and a,b</p>'), '<p>v1,2 and a,b</p>')


@tagged('post_install', '-at_install')
class TestObserved(ManualCase):

    def test_probe_observations_fill_unknown_ends_and_filter_unrealistic(self):
        Flow = self.env['corpaas.knowledge.flow'].sudo()
        flow = Flow.create({'model': 'res.partner', 'model_name': '調撥', 'state_field': 'kbo_state',
                            'field_type': 'selection', 'package_ids': [(4, self.pkg.id)],
                            'capability_id': self.cap_a.id})
        for i, v in enumerate(['draft', 'assigned', 'done']):
            self.env['corpaas.knowledge.flow.step'].sudo().create(
                {'flow_id': flow.id, 'sequence': i, 'value': v, 'label': v, 'on_statusbar': True})
        T = self.env['corpaas.knowledge.flow.transition'].sudo()
        blank = T.create({'flow_id': flow.id, 'from_value': 'assigned', 'button_name': 'button_validate',
                          'button_label': '核實', 'ev_static': True})
        sb = FakeSandbox(self.scenario)
        sb.base_sig, sb.seed_applied = 'b', 's'

        def shell(s, script):
            if 'GROUPS' in script:
                return {'items': {}, 'groups': {}}
            self.assertIn('"first": "draft"', script, '帶流程第一個狀態：清空明細只在草稿試')
            return {'messages': [{'flow': flow.id, 'button': 'button_validate', 'label': '核實',
                                  'from': 'assigned', 'variant': 'as_is', 'message': '刪不掉稅金'}],
                    'observed': [{'flow': flow.id, 'model': 'res.partner', 'button': 'button_validate',
                                  'from': 'assigned', 'to': 'done'}]}
        with patch.object(type(sb), '_shell', shell, create=True):
            self.hooks._manual_guide_probe(self.pkg, sb)
        got = flow.transition_ids.filtered(lambda t: t.to_value == 'done')
        self.assertEqual((got.button_label, got.ev_shot), ('核實', True), '實測終點另建一筆、沿用名稱')
        self.assertTrue(blank.exists(), '靜態那筆不動（結構雜湊只看靜態）')
        self.assertNotIn(blank, flow.effective_transitions(), '說明用的轉換改用實測那筆')
        with patch.object(type(self.env['corpaas.knowledge.ai']), 'ask', side_effect=lambda p, q, **k:
                          {'items': [{'id': 0, 'cause': '已過帳的稅金明細不能刪', 'fix': '改開貸記單沖銷',
                                      'realistic': False}]} if p == 'manual_message_help' else {}):
            self.hooks._manual_guide_ai(self.pkg, 'tok', {'ai': False})
        data = self.env['corpaas.knowledge.channel_section']._manual_messages_data(flow, self.pkg)
        self.assertFalse(data, '一般操作遇不到的訊息不列')


@tagged('post_install', '-at_install')
class TestLibraryAcceptance(ManualCase):

    def test_save_and_restore_library_after_wipe(self):
        self.cap_a._do_publish('new')
        self.cap_b._do_publish('new')
        self.scenario.seed_json = json.dumps([{'xmlid': 'p', 'model': 'res.partner',
                                               'values': {'name': '甲'}}])
        self.scenario._do_publish('new')
        flow = self.env['corpaas.knowledge.flow'].sudo().create({
            'model': 'res.partner', 'state_field': 'kbl_state', 'ai_name': '報名流程',
            'capability_id': self.cap_a.id, 'package_ids': [(4, self.pkg.id)]})
        self.env['corpaas.knowledge.flow.step'].sudo().create(
            {'flow_id': flow.id, 'sequence': 0, 'value': 'draft', 'label': '草稿',
             'on_statusbar': True, 'meaning': '還沒送出'})
        self.env['corpaas.knowledge.flow.transition'].sudo().create(
            {'flow_id': flow.id, 'from_value': 'draft', 'to_value': 'done',
             'button_name': 'action_done', 'button_label': '完成', 'ev_shot': True})
        self.assertEqual(self.pkg._knowledge_save_library(note='t'), 3)
        # 清除：能力、情境、流程名稱與實測轉換都拿掉
        codes = {self.cap_a.code: self.cap_a.name, self.cap_b.code: self.cap_b.name}
        (self.cap_a | self.cap_b).unlink()
        sc_code = self.scenario.code
        self.scenario.unlink()
        flow.write({'ai_name': False, 'capability_id': False})
        flow.transition_ids.unlink()
        flow.step_ids.meaning = False
        stats = self.pkg._knowledge_restore_library()
        self.assertEqual(stats, {'library_caps': 2, 'library_scenarios': 1})
        caps = self.pkg.knowledge_capability_ids
        self.assertEqual({c.code: c.name for c in caps}, codes, '能力名稱照範本，不重新叫 AI')
        self.assertTrue(all(c.state == 'published' for c in caps), '範本是核准過的：直接上線')
        cap_a = caps.filtered(lambda c: c.code == 'kb_reg')
        self.assertEqual(cap_a.feature_ids, self.f1 | self.f2, '功能點照功能鍵掛回去')
        sc = self.pkg.knowledge_scenario_ids
        self.assertEqual((sc.code, sc.state), (sc_code, 'published'))
        self.assertEqual(self.pkg._knowledge_restore_flows(), 1)
        self.assertEqual((flow.ai_name, flow.capability_id), ('報名流程', cap_a))
        self.assertEqual(flow.named_hash, flow.structure_hash, '記成已命名：不再請 AI 命名')
        self.assertEqual(flow.step_ids.meaning, '還沒送出')
        self.assertTrue(flow.transition_ids.filtered(lambda t: t.ev_shot and t.to_value == 'done'))
        self.assertFalse(self.pkg._knowledge_restore_library(), '已經有能力／情境就不再套用')

    def test_acceptance_report(self):
        self.f3.capability_ids = [(5,)]
        self.cap_b.feature_ids = [(5,)]
        self.cap_a.feature_ids = [(6, 0, (self.f1 | self.f2 | self.f3).ids)]
        arts = [self._article(f, self.cap_a, name=n) for f, n in
                ((self.f1, '甲'), (self.f2, '乙'), (self.f3, '丙'))]
        self._publish(*arts)
        with patch.object(type(self.pkg), '_knowledge_save_library', lambda s, note=None: 0):
            checks = {c['key']: c for c in self.hooks._manual_acceptance(self.pkg)}
        self.assertEqual(checks['articles']['value'], '3／4（75%）', '共通操作的 f4 還沒有文章')
        self.assertFalse(checks['articles']['ok'], '低於 90%')
        self.assertTrue(checks['text_lint']['ok'])
        self.assertFalse(checks['front']['ok'], '沒有開始前必設定資料：前置頁不完整')
        self.assertFalse(self.pkg.manual_acceptance_ok)
        self.assertIn('❌', self.pkg.manual_acceptance_html)

    def test_wizard_confirm_is_its_own_group(self):
        plan = [{'kind': 'press', 'flow': 1, 'button': 'button_confirm', 'label': '確認',
                 'from': 'draft', 'to': 'purchase', 'wizard': 'x.wizard'}]
        steps = self.hooks._manual_tutorial_steps(plan, 'purchase.order', 3, {'x.wizard': 'action_ok'})
        wiz = [st for st in steps if st.get('click') == {'button': 'action_ok'}][0]
        self.assertEqual((wiz['grp'], wiz['req']), ('s0w', ['s0']),
                         '精靈沒跳出來不影響這一步')


@tagged('post_install', '-at_install')
class TestLayout(ManualCase):

    def test_split_and_inline(self):
        from ..services import layout_lib as L
        out = L.lead_intro('<p>業務建立報價單,送出後待客戶確認;客戶同意就轉成訂單。例如報價 20 箱。'
                           '此行為由設定「自動開票」決定。請依下方步驟操作。</p>')
        self.assertTrue(out.startswith('<p class="lead">業務建立報價單，送出後待客戶確認；'),
                        '第一句導言、半形標點轉全形')
        self.assertIn('<blockquote', out, '例子成引用塊')
        self.assertIn('fa-cog', out, '設定影響成灰色備註')
        steps = L.split_paragraphs('<p>前往「銷售 / 訂單」，按「新增」後可設定客戶（圖中 1）、'
                                   '發票地址（圖中 2）、送貨地址（圖中 3）等欄位。</p>')
        self.assertIn('btn btn-sm btn-primary', steps, '按「新增」→ 按鈕外觀')
        self.assertIn('fa-angle-right', steps, '選單路徑')
        self.assertIn('<li>客戶（圖中 1）</li>', steps, '三個以上（圖中 n）改條列')

    def test_steps_layout_boxes(self):
        from ..services import layout_lib as L
        html = ('<h4 id="a-1"><span class="badge text-bg-primary">1</span> 開啟</h4>'
                '<p>開始前要先有：客戶資料。點選清單。</p>'
                '<h4 id="a-2"><span class="badge text-bg-primary">2</span> 完成後會看到</h4>'
                '<p>狀態變成銷售訂單。</p>')
        out, outline = L.steps_layout([('a', '操作步驟', html)])
        self.assertIn('alert-warning', out)
        self.assertIn('alert-success', out)
        self.assertIn('id="a"', out, '區塊錨點保留（help 連結用）')
        self.assertIn('id="a-1"', out)
        self.assertEqual([t for _i, t in outline], ['開啟'], '完成後會看到不算一步')
        self.assertLess(out.index('alert-warning'), out.index('o_kb_step'))

    def test_components_survive_slide_sanitize(self):
        """手風琴、頁籤、按鈕外觀、figure 寫進 slide 後讀回不變（前台互動靠 data-bs-*）。"""
        from ..services import layout_lib as L
        html = L.page(L.accordion('kbt', [('<span>標題</span>', '<p>內容</p>')], open_first=True)
                      + L.tabs('kbtab', [('甲', '<p>一</p>'), ('乙', '<p>二</p>')])
                      + '<p>按%s</p>' % L.button('確認')
                      + L.figure('<img src="/web/image/1" class="img-fluid rounded border" alt="x"/>',
                                 '圖說'))
        channel = self.env['slide.channel'].create({'name': 'kb layout test'})
        slide = self.env['slide.slide'].create({
            'name': 'layout', 'channel_id': channel.id, 'slide_category': 'article',
            'html_content': html})
        got = str(slide.html_content)
        for marker in ('data-bs-toggle="collapse"', 'data-bs-target="#kbt-0"', 'accordion-button',
                       'data-bs-toggle="tab"', 'tab-pane', 'btn btn-sm btn-primary', '<figure',
                       '<figcaption', 'max-width:52rem'):
            self.assertIn(marker, got, marker)


@tagged('post_install', '-at_install')
class TestRedraftCommits(ManualCase):

    def test_redraft_jobs_commit_per_item(self):
        Pkg = type(self.pkg)
        for name in ('_manual_redraft_review_run', '_manual_redraft_lint_run',
                     '_manual_redraft_handoff_run'):
            self.assertTrue(getattr(getattr(Pkg, name), 'knowledge_commits', False), name)
        job = self.env['corpaas.knowledge.ai.job'].sudo().create({
            'res_model': self.pkg._name, 'res_id': self.pkg.id,
            'method': '_manual_redraft_lint_run', 'package_id': self.pkg.id})
        with patch.object(type(self.hooks), '_manual_redraft_review', lambda s, *a, **k: (0, 0)):
            job._run()
        self.assertEqual(job.state, 'done', '逐筆提交的工作不包 savepoint 也照常完成')
