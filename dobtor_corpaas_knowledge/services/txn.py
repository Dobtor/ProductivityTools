# -*- coding: utf-8 -*-
"""獨立游標的共用判斷。

「立即 commit、不跟主交易綁在一起」的寫法（記帳、方案簿記、金鑰落帳）在實機是對的，
但測試裡主交易從不 commit：獨立游標看不到測試建立的列，寫入影響 0 列或撞外鍵。
測試期間改寫在目前交易。

☠️ 不能只看 registry.in_test_mode()：那只在 HttpCase 期間為真，一般 TransactionCase
  是 False。
"""
import odoo.modules.module as odoo_module


def in_tests(env):
    return env.registry.in_test_mode() or bool(getattr(odoo_module, 'current_test', None))
