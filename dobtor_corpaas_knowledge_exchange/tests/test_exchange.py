# -*- coding: utf-8 -*-
"""主從交換：公開判定、匯出／鏡像 upsert、主體端處理、從屬端送件與拉取、HTTP 驗證。"""
import json
import time
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import HttpCase, TransactionCase, tagged

from ..lib import protocol

POST = 'odoo.addons.dobtor_corpaas_knowledge_exchange.lib.protocol.post'


class _Base(TransactionCase):

    def setUp(self):
        super().setUp()
        self.icp = self.env['ir.config_parameter'].sudo()
        self.icp.set_param('corpaas_knowledge.console_code', 'corpaas')
        self.Ex = self.env['corpaas.knowledge.exchange']
        self.Def = self.env['corpaas.knowledge.code_def'].sudo()
        self.Peer = self.env['corpaas.knowledge.exchange.peer'].sudo()

    def mode(self, mode, *features):
        self.icp.set_param('corpaas_knowledge.exchange_mode', mode)
        for f in ('lookup', 'ingest', 'feed'):
            self.icp.set_param('corpaas_knowledge.exchange_enable_%s' % f, 'True' if f in features else 'False')

    def make_def(self, module='(core)', h='h1', summary=True):
        return self.Def.create({'def_hash': h, 'method': 'action_confirm', 'module': module,
                                'summary_json': json.dumps({'pre': ['已報價']}) if summary else False})


@tagged('post_install', '-at_install')
class TestVisibility(_Base):

    def test_core_public_custom_private(self):
        Vis = self.env['corpaas.knowledge.exchange.visibility']
        core, cust = self.make_def('(core)', 'a'), self.make_def('x_customer_mod', 'b')
        Vis._classify(core | cust)
        self.assertEqual(core.kb_visibility, 'public', 'Odoo 核心公開')
        self.assertEqual(cust.kb_visibility, 'private', '不認識的模組預設私有')
        self.icp.set_param('corpaas_knowledge.exchange_private_modules', '(core)')
        Vis._classify(core)
        self.assertEqual(core.kb_visibility, 'private', '系統參數可強制私有')

    def test_fact_with_private_segment_is_private(self):
        Vis = self.env['corpaas.knowledge.exchange.visibility']
        Fact = self.env['corpaas.knowledge.code_fact'].sudo()
        pub = Fact.create({'subject': 'sale.order.action_confirm', 'chain_hash': 'c1',
                           'def_ids': [(6, 0, self.make_def('(core)', 'a').ids)]})
        mixed = Fact.create({'subject': 'sale.order.action_confirm', 'chain_hash': 'c2',
                             'def_ids': [(6, 0, (self.make_def('(core)', 'b') | self.make_def('x_cust', 'c')).ids)]})
        Vis._classify(pub | mixed)
        self.assertEqual(pub.kb_visibility, 'public')
        self.assertEqual(mixed.kb_visibility, 'private', '繼承鏈任何一段私有 → 整個結論私有')


@tagged('post_install', '-at_install')
class TestCodec(_Base):

    def test_export_and_mirror_upsert_roundtrip(self):
        d = self.make_def()
        payload = d._kb_export()
        uid, digest = d.kb_uid, d.kb_content_hash
        self.assertEqual(payload['def_hash'], 'h1')
        self.assertNotIn('id', payload)
        d.unlink()
        m = self.Def._kb_upsert(payload)
        self.assertEqual((m.kb_uid, m.kb_sync_state, m.kb_trust), (uid, 'mirror', 'master'))
        self.assertEqual(m.kb_content_hash, digest, '兩邊算出同一個內容雜湊')
        self.assertEqual(self.Def._kb_upsert(payload), m, '同鍵同雜湊冪等，不重建')
        with self.assertRaises(UserError):
            m.summary_json = '{"x": 1}'

    def test_local_record_becomes_mirror_and_keeps_id(self):
        """本地算過的同鍵紀錄：主體版取代內容、改成鏡像，id 不變（引用不會斷）。"""
        d = self.make_def()
        payload = dict(d._kb_export(), kb_uid='u-master', content={'summary_json': '{"pre": ["主體版"]}'},
                       kb_content_hash='x')
        m = self.Def._kb_upsert(payload)
        self.assertEqual(m, d)
        self.assertEqual((d.kb_sync_state, d.kb_uid), ('mirror', 'u-master'))
        self.assertIn('主體版', d.summary_json)

    def test_template_code_clash_gets_suffix_and_kept_on_update(self):
        Cap = self.env['corpaas.knowledge.capability'].sudo()
        Cap.create({'name': '本地', 'code': 'cap_1'})
        payload = {'kind': 'capability', 'kb_uid': 'u-cap', 'kb_origin': 'corpaas', 'code': 'cap_1',
                   'content': {'name': '主體能力'}}
        m = Cap._kb_upsert(payload)
        self.assertEqual(m.code, 'cap_1_corpaas', '代碼撞到本地的加來源後綴')
        m2 = Cap._kb_upsert(dict(payload, code='cap_9', content={'name': '主體能力（改）'}))
        self.assertEqual((m2, m2.code, m2.name), (m, 'cap_1_corpaas', '主體能力（改）'), '既有紀錄不改代碼')


