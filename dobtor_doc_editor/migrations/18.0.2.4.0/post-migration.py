"""Phase 5（藥丸改版）：alias token → 自描述藥丸元素的一次性遷移。

實作在 models/doc_alias_migration.py，本檔只負責在升級時觸發並記錄報表。

動工前請先乾跑，確認 expression_fallbacks 與 skipped_split 的實際數量：

    env['doc.alias.migration'].run(dry_run=True)

沒有「已簽署／已歸檔文件跳過」的邏輯——本模組的 doc.document 目前沒有
state 或 active 欄位可據以判斷。若日後加入簽署狀態，這裡要補上排除條件。
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    if 'doc.alias.migration' not in env:
        _logger.warning('[18.0.2.4.0] doc.alias.migration 未載入，略過 alias 遷移')
        return
    stats = env['doc.alias.migration'].run(dry_run=False)
    _logger.info(
        '[18.0.2.4.0] alias 遷移完成：'
        '範本 %(templates_scanned)s / 文件 %(documents_scanned)s 掃描，'
        '%(records_changed)s 筆改寫，產生 %(pills_created)s 個藥丸；'
        'expression 類 %(expression_fallbacks)s、'
        '僅有 HTML 待開檔升級 %(skipped_no_json)s、'
        '被樣式切斷 %(skipped_split)s；'
        '舊 odoo_field 記錄轉換 %(legacy_fields_converted)s、'
        '孤兒 %(legacy_fields_orphaned)s',
        stats,
    )
