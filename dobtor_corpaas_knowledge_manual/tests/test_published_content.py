# -*- coding: utf-8 -*-
"""#15：步驟區塊的已發佈內容實體欄位——上線時寫入、前台用它、上線後再改不影響前台。"""
from odoo.tests import tagged

from .common import ManualCase


@tagged('post_install', '-at_install')
class TestPublishedContent(ManualCase):

    def test_publish_fills_fields_and_live_source_uses_them(self):
        blk = self.Block.create({'name': '建立報名', 'feature_id': self.f1.id, 'html': '<p>第一版</p>'})
        self.assertEqual(blk._manual_live_source(), ('建立報名', ''), '沒上線過前台是空的')
        blk._do_publish('text')
        self.assertEqual((blk.published_name, str(blk.published_html)), ('建立報名', '<p>第一版</p>'))
        blk.write({'name': '建立報名（改）', 'html': '<p>第二版草稿</p>'})
        name, html = blk._manual_live_source()
        self.assertEqual((name, str(html)), ('建立報名', '<p>第一版</p>'), '沒審過的修改不上前台')
        blk._do_publish('text')
        self.assertEqual(str(blk._manual_live_source()[1]), '<p>第二版草稿</p>')

    def test_backfill_from_snapshot(self):
        blk = self.Block.create({'name': '收款', 'feature_id': self.f3.id, 'html': '<p>上線版</p>'})
        blk._do_publish('text')
        blk.write({'html': '<p>之後改的</p>'})
        self.env.cr.execute('UPDATE corpaas_knowledge_step_block SET published_name=NULL, published_html=NULL '
                            'WHERE id=%s', (blk.id,))
        blk.invalidate_recordset()
        self.Block.init()
        blk.invalidate_recordset()
        self.assertEqual(str(blk.published_html), '<p>上線版</p>', '回填取上線快照，不取之後的修改')
