# -*- coding: utf-8 -*-
"""K18 使用量實測換算、K15 租戶轉換證據。需要 dobtor_database_activity_stats（沒裝就略過）。"""
from datetime import date
from unittest.mock import patch

from odoo import Command
from odoo.tests import TransactionCase, tagged


def make_database(env, number=9401):
    branch = env['infrastructure.repository_branch'].create({'name': 'kbu-%s' % number})
    ver = env['infrastructure.odoo_version'].create({
        'name': '18.0', 'sufix': '18', 'default_branch_id': branch.id,
        'custom_module_version': [Command.set([branch.id])],
        'odoo_module_version': [Command.set([branch.id])]})
    img = env['infrastructure.docker_image'].create({
        'name': 'KBU Odoo', 'pull_name': 'odoo:18.0', 'service': 'odoo',
        'odoo_version_id': ver.id})
    tag = env['infrastructure.docker_image.tag'].create({'name': '18.0',
                                                        'docker_image_id': img.id})
    pg = env['infrastructure.docker_image'].create({
        'name': 'KBU PG', 'pull_name': 'postgres:16', 'service': 'postgresql',
        'odoo_image_ids': [Command.set([img.id])]})
    pg_tag = env['infrastructure.docker_image.tag'].create({'name': '16',
                                                           'docker_image_id': pg.id})
    partner = env['res.partner'].create({'name': 'KBU Partner'})
    server = env['infrastructure.server'].create({
        'name': 'kbu-server-%s' % number, 'main_hostname': 'kbu%s.example.com' % number,
        'user_name': 'odoo',
        'server_configuration_id': env['infrastructure.server_configuration'].create({
            'name': 'KBU Config', 'distrib_codename': 'ubuntu'}).id,
        'holder_id': partner.id, 'owner_id': partner.id})
    environment = env['infrastructure.environment'].create({
        'number': number, 'name': 'kbu-env-%s' % number, 'partner_id': partner.id,
        'odoo_version_id': ver.id, 'server_id': server.id})
    inst = env['infrastructure.instance'].create({
        'number': number, 'sufix': 'kbu', 'environment_id': environment.id,
        'database_type_id': env['infrastructure.database_type'].create({
            'name': 'KBU Prod', 'prefix': 'kbu', 'sources_type': 'own'}).id,
        'db_filter': env['infrastructure.db_filter'].create({
            'name': 'KBU Filter', 'rule': '^%d$'}).id,
        'odoo_image_id': img.id, 'odoo_image_tag_id': tag.id,
        'pg_image_id': pg.id, 'pg_image_tag_id': pg_tag.id,
        'docker_ip_sequence': number})
    return env['infrastructure.database'].create({
        'name': 'kbu_db_%s' % number, 'partner_id': partner.id, 'instance_id': inst.id})


@tagged('post_install', '-at_install')
class TestUsageAndFlowEvidence(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ready = 'database.activity.usage' in cls.env
        if not cls.ready:
            return
        cls.db = make_database(cls.env)
        cls.pkg = cls.env['infrastructure.solution.package'].create({
            'product_tmpl_id': cls.env['product.template'].create(
                {'name': 'KBU 方案', 'type': 'service'}).id})
        F = cls.env['corpaas.knowledge.feature']
        cls.f_screen = F.create({
            'feature_key': 'base.action:base.action_res_users', 'module': 'base',
            'kind': 'action', 'anchor': 'base.action_res_users', 'name': '使用者',
            'model': 'res.users', 'action_xmlid': 'base.action_res_users',
            'package_ids': [(4, cls.pkg.id)]})
        cls.f_btn = F.create({
            'feature_key': 'base.button:v/button[action_x]', 'module': 'base',
            'kind': 'button', 'anchor': 'v/button[action_x]', 'name': 'X',
            'model': 'res.users', 'button_name': 'action_x',
            'package_ids': [(4, cls.pkg.id)]})
        cls.f_other = F.create({
            'feature_key': 'base.button:v/button[action_y]', 'module': 'base',
            'kind': 'button', 'anchor': 'v/button[action_y]', 'name': 'Y',
            'model': 'res.users', 'button_name': 'action_y',
            'package_ids': [(4, cls.pkg.id)]})

    def setUp(self):
        super().setUp()
        if not self.ready:
            self.skipTest('沒有安裝 dobtor_database_activity_stats')
        p = patch.object(type(self.pkg), '_knowledge_tenant_databases', lambda s: self.db)
        p.start()
        self.addCleanup(p.stop)

    def test_measured_usage_beats_model_level(self):
        U = self.env['database.activity.usage']
        today = date.today()
        U.create({'database_id': self.db.id, 'day': today, 'kind': 'action',
                  'model': 'res.users', 'name': 'base.action_res_users', 'count': 40})
        U.create({'database_id': self.db.id, 'day': today, 'kind': 'button',
                  'model': 'res.users', 'name': 'action_x', 'count': 5})
        self.pkg._knowledge_update_usage(self.f_screen | self.f_btn | self.f_other)
        self.assertEqual((self.f_screen.usage_score, self.f_screen.usage_source),
                         (40, 'measured'))
        self.assertEqual((self.f_btn.usage_score, self.f_btn.usage_source), (5, 'measured'))
        self.assertEqual(self.f_other.usage_source, 'model', '沒有實測就退回模型層級')

    def test_tenant_transitions_confirm_and_add_edges(self):
        flow = self.env['corpaas.knowledge.flow'].create(
            {'model': 'res.users', 'state_field': 'state'})
        T = self.env['corpaas.knowledge.flow.transition']
        static = T.create({'flow_id': flow.id, 'from_value': 'new', 'to_value': 'active',
                           'button_name': 'action_y', 'button_feature_id': self.f_other.id,
                           'ev_static': True})
        today = date.today()
        Tr = self.env['database.activity.transition']
        Tr.create({'database_id': self.db.id, 'day': today, 'model': 'res.users',
                   'field': 'state', 'from_value': 'new', 'to_value': 'active', 'count': 12})
        Tr.create({'database_id': self.db.id, 'day': today, 'model': 'res.users',
                   'field': 'state', 'from_value': 'active', 'to_value': 'new', 'count': 3})
        self.pkg._knowledge_flow_tenant(flow)
        self.assertTrue(static.ev_tenant)
        self.assertEqual(static.usage_count, 12)
        self.assertEqual((self.f_other.usage_score, self.f_other.usage_source),
                         (12, 'estimated'), '按鈕沒有實測：用轉換次數推估')
        extra = flow.transition_ids.filtered(lambda t: t.from_value == 'active')
        self.assertTrue(extra.ev_tenant and not extra.ev_static,
                        '靜態推不出來、但租戶確實發生的轉換要補上')
