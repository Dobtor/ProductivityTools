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
        note = self.env['res.partner'].create({'name': 'Tour target'})
        note_model_id = self.env['ir.model']._get('res.partner').id
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
