# -*- coding: utf-8 -*-
r"""收緊 doc.document 的 manager record rule——既有資料庫不會自動拿到這個修正。

☠️ 為什麼需要 migration：`security/doc_security.xml` 整份包在
`<data noupdate="1">` 裡。那個旗標的意思是「這些記錄建立之後，`-u` 不要再去
更新它們」——它保護的是使用者在 UI 上調過的權限設定，不會被升級覆蓋回去。

**副作用是：改 XML 對既有資料庫完全無效。** 2026-10-09 的實測就是這樣：
XML 已經改好、`-u` 跑完，而 DB 裡 `rule_doc_document_manager_all` 的
`domain_force` 仍然是 `[(1, '=', 1)]`，測試照樣紅。新安裝拿得到修正、
既有資料庫拿不到——那是最糟的一種「修好了」。

修的是什麼缺陷：Odoo 的**非 global rule 之間是 OR**，所以 manager 那條
`[(1, '=', 1)]` 把 `rule_doc_document_company` 的公司範圍整條 OR 掉了，
manager 讀得到**所有公司**的文件內容。對照 `rule_doc_output_manager_all` 與
`rule_doc_editor_export_log_company`，它們的 manager rule 都有公司範圍
——doc.document 是三者裡唯一沒有的，而它是裝文件內容的那一個。

這支刻意**只在 domain 還是舊值時才改**：如果管理員自己在 UI 上調過那條 rule，
就不要覆蓋他的決定（那正是 noupdate 存在的理由）。
"""
import logging

_logger = logging.getLogger(__name__)

_OLD_DOMAIN = "[(1, '=', 1)]"
_NEW_DOMAIN = (
    "['|', ('company_id', '=', False), ('company_id', 'in', company_ids)]"
)


def migrate(cr, version):
    if not version:
        # 全新安裝：XML 已經是新值，不需要也不應該動
        return
    cr.execute("""
        SELECT r.id, r.domain_force
          FROM ir_rule r
          JOIN ir_model_data d
            ON d.res_id = r.id AND d.model = 'ir.rule'
         WHERE d.module = 'dobtor_doc_editor'
           AND d.name = 'rule_doc_document_manager_all'
    """)
    row = cr.fetchone()
    if not row:
        _logger.warning(
            "[18.0.15.2.0] 找不到 rule_doc_document_manager_all"
            "——跳過（這條 rule 被刪掉了？）")
        return
    rule_id, current = row
    if (current or '').strip() != _OLD_DOMAIN:
        _logger.info(
            "[18.0.15.2.0] rule_doc_document_manager_all 的 domain 不是預期的"
            "舊值（目前是 %r）——有人調過，不覆蓋他的決定。"
            "若那個值沒有公司範圍，請自行確認多公司隔離。", current)
        return
    cr.execute(
        "UPDATE ir_rule SET domain_force = %s WHERE id = %s",
        (_NEW_DOMAIN, rule_id))
    _logger.info(
        "[18.0.15.2.0] 已把 rule_doc_document_manager_all 收斂到自己的公司範圍"
        "（原本 [(1,'=',1)] 會把 rule_doc_document_company 的公司隔離 OR 掉，"
        "manager 讀得到所有公司的文件）。")
