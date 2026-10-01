# -*- coding: utf-8 -*-
import io

from PIL import Image

from odoo.tests.common import TransactionCase, tagged

from ..services import annotate, manual_lib
from .common import ManualCase, png


@tagged('post_install', '-at_install')
class TestManualLib(TransactionCase):

    def test_steps_validation_and_derivation(self):
        steps = [
            {'goto': {'action': 'sale.action_orders'}},
            {'open': '{order}'},
            {'click': {'page': 'order_lines'}},
            {'fill': {'field': 'note', 'value': 'x'}},
            {'highlight': {'button': 'action_confirm', 'n': 1}},
            {'highlight': {'field': 'partner_id', 'n': 2}},
            {'shot': 'confirm'},
            {'goto': {'action': 'sale.action_orders', 'res_id': '{order}'}},
            {'shot': 'confirm'},
        ]
        self.assertTrue(manual_lib.validate_steps(steps))
        self.assertEqual(manual_lib.elements_from_steps(steps), [
            {'page': 'order_lines'}, {'field': 'note'}, {'button': 'action_confirm'},
            {'field': 'partner_id'}])
        self.assertEqual(manual_lib.placeholders_in(steps), ['order'])
        self.assertEqual(manual_lib.shot_names(steps), ['confirm'])
        with self.assertRaises(ValueError):
            manual_lib.validate_steps([{'goto': {'url': '/odoo'}}])
        # ☠️ goto.url 會被品牌過濾改寫：一律拒絕（有 shot 也一樣）
        with self.assertRaises(ValueError):
            manual_lib.validate_steps([{'goto': {'url': '/odoo/sale.order/1'}}, {'shot': 'a'}])
        with self.assertRaises(ValueError):
            manual_lib.validate_steps([{'goto': {'action': 'x.y', 'url': '/odoo'}},
                                       {'shot': 'a'}])
        from ..services import prompts
        self.assertNotIn('"url"', prompts.STEP_VOCAB)
        self.assertNotIn('/odoo/', prompts.explore_prompt({'name': 'x'}, {}, [], []))
        with self.assertRaises(ValueError):
            manual_lib.validate_steps([{'hack': {}}, {'shot': 'a'}])
        with self.assertRaises(ValueError):
            manual_lib.validate_steps([{'shot': '../etc'}])

    def test_fill_placeholders(self):
        steps = [{'open': '{order}'}, {'goto': {'action': 'x.y', 'res_id': '{order}'}},
                 {'goto': {'url': '/odoo/sale.order/{order}'}}, {'click': {'text': '{nope}'}}]
        out, missing = manual_lib.fill_placeholders(steps, {'order': ['sale.order', 42]})
        self.assertEqual(out[0], {'open': {'model': 'sale.order', 'res_id': 42}})
        self.assertEqual(out[1]['goto']['res_id'], 42)
        self.assertEqual(out[2]['goto']['url'], '/odoo/sale.order/42')
        self.assertEqual(missing, {'nope'})

    def test_clean_html_strips_forbidden(self):
        dirty = ('<p style="color:red" onclick="x()">A<a href="https://evil">B</a></p>'
                 '<style>p{}</style><script>alert(1)</script><svg><rect/></svg>'
                 '<table class="table table-bordered"><tr><td>C</td></tr></table>')
        clean = manual_lib.clean_html(dirty)
        for bad in ('<style', '<script', '<svg', '<a', 'href', 'onclick', 'style='):
            self.assertNotIn(bad, clean)
        self.assertIn('AB', clean)
        self.assertIn('table table-bordered', clean)

    def test_heading_ids_and_markers(self):
        html = manual_lib.steps_to_html(
            [{'title': '開啟', 'html': '<p>x</p><p>[[shot:main]]</p>'},
             {'title': '確認', 'html': '<p>y</p>'}], 'kb-anchor')
        self.assertIn('id="kb-anchor-1"', html)
        self.assertIn('id="kb-anchor-2"', html)
        restamped = manual_lib.stamp_heading_ids('<h4>一</h4><h4 id="old">二</h4>', 'a')
        self.assertIn('id="a-1"', restamped)
        self.assertIn('id="a-2"', restamped)
        out, used = manual_lib.replace_shot_markers(html, {'main': '<p><img src="/x"/></p>'})
        self.assertEqual(used, {'main'})
        self.assertIn('<img src="/x"/>', out)
        self.assertNotIn('[[shot', out)

    def test_text_signature_ignores_images(self):
        a = '<p>步驟</p><img src="/web/image/1"/>'
        b = '<p>步驟</p><img src="/web/image/2" class="img-fluid"/>'
        self.assertEqual(manual_lib.text_signature(a), manual_lib.text_signature(b))
        self.assertNotEqual(manual_lib.text_signature(a), manual_lib.text_signature('<p>改</p>'))

    def test_readback_lost(self):
        sent = '<h4 id="a-1">x</h4><img src="/1"/>'
        self.assertEqual(manual_lib.readback_lost(sent, sent), [])
        lost = manual_lib.readback_lost(sent, '<h4>x</h4>')
        self.assertEqual(len(lost), 2)

    def test_anchor_is_stable_slug(self):
        a = manual_lib.make_anchor('sale.button:sale.view_order_form/button[action_confirm]')
        self.assertEqual(a, manual_lib.make_anchor(
            'sale.button:sale.view_order_form/button[action_confirm]'))
        self.assertRegex(a, r'^[a-z0-9-]+$')

    def test_draw_regions(self):
        """紅框畫進新圖，原圖位元組不動；座標依 device scale 放大。"""
        original = png(size=(200, 100))
        out = annotate.draw_regions(original, [{'n': 1, 'x': 60, 'y': 20, 'w': 20, 'h': 10}],
                                    css_width=100)
        self.assertNotEqual(out, original)
        img = Image.open(io.BytesIO(out)).convert('RGB')
        # 右邊框：x = (60 + 20 + 3) * 2 = 166，框線往內畫
        r, g, b = img.getpixel((164, 50))
        self.assertGreater(r, 200)
        self.assertLess(g, 80)
        self.assertEqual(img.getpixel((140, 50)), (255, 255, 255))
        src = Image.open(io.BytesIO(original)).convert('RGB')
        self.assertEqual(src.getpixel((164, 50)), (255, 255, 255))


@tagged('post_install', '-at_install')
class TestAnnotatedAsset(ManualCase):

    def test_manual_attachment_is_public_copy(self):
        asset = self._asset(self.f1, regions=[{'n': 1, 'x': 10, 'y': 10, 'w': 50, 'h': 20}])
        raw = asset.attachment_id.raw
        att = asset._manual_image_attachment()
        self.assertTrue(att.public)
        self.assertNotEqual(att, asset.attachment_id)
        self.assertEqual(asset.attachment_id.raw, raw, '原圖不能被改')
        self.assertFalse(asset.attachment_id.public)
        self.assertEqual(asset._manual_image_attachment(), att, '沒變就不重畫')
        asset.regions_json = '[{"n": 1, "x": 5, "y": 5, "w": 10, "h": 10}]'
        self.assertEqual(asset._manual_image_attachment(), att, '重畫沿用同一個附件')
        self.assertNotEqual(att.raw, raw)
