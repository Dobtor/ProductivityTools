/** @odoo-module **/
/**
 * 編輯器面板的瀏覽器驗證。
 *
 * 為什麼要有這支：這個模組的前端量很大（doc_editor.js 約 7000 行、
 * doc_editor.xml 約 2000 行），而 Python 測試碰不到它。沒有 tour 的話，
 * 「模板引用了不存在的 getter」「inspector 分支寫錯」這類錯誤只會在使用者
 * 點下去的那一刻才出現——而且多半是靜默的（OWL 把渲染錯誤吞成空白面板）。
 *
 * 藥丸畫在 canvas 裡，DOM 點不到，所以選取藥丸一律透過
 * window._docEditorCmp（component instance 本來就為了 E2E 掛在那裡）
 * 直接設 state.selectedVariable，再驗右欄渲染出對的分支。
 * 這驗的是「inspector 分支的模板正確」，不是「canvas 選取邏輯正確」——
 * 後者要靠座標點擊，在 tour 裡不可靠，刻意不做。
 */
import { registry } from "@web/core/registry";

/** 等編輯器掛好（canvas-editor 初始化是非同步的）。 */
const waitEditor = {
    content: "等待編輯器初始化",
    trigger: ".o_dobtor_doc_editor .doc-left-tabs",
    run: () => {},
};

/** 直接設定選中的藥丸，再讓 OWL 重繪。 */
function selectPill(meta) {
    return () => {
        const cmp = window._docEditorCmp;
        if (!cmp) {
            throw new Error("window._docEditorCmp 不存在——component 沒掛載");
        }
        cmp.state.selectedFieldId = null;
        cmp.state.selectedVariable = meta;
    };
}

/** 斷言右欄出現了預期的標題文字。 */
function expectInspector(title) {
    return {
        content: `右欄應顯示「${title}」`,
        trigger: `.doc-inspector-header:contains("${title}")`,
        run: () => {},
    };
}

