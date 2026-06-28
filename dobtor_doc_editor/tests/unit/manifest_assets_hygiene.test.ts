/**
 * manifest_assets_hygiene.test.ts — Phase 8 Sprint I (2026-05-24)
 *
 * 防止 Sprint G/H 漏加 jinja2_scanner.js 到 __manifest__ assets 那種類型的 bug。
 *
 * 規則：static/src/components/、static/src/core/、static/src/css/ 底下每一個
 *      .js / .xml / .css 檔案都必須被 __manifest__.py 的 `assets` 區段
 *      **主動引用**（不算被註解掉的行）。例外清單：
 *        - test_harness.js / *.test.js — 開發/測試用
 *        - 已知 legacy 檔案（HTML/Wysiwyg 時代殘留，留作 reference）
 *
 * 失敗訊息會列出未被引用的檔案 + 提示如何加進 manifest。
 */

import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { globSync } from "glob";
import { resolve } from "node:path";

// 模組根 = 本檔的兩層上層（tests/unit/ → 模組根）
const MODULE_ROOT = resolve(__dirname, "../..");
const MODULE_NAME = "dobtor_doc_editor";

/**
 * 例外清單：這些檔案**故意不在** manifest assets 內，但仍允許留在源樹。
 * 增加例外時請在註解寫清楚原因，避免後人懷疑。
 */
const ALLOW_NOT_IN_MANIFEST = new Set<string>([
    // 開發/測試 harness，從 node 直接跑、不進 Odoo bundle
    "static/src/components/doc_editor/test_harness.js",

    // HTML/Wysiwyg 時代殘留，已被 canvas-editor 版本取代；
    // manifest 內以註解形式保留 reference，方便日後追溯
    "static/src/components/doc_page_layout/doc_page_layout.js",
    "static/src/components/doc_page_layout/doc_page_layout.xml",
    "static/src/components/doc_ruler/doc_ruler.js",
    "static/src/components/doc_ruler/doc_ruler.xml",
    "static/src/core/pagination_engine.js",
]);

/** Glob 出所有可能要 bundle 的源檔（components / core / css） */
function listAssetSources(): string[] {
    const patterns = [
        "static/src/components/**/*.{js,xml,css}",
        "static/src/core/**/*.{js,xml,css}",
        "static/src/css/**/*.css",
    ];
    const results = new Set<string>();
    for (const p of patterns) {
        for (const f of globSync(p, { cwd: MODULE_ROOT, nodir: true })) {
            results.add(f.replace(/\\/g, "/"));  // normalise Windows path
        }
    }
    return [...results].sort();
}

/**
 * 從 __manifest__.py 抽出**主動引用**的 asset 路徑（不算註解行）。
 * Odoo manifest 用 Python 字串清單，註解以 `#` 開頭——這道過濾很簡單但夠用。
 */
function extractActiveManifestRefs(): Set<string> {
    const text = readFileSync(resolve(MODULE_ROOT, "__manifest__.py"), "utf8");
    const refs = new Set<string>();
    for (const rawLine of text.split("\n")) {
        const line = rawLine.trim();
        if (line.startsWith("#")) continue;  // 整行註解 → 跳過
        // 抓 `'dobtor_doc_editor/...'` 或 `"dobtor_doc_editor/..."` 出現
        const re = new RegExp(`['"]${MODULE_NAME}/([^'"]+)['"]`, "g");
        let m;
        while ((m = re.exec(line)) !== null) {
            refs.add(m[1]);
        }
    }
    return refs;
}

describe("manifest assets hygiene (Sprint I)", () => {
    it("每個 components/core/css 底下的 .js/.xml/.css 都被 __manifest__ 引用（或在例外清單）", () => {
        const sources = listAssetSources();
        const manifestRefs = extractActiveManifestRefs();
        const missing: string[] = [];

        for (const src of sources) {
            if (ALLOW_NOT_IN_MANIFEST.has(src)) continue;
            if (!manifestRefs.has(src)) {
                missing.push(src);
            }
        }

        if (missing.length > 0) {
            const hint = missing
                .map(p => `  • '${MODULE_NAME}/${p}',`)
                .join("\n");
            throw new Error(
                `以下 ${missing.length} 個 asset 檔案未被 __manifest__.py 引用（runtime 會 import 失敗）：\n\n${hint}\n\n` +
                `修法：加進 __manifest__.py 的 'assets' 區段（web.assets_backend 與/或 web.assets_frontend），` +
                `**順序很重要**——被 import 的 module 必須在 importer 之前。\n` +
                `若刻意不 bundle（如測試 harness、legacy），把路徑加進 tests/unit/manifest_assets_hygiene.test.ts 的 ALLOW_NOT_IN_MANIFEST、附上原因。`
            );
        }
        expect(missing).toEqual([]);
    });

    it("ALLOW_NOT_IN_MANIFEST 內的路徑都實際存在（避免過期例外）", () => {
        const sources = new Set(listAssetSources());
        const stale: string[] = [];
        for (const allowed of ALLOW_NOT_IN_MANIFEST) {
            if (!sources.has(allowed)) {
                stale.push(allowed);
            }
        }
        if (stale.length > 0) {
            throw new Error(
                `ALLOW_NOT_IN_MANIFEST 內有 ${stale.length} 個路徑已不存在，請清理：\n${stale.map(p => `  • ${p}`).join("\n")}`
            );
        }
        expect(stale).toEqual([]);
    });

    it("manifest 內引用的路徑都實際存在（避免引用刪除的檔案）", () => {
        const sources = new Set(listAssetSources());
        const manifestRefs = extractActiveManifestRefs();
        const phantom: string[] = [];
        for (const ref of manifestRefs) {
            // 只檢查 components / core / css 範圍（其他如 lib/ 不在本檢查範疇）
            if (!/^static\/src\/(components|core|css)\//.test(ref)) continue;
            if (!sources.has(ref)) {
                phantom.push(ref);
            }
        }
        if (phantom.length > 0) {
            throw new Error(
                `__manifest__.py 引用了 ${phantom.length} 個不存在的 asset 檔案：\n${phantom.map(p => `  • ${p}`).join("\n")}`
            );
        }
        expect(phantom).toEqual([]);
    });
});