@tagged('post_install', '-at_install')
class TestMasterSide(_Base):

    def setUp(self):
        super().setUp()
        self.mode('master', 'lookup', 'ingest', 'feed')
        self.peer = self.Peer.create({'name': 'dobtor', 'code': 'dobtor', 'role': 'replica', 'key': 'k'})

    def _payload(self, module='(core)', h='p1', summary='{"pre": ["從屬讀的"]}'):
        return {'kind': 'code_def', 'kb_uid': 'u-%s' % h, 'kb_origin': 'dobtor', 'def_hash': h,
                'method': 'action_post', 'module': module, 'content': {'summary_json': summary}}

    def test_ingest_fact_private_rejected_public_ingested_then_exists(self):
        res = self.Ex._serve_ingest(self.peer, [self._payload('x_cust', 'p0')])
        self.assertEqual((res[0]['result'], res[0]['reason']), (protocol.REJECTED, 'private'),
                         '主體用自己的清單再判一次：私有不收')
        self.assertFalse(self.Def.search([('def_hash', '=', 'p0')]))
        res = self.Ex._serve_ingest(self.peer, [self._payload()])
        self.assertEqual(res[0]['result'], protocol.INGESTED)
        rec = self.Def.search([('def_hash', '=', 'p1')])
        self.assertEqual((rec.kb_origin, rec.kb_trust, rec.kb_sync_state), ('dobtor', 'replica', 'local'))
        res = self.Ex._serve_ingest(self.peer, [self._payload(summary='{"pre": ["另一份"]}')])
        self.assertEqual(res[0]['result'], protocol.EXISTS, '同一雜湊保留先入庫者')
        self.assertIn('從屬讀的', rec.summary_json)
        logs = self.env['corpaas.knowledge.exchange.ingest'].search([('peer_id', '=', self.peer.id)])
        self.assertEqual(len(logs), 3, '每筆都有稽核紀錄')

    def test_template_goes_to_review_and_approval_keeps_uid(self):
        payload = {'kind': 'capability', 'kb_uid': 'u-cap-1', 'kb_origin': 'dobtor', 'code': 'cap_7',
                   'content': {'name': '會員續約提醒'}}
        res = self.Ex._serve_ingest(self.peer, [payload])
        self.assertEqual(res[0]['result'], protocol.REVIEW)
        promo = self.env['corpaas.knowledge.exchange.promotion'].search([('kb_uid', '=', 'u-cap-1')])
        self.assertEqual(promo.state, 'pending')
        self.Ex._serve_ingest(self.peer, [payload])
        self.assertEqual(len(self.env['corpaas.knowledge.exchange.promotion'].search(
            [('kb_uid', '=', 'u-cap-1')])), 1, '重送不重複建提案')
        promo.action_approve()
        cap = self.env['corpaas.knowledge.capability'].search([('kb_uid', '=', 'u-cap-1')])
        self.assertEqual((cap.name, cap.kb_sync_state, cap.kb_origin), ('會員續約提醒', 'local', 'dobtor'))
        self.assertEqual(cap.state, 'published', '核准即上線')
        fed = self.env['corpaas.knowledge.exchange.feed'].search([('kb_uid', '=', 'u-cap-1')])
        self.assertTrue(fed, '核准後寫進發佈清單，從屬才拉得到')
        self.assertEqual(self.Ex._serve_ingest(self.peer, [payload])[0]['result'], protocol.EXISTS)

    def test_draft_template_not_fed_and_not_retracted(self):
        Feed = self.env['corpaas.knowledge.exchange.feed']
        start = Feed.search([], order='id desc', limit=1).id
        cap = self.env['corpaas.knowledge.capability'].create({'name': '報名'})
        cap._do_publish('new')
        items = self.Ex._serve_feed(self.peer, start)['items']
        self.assertIn(cap.kb_uid, [i['payload']['kb_uid'] for i in items if i['op'] == 'upsert'])
        cap.write({'pain': '草稿中的修改', 'state': 'draft'})
        items = [i for i in self.Ex._serve_feed(self.peer, start)['items']
                 if (i.get('kb_uid') or i.get('payload', {}).get('kb_uid')) == cap.kb_uid]
        self.assertEqual(items, [], '草稿不送也不作廢從屬已有的上線版')

    def test_merged_promotion_tells_replica(self):
        target = self.env['corpaas.knowledge.capability'].create({'name': '既有能力'})
        payload = {'kind': 'capability', 'kb_uid': 'u-cap-2', 'content': {'name': '既有能力 2'}}
        self.Ex._serve_ingest(self.peer, [payload])
        promo = self.env['corpaas.knowledge.exchange.promotion'].search([('kb_uid', '=', 'u-cap-2')])
        self.assertIn('既有能力', promo.similar_text, '名稱相近只當提示')
        promo.merged_into_uid = target.kb_uid
        promo.action_merge()
        res = self.Ex._serve_ingest(self.peer, [payload])
        self.assertEqual((res[0]['result'], res[0]['reason']), (protocol.REJECTED, 'merged:%s' % target.kb_uid))

    def test_lookup_only_public_with_content(self):
        pub = self.make_def('(core)', 'L1')
        self.make_def('x_cust', 'L2')
        self.make_def('(core)', 'L3', summary=False)
        res = self.Ex._serve_lookup(self.peer, [
            {'kind': 'code_def', 'key': {'def_hash': h, 'method': 'action_confirm', 'module': m}}
            for h, m in (('L1', '(core)'), ('L2', 'x_cust'), ('L3', '(core)'), ('L4', '(core)'))])
        self.assertEqual([r['found'] for r in res], [True, False, False, False])
        self.assertEqual(res[0]['payload']['kb_uid'], pub.kb_uid)

    def test_feed_upsert_and_retract(self):
        Feed = self.env['corpaas.knowledge.exchange.feed']
        start = Feed.search([], order='id desc', limit=1).id
        d = self.make_def('(core)', 'F1')
        self.env['corpaas.knowledge.exchange.visibility']._classify(d)
        res = self.Ex._serve_feed(self.peer, start)
        uids = [i['payload']['kb_uid'] for i in res['items'] if i['op'] == 'upsert']
        self.assertIn(d.kb_uid, uids, '公開且有內容 → 發佈')
        self.assertGreater(res['cursor'], start)
        self.icp.set_param('corpaas_knowledge.exchange_private_modules', '(core)')
        self.env['corpaas.knowledge.exchange.visibility']._classify(d)
        res2 = self.Ex._serve_feed(self.peer, start)
        ops = {i.get('kb_uid') or i.get('payload', {}).get('kb_uid'): i['op'] for i in res2['items']}
        self.assertEqual(ops.get(d.kb_uid), 'retract', '改為私有後同一筆回作廢，不再送內容')

    def test_feedback_lands_in_review_list(self):
        cap = self.env['corpaas.knowledge.capability'].create({'name': '報價'})
        res = self.Ex._serve_feedback(self.peer, [{'kind': 'capability', 'kb_uid': cap.kb_uid, 'text': '痛點寫得太籠統'}])
        self.assertTrue(res[0]['ok'])
        fb = self.env['corpaas.knowledge.exchange.promotion'].search([('type', '=', 'feedback')])
        self.assertEqual((fb.name, fb.note), ('報價', '痛點寫得太籠統'))


