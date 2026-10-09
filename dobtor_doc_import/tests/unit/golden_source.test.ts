/**
 * golden_source.test.ts — golden PNG 的渲染來源必須與目標一致，或**被明確宣告為不一致**
 *
 * ☠️ 2026-10-09 範圍收斂到「1:1 重現 Microsoft Word」之後，出現一個結構性的
 * 不一致：126 張 golden PNG 全部是 **LibreOffice** 渲染的。
 *
 *   即使視覺回歸 diff 降到 0%，也只代表「我們渲染得跟 LibreOffice 一樣」，
 *   不代表跟 Word 一樣。
 *
 * LibreOffice 自己對 Word 的重現就不是 1:1（斷行、字距、列高、分頁規則都有差），
 * 拿它當 1:1 Word 的基準，等於用一把不準的尺去校準。
 *
 * ☠️ 這支測試的第一版是「renderer ≠ target 就紅」——也就是**一個永遠紅的測試**。
 * 那正是這個專案一整天在反對的事（阻擋式紅燈配上無法立即修的狀況 ＝ 訓練大家
 * 無視紅燈）。改成「宣告 ＋ 守衛」：
 *
 *   - 不一致時，`status` 必須明確寫 `MISMATCH` → 綠（現況，已被承認）
 *   - 不一致卻沒宣告 → 紅（有人改了 renderer 沒說）
 *   - 一致了卻還寫 MISMATCH → 紅（宣告過期，該改成 MATCH）
 *
 * 這樣它現在是綠的，但任何一邊被偷偷改掉都會紅。
 *
 * 詳見 tests/fixtures/GOLDEN_SOURCE.md。
 */
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const DOC = resolve(__dirname, "../fixtures/GOLDEN_SOURCE.md");

function field(name: string): string {
    const text = readFileSync(DOC, "utf8");
    const m = text.match(new RegExp(`^${name}:\\s*([A-Za-z-]+)`, "m"));
    if (!m) throw new Error(`GOLDEN_SOURCE.md 裡找不到欄位 ${name}`);
    return m[1];
}

describe("golden 的渲染來源", () => {
    it("三個欄位都要填", () => {
        for (const f of ["renderer", "target", "status"]) {
            expect(field(f).length, `${f} 沒填`).toBeGreaterThan(0);
        }
    });

    it("renderer ≠ target 時必須宣告 MISMATCH（不一致不可以是靜默的）", () => {
        const renderer = field("renderer");
        const target = field("target");
        const status = field("status");
        if (renderer !== target) {
            expect(
                status,
                `\ngolden 是用 **${renderer}** 渲染的，而目標是 **${target}**，`
                + `但 status 不是 MISMATCH。\n`
                + `\n`
                + `視覺回歸的 diff 降到 0%，只代表「我們渲染得跟 ${renderer} 一樣」，`
                + `**不代表跟 ${target} 一樣**。\n`
                + `這個不一致是整個 1:1 目標裡最大的缺件，而它不會以任何其他方式`
                + `顯現——VR 照樣跑得出漂亮的數字。\n`
                + `改了 renderer 或 target 就要同步改 status，並更新`
                + ` tests/fixtures/GOLDEN_SOURCE.md 的說明。\n`,
            ).toBe("MISMATCH");
        }
    });

    it("renderer === target 時不可以還掛著 MISMATCH（宣告過期）", () => {
        const renderer = field("renderer");
        const target = field("target");
        if (renderer === target) {
            expect(
                field("status"),
                `renderer 與 target 都是 ${renderer} 了，status 應該改成 MATCH`,
            ).not.toBe("MISMATCH");
        }
    });
});
