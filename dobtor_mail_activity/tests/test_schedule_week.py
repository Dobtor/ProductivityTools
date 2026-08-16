# -*- coding: utf-8 -*-

from datetime import date, timedelta

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestScheduleWeekDomain(TransactionCase):
    """週次篩選：日期區間 domain 必須與 stored compute 等價，且不依賴 cron。

    schedule_week / schedule_week_number 是「相對今天」的 stored compute，會隨
    時間腐化。篩選改走 _week_date_domain 之後，即使 stored 值是錯的，查詢結果
    仍必須正確 —— 這組測試就是釘死這件事。
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Activity = cls.env['mail.activity']
        cls.activity_type = cls.env['mail.activity.type'].create({
            'name': 'Week Test Type', 'category': 'default',
        })
        cls.note = cls.env['note.note'].create({'memo': '<p>week</p>'})
        cls.note_model_id = cls.env['ir.model']._get('note.note').id
        today = date.today()
        cls.week_start = today - timedelta(days=today.weekday())

    def _make(self, summary, planned=None, scheduled=None, status='monday'):
        return self.Activity.create({
            'summary': summary,
            'activity_type_id': self.activity_type.id,
            'res_model_id': self.note_model_id,
            'res_id': self.note.id,
            'date_deadline': date.today() + timedelta(days=30),
            'user_id': self.env.user.id,
            'planned_date': planned,
            'scheduled_date': scheduled,
            'schedule_status': status,
        })

    def _in_week(self, activity, week_number):
        domain = self.Activity._week_date_domain(week_number)
        return bool(self.Activity.with_context(active_test=False).search_count(
            domain + [('id', '=', activity.id)]))

    def test_01_domain_matches_compute_for_planned_date(self):
        """對每個週次偏移，domain 的判定必須等於 compute 出來的 week number。"""
        for offset_weeks in (-3, -1, 0, 1, 2, 3):
            planned = self.week_start + timedelta(days=7 * offset_weeks + 2)
            act = self._make('w%s' % offset_weeks, planned=planned)
            # compute 端把「更早於上週」夾鉗成 -1
            expected = max(offset_weeks, -1)
            self.assertEqual(act.schedule_week_number, expected)
            for week_number in (-1, 0, 1, 2, 3):
                self.assertEqual(
                    self._in_week(act, week_number),
                    expected == week_number,
                    'planned=%s 對 week=%s 的 domain 判定與 compute 不符'
                    % (planned, week_number),
                )

    def test_02_falls_back_to_scheduled_date(self):
        """判斷依據是 planned_date or scheduled_date（COALESCE）。"""
        scheduled = self.week_start + timedelta(days=7 + 1)   # 下週
        act = self._make('sched only', planned=False, scheduled=scheduled)
        self.assertEqual(act.schedule_week_number, 1)
        self.assertTrue(self._in_week(act, 1))
        self.assertFalse(self._in_week(act, 0))

    def test_03_planned_wins_over_scheduled(self):
        act = self._make(
            'both',
            planned=self.week_start + timedelta(days=1),          # 本週
            scheduled=self.week_start + timedelta(days=14),       # 第三週
        )
        self.assertTrue(self._in_week(act, 0))
        self.assertFalse(self._in_week(act, 2))

    def test_04_no_date_matches_no_week(self):
        act = self._make('no date', planned=False, scheduled=False, status='waiting')
        self.assertEqual(act.schedule_week_number, -999)
        for week_number in (-1, 0, 1, 2, 3):
            self.assertFalse(self._in_week(act, week_number))

    def test_05_domain_survives_stale_stored_value(self):
        """關鍵：即使 stored 值被弄髒（模擬 cron 失效），篩選仍必須正確。"""
        planned = self.week_start + timedelta(days=2)   # 本週
        act = self._make('stale', planned=planned)
        self.env.cr.execute(
            'UPDATE mail_activity SET schedule_week_number = %s WHERE id = %s',
            (99, act.id))
        act.invalidate_recordset(['schedule_week_number'])
        self.assertEqual(act.schedule_week_number, 99, '前置：stored 值已被弄髒')
        self.assertTrue(self._in_week(act, 0), '日期區間 domain 不應受 stored 值影響')

    def test_06_cron_repairs_only_stale_rows(self):
        planned = self.week_start + timedelta(days=2)
        act = self._make('to repair', planned=planned)
        self.env.cr.execute(
            'UPDATE mail_activity SET schedule_week_number = %s WHERE id = %s',
            (99, act.id))
        act.invalidate_recordset(['schedule_week_number'])

        self.Activity._cron_refresh_schedule_week()
        act.invalidate_recordset(['schedule_week_number', 'schedule_week'])
        self.assertEqual(act.schedule_week_number, 0, 'cron 應修回正確值')
        self.assertEqual(act.schedule_week, 'week0')

    def test_07_week_descriptors_shape(self):
        descriptors = self.Activity.get_week_bounds()
        numbers = [d['number'] for d in descriptors]
        self.assertEqual(numbers, [-1, 0, 1, 'all'])
        for descriptor in descriptors:
            self.assertIn('domain', descriptor)
            self.assertIn('dates', descriptor)
        self.assertEqual(descriptors[-1]['domain'], [],
                         '「全部」不應帶任何週次條件')
        # 每週的 domain 都要放行 waiting（待排程在每一週都看得到）
        for descriptor in descriptors[:-1]:
            self.assertIn(('schedule_status', '=', 'waiting'), descriptor['domain'])

    def test_08_get_week_info_counts_match_filter(self):
        """選單上的數字必須等於「套用該週 domain（排除 waiting）」的實際筆數。"""
        base = [('activity_type_id', '=', self.activity_type.id)]
        self._make('this week a', planned=self.week_start + timedelta(days=1))
        self._make('this week b', planned=self.week_start + timedelta(days=3))
        self._make('next week', planned=self.week_start + timedelta(days=8))
        self._make('waiting', planned=False, scheduled=False, status='waiting')

        weeks = {w['number']: w for w in self.Activity.get_week_info(domain=base)}
        self.assertEqual(weeks[0]['count'], 2)
        self.assertEqual(weeks[1]['count'], 1)
        self.assertEqual(weeks['all']['count'], 4, '「全部」含 waiting 與無日期')
