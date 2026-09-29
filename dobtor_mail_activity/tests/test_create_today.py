# -*- coding: utf-8 -*-
"""「無法建立當天的待辦」回歸測試。

正式機的 Odoo 18.0 早於官方 commit bc0e1275be（2025-06-25），其
mail.activity.create 結尾引用只在「有關聯文件＋有指派人」時才綁定的迴圈變數
`activity`；獨立待辦（無關聯文件）＋有指派人＋截止日 <= 今天 → UnboundLocalError。

本機/CI 的核心可能已是修正版，直接建立不會重現，所以這裡把官方 create 換成
舊版原文（逐字複製自 odoo/odoo@25a3161615），讓測試不論核心版本都能釘住。
"""

from collections import defaultdict
from datetime import timedelta
from unittest.mock import patch

from odoo import api, fields
from odoo.addons.mail.models.mail_activity import MailActivity as CoreMailActivity
from odoo.tests.common import TransactionCase, tagged


@api.model_create_multi
def _pre_bc0e1275_create(self, vals_list):
    """odoo/odoo@25a3161615 addons/mail/models/mail_activity.py create()（原文）"""
    activities = super(CoreMailActivity, self).create(vals_list)

    if any(user != self.env.user for user in activities.user_id):
        user_partners = activities.user_id.partner_id
        readable_user_partners = user_partners._filtered_access('read')
    else:
        readable_user_partners = self.env.user.partner_id

    if self.env.context.get('mail_activity_quick_update'):
        activities_to_notify = self.env['mail.activity']
    else:
        activities_to_notify = activities.filtered(lambda act: act.user_id != self.env.user)
    if activities_to_notify:
        to_sudo = activities_to_notify.filtered(lambda act: act.user_id.partner_id not in readable_user_partners)
        other = activities_to_notify - to_sudo
        to_sudo.sudo().action_notify()
        other.action_notify()

    for model, activity_data in activities._classify_by_model().items():
        per_user = defaultdict(list)
        for activity in activity_data['activities'].filtered(lambda act: act.user_id):
            if activity.res_id not in per_user[activity.user_id]:
                per_user[activity.user_id].append(activity.res_id)
        for user, res_ids in per_user.items():
            pids = user.partner_id.ids if user.partner_id in readable_user_partners else user.sudo().partner_id.ids
            self.env[model].browse(res_ids).message_subscribe(partner_ids=pids)

    todo_activities = activities.filtered(lambda act: act.date_deadline <= fields.Date.today())
    if todo_activities:
        activity.user_id._bus_send("mail.activity/updated", {"activity_created": True})  # noqa: F821
    return activities


@tagged('post_install', '-at_install')
class TestCreateTodayActivity(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = cls.env['res.users'].create({
            'name': 'Today Tester', 'login': 'today_tester',
            'groups_id': [(6, 0, [cls.env.ref('base.group_user').id])],
        })
        cls.other = cls.env['res.users'].create({
            'name': 'Today Other', 'login': 'today_other',
            'groups_id': [(6, 0, [cls.env.ref('base.group_user').id])],
        })

    def setUp(self):
        super().setUp()
        # 模擬正式機的舊版核心
        patcher = patch.object(CoreMailActivity, 'create', _pre_bc0e1275_create)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _wizard_create(self, deadline, assignee):
        env = self.env(user=self.user)
        wiz = env['mail.activity.create.wizard'].create({
            'summary': 'today repro',
            'date_deadline': deadline,
            'activity_user_id': assignee.id if assignee else False,
        })
        return wiz.action_create_todo()['infos']['activity_id']

    def test_01_wizard_standalone_today(self):
        """看板/清單/系統匣「新增」不選目標文件、截止日今天 → 必須建得起來"""
        today = fields.Date.context_today(self.env['mail.activity'])
        for deadline in (today, today - timedelta(days=1), today + timedelta(days=1)):
            for assignee in (self.user, self.other, None):
                with self.subTest(deadline=deadline, assignee=assignee and assignee.login):
                    act_id = self._wizard_create(deadline, assignee)
                    act = self.env['mail.activity'].browse(act_id)
                    self.assertTrue(act.exists())
                    self.assertEqual(act.date_deadline, deadline)
                    self.assertFalse(act.res_model)

    def test_02_direct_create_default_user_today(self):
        """user_id 由 context default_user_id 帶入（有/無關聯文件）也要能建立"""
        partner = self.env['res.partner'].create({'name': 'Ctx default'})
        Act = self.env['mail.activity'].with_context(default_user_id=self.user.id)
        standalone = Act.create({
            'summary': 'ctx default', 'date_deadline': fields.Date.today(),
        })
        self.assertEqual(standalone.user_id, self.user)
        linked = Act.create({
            'summary': 'ctx default linked', 'date_deadline': fields.Date.today(),
            'res_model_id': self.env['ir.model']._get_id('res.partner'),
            'res_id': partner.id,
        })
        self.assertEqual(linked.user_id, self.user)
        # 有文件、未指派 → 官方迴圈綁不到，也必須走繞道
        unassigned = self.env['mail.activity'].create({
            'summary': 'linked unassigned', 'date_deadline': fields.Date.today(),
            'res_model_id': self.env['ir.model']._get_id('res.partner'),
            'res_id': partner.id,
        })
        self.assertFalse(unassigned.user_id)

    def test_03_bypass_still_updates_systray(self):
        """繞道路徑要補送系統匣 bus 計數（今天到期者），明天到期者不送"""
        today = fields.Date.today()
        sent = []
        orig = type(self.env['res.users'])._bus_send

        def spy(users, notification_type, message, *a, **kw):
            sent.append((users.ids, notification_type, message))
            return orig(users, notification_type, message, *a, **kw)

        with patch.object(type(self.env['res.users']), '_bus_send', spy):
            self.env['mail.activity'].create([
                {'summary': 'a', 'date_deadline': today, 'user_id': self.user.id},
                {'summary': 'b', 'date_deadline': today, 'user_id': self.user.id},
                {'summary': 'c', 'date_deadline': today + timedelta(days=1),
                 'user_id': self.other.id},
                {'summary': 'd', 'date_deadline': today, 'user_id': False},
            ])
        updates = [s for s in sent if s[1] == 'mail.activity/updated']
        self.assertEqual(updates, [(
            [self.user.id], 'mail.activity/updated',
            {'activity_created': True, 'count_diff': 2})])

    def test_04_linked_activity_uses_core_path(self):
        """有關聯文件＋指派人 → 仍走官方路徑（通知/訂閱照常）"""
        partner = self.env['res.partner'].create({'name': 'Linked'})
        act = self.env['mail.activity'].create({
            'summary': 'linked', 'date_deadline': fields.Date.today(),
            'res_model_id': self.env['ir.model']._get_id('res.partner'),
            'res_id': partner.id, 'user_id': self.other.id,
        })
        self.assertIn(self.other.partner_id, partner.message_partner_ids)
        self.assertEqual(act.res_model, 'res.partner')