@tagged('post_install', '-at_install')
class TestReplicaSide(_Base):

    def setUp(self):
        super().setUp()
        self.icp.set_param('corpaas_knowledge.console_code', 'dobtor')
        self.mode('replica', 'lookup', 'ingest', 'feed')
        self.Peer.create({'name': 'corpaas', 'code': 'corpaas', 'role': 'master',
                          'url': 'https://admin.corpaas.com', 'key': 'k'})

    def test_prefetch_stores_master_answer_as_mirror(self):
        payload = {'kind': 'module_summary', 'kb_uid': 'u-ms', 'kb_origin': 'corpaas', 'module': 'sale_x',
                   'dir_hash': 'd1', 'source': 'ai', 'content': {'summary_json': '{"purpose": "主體讀的"}',
                                                                 'facts_json': '{}'}}
        with patch(POST, return_value={'results': [{'kind': 'module_summary', 'found': True, 'payload': payload}]}) as p:
            n = self.env['corpaas.knowledge.hooks']._knowledge_code_prefetch(modules=[('sale_x', 'd1')])
        self.assertTrue(n)
        self.assertEqual(p.call_args.args[0], 'https://admin.corpaas.com/corpaas/knowledge/exchange/v1/lookup')
        ms = self.env['corpaas.knowledge.module_summary'].search([('module', '=', 'sale_x')])
        self.assertEqual((ms.kb_sync_state, ms.source), ('mirror', 'ai'), '主體有 → 鏡像，本地不必再讀')
        with patch(POST) as p:
            self.Ex._prefetch(modules=[('sale_x', 'd1')])
        p.assert_not_called()

    def test_prefetch_master_down_is_silent(self):
        with patch(POST, side_effect=ConnectionError('down')):
            self.assertEqual(self.Ex._prefetch(defs=[('h', 'm', '(core)')]), 0, '主體停機：本地照算，不拋例外')

    def test_prefetch_respects_switch(self):
        self.mode('replica', 'ingest')
        with patch(POST) as p:
            self.Ex._prefetch(defs=[('h', 'm', '(core)')])
        p.assert_not_called()

    def test_collect_push_reply(self):
        pub, priv = self.make_def('(core)', 'r1'), self.make_def('x_cust', 'r2')
        self.assertEqual(self.Ex._collect(), 1, '只收公開的')
        self.assertEqual((pub.kb_sync_state, priv.kb_sync_state), ('pending', 'local'))
        Outbox = self.env['corpaas.knowledge.exchange.outbox']
        row = Outbox.search([('res_id', '=', pub.id), ('res_model', '=', pub._name)])
        with patch(POST, side_effect=ConnectionError('down')):
            self.Ex._push()
        self.assertEqual((row.state, row.attempts), ('error', 1))
        self.assertTrue(row.next_try, '失敗依退避重試')
        row.next_try = False
        with patch(POST, return_value={'results': [{'result': protocol.INGESTED}]}) as p:
            self.Ex._push()
        sent = p.call_args.args[1]['items']
        self.assertEqual([i['def_hash'] for i in sent], ['r1'])
        self.assertNotIn('x_cust', json.dumps(sent), '私有內容外送為 0')
        self.assertEqual((row.state, pub.kb_sync_state), ('ingested', 'sent'))

    def test_double_check_before_send(self):
        pub = self.make_def('(core)', 'r3')
        self.Ex._collect()
        self.env['corpaas.knowledge.exchange.visibility']._classify(pub)
        pub.write({'kb_visibility': 'private'})
        with patch(POST) as p:
            self.Ex._push()
        p.assert_not_called()
        row = self.env['corpaas.knowledge.exchange.outbox'].search([('res_id', '=', pub.id),
                                                                   ('res_model', '=', pub._name)])
        self.assertEqual(row.state, 'rejected', '送出前再檢查一次')

    def test_promotion_submit_and_feed_turns_local_into_mirror(self):
        cap = self.env['corpaas.knowledge.capability'].create({'name': '從屬能力'})
        self.assertEqual(self.Ex._submit_promotion(cap), 1)
        with patch(POST, return_value={'results': [{'result': protocol.REVIEW}]}):
            self.Ex._push()
        self.assertEqual(cap.kb_sync_state, 'sent')
        payload = dict(cap._kb_export(), kb_origin='dobtor')
        with patch(POST, return_value={'items': [{'op': 'upsert', 'payload': payload}], 'cursor': 7, 'more': False}):
            self.Ex._pull()
        self.assertEqual(cap.kb_sync_state, 'mirror', '主體核准後本地那筆改指上游，不留兩份')
        self.assertEqual(self.Ex._master_peer().feed_cursor, 7)
        self.assertEqual(len(self.env['corpaas.knowledge.capability'].search([('name', '=', '從屬能力')])), 1)

    def test_feed_retract_archives_mirror(self):
        rule = self.env['corpaas.knowledge.rule'].sudo()._kb_upsert({
            'kind': 'rule', 'kb_uid': 'u-rule', 'kb_origin': 'corpaas', 'source': 'human',
            'content': {'name': '關掉導覽', 'kind': 'hide_selector', 'track': 'check', 'value': '.o_tour'}})
        self.assertEqual(rule.kb_sync_state, 'mirror')
        with patch(POST, return_value={'items': [{'op': 'retract', 'kind': 'rule', 'kb_uid': 'u-rule'}],
                                       'cursor': 9, 'more': False}):
            self.Ex._pull()
        self.assertFalse(rule.active)


