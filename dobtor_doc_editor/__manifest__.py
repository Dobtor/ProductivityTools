{
    'name': 'Dobtor Doc Editor',
    'version': '18.0.15.2.0',
    'summary': 'Google Docs 等級的 native Odoo 文件編輯器',
    'description': """
Dobtor Doc Editor v2.1
======================
基於 Odoo 18 html_editor 建立的全功能文件編輯器：
- A4/A3/A5/Letter/Legal 頁面排版
- 自動分頁引擎（PaginationEngine）+ 手動分頁
- 頁首/頁尾（Singleton 模式）
- 欄位變數插入（OWL Dialog 選擇器）
- 多欄排版（2/3 欄 Section）
- AutoSave（Debounce + MaxWait + Idle）
- 離線緩存（OfflineManager）
- PDF / DOCX 匯出（後端 LibreOffice 高品質 + 前端草稿）
- DOCX / ODT 匯入
- 版本快照
- 多公司隔離

選用功能（需額外 pip 套件，未安裝時該功能停用、其餘正常）：
- python-docx：DOCX 匯出 fallback、上傳 DOCX 時轉換 +++INS+++ 舊語法
- docxtpl：上傳 .docx 模板填值
- odfpy：.odt 匯入
  pip install python-docx docxtpl odfpy
    """,
    'category': 'Productivity',
    'author': 'Dobtor',
    # Dobtor 模組授權統一政策：OPL-1（新舊模組皆是）。
    # 2026-10-09 由 LGPL-3 改為 OPL-1——變更前的查證與第三方盤點寫在根目錄的
    # LICENSE 與 LICENSES/README.md：depends 六支全為 LGPL-3 核心 Odoo（無
    # AGPL）、自有檔案零授權標頭、隨附的三支第三方檔案授權皆為寬鬆式
    # （JSZip 的 MIT/GPLv3 雙授權中選用 MIT）。
    # 已散布的 LGPL-3 版本其授權不受本次變更影響。
    'license': 'OPL-1',
    'depends': [
        'base',
        'web',
        'mail',
        'html_editor',
        'bus',
        'portal',
    ],
    # ─── 選用 Python 套件（刻意不寫進 external_dependencies）────────────
    #
    #   python-docx  DOCX 匯出的 fallback（LibreOffice 缺席時）、
    #                上傳 DOCX 時把 +++INS+++ 舊語法轉成 {{ }}
    #   docxtpl      fill_template（上傳 .docx 模板填值）
    #   odfpy        .odt 匯入解析
    #
    # 為什麼不宣告成 external_dependencies：
    #   這三個套件都只在函式內 lazy import，核心編輯器（canvas 編輯、存檔、
    #   PDF 匯出、模型變數快照與匯出）完全不需要它們。宣告了會讓整個模組
    #   因為「一個選用匯出格式的函式庫沒裝」而裝不起來——Odoo 18 的
    #   check_python_external_dependency 是硬性阻擋，不是警告。
    #
    # 缺套件時的行為：對應功能回傳明確訊息並指名該裝哪個 pip 套件，
    #   其餘功能照常。要啟用這些功能：
    #   pip install python-docx docxtpl odfpy
    'data': [
        'security/doc_groups.xml',
        'security/ir.model.access.csv',
        'security/doc_security.xml',
        'wizards/doc_field_picker_views.xml',
        'wizards/doc_qweb_import_wizard_views.xml',
        'views/doc_document_views.xml',
        'views/doc_template_views.xml',
        'views/doc_report_views.xml',
        'views/doc_output_views.xml',
        'views/report_entry_points_views.xml',
        'views/portal_templates.xml',
        'views/doc_telemetry_views.xml',
        'views/menu.xml',
        'data/doc_template_data.xml',
        'data/ir_cron_data.xml',
    ],
    'assets': {
        # tour：只在測試模式載入。前端有約 7000 行 JS 與 2000 行 OWL 模板，
        # Python 測試碰不到，而 OWL 會把渲染錯誤吞成一塊空白面板。
        'web.assets_tests': [
            'dobtor_doc_editor/static/tests/tours/*.js',
        ],
        'web.assets_backend': [
            # CSS
            'dobtor_doc_editor/static/src/css/doc_editor.css',
            # 清單視圖：點一筆直接進編輯器
            'dobtor_doc_editor/static/src/views/doc_document_list_open_editor.js',
            # Core 模組（AutoSave / Leader / Offline）
            'dobtor_doc_editor/static/src/core/auto_save_manager.js',
            'dobtor_doc_editor/static/src/core/leader_election.js',
            'dobtor_doc_editor/static/src/core/offline_manager.js',
            'dobtor_doc_editor/static/src/core/lazy_loader.js',
            # P2-4 監控與遙測
            'dobtor_doc_editor/static/src/core/telemetry.js',
            # Canvas 編輯器外部庫（必須在 doc_editor.js 之前載入）
            'dobtor_doc_editor/static/src/lib/canvas_editor/canvas-editor.umd.min.js',
            # shim：為 plugin-docx UMD 建立 window.canvasEditor 別名
            'dobtor_doc_editor/static/src/lib/canvas_editor/canvas-editor-shim.js',
            # DOCX 匯入/匯出 plugin
            'dobtor_doc_editor/static/src/lib/canvas_editor/canvas-editor-plugin-docx.umd.js',
            # Odoo 欄位選擇器 Dialog（Phase 8 ADR-022 復活，必須在 doc_editor.js 之前）
            'dobtor_doc_editor/static/src/components/doc_field_picker/doc_field_picker.xml',
            'dobtor_doc_editor/static/src/components/doc_field_picker/doc_field_picker.js',
            # Sprint G/H：jinja2 變數掃描器（純函式 util，必須在 doc_editor.js 之前）
            'dobtor_doc_editor/static/src/components/doc_editor/jinja2_scanner.js',
            # 主編輯器 Component
            'dobtor_doc_editor/static/src/components/doc_editor/doc_editor.xml',
            # doc_editor 拆成四層 mixin + 共用常數（見各檔檔頭）。
            # 順序無所謂（Odoo 的 asset 走 define/require），但照相依序列著好讀。
            'dobtor_doc_editor/static/src/components/doc_editor/doc_editor_shared.js',
            'dobtor_doc_editor/static/src/components/doc_editor/doc_editor_shell.js',
            'dobtor_doc_editor/static/src/components/doc_editor/doc_editor_io.js',
            'dobtor_doc_editor/static/src/components/doc_editor/doc_editor_pills.js',
            'dobtor_doc_editor/static/src/components/doc_editor/doc_editor_templateui.js',
            'dobtor_doc_editor/static/src/components/doc_editor/doc_editor.js',
            # 版本歷史面板（W7-8 P1-1）
            'dobtor_doc_editor/static/src/components/doc_version_panel/doc_version_panel.xml',
            'dobtor_doc_editor/static/src/components/doc_version_panel/doc_version_panel.js',
            'dobtor_doc_editor/static/src/components/doc_version_panel/doc_version_panel.css',
            # ☠️ 這裡原本有 15 行被註解掉的 HTML/Wysiwyg 時代舊資源
            #    （標「保留備查」，無條件無期限）。2026-10-09 全檔案稽核量到
            #    它們唯一的引用者是 tests/test_manifest_assets.py 那份宣告它們
            #    沒用的例外清單——於是連檔案一起刪了（git 保留歷史）。
        ],
        # ── Portal / Website frontend bundle（W2-3 P0-1 最後一哩）──
        # 為什麼必須在 `web.assets_frontend` 而不是自訂 bundle：
        #   Odoo 18 把所有 @odoo-module JS 編譯成 `odoo.define(...)` 呼叫，
        #   而 `odoo.define` 是 `web.assets_frontend` 標準 bundle 啟動時建立的。
        #   自訂 bundle 用 t-call-assets 注入時，`odoo.define` 還未就緒 → TypeError。
        #   Odoo 18 沒有 inter-bundle dependency 機制，唯一可靠做法是放這裡。
        # 副作用：所有 portal 頁面都會下載 1.5MB（含 canvas-editor.umd 184KB），
        #   但只第一次訪問會付出代價，後續走瀏覽器快取。
        'web.assets_frontend': [
            # CSS
            'dobtor_doc_editor/static/src/css/doc_editor.css',
            # Core 模組（AutoSave / Leader / Offline / Telemetry）
            'dobtor_doc_editor/static/src/core/auto_save_manager.js',
            'dobtor_doc_editor/static/src/core/leader_election.js',
            'dobtor_doc_editor/static/src/core/offline_manager.js',
            'dobtor_doc_editor/static/src/core/telemetry.js',
            # Canvas 編輯器外部庫（順序：lib → shim → plugin → component → loader）
            'dobtor_doc_editor/static/src/lib/canvas_editor/canvas-editor.umd.min.js',
            'dobtor_doc_editor/static/src/lib/canvas_editor/canvas-editor-shim.js',
            'dobtor_doc_editor/static/src/lib/canvas_editor/canvas-editor-plugin-docx.umd.js',
            # Sprint G/H：jinja2 變數掃描器（純函式 util，必須在 doc_editor.js 之前）
            'dobtor_doc_editor/static/src/components/doc_editor/jinja2_scanner.js',
            # 主編輯器 Component
            'dobtor_doc_editor/static/src/components/doc_editor/doc_editor.xml',
            # doc_editor 拆成四層 mixin + 共用常數（見各檔檔頭）。
            # 順序無所謂（Odoo 的 asset 走 define/require），但照相依序列著好讀。
            'dobtor_doc_editor/static/src/components/doc_editor/doc_editor_shared.js',
            'dobtor_doc_editor/static/src/components/doc_editor/doc_editor_shell.js',
            'dobtor_doc_editor/static/src/components/doc_editor/doc_editor_io.js',
            'dobtor_doc_editor/static/src/components/doc_editor/doc_editor_pills.js',
            'dobtor_doc_editor/static/src/components/doc_editor/doc_editor_templateui.js',
            'dobtor_doc_editor/static/src/components/doc_editor/doc_editor.js',
            # 版本歷史面板（讓 portal 協作者也能查看歷次儲存）
            'dobtor_doc_editor/static/src/components/doc_version_panel/doc_version_panel.xml',
            'dobtor_doc_editor/static/src/components/doc_version_panel/doc_version_panel.js',
            'dobtor_doc_editor/static/src/components/doc_version_panel/doc_version_panel.css',
            # Portal 端註冊 entry（在 component 之後載入）
            'dobtor_doc_editor/static/src/components/portal_doc_editor_loader.js',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
