# -*- coding: utf-8 -*-
import io

from odoo.tests import TransactionCase, tagged

from ..services import fingerprint_lib as fl
from ..services import phash, search_lib

FORM = """<form><sheet><group>
  <field name="partner_id" required="1"/>
  <field name="date_order"/>
</group><notebook><page name="lines" string="明細">
  <field name="order_line"/></page></notebook>
<footer><button name="action_confirm" string="確認" type="object"/></footer></sheet></form>"""


@tagged('post_install', '-at_install')
class TestPureLibs(TransactionCase):

    def test_normalize_is_whitespace_and_attr_order_insensitive(self):
        a = '<form><field  name="x"   string="X"/></form>'
        b = '<form>\n  <field string="X" name="x"/>\n</form>'
        self.assertEqual(fl.normalize_arch(a), fl.normalize_arch(b))

    def test_scope_hash_ignores_unrelated_fields(self):
        elements = [{'field': 'partner_id'}, {'button': 'action_confirm'}]
        h1, found = fl.scope_hash({'form': FORM}, elements, '銷售/報價')
        other = FORM.replace('<field name="date_order"/>',
                             '<field name="date_order"/><field name="note"/>')
        h2, _ = fl.scope_hash({'form': other}, elements, '銷售/報價')
        self.assertEqual(h1, h2, '無關欄位變動不應觸發重拍')
        self.assertEqual(sorted(found), ['button=action_confirm', 'field=partner_id'])
        # 但表單層指紋要變（只觸發檢查）
        self.assertNotEqual(fl.form_hash({'form': FORM}), fl.form_hash({'form': other}))

    def test_scope_hash_detects_label_and_ancestor_change(self):
        elements = [{'button': 'action_confirm'}]
        h1, _ = fl.scope_hash({'form': FORM}, elements)
        relabel = FORM.replace('string="確認"', 'string="確認訂單"')
        h2, _ = fl.scope_hash({'form': relabel}, elements)
        self.assertNotEqual(h1, h2)
        hidden = FORM.replace('<footer>', '<footer invisible="state != \'draft\'">')
        h3, _ = fl.scope_hash({'form': hidden}, elements)
        self.assertNotEqual(h1, h3, '祖先節點的 invisible 改變會影響畫面')

    def test_scope_hash_menu_path_matters(self):
        e = [{'field': 'partner_id'}]
        self.assertNotEqual(fl.scope_hash({'form': FORM}, e, 'A/B')[0],
                            fl.scope_hash({'form': FORM}, e, 'A/C')[0])

    def test_missing_element_is_part_of_hash(self):
        e = [{'field': 'nope'}]
        h, found = fl.scope_hash({'form': FORM}, e)
        self.assertFalse(found)
        self.assertTrue(h)

    def test_similarity(self):
        a = fl.signature({'form': FORM})
        b = fl.signature({'form': FORM.replace('date_order', 'validity_date')})
        self.assertGreater(fl.similarity(a, b), 0.5)
        self.assertEqual(fl.similarity([], []), 1.0)

    def test_dhash_distance(self):
        from PIL import Image, ImageDraw

        def png(shift=0, box=True):
            img = Image.new('RGB', (320, 200), 'white')
            d = ImageDraw.Draw(img)
            if box:
                d.rectangle([40 + shift, 40, 160 + shift, 120], fill='black')
            out = io.BytesIO()
            img.save(out, format='PNG')
            return out.getvalue()

        base = phash.dhash(png())
        self.assertEqual(phash.distance(base, phash.dhash(png())), 0)
        self.assertGreater(phash.distance(base, phash.dhash(png(shift=120))), 10)
        self.assertEqual(phash.distance(base, ''), phash.HASH_SIZE ** 2)

    def test_search_bigrams(self):
        s1 = search_lib.score('怎麼確認報價單', [('確認報價單', 3.0), ('銷售/報價', 2.0)])
        s2 = search_lib.score('怎麼開發票', [('確認報價單', 3.0), ('銷售/報價', 2.0)])
        self.assertGreater(s1, s2)
        self.assertEqual(search_lib.score('', [('x', 1.0)]), 0.0)
