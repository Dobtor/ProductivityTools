/** @odoo-module **/
/**
 * doc_editor 的模組層級常數與純函式。
 *
 * 單獨一支的理由是**避免循環 import**：四層 mixin 需要這些常數，而
 * doc_editor.js 需要那四層——常數留在 doc_editor.js 的話就是一圈。
 * doc_editor.js 仍然 re-export 它們，因為 OWL 模板是用 component 的
 * static 欄位取用的。
 */
export const FONT_OPTIONS = [
    { value: "",                 label: "預設" },
    { value: "Microsoft JhengHei", label: "微軟正黑體" },
    { value: "Microsoft YaHei",  label: "微軟雅黑" },
    { value: "PMingLiU",         label: "新細明體" },
    { value: "DFKai-SB",         label: "標楷體" },
    { value: "Noto Sans TC",     label: "思源黑體" },
    { value: "Noto Serif TC",    label: "思源宋體" },
    { value: "Arial",            label: "Arial" },
    { value: "Times New Roman",  label: "Times New Roman" },
    { value: "Courier New",      label: "Courier New" },
    { value: "Helvetica",        label: "Helvetica" },
    { value: "Georgia",          label: "Georgia" },
];
export const FONT_SIZE_OPTIONS = [8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 32, 36, 48, 60, 72];

// ─── Sprint Y25：localStorage helper（統一 try/catch + 可選 JSON parse/stringify）
// Y9 / Y13 / Y19 / Y23 各自寫過 4 次 boilerplate；Y25 抽成一致 API。
// 設計重點：兩個 helper 都 _不_ throw，失敗（quota / private mode / 環境不支援）
// 回傳 `null` (get) 或 `false` (set)，呼叫端用預設值 fallback。
export function _lsGet(key, { json = false } = {}) {
    try {
        const raw = localStorage.getItem(key);
        if (raw === null) return null;
        return json ? JSON.parse(raw) : raw;
    } catch (e) { return null; }
}
export function _lsSet(key, value, { json = false } = {}) {
    try {
        localStorage.setItem(key, json ? JSON.stringify(value) : String(value));
        return true;
    } catch (e) { return false; }
}

// ═══ Phase 4（藥丸改版）：模型變數藥丸 ═══════════════════════════════
//
// 綁定定義存在元素的 extension.dobtorField——canvas-editor 的官方擴充點，
// 且在其序列化白名單內，能安然通過 getValue()/setValue() 進 content_json。
// 鍵名必須與後端 doc_render_mixin.DOBTOR_FIELD_KEY 一致。
export const DOBTOR_FIELD_KEY = "dobtorField";
/**
 * 區塊容器標記鍵（掛在 table 元素的 extension 上）。
 * 條件區塊、稅額彙總這類要包住多段內容的構件，容器一律用無框線表格——
 * 元素串列是扁平的，只有換行與表格列是可靠邊界。
 */
export const DOBTOR_BLOCK_KEY = "dobtorBlock";

/**
 * 「主記錄欄位」面板只列這些型別。
 * 必須與後端 doc.render.mixin._SCALAR_TTYPES 一致——後端放寬了欄位清單
 * （為了讓 one2many 餵給重複列、binary 餵給圖片藥丸），前端要負責分流。
 */
/** i18n 藥丸的底色：與模型變數（藍）分開，一眼看出哪些是靜態文字。 */
export const I18N_PILL_STYLE = {
    backgroundColor: "#fff3e0",
    color: "#e65100",
};

export const SCALAR_FIELD_TYPES = [
    "char", "text", "html", "integer", "float", "monetary",
    "date", "datetime", "boolean", "selection", "many2one",
];

// canvas-editor 0.9.128 內建 ElementType.LABEL 與 labelParticle（畫圓角矩形），
// 這組值即其預設值；抽成常數是為了讓 inspector 的色票有共同起點。
export const PILL_STYLE = {
    backgroundColor: "#e3f2fd",
    color: "#1976d2",
    borderRadius: 4,
    padding: [2, 6, 2, 6],
};

// Phase 7：簽約人色票。doc.template.signer.color 是 Odoo 的 colour index（整數），
// 這裡對應成待填欄位在畫布上的底色，讓「這格誰要填」一眼看得出來。
// 取值刻意偏淡：control 底色是襯在文字後面的，太飽和會蓋掉字。
export const SIGNER_COLORS = [
    "#eceff1", "#ffcdd2", "#ffe0b2", "#fff9c4", "#dcedc8",
    "#c8e6c9", "#b2dfdb", "#b3e5fc", "#d1c4e9", "#f8bbd0",
    "#d7ccc8",
];

export function signerColor(index) {
    const n = Number.isFinite(index) ? Math.abs(Math.trunc(index)) : 0;
    return SIGNER_COLORS[n % SIGNER_COLORS.length];
}

/** 值來源：record 從記錄取、expression 任意 Jinja、static 固定文字。 */
export const VALUE_SOURCES = [
    { key: "record", label: "關聯記錄" },
    { key: "expression", label: "表達式" },
    { key: "static", label: "固定值" },
];

export const FIELD_TYPES = [
    { key: "name",       label: "名稱",     icon: "A",     ctrlType: "text" },
    { key: "email",      label: "電子郵件", icon: "A",     ctrlType: "text" },
    { key: "phone",      label: "電話",     icon: "A",     ctrlType: "text" },
    { key: "company",    label: "公司",     icon: "A",     ctrlType: "text" },
    { key: "title",      label: "標題",     icon: "A",     ctrlType: "text" },
    { key: "text",       label: "文字",     icon: "A",     ctrlType: "text" },
    { key: "date",       label: "日期",     icon: "fa-calendar", ctrlType: "date" },
    { key: "checkbox",   label: "核取方塊", icon: "fa-check-square-o", ctrlType: "checkbox" },
    { key: "select",     label: "下拉選單", icon: "fa-caret-square-o-down", ctrlType: "select" },
    { key: "radio",      label: "單選組",   icon: "fa-dot-circle-o", ctrlType: "radio" },
    { key: "signature",  label: "簽名",     icon: "fa-pencil", ctrlType: "text" },
    { key: "initial",    label: "繕寫簽名", icon: "fa-edit", ctrlType: "text" },
];

