/**
 * opentype.js 的型別宣告 shim。
 *
 * ☠️ 為什麼需要它：opentype.js v1.3.5 沒有附帶 .d.ts，而 tsconfig 是
 * `strict: true`，所以 `import * as opentypeNs from 'opentype.js'`
 * （static/src/core/ooxml/font/FontMetrics.ts:27）會是
 *   TS7016: Could not find a declaration file for module 'opentype.js'
 * ——**而 `npm run typecheck` 是 `make ci-frontend` 的第一步**，所以這一個
 * 錯誤會讓 vitest（3,075 則）與三個產物的建置全都跑不到。
 * 2026-10-09 稽核才發現匯入模組的 `make ci-all` 從來沒有通過。
 *
 * 刻意**不重述 opentype.js 的 API**：FontMetrics.ts 自己已經定義了
 * `OpentypeModule` / `OpentypeFont` 兩個結構介面，只取它真的會用到的那幾個
 * 欄位（unitsPerEm / ascender / descender / tables.os2 / tables.hhea /
 * charToGlyphIndex / glyphs）。真正的型別約束在那裡，這裡只負責讓 import
 * 成立。在這個檔案裡再抄一份 API 只會多一個會跟上游不同步的地方。
 *
 * 用 `unknown` 而不是 `any`：FontMetrics.ts 取到它之後立刻斷言成自己的介面，
 * `unknown` 迫使那個斷言留在原處（看得見），`any` 會讓它悄悄消失。
 */
declare module 'opentype.js' {
    const opentype: unknown;
    export default opentype;
}
