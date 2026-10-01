# -*- coding: utf-8 -*-
import io
import json

from PIL import Image

from odoo.tests.common import TransactionCase, new_test_user


def png(color=(255, 255, 255), size=(200, 100), box=None, stripes=0):
    img = Image.new('RGB', size, color)
    if stripes:
        for x in range(size[0]):
            if (x // stripes) % 2:
                for y in range(size[1]):
                    img.putpixel((x, y), (0, 0, 0))
    if box:
        for x in range(box[0], box[2]):
            for y in range(box[1], box[3]):
                img.putpixel((x, y), (0, 0, 0))
    out = io.BytesIO()
    img.save(out, format='PNG')
    return out.getvalue()


class ManualCase(TransactionCase):
    """方案、兩個能力、一個情境、四個功能點（全部是候選）；不接任何實機。

    f1、f2 → 能力 A；f3 → 能力 B；f4 → 圈選核准但沒有能力（共通操作）。
    每個功能在方案的目前指紋（角色 admin）預設是 h1。
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.tmpl = env['product.template'].create(
            {'name': 'KB Manual Plan', 'type': 'service'})  # is_package 會要求 Branch 屬性
        cls.pkg = env['infrastructure.solution.package'].sudo().create(
            {'product_tmpl_id': cls.tmpl.id})
        cls.Feature = env['corpaas.knowledge.feature'].sudo()
        cls.FP = env['corpaas.knowledge.fingerprint'].sudo()

        def feature(anchor, name):
            return cls.Feature.create({
                'feature_key': 'kbtest.action:%s' % anchor, 'module': 'kbtest',
                'kind': 'action', 'anchor': anchor, 'name': name, 'model': 'res.partner',
                'package_ids': [(6, 0, cls.pkg.ids)]})
        cls.f1 = feature('kbtest.a1', '建立報名')
        cls.f2 = feature('kbtest.a2', '報名確認')
        cls.f3 = feature('kbtest.a3', '收款')
        cls.f4 = feature('kbtest.a4', '聯絡人')
        Cap = env['corpaas.knowledge.capability'].sudo()
        cls.cap_a = Cap.create({'name': '線上報名', 'code': 'kb_reg', 'sequence': 10,
                                'package_ids': [(6, 0, cls.pkg.ids)],
                                'feature_ids': [(6, 0, (cls.f1 | cls.f2).ids)]})
        cls.cap_b = Cap.create({'name': '收費對帳', 'code': 'kb_pay', 'sequence': 20,
                                'package_ids': [(6, 0, cls.pkg.ids)],
                                'feature_ids': [(6, 0, cls.f3.ids)]})
        env['corpaas.knowledge.selection'].sudo().create({
            'package_id': cls.pkg.id, 'kind': 'feature', 'feature_id': cls.f4.id,
            'state': 'approved'})
        cls.scenario = env['corpaas.knowledge.scenario'].sudo().create({
            'name': '協會年會', 'code': 'kbtest_assoc', 'glossary': '客戶=會員',
            'package_ids': [(6, 0, cls.pkg.ids)]})
        for f in (cls.f1, cls.f2, cls.f3, cls.f4):
            cls._fp(f, 'h1')
        cls.Article = env['corpaas.knowledge.article'].sudo()
        cls.Block = env['corpaas.knowledge.step_block'].sudo()
        cls.hooks = env['corpaas.knowledge.hooks']
        cls.approver = new_test_user(
            env, 'kb_manual_approver',
            groups='base.group_user,dobtor_corpaas_knowledge.group_knowledge_approver')

    @classmethod
    def _fp(cls, feature, scope_hash, pkg=None, role='admin', error=None):
        """方案目前的指紋：舊的 current 一律關掉。"""
        pkg = pkg or cls.pkg
        cls.FP.search([('feature_id', '=', feature.id), ('package_id', '=', pkg.id),
                       ('role_code', '=', role), ('current', '=', True)]).write(
            {'current': False})
        return cls.FP.create({
            'feature_id': feature.id, 'package_id': pkg.id, 'role_code': role,
            'scope_hash': False if error else scope_hash, 'error': error, 'current': True,
            'found_json': '["field=name"]'})

    @classmethod
    def _new_package(cls, name, scenario=None, caps=None, features=None, scope_hash='h1'):
        tmpl = cls.env['product.template'].create({'name': name, 'type': 'service'})
        pkg = cls.env['infrastructure.solution.package'].sudo().create(
            {'product_tmpl_id': tmpl.id})
        (caps or cls.cap_a).package_ids = [(4, pkg.id)]
        (scenario or cls.scenario).package_ids = [(4, pkg.id)]
        for f in (features or cls.f1):
            f.package_ids = [(4, pkg.id)]
            cls._fp(f, scope_hash, pkg=pkg)
        return pkg

    def _block(self, feature, fingerprint='h1', html=None, publish=False, **kw):
        blk = self.Block.create(dict({
            'name': '%s 步驟' % feature.name, 'feature_id': feature.id,
            'fingerprint': fingerprint,
            'html': html or '<h4>開啟</h4><p>按下按鈕。</p><p>[[shot:main]]</p>'}, **kw))
        if publish:
            blk._do_publish('new')
        return blk

    def _article(self, feature, cap=None, name=None, scenario=None, block=None, **kw):
        block = block or self._block(feature, fingerprint=kw.get('fingerprint', 'h1'),
                                     publish=True)
        return self.Article.create(dict({
            'name': name or feature.name, 'feature_id': feature.id,
            'scenario_id': (scenario or self.scenario).id,
            'capability_id': cap.id if cap else False,
            'step_block_ids': [(6, 0, block.ids)], 'fingerprint': 'h1',
            'scenario_html': '<p>會員報名前要先建立年會。</p>'}, **kw))

    def _publish(self, *articles):
        for art in articles:
            art._do_publish('new')

    def _channel(self, tmpl=None):
        return self.env['slide.channel'].sudo().search(
            [('knowledge_product_tmpl_id', '=', (tmpl or self.tmpl).id)])

    def _asset(self, feature, shot_name='main', regions=None, data=None, owner=None,
               scope_hash='h1'):
        asset = self.env['corpaas.knowledge.asset'].sudo().create({
            'name': 'asset %s' % shot_name, 'shot_name': shot_name,
            'feature_id': feature.id, 'scenario_id': self.scenario.id,
            'regions_json': json.dumps(regions or []), 'scope_hash': scope_hash,
            'owner_model': owner._name if owner else False,
            'owner_id': owner.id if owner else 0})
        asset.attachment_id = self.env['ir.attachment'].sudo().create({
            'name': '%s.png' % shot_name, 'raw': data or png(), 'mimetype': 'image/png',
            'res_model': asset._name, 'res_id': asset.id})
        return asset
