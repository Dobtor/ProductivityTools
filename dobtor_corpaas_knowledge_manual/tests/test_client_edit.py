# -*- coding: utf-8 -*-
from odoo.tests.common import HttpCase, JsonRpcException, new_test_user, tagged

from .common import ManualCase, png


@tagged('post_install', '-at_install')
class TestClientEdit(ManualCase, HttpCase):
    """編輯者從網頁表單直接改已上線的文章／步驟區塊：沒審過的文字絕不上前台。"""

    def _save(self, rec, vals):
        return self.make_jsonrpc_request(
            '/web/dataset/call_kw/%s/web_save' % rec._name,
            {'model': rec._name, 'method': 'web_save', 'args': [rec.ids, vals],
             'kwargs': {'specification': {'state': {}}}})

    def test_client_edit_never_rides_a_reshoot(self):
        new_test_user(self.env, 'kb_manual_editor',
                      groups='base.group_user,dobtor_corpaas_knowledge.group_knowledge_editor')
        other = self.env['corpaas.knowledge.scenario'].sudo().create(
            {'name': '學會研討會', 'code': 'kbtest_conf', 'package_ids': [(6, 0, self.pkg.ids)]})
        art = self._article(self.f1, self.cap_a)
        blk = art.step_block_ids
        art2 = self._article(self.f1, self.cap_a, scenario=other, block=blk)
        self._publish(art, art2)
        slide, slide2 = art.placement_ids.slide_id, art2.placement_ids.slide_id
        self.assertIn('按下按鈕', slide2.html_content)

        self.authenticate('kb_manual_editor', 'kb_manual_editor')
        self._save(art, {'name': 'UNREVIEWED TITLE',
                         'scenario_html': '<p>UNREVIEWED ARTICLE</p>'})
        self._save(blk, {'html': '<h4>開啟</h4><p>UNREVIEWED BLOCK</p><p>[[shot:main]]</p>'})
        with self.assertRaises(JsonRpcException):
            self._save(art, {'state': 'published'})
        (art | art2).invalidate_recordset()
        blk.invalidate_recordset()
        self.assertEqual(art.state, 'draft', '改了上線文章的文字 → 退回草稿')
        self.assertEqual(blk.state, 'draft')
        self.assertEqual(art2.state, 'published', '只改了共用區塊的文章本身不動')

        # 另一篇（只共用區塊）重拍上線：區塊用上線快照
        art2.asset_ids = self._asset(self.f1, data=png(stripes=5))
        art2.knowledge_reshoot_done()
        self.assertEqual(art2.state, 'published')
        slide2.invalidate_recordset()
        self.assertIn('/web/image/', slide2.html_content, '新圖要上去')
        self.assertIn('按下按鈕', slide2.html_content)
        self.assertNotIn('UNREVIEWED BLOCK', slide2.html_content)

        # 草稿中的文章被重推（重試、補掛 channel）：推的仍是上線版
        art.sudo()._manual_push()
        slide.invalidate_recordset()
        for text in ('UNREVIEWED TITLE', 'UNREVIEWED ARTICLE', 'UNREVIEWED BLOCK'):
            self.assertNotIn(text, slide.html_content + (slide.name or ''))
        self.assertIn('會員報名前要先建立年會', slide.html_content)

        # 伺服端流程改了文字、沒退回草稿：純重拍也要送審，不能順手發佈
        art2.write({'scenario_html': '<p>SERVER EDIT</p>'})
        art2.knowledge_mark_stale('畫面改版')
        art2.knowledge_reshoot_done()
        self.assertEqual(art2.state, 'review')
        slide2.invalidate_recordset()
        self.assertNotIn('SERVER EDIT', slide2.html_content)

        # 核准後才上線
        blk.knowledge_propose('text')
        blk.with_user(self.approver).action_approve()
        slide2.invalidate_recordset()
        self.assertIn('UNREVIEWED BLOCK', slide2.html_content, '核准的區塊跟著上線')
        self.assertNotIn('SERVER EDIT', slide2.html_content)