@tagged('post_install', '-at_install')
class TestExchangeHttp(HttpCase):

    def setUp(self):
        super().setUp()
        icp = self.env['ir.config_parameter'].sudo()
        icp.set_param('corpaas_knowledge.exchange_mode', 'master')
        icp.set_param('corpaas_knowledge.exchange_enable_lookup', 'True')
        self.env['corpaas.knowledge.exchange.peer'].sudo().create(
            {'name': 'dobtor', 'code': 'dobtor', 'role': 'replica', 'key': 'secret-k'})

    def _post(self, params, key='secret-k', peer='dobtor', ts=None, raw=None):
        body = raw or json.dumps({'jsonrpc': '2.0', 'method': 'call', 'params': params, 'id': 1},
                                 separators=(',', ':')).encode()
        ts = str(int(ts or time.time()))
        headers = {'Content-Type': 'application/json', 'X-KB-Peer': peer, 'X-KB-Timestamp': ts,
                   'X-KB-Signature': protocol.sign(key, ts, body)}
        res = self.url_open('/corpaas/knowledge/exchange/v1/lookup', data=body, headers=headers)
        return res.json().get('result') or {}, body, headers

    def test_auth(self):
        ok = {'items': [], 'schema_version': protocol.SCHEMA_VERSION, 'nonce': 'n-1'}
        res, body, headers = self._post(ok)
        self.assertTrue(res.get('ok'), res)
        replay = self.url_open('/corpaas/knowledge/exchange/v1/lookup', data=body, headers=headers).json()['result']
        self.assertEqual(replay.get('error'), 'replayed', '同一個請求重送一次就擋')
        self.assertEqual(self._post(dict(ok, nonce='n-2'), key='wrong')[0].get('error'), 'bad_signature')
        self.assertEqual(self._post(dict(ok, nonce='n-3'), peer='nobody')[0].get('error'), 'bad_signature',
                         '不分辨對端不存在與簽章錯')
        self.assertEqual(self._post(dict(ok, nonce='n-4'), ts=time.time() - 3600)[0].get('error'), 'bad_signature')
        self.assertEqual(self._post(dict(ok, nonce='n-5', schema_version=99))[0].get('error'), 'schema_mismatch',
                         '格式版本不一致拒收')
        self.env['ir.config_parameter'].sudo().set_param('corpaas_knowledge.exchange_enable_lookup', 'False')
        self.assertEqual(self._post(dict(ok, nonce='n-6'))[0].get('error'), 'disabled')


