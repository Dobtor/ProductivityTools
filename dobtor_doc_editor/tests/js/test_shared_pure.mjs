/**
 * doc_editor_shared.js 的純函式單測（node，不需要 Odoo 或瀏覽器）。
 *
 * 為什麼是 node 而不是 hoot：這個模組沒有 hoot/QUnit 基礎設施，而
 * `web.assets_unit_tests` 要靠瀏覽器 runner 才跑得起來——CI 刻意不跑瀏覽器。
 * doc_editor_shared.js **沒有任何 import**（它存在的理由就是切斷循環
 * import），所以 node 可以直接把它當 ESM 載入並斷言。
 *
 * ☠️ 不能寫 `import "../../static/.../doc_editor_shared.js"`：那個目錄沒有
 * `package.json`，node 會把 .js 當 CommonJS 解析，撞到 `export` 就掛。
 * 改成讀檔 → data: URL 動態 import。檔案一旦新增相對 import 這招就會失效，
 * 那時應該修的是「shared 不該有 import」而不是這支測試。
 *
 * 跑法：node dobtor_doc_editor/tests/js/test_shared_pure.mjs
 * CI：dobtor_doc_editor_static.yml（擋 PR）
 */
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import assert from "node:assert/strict";

const here = dirname(fileURLToPath(import.meta.url));
const sharedPath = join(
    here, "..", "..", "static", "src", "components", "doc_editor",
    "doc_editor_shared.js"
);
const src = await readFile(sharedPath, "utf8");
if (/^\s*import\s/m.test(src)) {
    throw new Error(
        "doc_editor_shared.js 出現了 import——它必須保持零相依"
        + "（存在的理由是切斷循環 import），這支測試的載入方式也會失效。"
    );
}
const mod = await import(
    "data:text/javascript;base64," + Buffer.from(src, "utf8").toString("base64")
);

const { isSessionExpiredResponse, signerColor } = mod;

let passed = 0;
function check(name, fn) {
    fn();
    passed += 1;
    console.log("  ok  " + name);
}

// ─── isSessionExpiredResponse ────────────────────────────────────────────
// 業務情境：編輯器開著好幾小時（寫合約、排版報表），午休回來按「匯入」。
// Odoo 對 session 逾時是 303 轉址到 /web/login，fetch 跟過去之後拿到的是
// 登入頁 HTML、status 200——不是 4xx。認不出來的話使用者看到的是登入頁
// 被剝成純文字的字串。
check("轉址到 /web/login → 認得出是 session 逾時", () => {
    assert.equal(isSessionExpiredResponse({
        redirected: true,
        url: "http://localhost:8069/web/login?redirect=%2Fdobtor_doc%2Fimport",
        status: 200,
    }), true);
});

check("沒轉址的正常 JSON 回應 → 不是逾時", () => {
    assert.equal(isSessionExpiredResponse({
        redirected: false,
        url: "http://localhost:8069/dobtor_doc/upload_template",
        status: 200,
    }), false);
});

check("handler 回的 400（decorator 的 JSON）→ 不是逾時", () => {
    // 這一則守的是「不要把正常的錯誤路徑誤判成逾時」——誤判的話使用者會被
    // 叫去重新登入，而真正的原因（沒有寫入權限）就不見了。
    assert.equal(isSessionExpiredResponse({
        redirected: false,
        url: "http://localhost:8069/dobtor_doc/upload_template",
        status: 400,
    }), false);
});

check("轉址到別的地方 → 不是逾時", () => {
    assert.equal(isSessionExpiredResponse({
        redirected: true,
        url: "http://localhost:8069/web/database/selector",
        status: 200,
    }), false);
});

check("路徑只是開頭像 /web/login → 不算（比對整個 pathname）", () => {
    assert.equal(isSessionExpiredResponse({
        redirected: true,
        url: "http://localhost:8069/web/login_other",
        status: 200,
    }), false);
});

check("resp 是 null / url 不合法 → 不丟例外，回 false", () => {
    assert.equal(isSessionExpiredResponse(null), false);
    assert.equal(isSessionExpiredResponse(undefined), false);
    assert.equal(isSessionExpiredResponse({ redirected: true, url: "" }), false);
    assert.equal(isSessionExpiredResponse({ redirected: true }), false);
});

// ─── 順手守一支同檔的純函式（證明這個載入方式可重複使用）───────────────
check("signerColor 對負數與非數字都要給得出顏色", () => {
    assert.equal(typeof signerColor(0), "string");
    assert.equal(signerColor(-1), signerColor(1));
    assert.equal(signerColor(NaN), signerColor(0));
    assert.equal(signerColor(undefined), signerColor(0));
});

console.log(`\n${passed} 則全部通過`);
