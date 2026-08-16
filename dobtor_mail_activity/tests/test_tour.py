# -*- coding: utf-8 -*-

from datetime import date, timedelta

from odoo.tests.common import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestActivityTours(HttpCase):
    """前端端到端測試。

    週次選擇器與搜尋 facet 的共存只存在於前端資料流（SearchModel → props.domain
    → model.load），Python 測不到，只能靠 tour。
    """

    def test_week_selector_and_facet_coexist(self):
        activity_type = self.env['mail.activity.type'].create({
            'name': 'Tour Type', 'category': 'default',
        })
        note = self.env['note.note'].create({'memo': '<p>tour</p>'})
        note_model_id = self.env['ir.model']._get('note.note').id
        admin = self.env.ref('base.user_admin')

        today = date.today()
        week_start = today - timedelta(days=today.weekday())

        # 本週與下週各備一筆緊急待辦，確保切週次與勾 Urgent 都有東西可顯示
        for offset, status in ((1, 'tuesday'), (8, 'tuesday')):
            self.env['mail.activity'].create({
                'summary': 'Tour activity +%d' % offset,
                'activity_type_id': activity_type.id,
                'res_model_id': note_model_id,
                'res_id': note.id,
                'user_id': admin.id,
                'date_deadline': today + timedelta(days=30),
                'planned_date': week_start + timedelta(days=offset),
                'schedule_status': status,
                'urgency': 'urgent',
            })

        self.start_tour('/odoo', 'dobtor_activity_week_selector_tour', login='admin')

    def test_chip_redirects_to_master_after_merge(self):
        """合併後，筆記內文的膠囊必須顯示／指向主待辦。

        HTML 裡仍是被併入者的舊 id —— 轉向發生在讀取時（get_chip_data），
        所以這條必須用瀏覽器跑，Python 只測得到後端那一層。
        """
        activity_type = self.env['mail.activity.type'].create({
            'name': 'Chip Tour Type', 'category': 'default',
        })
        admin = self.env.ref('base.user_admin')
        note = self.env['note.note'].create({
            'memo': '<p>Chip merge tour note</p>',
            'user_id': admin.id,
        })
        note_model_id = self.env['ir.model']._get('note.note').id

        def _make(summary):
            return self.env['mail.activity'].create({
                'summary': summary,
                'activity_type_id': activity_type.id,
                'res_model_id': note_model_id,
                'res_id': note.id,
                'user_id': admin.id,
                'date_deadline': date.today() + timedelta(days=7),
                'note_id': note.id,
            })

        master = _make('Chip tour master')
        source = _make('Chip tour source')

        # 膠囊先指向「將被併入」的那一筆，且刻意**不**讓 _rewrite_note_chips 改到它：
        # 放在 memo 內、但把 note 從 source 的引用移除後再合併，模擬「改寫涵蓋不到」
        # 的情境（例如膠囊被貼到其他 html 欄位）→ 正確性應由讀取時轉向保證。
        note.memo = (
            '<p>Chip merge tour note</p>'
            '<p>see <span data-embedded-props=\'{"activityId": %d}\' '
            'data-embedded="activityChip" data-oe-protected="true" '
            'contenteditable="false" class="o_dobtor_activity_chip_host"></span></p>'
            % source.id
        )
        source.note_ids = [(5, 0, 0)]
        source.note_id = False

        (master | source).action_merge(master)
        self.assertEqual(source.merged_into_id, master, '前置：合併已成立')

        self.start_tour('/odoo', 'dobtor_activity_chip_merge_tour', login='admin')
