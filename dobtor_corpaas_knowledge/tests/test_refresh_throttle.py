# -*- coding: utf-8 -*-
"""自動更新不零散：變動驅動的觸發合併等待 30 分鐘、24 小時內最多 2 次；手動與製作流程不受限。"""
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged

from .test_usage_flow import make_database


@tagged('post_install', '-at_install')
class TestRefreshThrottle(TransactionCase):

    def setUp(self):
        super().setUp()
        tmpl = self.env['product.template'].create({'name': '節流方案', 'type': 'service'})
        self.pkg = self.env['infrastructure.solution.package'].create({'product_tmpl_id': tmpl.id,
                                                                       'knowledge_enabled': True})
        inst = make_database(self.env, 9511).instance_id
        p = patch.object(type(self.pkg), '_knowledge_master', lambda s, raise_if_missing=True: inst)
        p.start()
        self.addCleanup(p.stop)
        self.Q = self.env['corpaas.queue'].sudo()

    def _job(self):
        return self.Q.search([('operate', '=', 'knowledge_refresh'), ('reference_id', '=', self.pkg.id),
                              ('state', '=', 'pending')])

    def test_quiet_window_merges_bursts(self):
        now = fields.Datetime.now()
        self.pkg.knowledge_enqueue_refresh(reason='modules')
        q = self._job()
        self.assertEqual(len(q), 1)
        self.assertGreaterEqual(q.q_datetime, now + timedelta(minutes=29), '等安靜 30 分鐘才跑')
        first = q.q_datetime
        with patch.object(fields.Datetime, 'now', lambda *a: now + timedelta(minutes=10)):
            self.pkg.knowledge_enqueue_refresh(reason='code')
        self.assertEqual(len(self._job()), 1, '連續變動只有一張')
        self.assertGreater(self._job().q_datetime, first, '每次變動把開跑時間往後推')

    def test_workflow_runs_now_and_absorbs_pending_changes(self):
        self.pkg.knowledge_enqueue_refresh(reason='modules')
        self.pkg.knowledge_enqueue_refresh(reason='manual')
        q = self._job()
        self.assertEqual(len(q), 1)
        self.assertFalse(q.q_datetime, '手動不等，等待中的變動一起跑')
        self.pkg.knowledge_enqueue_refresh(reason='image')
        self.assertFalse(self._job().q_datetime, '已經有流程要的那張在等：變動併進去，不把它往後推')
        self.assertEqual(self.pkg.knowledge_pending_reason, 'manual', '原因保留流程那張')

    def test_daily_cap(self):
        Run = self.env['corpaas.knowledge.run'].sudo()
        r1 = Run.create({'package_id': self.pkg.id, 'token': 't1', 'reason': 'modules'})
        Run.create({'package_id': self.pkg.id, 'token': 't2', 'reason': 'image'})
        Run.create({'package_id': self.pkg.id, 'token': 't3', 'reason': 'manual'})
        self.pkg.knowledge_enqueue_refresh(reason='modules')
        self.assertGreaterEqual(self._job().q_datetime, r1.create_date + timedelta(hours=24) - timedelta(seconds=1),
                                '24 小時內自動跑滿 2 次：順延到最早那次滿 24 小時（手動那次不算）')
        self._job().state = 'cancel'
        self.pkg.knowledge_enqueue_refresh(reason='manual')
        self.assertFalse(self._job().q_datetime, '手動不受上限')

    def test_seed_approval_reshoots_only_that_scenario(self):
        sc = self.env['corpaas.knowledge.scenario'].create({'name': '情境甲', 'code': 'kbthr_a',
                                                            'package_ids': [(4, self.pkg.id)]})
        sc._knowledge_refresh_packages()
        self.assertIn(sc, self.pkg.knowledge_pending_scenario_ids, '記下要重拍的情境')
        self.assertFalse(self.pkg.knowledge_pending_full, '不整個方案全量')
        self.assertEqual(len(self._job()), 1)
