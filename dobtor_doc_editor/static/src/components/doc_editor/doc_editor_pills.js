/** @odoo-module **/
/**
 * DocEditorPills — 藥丸：取值、標記、條件、重複、分組、檢視器。
 * 
 * 這一層最大（原本 doc_editor.js 近一半），因為藥丸是這個模組的核心
 * 抽象。對應後端的 doc.render.mixin——**兩邊的 source 名稱必須一致**，
 * 不一致的症狀是藥丸在文件上原樣印出標籤文字而且不報錯。
 *
 * 這是 doc_editor.js 拆出來的一層（mixin 工廠），由 doc_editor.js
 * 組合。拆的理由不是檔案太大，是**每一層的不變量要寫在自己的檔頭**。
 *
 * ☠️ import 區塊是整份照抄原檔的，沒有裁掉用不到的。理由：少一個 import
 * 的症狀是執行期 ReferenceError，而 OWL 會把它吞成一塊空白面板；
 * 多一個 import 沒有任何代價。**不要在 import {} 裡面加註解**——Odoo 的
 * asset compiler 不會 strip 它，會輸出 require({) 讓整個 bundle 掛掉。
 *
 * 後端對應：models/render/snapshot.py（pass 鏈）與 sandbox.py（求值）。
 */
import { Component, useState, onMounted, onWillUnmount, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";
import { AutoSaveManager } from "../../core/auto_save_manager";
import { LeaderElection } from "../../core/leader_election";
import { OfflineManager } from "../../core/offline_manager";
import { installGlobalErrorReporting, mark, reportError } from "../../core/telemetry";
import { DocVersionPanel } from "../doc_version_panel/doc_version_panel";
import { DocFieldPickerDialog } from "../doc_field_picker/doc_field_picker";
import {
    scanJinja2Variables,
    scanJinja2VariablesWithPositions,
    scanJinja2VariablesInTables,
    analyzeScanResults,
    computeOrphanRecordIds,
    findMarkerPositionsInMain,
    rewriteTdValueWithControls,
    flattenElementsToText,
} from "./jinja2_scanner";
import {
    FONT_OPTIONS,
    FONT_SIZE_OPTIONS,
    _lsGet,
    _lsSet,
    DOBTOR_FIELD_KEY,
    DOBTOR_BLOCK_KEY,
    I18N_PILL_STYLE,
    SCALAR_FIELD_TYPES,
    PILL_STYLE,
    SIGNER_COLORS,
    signerColor,
    VALUE_SOURCES,
    FIELD_TYPES,
} from "./doc_editor_shared";

export const DocEditorPills = (Base) => class extends Base {

    // ═══ 條件式列印 ═══════════════════════════════════════════════════
    //
    // 三種機制在後端（doc.render.mixin）：自動收合空段落、source='condition'、
    // repeat 的 filter。前端要做的是入口與編輯。
    //
    // 「欄位有值才印」那一類（真實報表裡佔一半）由自動收合處理，使用者什麼都
    // 不用設——所以這裡的入口只服務「值比較／複合邏輯」那些真的需要表達式的。

    /** 常用條件範例，給 inspector 當提示用（點了直接填入）。 */
    static CONDITION_PRESETS = [
        { label: "欄位有值", expr: "object.欄位名" },
        { label: "欄位沒值", expr: "not object.欄位名" },
        { label: "值等於", expr: "object.state == 'sale'" },
        { label: "兩欄位不同", expr: "object.partner_shipping_id != object.partner_invoice_id" },
        { label: "明細中有折扣", expr: "object.order_line|selectattr('discount')|list|length > 0" },
    ];

    /**
     * 插入條件標記。放在哪就控制哪個範圍：
     *   段落內 → 條件為假整段移除
     *   表格列內 → 條件為假該列移除
     *
     * 刻意允許「未設定」就插入——空表達式在後端等於恆真，所以不會造成傷害，
     * 而標記上的「未設定」字樣會提醒使用者去填。用 modal 強迫先填反而讓
     * 「先插好位置再想條件」這個自然流程變難。
     */
    onInsertCondition(expression = "") {
        if (!this.canPlaceVariables) {
            this.notification.add("目前的版面或權限不允許放置變數。", { type: "warning" });
            return;
        }
        const label = expression
            ? `條件：${expression}`
            : "條件（未設定）";
        const ok = this.insertPill({
            source: "condition",
            expression: expression,
            labelText: label,
        });
        if (ok && !expression) {
            this.notification.add(
                "已插入條件標記。請在右欄填入條件表達式——未填時等於「永遠列印」。",
                { type: "info" }
            );
        }
    }

    /** 從欄位清單一鍵建立「此欄位有值才印」條件。 */
    onInsertFieldCondition(field, parent = null) {
        const path = parent ? `${parent.name}.${field.name}` : field.name;
        this.onInsertCondition(`object.${path}`);
    }

    /**
     * 插入欄條件標記。放在要控制的那一欄的任一格（通常是表頭）。
     *
     * 列條件與欄條件是對稱的兩件事——表格有 colgroup，欄邊界跟列一樣可靠。
     * 原生報表的折扣欄就是這種寫法：同一個 t-if 掛在 <th> 與每一列的 <td> 上。
     */
    onInsertColumnCondition(expression = "") {
        if (!this.canPlaceVariables) {
            this.notification.add("目前的版面或權限不允許放置變數。", { type: "warning" });
            return;
        }
        const ok = this.insertPill({
            source: "column",
            expression,
            labelText: expression ? `欄條件：${expression}` : "欄條件（未設定）",
        });
        if (ok) {
            this.notification.add(
                "已插入欄條件標記。放在哪一格就控制那一欄——條件為假時整欄（含表頭）不印。",
                { type: "info" }
            );
        }
    }

    /**
     * 插入條件式格式標記。放在表格列內＝整列，放在段落裡＝整段。
     *
     * 為什麼需要它：原生報表用 t-att-class 做「章節列要粗體、備註列要斜體」
     *   <tr t-att-class="'fw-bold' if line.display_type == 'line_section' …">
     * 而範本只吃得懂靜態 class，條件式的那些本來只能留待辦。
     *
     * 與條件標記刻意對稱（同一套心智模型）：標記放哪裡就決定作用範圍。
     * 失敗策略相反——條件算不出來時「不套用」：格式套錯（整份變粗體）
     * 比沒套上難追得多。
     */
    onInsertFormatMarker(expression = "") {
        if (!this.canPlaceVariables) {
            this.notification.add("目前的版面或權限不允許放置變數。", { type: "warning" });
            return;
        }
        const ok = this.insertPill({
            source: "format",
            expression,
            bold: true,
            labelText: "條件格式",
        });
        if (ok) {
            this.notification.add(
                "已插入條件式格式。放在表格列內＝整列套用、放在段落裡＝整段套用；"
                + "條件算不出來時不套用。",
                { type: "info" }
            );
        }
    }

    get isFormatPill() {
        return (this.state.selectedVariable || {}).source === "format";
    }

    get FORMAT_ALIGNS() {
        return [
            { value: "", label: "不變" },
            { value: "left", label: "靠左" },
            { value: "center", label: "置中" },
            { value: "right", label: "靠右" },
        ];
    }

    onFormatPropertyChange(key, value) {
        this.updateSelectedPill({ [key]: value });
    }


    // ═══ 圖片 / 地址 / 頁碼 ════════════════════════════════════════

    /**
     * 插入圖片藥丸（客戶簽名、公司 logo…）。
     *
     * 編輯器裡顯示為藥丸而不是圖片——藥丸是設計期的宣告，而且編輯範本時
     * 根本還沒有「那一筆記錄」可以取圖。快照時才求值，攤平時變成真正的
     * image 元素。
     *
     * 只接 binary 欄位：binary 的值是 base64 bytes，經過 Jinja 會變成
     * "b'iVBOR...'" 的 repr，所以後端走欄位路徑直接取值，不求表達式。
     */
    onInsertImageField(field, parent = null) {
        if (!this.canPlaceVariables) {
            this.notification.add("目前的版面或權限不允許放置變數。", { type: "warning" });
            return;
        }
        const path = parent ? `${parent.name}.${field.name}` : field.name;
        this.insertPill({
            source: "image",
            path,
            labelText: `圖：${field.label || field.name}`,
        });
    }

    /** 插入條碼／QR（走圖片藥丸，所以輸出是 <img> 而不是一串 base64）。 */
    onInsertBarcode(field = null) {
        if (!this.canPlaceVariables) {
            this.notification.add("目前的版面或權限不允許放置變數。", { type: "warning" });
            return;
        }
        const path = field ? field.name : "name";
        this.insertPill({
            source: "image",
            barcodeType: "QR",
            path,
            labelText: `條碼：${field ? (field.label || field.name) : "單號"}`,
        });
    }

    get BARCODE_TYPES() {
        return ["QR", "Code128", "Code39", "EAN13", "EAN8", "UPCA"];
    }

    get isBarcodePill() {
        const v = this.state.selectedVariable || {};
        return v.source === "image" && !!v.barcodeType;
    }

    get isImagePill() {
        return (this.state.selectedVariable || {}).source === "image";
    }

    // 圖片的來源可以是欄位路徑，也可以是算出來的表達式（發票的付款 QR 就是
    // partner_bank_id.build_qr_code_base64(...) 的結果，不對應任何欄位）。
    // 只顯示 path 的話，表達式型的圖片會寫「（未設定）」——使用者會以為壞了，
    // 然後去設一個欄位把表達式蓋掉。
    get imageSourceLabel() {
        const v = this.state.selectedVariable || {};
        if (v.path) {
            return v.path;
        }
        return v.expression ? "（用下方的來源表達式）" : "（未設定）";
    }

    onImagePropertyChange(key, value) {
        const num = parseInt(value, 10);
        this.updateSelectedPill({
            [key]: Number.isFinite(num) && num > 0 ? num : "",
        });
    }

    /** 插入依國別格式排版的地址（對應原生的 widget="contact"）。 */
    onInsertAddress(field) {
        if (!this.canPlaceVariables) {
            this.notification.add("目前的版面或權限不允許放置變數。", { type: "warning" });
            return;
        }
        this.insertPill({
            source: "expression",
            expression: `format_address(object.${field.name})`,
            labelText: `地址：${field.label || field.name}`,
        });
    }

    /**
     * 插入頁碼／總頁數。
     *
     * 只在 PDF 與 DOCX 有意義，而且要放在頁首或頁尾——放在本文裡 wkhtmltopdf
     * 不會替換（替換 JS 只套用在被抽出來的 header/footer 上）。
     */
    /**
     * 插入「頁面範圍標記」——這一段只在某些頁出現。
     *
     * 對應 LibreOffice Writer 頁首／頁尾的「首頁相同」與「左右頁相同」兩個
     * 勾選，但做法不同：那兩個是版面設定，這裡是標記。原因是我們的頁首頁尾
     * 是一份 HTML，wkhtmltopdf 每一頁重載一次並在網址帶 page 參數——
     * 「哪一段要出現」只能在那一刻決定，後端不知道這一頁是第幾頁。
     *
     * 業務上最常用的三個：
     *   首頁   公司信紙（logo＋完整公司資訊）只印第一頁
     *   續頁   第 2 頁起才印「（接前頁）」與單號
     *   奇／偶 雙面列印時頁碼放外側、裝訂邊左右交換
     */
    onInsertPageScope(scope) {
        if (!this.canPlaceVariables) {
            this.notification.add("目前的版面或權限不允許放置變數。", { type: "warning" });
            return;
        }
        const labels = {
            first: "只在首頁", rest: "只在續頁",
            odd: "只在奇數頁", even: "只在偶數頁",
        };
        const ok = this.insertPill({
            source: "pageScope",
            scope,
            isMarker: true,
            labelText: labels[scope] || "頁面範圍",
        });
        if (ok) {
            this.notification.add(
                "這個標記讓它所在的那一段只在指定的頁出現，而且只在頁首／頁尾生效。",
                { type: "info" }
            );
        }
    }

    get isPageScopePill() {
        return (this.state.selectedVariable || {}).source === "pageScope";
    }

    onInsertPageField(part) {
        if (!this.canPlaceVariables) {
            this.notification.add("目前的版面或權限不允許放置變數。", { type: "warning" });
            return;
        }
        const ok = this.insertPill({
            source: "page",
            part,
            labelText: part === "count" ? "總頁數" : "頁碼",
        });
        if (ok) {
            this.notification.add(
                "頁碼要放在頁首或頁尾才會替換成實際頁次；放在本文內不會生效。",
                { type: "info" }
            );
        }
    }

    get isPagePill() {
        return (this.state.selectedVariable || {}).source === "page";
    }


    // ═══ Html 欄位藥丸 ═════════════════════════════════════════════

    /**
     * 插入 Html 欄位藥丸（條款、公司資訊、頁尾文字…）。
     *
     * 純量藥丸會把 Html 欄位的值逸出成可見的 <p>、<strong> 標籤，而且完全
     * 不報錯。後端這個 source 會過 html_sanitize 並以區塊級輸出。
     */
    onInsertHtmlField(field, parent = null) {
        if (!this.canPlaceVariables) {
            this.notification.add("目前的版面或權限不允許放置變數。", { type: "warning" });
            return;
        }
        const path = parent ? `${parent.name}.${field.name}` : field.name;
        this.insertPill({
            source: "html",
            path,
            labelText: `HTML：${field.label || field.name}`,
        });
    }

    get htmlFields() {
        const q = (this.state.modelFieldFilter || "").trim().toLowerCase();
        const list = (this.state.modelFields || []).filter(f => f.type === "html");
        if (!q) return list;
        return list.filter(f =>
            (f.label || "").toLowerCase().includes(q) ||
            (f.name || "").toLowerCase().includes(q)
        );
    }

    get isHtmlPill() {
        return (this.state.selectedVariable || {}).source === "html";
    }


    // ═══ i18n 靜態文字 ═════════════════════════════════════════════
    //
    // 欄位「值」的語言由 doc.report 的 lang 與 ORM 負責（商品名稱、selection
    // 標籤都會自動翻譯）。這裡只處理「使用者自己打進範本的靜態文字」。
    //
    // 為什麼不是「一種語言一張範本」：真正的維護痛點不是 N 份文字（.po 也是
    // N 份，省不掉），是 N 份版面——改一次表格欄寬要改 N 張，漏掉哪一張
    // 完全看不出來。i18n 藥丸讓版面只有一份。

    async loadLanguages() {
        if (this.state.languages.length) return;
        try {
            const langs = await rpc("/dobtor_doc/i18n/languages", {});
            this.state.languages = Array.isArray(langs) ? langs : [];
        } catch (e) {
            console.warn("[DocEditor] 載入語言清單失敗", e);
        }
    }

    onInsertI18nText(text = "") {
        if (!this.canPlaceVariables) {
            this.notification.add("目前的版面或權限不允許放置變數。", { type: "warning" });
            return;
        }
        const lang = this.state.previewLang || this.state.languages[0]?.code || "en_US";
        const label = text || "多語文字";
        this.insertPill({
            source: "i18n",
            texts: text ? { [lang]: text } : {},
            labelText: label,
            style: I18N_PILL_STYLE,
        });
        this.loadLanguages();
    }


    // ═══ 條件區塊（多段內容的條件）═════════════════════════════════
    //
    // 區塊級條件真正缺的是「可靠邊界」。元素串列是扁平的，只有換行與表格列
    // 是可靠邊界，跨段落的起訖標記在使用者編輯時極易被拆散——而拆散後的結果
    // 無從察覺。表格則是原子結構：使用者刪就整個刪，不可能只剩半邊。
    //
    // 所以「條件區塊」＝一個無框線的單格表格，列上掛條件標記，後端既有的
    // _apply_row_conditions 一行都不用改就能整塊移除。
    // if/else 則是同一個表格的兩列共用一個 groupId——兩個分支因此不可能被分開。

    _newGroupId() {
        return "cg" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
    }

    /**
     * 依文件順序收集所有表格元素。
     *
     * 不用 element.id 認表格：canvas-editor 的 getValue() 序列化白名單裡
     * 沒有 id（只有 getElementById 會用 extraPickAttrs 把它撈回來），
     * 所以 getValue().data 上的表格一律沒有 id，id 差集永遠是空的。
     */
    _collectTables(data) {
        const out = [];
        const visit = (list) => {
            for (const el of list || []) {
                if (!el || typeof el !== "object") continue;
                if (el.type === "table") out.push(el);
                if (Array.isArray(el.valueList)) visit(el.valueList);
                for (const row of el.trList || []) {
                    for (const cell of row.tdList || []) {
                        if (Array.isArray(cell.value)) visit(cell.value);
                    }
                }
            }
        };
        for (const zone of ["header", "main", "footer"]) {
            if (Array.isArray(data[zone])) visit(data[zone]);
        }
        return out;
    }

    /**
     * 表格的內容簽章（列數×欄數＋各格文字）。
     *
     * 刻意只看內容、不看幾何：插入新表格可能讓既有表格重新分頁而改變
     * height，拿整份 JSON 比對會在前面就出現假差異，然後把使用者既有的
     * 表格改成區塊容器——那是最糟的失敗方式。
     */
    _tableSignature(table) {
        const rows = table.trList || [];
        const cols = rows.length ? (rows[0].tdList || []).length : 0;
        const text = rows
            .map((row) => (row.tdList || [])
                .map((cell) => (cell.value || [])
                    .map((e) => (e && e.value) || "").join(""))
                .join("\u0001"))
            .join("\u0002");
        return `${rows.length}x${cols}|${text}`;
    }

    /**
     * 插入一個區塊容器：無框線表格，每一列一個分支。
     *
     * canvas-editor 的 executeInsertTable 只接 (列數, 欄數)，不能一併帶
     * borderType / extension；而它插完之後 caret 停在表格元素本身而不是儲存格內，
     * 所以接著呼叫 insertPill 會把藥丸放到表格外面去。
     * 作法因此是：插表格 → 用 id 差集認出新表格 → 直接改寫它 → setValue 回去。
     *
     * @param {string} blockKind 後端 _element_block_kind 讀的區塊種類
     * @param {Array<Array<Array<Object>>>} grid 列 → 格 → 藥丸綁定定義
     */
    insertBlockContainer(blockKind, grid) {
        if (!this.canPlaceVariables) {
            this.notification.add("目前的版面或權限不允許放置變數。", { type: "warning" });
            return false;
        }
        if (!this.editor) {
            this.notification.add("編輯器尚未初始化", { type: "warning" });
            return false;
        }
        let beforeSigs;
        try {
            beforeSigs = this._collectTables(this.editor.command.getValue().data)
                .map((t) => this._tableSignature(t));
        } catch (e) {
            console.error("[DocEditor] 讀取內容失敗", e);
            return false;
        }
        const colCount = Math.max(1, ...grid.map((row) => row.length));
        try {
            this.editor.command.executeInsertTable(grid.length, colCount);
        } catch (e) {
            console.error("[DocEditor] 插入區塊容器失敗", e);
            this.notification.add(`插入區塊失敗：${e.message || e}`, { type: "danger" });
            return false;
        }
        let data;
        try {
            data = this.editor.command.getValue().data;
        } catch (e) {
            return false;
        }
        const afterTables = this._collectTables(data);
        if (afterTables.length === beforeSigs.length) {
            // 完全沒多出表格＝canvas-editor 的 insertTable 直接 return 了。
            // 它在沒有有效游標時會靜默不做事（insertTable 開頭就
            // `if (!~startIndex && !~endIndex) return`）。
            // 這種情況講「已插入表格但無法標記」是錯的——使用者會去復原一個
            // 不存在的表格。瀏覽器 tour 就是這樣抓到這條訊息寫錯。
            this.notification.add(
                "請先在文件中點一下，決定區塊要插入的位置。",
                { type: "warning" }
            );
            return false;
        }
        if (afterTables.length !== beforeSigs.length + 1) {
            // 認不出新表格就不亂改既有內容——寧可讓使用者看到一個普通表格，
            // 也不要把條件標記塞進他別的表格裡。
            this.notification.add(
                "已插入表格，但無法自動標記為區塊。請復原後重試。",
                { type: "warning" }
            );
            return false;
        }
        // 剛好多了一個表格，所以「前後簽章第一個不一致的位置」就是新表格。
        // 兩者簽章相同（例如旁邊本來就有一個空表格）時取較前者也正確——
        // 游標在那個位置，使用者期待區塊出現在那裡。
        let idx = beforeSigs.length;
        for (let i = 0; i < beforeSigs.length; i++) {
            if (this._tableSignature(afterTables[i]) !== beforeSigs[i]) {
                idx = i;
                break;
            }
        }
        const table = afterTables[idx];
        if (!table) return false;
        // dash：編輯時看得到虛線框（區塊要找得到才能編輯），輸出時由
        // .doc-block 的 CSS 關掉框線——兩邊的需求相反，所以分開處理。
        table.borderType = "dash";
        table.extension = { ...(table.extension || {}), [DOBTOR_BLOCK_KEY]: blockKind };
        (table.trList || []).forEach((row, r) => {
            (grid[r] || []).forEach((metas, c) => {
                const cell = (row.tdList || [])[c];
                if (!cell || !metas.length) return;
                const pills = metas.map((m) => this._buildPillElement(m));
                cell.value = [...pills, ...(Array.isArray(cell.value) ? cell.value : [])];
            });
        });
        try {
            this.editor.command.executeSetValue(data);
        } catch (e) {
            console.error("[DocEditor] 寫回區塊容器失敗", e);
            return false;
        }
        return true;
    }

    /** 插入單一條件區塊：條件為假時整塊（含多段內容）不印。 */
    onInsertConditionBlock() {
        const ok = this.insertBlockContainer("condition", [
            [[{ source: "condition", expression: "", labelText: "條件（未設定）" }]],
        ]);
        if (ok) {
            this.notification.add(
                "已插入條件區塊。區塊內可以放多段內容；請在右欄填入條件表達式。",
                { type: "info" }
            );
        }
    }

    /**
     * 插入 if / else 區塊：同一個表格的兩列共用一個 groupId。
     *
     * else 那一列不帶自己的表達式，後端取同群 if 的反值——只有一處表達式要維護。
     * 放在同一個表格而不是兩個獨立區塊，是為了讓兩個分支不可能被分開：
     * 分開之後使用者改了 if 卻沒改 else，結果會是兩段都印或都不印，而且不會報錯。
     */
    onInsertIfElseBlock() {
        const gid = this._newGroupId();
        const ok = this.insertBlockContainer("condition", [
            [[{
                source: "condition", groupId: gid, role: "if",
                expression: "", labelText: "若（未設定）",
            }]],
            [[{
                source: "condition", groupId: gid, role: "else",
                labelText: "否則",
            }]],
        ]);
        if (ok) {
            this.notification.add(
                "已插入「若／否則」兩個區塊。只要設定上半部的條件，下半部自動取反。",
                { type: "info" }
            );
        }
    }

    /**
     * 插入稅額彙總區塊：三列兩欄，稅別那列會依稅別數自動複製。
     *
     * 對應原生報表的 t-call="sale.document_tax_totals"。做成內建區塊而不是
     * 讓使用者自己對 object.tax_totals['subtotals'] 重複，是因為那個資料結構
     * 每個 Odoo 版本都在改（amount_by_group 在 18 已消失）——內建區塊升版時
     * 改模組一處，通用寫法則是每張範本都要改，而且錯了只會印出空白。
     */
    onInsertTaxTotalsBlock() {
        const val = (part, field, labelText) => ({
            source: "taxTotals", part, field, labelText,
        });
        // 稅前小計與稅別的名稱是 Odoo 給的（已依記錄語言翻好），
        // 「總計」與「現金捨入」是我們自己寫的字——用多語文字藥丸，
        // 寫死中文的話英文單據上會夾一個中文的「總計」。
        // 後端靠「列內任一個 taxTotals 藥丸的 part」認列，不需要額外的標記藥丸。
        const i18n = (key, zh, en) => ({
            source: "i18n", key, labelText: zh, texts: { zh_TW: zh, en_US: en },
        });
        const ok = this.insertBlockContainer("taxTotals", [
            [[val("untaxed", "label", "稅前小計")], [val("untaxed", "amount", "金額")]],
            [[val("groups", "label", "稅別")], [val("groups", "amount", "稅額")]],
            [[i18n("doc_tax_rounding", "現金捨入", "Rounding")],
             [val("rounding", "amount", "捨入金額")]],
            [[i18n("doc_tax_total", "總計", "Total")],
             [val("total", "amount", "總計金額")]],
        ]);
        if (ok) {
            this.notification.add(
                "已插入稅額彙總。小計列依稅基數、稅別列依稅別數自動複製；"
                + "沒有稅或沒設現金捨入時那一列不印。",
                { type: "info" }
            );
        }
    }

    get isTaxTotalsPill() {
        return (this.state.selectedVariable || {}).source === "taxTotals";
    }

    get TAX_TOTALS_PARTS() {
        return [
            { value: "untaxed", label: "稅前小計" },
            { value: "groups", label: "稅別（每稅別一列）" },
            { value: "rounding", label: "現金捨入（沒設定就不印）" },
            { value: "total", label: "總計" },
        ];
    }

    get TAX_TOTALS_FIELDS() {
        return [
            { value: "label", label: "名稱" },
            { value: "amount", label: "金額" },
            { value: "base", label: "稅基" },
        ];
    }

    onTaxTotalsPropertyChange(key, value) {
        this.updateSelectedPill({ [key]: value });
    }

    get isElseMarker() {
        const v = this.state.selectedVariable || {};
        return v.source === "condition" && v.role === "else";
    }


    // ═══ 重複列（表格明細）═══════════════════════════════════════════
    //
    // 業務單據的核心需求：訂單明細、發票行。純量藥丸只能帶一個值。
    //
    // 設計上刻意不去「偵測游標在第幾列」——canvas-editor 的 range context 取不到
    // 穩定的列索引。改成：使用者按「設為重複列」時在游標處插一個標記藥丸，
    // 由後端 _expand_repeat_rows 找出「含該標記的那一列」。前端完全不必知道列號。

    /** 這個欄位可以當重複來源嗎（必須是 one2many / many2many）。 */
    _isRepeatable(field) {
        return ['one2many', 'many2many'].includes(field.type);
    }

    get repeatableFields() {
        return (this.state.modelFields || []).filter(f => this._isRepeatable(f));
    }

    /**
     * 把游標所在的表格列設為「對這個欄位重複」。
     *
     * 插入標記藥丸即完成宣告——使用者看得到哪一列會重複，刪掉標記就是取消。
     */
    async onSetRepeatRow(field) {
        if (!this.canPlaceVariables) {
            this.notification.add("目前的版面或權限不允許放置變數。", { type: "warning" });
            return;
        }
        if (!this._isRepeatable(field)) {
            this.notification.add(
                `「${field.label || field.name}」不是一對多欄位，不能當重複來源。`,
                { type: "warning" }
            );
            return;
        }
        const label = `明細 × ${field.label || field.name}`;
        // repeatId：一個表格裡有兩組重複列時，分組標題／小計列才知道自己屬於哪一組。
        // 單一重複列的情況後端會容忍沒帶 id 的分組列，所以這不是必填。
        const repeatId = "rp" + Date.now().toString(36)
            + Math.random().toString(36).slice(2, 6);
        const ok = this.insertPill({
            source: "repeat",
            path: field.name,
            labelText: label,
            relation: field.relation || "",
            repeatId,
        });
        if (!ok) return;
        this.state.repeatContext = {
            path: field.name,
            model: field.relation || "",
            label: field.label || field.name,
            repeatId,
            groupMode: "",
            groupBy: "",
            groupSplitOn: "",
        };
        this.state.lineFields = [];
        await this.loadLineFields();
        this.notification.add(
            `已將游標所在的表格列設為重複列。` +
            `現在可以從左欄「明細欄位」拖入 ${field.label || field.name} 的欄位。`,
            { type: "success", sticky: true }
        );
    }

    /**
     * 為同一筆明細再加一個「列型」。
     *
     * 對應原生報表在迴圈裡的 t-if / t-elif / t-else——商品列／備註列各自
     * 不同版面，而且必須保持原本的交錯順序。兩條獨立的重複列做不到：
     * 那會變成「所有商品」然後「所有備註」。
     *
     * 共用同一個 repeatId，來源／篩選／分組一律取第一個列型的設定。
     */
    onAddRowVariant() {
        if (!this.canPlaceVariables) {
            this.notification.add("目前的版面或權限不允許放置變數。", { type: "warning" });
            return;
        }
        const ctx = this.state.repeatContext;
        if (!ctx) {
            this.notification.add(
                "請先設定重複列，再加其他列型。",
                { type: "warning" }
            );
            return;
        }
        const ok = this.insertPill({
            source: "repeat",
            path: ctx.path,
            relation: ctx.model,
            repeatId: ctx.repeatId || "",
            rowFilter: "",
            labelText: `列型 × ${ctx.label}`,
        });
        if (!ok) return;
        this.notification.add(
            "已加入列型。請在右欄填「列型條件」——有條件的列型優先，" +
            "都不成立時才用條件留空的那一列。不必搬動既有的列。",
            { type: "success", sticky: true }
        );
    }

    /** 列型條件的常用寫法。 */
    get ROW_VARIANT_PRESETS() {
        return [
            { label: "備註列", expr: "line.display_type == 'line_note'" },
            { label: "章節列", expr: "line.display_type == 'line_section'" },
            { label: "有折扣的列", expr: "line.discount" },
        ];
    }

    onRowFilterChange(value) {
        const expr = (value || "").trim();
        const cur = this.state.selectedVariable || {};
        this.updateSelectedPill({
            rowFilter: expr,
            labelText: expr
                ? `列型 × ${cur.path || ""}（${expr.slice(0, 20)}）`
                : `明細 × ${cur.path || ""}`,
        });
    }

    /** 載入明細模型的欄位清單（給左欄的「明細欄位」組用）。 */
    async loadLineFields() {
        const ctx = this.state.repeatContext;
        if (!ctx || !ctx.model || this.state.lineFieldsLoading) return;
        if (this.state.lineFields.length) return;
        this.state.lineFieldsLoading = true;
        try {
            const fields = await rpc("/dobtor_doc/fields", {
                model_name: ctx.model,
                doc_id: this.state.docId || null,
            });
            this.state.lineFields = Array.isArray(fields) ? fields : [];
        } catch (e) {
            console.warn("[DocEditor] 載入明細欄位失敗", e);
            this.notification.add("載入明細欄位失敗", { type: "warning" });
        } finally {
            this.state.lineFieldsLoading = false;
        }
    }

    get filteredLineFields() {
        const q = (this.state.modelFieldFilter || "").trim().toLowerCase();
        const list = this.state.lineFields || [];
        if (!q) return list;
        return list.filter(f =>
            (f.label || "").toLowerCase().includes(q) ||
            (f.name || "").toLowerCase().includes(q)
        );
    }

    /** 明細欄位 → source='line' 的綁定定義（path 相對於當前明細）。 */
    _metaForLineField(field, parent = null) {
        const path = parent ? `${parent.name}.${field.name}` : field.name;
        const labelText = parent
            ? `${parent.label || parent.name}-${field.label || field.name}`
            : (field.label || field.name);
        // 同 _metaForModelField：只帶路徑，格式由渲染層依型別決定。
        // 明細藥丸求值時 object 綁的就是那筆明細，所以金額的幣別、float 的
        // digits 都查得到——不需要在這裡寫死任何表達式。
        return { source: "line", path, labelText };
    }

    onLineFieldDragStart(ev, field, parent = null) {
        if (!this.canPlaceVariables) {
            ev.preventDefault();
            return;
        }
        ev.dataTransfer.setData(
            "text/x-doc-odoo-field",
            JSON.stringify(this._metaForLineField(field, parent))
        );
        ev.dataTransfer.effectAllowed = "copy";
    }

    onLineFieldClick(field, parent = null) {
        if (!this.canPlaceVariables) return;
        this.insertPill(this._metaForLineField(field, parent));
    }

    /**
     * 從既有內容復原 repeatContext。
     *
     * 開檔時掃內容裡的 repeat 標記藥丸——否則重新開啟範本後
     * 左欄不會出現「明細欄位」，使用者得重新設一次重複列才能繼續加欄位。
     */
    _recoverRepeatContext() {
        if (!this.editor) return;
        let data;
        try {
            data = this.editor.command.getValue().data;
        } catch (e) {
            return;
        }
        let found = null;
        const visit = (list) => {
            for (const el of list || []) {
                if (found || !el || typeof el !== "object") continue;
                const meta = this._elementFieldMeta(el);
                if (meta && meta.source === "repeat") {
                    found = meta;
                    return;
                }
                if (Array.isArray(el.valueList)) visit(el.valueList);
                for (const row of el.trList || []) {
                    for (const cell of row.tdList || []) visit(cell.value);
                }
            }
        };
        for (const zone of ["header", "main", "footer"]) visit(data[zone]);
        if (found) {
            this.state.repeatContext = {
                path: found.path || "",
                model: found.relation || "",
                label: found.labelText || found.path || "",
                repeatId: found.repeatId || "",
                groupMode: found.groupMode || "",
                groupBy: found.groupBy || "",
                groupSplitOn: found.groupSplitOn || "",
            };
            this.loadLineFields();
        }
    }


    // ═══ 分組重複與流水累計 ═════════════════════════════════════════
    //
    // 為什麼做「分組」而不是 QWeb 那種累加器：累加器是 QWeb 只能單次順序掃描
    // 才被迫採用的實作手法，不是使用者的需求。使用者心裡想的是「依章節分組，
    // 每組印小計」。我們手上有完整 recordset，分組後直接聚合即可。
    // 在編輯器裡暴露「宣告變數／每列更新／歸零」等於要使用者寫程式，
    // 而且寫錯了只會印出錯的數字，什麼訊息都沒有。
    //
    // 真的需要跨列狀態的只剩兩個：項次（1,2,3…）與逐列累計。範圍小到可以
    // 直接放在後端展開的順序迴圈裡（source='running'）。

    /** 數值型明細欄位——只有這些適合做累計／小計。 */
    get numericLineFields() {
        return (this.state.lineFields || []).filter(
            (f) => ["integer", "float", "monetary"].includes(f.type)
        );
    }

    /** 插入「項次」藥丸（必須放在重複列內）。 */
    onInsertRunningIndex() {
        if (!this.state.repeatContext) {
            this.notification.add(
                "項次要放在重複列裡才有意義。請先設定重複列。",
                { type: "warning" }
            );
            return;
        }
        this.insertPill({
            source: "running",
            op: "index",
            resetOn: "",
            labelText: "項次",
        });
    }

    /** 插入「逐列累計」藥丸。 */
    onInsertRunningSum(field) {
        if (!this.state.repeatContext) {
            this.notification.add(
                "累計要放在重複列裡才有意義。請先設定重複列。",
                { type: "warning" }
            );
            return;
        }
        this.insertPill({
            source: "running",
            op: "sum",
            expression: `line.${field.name}`,
            resetOn: "",
            asMoney: field.type === "monetary",
            // 同 onInsertGroupSubtotal：累計是跨列狀態，不是欄位路徑，
            // 小數位要明講才會和明細欄一致
            numberFormat: `,.${field.digits ?? 2}f`,
            labelText: `累計 ${field.label || field.name}`,
        });
    }

    get isRunningPill() {
        return (this.state.selectedVariable || {}).source === "running";
    }

    onRunningPropertyChange(key, value) {
        const patch = { [key]: value };
        if (key === "op") {
            patch.labelText = value === "index" ? "項次" : "累計";
        }
        this.updateSelectedPill(patch);
    }


    // ─── 分組設定（掛在重複列標記上）───────────────────────────────

    get GROUP_MODES() {
        return [
            { value: "", label: "不分組" },
            { value: "field", label: "依欄位值" },
            { value: "marker", label: "依分隔列" },
        ];
    }

    /** 分隔判斷式的常用寫法（sale 的章節列就是這個）。 */
    get GROUP_SPLIT_PRESETS() {
        return [
            { label: "銷售訂單章節列", expr: "line.display_type == 'line_section'" },
            { label: "任何非商品列", expr: "line.display_type" },
        ];
    }

    onRepeatGroupChange(key, value) {
        const cur = this.state.selectedVariable || {};
        const patch = { [key]: value };
        if (key === "groupMode") {
            // 切換模式時清掉另一種模式的依據，否則面板看起來兩個都設了，
            // 而後端只會用其中一個——使用者會以為設定沒生效。
            if (value === "field") patch.groupSplitOn = "";
            else if (value === "marker") patch.groupBy = "";
            else {
                patch.groupBy = "";
                patch.groupSplitOn = "";
            }
        }
        const base = cur.path || "";
        const mode = key === "groupMode" ? value : (cur.groupMode || "");
        const flt = cur.filter ? "（已篩選）" : "";
        patch.labelText = mode
            ? `明細 × ${base}${flt}・分組`
            : `明細 × ${base}${flt}`;
        this.updateSelectedPill(patch);
        // repeatContext 也要同步：取消選取藥丸之後，左欄的分組列按鈕是靠它判斷的
        if (this.state.repeatContext) {
            this.state.repeatContext = { ...this.state.repeatContext, ...patch };
        }
    }

    /** 這個重複列有啟用分組嗎（決定要不要顯示分組列按鈕）。 */
    onRepeatSortChange(key, value) {
        this.updateSelectedPill({
            [key]: key === "sortDesc" ? !!value : (value || "").trim(),
        });
    }

    onRepeatSourceExpressionChange(value) {
        this.updateSelectedPill({ sourceExpression: (value || "").trim() });
    }

    /** 常用的來源表達式：排序與非 recordset 來源都走這裡。 */
    get REPEAT_SOURCE_PRESETS() {
        return [
            {
                label: "依序號排序",
                expr: "object.order_line|sort(attribute='sequence')",
            },
            {
                label: "排除非商品列",
                expr: "object.order_line|rejectattr('display_type')|list",
            },
            {
                label: "稅別清單",
                expr: "object.tax_totals['subtotals'][0]['tax_groups']",
            },
        ];
    }

    onTaxCurrencyModeChange(value) {
        this.updateSelectedPill({ currencyMode: value || "document" });
    }

    get repeatHasGrouping() {
        const v = this.state.selectedVariable || {};
        if (v.source === "repeat") {
            return !!(v.groupMode && (v.groupBy || v.groupSplitOn));
        }
        const ctx = this.state.repeatContext || {};
        return !!(ctx.groupMode && (ctx.groupBy || ctx.groupSplitOn));
    }


    // ─── 分組標題／小計列 ─────────────────────────────────────────

    /**
     * 把游標所在的表格列設為分組標題列／小計列。
     *
     * 與重複列同一個設計：插一個標記藥丸就完成宣告，後端找「含該標記的那一列」。
     * 輸出順序固定為 標題 → 明細 → 小計，不管使用者把這幾列排在表格的哪裡
     * ——那是唯一說得通的語意，而要求使用者自己排對順序只會製造一種
     * 「看起來沒錯但印出來順序不對」的錯誤。
     */
    onSetGroupRow(role) {
        if (!this.canPlaceVariables) {
            this.notification.add("目前的版面或權限不允許放置變數。", { type: "warning" });
            return;
        }
        const ctx = this.state.repeatContext;
        if (!ctx) {
            this.notification.add(
                "請先設定重複列，分組列才知道要對哪一組明細。",
                { type: "warning" }
            );
            return;
        }
        const isHeader = role === "header";
        const ok = this.insertPill({
            source: isHeader ? "groupHeader" : "groupFooter",
            isMarker: true,
            repeatId: ctx.repeatId || "",
            labelText: isHeader ? "〔分組標題〕" : "〔分組小計〕",
        });
        if (!ok) return;
        this.notification.add(
            isHeader
                ? "已設為分組標題列。每一組開頭會印一次；可從左欄「分組欄位」放入組名。"
                : "已設為分組小計列。每一組結尾會印一次；可從左欄「分組欄位」放入小計。",
            { type: "success" }
        );
    }

    /** 分組上下文可用的固定值（不必寫表達式的部分）。 */
    get GROUP_PILL_PRESETS() {
        return [
            { label: "組名", expr: "group.label", hint: "分組依據的值" },
            { label: "本組筆數", expr: "group.lines|length", hint: "" },
            { label: "組序號", expr: "group.index", hint: "第幾組" },
            { label: "組數", expr: "group.count", hint: "共幾組" },
        ];
    }

    onInsertGroupPill(preset) {
        if (!this.state.repeatContext) {
            this.notification.add(
                "分組欄位要放在分組標題列或小計列裡。請先設定重複列與分組列。",
                { type: "warning" }
            );
            return;
        }
        // source='group'：取值藥丸不綁定列角色，放標題列或小計列都一樣。
        // 用 groupFooter 當取值來源的話，「在標題列放一顆組名」會讓該列被
        // 誤判成小計列而跑到明細後面去。
        this.insertPill({
            source: "group",
            expression: preset.expr,
            labelText: preset.label,
        });
    }

    /** 插入「本組小計」：對組內明細的某個數值欄位加總。 */
    onInsertGroupSubtotal(field) {
        if (!this.state.repeatContext) {
            this.notification.add(
                "本組小計要放在分組小計列裡。請先設定重複列與分組小計列。",
                { type: "warning" }
            );
            return;
        }
        // 金額用 format_money、其他數值用 format_number——同一張單上
        // 小計有幣別符號、明細沒有（或反過來）看起來像兩個系統拼起來的。
        //
        // 聚合藥丸的來源是 sum(...) 而不是一條欄位路徑，渲染層的型別表查不到
        // 型別，所以格式只能在插入時寫進表達式。至少小數位要跟著欄位走：
        // 固定兩位的話，數量欄位（digits 常是三位）明細三位、小計兩位。
        const sum = `group.lines|sum(attribute='${field.name}')`;
        const expression = field.type === "monetary"
            ? `format_money(${sum})`
            : `format_number(${sum}, ',.${field.digits ?? 2}f')`;
        this.insertPill({
            source: "group",
            expression,
            labelText: `本組 ${field.label || field.name}`,
        });
    }

    get isGroupPill() {
        const src = (this.state.selectedVariable || {}).source;
        return src === "groupHeader" || src === "groupFooter" || src === "group";
    }

    get isGroupMarkerPill() {
        return this.isGroupPill && !!(this.state.selectedVariable || {}).isMarker;
    }

    onGroupExpressionChange(value) {
        const expr = (value || "").trim();
        this.updateSelectedPill({ expression: expr });
    }

    _metaForModelField(field, parent = null) {
        const path = parent ? `${parent.name}.${field.name}` : field.name;
        const labelText = parent
            ? `${parent.label || parent.name}-${field.label || field.name}`
            : (field.label || field.name);
        // 只帶路徑，格式交給渲染層依欄位型別決定
        //（doc.render.mixin 的 _type_format_expression，唯一一份表）。
        //
        // 這裡原本自己判 selection 與 monetary 並寫成固定的 expression。
        // 問題不是寫錯，是那份判斷只有兩種型別、而且 selection 還漏了巢狀
        // 路徑（`!parent` 條件）——拖一個「客戶-狀態」進來印的是代碼。
        // date / float / integer 乾脆沒有，於是同一個欄位走轉換器會格式化、
        // 手工拉就不會。改成只帶 path 以後兩條路徑結果一致。
        return { source: "record", path, labelText };
    }

    /**
     * 插入「欄位標籤」藥丸——印的是欄位名稱而不是值。
     *
     * 明細表的表頭「品名／數量／單價／小計」就是欄位標籤，而 Odoo 自己的
     * .po 早就翻好了。走 i18n 藥丸等於請使用者把 Odoo 的翻譯再抄一遍、
     * 每個語言一次，之後兩邊各自漂移。
     *
     * labelModel 要明講：表頭那顆藥丸放在重複列**外面**，求值時的記錄是主
     * 記錄，推斷不出明細的模型。
     */
    onInsertFieldLabel(field, parent = null, model = null) {
        const path = parent ? `${parent.name}.${field.name}` : field.name;
        this.insertPill({
            source: "fieldLabel",
            path,
            labelModel: model || this._loadedModelName || "",
            labelText: field.label || field.name,
        });
    }

    /** 明細欄位的標籤（給表頭用）——模型是重複來源的模型，不是主記錄。 */
    onInsertLineFieldLabel(field) {
        const ctx = this.state.repeatContext;
        this.onInsertFieldLabel(field, null, (ctx && ctx.model) || "");
    }

    onModelFieldDragStart(ev, field, parent = null) {
        if (!this.canPlaceVariables) {
            ev.preventDefault();
            return;
        }
        // 自訂 MIME：與工具列拖出的 text/x-doc-field-type（待填欄位型別）分流，
        // 兩者在 drop handler 走不同分支
        ev.dataTransfer.setData(
            "text/x-doc-odoo-field",
            JSON.stringify(this._metaForModelField(field, parent))
        );
        ev.dataTransfer.effectAllowed = "copy";
    }

    onModelFieldClick(field, parent = null) {
        if (!this.canPlaceVariables) {
            this.notification.add(
                "浮動版面不支援模型變數（匯出時不會出現），請切回行內版面。",
                { type: "warning" }
            );
            return;
        }
        this.insertPill(this._metaForModelField(field, parent));
    }


    // ═══ Phase 5：舊 alias token → 藥丸的開檔延遲升級 ════════════════
    //
    // 伺服器端 migration 只能處理已有 content_json 的資料。只有 content_html
    // 的舊文件無法在伺服器端可靠轉換（HTML → IElement 需要 canvas-editor 的
    // executeSetHTML，那是瀏覽器端的東西）。所以走這條：開檔時就地升級並存回，
    // 使用者無感，開一次升一次。兩群都清空後正則路徑才能刪除。

    _aliasMaps() {
        const merged = {
            ...(this.state.templateFieldAliases || {}),
            ...(this.state.fieldAliases || {}),
        };
        const tokenMap = {};
        const varMap = {};
        for (const [key, expression] of Object.entries(merged)) {
            const k = String(key).trim();
            const expr = String(expression || "").trim();
            if (!k || !expr) continue;
            if (/^[A-Za-z_]\w*$/.test(k)) varMap[k] = expr;
            else tokenMap[k] = expr;
        }
        return { tokenMap, varMap };
    }

    _metaFromExpression(expression, labelText) {
        const plain = /^object\.([A-Za-z_][\w.]*)$/.exec((expression || "").trim());
        if (plain) {
            return { source: "record", path: plain[1], labelText };
        }
        return { source: "expression", expression: (expression || "").trim(), labelText };
    }

    /** 把單一文字元素中的 token 拆成 [文字, 藥丸, 文字…]；無 token 回 null。 */
    _splitElementTokens(el, tokenMap, varMap) {
        if (!el || (el.type && el.type !== "text")) return null;
        const text = el.value || "";
        if (!text || text === "\n") return null;

        const matches = [];
        const tokenRe = /《([^》]+)》/g;
        const varRe = /\{\{\s*([A-Za-z_]\w*)\s*\}\}/g;
        let m;
        while ((m = tokenRe.exec(text)) !== null) {
            const key = m[1].trim();
            if (tokenMap[key]) matches.push([m.index, m.index + m[0].length, key, tokenMap[key]]);
        }
        while ((m = varRe.exec(text)) !== null) {
            const key = m[1].trim();
            if (varMap[key]) matches.push([m.index, m.index + m[0].length, key, varMap[key]]);
        }
        if (!matches.length) return null;
        matches.sort((a, b) => a[0] - b[0]);

        // 文字片段沿用原元素樣式，只換 value——否則被拆開的字會掉字型與顏色
        const base = { ...el };
        delete base.value;
        delete base.type;
        delete base.label;
        delete base.extension;

        const pieces = [];
        let cursor = 0;
        for (const [start, end, key, expression] of matches) {
            if (start < cursor) continue;
            if (start > cursor) pieces.push({ ...base, value: text.slice(cursor, start) });
            pieces.push(this._buildPillElement(this._metaFromExpression(expression, key)));
            cursor = end;
        }
        if (cursor < text.length) pieces.push({ ...base, value: text.slice(cursor) });
        return pieces.length ? pieces : null;
    }

    /**
     * 掃描目前內容，把殘餘 alias token 就地升級成藥丸。
     * 回傳升級的藥丸數；0 表示沒東西可升。
     */
    upgradeTokensToPills() {
        if (!this.editor) return 0;
        const { tokenMap, varMap } = this._aliasMaps();
        if (!Object.keys(tokenMap).length && !Object.keys(varMap).length) return 0;

        let data;
        try {
            data = this.editor.command.getValue().data;
        } catch (e) {
            return 0;
        }
        let created = 0;
        const visit = (list) => {
            if (!Array.isArray(list)) return;
            let i = 0;
            while (i < list.length) {
                const el = list[i];
                if (el && typeof el === "object") {
                    if (Array.isArray(el.valueList)) visit(el.valueList);
                    for (const row of el.trList || []) {
                        for (const cell of row.tdList || []) visit(cell.value);
                    }
                }
                const pieces = this._splitElementTokens(el, tokenMap, varMap);
                if (pieces) {
                    list.splice(i, 1, ...pieces);
                    created += pieces.filter(p => p.type === "label").length;
                    i += pieces.length;
                } else {
                    i += 1;
                }
            }
        };
        for (const zone of ["header", "main", "footer"]) visit(data[zone]);
        if (!created) return 0;
        try {
            this.editor.command.executeSetValue(data);
        } catch (e) {
            console.error("[DocEditor] token 升級藥丸失敗", e);
            return 0;
        }
        return created;
    }


    // ═══ Phase 4：模型變數藥丸 ═══════════════════════════════════════

    /** 從元素身上讀綁定定義；不是模型變數藥丸回 null。 */
    _elementFieldMeta(el) {
        if (!el || el.type !== "label") return null;
        const meta = (el.extension || {})[DOBTOR_FIELD_KEY];
        return meta && typeof meta === "object" ? meta : null;
    }

    /**
     * 依綁定定義建一個藥丸元素。
     *
     * value 是「給人看的標籤文字」，快照時才會被換成實際值；
     * 綁定關係全部在 extension，改標籤文字不影響取值。
     */
    _buildPillElement(meta) {
        const labelText = meta.labelText || meta.path || meta.expression || "變數";
        return {
            type: "label",
            value: labelText,
            label: { ...PILL_STYLE, ...(meta.style || {}) },
            extension: { [DOBTOR_FIELD_KEY]: { ...meta, labelText } },
        };
    }

    /**
     * 在游標處插入模型變數藥丸。
     *
     * 用 executeInsertElementList 而不是 executeInsertControl——
     * control 是「待人填寫」的互動元件，模型變數是唯讀顯示，兩者不同。
     */
    insertPill(meta) {
        if (!this.editor) {
            this.notification.add("編輯器尚未初始化", { type: "warning" });
            return false;
        }
        try {
            this.editor.command.executeInsertElementList([this._buildPillElement(meta)]);
            return true;
        } catch (e) {
            console.error("[DocEditor] 插入變數藥丸失敗", e);
            this.notification.add(`插入變數失敗：${e.message || e}`, { type: "danger" });
            return false;
        }
    }

    /**
     * 更新目前選中藥丸的綁定定義（inspector 用）。
     *
     * canvas-editor 沒有「就地改單一元素屬性」的公開 API，故走
     * 取整份 value → 依 extension 找到該元素 → 改寫 → setValue 回去。
     * 為避免把 caret 位置弄丟，改寫後不重設選區（canvas-editor 自行處理）。
     */
    updateSelectedPill(patch) {
        const current = this.state.selectedVariable;
        if (!current || !this.editor) return;
        const merged = { ...current, ...patch };
        delete merged._elementValue;
        if (patch.labelText !== undefined) {
            merged.labelText = patch.labelText;
        }
        let data;
        try {
            data = this.editor.command.getValue().data;
        } catch (e) {
            return;
        }
        let hit = false;
        const visit = (list) => {
            for (const el of list || []) {
                if (!el || typeof el !== "object") continue;
                const meta = this._elementFieldMeta(el);
                if (meta && !hit && this._sameMeta(meta, current)) {
                    el.extension = { [DOBTOR_FIELD_KEY]: merged };
                    el.value = merged.labelText || el.value;
                    el.label = { ...PILL_STYLE, ...(merged.style || {}) };
                    hit = true;
                }
                if (Array.isArray(el.valueList)) visit(el.valueList);
                for (const row of el.trList || []) {
                    for (const cell of row.tdList || []) {
                        if (Array.isArray(cell.value)) visit(cell.value);
                    }
                }
            }
        };
        for (const zone of ["header", "main", "footer"]) {
            if (Array.isArray(data[zone])) visit(data[zone]);
        }
        if (!hit) return;
        try {
            this.editor.command.executeSetValue(data);
            this.state.selectedVariable = { ...merged };
        } catch (e) {
            console.error("[DocEditor] 更新變數定義失敗", e);
        }
    }

    /** 兩份綁定定義是否指向同一個變數（用於在元素樹中定位）。 */
    _sameMeta(a, b) {
        if (!a || !b) return false;
        return (a.source || "record") === (b.source || "record")
            && (a.path || "") === (b.path || "")
            && (a.expression || "") === (b.expression || "")
            && (a.labelText || "") === (b.labelText || "");
    }

    /** inspector 事件：改綁定定義的單一鍵。 */
    onVariablePropertyChange(key, value) {
        this.updateSelectedPill({ [key]: value });
    }

    /**
     * 取目前文件 body 的 HTML（含 control 已填值，攤平成純 HTML 供匯出鏈使用）。
     * canvas-editor getHTML() 回 { header, main, footer } 物件；content_html 只存 main。
     * 任何失敗回 undefined → 呼叫端略過 content_html（不擋存檔；後端 content_html=None 即不更新）。
     */
    _mainHtml() {
        try {
            const html = this.editor?.command?.getHTML?.();
            return html && typeof html.main === "string" ? html.main : undefined;
        } catch (e) {
            console.warn("[DocEditor] getHTML().main 失敗，content_html 本次不同步", e);
            return undefined;
        }
    }

    /**
     * 載入互動式 control 欄位的選項 spec（valueSets + record 當前值），
     * 鍵為 placeholder_text token 名，供升級 token→control 時組 payload。
     * 只有 select/radio/checkbox 需要；純 text/odoo_field 不需選項。
     */
    async _loadControlSpecs() {
        this._controlSpecByVar = {};
        if (!this.targetId || !this._hasTemplate) return;
        const needSpec = (this._templateFieldsCache || []).some(
            f => ["select", "radio", "checkbox"].includes(f.field_type)
        );
        if (!needSpec) return;
        try {
            const resp = await rpc(
                "/dobtor_doc/template_fields/options",
                this.targetRpcParams
            );
            if (resp.success && Array.isArray(resp.specs)) {
                for (const spec of resp.specs) {
                    const token = (spec.placeholder_text || "").trim();
                    if (token) this._controlSpecByVar[token] = spec;
                }
            }
        } catch (e) {
            console.warn("[DocEditor] _loadControlSpecs failed", e);
        }
    }

    /**
     * 判斷一個 doc.template.field 是否對應某 token 變數名。
     * 相容三種：odoo_field_name===var、placeholder_text===var、placeholder_text===`{{ var }}`。
     */
    _fieldMatchesVar(f, varName) {
        if (!f) return false;
        if (f.odoo_field_name === varName) return true;
        const ph = (f.placeholder_text || "").trim();
        return ph === varName || ph === `{{ ${varName} }}`;
    }

    /**
     * 依 token 變數名建 canvas-editor control element（正式結構 {type:"control", control:{...}}）。
     * 有設定 spec（select/radio/checkbox）→ 帶 valueSets + 預設選中（record 當前值）+ inputAble；
     * 否則退回純 text control（與既有 Sprint W 行為一致）。
     */
    _controlElementForVar(varName, fieldId) {
        const placeholder = `{{ ${varName} }}`;
        const spec = (this._controlSpecByVar || {})[varName];
        const control = {
            type: "text",
            value: null,
            placeholder,
            conceptId: String(fieldId),
            deletable: true,
            disabled: false,
        };
        if (spec && spec.control_type === "select") {
            control.type = "select";
            control.valueSets = spec.value_sets || [];
            control.code = spec.current_code || null;
            if (spec.is_multi_select) {
                control.isMultiSelect = true;
                control.multiSelectDelimiter = "、";
            }
            if (spec.input_able) control.selectExclusiveOptions = { inputAble: true };
            if (spec.current_code) {
                const hit = (spec.value_sets || []).find(v => v.code === spec.current_code);
                if (hit) control.value = [{ value: hit.value }];
            }
        } else if (spec && spec.control_type === "radio") {
            control.type = "radio";
            control.flexDirection = "row";
            control.valueSets = (spec.value_sets && spec.value_sets.length)
                ? spec.value_sets : [{ value: "", code: String(fieldId) }];
            control.code = spec.current_code || null;
        } else if (spec && spec.control_type === "checkbox") {
            control.type = "checkbox";
            control.flexDirection = "row";
            if (spec.value_sets && spec.value_sets.length) {
                control.valueSets = spec.value_sets;
                control.value = spec.value_sets
                    .filter(v => v.code === spec.current_code)
                    .map(v => ({ value: v.value, code: v.code, checked: true }));
            } else {
                control.value = [{ value: "", code: String(fieldId), checked: false }];
            }
        }
        return { type: "control", value: null, control };
    }

    /**
     * 開檔自動升級：把「已設定為互動式 control」的 token（select/radio/checkbox）
     * 就地轉成可點 chip（帶 record 當前值）。只處理有 spec 的 token，不碰其他 token
     * （那些留給 auto-preview 顯示值），所以不會大量建 record。
     * 必須在 auto-preview 之前跑：control chip 不是 token 文字、preview 不會動到它。
     */
    async _autoUpgradeConfiguredControls() {
        if (!this.editor || !this.state.docId || !this._hasTemplate) return null;
        const specs = Object.values(this._controlSpecByVar || {});
        if (!specs.length) return null;
        const cmd = this.editor.command;
        this._suppressAutoSave = true;
        try {
            // Step 0：把已遷移文件的 《中文》 token 正規化成 {{ varname }}，讓既有 {{ }} 管線能處理。
            //   spec.tokens 列出此欄位所有 token 字面字串；非 {{ }} 的（《中文》）替換成 {{ placeholder_text }}。
            const SAFE_GUARD = 50;
            for (const spec of specs) {
                const varname = spec.placeholder_text;
                if (!varname) continue;
                const canonical = `{{ ${varname} }}`;
                for (const tok of (spec.tokens || [])) {
                    if (tok === canonical) continue;
                    for (let i = 0; i < SAFE_GUARD; i++) {
                        let curMain;
                        try {
                            curMain = cmd.getValue().data.main || [];
                        } catch (e) {
                            break;
                        }
                        if (flattenElementsToText(curMain).indexOf(tok) < 0) break;
                        try {
                            cmd.executeSearch(tok);
                            cmd.executeReplace(canonical);
                        } catch (e) {
                            console.warn("[DocEditor] 中文 token 正規化失敗", tok, e);
                            break;
                        }
                    }
                }
            }

            // Step 1：掃描 {{ }} token（含剛正規化進來的）並升級成 control
            let data;
            try {
                data = cmd.getValue().data;
            } catch (e) {
                console.warn("[DocEditor] 自動升級 getValue 失敗", e);
                return null;
            }
            const scannedAll = scanJinja2Variables(data);
            const present = new Set(scannedAll.map(v => v.varName));
            const toUpgrade = specs.map(s => s.placeholder_text).filter(v => v && present.has(v));
            if (!toUpgrade.length) return null;   // 無對應 token
            return await this._sprintWScanAndReplace(scannedAll, { silent: true, onlyVars: toUpgrade });
        } catch (e) {
            console.error("[DocEditor] 自動升級失敗", e);
            return null;
        } finally {
            this._suppressAutoSave = false;
        }
    }

    _insertControlForField(fieldId, field, signer) {
        const conceptId = String(fieldId);
        let placeholder = `[${signer.name}/${field.label}]`;
        if (field.key === "odoo_field" && field.odooFieldName) {
            placeholder = `{{ ${field.odooFieldName} }}`;
        }
        // canvas-editor control type 對應（FIELD_TYPES 的 ctrlType）
        const controlPayload = {
            type: field.ctrlType || "text",
            value: null,
            placeholder: placeholder,
            conceptId: conceptId,
            // 必填欄位：在 Phase 2.1 暫不在 control 上 enforce，由 doc.template.field.required 控
            deletable: true,
            disabled: false,
        };
        // 互動式 control 的選項設定（自動升級時由 caller 掛在 field 上）：
        //   field.valueSets    [{ value, code }]   下拉/勾選/單選的選項
        //   field.inputAble    bool                 select 允許自填
        //   field.isMultiSelect bool                select 複選
        //   field.currentCode  str                  開啟時的預設選中值（綁定 record 的當前值）
        const valueSets = Array.isArray(field.valueSets) ? field.valueSets : [];
        if (field.ctrlType === "select") {
            controlPayload.valueSets = valueSets;
            controlPayload.code = field.currentCode || null;
            if (field.isMultiSelect) {
                controlPayload.isMultiSelect = true;
                controlPayload.multiSelectDelimiter = "、";
            }
            if (field.inputAble) {
                controlPayload.selectExclusiveOptions = { inputAble: true };
            }
            // 預設選中：把對應 valueSet 的顯示文字放進 value，chip 開啟即帶 record 當前值
            if (field.currentCode) {
                const hit = valueSets.find((v) => v.code === field.currentCode);
                if (hit) {
                    controlPayload.value = [{ value: hit.value }];
                }
            }
        } else if (field.ctrlType === "radio") {
            controlPayload.flexDirection = "row";
            controlPayload.valueSets = valueSets.length
                ? valueSets
                : [{ value: "", code: conceptId }];
            controlPayload.code = field.currentCode || null;
        } else if (field.ctrlType === "checkbox") {
            controlPayload.flexDirection = "row";
            if (valueSets.length) {
                // 多選勾選組：依 currentCode 預先勾選
                controlPayload.valueSets = valueSets;
                controlPayload.value = valueSets
                    .filter((v) => v.code === field.currentCode)
                    .map((v) => ({ value: v.value, code: v.code, checked: true }));
            } else {
                // 既有單一 checkbox 相容：留空陣列表示未勾選
                controlPayload.value = [{ value: "", code: conceptId, checked: false }];
            }
        }
        // Phase 7：依簽約人上色。element.highlight 在 canvas-editor 內優先於
        // options.control 的全域底色（lib 內判斷是 `a.highlight ||`），
        // 所以同一份文件裡不同填寫者的欄位可以有各自的顏色。
        const highlight = signerColor(signer?.color);
        if (highlight) {
            controlPayload.highlight = highlight;
        }
        try {
            this.editor.command.executeInsertControl(controlPayload);
        } catch (e) {
            console.error("[DocEditor] executeInsertControl failed", e);
            this.notification.add(
                `欄位資料已建立但插入文件失敗：${e.message || e}（可手動 reload 重試）`,
                { type: "warning" }
            );
        }
    }

    /**
     * 若 active signer 是 placeholder（id < 0、來自 state.signers 預設值），
     * 先在後端建立真正的 doc.template.signer 紀錄、回填 state。
     */
    async _ensureSignerExists(signerId) {
        const local = this.state.signers.find(s => s.id === signerId);
        if (!local) {
            this.notification.add("找不到當前簽約人", { type: "warning" });
            return null;
        }
        if (local.id > 0) {
            return local;  // 已是後端紀錄
        }
        const resp = await rpc("/dobtor_doc/template_fields/save_signer", {
            ...this.targetRpcParams,
            signer: {
                name: local.name,
                color: 0,
                sequence: 10,
            },
        });
        if (!resp.success) {
            this.notification.add(`建立簽約人失敗：${resp.error}`, { type: "danger" });
            return null;
        }
        // 把 placeholder 換成真實紀錄
        const updated = { id: resp.id, name: local.name, color: local.color, count: 0 };
        const idx = this.state.signers.findIndex(s => s.id === signerId);
        if (idx >= 0) {
            this.state.signers[idx] = updated;
            this.state.activeSignerId = updated.id;
        }
        return updated;
    }

    /**
     * 用後端回傳的 {signer_id: count} 更新 chip 上的數字。
     * 未在 dict 中的 signer 不動（避免覆蓋未同步的 placeholder）。
     *
     * 防禦：
     *   - JSON RPC 序列化後 dict key 一律 string；s.id 是 number。
     *     同時試 number / string key，並對 0 / null / undefined 嚴謹判斷。
     *   - OWL useState 對「array element 內部物件屬性 set」偵測 lag（E2E 已 reproduce：
     *     delete RPC 成功、後端 count 正確、但 chip DOM 不更新）。
     *     解法：用 map() 重組整個陣列、再 reassign，強制 root state proxy 觸發 re-render。
     */
    _applySignerCounts(counts) {
        if (!counts || typeof counts !== "object") return;
        this.state.signers = this.state.signers.map((s) => {
            let v = counts[s.id];
            if (v === undefined) v = counts[String(s.id)];
            if (v !== undefined && v !== null) {
                return { ...s, count: v };
            }
            return s;
        });
    }

    /**
     * 從後端載入當前 doc 對應 template 的 signers + fields。
     * 在 _loadDocument 之後呼叫，把後端紀錄合併到 state（覆蓋 Phase 1 的 placeholder）。
     */
    async _loadTemplateFields() {
        if (!this.targetId) return;
        try {
            const data = await rpc(
                "/dobtor_doc/template_fields/load",
                this.targetRpcParams
            );
            this._hasTemplate = !!data.has_template;
            if (!data.has_template) {
                // 沒範本：保留 placeholder signers 給視覺，但點欄位按鈕時會擋下
                return;
            }
            // 後端 signers 完整覆蓋 state.signers（每筆都附上 count）
            const signerById = {};
            for (const f of (data.fields || [])) {
                signerById[f.signer_id] = (signerById[f.signer_id] || 0) + 1;
            }
            const signers = (data.signers || []).map(s => ({
                id: s.id,
                name: s.name,
                color: this._signerColorHex(s.color),
                count: signerById[s.id] || 0,
            }));
            // 若範本一個 signer 都沒有，給一個預設「簽約人」placeholder（不寫後端、user 拖欄位時才建）
            if (signers.length === 0) {
                signers.push({ id: -1, name: "簽約人", color: "#2c2c2c", count: 0 });
            }
            this.state.signers = signers;
            this.state.activeSignerId = signers[0].id;
            this.state.fieldCount = (data.fields || []).length;
            this._templateFieldsCache = data.fields || [];
            // Phase 8 Del 同步：初始化 control id tracker 為當前已存在的 fields
            this._lastControlIds = new Set(
                this._templateFieldsCache.map(f => f.id)
            );
            // 載入互動式 control 的選項 spec（select/radio/checkbox），供 token→control 升級用
            await this._loadControlSpecs();
            // Sprint D：觸發 overlay layer re-render
            this.state.overlayFieldsRev++;
        } catch (e) {
            console.warn("[DocEditor] _loadTemplateFields failed", e);
            // 不擋編輯流程：載入失敗時保留 Phase 1 的 placeholder signers
        }
    }

    /**
     * Phase 8 Del 同步：偵測 canvas-editor 上 control 被刪 → 自動刪後端紀錄。
     *
     * 流程：
     *   1. 從 canvas-editor 取當前所有 control 的 conceptId 集合
     *   2. 與 _lastControlIds diff，找出「上次有、現在沒」的 → 是被刪掉的
     *   3. 對每個失蹤的 id 呼叫 delete_field endpoint（並行）
     *   4. 更新 cache、chip count、選中狀態、_lastControlIds
     *
     * 容錯：getControlList 在某些 canvas-editor 版本可能 throw；包 try/catch、
     *       失敗時不擋編輯流程（autoSave 自己會處理）。
     */
    async _syncDeletedControls() {
        // 只處理 control（待填欄位）。模型變數是自描述的 label 元素、
        // 沒有後端記錄，使用者按 Del 刪掉就沒了，不需要同步任何東西。
        if (!this.targetId || !this._hasTemplate) return;
        if (this._syncingDeletes) return;  // 重入保護
        let list;
        try {
            list = this.editor?.command?.getControlList?.() || [];
        } catch (e) {
            return;  // API 不可用 → 靜默跳過（使用者仍可從 inspector 手動刪）
        }
        // canvas-editor 不同版本 getControlList 回的 shape 不同，
        // 嘗試多種路徑取 conceptId
        const currentIds = new Set();
        for (const item of list) {
            const cid = item?.control?.conceptId
                     || item?.conceptId
                     || item?.element?.control?.conceptId;
            if (!cid) continue;
            const n = parseInt(cid, 10);
            if (Number.isFinite(n)) currentIds.add(n);
        }
        const lastIds = this._lastControlIds || new Set();
        const deleted = [...lastIds].filter(id => !currentIds.has(id));
        if (deleted.length === 0) {
            this._lastControlIds = currentIds;
            return;
        }

        this._syncingDeletes = true;
        try {
            const results = await Promise.all(deleted.map(async (id) => {
                try {
                    return await rpc("/dobtor_doc/template_fields/delete_field", {
                        doc_id: this.state.docId,
                        field_id: id,
                    });
                } catch (e) {
                    console.warn("[DocEditor] 同步刪除 field", id, "失敗：", e);
                    return { success: false, error: e?.message || String(e) };
                }
            }));
            // 從 cache 移除已被刪的
            this._templateFieldsCache = (this._templateFieldsCache || [])
                .filter(f => !deleted.includes(f.id));
            // 用最後一筆成功的回應更新 chip + total count
            const last = [...results].reverse().find(r => r && r.success);
            if (last) {
                this._applySignerCounts(last.signer_field_counts);
                this.state.fieldCount = last.field_count;
            }
            // 若選中欄位被刪了，清 selectedFieldId 讓 inspector 回空狀態
            if (this.state.selectedFieldId
                && deleted.includes(this.state.selectedFieldId)) {
                this.state.selectedFieldId = null;
            }
            // 不打 notification（避免按 Del 連發 toast 干擾）
        } finally {
            this._lastControlIds = currentIds;
            this._syncingDeletes = false;
        }
    }

    /**
     * Odoo color picker 索引（0-11）→ CSS color。
     * 沿用 Odoo 後台 colour palette 的近似值。
     */
    _signerColorHex(idx) {
        const palette = [
            "#2c2c2c", // 0 default 黑
            "#ef4444", // 1 紅
            "#f97316", // 2 橙
            "#eab308", // 3 黃
            "#22c55e", // 4 綠
            "#06b6d4", // 5 青
            "#3b82f6", // 6 藍
            "#8b5cf6", // 7 紫
            "#ec4899", // 8 粉
            "#10b981", // 9 翡翠
            "#64748b", // 10 灰
            "#714B67", // 11 Odoo 紫
        ];
        return palette[idx] || palette[0];
    }

    /**
     * Sprint E：開啟 Odoo 欄位選擇器 Dialog，user 選好 Odoo 欄位後**建立可編輯的
     * `doc.template.field` 紀錄**（field_type='odoo_field' + odoo_field_name）並
     * 插入帶 conceptId 的 inline control。
     *
     * 與舊版差異：
     *   舊版（Sprint 89 復活）：只插入 `{{ object.partner_id.name }}` 純文字字串，
     *                          無法在 inspector 編輯、無法統計到 signer/field count。
     *   新版（Sprint E）：     完整走 save_field + insertControl 流程，
     *                          user 可在右側 inspector 改填寫者/必填/佔位符/字型大小、
     *                          以及最關鍵的「Odoo 欄位名稱」（XML 已有對應輸入框）。
     */
    async onOdooFieldClick() {
        if (!this.dialog) {
            this.notification.add("Dialog service 未就緒", { type: "warning" });
            return;
        }
        if (!this.editor) {
            this.notification.add("編輯器尚未初始化", { type: "warning" });
            return;
        }
        if (!this.state.docId) {
            this.notification.add("請先儲存文件後再新增 Odoo 欄位", { type: "warning" });
            return;
        }
        if (!this._hasTemplate) {
            this.notification.add(
                "此文件未關聯範本。請先在後台 doc.document.template_id 設定範本後再回來。",
                { type: "warning" }
            );
            return;
        }
        // 取得當前文件綁定的 model_name（_loadDocument 已寫入 state）。
        const modelName = this._loadedModelName || null;
        this.dialog.add(DocFieldPickerDialog, {
            modelName: modelName,
            docId: this.state.docId,
            onInsert: async (expression, label) => {
                // expression 形如 `{{ object.partner_id.name }}`；label 形如 `partner_id.name`。
                // 我們只要 label（純欄位路徑）存到 doc.template.field.odoo_field_name。
                const odooFieldName = (label || "").trim()
                    || (expression || "").replace(/[{}]/g, "").replace(/^\s*object\.\s*/, "").trim();
                if (!odooFieldName) {
                    this.notification.add("欄位名稱解析失敗", { type: "danger" });
                    return;
                }
                try {
                    const signer = await this._ensureSignerExists(this.state.activeSignerId);
                    if (!signer) return;

                    const fieldPayload = {
                        signer_id: signer.id,
                        field_type: "odoo_field",
                        page_no: this.state.pageNo || 1,
                        required: false,
                        placeholder_text: `{{ ${odooFieldName} }}`,
                        font_size: 12,
                        odoo_field_name: odooFieldName,
                    };
                    const saveResult = await rpc("/dobtor_doc/template_fields/save_field", {
                        doc_id: this.state.docId,
                        field: fieldPayload,
                    });
                    if (!saveResult.success) {
                        this.notification.add(
                            `新增 Odoo 欄位失敗：${saveResult.error}`,
                            { type: "danger" }
                        );
                        return;
                    }
                    // 插入 inline control（_insertControlForField 對 odoo_field 走 `{{ x.y }}` placeholder）
                    this._insertControlForField(
                        saveResult.id,
                        {
                            key: "odoo_field",
                            label: `Odoo: ${odooFieldName}`,
                            ctrlType: "text",
                            odooFieldName: odooFieldName,
                        },
                        signer,
                    );
                    // push cache 讓 Inspector 立即顯示
                    if (!this._templateFieldsCache) this._templateFieldsCache = [];
                    this._templateFieldsCache.push({
                        id: saveResult.id,
                        ...fieldPayload,
                        width: 120,
                        height: 24,
                        pos_x: 0,
                        pos_y: 0,
                    });
                    this._applySignerCounts(saveResult.signer_field_counts);
                    this.state.fieldCount = saveResult.field_count;
                    this.state.selectedFieldId = saveResult.id;
                    this.notification.add(
                        `已插入 Odoo 欄位「${odooFieldName}」，可在右側 inspector 編輯。`,
                        { type: "success" }
                    );
                } catch (e) {
                    console.error("[DocEditor] onOdooFieldClick insert failed", e);
                    this.notification.add(
                        `新增 Odoo 欄位失敗：${e.message || e}`,
                        { type: "danger" }
                    );
                }
            },
        });
    }

    /**
     * L2-v2：開啟欄位選擇器，把選擇的 Odoo 欄位以「《中文 label》」純文字插入游標位置，
     * 並同步寫入 doc.document.field_aliases 對映，渲染時由 _render_template 自動展開。
     *
     * 與 onOdooFieldClick 差異：
     *   - 不需要 doc.template_id（不依賴範本機制）
     *   - 不建立 doc.template.field record；alias map 集中在 doc.field_aliases JSON
     *   - 文字保留純中文，匯出 Word/PDF 後看起來就是「《工程名稱》」這種人類可讀標記
     */
    async onInsertAliasClick() {
        if (!this.dialog) {
            this.notification.add("Dialog service 未就緒", { type: "warning" });
            return;
        }
        if (!this.editor) {
            this.notification.add("編輯器尚未初始化", { type: "warning" });
            return;
        }
        if (!this.state.docId) {
            this.notification.add("請先儲存文件後再插入欄位", { type: "warning" });
            return;
        }
        if (!this._loadedModelName) {
            this.notification.add(
                "此文件未綁定 Odoo 模型。請在後台 doc.document.model_id 設定後再回來。",
                { type: "warning" }
            );
            return;
        }

        this.dialog.add(DocFieldPickerDialog, {
            modelName: this._loadedModelName,
            docId: this.state.docId,
            onInsert: async (expression, label, fieldInfo) => {
                // expression: 「{{ object.partner_id.name }}」
                // label:      「partner_id」或「partner_id.name」
                // fieldInfo:  完整欄位資料（含中文 label / type / displayLabel）
                // 推導出純欄位路徑（不含 object. 與 {{ }}）
                const fieldPath = (expression || "")
                    .replace(/[{}]/g, "")
                    .replace(/^\s*object\.\s*/, "")
                    .trim();
                if (!fieldPath) {
                    this.notification.add("欄位路徑解析失敗", { type: "danger" });
                    return;
                }

                // 中文 token：優先用 displayLabel（含父欄位串接），否則用 fieldInfo.label
                let defaultToken = (fieldInfo && (fieldInfo.displayLabel || fieldInfo.label)) || label || fieldPath;
                defaultToken = String(defaultToken).trim().replace(/[《》]/g, '');

                // 自訂 token 名稱：讓 user 自由命名（如「客戶名稱」「申請人」）
                // 取消 = 中斷整個插入流程；空白 = 用預設 token
                const userInput = window.prompt(
                    `請輸入此欄位在文件中顯示的中文名稱：\n` +
                    `（會以《名稱》形式插入，並對映到 ${fieldPath}）\n` +
                    `按確定使用此名稱、取消放棄插入。`,
                    defaultToken,
                );
                if (userInput === null) {
                    // user 按了取消
                    return;
                }
                let token = String(userInput).trim().replace(/[《》]/g, '') || defaultToken;
                if (!token) {
                    this.notification.add("無法取得欄位中文名稱", { type: "danger" });
                    return;
                }

                // 計算 alias expression：date / datetime 套 format_date、selection 套 selection_label
                let aliasExpression;
                const ftype = fieldInfo && fieldInfo.type;
                if (ftype === "date" || ftype === "datetime") {
                    aliasExpression = `format_date(object.${fieldPath})`;
                } else if (ftype === "selection") {
                    aliasExpression = `selection_label('${fieldPath}')`;
                } else {
                    aliasExpression = `object.${fieldPath}`;
                }

                // 同名 token 衝突偵測：若已存在且 expression 不同，提示 user
                const existing = this.state.fieldAliases || {};
                if (existing[token] && existing[token] !== aliasExpression) {
                    const overwrite = window.confirm(
                        `「${token}」已對映到不同欄位：\n  舊：${existing[token]}\n  新：${aliasExpression}\n\n要覆寫嗎？`
                    );
                    if (!overwrite) return;
                }

                // 1. 先在文件游標位置插入《token》純文字
                try {
                    const text = `《${token}》`;
                    const elements = text.split("").map(ch => ({ value: ch }));
                    this.editor.command.executeInsertElementList(elements);
                } catch (e) {
                    console.error("[DocEditor] executeInsertElementList failed", e);
                    this.notification.add(`插入文字失敗：${e.message || e}`, { type: "danger" });
                    return;
                }

                // 2. 寫入 alias map（整批覆寫；前端 cache 已含舊內容）
                const newAliases = { ...existing, [token]: aliasExpression };
                try {
                    const resp = await rpc("/dobtor_doc/aliases/save", {
                        doc_id: this.state.docId,
                        aliases: newAliases,
                    });
                    if (resp && resp.error) {
                        this.notification.add(`alias 儲存失敗：${resp.error}`, { type: "warning" });
                        return;
                    }
                    // 整體 reassign 觸發 OWL reactive re-render（直接寫 key 偵測 lag）
                    this.state.fieldAliases = resp && resp.aliases ? { ...resp.aliases } : { ...newAliases };
                    this.notification.add(
                        `已插入「《${token}》」並對映到 ${aliasExpression}`,
                        { type: "success" }
                    );
                } catch (e) {
                    console.error("[DocEditor] alias save failed", e);
                    this.notification.add(`alias 儲存失敗：${e.message || e}`, { type: "danger" });
                }
            },
        });
    }

    /**
     * L2-v2：預覽模式 toggle——在編輯器內把 token 替換成實際值（暫時，不存回 DB）。
     *
     * 切到預覽模式：
     *   1. 暫存當前 content_json 到 this._editModeSnapshot
     *   2. 呼叫 /dobtor_doc/preview_content_json 取得 token 已替換的 JSON
     *   3. executeSetValue 灌進 canvas-editor
     *   4. disable AutoSave 防止覆寫
     *
     * 切回編輯模式：
     *   1. enable AutoSave
     *   2. executeSetValue 把 snapshot 還原
     *   3. 清掉 snapshot
     */
    async onTogglePreviewMode() {
        if (!this.editor) {
            this.notification.add("編輯器尚未初始化", { type: "warning" });
            return;
        }
        if (!this.state.docId) return;
        if (!this._loadedModelName || !this._loadedResId) {
            this.notification.add(
                "此文件未綁定 model_id + res_id，無法進入預覽模式。",
                { type: "warning" }
            );
            return;
        }

        if (this.state.previewMode) {
            // 切回「範本模式」（顯示原始 token）：還原 snapshot
            try {
                this._suppressAutoSave = true;
                if (this._editModeSnapshot) {
                    this.editor.command.executeSetValue(this._editModeSnapshot);
                    this._editModeSnapshot = null;
                }
                this.state.previewMode = false;
                this.notification.add(
                    "已切到範本模式（顯示 《token》 原文）。在此模式下可調整 token 位置。",
                    { type: "info" }
                );
            } catch (e) {
                console.error("[DocEditor] exit preview mode failed", e);
                this.notification.add(
                    `切回範本模式失敗：${e.message || e}`,
                    { type: "danger", sticky: true }
                );
            } finally {
                // 200ms 讓 executeSetValue 觸發的 contentChange 跑完再恢復 AutoSave
                setTimeout(() => { this._suppressAutoSave = false; }, 200);
            }
            return;
        }

        // 切到「預覽（=實際值編輯）模式」
        try {
            // 1. 暫存當前 content_json（含 token，給切回用）
            const snapshot = this.editor.command.getValue().data;
            this._editModeSnapshot = JSON.parse(JSON.stringify(snapshot));

            // 2. 取後端渲染結果（傳入「當前內容」：保留已建的 control chip，只把殘餘 token 換成值）
            const resp = await rpc("/dobtor_doc/preview_content_json", {
                doc_id: this.state.docId,
                content_json: JSON.stringify(snapshot),
            });
            if (!resp || resp.error) {
                this.notification.add(
                    `進入預覽模式失敗：${resp && resp.error}`,
                    { type: "danger" }
                );
                this._editModeSnapshot = null;
                return;
            }

            // 3. 灌入渲染後 content_json；suppress autosave 避免立即被當編輯寫回
            this._suppressAutoSave = true;
            this.editor.command.executeSetValue(resp.content_json);
            this.state.previewMode = true;

            // 4. 200ms 後恢復 AutoSave：之後使用者真正編輯（純文字部分）才會 save
            //    這樣的設計取捨：使用者直接編輯實際值會凍結這份文件為純文字，
            //    範本層的 token 仍保留於 doc.template，不影響其他文件
            setTimeout(() => { this._suppressAutoSave = false; }, 200);

            this.notification.add(
                "已顯示實際值。可直接編輯；改動會凍結為這份文件的純文字（不會影響範本）。",
                { type: "success" }
            );
        } catch (e) {
            console.error("[DocEditor] enter preview mode failed", e);
            this.notification.add(`進入預覽模式失敗：${e.message || e}`, { type: "danger" });
            this._editModeSnapshot = null;
            this._suppressAutoSave = false;
        }
    }

    /**
     * L2-v2：alias 管理面板用——把 state.fieldAliases 轉成排序好的 [{token, expression}] 陣列。
     * QWeb 不易在 t-foreach 直接迭代 dict，所以給 getter 統一處理。
     */
    get fieldAliasesList() {
        const docAliases = this.state.fieldAliases || {};
        const tmplAliases = this.state.templateFieldAliases || {};
        const tokens = new Set([
            ...Object.keys(docAliases),
            ...Object.keys(tmplAliases),
        ]);
        return [...tokens]
            .sort((a, b) => a.localeCompare(b, 'zh-Hant'))
            .map(token => {
                const docExpr = docAliases[token];
                const tmplExpr = tmplAliases[token];
                // 文件層級覆寫範本層級
                const expression = docExpr || tmplExpr;
                const source = docExpr ? 'doc' : 'template';
                return { token, expression, source };
            });
    }

    /**
     * L2-v2：刪除單一 alias 對映。文件內已存在的《token》純文字會保留（讓 user 自己決定要不要刪），
     * 但 token 不再對映到任何 expression，渲染時會原樣輸出。
     */
    async onDeleteAlias(token, source) {
        if (!this.state.docId || !token) return;
        // source: 'doc' = 文件層級；'template' = 範本層級
        const isTemplate = source === 'template';
        const aliases = isTemplate
            ? (this.state.templateFieldAliases || {})
            : (this.state.fieldAliases || {});
        if (!(token in aliases)) return;
        const scopeMsg = isTemplate
            ? `⚠️ 此對映來自範本「${this.state.templateName}」，移除後所有使用此範本的文件都會受影響。`
            : `文件內已輸入的《${token}》文字會保留，但渲染時不會被替換成實際值。`;
        const ok = window.confirm(`要移除「${token}」的對映嗎？\n\n${scopeMsg}`);
        if (!ok) return;
        const next = { ...aliases };
        delete next[token];
        try {
            const endpoint = isTemplate
                ? "/dobtor_doc/template_aliases/save"
                : "/dobtor_doc/aliases/save";
            const resp = await rpc(endpoint, {
                doc_id: this.state.docId,
                aliases: next,
            });
            if (resp && resp.error) {
                this.notification.add(`刪除失敗：${resp.error}`, { type: "danger" });
                return;
            }
            const fresh = resp && resp.aliases ? { ...resp.aliases } : next;
            if (isTemplate) {
                this.state.templateFieldAliases = fresh;
            } else {
                this.state.fieldAliases = fresh;
            }
            this.notification.add(
                `已移除「${token}」對映` + (isTemplate ? "（範本級）" : ""),
                { type: "success" }
            );
        } catch (e) {
            console.error("[DocEditor] onDeleteAlias failed", e);
            this.notification.add(`刪除失敗：${e.message || e}`, { type: "danger" });
        }
    }

    /**
     * L2-v2：alias 管理面板用——點某條 alias 直接在游標位置插入《token》純文字。
     * 不再次寫 alias map（已存在），純粹文字插入。
     */
    onInsertAliasFromList(token) {
        if (!this.editor || !token) return;
        try {
            const text = `《${token}》`;
            const elements = text.split("").map(ch => ({ value: ch }));
            this.editor.command.executeInsertElementList(elements);
            this.notification.add(`已在游標位置插入「《${token}》」`, { type: "info" });
        } catch (e) {
            console.error("[DocEditor] onInsertAliasFromList failed", e);
            this.notification.add(`插入失敗：${e.message || e}`, { type: "danger" });
        }
    }

    /**
     * Sprint G：批次掃描文件內所有 `{{ var }}` jinja2 變數，為每個 unique 變數
     * 建立 doc.template.field record（field_type='odoo_field' + odoo_field_name=var）。
     *
     * 解決 Sprint E 留下的痛點：「舊文件內既有 `{{ var }}` 文字無法自動轉」——
     * 以前要手動逐個刪掉舊文字再點 Odoo 欄位按鈕重插，5 個變數要點 5 次。
     * 現在點一次「掃描變數」按鈕、後端批次建好 record，user 直接在 inspector 編輯。
     *
     * 設計取捨：
     *   - **不做 in-place text → control 替換**：canvas-editor 的 IElement 位置操作易碎，
     *     替換失敗會破壞文件結構。MVP 只建 record、不動原文，user 在 inspector 看
     *     到後可決定要不要手動刪除舊文字。完整 in-place 替換留 Sprint H+ 視需求加。
     *   - **跳過已存在的 odoo_field_name**：避免重複掃描重複建檔。
     *   - **逐個 save_field 而非 batch 端點**：5-10 個變數的場景下 N 次 RPC 仍 < 1s，
     *     無需新增後端端點。若未來掃 50+ 變數頻繁卡頓再加 batch。
     */
    async onScanVariablesClick() {
        if (!this.editor) {
            this.notification.add("編輯器尚未初始化", { type: "warning" });
            return;
        }
        if (!this.state.docId) {
            this.notification.add("請先儲存文件後再執行掃描", { type: "warning" });
            return;
        }
        if (!this._hasTemplate) {
            this.notification.add(
                "此文件未關聯範本。請先在後台 doc.document.template_id 設定範本後再回來。",
                { type: "warning" }
            );
            return;
        }

        // 取出當前 canvas-editor 完整資料，掃描 main / header / footer
        let data;
        try {
            data = this.editor.command.getValue().data;
        } catch (e) {
            console.error("[DocEditor] onScanVariablesClick getValue failed", e);
            this.notification.add(`讀取文件內容失敗：${e.message || e}`, { type: "danger" });
            return;
        }
        const scanned = scanJinja2Variables(data);
        if (scanned.length === 0) {
            this.notification.add(
                "未找到任何 `{{ var }}` 變數。如需新增，請點「Odoo 欄位」按鈕。",
                { type: "info" }
            );
            return;
        }

        // 已註冊 odoo_field_name 清單（避免重複建檔）
        const existingNames = new Set(
            (this._templateFieldsCache || [])
                .filter(f => f.field_type === "odoo_field" && f.odoo_field_name)
                .map(f => f.odoo_field_name)
        );
        const toCreate = scanned.filter(v => !existingNames.has(v.varName));
        const skipCount = scanned.length - toCreate.length;

        if (toCreate.length === 0) {
            this.notification.add(
                `找到 ${scanned.length} 個變數，但全部已是 Odoo 欄位 record（在 Inspector 中可編輯）。`,
                { type: "info" }
            );
            return;
        }

        // 使用 window.confirm 而非自訂 dialog：portal 環境 dialog service 可能不可用，
        // 且這是一次性確認、不需要複雜 UI。列出將建檔的變數名讓 user 確認。
        const previewList = toCreate
            .slice(0, 10)
            .map(v => `  • ${v.varName}（${v.occurrences} 次）`)
            .join("\n");
        const moreSuffix = toCreate.length > 10 ? `\n  ... 還有 ${toCreate.length - 10} 個` : "";
        const skipMsg = skipCount > 0 ? `\n\n（${skipCount} 個已是 Odoo 欄位、自動略過）` : "";
        const ok = window.confirm(
            `將為以下 ${toCreate.length} 個 jinja2 變數建立 Odoo 欄位 record：\n\n${previewList}${moreSuffix}${skipMsg}\n\n建立後可在右側 Inspector 編輯填寫者、必填、字型大小等屬性。\n\n確定要繼續嗎？`
        );
        if (!ok) return;

        // 先確保 active signer 存在（同 onOdooFieldClick 流程）
        const signer = await this._ensureSignerExists(this.state.activeSignerId);
        if (!signer) return;

        // 逐個 save_field（並行可能造成 race，序列化才安全）
        const created = [];
        const failed = [];
        let lastSaveResult = null;
        for (const v of toCreate) {
            const payload = {
                signer_id: signer.id,
                field_type: "odoo_field",
                page_no: this.state.pageNo || 1,
                required: false,
                placeholder_text: `{{ ${v.varName} }}`,
                font_size: 12,
                odoo_field_name: v.varName,
            };
            try {
                const resp = await rpc("/dobtor_doc/template_fields/save_field", {
                    doc_id: this.state.docId,
                    field: payload,
                });
                if (!resp.success) {
                    failed.push({ varName: v.varName, error: resp.error || "未知錯誤" });
                    continue;
                }
                created.push({ id: resp.id, varName: v.varName });
                lastSaveResult = resp;
                // push cache 讓 inspector 立即看得到
                if (!this._templateFieldsCache) this._templateFieldsCache = [];
                this._templateFieldsCache.push({
                    id: resp.id,
                    ...payload,
                    width: 120,
                    height: 24,
                    pos_x: 0,
                    pos_y: 0,
                });
            } catch (e) {
                console.error("[DocEditor] onScanVariablesClick save_field failed", v.varName, e);
                failed.push({ varName: v.varName, error: e.message || String(e) });
            }
        }

        // 用最後一次的 signer_field_counts / field_count 更新 chips（已涵蓋所有新增）
        if (lastSaveResult) {
            this._applySignerCounts(lastSaveResult.signer_field_counts);
            this.state.fieldCount = lastSaveResult.field_count;
        }

        // 結果通知
        if (failed.length === 0) {
            this.notification.add(
                `已批次建立 ${created.length} 個 Odoo 欄位 record。請至右側 Inspector 編輯詳細屬性。`,
                { type: "success" }
            );
        } else if (created.length === 0) {
            this.notification.add(
                `批次建立失敗：${failed.map(f => f.varName).join(", ")}`,
                { type: "danger" }
            );
        } else {
            this.notification.add(
                `成功 ${created.length} 個、失敗 ${failed.length} 個（${failed.map(f => f.varName).join(", ")}）。`,
                { type: "warning" }
            );
        }
    }

    /**
     * Sprint H：掃描 + 建 record + **in-place 替換**。
     *
     * 在 Sprint G 的基礎上多做一步：對 main 流的每個 `{{ var }}` match，用
     * setRange + backspace + executeInsertControl 把純文字替換為帶 conceptId
     * 的可編輯 control。完成後 user 點文件上的 control 即可在 inspector 編輯，
     * 視覺與 Sprint E onOdooFieldClick 插入的 control 完全一致。
     *
     * 標註為「實驗性」原因：
     *   - canvas-editor 的 setRange + backspace + insertControl 組合在巢狀結構
     *     （table / list / title）內可能失敗、破壞文件結構。本實作只處理 main 流，
     *     跨巢狀結構的 match 在 scanJinja2VariablesWithPositions 已過濾（會在
     *     掃描階段被作廢、不會嘗試替換）。
     *   - 替換過程任何一步丟例外都會中斷後續、但**前面已成功的替換不會回滾**
     *     （canvas-editor 沒提供 transaction API）。確認失敗時 user 可用 Ctrl+Z
     *     回退。
     *   - 萬一 reverse-order 操作仍導致位置失準（極端罕見），fallback 是依靠
     *     vitest 已驗證的位置精度測試 + 第二道 sentinel 防線。
     */
    async onScanAndReplaceClick() {
        if (!this.editor) {
            this.notification.add("編輯器尚未初始化", { type: "warning" });
            return;
        }
        if (!this.state.docId) {
            this.notification.add("請先儲存文件後再執行掃描", { type: "warning" });
            return;
        }
        if (!this._hasTemplate) {
            this.notification.add(
                "此文件未關聯範本。請先在後台 doc.document.template_id 設定範本後再回來。",
                { type: "warning" }
            );
            return;
        }

        let data;
        try {
            data = this.editor.command.getValue().data;
        } catch (e) {
            console.error("[DocEditor] onScanAndReplaceClick getValue failed", e);
            this.notification.add(`讀取文件內容失敗：${e.message || e}`, { type: "danger" });
            return;
        }

        // Sprint G 用的去重清單（含 header/footer/巢狀）— 給 user 看的總數
        const scannedAll = scanJinja2Variables(data);
        // Sprint H 用的位置清單（main 流可替換的單字元元素）
        const mainPositions = scanJinja2VariablesWithPositions(data.main || []);
        // Sprint J 用的位置清單（table 內 td.value 可替換的單字元元素）
        const tablePositions = scanJinja2VariablesInTables(data.main || []);

        // Sprint T (revert): canvas-editor 的 executeSetValue 會自動把連續同樣式的
        // single-char elements **合併**回 multi-char run（measured behavior：傳入
        // [{X},{Y},{Z}] 出來 [{XYZ}]）。所以「normalize 後 setValue 回去 + 再 scan」
        // 不可行。Sprint H/J 對 HTML-imported 內容仍會早退（mainPos=0），這是已知
        // 限制——詳見 docs/phase8_sprint_t_2026-05-24.md。Workaround：user 用
        // 「掃描變數」（Sprint G）建 record，或在 canvas-editor 內手動 type 變數
        // （typed content 是 per-char element、可被 Sprint H/J 替換）。

        // Sprint Q：用純函式 analyzeScanResults 算 positions / uniqueVars / toCreate
        const existingNames = (this._templateFieldsCache || [])
            .filter(f => f.field_type === "odoo_field" && f.odoo_field_name)
            .map(f => f.odoo_field_name);
        const analysis = analyzeScanResults({
            scannedAll,
            mainPositions,
            tablePositions,
            existingOdooFieldNames: existingNames,
        });
        const { positions, uniqueVars, toCreate } = analysis;

        if (scannedAll.length === 0) {
            this.notification.add(
                "未找到任何 `{{ var }}` 變數。",
                { type: "info" }
            );
            return;
        }
        if (positions.length === 0) {
            // Sprint W：Sprint H/J 對 HTML-imported（multi-char）內容會早退。
            // 改走兩階段路徑：先用 canvas-editor 內建的 executeSearch+executeReplace 把
            // `{{ var }}` 文字換成 unique marker，再用 marker 位置 setRange + executeBackspace
            // + executeInsertControl 把 marker 換成 odoo_field control。
            //
            // 為什麼可行（與 Sprint T setValue auto-merge 失敗對比）：
            //   - search/replace 在 element value 字串層替換、不重建 element list
            //   - setRange 對 multi-char element 也以 char 為步長（probe 已驗證 setRange(3, 20)
            //     對 single multi-char element 的 char 3..19 範圍正確 backspace）
            //   - 不經 setValue → 不觸發 canvas-editor 的 single-char element 自動合併
            //
            // 限制：本路徑目前**僅處理 main 流**。table cell 內 `{{ var }}` 仍跳過
            // （留待 Sprint X：multi-arg setRange 對 td 的 char-offset 簽名探路）。
            return await this._sprintWScanAndReplace(scannedAll);
        }

        // 確認 dialog（user 必須意識到「會替換文件內容」）
        const previewList = uniqueVars
            .slice(0, 10)
            .map(v => `  • ${v}`)
            .join("\n");
        const moreSuffix = uniqueVars.length > 10 ? `\n  ... 還有 ${uniqueVars.length - 10} 個` : "";
        // 巢狀（list/title/multi-char）的變數總量 = scannedAll 含的 var 數 − 我們能替換的 uniqueVars 數
        // 注意：scannedAll 計次但去重後與 uniqueVars 數不同；這裡只給粗略提示
        const skippedCount = scannedAll.length - uniqueVars.length;
        const skipReasonNote = skippedCount > 0
            ? `\n\n注意：另有約 ${skippedCount} 個變數位於 list/title 或多字元元素，**不會**被替換（僅 main + table cells）。`
            : "";
        const cacheNote = toCreate.length < uniqueVars.length
            ? `\n（${uniqueVars.length - toCreate.length} 個變數的 record 已存在、會被沿用）`
            : "";
        const sourceNote = tablePositions.length > 0
            ? `\n包含：main 流 ${mainPositions.length} 處、table 內 ${tablePositions.length} 處。`
            : "";
        const ok = window.confirm(
            `【實驗性功能】將為以下 ${uniqueVars.length} 個變數建立 record，並替換 ${positions.length} 處 \`{{ var }}\` 文字為可編輯 control：${sourceNote}\n\n${previewList}${moreSuffix}${cacheNote}${skipReasonNote}\n\n⚠️ 替換為不可回復操作（無 transaction）。如需先建 record 不替換，請按取消後改用「掃描變數」按鈕。\n\n確定要繼續嗎？`
        );
        if (!ok) return;

        // 確保 signer 存在
        const signer = await this._ensureSignerExists(this.state.activeSignerId);
        if (!signer) return;

        // === Sprint N: 動工前捕捉文件快照（給「復原最近一次掃描並替換」用）===
        // JSON 序列化深拷貝避免後續操作意外動到 snapshot
        // 失敗（如循環引用）→ 不捕捉、不擋流程；rollback 按鈕只在 snapshot 存在時顯示
        let preReplaceSnapshot = null;
        try {
            preReplaceSnapshot = JSON.parse(JSON.stringify(data));
        } catch (e) {
            console.warn("[DocEditor] scan-replace snapshot 捕捉失敗（rollback 不可用）", e);
        }

        // === Phase 1: 建 record ===
        const fieldIdByVarName = new Map();
        // 先把已存在的塞進 map
        for (const f of (this._templateFieldsCache || [])) {
            if (f.field_type === "odoo_field" && f.odoo_field_name && !fieldIdByVarName.has(f.odoo_field_name)) {
                fieldIdByVarName.set(f.odoo_field_name, f.id);
            }
        }
        const createFailed = [];
        let lastSaveResult = null;
        for (const varName of toCreate) {
            const payload = {
                signer_id: signer.id,
                field_type: "odoo_field",
                page_no: this.state.pageNo || 1,
                required: false,
                placeholder_text: `{{ ${varName} }}`,
                font_size: 12,
                odoo_field_name: varName,
            };
            try {
                const resp = await rpc("/dobtor_doc/template_fields/save_field", {
                    doc_id: this.state.docId,
                    field: payload,
                });
                if (!resp.success) {
                    createFailed.push({ varName, error: resp.error || "未知錯誤" });
                    continue;
                }
                fieldIdByVarName.set(varName, resp.id);
                lastSaveResult = resp;
                if (!this._templateFieldsCache) this._templateFieldsCache = [];
                this._templateFieldsCache.push({
                    id: resp.id,
                    ...payload,
                    width: 120,
                    height: 24,
                    pos_x: 0,
                    pos_y: 0,
                });
            } catch (e) {
                console.error("[DocEditor] onScanAndReplaceClick save_field failed", varName, e);
                createFailed.push({ varName, error: e.message || String(e) });
            }
        }
        if (lastSaveResult) {
            this._applySignerCounts(lastSaveResult.signer_field_counts);
            this.state.fieldCount = lastSaveResult.field_count;
        }

        // === Phase 2: in-place 替換（reverse order）===
        // 必須 reverse：每次替換改變後續 index、從尾巴開始才能保持前面位置有效。
        // 分兩段處理：
        //   2a. table 內位置（用 multi-arg setRange、按 (tableElementIdx, trIdx, tdIdx, startIdx) 全字典序倒排）
        //   2b. main 流位置（用 2-arg setRange、按 startIdx 倒排）
        // 為什麼分段：table 改動不影響 main element index、main 改動不影響 table 內部
        //   index，但**互相**不安全（如果 main 替換先做、table 元素整個移位、tableElementIdx
        //   失效）。先處理 table（內部）、後處理 main 是安全的單向。
        let replaced = 0;
        const replaceFailed = [];

        const doReplace = (pos, fieldId) => {
            this._insertControlForField(
                fieldId,
                {
                    key: "odoo_field",
                    label: `Odoo: ${pos.varName}`,
                    ctrlType: "text",
                    odooFieldName: pos.varName,
                },
                signer,
            );
        };

        // Phase 2a: table 位置（reverse 全字典序：table 大→小、tr 大→小、td 大→小、startIdx 大→小）
        const tableSorted = tablePositions.slice().sort((a, b) => {
            if (b.tableElementIdx !== a.tableElementIdx) return b.tableElementIdx - a.tableElementIdx;
            if (b.trIdx !== a.trIdx) return b.trIdx - a.trIdx;
            if (b.tdIdx !== a.tdIdx) return b.tdIdx - a.tdIdx;
            return b.startIdx - a.startIdx;
        });
        for (const pos of tableSorted) {
            const fieldId = fieldIdByVarName.get(pos.varName);
            if (!fieldId) {
                replaceFailed.push({ varName: pos.varName, reason: "no_field_id" });
                continue;
            }
            if (!pos.tableId) {
                // canvas-editor 沒給 table id → setRange 多參數簽名無法用
                replaceFailed.push({ varName: pos.varName, reason: "no_table_id" });
                continue;
            }
            try {
                this.editor.command.setRange(
                    pos.startIdx,
                    pos.endIdx + 1,
                    pos.tableId,
                    pos.tdIdx,
                    pos.tdIdx,
                    pos.trIdx,
                    pos.trIdx,
                );
                this.editor.command.backspace();
                doReplace(pos, fieldId);
                replaced++;
            } catch (e) {
                console.error("[DocEditor] onScanAndReplaceClick table replace failed", pos, e);
                replaceFailed.push({ varName: pos.varName, reason: e.message || String(e) });
            }
        }

        // Phase 2b: main 位置（reverse startIdx）
        const mainSorted = mainPositions.slice().sort((a, b) => b.startIdx - a.startIdx);
        for (const pos of mainSorted) {
            const fieldId = fieldIdByVarName.get(pos.varName);
            if (!fieldId) {
                replaceFailed.push({ varName: pos.varName, reason: "no_field_id" });
                continue;
            }
            try {
                this.editor.command.setRange(pos.startIdx, pos.endIdx + 1);
                this.editor.command.backspace();
                doReplace(pos, fieldId);
                replaced++;
            } catch (e) {
                console.error("[DocEditor] onScanAndReplaceClick main replace failed", pos, e);
                replaceFailed.push({ varName: pos.varName, reason: e.message || String(e) });
            }
        }

        // === Sprint N: 存 snapshot + 本輪新建 field id 列表，供 rollback ===
        // 只在「至少 replaced 或 toCreate 有變動」時才存（避免 user 反覆按沒變動的「掃描並替換」覆寫之前有效的 snapshot）
        if (preReplaceSnapshot && (replaced > 0 || toCreate.length > 0)) {
            const createdIds = [];
            for (const varName of toCreate) {
                const id = fieldIdByVarName.get(varName);
                if (id) createdIds.push(id);
            }
            this.state.lastScanReplaceSnapshot = {
                docData: preReplaceSnapshot,
                createdFieldIds: createdIds,
                replacedCount: replaced,
                timestamp: Date.now(),
            };
        }

        // === 結果通知 ===
        const parts = [];
        if (replaced > 0) parts.push(`已替換 ${replaced} 處文字為可編輯 control`);
        if (toCreate.length > 0) parts.push(`新建 ${toCreate.length - createFailed.length}/${toCreate.length} 個 record`);
        if (createFailed.length > 0) parts.push(`record 建立失敗：${createFailed.map(f => f.varName).join(", ")}`);
        if (replaceFailed.length > 0) parts.push(`替換失敗 ${replaceFailed.length} 處（${replaceFailed.map(r => r.varName).slice(0, 3).join(", ")}${replaceFailed.length > 3 ? "..." : ""}）`);
        const summary = parts.join("；") || "未做任何變動";
        const ntype = (createFailed.length || replaceFailed.length) > 0 ? "warning" : "success";
        const rollbackHint = (this.state.lastScanReplaceSnapshot && (replaced > 0 || toCreate.length > 0))
            ? "（如需復原請點右上角『復原』按鈕）"
            : "";
        this.notification.add(`【掃描並替換】${summary}${rollbackHint ? "。" + rollbackHint : "。"}`, { type: ntype });
    }

    /**
     * Sprint N：復原最近一次掃描並替換。
     *
     * 兩步驟：
     *   1. setValue(snapshot.docData) → 把文件還原到掃描前狀態（control 變回 {{ var }} 文字）
     *   2. delete_field(每個 createdFieldIds) → 刪掉本次新建的 record
     *      （Sprint H/J 已存在的 record 不動，避免吞掉 user 之前手動建的）
     *
     * 限制：只支援單層 undo（覆蓋式 snapshot）。snapshot 在以下情況清除：
     *   - rollback 成功後（不可再次 rollback）
     *   - user 再按一次「掃描並替換」（snapshot 被覆蓋）
     *   - editor reload（state 重置）
     *
     * 不處理：snapshot 之後的 autosave / 其他 edit。canvas-editor undo stack
     *   會被 setValue 清空（這是 canvas-editor 本身的行為、不在我們控制範圍）。
     */
    async onRollbackScanReplaceClick() {
        const snap = this.state.lastScanReplaceSnapshot;
        if (!snap) {
            this.notification.add("沒有可復原的掃描並替換操作。", { type: "info" });
            return;
        }
        const ageSec = Math.round((Date.now() - snap.timestamp) / 1000);
        const ok = window.confirm(
            `將復原最近一次「掃描並替換」：\n\n` +
            `  • 還原文件內容到掃描前狀態（${snap.replacedCount} 處 control 變回 {{ var }} 文字）\n` +
            `  • 刪除本次新建的 ${snap.createdFieldIds.length} 個 record\n\n` +
            `（執行於 ${ageSec} 秒前；本操作會覆寫期間其他編輯）\n\n確定要復原嗎？`
        );
        if (!ok) return;

        // Step 1: 還原文件
        // 注意：snap.docData 經 OWL state 包裝後是 Proxy；canvas-editor 內部會
        // 呼叫 structuredClone()，structuredClone 不接受 Proxy 會 DataCloneError。
        // 先用 JSON 深拷一份純物件交給 setValue。
        let plainDocData;
        try {
            plainDocData = JSON.parse(JSON.stringify(snap.docData));
        } catch (e) {
            console.error("[DocEditor] onRollbackScanReplaceClick deep-clone snap failed", e);
            this.notification.add(`快照解封失敗：${e.message || e}`, { type: "danger" });
            return;
        }
        try {
            this.editor.command.executeSetValue(plainDocData);
        } catch (e) {
            console.error("[DocEditor] onRollbackScanReplaceClick setValue failed", e);
            this.notification.add(`還原文件失敗：${e.message || e}`, { type: "danger" });
            return;
        }

        // Step 2: 刪除本次新建的 record
        let deleted = 0;
        const failed = [];
        let lastSuccess = null;
        for (const id of snap.createdFieldIds) {
            try {
                const r = await rpc("/dobtor_doc/template_fields/delete_field", {
                    doc_id: this.state.docId,
                    field_id: id,
                });
                if (r && r.success) {
                    deleted++;
                    lastSuccess = r;
                } else {
                    failed.push({ id, error: r?.error || "未知錯誤" });
                }
            } catch (e) {
                failed.push({ id, error: e?.message || String(e) });
            }
        }
        // 從 cache / _lastControlIds / selectedFieldId 同步移除
        const deletedSet = new Set(snap.createdFieldIds.filter((_, i) => i < deleted));
        this._templateFieldsCache = (this._templateFieldsCache || [])
            .filter(f => !snap.createdFieldIds.includes(f.id));
        for (const id of snap.createdFieldIds) this._lastControlIds?.delete(id);
        if (this.state.selectedFieldId && snap.createdFieldIds.includes(this.state.selectedFieldId)) {
            this.state.selectedFieldId = null;
        }
        if (lastSuccess) {
            this._applySignerCounts(lastSuccess.signer_field_counts);
            this.state.fieldCount = lastSuccess.field_count;
        }

        // 清 snapshot
        this.state.lastScanReplaceSnapshot = null;

        if (failed.length === 0) {
            this.notification.add(
                `已復原：文件還原 + ${deleted} 個 record 刪除。`,
                { type: "success" }
            );
        } else {
            this.notification.add(
                `部分復原：文件已還原、${deleted}/${snap.createdFieldIds.length} 個 record 刪除成功、${failed.length} 個失敗。`,
                { type: "warning" }
            );
        }
    }

    /**
     * Sprint W：對 HTML-imported（multi-char element）內容的「掃描並替換」
     * 兩階段路徑。被 onScanAndReplaceClick 在 Sprint H 位置陣列為空時 dispatch。
     *
     * Stage 1：對每個 unique varName，呼叫 canvas-editor 的 executeSearch + executeReplace
     *   把所有 `{{ varName }}` 出現處換成 unique marker 字串。canvas-editor 的 replace 在
     *   element value 字串層做替換、不重建 element list，因此不會觸發 Sprint T 發現的
     *   setValue auto-merge 問題。
     *
     * Stage 2：getValue 拿 marker-含 main，用 findMarkerPositionsInMain 找各 marker 的
     *   flat char-offset。reverse order 對每個 marker 做：
     *     setRange(start, end) → executeBackspace() → executeInsertControl(controlPayload)
     *   probe-search-control-insertion.spec.ts 證實這組合在 multi-char element 內 work。
     *
     * 限制（留待 Sprint X+）：
     *   - 不處理 table cell 內 `{{ var }}`（setRange 的 td 簽名需以 td-internal char offset 為單位）
     *   - 不處理 list / title 內變數（valueList 結構複雜，setRange 簽名待研究）
     *   - 不處理 header / footer
     */
    async _sprintWScanAndReplace(scannedAll, opts = {}) {
        // opts.silent   ：跳過確認 dialog（給開檔自動升級用）
        // opts.onlyVars ：只處理指定的變數子集（給「只升級已設定 control 的 token」用）
        const cmd = this.editor.command;

        // 抓 main 流的 unique varNames（只看 main、不含 header/footer/table 內變數）
        let data;
        try {
            data = cmd.getValue().data;
        } catch (e) {
            if (!opts.silent) {
                this.notification.add(`讀取文件內容失敗：${e.message || e}`, { type: "danger" });
            }
            return;
        }
        const mainOnlyAll = scanJinja2Variables({ main: data.main });
        let mainVarNames = mainOnlyAll.map(v => v.varName);
        if (Array.isArray(opts.onlyVars)) {
            const allow = new Set(opts.onlyVars);
            mainVarNames = mainVarNames.filter(v => allow.has(v));
        }
        if (mainVarNames.length === 0) {
            if (!opts.silent) {
                this.notification.add(
                    `找到 ${scannedAll.length} 個變數，但都不在 main 流（可能在 list / title 內）。請改用「掃描變數」（只建 record）。`,
                    { type: "warning" }
                );
            }
            return;
        }

        // 確認 dialog（silent 模式跳過）
        if (!opts.silent) {
            const previewList = mainVarNames.slice(0, 10).map(v => `  • ${v}`).join("\n");
            const more = mainVarNames.length > 10 ? `\n  ... 還有 ${mainVarNames.length - 10} 個` : "";
            const skipNote = mainVarNames.length < scannedAll.length
                ? `\n\n注意：另有約 ${scannedAll.length - mainVarNames.length} 個變數位於 list / title 內，**不會**被替換（main + table 皆會處理）。`
                : "";
            const ok = window.confirm(
                `【Sprint W/X — HTML-imported 替換】將 ${mainVarNames.length} 個變數的所有出現處替換為可編輯 control（main + table cell 皆支援）：\n\n${previewList}${more}${skipNote}\n\n⚠️ 此操作會修改文件內容（如需復原請用右上角「復原」按鈕）。\n\n確定要繼續嗎？`
            );
            if (!ok) return;
        }

        // signer
        const signer = await this._ensureSignerExists(this.state.activeSignerId);
        if (!signer) return;

        // Snapshot for Sprint N rollback
        let preReplaceSnapshot = null;
        try {
            preReplaceSnapshot = JSON.parse(JSON.stringify(data));
        } catch (e) {
            console.warn("[DocEditor.Sprint W] snapshot 捕捉失敗（rollback 不可用）", e);
        }

        // Phase 1: 建/沿用 record
        const fieldIdByVarName = new Map();
        for (const f of (this._templateFieldsCache || [])) {
            if (f.field_type === "odoo_field" && f.odoo_field_name && !fieldIdByVarName.has(f.odoo_field_name)) {
                fieldIdByVarName.set(f.odoo_field_name, f.id);
            }
        }
        // 已設定的互動式 control 欄位（select/radio/checkbox/text）依 token 名對應、沿用不重建
        for (const varName of mainVarNames) {
            if (fieldIdByVarName.has(varName)) continue;
            const matched = (this._templateFieldsCache || []).find(f => this._fieldMatchesVar(f, varName));
            if (matched) fieldIdByVarName.set(varName, matched.id);
        }
        const toCreate = mainVarNames.filter(v => !fieldIdByVarName.has(v));
        const createFailed = [];
        let lastSaveResult = null;
        for (const varName of toCreate) {
            const payload = {
                signer_id: signer.id,
                field_type: "odoo_field",
                page_no: this.state.pageNo || 1,
                required: false,
                placeholder_text: `{{ ${varName} }}`,
                font_size: 12,
                odoo_field_name: varName,
            };
            try {
                const resp = await rpc("/dobtor_doc/template_fields/save_field", {
                    doc_id: this.state.docId,
                    field: payload,
                });
                if (!resp.success) {
                    createFailed.push({ varName, error: resp.error || "未知錯誤" });
                    continue;
                }
                fieldIdByVarName.set(varName, resp.id);
                lastSaveResult = resp;
                if (!this._templateFieldsCache) this._templateFieldsCache = [];
                this._templateFieldsCache.push({
                    id: resp.id,
                    ...payload,
                    width: 120,
                    height: 24,
                    pos_x: 0,
                    pos_y: 0,
                });
            } catch (e) {
                console.error("[DocEditor.Sprint W] save_field failed", varName, e);
                createFailed.push({ varName, error: e.message || String(e) });
            }
        }
        if (lastSaveResult) {
            this._applySignerCounts(lastSaveResult.signer_field_counts);
            this.state.fieldCount = lastSaveResult.field_count;
        }

        // Phase 2 / Stage 1: search/replace `{{ var }}` → unique marker per var
        // 用迴圈 + 防無窮跑（最多每變數 50 次 / 出現過 var 名相同 marker 即不重複）
        const markerByVar = new Map();   // varName -> markerText
        // 用全 ASCII marker：避免不可見字（如 U+2063）被 canvas-editor 正規化掉、
        // 也避免與使用者中文內容衝突。`__` 開頭 + `__` 結尾不會在 jinja2 var 中
        // 出現，sanitize-過的 var 名（只允許 `[A-Za-z_][\w]*`）也不會包含 `__CYSWM__` 前後綴
        for (const varName of mainVarNames) {
            // 安全 varName 含 `[\w.]` ⊆ ASCII，組合後 marker 為純 ASCII
            const safe = varName.replace(/[^A-Za-z0-9_.]/g, "_");
            markerByVar.set(varName, `__CYSWM__${safe}__`);
        }
        const REPLACE_SAFE_GUARD = 50;
        for (const varName of mainVarNames) {
            const marker = markerByVar.get(varName);
            const searchText = `{{ ${varName} }}`;
            for (let i = 0; i < REPLACE_SAFE_GUARD; i++) {
                // 檢查還有沒有 `{{ varName }}` 文字。必須用 flattenElementsToText 遞迴
                // 含 table cells（Sprint X bug：原本只看 top-level main IElements 的 .value，
                // 漏了 td.value 內的 marker → table-only vars safe-guard 直接 break、
                // search/replace 沒跑、Stage 2b 找不到 marker → 0 control）
                const curMain = cmd.getValue().data.main || [];
                const flat = flattenElementsToText(curMain);
                if (flat.indexOf(searchText) < 0) break;
                try {
                    cmd.executeSearch(searchText);
                    cmd.executeReplace(marker);
                } catch (e) {
                    console.error("[DocEditor.Sprint W] search/replace failed", varName, e);
                    break;
                }
            }
        }

        // Stage 2: 用 marker 位置 setRange + backspace + insertControl
        let replaced = 0;
        const replaceFailed = [];
        // 累計每 var 的位置（多 var 各自掃）→ 合併後按 startIdx 倒排（後面動前面不影響）
        const allMarkerPositions = [];
        // re-fetch main（前面 search/replace 已改）
        let curMain;
        try {
            curMain = cmd.getValue().data.main || [];
        } catch (e) {
            console.error("[DocEditor.Sprint W] getValue after stage 1 failed", e);
            this.notification.add(`Stage 1 後讀取文件失敗：${e.message || e}`, { type: "danger" });
            return;
        }
        for (const varName of mainVarNames) {
            const marker = markerByVar.get(varName);
            const positions = findMarkerPositionsInMain(curMain, marker);
            for (const pos of positions) {
                allMarkerPositions.push({ ...pos, varName });
            }
        }
        allMarkerPositions.sort((a, b) => b.startIdx - a.startIdx);

        // Sprint W：直接 inline 插入（用 canvas-editor 正式 IElement-with-control 包裝）。
        // 為什麼不走既有 _insertControlForField：它把 IControlBasic 直接當 payload 傳，
        // canvas-editor 把它寫入 main 變成 `type: "text"` 而非 `type: "control"`，
        // 結果 getControlList 看不到、Sprint M 孤兒檢查永遠把它判為孤兒。Sprint W 用
        // 正式結構 `{type: "control", control: {...}}` 解此問題（probe-sprint-w-handler
        // 已驗證 getControlList 數量正確）。Sprint E 的 _insertControlForField 暫不動、
        // 留到後續 sprint 對齊（風險：怕影響 user 手動點按鈕已生產的文件）。
        for (const pos of allMarkerPositions) {
            const fieldId = fieldIdByVarName.get(pos.varName);
            if (!fieldId) {
                replaceFailed.push({ varName: pos.varName, reason: "no_field_id" });
                continue;
            }
            // Sprint Y13：radio / checkbox 在 main 流用 executeInsertControl 會「marker 被
            // backspace 掉、control 卻沒插進去」（canvas-editor 對 radio/checkbox 的
            // insertControl 與 select/text 行為不同、靜默失敗）。這裡跳過、保留 marker，
            // 交給下方 Stage 2b 同款的 array-mutate + executeSetValue 段處理（setValue
            // 對 radio/checkbox 可靠，已實測）。
            const _spec = (this._controlSpecByVar || {})[pos.varName];
            if (_spec && (_spec.control_type === "radio" || _spec.control_type === "checkbox")) {
                continue;
            }
            try {
                cmd.executeSetRange ? cmd.executeSetRange(pos.startIdx, pos.endIdx) : cmd.setRange(pos.startIdx, pos.endIdx);
                cmd.executeBackspace();
                // spec-aware：select 帶 valueSets + 預設選中，其餘 text
                cmd.executeInsertControl(this._controlElementForVar(pos.varName, fieldId));
                replaced++;
            } catch (e) {
                console.error("[DocEditor.Sprint W] setRange/backspace/insertControl failed", pos, e);
                replaceFailed.push({ varName: pos.varName, reason: e.message || String(e) });
            }
        }

        // ── Sprint X Stage 2b：table cell 內 marker 直接 mutate td.value + setValue ──
        // Stage 2a 走的 setRange+executeBackspace+executeInsertControl 路徑在 table cell
        // 第二次 insert 後會丟 "Cannot read properties of undefined (reading 'controlId')"
        // （probe-sprint-x-table 驗證、原因見 jinja2_scanner.js rewriteTdValueWithControls 註解）。
        // 改用直接 IElement 陣列 mutate + executeSetValue：對 table cell 4/4 OK。
        //
        // 注意：setValue 會 reset 整份 data，所以這段必須在 Stage 2a（main setRange+insert
        // 已完成、control 已在 data 內）之後做、用 getValue 取最新 data 為基礎、不能 reuse
        // preReplaceSnapshot（那是掃描前狀態、會丟掉 main 已插入的 control）。
        let tableReplaced = 0;
        const tableReplaceFailed = [];
        try {
            const latestData = cmd.getValue().data;
            // 反向 markerByVar → markerToField，給 rewriteTdValueWithControls 用
            const markerToField = new Map();
            for (const [varName, marker] of markerByVar.entries()) {
                const fieldId = fieldIdByVarName.get(varName);
                if (fieldId) markerToField.set(marker, { fieldId, varName });
            }
            const buildControlElement = (varName, fieldId) =>
                this._controlElementForVar(varName, fieldId);
            // 深拷主流（避免 OWL state Proxy + 也避免 setValue 動到原物件）
            let mutatedMain = JSON.parse(JSON.stringify(latestData.main || []));
            let anyChanged = false;
            // Sprint Y13：先處理 main 頂層 marker。Stage 2a 已把 select/text 的 marker
            // 轉成 control（其 marker 已不在），故這裡只會命中剩下的 radio/checkbox marker。
            // 用與 table cell 同款的 rewriteTdValueWithControls（top-level main 結構等同
            // td.value：扁平 IElement 陣列、table 元素 value 為空字串會被原樣略過）。
            {
                const { newValue, replaced: nTop } = rewriteTdValueWithControls(
                    mutatedMain, markerToField, buildControlElement,
                );
                if (nTop > 0) {
                    mutatedMain = newValue;
                    tableReplaced += nTop;
                    anyChanged = true;
                }
            }
            for (const el of mutatedMain) {
                if (!el || el.type !== "table" || !Array.isArray(el.trList)) continue;
                for (const tr of el.trList) {
                    if (!tr || !Array.isArray(tr.tdList)) continue;
                    for (const td of tr.tdList) {
                        if (!td || !Array.isArray(td.value)) continue;
                        const { newValue, replaced: nRepl } = rewriteTdValueWithControls(
                            td.value, markerToField, buildControlElement,
                        );
                        if (nRepl > 0) {
                            td.value = newValue;
                            tableReplaced += nRepl;
                            anyChanged = true;
                        }
                    }
                }
            }
            if (anyChanged) {
                // 同樣深拷整個 data：避免 OWL Proxy + structuredClone DataCloneError（Sprint W 教訓）
                const plainData = {
                    ...latestData,
                    main: mutatedMain,
                };
                // header / footer / graffiti 若是 Proxy，executeSetValue 內部 structuredClone 也會炸
                const safePlain = JSON.parse(JSON.stringify(plainData));
                cmd.executeSetValue(safePlain);
            }
        } catch (e) {
            console.error("[DocEditor.Sprint X] table cell rewrite failed", e);
            tableReplaceFailed.push({ reason: e.message || String(e) });
        }
        replaced += tableReplaced;

        // Sprint N snapshot
        if (preReplaceSnapshot && (replaced > 0 || toCreate.length > 0)) {
            const createdIds = [];
            for (const varName of toCreate) {
                const id = fieldIdByVarName.get(varName);
                if (id) createdIds.push(id);
            }
            this.state.lastScanReplaceSnapshot = {
                docData: preReplaceSnapshot,
                createdFieldIds: createdIds,
                replacedCount: replaced,
                timestamp: Date.now(),
            };
        }

        // 結果通知
        const parts = [];
        if (replaced > 0) parts.push(`已替換 ${replaced} 處 \`{{ var }}\` 為 control（含 table ${tableReplaced} 處）`);
        if (toCreate.length > 0) parts.push(`新建 ${toCreate.length - createFailed.length}/${toCreate.length} 個 record`);
        if (createFailed.length > 0) parts.push(`record 失敗：${createFailed.map(f => f.varName).join(", ")}`);
        if (replaceFailed.length > 0) parts.push(`main 替換失敗 ${replaceFailed.length} 處`);
        if (tableReplaceFailed.length > 0) parts.push(`table 替換失敗`);
        const summary = parts.join("；") || "未做任何變動";
        const ntype = (createFailed.length || replaceFailed.length || tableReplaceFailed.length) > 0 ? "warning" : "success";
        const hint = (this.state.lastScanReplaceSnapshot && (replaced > 0 || toCreate.length > 0))
            ? "（如需復原請點右上角『復原』按鈕）" : "";
        if (!opts.silent) {
            this.notification.add(`【Sprint W/X 掃描並替換】${summary}${hint ? "。" + hint : "。"}`, { type: ntype });
        }
        return { replaced, tableReplaced, created: toCreate.length };
    }

    /**
     * Sprint K：預覽變數 — 用 canvas-editor 的 search() API 把所有 `{{ var }}`
     * 在文件內加上高亮，**不做任何破壞性修改**。
     *
     * 用途：在按「掃描變數」/「掃描並替換」前先看一眼「哪些位置會被掃到」。
     * 補位 Sprint H/J 的破壞性操作的可見性缺口。
     *
     * 行為：
     *   - 已高亮 → 清除（toggle）
     *   - 未高亮 → 用 regex `\{\{\s*\w+(?:\.\w+)*\s*\}\}` 搜尋並高亮
     *   - 通知：「找到 N 個變數，已高亮。再按一次清除高亮。」
     *
     * 不需要 docId / template / signer——純文件內搜尋。
     */
    onPreviewVariablesClick() {
        if (!this.editor) {
            this.notification.add("編輯器尚未初始化", { type: "warning" });
            return;
        }
        // toggle：用實例旗標記住目前是高亮中還是清除中
        if (this._previewVarsActive) {
            try {
                // Sprint Y41：canvas-editor public API 是 executeSearch、不是 search
                //   Sprint K 原寫法 command.search 在 lib 升級後 not a function、
                //   feature 徹底壞 30+ sprint（Y40 spec 揭露）。改用 executeSearch
                //   public wrapper、同 find/replace path 一致。
                this.editor.command.executeSearch(null);  // 清除高亮
            } catch (e) {
                console.error("[DocEditor] onPreviewVariablesClick clear failed", e);
            }
            this._previewVarsActive = false;
            this.notification.add("已清除變數高亮。", { type: "info" });
            return;
        }
        try {
            // Sprint Y41：同上、改用 executeSearch。ISearchOption.isRegEnable 仍支援。
            this.editor.command.executeSearch(
                "\\{\\{\\s*[A-Za-z_][\\w]*(?:\\.[A-Za-z_][\\w]*)*\\s*\\}\\}",
                { isRegEnable: true },
            );
            this._previewVarsActive = true;
            // 也跑一次掃描算數量、給 user 知道找到幾個
            try {
                const data = this.editor.command.getValue().data;
                const all = scanJinja2Variables(data);
                const total = all.reduce((sum, v) => sum + v.occurrences, 0);
                this.notification.add(
                    `找到 ${all.length} 個變數（共 ${total} 處）已高亮。再按一次清除高亮。`,
                    { type: "success" }
                );
            } catch (e) {
                // search 已成功，計數失敗時只給簡單通知
                this.notification.add("已高亮所有 `{{ var }}`。再按一次清除高亮。", { type: "success" });
            }
        } catch (e) {
            console.error("[DocEditor] onPreviewVariablesClick search failed", e);
            this.notification.add(`預覽失敗：${e.message || e}`, { type: "danger" });
        }
    }

    onSignerClick(signerId) {
        this.state.activeSignerId = signerId;
    }

    /**
     * Sprint B：縮放模式切換。
     *   auto  → executePageScaleRecovery（canvas-editor 預設值，通常 = 1）
     *   width → 計算 workspace_width / page_native_width × 0.95 後呼叫 executePageScale
     *   page  → min(workspace_w/page_w, workspace_h/page_h) × 0.95
     *
     * canvas-editor 沒有原生 fit-to-width，靠 DOM 量測 + executePageScale 達成。
     */
    onZoomFitChange(event) {
        const mode = event.target.value;
        this.state.zoomFit = mode;
        if (!this.editor) {
            return;
        }
        try {
            if (mode === "auto") {
                if (typeof this.editor.command.executePageScaleRecovery === "function") {
                    this.editor.command.executePageScaleRecovery();
                } else {
                    this.editor.command.executePageScale(1);
                }
                return;
            }
            const workspaceEl = this.canvasContainer?.el?.closest(".doc-workspace")
                || this.canvasContainer?.el?.parentElement;
            if (!workspaceEl) {
                this.notification.add("無法取得工作區尺寸，縮放未變更。", { type: "warning" });
                return;
            }
            // 找出實際 page canvas 量測原生尺寸（每頁有一個 <canvas>）
            const pageCanvas = this.canvasContainer.el.querySelector("canvas");
            if (!pageCanvas) {
                this.notification.add("找不到頁面元素，縮放未變更。", { type: "warning" });
                return;
            }
            // canvas-editor 用 devicePixelRatio 放大 canvas backing store；
            // pageCanvas.width/.height 是 backing pixels，需除以 pixelRatio 還原邏輯尺寸
            const ratio = (typeof this.editor.command.getPagePixelRatio === "function"
                ? this.editor.command.getPagePixelRatio()
                : (window.devicePixelRatio || 1)) || 1;
            // 當前縮放：state.currentZoomScale 由 pageScaleChange listener 同步
            const currentScale = this.state.currentZoomScale || 1;
            const logicalPageWidth = pageCanvas.width / ratio / currentScale;
            const logicalPageHeight = pageCanvas.height / ratio / currentScale;
            const workspaceRect = workspaceEl.getBoundingClientRect();
            // 預留 5% margin 給 scrollbar 與視覺留白
            const PADDING = 0.95;
            let newScale = 1;
            if (mode === "width") {
                newScale = (workspaceRect.width * PADDING) / logicalPageWidth;
            } else if (mode === "page") {
                newScale = Math.min(
                    (workspaceRect.width * PADDING) / logicalPageWidth,
                    (workspaceRect.height * PADDING) / logicalPageHeight,
                );
            }
            // canvas-editor executePageScale 範圍：0.5 ~ 3
            newScale = Math.max(0.5, Math.min(3, newScale));
            this.editor.command.executePageScale(newScale);
        } catch (e) {
            console.warn("[DocEditor] onZoomFitChange failed", e);
            this.notification.add(`縮放切換失敗：${e.message || e}`, { type: "warning" });
        }
    }

    /**
     * Sprint B：上一頁／下一頁。
     *
     * canvas-editor 沒有暴露 `editor.command.executePageNo`，但每頁渲染為獨立
     * `<canvas>` 元素於容器內。透過 `scrollIntoView` 把對應頁滾入視野，
     * 隨後由 `intersectionPageNoChange` listener 回寫 state.pageNo。
     */
    onPrevPage() {
        if (this.state.pageNo > 1) {
            this._scrollToPage(this.state.pageNo - 1);
        }
    }

    onNextPage() {
        if (this.state.pageNo < this.state.totalPages) {
            this._scrollToPage(this.state.pageNo + 1);
        }
    }

    /**
     * Sprint B 共用：把指定頁（1-based）滾入視野。
     */
    _scrollToPage(targetPageOneBased) {
        if (!this.editor || !this.canvasContainer?.el) {
            return;
        }
        const target = parseInt(targetPageOneBased, 10);
        if (!Number.isFinite(target) || target < 1) {
            return;
        }
        try {
            // canvas-editor 每頁渲染為一個 <canvas>；用 nth-of-type 選第 N 個
            const pageCanvases = this.canvasContainer.el.querySelectorAll("canvas");
            const idx = target - 1;
            if (idx < 0 || idx >= pageCanvases.length) {
                this.notification.add(
                    `第 ${target} 頁不存在（文件共 ${pageCanvases.length} 頁）`,
                    { type: "warning" }
                );
                return;
            }
            pageCanvases[idx].scrollIntoView({ behavior: "smooth", block: "start" });
            // 樂觀更新 state.pageNo；intersectionPageNoChange listener 隨後會校正
            this.state.pageNo = target;
        } catch (e) {
            console.warn("[DocEditor] _scrollToPage failed", e);
        }
    }


    // ─── Phase 2.1 補項：Inspector 雙向綁定 ──────────────────────────

    /**
     * 從 _templateFieldsCache 找當前選中的 field record。
     * 若找不到（cache 過期 / 還沒重新載），回 null，inspector 顯示空狀態。
     */
    get selectedField() {
        if (!this.state.selectedFieldId) return null;
        const list = this._templateFieldsCache || [];
        return list.find(f => f.id === this.state.selectedFieldId) || null;
    }

    /**
     * Sprint L：給 inspector 上方顯示「所有欄位」列表用的 getter。
     *
     * 從 _templateFieldsCache 取出排序穩定的列表：
     *   - 主排序：page_no 升冪（一頁文件、跨頁範本對齊瀏覽順序）
     *   - 次排序：id 升冪（同頁照建檔順序，新建檔的排後）
     *
     * 不做 dedup（每個 record 都是獨立欄位、即便 odoo_field_name 相同也代表
     * 文件內多處對應）。
     */
    get fieldsList() {
        const list = this._templateFieldsCache || [];
        return [...list].sort((a, b) => {
            const pa = a.page_no || 1;
            const pb = b.page_no || 1;
            if (pa !== pb) return pa - pb;
            return (a.id || 0) - (b.id || 0);
        });
    }

    /**
     * Sprint O：套用 state.fieldListFilter 對 fieldsList 做 substring filter。
     *
     * 三個欄位都會被比對（case-insensitive）：
     *   - odoo_field_name（如 `partner_id.name`）
     *   - placeholder_text（如 `{{ project_name }}`）
     *   - field_type（如 `odoo_field`、`text`、`signature`）
     *
     * 空字串 → 回 fieldsList 原樣（不過濾）。
     */
    get filteredFieldsList() {
        const filter = (this.state.fieldListFilter || "").trim().toLowerCase();
        if (!filter) return this.fieldsList;
        return this.fieldsList.filter((f) => {
            const haystack = [
                f.odoo_field_name || "",
                f.placeholder_text || "",
                f.field_type || "",
            ].join(" ").toLowerCase();
            return haystack.includes(filter);
        });
    }

    /**
     * Sprint O：filter input 變更時觸發。直接寫 state，OWL 自動 re-render。
     * 不做 debounce —— 純記憶體 substring 比對在 < 500 fields 規模下 < 0.1ms。
     *
     * Sprint P：filter 變動時 reset focusedListIndex（避免指向不存在的 row）。
     */
    onFieldListFilterInput(value) {
        this.state.fieldListFilter = value || "";
        this.state.focusedListIndex = -1;
    }

    /**
     * Sprint P：inspector 列表的鍵盤導航。
     *
     * 綁在 ul.doc-inspector-fields-list-items 的 keydown listener 上：
     *   - ↓ / ↑   ：focusedListIndex ± 1（clamp 到 [0, length-1]）；scrollIntoView
     *   - Home    ：focusedListIndex = 0
     *   - End     ：focusedListIndex = length - 1
     *   - Enter   ：呼叫 onFieldListRowClick(filteredFieldsList[focused].id)
     *   - Escape  ：focusedListIndex = -1，blur ul
     *
     * 設計：focusedListIndex 與 selectedFieldId 分離 —— 鍵盤導覽時可以「先標
     * 在某 row 上不選」（focused），按 Enter 才真正 select + locateControl。
     * 與 selectedFieldId 視覺對比：focused = 藍框 / selected = 紫底。
     */
    onFieldListKeyDown(ev) {
        const list = this.filteredFieldsList;
        if (!list || list.length === 0) return;
        const cur = this.state.focusedListIndex;
        let next = cur;
        switch (ev.key) {
            case "ArrowDown":
                next = cur < 0 ? 0 : Math.min(cur + 1, list.length - 1);
                break;
            case "ArrowUp":
                next = cur < 0 ? list.length - 1 : Math.max(cur - 1, 0);
                break;
            case "Home":
                next = 0;
                break;
            case "End":
                next = list.length - 1;
                break;
            case "Enter":
                if (cur >= 0 && cur < list.length) {
                    this.onFieldListRowClick(list[cur].id);
                    ev.preventDefault();
                }
                return;
            case "Escape":
                this.state.focusedListIndex = -1;
                ev.target?.blur?.();
                ev.preventDefault();
                return;
            default:
                return;  // 其他鍵不擋（讓 user 輸入到 filter 走別的 listener）
        }
        if (next !== cur) {
            this.state.focusedListIndex = next;
            ev.preventDefault();
            // scrollIntoView：等下次 microtask、DOM 更新後再 scroll
            Promise.resolve().then(() => {
                try {
                    const ul = ev.currentTarget;
                    const li = ul?.querySelectorAll?.("li.doc-inspector-fields-list-item")?.[next];
                    li?.scrollIntoView?.({ block: "nearest" });
                } catch (e) {
                    // 任何 DOM 操作失敗都不擋
                }
            });
        }
    }

    /**
     * Sprint M：在 _templateFieldsCache 中、但沒有對應 control 在文件內的
     * field id 集合（孤兒 record）。
     *
     * 形成原因：
     *   1. user 用 Sprint G「掃描變數」只建 record、文件仍是純 `{{ var }}` 文字
     *   2. user 手動刪掉某個 control 但 Phase 8 Del 同步因故沒同步（極罕見 race）
     *   3. record 透過 inspector「刪除」清掉、但對應 control 還在（反向 race）
     *
     * 效能：每次 render 都會走 getControlList() + Set.has() × cache.length。
     *      10-50 個 control 的常態下 < 1ms；> 500 時可改用 state.controlListRev
     *      memoize（目前 KISS）。
     */
    get orphanRecordIds() {
        const cache = this._templateFieldsCache || [];
        if (cache.length === 0) return new Set();
        // 從 canvas-editor 抽當前 control list 的 conceptId 集合（IO 部分）
        let controlIds;
        try {
            const list = this.editor?.command?.getControlList?.() || [];
            controlIds = new Set();
            for (const item of list) {
                const cid = item?.control?.conceptId
                         || item?.conceptId
                         || item?.element?.control?.conceptId;
                if (!cid) continue;
                const n = parseInt(cid, 10);
                if (Number.isFinite(n)) controlIds.add(n);
            }
        } catch (e) {
            // getControlList 在某些 canvas-editor 版本可能 throw → 退化：不標孤兒
            return new Set();
        }
        // 純函式做 diff（Sprint Q 抽出至 jinja2_scanner.js，方便單測）
        return computeOrphanRecordIds(cache, controlIds);
    }

    /**
     * Sprint M：批次刪除所有孤兒 record。
     *   - 列出將被刪的 id + 變數名（top 5）讓 user 確認
     *   - Promise.all 並行 delete_field
     *   - 從 cache / _lastControlIds / selectedFieldId 移除
     *   - 用最後一次 success response 更新 signer count + field count
     */
    async onCleanupOrphansClick() {
        if (!this.state.docId || !this._hasTemplate) {
            this.notification.add("此文件未關聯範本", { type: "warning" });
            return;
        }
        const orphans = this.orphanRecordIds;
        if (orphans.size === 0) {
            this.notification.add("沒有孤兒 record 需要清理。", { type: "info" });
            return;
        }
        const cache = this._templateFieldsCache || [];
        const orphanFields = cache.filter(f => orphans.has(f.id));
        const preview = orphanFields
            .slice(0, 5)
            .map(f => `  • ${f.odoo_field_name || f.placeholder_text || f.field_type} (#${f.id})`)
            .join("\n");
        const moreSuffix = orphanFields.length > 5 ? `\n  ... 還有 ${orphanFields.length - 5} 個` : "";
        const ok = window.confirm(
            `將刪除 ${orphans.size} 個沒有文件內 control 對應的孤兒 record：\n\n${preview}${moreSuffix}\n\n確定要繼續嗎？`
        );
        if (!ok) return;

        const ids = [...orphans];
        let lastSuccess = null;
        const failed = [];
        const results = await Promise.all(ids.map(async (id) => {
            try {
                const r = await rpc("/dobtor_doc/template_fields/delete_field", {
                    doc_id: this.state.docId,
                    field_id: id,
                });
                if (r && r.success) {
                    lastSuccess = r;
                    return { id, ok: true };
                }
                failed.push({ id, error: r?.error || "未知錯誤" });
                return { id, ok: false };
            } catch (e) {
                failed.push({ id, error: e?.message || String(e) });
                return { id, ok: false };
            }
        }));

        const deleted = results.filter(r => r.ok).map(r => r.id);
        if (deleted.length > 0) {
            this._templateFieldsCache = (this._templateFieldsCache || [])
                .filter(f => !deleted.includes(f.id));
            for (const id of deleted) this._lastControlIds?.delete(id);
            if (this.state.selectedFieldId && deleted.includes(this.state.selectedFieldId)) {
                this.state.selectedFieldId = null;
            }
            if (lastSuccess) {
                this._applySignerCounts(lastSuccess.signer_field_counts);
                this.state.fieldCount = lastSuccess.field_count;
            }
        }
        if (failed.length === 0) {
            this.notification.add(`已清理 ${deleted.length} 個孤兒 record。`, { type: "success" });
        } else {
            this.notification.add(
                `清理 ${deleted.length}/${orphans.size} 個，${failed.length} 個失敗（${failed.map(f => `#${f.id}`).slice(0, 3).join(", ")}${failed.length > 3 ? "..." : ""}）`,
                { type: "warning" }
            );
        }
    }

    /**
     * Sprint L：點 inspector 欄位列表的 row 時觸發。
     *   1. 設 selectedFieldId（讓下方屬性區顯示該 field 的編輯欄位）
     *   2. 呼叫 canvas-editor locationControl(conceptId) 把游標 / 視窗
     *      跳到文件內對應 control 位置（reverse 上：原本是「點 control 跳
     *      inspector」、此處反向「點 inspector 跳 control」）
     *
     * 容錯：locationControl 在某些 canvas-editor 版本可能不存在或 throw、
     *       靜默 catch、selectedFieldId 仍會被設好（inspector 編輯仍可用）。
     */
    onFieldListRowClick(fieldId) {
        if (!fieldId) return;
        // 設 selectedFieldId（讓 inspector 屬性區顯示此欄位）
        if (this.state.selectedFieldId !== fieldId) {
            this.state.selectedFieldId = fieldId;
        }
        // 跳到文件內對應 control
        try {
            this.editor?.command?.locationControl?.(String(fieldId));
        } catch (e) {
            // 該 fieldId 在文件內沒有對應 control（記錄存在但 control 未插入
            // 或已被刪），locationControl 會 throw、靜默忽略
            console.debug("[DocEditor] locationControl skipped for field", fieldId, e?.message);
        }
    }

    /**
     * 從 FIELD_TYPES 拿到選中 field 的 label（顯示在 inspector header）。
     */
    get selectedFieldLabel() {
        const f = this.selectedField;
        if (!f) return "";
        const meta = FIELD_TYPES.find(x => x.key === f.field_type);
        return meta ? meta.label : f.field_type;
    }

    /**
     * Inspector 內欄位變動時呼叫，debounce 500ms 後送後端 save_field。
     * key: 'placeholder_text' | 'required' | 'font_size' | 'odoo_field_name' | 'signer_id'
     *      | 'pos_x' | 'pos_y' | 'width' | 'height'（Sprint F：overlay 模式可改）
     */
    onInspectorFieldChange(key, value) {
        const field = this.selectedField;
        if (!field) return;
        // 本地立即更新（樂觀 UI），保證輸入流暢
        if (key === "required") {
            field[key] = !!value;
        } else if (key === "font_size" || key === "signer_id") {
            field[key] = parseInt(value, 10) || field[key];
        } else if (key === "pos_x" || key === "pos_y" || key === "width" || key === "height") {
            // Sprint F：浮點數，但 user 輸入整數即可
            const n = parseFloat(value);
            if (Number.isFinite(n)) {
                field[key] = Math.max(0, n);
            }
            // 強制 OWL re-render overlay layer 以反映新位置/尺寸
            this.state.overlayFieldsRev++;
        } else {
            field[key] = value;
        }

        // debounce save
        if (this._inspectorSaveTimer) clearTimeout(this._inspectorSaveTimer);
        this._inspectorSaveTimer = setTimeout(async () => {
            try {
                const payload = {
                    id: field.id,
                    signer_id: field.signer_id,
                    field_type: field.field_type,
                    page_no: field.page_no,
                    required: field.required,
                    placeholder_text: field.placeholder_text,
                    font_size: field.font_size,
                    odoo_field_name: field.odoo_field_name,
                    // Sprint F：overlay 幾何屬性
                    pos_x: field.pos_x,
                    pos_y: field.pos_y,
                    width: field.width,
                    height: field.height,
                };
                const result = await rpc("/dobtor_doc/template_fields/save_field", {
                    doc_id: this.state.docId,
                    field: payload,
                });
                if (!result.success) {
                    this.notification.add(`欄位更新失敗：${result.error}`, { type: "danger" });
                    return;
                }
                this._applySignerCounts(result.signer_field_counts);
                this.state.fieldCount = result.field_count;
            } catch (e) {
                console.error("[DocEditor] onInspectorFieldChange save failed", e);
                this.notification.add(`欄位更新失敗：${e.message || e}`, { type: "danger" });
            }
        }, 500);
    }

    /**
     * Inspector 「刪除欄位」按鈕：刪後端紀錄 + 從 cache 移除 + 清 selectedFieldId。
     * 注意 canvas-editor 上的 inline control 不會自動同步刪除（user 需自行按 Del 鍵）。
     */
    async onInspectorDeleteField() {
        const field = this.selectedField;
        if (!field) return;
        try {
            const result = await rpc("/dobtor_doc/template_fields/delete_field", {
                doc_id: this.state.docId,
                field_id: field.id,
            });
            if (!result.success) {
                this.notification.add(`刪除失敗：${result.error}`, { type: "danger" });
                return;
            }
            // 從 cache 移除
            this._templateFieldsCache = (this._templateFieldsCache || []).filter(f => f.id !== field.id);
            // 從 control id tracker 移除（避免 contentChange 誤發無效 RPC）
            this._lastControlIds?.delete(field.id);
            this._applySignerCounts(result.signer_field_counts);
            this.state.fieldCount = result.field_count;
            this.state.selectedFieldId = null;
            this.notification.add(
                "後端欄位紀錄已刪除。文件上的占位符請按 [Del] 移除。",
                { type: "info" }
            );
        } catch (e) {
            this.notification.add(`刪除失敗：${e.message || e}`, { type: "danger" });
        }
    }

};