registry.category("web_tour.tours").add("doc_editor_panels_tour", {
    // 刻意不設 url：進入點由 Python 端的 start_tour 給（它要帶一個把
    // template_id 寫進 context 的 client action id）。這裡寫 url 會蓋掉它，
    // 瀏覽器就停在預設首頁——實測時停在 Discuss，然後第一步就找不到編輯器。
    steps: () => [
        waitEditor,

        // ─── 左欄：欄位分頁的各個群組 ───
        {
            content: "切到「欄位」分頁",
            trigger: ".doc-left-tab:contains('欄位')",
            run: "click",
        },
        {
            content: "條件群組",
            trigger: ".doc-palette-group-head:contains('條件')",
            run: () => {},
        },
        {
            content: "插入條件區塊的按鈕在",
            trigger: ".doc-field-palette-item:contains('插入條件區塊')",
            run: () => {},
        },
        {
            content: "若／否則區塊的按鈕在",
            trigger: ".doc-field-palette-item:contains('插入若／否則區塊')",
            run: () => {},
        },
        {
            content: "欄條件的按鈕在",
            trigger: ".doc-field-palette-item:contains('插入欄條件')",
            run: () => {},
        },
        {
            content: "內建區塊群組（稅額彙總／頁碼／總頁數）",
            trigger: ".doc-field-palette-item:contains('稅額彙總')",
            run: () => {},
        },
        {
            content: "頁碼按鈕在",
            trigger: ".doc-field-palette-item:contains('頁碼')",
            run: () => {},
        },
        {
            content: "多語文字群組",
            trigger: ".doc-field-palette-item:contains('插入多語文字')",
            run: () => {},
        },
        {
            content: "抽出靜態文字的按鈕在",
            trigger: ".doc-field-palette-item:contains('抽出靜態文字')",
            run: () => {},
        },
        {
            content: "主記錄欄位群組（確認 modelFields 有載到）",
            trigger: ".doc-palette-group-head:contains('主記錄欄位')",
            run: () => {},
        },
        {
            content: "明細（一對多）群組——欄位白名單少了 one2many 的話這組不會出現",
            trigger: ".doc-field-palette-item:contains('設為重複列')",
            run: () => {},
        },

        // ─── 右欄：每一種藥丸的 inspector 分支 ───
        {
            content: "選取條件標記",
            trigger: "body",
            run: selectPill({ source: "condition", expression: "object.name",
                              labelText: "條件" }),
        },
        expectInspector("條件標記"),
        {
            content: "常用條件預設鈕有渲染",
            trigger: ".doc-inspector-preset-btn",
            run: () => {},
        },

        {
            content: "選取否則分支",
            trigger: "body",
            run: selectPill({ source: "condition", groupId: "g1",
                              role: "else", labelText: "否則" }),
        },
        {
            content: "否則分支不該出現條件輸入框",
            trigger: ".doc-inspector-note:contains('否則')",
            run: () => {},
        },

        {
            content: "條件式格式的按鈕在",
            trigger: ".doc-field-palette-item:contains('插入條件式格式')",
            run: () => {},
        },
        {
            content: "選取條件式格式標記",
            trigger: "body",
            run: selectPill({ source: "format", bold: true,
                              expression: "line.display_type == 'line_section'",
                              labelText: "條件格式" }),
        },
        expectInspector("條件式格式"),
        {
            content: "粗體勾選在",
            trigger: ".doc-inspector-field.is-check:contains('粗體')",
            run: () => {},
        },
        {
            content: "對齊下拉有「靠右」",
            trigger: ".doc-inspector-field:contains('對齊') select",
            run: () => {
                const field = [...document.querySelectorAll(
                    ".doc-inspector-field")].find(
                    (el) => el.textContent.includes("對齊"));
                const values = [...field.querySelector("select").options]
                    .map((o) => o.value);
                if (!values.includes("right")) {
                    throw new Error(`對齊下拉少了 right，實際 ${values}`);
                }
            },
        },
        {
            content: "選取欄條件",
            trigger: "body",
            run: selectPill({ source: "column", expression: "object.name",
                              labelText: "欄條件" }),
        },
        expectInspector("欄條件"),

        {
            content: "選取重複列",
            trigger: "body",
            run: selectPill({ source: "repeat", path: "order_line",
                              repeatId: "rp1", labelText: "明細" }),
        },
        expectInspector("重複列"),
        {
            content: "分組方式下拉在",
            trigger: ".doc-inspector-field:contains('分組方式') select",
            run: () => {},
        },
        {
            content: "列型條件欄位在",
            trigger: ".doc-inspector-field:contains('列型條件')",
            run: () => {},
        },
        {
            content: "排序欄位在",
            trigger: ".doc-inspector-field:contains('排序欄位')",
            run: () => {},
        },
        {
            content: "來源表達式在",
            trigger: ".doc-inspector-field:contains('來源表達式')",
            run: () => {},
        },

        {
            content: "選取分組取值藥丸",
            trigger: "body",
            run: selectPill({ source: "group", expression: "group.label",
                              labelText: "組名" }),
        },
        expectInspector("分組取值"),

        {
            content: "選取流水藥丸",
            trigger: "body",
            run: selectPill({ source: "running", op: "sum",
                              expression: "line.price_subtotal",
                              labelText: "累計" }),
        },
        expectInspector("流水值"),
        {
            content: "金額格式勾選在（op=sum 才出現）",
            trigger: ".doc-inspector-field.is-check:contains('金額格式')",
            run: () => {},
        },

        {
            content: "選取稅額彙總藥丸",
            trigger: "body",
            run: selectPill({ source: "taxTotals", part: "groups",
                              field: "amount", labelText: "稅額" }),
        },
        expectInspector("稅額彙總"),
        {
            content: "幣別下拉在（雙幣別支援）",
            trigger: ".doc-inspector-field:contains('幣別') select",
            run: () => {},
        },
        {
            // 不可以用 option:contains(...) 當 trigger：tour 的 trigger 要求
            // 元素可見，而關起來的 <select> 裡的 <option> 不可見，
            // 這一步會卡到 timeout（實測）。改成抓 select 再用 JS 看選項。
            content: "列別下拉要有現金捨入（原生有這一列，我們本來沒有）",
            trigger: ".doc-inspector-field:contains('這一列是') select",
            run: () => {
                const field = [...document.querySelectorAll(
                    ".doc-inspector-field")].find(
                    (el) => el.textContent.includes("這一列是"));
                const values = [...field.querySelector("select").options]
                    .map((o) => o.value);
                if (!values.includes("rounding")) {
                    throw new Error(`列別下拉少了 rounding，實際 ${values}`);
                }
            },
        },

        {
            content: "選取圖片藥丸",
            trigger: "body",
            run: selectPill({ source: "image", path: "signature",
                              labelText: "圖：簽名" }),
        },
        expectInspector("圖片"),
        {
            content: "圖片的來源表達式欄位在（算出來的圖片靠它）",
            trigger: ".doc-inspector-field:contains('來源表達式')",
            run: () => {},
        },

        {
            content: "選取條碼藥丸",
            trigger: "body",
            run: selectPill({ source: "image", barcodeType: "QR",
                              path: "name", labelText: "條碼" }),
        },
        {
            content: "條碼型別下拉在（isBarcodePill 分支）",
            trigger: ".doc-inspector-field:contains('條碼型別') select",
            run: () => {},
        },

        {
            content: "選取頁碼藥丸",
            trigger: "body",
            run: selectPill({ source: "page", part: "count",
                              labelText: "總頁數" }),
        },
        expectInspector("總頁數"),

        {
            content: "選取 HTML 藥丸",
            trigger: "body",
            run: selectPill({ source: "html", path: "note",
                              labelText: "HTML：條款" }),
        },
        expectInspector("HTML 欄位"),

        {
            content: "選取多語文字藥丸",
            trigger: "body",
            run: selectPill({ source: "i18n", key: "doc_title",
                              texts: { en_US: "Quotation" },
                              labelText: "報價單" }),
        },
        expectInspector("多語文字"),
        {
            content: "翻譯鍵欄位在",
            trigger: ".doc-inspector-field:contains('翻譯鍵')",
            run: () => {},
        },

        // ─── 欄位標籤藥丸（ADR-024）───
        // 表頭用它而不是多語文字藥丸：翻譯取自 Odoo 的欄位定義。
        {
            content: "選取欄位標籤藥丸",
            trigger: "body",
            run: selectPill({ source: "fieldLabel", path: "price_unit",
                              labelModel: "sale.order.line",
                              labelText: "單價" }),
        },
        expectInspector("欄位標籤"),
        {
            content: "欄位所屬模型的輸入框在（表頭要能指定明細模型）",
            trigger: ".doc-inspector-field:contains('欄位所屬模型')",
            run: () => {},
        },
        // ─── 頁面範圍標記 ───
        // 對應 LibreOffice 的「首頁相同」「左右頁相同」。
        {
            content: "選取頁面範圍標記",
            trigger: "body",
            run: selectPill({ source: "pageScope", scope: "first",
                              isMarker: true, labelText: "只在首頁" }),
        },
        expectInspector("頁面範圍"),
        {
            content: "「出現在」選單有四個範圍",
            trigger: ".doc-inspector-field:contains('出現在')",
            run: () => {
                const opts = Array.from(document.querySelectorAll(
                    ".doc-inspector-field select option")).map((o) => o.value);
                for (const want of ["first", "rest", "odd", "even"]) {
                    if (!opts.includes(want)) {
                        throw new Error(`「出現在」少了選項 ${want}`);
                    }
                }
            },
        },
        {
            content: "左欄有「只在首頁」的插入項",
            trigger: ".doc-field-palette-item:contains('只在首頁')",
            run: () => {},
        },

        {
            // 這顆鈕的 CSS 是 opacity:0、只有 .doc-field-palette-item:hover 才顯示
            //（doc_editor.css:3208）。tour 的 trigger 要求元素可見，所以不能直接
            // 拿它當 trigger——會卡到 timeout。改成在可見的群組標題上停住，
            // 用 querySelector 驗「模板真的渲染出這顆鈕」。
            content: "左欄的欄位列上有「插入欄位標籤」鈕（hover 才顯示，用 DOM 驗）",
            trigger: ".doc-palette-group-head:contains('主記錄欄位')",
            run: () => {
                const n = document.querySelectorAll(
                    ".doc-field-palette-item button[aria-label='插入欄位標籤']"
                ).length;
                if (!n) {
                    throw new Error("欄位列上沒有「插入欄位標籤」鈕");
                }
            },
        },

        // ─── 插入條件區塊：這是最容易壞的一段 ───
        // insertBlockContainer 要先插表格、再用內容簽章認出剛插入的那一個。
        // 認錯的話會把使用者既有的表格改成區塊容器，而那在畫面上看不出來。
        {
            content: "取消選取，回到可插入狀態",
            trigger: "body",
            run: () => { window._docEditorCmp.state.selectedVariable = null; },
        },
        {
            // canvas-editor 的 insertTable 在沒有游標時會靜默 return
            // （insertTable 開頭就 `if (!~startIndex && !~endIndex) return`），
            // 所以插入前一定要先讓文件取得游標。
            content: "先在文件中建立游標",
            trigger: ".canvas-editor-container canvas",
            run: "click",
        },
        {
            content: "記下插入前的表格數",
            trigger: "body",
            run: () => {
                const cmp = window._docEditorCmp;
                const data = cmp.editor.command.getValue().data;
                window.__tourTablesBefore = cmp._collectTables(data).length;
            },
        },
        {
            content: "點「插入條件區塊」",
            trigger: ".doc-field-palette-item:contains('插入條件區塊')",
            run: "click",
        },
        {
            content: "應該多了一個表格，而且被標成條件區塊",
            trigger: "body",
            run: () => {
                const cmp = window._docEditorCmp;
                const tables = cmp._collectTables(cmp.editor.command.getValue().data);
                const before = window.__tourTablesBefore;
                if (tables.length !== before + 1) {
                    throw new Error(
                        `表格數應為 ${before + 1}，實際 ${tables.length}`);
                }
                const blocks = tables.filter(
                    (t) => (t.extension || {}).dobtorBlock === "condition");
                if (!blocks.length) {
                    throw new Error("沒有任何表格被標成 dobtorBlock=condition");
                }
                const b = blocks[blocks.length - 1];
                if (b.borderType !== "dash") {
                    throw new Error(`borderType 應為 dash，實際 ${b.borderType}`);
                }
                const cellPills = (b.trList[0].tdList[0].value || []).filter(
                    (el) => el.type === "label"
                        && ((el.extension || {}).dobtorField || {}).source === "condition");
                if (!cellPills.length) {
                    throw new Error("區塊內沒有條件標記藥丸");
                }
            },
        },
        // ─── 插入稅額彙總：列結構與多語標籤 ───
        // 這一段驗的是「插入出來的東西對不對」，不只是按鈕在不在。
        // 小計列要依稅基數複製、要有現金捨入列、而「總計」與「現金捨入」
        // 這兩個寫死的字要是多語文字藥丸——寫死中文的話英文單據上會夾一個
        // 中文的「總計」。
        {
            content: "記下插入前的表格數（稅額彙總）",
            trigger: "body",
            run: () => {
                const cmp = window._docEditorCmp;
                window.__ttBefore = cmp._collectTables(
                    cmp.editor.command.getValue().data).length;
            },
        },
        {
            content: "點「插入稅額彙總」",
            trigger: ".doc-field-palette-item:contains('稅額彙總')",
            run: "click",
        },
        {
            content: "彙總區塊要有四列，後兩列的標籤是多語文字藥丸",
            trigger: "body",
            run: () => {
                const cmp = window._docEditorCmp;
                const tables = cmp._collectTables(
                    cmp.editor.command.getValue().data);
                if (tables.length !== window.__ttBefore + 1) {
                    throw new Error(
                        `表格數應為 ${window.__ttBefore + 1}，實際 ${tables.length}`);
                }
                const blocks = tables.filter(
                    (t) => (t.extension || {}).dobtorBlock === "taxTotals");
                if (!blocks.length) {
                    throw new Error("沒有表格被標成 dobtorBlock=taxTotals");
                }
                const b = blocks[blocks.length - 1];
                if ((b.trList || []).length !== 4) {
                    throw new Error(
                        `應為 4 列（小計／稅別／現金捨入／總計），實際 ${
                            (b.trList || []).length}`);
                }
                const metaOf = (row, col) => ((row.tdList[col].value || [])
                    .map((el) => (el.extension || {}).dobtorField)
                    .filter(Boolean)[0]) || {};
                const parts = b.trList.map((r) => metaOf(r, 1).part);
                if (parts.join(",") !== "untaxed,groups,rounding,total") {
                    throw new Error(`列的 part 應為 untaxed,groups,rounding,total，實際 ${parts}`);
                }
                for (const [idx, key] of [[2, "doc_tax_rounding"],
                                          [3, "doc_tax_total"]]) {
                    const label = metaOf(b.trList[idx], 0);
                    if (label.source !== "i18n") {
                        throw new Error(
                            `第 ${idx + 1} 列的標籤應是多語文字藥丸，實際 ${label.source}`);
                    }
                    if (label.key !== key) {
                        throw new Error(`翻譯鍵應為 ${key}，實際 ${label.key}`);
                    }
                    if (!(label.texts || {}).en_US) {
                        throw new Error(`${key} 少了 en_US 的文字`);
                    }
                }
                // 小計與稅別的名稱是 Odoo 給的資料，不該被改成多語文字
                for (const idx of [0, 1]) {
                    if (metaOf(b.trList[idx], 0).source !== "taxTotals") {
                        throw new Error(
                            `第 ${idx + 1} 列的名稱應該是 taxTotals 藥丸（那是資料）`);
                    }
                }
            },
        },

        {
            content: "插入若／否則區塊",
            trigger: ".doc-field-palette-item:contains('插入若／否則區塊')",
            run: "click",
        },
        {
            content: "若／否則應該是同一個表格的兩列、共用 groupId",
            trigger: "body",
            run: () => {
                const cmp = window._docEditorCmp;
                const tables = cmp._collectTables(cmp.editor.command.getValue().data);
                const pairs = tables.filter((t) => (t.trList || []).length === 2);
                if (!pairs.length) {
                    throw new Error("找不到兩列的區塊容器");
                }
                const t = pairs[pairs.length - 1];
                const metaOf = (row) => ((row.tdList[0].value || [])
                    .map((el) => (el.extension || {}).dobtorField)
                    .filter(Boolean)[0]) || {};
                const a = metaOf(t.trList[0]);
                const b = metaOf(t.trList[1]);
                if (!a.groupId || a.groupId !== b.groupId) {
                    throw new Error(
                        `兩列的 groupId 應相同，實際 ${a.groupId} / ${b.groupId}`);
                }
                if (a.role !== "if" || b.role !== "else") {
                    throw new Error(`role 應為 if/else，實際 ${a.role}/${b.role}`);
                }
            },
        },

        // ─── 左右側面板收合 ───
        // 放在最後：收起來時面板內容會不見，前面的步驟都還需要它們。
        // 每一組都「收起→驗→展開→驗」，不要留下收合狀態給下一次執行
        //（狀態存在 localStorage，會跨 tour 執行殘留）。
        {
            content: "收合左側面板",
            trigger: ".doc-thumbnail-panel .doc-panel-collapse-btn",
            run: "click",
        },
        {
            content: "左側只剩展開帶，而且中間變寬了",
            trigger: ".doc-thumbnail-panel.is-collapsed .doc-panel-collapse-strip",
            run: () => {
                const cols = document.querySelector(".doc-main")
                    .style.gridTemplateColumns || "";
                if (!cols.startsWith("28px")) {
                    throw new Error(`grid 第一欄應為 28px，實際「${cols}」`);
                }
                if (document.querySelector(".doc-left-tabs")) {
                    throw new Error("收合後左欄分頁還在");
                }
            },
        },
        {
            content: "展開左側面板",
            trigger: ".doc-thumbnail-panel .doc-panel-collapse-strip",
            run: "click",
        },
        {
            content: "左欄分頁回來了",
            trigger: ".doc-left-tabs",
            run: () => {},
        },
        {
            content: "收合右側面板",
            trigger: ".doc-inspector-panel .doc-panel-collapse-btn",
            run: "click",
        },
        {
            content: "右側只剩展開帶",
            trigger: ".doc-inspector-panel.is-collapsed .doc-panel-collapse-strip",
            run: () => {
                const cols = document.querySelector(".doc-main")
                    .style.gridTemplateColumns || "";
                if (!cols.trim().endsWith("28px")) {
                    throw new Error(`grid 第三欄應為 28px，實際「${cols}」`);
                }
            },
        },
        {
            content: "展開右側面板（不要留下收合狀態給下一次執行）",
            trigger: ".doc-inspector-panel .doc-panel-collapse-strip",
            run: "click",
        },
        {
            content: "右欄回來了",
            trigger: ".doc-inspector-topbar .doc-panel-collapse-btn",
            run: () => {},
        },
    ],
});
