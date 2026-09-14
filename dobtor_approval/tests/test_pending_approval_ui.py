# -*- coding: utf-8 -*-
# Copyright Dobtor Systems Integration Co., Ltd. — License: OPL-1
"""「已送出簽核」不可以長成 Python traceback 的樣子。

☠★ 這是所有「自訂 UserError 子類別」共通的坑
   web client 的錯誤呈現是用**完整的例外名稱**當 key 查登記表，不是用
   isinstance：

       registry.category("error_dialogs")
           .add("odoo.exceptions.UserError", WarningDialog)

   BpmnPendingApproval 繼承 UserError，但名字是
       odoo.addons.dobtor_approval.models.bpmn_guard_mixin.BpmnPendingApproval
   ——不在表裡，於是掉進通用的 RPCErrorDialog，使用者按下「允收」看到的是
   「Odoo Server Error」加一整段 traceback。後端完全正常，前端全毀。

   實機 2026-09-14 就是這樣被回報的：閘門第一次真的生效，而現場的結論是
   「簽核壞了」。

☠️ 這一組守的是靜態事實（檔案在、名字對得上、有掛進 bundle），不是行為。
   行為要瀏覽器才驗得到，而這三件事任何一件錯掉，症狀都一樣是 traceback。
"""
import os

from odoo.tests import TransactionCase, tagged

from ..models.bpmn_guard_mixin import BpmnPendingApproval

ASSET = 'dobtor_approval/static/src/js/pending_approval_notification.js'


def _module_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@tagged('post_install', '-at_install')
class TestPendingApprovalUi(TransactionCase):

    def _asset_source(self):
        path = os.path.join(_module_root(), 'static', 'src', 'js',
                            'pending_approval_notification.js')
        self.assertTrue(os.path.exists(path), '登記檔不見了：%s' % path)
        with open(path, encoding='utf-8') as fh:
            return fh.read()

    def test_the_exception_name_used_by_the_client_is_the_dotted_path(self):
        """登記用的字串必須是 Python 這邊真正送出去的那一個。

        ☠️ 手打字串與實際類別對不上時沒有任何錯誤——只是登記永遠不會命中。
        """
        actual = '%s.%s' % (BpmnPendingApproval.__module__,
                            BpmnPendingApproval.__name__)
        self.assertIn(actual, self._asset_source(),
                      '前端登記的名稱與實際例外名稱對不上：%s' % actual)

    def test_it_is_registered_as_a_notification_not_an_error_dialog(self):
        """☠️ 閘門攔截是**成功**的結果（單子已經送出去簽了）。

        用警告對話框呈現會讓人以為動作失敗了；用通用對話框更糟，
        那會直接吐 traceback。
        """
        src = self._asset_source()
        self.assertIn('error_notifications', src,
                      '要登記在 error_notifications，不是 error_dialogs')

    def test_the_asset_is_in_the_backend_bundle(self):
        """☠️ 檔案寫好了沒掛進 bundle＝完全沒有效果，而且不會報錯。"""
        manifest = os.path.join(_module_root(), '__manifest__.py')
        with open(manifest, encoding='utf-8') as fh:
            content = fh.read()
        self.assertIn(ASSET, content, '登記檔沒有掛進 web.assets_backend')

    def test_the_exception_is_still_a_user_error(self):
        """前端修好了，後端的語意不可以跟著跑掉。

        ☠️ 它必須仍然是 UserError 的子類別：Odoo 的交易層對 UserError
           會回滾並保留訊息，對一般例外則是 500。改成裸 Exception 的話，
           送簽被攔的那一刻整個請求會變成伺服器錯誤。
        """
        from odoo.exceptions import UserError
        self.assertTrue(issubclass(BpmnPendingApproval, UserError))
