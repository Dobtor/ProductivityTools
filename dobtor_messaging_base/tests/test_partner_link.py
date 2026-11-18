# -*- coding: utf-8 -*-
"""綁定精靈 messaging.partner.link：Odoo 18 禁止改寫 discuss.channel.member.partner_id，
來源聯絡人只要是任何對話成員，舊寫法就必定「您不能在 partner_id 上書寫」。"""
from unittest.mock import patch

from odoo import Command
from odoo.tests.common import TransactionCase, new_test_user, tagged

from odoo.addons.dobtor_messaging_base.models.messaging_account import MessagingAccount


@tagged('post_install', '-at_install')
class TestMessagingPartnerLink(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # 基礎模組本身沒有 provider，測試期間掛一個假的
        cls.startClassPatcher(patch.object(
            MessagingAccount, '_selection_messaging_provider',
            lambda self: [('fake', 'Fake')], create=False))
        cls.source = cls.env['res.partner'].create({'name': 'External U1'})
        cls.target = cls.env['res.partner'].create({'name': 'Customer Co', 'is_company': True})
        cls.account = cls.env['messaging.account'].create({
            'partner_id': cls.source.id, 'provider': 'fake', 'external_user_id': 'U1'})
        cls.staff = cls.env.user.partner_id
        cls.channel = cls.env['discuss.channel'].create({
            'name': 'External U1',
            'channel_type': 'group',
            'channel_member_ids': [
                Command.create({'partner_id': cls.source.id, 'fold_state': 'open'}),
                Command.create({'partner_id': cls.staff.id}),
            ],
        })
        cls.message = cls.channel.message_post(
            body='hello', author_id=cls.source.id, message_type='comment')

    def _link(self, **vals):
        wizard = self.env['messaging.partner.link'].create(dict({
            'source_partner_id': self.source.id,
            'target_partner_id': self.target.id,
        }, **vals))
        return wizard.action_link_partner()

    def test_link_source_in_conversation(self):
        self._link()
        members = self.channel.channel_member_ids
        self.assertIn(self.target, members.partner_id)
        self.assertNotIn(self.source, members.partner_id)
        self.assertEqual(members.filtered(lambda m: m.partner_id == self.target).fold_state, 'open',
                         '成員個人狀態要跟著帶過去')
        self.assertEqual(self.account.partner_id, self.target)
        self.assertEqual(self.message.author_id, self.target)
        self.assertFalse(self.source.active)

    def test_link_target_already_member(self):
        self.channel.channel_member_ids = [Command.create({'partner_id': self.target.id})]
        self._link(archive_source=False)
        members = self.channel.channel_member_ids.filtered(lambda m: m.partner_id == self.target)
        self.assertEqual(len(members), 1)
        self.assertFalse(self.source.exists())

    def test_link_one_to_one_chat(self):
        chat = self.env['discuss.channel'].create({
            'name': 'chat',
            'channel_type': 'chat',
            'channel_member_ids': [
                Command.create({'partner_id': self.source.id}),
                Command.create({'partner_id': self.staff.id}),
            ],
        })
        self._link()
        self.assertEqual(chat.channel_member_ids.partner_id, self.target | self.staff)

    def test_admin_gets_messaging_manager(self):
        self.assertTrue(self.env.ref('base.user_admin').has_group(
            'dobtor_messaging_base.group_messaging_manager'))
        user = new_test_user(self.env, login='msg_erp_mgr',
                             groups='base.group_user,base.group_erp_manager')
        self.assertTrue(user.has_group('dobtor_messaging_base.group_messaging_manager'))
