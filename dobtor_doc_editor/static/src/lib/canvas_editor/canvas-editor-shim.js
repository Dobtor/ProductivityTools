// canvas-editor-plugin-docx UMD 的外部依賴名稱是 window.canvasEditor（camelCase）
// 但 canvas-editor.umd.min.js 掛載於 window["canvas-editor"]（連字號）
// 此 shim 建立別名，確保 plugin 能正確取得核心庫
(function () {
    if (typeof window !== "undefined" && window["canvas-editor"] && !window.canvasEditor) {
        window.canvasEditor = window["canvas-editor"];
    }
})();
