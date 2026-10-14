# -*- coding: utf-8 -*-
"""目錄項行銷內容 API：真的 portal 經銷商＋真的 API 金鑰（不 mock 認證）。

經銷商帳號是 portal 使用者，沒有任何知識／方案模型權限——任何一處沒 sudo、
偷靠 API 使用者模型權限的地方都會在這裡現形。
"""
import base64

from odoo.tests import HttpCase, tagged

PNG = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==')


@tagged('post_install', '-at_install')
class TestCatalogMarketingApi(HttpCase):

    def setUp(self):
        super().setUp()
        env = self.env
        if 'corpaas.knowledge.pitch' not in env:
            self.skipTest('行銷出口（dobtor_corpaas_knowledge_marketing）沒裝')
        self.reseller = env['res.partner'].create({'name': 'MKT Reseller', 'is_reseller': True,
                                                   'is_company': True})
        contact = env['res.partner'].create({'name': 'MKT Staff', 'parent_id': self.reseller.id,
                                             'email': 'mkt-staff@example.com'})
        user = env['res.users'].with_context(no_reset_password=True).create({
            'name': 'MKT Staff', 'login': 'mkt-portal', 'password': 'mkt-portal-pw-123',
            'partner_id': contact.id,
            'groups_id': [(6, 0, [env.ref('base.group_portal').id,
                                  env.ref('dobtor_infrastructure.group_reseller').id])]})
        self.assertTrue(user.share, 'fixture 必須是 portal 使用者')
        self.key = env['res.users.apikeys'].with_user(user).sudo()._generate(
            None, 'mkt-test', None)
        # 已發布的目錄項（發布檢查要能開通的層級，與這裡無關：直接寫庫）
        self.tmpl = env['product.template'].create({'name': 'MKT 方案', 'type': 'service'})
        self.pkg = env['infrastructure.solution.package'].create({'product_tmpl_id': self.tmpl.id})
        env.cr.execute("UPDATE infrastructure_solution_package SET catalog_ref='mkt-std-18', "
                       "is_published=true WHERE id=%s", (self.pkg.id,))
        self.pkg.invalidate_recordset()
        Feature = env['corpaas.knowledge.feature']
        self.feat = Feature.create({
            'feature_key': Feature.make_key('kb_mkt_api', 'action', 'signup'),
            'module': 'kb_mkt_api', 'kind': 'action', 'anchor': 'signup', 'name': '線上報名',
            'package_ids': [(6, 0, self.pkg.ids)]})
        cap = env['corpaas.knowledge.capability'].create({
            'name': '線上報名', 'code': 'kb_mkt_api_signup',
            'feature_ids': [(6, 0, self.feat.ids)], 'package_ids': [(6, 0, self.pkg.ids)]})
        self.att = env['ir.attachment'].create({'name': 'signup.png', 'raw': PNG,
                                                'mimetype': 'image/png'})
        scenario = env['corpaas.knowledge.scenario'].create(
            {'name': '協會年會', 'code': 'kb_mkt_api_assoc'})
        asset = env['corpaas.knowledge.asset'].create({
            'name': '報名表', 'shot_name': 'signup_form', 'feature_id': self.feat.id,
            'scenario_id': scenario.id, 'attachment_id': self.att.id})
        self.pitch = env['corpaas.knowledge.pitch'].create({
            'capability_id': cap.id, 'product_tmpl_id': self.tmpl.id, 'package_id': self.pkg.id,
            'headline': '報名就收到錢', 'body_html': '<p>痛點到成果</p>',
            'asset_ids': [(6, 0, asset.ids)]})
        self.pitch._replace_claims([{'text': '報名表自動建檔',
                                     'features': [self.feat.feature_key]}])
        self.pitch.knowledge_propose('claim')
        self.pitch.action_approve()
        self.assertEqual(self.pitch.state, 'published')

    def _get(self, path, headers=None):
        return self.url_open(path, headers=dict({'X-API-Key': self.key}, **(headers or {})))

    def test_marketing_as_portal_reseller(self):
        r = self._get('/api/v1/catalog/mkt-std-18/marketing')
        self.assertEqual(r.status_code, 200, r.text)
        data = r.json()
        self.assertEqual(data['catalog_ref'], 'mkt-std-18')
        self.assertEqual(data['cards'][0]['headline'], '報名就收到錢')
        self.assertEqual(data['cards'][0]['claims'], ['報名表自動建檔'])
        self.assertEqual(data['cards'][0]['images'][0]['src'], 'corpaas-image:%s' % self.att.id)
        self.assertTrue(data['content_hash'])
        self.assertEqual(r.headers.get('ETag'), '"%s"' % data['content_hash'])
        # 沒變 → 304
        r = self._get('/api/v1/catalog/mkt-std-18/marketing',
                      {'If-None-Match': '"%s"' % data['content_hash']})
        self.assertEqual(r.status_code, 304)
        # 圖片：引用到的才給
        r = self._get('/api/v1/catalog/mkt-std-18/marketing/image/%s' % self.att.id)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.content, PNG)
        other = self.env['ir.attachment'].create({'name': 'secret.png', 'raw': PNG,
                                                  'mimetype': 'image/png'})
        self.assertEqual(self._get('/api/v1/catalog/mkt-std-18/marketing/image/%s'
                                   % other.id).status_code, 404)

    def test_catalog_payload_carries_marketing_hash(self):
        payload, _imgs = self.pkg._reseller_marketing_export()
        Pkg = self.env['infrastructure.solution.package']
        items = Pkg._published_catalog(catalog_ref='mkt-std-18', reseller=self.reseller)
        self.assertEqual(items[0]['marketing_hash'], payload['content_hash'])

    def test_scope_hidden_withdrawn_unknown(self):
        self.assertEqual(self.url_open('/api/v1/catalog/mkt-std-18/marketing').status_code, 401)
        self.assertEqual(self._get('/api/v1/catalog/nope/marketing').status_code, 404)
        rule = self.env['reseller.price.rule'].sudo().create({
            'reseller_id': self.reseller.id, 'package_id': self.pkg.id, 'visible': False})
        self.assertEqual(self._get('/api/v1/catalog/mkt-std-18/marketing').status_code, 404,
                         '價格規則設成看不到的目錄項')
        self.assertEqual(self._get('/api/v1/catalog/mkt-std-18/marketing/image/%s'
                                   % self.att.id).status_code, 404)
        rule.unlink()
        self.env.cr.execute("UPDATE infrastructure_solution_package SET is_published=false, "
                            "sunset_date='2026-12-31' WHERE id=%s", (self.pkg.id,))
        self.pkg.invalidate_recordset()
        self.assertEqual(self._get('/api/v1/catalog/mkt-std-18/marketing').status_code, 404,
                         '已下架：經銷商據此清掉商品頁上的內容')

    def test_retired_content_is_empty(self):
        self.pitch.action_retire()
        r = self._get('/api/v1/catalog/mkt-std-18/marketing')
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()['cards'], [])
        self.assertFalse(r.json()['content_hash'])
        self.assertEqual(self._get('/api/v1/catalog/mkt-std-18/marketing/image/%s'
                                   % self.att.id).status_code, 404)
