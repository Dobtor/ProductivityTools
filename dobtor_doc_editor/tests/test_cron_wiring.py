# -*- coding: utf-8 -*-
"""ir.cron 的接線——`code` 字串真的解析得到嗎。

☠️ 為什麼需要這一支：`ir.cron` 的 `code` 是**字串**，每天在無人看管的情況下
被 eval。方法改名、搬家、或 `model_id` 指錯 model，症狀是**每天在沒人看的
log 裡丟一次例外**——不會紅、不會有人收到通知、使用者也看不出來。

這跟本模組一整天反覆出現的失效模式是同一個：程式碼存在、甚至每天在執行，
但它的結果到不了任何人眼前。

0a6c410 補過其中一支（`_cron_health_check_no_alias` 當時整支零測試），
但那是逐支補；這一支是**結構性**的：XML 裡新增一條 cron，它的 code 自動
被納入檢查，不必記得去補測試。

檢查三件事：
  1. 每條 cron 的 `model_id` 都解析得到一個已安裝的 model
  2. `code` 裡 `model.<method>(…)` 的那個方法在該 model 上存在且可呼叫
  3. `code` 不符合 `model.<method>(…)` 形狀時**要紅**，不是靜默跳過
     （否則「檢查涵蓋不到的寫法」就成了繞過它的方式）

刻意**不實際呼叫**那些方法：它們是 GC（會 unlink）。各自的行為測試在
test_telemetry.py / test_doc_output.py 裡，這裡只驗接線。
"""
import os
import re
import xml.etree.ElementTree as ET

from odoo.tests.common import TransactionCase, tagged

MODULE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CRON_XML = os.path.join(MODULE_ROOT, 'data', 'ir_cron_data.xml')

# `model.method(...)` / `model.method()`——cron code 的標準形狀
_CODE_RE = re.compile(r'^\s*model\.([A-Za-z_][A-Za-z0-9_]*)\s*\(')


def _cron_records():
    """從 XML 讀出 (xml_id, model_ref, code) 三元組。"""
    out = []
    for rec in ET.parse(CRON_XML).getroot().iter('record'):
        if rec.get('model') != 'ir.cron':
            continue
        model_ref, code = None, None
        for field in rec.findall('field'):
            if field.get('name') == 'model_id':
                model_ref = field.get('ref')
            elif field.get('name') == 'code':
                code = (field.text or '').strip()
        out.append((rec.get('id'), model_ref, code))
    return out


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestCronWiring(TransactionCase):
    """五條每天跑的 cron，它們的 code 字串要真的解析得到。"""

    def test_cron_xml_has_records(self):
        """先確認真的讀到 cron——讀不到的話底下每一則都會空轉過關。"""
        crons = _cron_records()
        self.assertTrue(
            crons,
            '%s 裡找不到任何 ir.cron 記錄。如果 cron 搬到別的檔案，'
            '這一支的 CRON_XML 要跟著改——否則它會變成永遠綠的空檢查。'
            % CRON_XML,
        )

    def test_every_cron_code_resolves_to_a_real_method(self):
        """`model.<method>` 在 cron 宣告的 model 上存在且可呼叫。"""
        broken = []
        for xml_id, model_ref, code in _cron_records():
            if not model_ref:
                broken.append('%s：沒有 model_id' % xml_id)
                continue
            # model_ref 形如 model_doc_editor_error_log（ir.model 的 XML id）
            ref = model_ref if '.' in model_ref else 'dobtor_doc_editor.%s' % model_ref
            ir_model = self.env.ref(ref, raise_if_not_found=False)
            if not ir_model:
                broken.append('%s：model_id ref「%s」解析不到' % (xml_id, model_ref))
                continue
            model_name = ir_model.model
            if model_name not in self.env:
                broken.append('%s：model「%s」沒有註冊' % (xml_id, model_name))
                continue
            m = _CODE_RE.match(code or '')
            if not m:
                broken.append(
                    '%s：code「%s」不是 `model.方法(…)` 的形狀，本測試驗不到它。'
                    '要嘛改成那個形狀，要嘛把 _CODE_RE 擴充並補上對應驗證'
                    '——**不要**讓它靜默跳過。' % (xml_id, code))
                continue
            method = m.group(1)
            target = getattr(self.env[model_name], method, None)
            if target is None:
                broken.append(
                    '%s：%s 上沒有方法 %s()（cron 每天 eval 這個字串，'
                    '改名的症狀是每天在沒人看的 log 裡丟一次例外）'
                    % (xml_id, model_name, method))
            elif not callable(target):
                broken.append('%s：%s.%s 不可呼叫' % (xml_id, model_name, method))
        self.assertFalse(broken, '以下 cron 接線壞了：\n  ' + '\n  '.join(broken))

    def test_every_cron_is_installed_and_active_as_declared(self):
        """XML 裡宣告的每條 cron 都真的建進 ir.cron（ref 解析得到）。"""
        missing = []
        for xml_id, _model_ref, _code in _cron_records():
            ref = 'dobtor_doc_editor.%s' % xml_id
            if not self.env.ref(ref, raise_if_not_found=False):
                missing.append(xml_id)
        self.assertFalse(
            missing,
            '這些 cron 在 XML 裡宣告了但 ir.cron 裡沒有：%s。'
            '通常是 manifest 的 data 沒帶到那支 XML。' % missing,
        )
