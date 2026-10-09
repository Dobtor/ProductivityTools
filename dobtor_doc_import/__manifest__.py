{
    'name': 'Dobtor Doc Import',
    'version': '18.0.2.1.0',
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
    'assets': {
        # 自寫的 OOXML Parser（瀏覽器端），全域 window.DobtorCanvasEditor。
        #
        # ☠️ 2026-10-09 之前這支**從未掛進任何 manifest**（ADR-032 修的）：
        #    rollup 產得出來、git 也追蹤著，但沒有 bundle 載它，所以瀏覽器端的
        #    parser 從頭到尾沒被執行過。那種「存在但不載入」不會報錯。
        #
        #    它**不含** canvas-editor 的編輯器 API（實測 executeSetValue /
        #    CanvasEvent / command.execute 皆 0 筆），所以與核心載的上游
        #    canvas-editor.umd.min.js 不衝突、不會有兩份實例。
        #
        # 代價：backend bundle 多 ~425KB。消費者是
        #    DocEditorIo.importViaBrowserParser()（在核心的 doc_editor_io.js，
        #    拆模組步驟 5 會改成由本模組 patch 進去）。
        #    刻意不加到 web.assets_frontend：portal 已要下載 1.5MB，
        #    而 portal 沒有這條驗收通道。
        'web.assets_backend': [
            'dobtor_doc_import/static/src/lib/canvas_editor/canvas-editor-custom.umd.js',
            # 把兩條匯入驗收通道 patch 進核心的 DocEditor。
            # 必須在 bundle 之後（它用 window.DobtorCanvasEditor），不過 Odoo 的
            # asset 走 define/require，順序其實無所謂——照相依序列著好讀。
            'dobtor_doc_import/static/src/components/patch_doc_editor_import.js',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
