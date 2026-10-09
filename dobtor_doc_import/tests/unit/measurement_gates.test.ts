/**
 * measurement_gates.test.ts — 量測閘門不可以在「沒量到東西」時說通過
 *
 * ☠️ 2026-10-09 稽核在兩個地方抓到同一個洞：
 *
 *   tests/scripts/run_visual_regression.sh  threshold gate：results 是空陣列
 *       → errors=[] 、ok=[] → failures=[] → 印「✓ PASSED」並 exit 0
 *   scripts/visual_regression_v14.mjs       只看 failedPages 與 bootFailed
 *       → `rendered=0/0 comparedPages=0 failedPages=0` 也 exit 0
 *
 * 觸發路徑都很平凡：--filter / --category 打錯、fixture 目錄撈不到、
 * golden PNG 還沒產生。症狀是**跟跑得漂亮完全分不出來**。
 *
 * 這跟 bundle_reachability.test.ts 守的是同一個失效模式的兩種形狀：
 *   那邊是「程式存在但不執行」，這邊是「閘門執行了但沒量到東西還說通過」。
 *
 * 兩道閘門都**真的執行**來驗，不是比對原始碼字串——比對字串的守衛會在
 * 重寫實作時失效，而且它證明的是「文字還在」不是「行為還對」。
 */
import { describe, expect, it } from "vitest";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const MODULE_ROOT = resolve(__dirname, "../..");
const VR_SH = resolve(MODULE_ROOT, "tests/scripts/run_visual_regression.sh");

/**
 * 把 run_visual_regression.sh 裡的 threshold gate（python heredoc）抽出來。
 * 抽不到就讓測試紅——那代表腳本結構變了，這支守衛跟著失效，
 * 而「守衛自己悄悄失效」正是它要防的事。
 */
function extractThresholdGate(): string {
    const src = readFileSync(VR_SH, "utf8");
    const m = src.match(/<<'PYEOF'\n([\s\S]*?)\nPYEOF/);
    expect(
        m,
        `${VR_SH} 裡抽不到 <<'PYEOF' … PYEOF 的 threshold gate。`
        + `腳本結構若改了，請同步改這支測試——不要讓它變成空轉的綠燈。`,
    ).not.toBeNull();
    return m![1];
}

/** 用一份 results JSON 跑 gate，回它的退出碼與輸出。 */
function runGate(results: unknown): { code: number; out: string } {
    const dir = mkdtempSync(join(tmpdir(), "vrgate-"));
    const json = join(dir, "results.json");
    writeFileSync(json, JSON.stringify(results));
    try {
        const out = execFileSync(
            "python3",
            ["-c", extractThresholdGate(), json, "0.05", "0.10", "0"],
            { encoding: "utf8" },
        );
        return { code: 0, out };
    } catch (e: any) {
        return { code: e.status ?? -1, out: `${e.stdout ?? ""}${e.stderr ?? ""}` };
    }
}

describe("run_visual_regression.sh 的 threshold gate", () => {
    it("0 筆結果 → 不可以通過", () => {
        const r = runGate([]);
        expect(r.code, `空結果竟然通過了：\n${r.out}`).not.toBe(0);
        expect(r.out).toContain("0 筆結果");
    });

    it("有結果但沒有一筆算出 meanDiff → 不可以通過", () => {
        const r = runGate([{ fixture: "a", error: "boom" }]);
        expect(r.code, `全錯竟然通過了：\n${r.out}`).not.toBe(0);
    });

    it("正常結果 → 要通過（確認上面兩則沒有誤殺）", () => {
        const r = runGate([{ fixture: "a", meanDiff: 0.01 }]);
        expect(r.code, `正常結果被誤殺：\n${r.out}`).toBe(0);
        expect(r.out).toContain("PASSED");
    });

    it("diff 超標 → 仍然要攔（原本的判定沒被新守衛蓋掉）", () => {
        const r = runGate([{ fixture: "a", meanDiff: 0.9 }]);
        expect(r.code).not.toBe(0);
    });
});

describe("visual_regression_v14.mjs 的退出碼", () => {
    it("--filter 撈不到任何 fixture → 退 2（設定／環境問題，不是通過）", () => {
        let code = 0;
        try {
            execFileSync(
                "node",
                ["scripts/visual_regression_v14.mjs",
                 "--filter", "__nonexistent__", "--max-fixtures", "1"],
                { cwd: MODULE_ROOT, encoding: "utf8", stdio: "pipe" },
            );
        } catch (e: any) {
            code = e.status ?? -1;
        }
        expect(
            code,
            "fixture 一份都沒撈到卻回 0——那跟全部通過分不出來。",
        ).toBe(2);
    }, 120_000);
});
