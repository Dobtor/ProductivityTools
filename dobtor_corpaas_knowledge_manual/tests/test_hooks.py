# -*- coding: utf-8 -*-
import json
from unittest.mock import patch

from odoo.tests.common import new_test_user, tagged

from odoo.addons.dobtor_corpaas_knowledge.services import hub_client

from .common import ManualCase, png

_RUN_SHOTS = 'odoo.addons.dobtor_corpaas_knowledge.services.shooter.run_shots'


class FakeSandbox:
    """_knowledge_shoot 只用到這幾個屬性；不接 SSH／docker。"""

    def __init__(self, scenario, known=None):
        self.scenario_id = scenario
        self.role_logins = json.dumps({'admin': 'doc_admin'})
        self.password = 'pw'
        self.db_name = 'docsbx-test'
        self.master_instance_id = None
        self.bad = []
        self.known = known

    def sudo(self):
        return self

    def resolve_xmlids(self, xmlids):
        return {x: ['res.partner', 7] for x in xmlids
                if self.known is None or x in self.known}

    def gate_bad_records(self, pairs, refs=None):
        return self.bad


@tagged('post_install', '-at_install')
class TestManualHooks(ManualCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Ai = type(cls.env['corpaas.knowledge.ai'])
        cls.Event = cls.env['corpaas.knowledge.event'].sudo()
        cls.Template = cls.env['corpaas.knowledge.shot_template'].sudo()
        cls.Binding = cls.env['corpaas.knowledge.shot_binding'].sudo()
        # 方案目前 f1 的指紋是 h2；範本就是 h2 這一份
        cls._fp(cls.f1, 'h2')
        cls.tmpl1 = cls.Template.create({
            'feature_id': cls.f1.id, 'login_role': 'admin', 'fingerprint': 'h2',
            'steps_json': json.dumps([{'open': '{rec}'},
                                      {'highlight': {'field': 'name', 'n': 1}},
                                      {'shot': 'main'}])})
        cls.binding = cls.Binding.create({
            'template_id': cls.tmpl1.id, 'scenario_id': cls.scenario.id,
            'bindings_json': json.dumps({'rec': '__doc_scenario_kbtest_assoc.p1'})})

    def _only_f1(self):
        """只留 f1 當候選（其他功能沒有範本會一直要求重建說明庫）。"""
        self.cap_a.feature_ids = [(6, 0, self.f1.ids)]
        self.cap_b.feature_ids = [(5,)]
        self.env['corpaas.knowledge.selection'].sudo().search(
            [('package_id', '=', self.pkg.id)]).unlink()

    def _event(self, etype, feature=None, pkg=None, **kw):
        return self.Event.create(dict({'type': etype, 'package_id': (pkg or self.pkg).id,
                                       'feature_id': feature.id if feature else False,
                                       'refresh_token': 'tok'}, **kw))

    def _dispatch(self, events=None, pkg=None, token='tok'):
        return self.hooks._knowledge_dispatch_events(
            pkg or self.pkg, events if events is not None else self.Event.browse(),
            {'token': token})

    def _mine(self, ask):
        # ★ 只數本模組的呼叫：同庫裝了行銷出口時，它也會對事件起草內容
        return [c for c in ask.call_args_list if c[0][0].startswith('manual_')]

    # ------------------------------------------------------------------
    # 範圍、要拍哪些情境
    # ------------------------------------------------------------------
    def test_elements_and_scenarios_needing_shots(self):
        self.assertEqual(self.hooks._knowledge_elements_for(self.f1, self.pkg),
                         [{'field': 'name'}])
        self._only_f1()
        needing = self.hooks._knowledge_scenarios_needing_shots(self.pkg, self.Event.browse())
        self.assertIn(self.scenario, needing, '待拍的繫結要拍')

    def test_failed_binding_repaired_without_rebuild(self):
        """佔位符對不到 → 列入 AI 修補；失敗等修的繫結不逼每次重建說明庫。"""
        self._only_f1()
        sandbox = FakeSandbox(self.scenario, known=set())
        with patch.object(self.Ai, 'ask', side_effect=hub_client.BudgetExceeded('over')), \
                patch(_RUN_SHOTS) as run:
            ctx = {'token': 'tok', 'full': False}
            self.hooks._knowledge_shoot(self.pkg, sandbox, self.Event.browse(), ctx)
        run.assert_not_called()
        self.assertEqual(self.binding.state, 'failed')
        self.assertTrue(self.binding.needs_repair)
        self.assertIn('找不到示範資料', self.binding.last_error)
        self.assertNotIn(self.scenario, self.hooks._knowledge_scenarios_needing_shots(
            self.pkg, self.Event.browse()), '等修的繫結不重建說明庫')
        fixed = {'bindings': {'rec': 'base.main_partner'}, 'reason': 'x'}
        with patch.object(self.Ai, 'ask', return_value=fixed) as ask:
            self._dispatch()
        self.assertEqual(self._mine(ask)[0][0][0], 'manual_repair')
        self.assertEqual(self.binding.state, 'pending')
        self.assertEqual(self.binding.bindings(), {'rec': 'base.main_partner'})
        self.assertEqual(self.binding.repair_attempts, 1)
        self.assertIn(self.scenario, self.hooks._knowledge_scenarios_needing_shots(
            self.pkg, self.Event.browse()), '修好了才重建重拍')

    # ------------------------------------------------------------------
    # 拍攝
    # ------------------------------------------------------------------
    def _shoot(self, result, files, sandbox=None, ctx=None):
        ctx = ctx if ctx is not None else {'token': 'tok', 'full': False}
        sandbox = sandbox or FakeSandbox(self.scenario)
        with patch(_RUN_SHOTS, return_value=(result, files)) as run:
            self.hooks._knowledge_shoot(self.pkg, sandbox, self.Event.browse(), ctx)
        return run, ctx

    def _ok_result(self, image):
        return ({'shots': {'b%s' % self.binding.id: {'ok': True, 'images': [{
            'name': 'main', 'file': 'b/main.png',
            'regions': [{'n': 1, 'x': 10, 'y': 10, 'w': 30, 'h': 10}],
            'records': {'res.partner': [7]}}]}}}, {'b/main.png': image})

    def test_shoot_adopts_images_and_skips_same_dhash(self):
        self._only_f1()
        art = self._article(self.f1, self.cap_a, fingerprint='h2')
        self._publish(art)
        result, files = self._ok_result(png(box=(20, 20, 80, 60)))
        run, _ctx = self._shoot(result, files)
        shots = run.call_args[0][2]
        self.assertEqual(shots[0]['login'], 'doc_admin')
        self.assertEqual(shots[0]['steps'][0], {'open': {'model': 'res.partner', 'res_id': 7}})
        self.assertEqual(self.binding.state, 'ok')
        self.assertEqual(self.binding.shot_scope_hash, 'h2')
        assets = self.binding.current_assets()
        self.assertEqual(len(assets), 1)
        self.assertEqual(assets.owner_model, 'corpaas.knowledge.shot_binding')
        self.assertEqual(assets.scope_hash, 'h2', '素材鍵＝範本指紋')
        # 對帳：同指紋的文章換上新圖、重新推送
        self._dispatch()
        self.assertEqual(art.asset_ids, assets)
        self.assertIn('/web/image/', art.placement_ids.slide_id.html_content)
        self.binding.state = 'pending'
        self._shoot(*self._ok_result(png(box=(20, 20, 80, 60))))
        self.assertEqual(self.binding.current_assets(), assets, 'dHash 相同不換圖')
        self.binding.state = 'pending'
        self._shoot(*self._ok_result(png(stripes=6)))
        self.assertEqual(assets.state, 'superseded')
        self.assertTrue(assets.superseded_at)
        self.assertEqual(len(self.binding.current_assets()), 1)

    def test_shoot_d1_gate_rejects(self):
        self._only_f1()
        sandbox = FakeSandbox(self.scenario)
        sandbox.bad = [['res.partner', 99]]
        with patch.object(self.Ai, 'ask', side_effect=hub_client.BudgetExceeded('over')):
            self._shoot(*self._ok_result(png()), sandbox=sandbox)
        self.assertEqual(self.binding.state, 'failed')
        self.assertIn('D1', self.binding.last_error)
        self.assertFalse(self.binding.current_assets())

    def test_shoot_failure_repairs_template_next_time(self):
        self._only_f1()
        result = {'shots': {'b%s' % self.binding.id: {
            'ok': False, 'error': 'Timeout waiting for field name', 'dom_text': '報名'}}}
        fixed = [{'open': '{rec}'}, {'highlight': {'field': 'display_name'}}, {'shot': 'main'}]
        with patch.object(self.Ai, 'ask', return_value={'steps': fixed, 'reason': 'x'}) as ask:
            run, _ctx = self._shoot(result, {})
        self.assertEqual(run.call_count, 1, '同一次不重拍')
        self.assertEqual(ask.call_args[0][0], 'manual_repair')
        self.assertEqual(self.tmpl1.steps(), fixed)
        self.assertEqual(self.tmpl1.repair_count, 1)
        self.assertEqual(self.binding.state, 'pending')

    def test_repair_attempts_capped(self):
        self._only_f1()
        self.binding.write({'state': 'failed', 'needs_repair': True, 'repair_attempts': 3})
        with patch.object(self.Ai, 'ask', side_effect=hub_client.BudgetExceeded('x')) as ask:
            self._dispatch()
        self.assertNotIn('manual_repair', [c[0][0] for c in ask.call_args_list])
        self.assertFalse(self.binding.needs_repair)
        self.assertEqual(self.binding.state, 'failed')

    def test_shoot_budget_exceeded_is_not_failure(self):
        self._only_f1()
        result = {'shots': {'b%s' % self.binding.id: {'ok': False, 'error': 'boom'}}}
        with patch.object(self.Ai, 'ask', side_effect=hub_client.BudgetExceeded('over')):
            _run, ctx = self._shoot(result, {})
        self.assertTrue(ctx['manual_ai_stopped']['ai'])
        self.assertEqual(self.binding.state, 'failed')
        self.assertTrue(self.binding.needs_repair)

    def test_new_fingerprint_forks_template_without_ai(self):
        """B6：方案指紋換了、沒有新指紋的範本 → 複製舊範本（不叫 AI），繫結沿用。"""
        self._only_f1()
        self._fp(self.f1, 'h3')
        with patch.object(self.Ai, 'ask', side_effect=hub_client.BudgetExceeded('x')) as ask, \
                patch(_RUN_SHOTS, return_value=({}, {})):
            self.hooks._knowledge_shoot(self.pkg, FakeSandbox(self.scenario),
                                        self.Event.browse(), {'token': 'tok'})
        purposes = [c[0][0] for c in ask.call_args_list]
        self.assertNotIn('manual_explore', purposes)
        self.assertNotIn('manual_bind', purposes)
        new = self.Template.search([('feature_id', '=', self.f1.id), ('fingerprint', '=', 'h3')])
        self.assertEqual(len(new), 1)
        self.assertEqual(new.derived_from_id, self.tmpl1)
        self.assertEqual(new.steps(), self.tmpl1.steps())
        self.assertEqual(new.binding_for(self.scenario).bindings(), self.binding.bindings())
        self.assertEqual(self.tmpl1.fingerprint, 'h2', '舊範本不動（別的方案還在用）')

    def test_fingerprint_error_skips(self):
        """B7：指紋算不出來（scope False）→ 跳過，不寫新區塊、新文章。"""
        self._only_f1()
        self._fp(self.f1, None, error='boom')
        with patch.object(self.Ai, 'ask') as ask:
            self._dispatch(self._event('feature_added', self.f1))
        self.assertFalse(self._mine(ask))
        self.assertFalse(self.Article.search([('feature_id', '=', self.f1.id)]))
        self.assertFalse(self.Block.search([('feature_id', '=', self.f1.id)]))

    # ------------------------------------------------------------------
    # 指紋改變：分岔（B1）、原地換鍵、收斂提案
    # ------------------------------------------------------------------
    def _published_article(self, scenario=None, fingerprint='h1'):
        block = self._block(self.f1, fingerprint=fingerprint, publish=True)
        art = self._article(self.f1, self.cap_a, scenario=scenario, block=block,
                            fingerprint=fingerprint)
        art._do_publish('new')
        return art, block

    def test_scope_change_in_shared_article_forks_new_one(self):
        """B1：兩個方案共用一篇；方案 A 改版 → A 分岔一篇新的，B 的文字與圖一個字都不變。"""
        self._only_f1()
        self._fp(self.f1, 'h1')
        pkg_b = self._new_package('KB Plan B')
        art, old = self._published_article()
        self.assertEqual(art.placement_ids.mapped('package_id'), self.pkg | pkg_b)
        slide_a = art.placement_ids.filtered(lambda p: p.package_id == self.pkg).slide_id
        slide_b = art.placement_ids.filtered(lambda p: p.package_id == pkg_b).slide_id
        html_b = slide_b.html_content
        self._fp(self.f1, 'h2')
        self.binding.write({'state': 'ok'})
        self._asset(self.f1, owner=self.binding, scope_hash='h2')
        answer = {'changed': True, 'title': '新步驟',
                  'steps': [{'title': '開啟', 'html': '<p>改了</p>'}], 'reason': '欄位改名'}
        with patch.object(self.Ai, 'ask', return_value=answer) as ask:
            self._dispatch(self._event('scope_changed', self.f1, role_code='admin',
                                       payload=json.dumps({'old': 'h1', 'new': 'h2'})))
        self.assertEqual(len(self._mine(ask)), 1)
        self.assertEqual(self._mine(ask)[0][0][0], 'manual_fork')
        self.assertIn('按下按鈕', self._mine(ask)[0][0][1], '分岔以既有步驟為底')
        new = self.Article.search([('feature_id', '=', self.f1.id), ('fingerprint', '=', 'h2')])
        self.assertEqual(len(new), 1)
        self.assertEqual(new.manual_forked_from_id, art)
        self.assertEqual(new.state, 'review')
        fork = new.step_block_ids
        self.assertEqual(fork.derived_from_id, old)
        self.assertEqual(fork.anchor, old.anchor, '分岔沿用錨點')
        self.assertEqual(art.fingerprint, 'h1')
        self.assertEqual(art.step_block_ids, old)
        self.assertEqual(art.state, 'published')
        self.assertEqual(old.state, 'published', '舊方案仍引用舊區塊')
        # 審核畫面：文字差異、截圖、影響範圍
        review = new.manual_review_html
        self.assertIn('步驟區塊差異', review)
        self.assertIn('影響範圍', review)
        self.assertIn('KB Manual Plan', review)
        self.assertNotIn('KB Plan B', review)
        new.with_user(self.approver).action_approve()
        self.assertEqual(new.state, 'published')
        self.assertEqual(fork.state, 'published')
        pl_a = new.placement_ids
        self.assertEqual(pl_a.package_id, self.pkg)
        self.assertEqual(pl_a.slide_id, slide_a, 'A 的 slide 由新指紋那篇接手，網址不變')
        self.assertIn('改了', slide_a.html_content)
        self.assertEqual(art.placement_ids.package_id, pkg_b)
        slide_b.invalidate_recordset()
        self.assertEqual(slide_b.html_content, html_b, 'B 的內容一個字都不變')

    def test_scope_change_unshared_rekeys_in_place(self):
        """只有本方案在用：原地換指紋；AI 判定文字不必改 → stale，圖好了才回 published。"""
        self._only_f1()
        self._fp(self.f1, 'h1')
        art, old = self._published_article()
        self._fp(self.f1, 'h2')
        with patch.object(self.Ai, 'ask', return_value={'changed': False}):
            self._dispatch()
        self.assertEqual(art.fingerprint, 'h2')
        self.assertEqual(art.step_block_ids, old)
        self.assertEqual(art.state, 'stale', '新指紋的圖還沒拍好')
        self.assertEqual(self.Article.search_count([('feature_id', '=', self.f1.id)]), 1)
        # 下一次 refresh（沒有新事件）：圖好了 → 回 published（B5 失效回復）
        self.binding.write({'state': 'ok'})
        asset = self._asset(self.f1, owner=self.binding, scope_hash='h2')
        with patch.object(self.Ai, 'ask') as ask:
            self._dispatch()
        self.assertFalse(self._mine(ask), '同一個區塊×指紋不再問 AI')
        self.assertEqual(art.state, 'published')
        self.assertEqual(art.asset_ids, asset)

    def test_scope_change_forks_step_block_in_place(self):
        self._only_f1()
        self._fp(self.f1, 'h1')
        art, old = self._published_article()
        other_sc = self.env['corpaas.knowledge.scenario'].sudo().create(
            {'name': '學會研討會', 'code': 'kbtest_conf', 'package_ids': [(6, 0, self.pkg.ids)]})
        art2 = self._article(self.f1, self.cap_a, scenario=other_sc, block=old)
        art2._do_publish('new')
        self._fp(self.f1, 'h2')
        answer = {'changed': True, 'title': '新步驟',
                  'steps': [{'title': '開啟', 'html': '<p>改了</p>'}], 'reason': '欄位改名'}
        with patch.object(self.Ai, 'ask', return_value=answer) as ask:
            self._dispatch()
        self.assertEqual(len(self._mine(ask)), 1, '同一個分岔只問一次 AI')
        fork = art.step_block_ids
        self.assertNotEqual(fork, old)
        self.assertEqual(fork.derived_from_id, old)
        self.assertEqual(fork.fingerprint, 'h2')
        self.assertEqual(art2.step_block_ids, fork)
        self.assertEqual(art.state, 'review')
        self.assertEqual(art.pending_change, 'text')
        self.assertEqual(old.state, 'published')
        slide = art.placement_ids.slide_id
        self.assertNotIn('改了', slide.html_content, '待核的新區塊不上前台')

    def test_budget_leaves_stale_and_next_refresh_recovers(self):
        """B5：這次預算用完 → 維持原狀；下一次 refresh 沒有事件也會接著做。"""
        self._only_f1()
        self._fp(self.f1, 'h1')
        art, _old = self._published_article()
        self._fp(self.f1, 'h2')
        with patch.object(self.Ai, 'ask', side_effect=hub_client.BudgetExceeded('over')):
            self._dispatch(self._event('scope_changed', self.f1, role_code='admin',
                                       payload=json.dumps({'old': 'h1', 'new': 'h2'})))
        self.assertEqual(art.fingerprint, 'h1')
        self.assertEqual(art.state, 'published')
        answer = {'changed': True, 'title': 't',
                  'steps': [{'title': '開啟', 'html': '<p>改了</p>'}]}
        with patch.object(self.Ai, 'ask', return_value=answer):
            self._dispatch(token='tok2')
        self.assertEqual(art.fingerprint, 'h2')
        self.assertEqual(art.state, 'review')

    def test_scope_change_other_role_ignored(self):
        self._only_f1()
        self._fp(self.f1, 'h1')
        art, _old = self._published_article()
        self._fp(self.f1, 'h9', role='sales')
        with patch.object(self.Ai, 'ask') as ask:
            self._dispatch()
        self.assertFalse(self._mine(ask))
        self.assertEqual(art.state, 'published')
        self.assertEqual(art.fingerprint, 'h1')

    def test_implicit_convergence_becomes_merge_proposal(self):
        """同指紋已有別條分岔線的區塊 → 不默默改用它，分岔後提合併、人工確認。"""
        self._only_f1()
        self._fp(self.f1, 'h1')
        art, old = self._published_article()
        stranger = self._block(self.f1, fingerprint='h2', html='<h4>別人</h4><p>別條線</p>',
                               publish=True)
        self._fp(self.f1, 'h2')
        answer = {'changed': True, 'title': '新步驟',
                  'steps': [{'title': '開啟', 'html': '<p>改了</p>'}]}
        with patch.object(self.Ai, 'ask', return_value=answer):
            self._dispatch()
        fork = art.step_block_ids
        self.assertNotEqual(fork, stranger)
        self.assertEqual(fork.derived_from_id, old)
        merge = self.env['corpaas.knowledge.step_block.merge'].search(
            [('feature_id', '=', self.f1.id), ('state', '=', 'proposed')])
        self.assertEqual(len(merge), 1)
        self.assertEqual(merge.keep_id | merge.merge_ids, stranger | fork)

    def test_converged_blocks_merge_proposal(self):
        keep = self._block(self.f2, fingerprint='hx', publish=True)
        dup = self._block(self.f2, fingerprint='hx', derived_from_id=keep.id)
        art = self._article(self.f2, self.cap_a, block=dup)
        merges = self.hooks._manual_propose_merges(self.f2)
        self.assertEqual(len(merges), 1)
        self.assertEqual(merges.keep_id, keep)
        self.assertEqual(merges.merge_ids, dup)
        self.assertEqual(self.hooks._manual_propose_merges(self.f2), merges, '不重複提案')
        merges.action_merge()
        self.assertEqual(art.step_block_ids, keep)
        self.assertEqual(dup.state, 'retired')
        self.assertEqual(merges.state, 'done')
        self.assertFalse(self.hooks._manual_propose_merges(self.f2))

    def test_rejected_merge_not_reproposed(self):
        keep = self._block(self.f3, fingerprint='hy')
        self._block(self.f3, fingerprint='hy')
        merge = self.hooks._manual_propose_merges(self.f3)
        merge.action_reject()
        self.assertFalse(self.hooks._manual_propose_merges(self.f3))
        self.assertEqual(merge.keep_id, keep)

    # ------------------------------------------------------------------
    # 重新基準（B6）
    # ------------------------------------------------------------------
    def test_rebaseline_rekeys_without_forking(self):
        self._only_f1()
        art, block = self._published_article(fingerprint='h2')
        asset = self._asset(self.f1, owner=self.binding, scope_hash='h2')
        self.binding.write({'state': 'ok', 'shot_scope_hash': 'h2'})
        pkg_b = self._new_package('KB Plan R', scope_hash='h2')
        with patch.object(self.Ai, 'ask') as ask:
            self.hooks._knowledge_fingerprint_rebaselined(self.f1, self.pkg, 'admin', 'h2', 'h3')
        self.assertFalse(self._mine(ask))
        self.assertEqual(self.tmpl1.fingerprint, 'h3')
        self.assertEqual(block.fingerprint, 'h3')
        self.assertEqual(art.fingerprint, 'h3')
        self.assertEqual(asset.scope_hash, 'h3')
        self.assertEqual(self.binding.shot_scope_hash, 'h3')
        self.assertEqual(art.state, 'published', '不分岔、不送審')
        # 方案 B 還沒 refresh（目前指紋仍是 h2）→ 經對照換算，文章照樣屬於它
        self.assertEqual(self.hooks._manual_package_hashes(pkg_b, self.f1), {'admin': 'h3'})
        self.assertIn(pkg_b, art._manual_fitting_packages())
        # B 之後也換到同一個新指紋：不再搬第二次
        self.hooks._knowledge_fingerprint_rebaselined(self.f1, pkg_b, 'admin', 'h2', 'h3')
        self.assertEqual(self.env['corpaas.knowledge.manual.rebase'].search_count(
            [('feature_id', '=', self.f1.id)]), 1)

    # ------------------------------------------------------------------
    # 新文章
    # ------------------------------------------------------------------
    def test_draft_new_article_uses_existing_step_block(self):
        self._only_f1()
        block = self._block(self.f1, fingerprint='h2')
        with patch.object(self.Ai, 'ask',
                          return_value={'title': '會員報名', 'html': '<p>為什麼</p>'}) as ask:
            self._dispatch(self._event('feature_added', self.f1))
        mine = self._mine(ask)
        self.assertEqual(len(mine), 1, '已有步驟區塊就只寫情境區塊')
        self.assertEqual(mine[0][0][0], 'manual_scenario')
        self.assertIn('按下按鈕', mine[0][0][1], '情境區塊 prompt 要帶入既有步驟')
        art = self.Article.search([('feature_id', '=', self.f1.id)])
        self.assertEqual(len(art), 1)
        self.assertEqual(art.step_block_ids, block)
        self.assertEqual(art.fingerprint, 'h2')
        self.assertEqual(art.state, 'review')
        self.assertEqual(art.capability_id, self.cap_a)
        self.assertEqual(art.shot_binding_id, self.binding)

    def test_draft_new_article_forks_block_of_other_fingerprint(self):
        """B7：這個指紋沒有區塊、別的指紋有 → 以它為底分岔（不從頭重寫）。"""
        self._only_f1()
        src = self._block(self.f1, fingerprint='h1', publish=True)

        def ask(purpose, prompt, **kw):
            if purpose == 'manual_fork':
                return {'changed': True, 'title': 't',
                        'steps': [{'title': '開啟', 'html': '<p>新版</p>'}]}
            return {'title': '會員報名', 'html': '<p>為什麼</p>'}
        with patch.object(self.Ai, 'ask', side_effect=ask) as mock:
            self._dispatch()
        purposes = [c[0][0] for c in self._mine(mock)]
        self.assertEqual(purposes, ['manual_fork', 'manual_scenario'])
        art = self.Article.search([('feature_id', '=', self.f1.id)])
        self.assertEqual(art.step_block_ids.derived_from_id, src)
        self.assertEqual(art.step_block_ids.fingerprint, 'h2')

    def test_rename_target_is_not_candidate(self):
        """B9：改名候選還沒確認 → 新鍵不起草。"""
        self._only_f1()
        old = self.Feature.create({
            'feature_key': 'kbtest.action:kbtest.a0', 'module': 'kbtest', 'kind': 'action',
            'anchor': 'kbtest.a0', 'name': '舊報名', 'model': 'res.partner'})
        rename = self.env['corpaas.knowledge.rename'].sudo().create(
            {'old_feature_id': old.id, 'new_feature_id': self.f1.id})
        self.assertNotIn(self.f1, self.hooks._manual_candidates(self.pkg))
        with patch.object(self.Ai, 'ask') as ask:
            self._dispatch()
        self.assertFalse(self._mine(ask))
        rename.state = 'rejected'
        self.assertIn(self.f1, self.hooks._manual_candidates(self.pkg))

    # ------------------------------------------------------------------
    # 下架（B8）
    # ------------------------------------------------------------------
    def _remove(self, feature, pkg):
        feature.write({'package_ids': [(3, pkg.id)], 'missing_package_ids': [(4, pkg.id)]})

    def test_feature_removed_retires_only_that_package(self):
        self._only_f1()
        self._fp(self.f1, 'h1')
        pkg_b = self._new_package('KB Plan B')
        art, _old = self._published_article()
        pl_a = art.placement_ids.filtered(lambda p: p.package_id == self.pkg)
        pl_b = art.placement_ids - pl_a
        self._remove(self.f1, self.pkg)
        # 有改名候選 → 先不下架
        self._event('rename_candidate', self.f1)
        events = self.Event.search([('refresh_token', '=', 'tok')])
        self._dispatch(events | self._event('feature_removed', self.f1))
        self.assertTrue(pl_a.slide_id.is_published, '有改名候選就先不下架')
        self._dispatch(self._event('feature_removed', self.f1))
        self.assertTrue(pl_a.manual_retired)
        self.assertFalse(pl_a.slide_id.is_published)
        self.assertTrue(pl_a.slide_id.exists())
        self.assertTrue(pl_b.slide_id.is_published, '別的方案照樣上線')
        self.assertEqual(art.state, 'published')
        # 全部方案都沒有了 → 整篇下架
        self._remove(self.f1, pkg_b)
        self._dispatch(self._event('feature_removed', self.f1, pkg=pkg_b), pkg=pkg_b)
        self.assertEqual(art.state, 'retired')
        self.assertFalse(pl_b.slide_id.is_published)

    def test_retired_article_not_duplicated(self):
        self._only_f1()
        art, _old = self._published_article(fingerprint='h2')
        self._remove(self.f1, self.pkg)
        self.hooks._knowledge_feature_gone(self.f1)
        self.assertEqual(art.state, 'retired')
        # 功能回來了
        self.f1.write({'package_ids': [(4, self.pkg.id)],
                       'missing_package_ids': [(3, self.pkg.id)]})
        with patch.object(self.Ai, 'ask') as ask:
            self._dispatch()
        self.assertFalse(self._mine(ask))
        self.assertEqual(self.Article.search_count([('feature_id', '=', self.f1.id)]), 1)
        self.assertEqual(art.state, 'review')
        self.assertEqual(art.pending_change, 'restore')

    def test_system_retire_as_non_approver(self):
        """功能消失的下架是系統流程：觸發 refresh 的人不是核准者也要做得完。"""
        self._only_f1()
        art, _block = self._published_article(fingerprint='h2')
        plain = new_test_user(self.env, 'kb_manual_plain', groups='base.group_user')
        self._remove(self.f1, self.pkg)
        self.assertTrue(self.f1.missing)
        self.hooks.with_user(plain)._manual_retire_removed(
            self.pkg, self._event('feature_removed', self.f1))
        self.assertEqual(art.state, 'retired')
        self.assertFalse(art.placement_ids.slide_id.is_published)

    # ------------------------------------------------------------------
    # AI 回覆格式不對：當成這一項失敗，不中斷分派
    # ------------------------------------------------------------------
    _BAD = (['x'], 'oops', 42, {'title': ['t'], 'steps': ['打開選單', '按下建立']},
            {'steps': 'x', 'bindings': ['a'], 'html': ['<p>x</p>']})

    def test_malformed_ai_new_article_paths(self):
        self._only_f1()
        for bad in self._BAD:
            with patch.object(self.Ai, 'ask', return_value=bad):
                self._dispatch()
        self.assertFalse(self.Article.search([('feature_id', '=', self.f1.id)]))
        self.assertFalse(self.Block.search([('feature_id', '=', self.f1.id)]))
        # 已有步驟區塊 → 只剩情境區塊這一步
        self._block(self.f1, fingerprint='h2')
        for bad in self._BAD:
            with patch.object(self.Ai, 'ask', return_value=bad):
                self._dispatch()
        self.assertFalse(self.Article.search([('feature_id', '=', self.f1.id)]))
        # 下一次 refresh AI 正常 → 接著做
        with patch.object(self.Ai, 'ask', return_value={'title': '會員報名', 'html': '<p>為什麼</p>'}):
            self._dispatch()
        self.assertEqual(self.Article.search([('feature_id', '=', self.f1.id)]).state, 'review')

    def test_malformed_ai_fork_and_repair_paths(self):
        self._only_f1()
        self._fp(self.f1, 'h1')
        art, old = self._published_article()
        self._fp(self.f1, 'h2')
        self.binding.write({'state': 'failed', 'needs_repair': True})
        for bad in (['x'], 'oops', 42, {'changed': True, 'steps': ['打開選單']},
                    {'changed': True, 'steps': 'x'}):
            with patch.object(self.Ai, 'ask', return_value=bad):
                self._dispatch()
        self.assertEqual(art.fingerprint, 'h1')
        self.assertEqual(art.step_block_ids, old)
        self.assertEqual(art.state, 'published')
        self.assertEqual(self.binding.state, 'failed')
        self.assertEqual(self.binding.repair_attempts, 0)

    def test_malformed_ai_explore_and_bind(self):
        tmpl = self.Template.create({
            'feature_id': self.f2.id, 'login_role': 'admin', 'fingerprint': 'h1',
            'steps_json': json.dumps([{'open': '{rec}'}, {'shot': 'main'}])})
        sandbox = FakeSandbox(self.scenario)
        stop = {'ai': False}
        for bad in self._BAD:
            with patch.object(self.Ai, 'ask', return_value=bad), \
                    patch.object(type(self.hooks), '_manual_probe', lambda *a: {}), \
                    patch('odoo.addons.dobtor_corpaas_knowledge.services.remote.shell_json',
                          return_value={'form': '<form/>'}):
                with self.assertRaises(ValueError):
                    self.hooks._manual_explore(self.pkg, sandbox, self.f3, {'admin': 'h1'},
                                               'tok')
                try:
                    binding = self.hooks._manual_bind(self.pkg, tmpl, self.scenario, 'tok', stop)
                except ValueError:
                    continue
                self.assertEqual(binding.bindings(), {}, '格式不對的繫結一律不收')
                binding.unlink()
        # 整條拍攝流程：格式不對不中斷
        with patch.object(self.Ai, 'ask', return_value=['x']), \
                patch(_RUN_SHOTS, return_value=({}, {})), \
                patch.object(type(self.hooks), '_manual_probe', lambda *a: {}), \
                patch('odoo.addons.dobtor_corpaas_knowledge.services.remote.shell_json',
                      return_value={'form': '<form/>'}):
            self.hooks._knowledge_shoot(self.pkg, sandbox, self.Event.browse(), {'token': 'tok'})

    # ------------------------------------------------------------------
    # help 連結
    # ------------------------------------------------------------------
    def test_help_links(self):
        self._only_f1()
        art, block = self._published_article(fingerprint='h2')
        matches = [(self.f1, 1.0)]
        links = self.hooks._knowledge_help_links(self.pkg, matches, None, {'limit': 5})
        self.assertEqual(len(links), 1)
        link = links[0]
        self.assertEqual(link['kind'], 'manual')
        self.assertEqual(link['feature_key'], self.f1.feature_key)
        self.assertEqual(link['scenario'], '協會年會')
        self.assertEqual(link['anchor'], block.anchor)
        self.assertTrue(link['url'].endswith('#%s' % block.anchor))
        self.assertIn('/slides/slide/', link['url'])
        self.assertEqual(link['fingerprint'].get('scope_hash'), 'h2')
        self.env['ir.config_parameter'].sudo().set_param(
            'corpaas_knowledge.public_base_url', 'https://docs.example.com/')
        link = self.hooks._knowledge_help_links(self.pkg, matches, None, {})[0]
        self.assertTrue(link['url'].startswith('https://docs.example.com/slides/slide/'))
        # ★ 送審中、失效中：舊版照樣在線上，連結照給
        art.scenario_html = '<p>改寫中</p>'
        art.knowledge_propose('text')
        self.assertEqual(art.state, 'review')
        self.assertEqual(len(self.hooks._knowledge_help_links(self.pkg, matches, None, {})), 1)
        art.state = 'stale'
        self.assertEqual(len(self.hooks._knowledge_help_links(self.pkg, matches, None, {})), 1)
        art.action_retire()
        self.assertFalse(self.hooks._knowledge_help_links(self.pkg, matches, None, {}))

    # ------------------------------------------------------------------
    # 按鈕走 AI 佇列、審核、改名
    # ------------------------------------------------------------------
    def test_ai_button_enqueues(self):
        self._only_f1()
        art, _block = self._published_article(fingerprint='h2')
        with patch.object(self.Ai, 'enqueue', return_value={'type': 'x'}) as enq, \
                patch.object(self.Ai, 'ask') as ask:
            art.action_ai_rewrite_scenario()
        ask.assert_not_called()
        self.assertEqual(enq.call_args[0][:3], (art, '_manual_ai_rewrite_scenario_run', self.pkg))
        with patch.object(self.Ai, 'ask', return_value={'title': '新', 'html': '<p>新情境</p>'}):
            art._manual_ai_rewrite_scenario_run()
        self.assertEqual(art.state, 'review')
        self.assertIn('新情境', art.scenario_html)

    def test_batch_approve_by_scenario(self):
        self._only_f1()
        a1 = self._article(self.f1, self.cap_a, fingerprint='h2')
        a2 = self._article(self.f2, self.cap_a)
        (a1 | a2).knowledge_propose('new')
        a1.with_user(self.approver).action_approve_by_scenario()
        self.assertEqual((a1 | a2).mapped('state'), ['published', 'published'])

    def test_rename_and_check_ref(self):
        self._only_f1()
        art, block = self._published_article(fingerprint='h2')
        new = self.Feature.create({
            'feature_key': 'kbtest.action:kbtest.a1b', 'module': 'kbtest', 'kind': 'action',
            'anchor': 'kbtest.a1b', 'name': '建立報名（新）', 'model': 'res.partner'})
        self.assertTrue(self.hooks._knowledge_check_feature_ref(self.f1))
        self.hooks._knowledge_rename_feature(self.f1, new)
        self.assertEqual(art.feature_id, new)
        self.assertEqual(block.feature_id, new)
        self.assertEqual(self.tmpl1.feature_id, new)
        self.assertEqual(self.binding.feature_id, new)
        self.assertFalse(self.hooks._knowledge_check_feature_ref(self.f1))


@tagged('post_install', '-at_install')
class TestManualProbe(ManualCase):
    """AI 探索前先在說明庫實際打開畫面（探測），結果交給 AI。"""

    def test_probe_feeds_explore_prompt(self):
        Ai = type(self.env['corpaas.knowledge.ai'])
        hooks = self.env['corpaas.knowledge.hooks']
        sandbox = FakeSandbox(self.scenario)
        probe_result = {'shots': {'probe': {'ok': True, 'images': [
            {'name': 'entry', 'is_probe': True,
             'probe': {'view_type': 'list', 'buttons': [], 'fields': [], 'tabs': []}},
            {'name': 'record', 'is_probe': True,
             'probe': {'view_type': 'form', 'buttons': [{'name': 'action_confirm', 'text': '確認'}],
                       'fields': [{'name': 'partner_id', 'label': '客戶'}], 'tabs': []}}]}}}
        seed = [{'xmlid': '__doc_scenario_kbtest_assoc.p1', 'model': 'res.partner',
                 'values': {'name': 'x'}}]
        with patch(_RUN_SHOTS, return_value=(probe_result, {})) as run, \
                patch.object(type(hooks), '_manual_seed', lambda s, sc: seed), \
                patch('odoo.addons.dobtor_corpaas_knowledge.services.remote.shell_json',
                      return_value={'form': '<form/>'}), \
                patch.object(Ai, 'ask', return_value={
                    'login_role': 'admin', 'bindings': {'rec': seed[0]['xmlid']},
                    'steps': [{'open': '{rec}'}, {'shot': 'main'}]}) as ask:
            tmpl = hooks._manual_explore(self.pkg, sandbox, self.f1, {'admin': 'h9'}, 'tok')
        steps = run.call_args[0][2][0]['steps']
        self.assertIn({'probe': 'entry'}, steps)
        self.assertIn({'probe': 'record'}, steps)
        prompt = ask.call_args[0][1]
        self.assertIn('action_confirm', prompt, '實際畫面要進 prompt')
        self.assertIn('實際畫面', prompt)
        self.assertEqual(tmpl.fingerprint, 'h9')

    def test_probe_failure_falls_back(self):
        from odoo.addons.dobtor_corpaas_knowledge.services import shooter
        hooks = self.env['corpaas.knowledge.hooks']
        with patch(_RUN_SHOTS, side_effect=shooter.ShotError('boom')):
            self.assertEqual(hooks._manual_probe(FakeSandbox(self.scenario), self.f1), {})


@tagged('post_install', '-at_install')
class TestHelpRoleOrder(ManualCase):

    def test_role_overlap_orders_articles(self):
        Role = self.env['corpaas.knowledge.role'].sudo()
        wh = Role.create({'code': 'wh', 'name': '倉管', 'group_xmlids': 'stock.group_stock_user'})
        sales = Role.create({'code': 'kbt_sales', 'name': '業務', 'group_xmlids': 'sales_team.group_sale_salesman'})
        sc2 = self.env['corpaas.knowledge.scenario'].sudo().create({
            'name': '倉儲', 'code': 'kbtest_wh', 'package_ids': [(6, 0, self.pkg.ids)],
            'role_ids': [(6, 0, wh.ids)]})
        self.scenario.role_ids = [(6, 0, sales.ids)]
        hooks = self.env['corpaas.knowledge.hooks']
        arts = self.Article.browse()
        for sc in (self.scenario, sc2):
            arts |= self._article(self.f1, self.cap_a, scenario=sc)
        # 不依賴同步細節：直接驗排序函式對 ctx.groups 的反應
        with patch.object(type(hooks), '_manual_public_url', lambda s, slide: '/x/%s' % slide.id):
            self._publish(*arts)
            links = hooks._knowledge_help_links(self.pkg, [(self.f1, 1.0)], None,
                                                {'groups': ['stock.group_stock_user']})
        manual = [l for l in links if l['kind'] == 'manual']
        if len(manual) >= 2:
            self.assertEqual(manual[0]['scenario'], '倉儲')
