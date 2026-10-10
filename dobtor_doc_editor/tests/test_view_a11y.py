# -*- coding: utf-8 -*-
r"""視圖的無障礙警告必須是 0——而且由 **Odoo 自己的驗證器**判定。

☠️ 為什麼不自己重寫一份判準：2026-10-10 我重實作
`_validate_fa_class_accessibility` 時漏掉第一段（`node.tail` 與
`parent.text`），算出 21 處；補回去才得到 7 處，而 Odoo 安裝時報 6 處。
**我的尺跟 Odoo 的尺不一樣，而出警告的是 Odoo 那把。** 所以這一支不重寫
判準，直接叫 `_check_xml()` 並接住 `ir_ui_view` logger 的 warning。

裝飾性圖示的處理方式（`views/`、`wizards/` 六處）：把 `<i>` 搬進緊接的
`<strong>`／`<b>` 裡，讓它的 tail 就是那段可見文字，再加 `aria-hidden="true"`。
理由：

- Odoo 的 `valid_aria_attrs` 只收 `title`／`aria-label`／`aria-labelledby`，
  **不收 `aria-hidden`**。所以單加 `aria-hidden` 消不掉警告。
- 但這些圖示確實是裝飾性的（坐在警示框開頭，後面緊接完整句子），
  替它們編一個 `title` 會讓滑鼠停留冒出一個沒意義的提示，
  編一個 `aria-label` 會讓螢幕閱讀器把同一句話唸兩次。
- Odoo 的驗證器第一道檢查就是「緊鄰有可見文字」——搬進 `<strong>` 之後
  tail 正是那段文字，這是最不需要編造資訊的一條路。`aria-hidden="true"`
  才是 WCAG 對裝飾性圖示的正解，兩者併用。

☠️ `_check_xml()` 對 `type == 'qweb'` 的視圖直接 `continue`
（`ir_ui_view.py:370`）——**Odoo 完全不驗 QWeb 模板**。這就是
`views/portal_templates.xml` 的圖示不在那 6 處裡的原因。所以下面第二則
自己掃 qweb，用的是一條**比 Odoo 寬**的規則，掃的是 Odoo 根本不看的地方。
"""
import logging
import re

from odoo.tests.common import TransactionCase, tagged

MODULE = 'dobtor_doc_editor'
IR_UI_VIEW_LOGGER = 'odoo.addons.base.models.ir_ui_view'
FA_A11Y_MARKER = 'must have title in its tag, parents, descendants or have text'


class _Collector(logging.Handler):
    """把 ir_ui_view 的 warning 收進清單，不讓它只是飄過 log。"""

    def __init__(self):
        logging.Handler.__init__(self, level=logging.WARNING)
        self.messages = []

    def emit(self, record):
        try:
            self.messages.append(record.getMessage())
        except Exception:                       # pragma: no cover
            self.messages.append(str(record.msg))


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestViewAccessibility(TransactionCase):
    """本模組的視圖重新驗證一次，無障礙警告必須 0 條。"""

    def _own_views(self):
        data = self.env['ir.model.data'].search([
            ('module', '=', MODULE), ('model', '=', 'ir.ui.view'),
        ])
        return self.env['ir.ui.view'].browse(data.mapped('res_id')).exists()

    def _validate_and_collect(self, views):
        """跑 Odoo 的驗證器並回傳它記下的 warning 訊息。"""
        logger = logging.getLogger(IR_UI_VIEW_LOGGER)
        collector = _Collector()
        logger.addHandler(collector)
        try:
            views._check_xml()
        finally:
            logger.removeHandler(collector)
        return collector.messages

    def test_module_has_views_to_check(self):
        """先確認抽得到視圖——抽到 0 筆的話下面那則會空轉過關。

        ☠️ 這是本模組反覆抓到的形狀：沒量到東西卻印「通過」。
        """
        views = self._own_views()
        self.assertGreaterEqual(
            len(views), 5,
            '只抽到 %d 筆 %s 的 ir.ui.view。抽法若失效，這支測試會變成'
            '空檢查——請修 _own_views() 而不是放它過。' % (len(views), MODULE))

    def test_no_fa_accessibility_warnings(self):
        """`<i class="fa …">` 的無障礙警告必須 0 條。"""
        warnings = self._validate_and_collect(self._own_views())
        offenders = [m for m in warnings if FA_A11Y_MARKER in m]
        self.assertFalse(
            offenders,
            '還有 %d 條 fa 圖示的無障礙警告：\n\n%s'
            % (len(offenders), '\n---\n'.join(offenders)))

    def test_detector_actually_fires(self):
        """負向驗證：故意放一個沒有說明文字的 fa 圖示，上面那則的收集器要抓到。

        ☠️ 沒有這一則，`test_no_fa_accessibility_warnings` 綠只能證明
        「收集器沒收到東西」，不能證明「警告不存在」——本模組今天在
        traversal 守衛與煙霧測試上各踩過一次這個分別。
        """
        bad = self.env['ir.ui.view'].new({
            'name': 'a11y negative control',
            'model': 'res.partner',
            'type': 'form',
            'arch': '<form><div><i class="fa fa-lock"/></div></form>',
        })
        warnings = self._validate_and_collect(bad)
        self.assertTrue(
            [m for m in warnings if FA_A11Y_MARKER in m],
            '故意放的壞圖示沒有被 Odoo 的驗證器報出來——'
            '代表 _validate_and_collect() 接錯了 logger，或 Odoo 改了訊息文字'
            '（FA_A11Y_MARKER 要跟著改）。那會讓上面那則永遠綠。')

    def test_qweb_fa_icons_are_labelled_or_hidden(self):
        """QWeb 模板 Odoo 不驗，所以這裡自己掃一條比較寬的規則。

        規則：`<i>` 帶 fa class 時，必須至少有一項——
        緊鄰的可見文字（tail）、`title`／`aria-label`／`aria-labelledby`、
        或 `aria-hidden="true"`（明確宣告它是裝飾性的）。
        """
        from lxml import etree

        views = self._own_views().filtered(lambda v: v.type == 'qweb')
        self.assertTrue(views, '抽不到 qweb 視圖——抽法失效了')
        offenders = []
        for view in views:
            root = etree.fromstring(view.arch_db.encode('utf-8'))
            for node in root.iter('i'):
                if not re.search(r'\bfa\b', node.get('class') or ''):
                    continue
                if (node.tail or '').strip():
                    continue
                if any(node.get(a) for a in
                       ('title', 'aria-label', 'aria-labelledby')):
                    continue
                if node.get('aria-hidden') == 'true':
                    continue
                offenders.append('%s 第 %s 行：%s'
                                 % (view.xml_id, node.sourceline,
                                    node.get('class')))
        self.assertFalse(
            offenders,
            'QWeb 模板裡有 fa 圖示既沒有緊鄰文字也沒有 aria 標記：\n  %s'
            % '\n  '.join(offenders))