@tagged('post_install', '-at_install')
class TestOutputs(_Base):
    """主體方案產出：步驟區塊（只從主體流向從屬）、方案可用模組清單。"""

    def setUp(self):
        super().setUp()
        tmpl = self.env['product.template'].create({'name': '交換方案', 'type': 'service'})
        self.pkg = self.env['infrastructure.solution.package'].create({'product_tmpl_id': tmpl.id})
        self.feature = self.env['corpaas.knowledge.feature'].sudo().create({
            'feature_key': 'kbx.action:a1', 'module': 'kbx_mod', 'kind': 'action', 'anchor': 'kbx.a1',
            'name': '建立訂單', 'model': 'res.partner', 'package_ids': [(6, 0, self.pkg.ids)]})
        self.Block = self.env['corpaas.knowledge.step_block'].sudo()
        self.Vis = type(self.env['corpaas.knowledge.exchange.visibility'])

    def test_published_block_feeds_and_mirrors_as_published(self):
        self.mode('master', 'feed')
        peer = self.Peer.create({'name': 'd', 'code': 'dobtor', 'role': 'replica', 'key': 'k'})
        start = self.env['corpaas.knowledge.exchange.feed'].search([], order='id desc', limit=1).id
        blk = self.Block.create({'name': '建立訂單', 'feature_id': self.feature.id, 'fingerprint': 'fp1',
                                 'html': '<p>步驟</p>'})
        with patch.object(self.Vis, '_public_modules', lambda s, mods: set(mods)):
            self.env['corpaas.knowledge.exchange.visibility']._classify(blk)
            blk._do_publish('text')
        items = self.Ex._serve_feed(peer, start)['items']
        payload = [i['payload'] for i in items if i['op'] == 'upsert' and i['payload']['kind'] == 'step_block'][-1]
        self.assertEqual((payload['feature_key'], payload['content']['published_name']), ('kbx.action:a1', '建立訂單'))
        self.assertNotIn('html', payload['content'], '草稿與修訂不出主控台')
        # 從屬那邊：同一個功能點已有本地區塊（客戶文章可能引用）→ 不被改成鏡像，另建一筆
        self.mode('replica', 'feed')
        uid = payload['kb_uid']
        blk.unlink()
        local = self.Block.create({'name': '本地寫的', 'feature_id': self.feature.id, 'fingerprint': 'fp1'})
        m = self.Block._kb_upsert(payload)
        self.assertNotEqual(m, local, '本地區塊不被收編')
        self.assertEqual((m.kb_uid, m.kb_sync_state, m.state), (uid, 'mirror', 'published'))
        self.assertEqual(str(m._manual_live_source()[1]), '<p>步驟</p>', '前台用主體的上線版')
        self.assertEqual(self.Block._kb_upsert(payload), m, '冪等')

    def test_block_for_unknown_feature_is_skipped(self):
        payload = {'kind': 'step_block', 'kb_uid': 'u-b', 'feature_key': 'nope.action:x', 'fingerprint': 'f',
                   'content': {'published_name': 'x', 'published_html': '<p/>', 'fingerprint': 'f'}}
        with self.assertRaises(ValueError):
            self.Block._kb_upsert(payload)

    def test_master_refuses_block_ingest(self):
        self.mode('master', 'ingest')
        peer = self.Peer.create({'name': 'd', 'code': 'dobtor', 'role': 'replica', 'key': 'k'})
        res = self.Ex._serve_ingest(peer, [{'kind': 'step_block', 'kb_uid': 'x', 'feature_key': 'kbx.action:a1',
                                            'fingerprint': 'f', 'content': {}}])
        self.assertEqual((res[0]['result'], res[0]['reason']), (protocol.REJECTED, 'master_only'))

    def test_package_module_list_and_addon(self):
        self.mode('replica', 'feed')
        local = self.env['infrastructure.solution.package'].create({
            'product_tmpl_id': self.env['product.template'].create({'name': '從屬方案', 'type': 'service'}).id,
            'knowledge_upstream_key': 'corpaas:pkg14'})
        cap = self.env['corpaas.knowledge.capability'].create({
            'name': '會員', 'required_module_names': 'kbx_member\nkbx_wallet'})
        Pkg = type(local)
        with patch.object(Pkg, '_provision_module_names', lambda s: []):
            self.assertEqual(cap.availability_for(local)[0], 'missing')
            with patch(POST, return_value={'items': [{'op': 'upsert', 'payload': {
                    'kind': 'package', 'global_key': 'corpaas:pkg14', 'modules': ['kbx_member'],
                    'sellable': ['kbx_wallet']}}], 'cursor': 3, 'more': False}):
                self.Peer.create({'name': 'm', 'code': 'corpaas', 'role': 'master', 'url': 'https://m', 'key': 'k'})
                self.Ex._pull()
            self.assertIn('kbx_member', local._knowledge_available_modules())
            state, lacking = cap.availability_for(local)
            self.assertEqual((state, lacking), ('addon', {'kbx_wallet'}), '主體登記可販售 → 加購可得')

    def test_master_publishes_package_once_per_change(self):
        self.mode('master', 'feed')
        self.pkg.knowledge_enabled = True
        Pkg = type(self.pkg)
        with patch.object(Pkg, '_knowledge_available_modules', lambda s: {'sale'}):
            first = self.pkg._kb_publish_packages()
            again = self.pkg._kb_publish_packages()
        self.assertGreaterEqual(first, 1)
        self.assertEqual(again, 0, '沒變就不再發佈')
