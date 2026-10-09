{
    'name': 'Dobtor Doc Import',
    'version': '18.0.1.1.0',
    'summary': 'DOCX / ODT 匯入成 Dobtor 文件（含自寫 OOXML 管線）',
    'description': """
Dobtor Doc Import
=================
把 .docx / .odt 匯入成 `doc.document`，兩條解析路徑並存：

- **LibreOffice headless → HTML**（預設、穩定）
  缺 LibreOffice 時退回 python-docx / odfpy 的純 Python 解析。
- **自寫 OOXML 管線**（`engine=ts` 與瀏覽器端 `importViaBrowserParser()`）
  驗收通道：同一個 parser 兩條執行路徑，可當場比對輸出。

也提供批次匯入精靈，與 OOXML 管線的字型服務路由。

從 `dobtor_doc_editor` 拆出來的理由
-----------------------------------
匯入這條線的規模（TS 約 31,000 行、208 支 vitest、82MB fixture）比核心編輯器
還大，而它與核心的介面很窄——只透過 `doc.document` / `doc.template` 的
`content_json`。混在一個模組裡，每次部署都要帶上整套解析器的測試資料。

與核心共用、**不**搬過來的：
- `doc_zip_guard`（zip bomb 防護）——核心的範本上傳也在用
- `doc_ins_syntax`（`+++INS+++` → Jinja2）——只有核心的範本上傳在用

選用 Python 套件（刻意不寫進 external_dependencies，理由同核心模組）：
  python-docx（DOCX 的純 Python fallback）、odfpy（.odt 解析）
    """,
    'category': 'Productivity',
    'author': 'Dobtor',
    'license': 'OPL-1',
    'depends': [
        'dobtor_doc_editor',
    ],
    'data': [
        'security/ir.model.access.csv',
        'wizards/doc_bulk_import_wizard_views.xml',
        'views/menu.xml',
        'views/test_layout.xml',
    ],
    'assets': {},
    'installable': True,
    'application': False,
    'auto_install': False,
}
