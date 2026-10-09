/**
 * vr_attribution.test.ts — 誤差拆解的純函式（優化 2）
 *
 * ☠️ 用**合成影像**測，不用真 fixture：合成的我知道正確答案。
 *    拿真 fixture 測拆解器，等於用一個未知去驗另一個未知——那不是測試，
 *    是兩個東西一起亂。本模組今天在「負向驗證」上學到的同一件事。
 *
 * 每一則都造一個**已知形狀**的誤差，然後斷言拆解器指認得出來：
 *   整體位移   → shift 分析要抓到位移量，而且 SSD 要明顯下降
 *   水平線位移 → byRegion 的 rule 要佔多數
 *   字寬累積   → advanceDrift 要接近 1（diff 集中在右半）
 *   均勻雜訊   → advanceDrift 要接近 0（不可以把雜訊誤判成字寬問題）
 */
import { describe, expect, it } from "vitest";
import {
    advanceDrift,
    attributeByRegion,
    bestShift1D,
    classifyRows,
    colInk,
    rowInk,
    shiftBuffer,
} from "../../scripts/vr_attribution.mjs";

const W = 40;
const H = 30;

/** 造一張全白 RGBA 影像。 */
function blank(w = W, h = H): Uint8Array {
    return new Uint8Array(w * h * 4).fill(255);
}

/** 在 (x, y) 畫一個黑點。 */
function ink(buf: Uint8Array, x: number, y: number, w = W): void {
    const i = (y * w + x) * 4;
    buf[i] = 0; buf[i + 1] = 0; buf[i + 2] = 0; buf[i + 3] = 255;
}

/** 畫一條水平線（整列全黑）。 */
function hLine(buf: Uint8Array, y: number, w = W): void {
    for (let x = 0; x < w; x++) ink(buf, x, y, w);
}

/** 畫一行「文字」：稀疏的點，佔寬度的 ~10%。 */
function textRow(buf: Uint8Array, y: number, w = W): void {
    for (let x = 0; x < w; x += 10) ink(buf, x, y, w);
}

/** 造一張 pixelmatch 風格的 diff（差異處塗紅）。 */
function diffAt(points: Array<[number, number]>, w = W, h = H): Uint8Array {
    const buf = new Uint8Array(w * h * 4).fill(0);
    for (const [x, y] of points) {
        const i = (y * w + x) * 4;
        buf[i] = 255; buf[i + 1] = 0; buf[i + 2] = 0; buf[i + 3] = 255;
    }
    return buf;
}

describe("ink profile", () => {
    it("rowInk 數得出每一列的深色像素", () => {
        const b = blank();
        hLine(b, 5);
        textRow(b, 10);
        const ink_ = rowInk(b, W, H);
        expect(ink_[5]).toBe(W);          // 整列
        expect(ink_[10]).toBe(4);         // 40 / 10 = 4 個點
        expect(ink_[0]).toBe(0);          // 空白列
    });

    it("colInk 同理，按欄算", () => {
        const b = blank();
        for (let y = 0; y < H; y++) ink(b, 7, y);
        const c = colInk(b, W, H);
        expect(c[7]).toBe(H);
        expect(c[8]).toBe(0);
    });
});

describe("最佳位移（整體偏移的指認）", () => {
    it("往下位移 3 列 → shift 要抓到 -3 或 3，且 SSD 明顯下降", () => {
        const golden = blank();
        const rendered = blank();
        hLine(golden, 8);
        textRow(golden, 12);
        hLine(rendered, 11);              // 下移 3
        textRow(rendered, 15);
        const a = rowInk(golden, W, H);
        const b = rowInk(rendered, W, H);
        const r = bestShift1D(a, b, 6);
        expect(Math.abs(r.shift)).toBe(3);
        expect(r.ssdAtBest).toBeLessThan(r.ssdAt0 * 0.1);
    });

    it("沒有位移 → shift 要是 0（不可以亂報位移）", () => {
        const golden = blank();
        hLine(golden, 8);
        const a = rowInk(golden, W, H);
        const r = bestShift1D(a, a, 6);
        expect(r.shift).toBe(0);
        expect(r.ssdAtBest).toBe(0);
    });

    it("shiftBuffer 真的把內容搬過去", () => {
        const b = blank();
        ink(b, 5, 5);
        const moved = shiftBuffer(b, W, H, 2, 3);
        const i = ((5 + 3) * W + (5 + 2)) * 4;
        expect(moved[i]).toBe(0);         // 搬到 (7, 8)
        const orig = (5 * W + 5) * 4;
        expect(moved[orig]).toBe(255);    // 原位置補白
    });
});

describe("列分類", () => {
    it("分得出水平線／文字／空白", () => {
        const g = blank();
        hLine(g, 4);
        textRow(g, 9);
        const kinds = classifyRows(g, W, H);
        expect(kinds[4]).toBe("rule");
        expect(kinds[9]).toBe("text");
        expect(kinds[0]).toBe("blank");
    });

    it("連續的密集列算圖片，不算一堆線", () => {
        const g = blank();
        for (let y = 10; y < 16; y++) hLine(g, y);
        const kinds = classifyRows(g, W, H);
        // 區塊中間一定是 image；邊緣那兩列上下不對稱，算 rule 是可接受的
        expect(kinds[13]).toBe("image");
    });
});

describe("誤差歸屬", () => {
    it("diff 全落在水平線上 → rule 佔多數", () => {
        const g = blank();
        hLine(g, 6);
        textRow(g, 15);
        const d = diffAt([[3, 6], [9, 6], [20, 6]]);
        const r = attributeByRegion(d, g, W, H);
        expect(r.total).toBe(3);
        expect(r.ratios.rule).toBe(1);
        expect(r.ratios.text).toBe(0);
    });

    it("diff 全落在文字列上 → text 佔多數", () => {
        const g = blank();
        hLine(g, 6);
        textRow(g, 15);
        const d = diffAt([[1, 15], [2, 15]]);
        const r = attributeByRegion(d, g, W, H);
        expect(r.ratios.text).toBe(1);
    });
});

describe("字寬累積的指認", () => {
    it("diff 集中在文字列的右半 → advanceDrift 接近 1", () => {
        const g = blank();
        textRow(g, 10);
        const d = diffAt([[30, 10], [33, 10], [36, 10], [38, 10]]);
        expect(advanceDrift(d, g, W, H)).toBeGreaterThan(0.9);
    });

    it("☠️ 均勻分布的 diff → advanceDrift 接近 0（不可以把雜訊誤判成字寬問題）", () => {
        const g = blank();
        textRow(g, 10);
        const d = diffAt([[2, 10], [36, 10], [8, 10], [30, 10]]);
        expect(advanceDrift(d, g, W, H)).toBeLessThan(0.2);
    });

    it("沒有 diff → 回 0，不可以除以零", () => {
        const g = blank();
        textRow(g, 10);
        expect(advanceDrift(diffAt([]), g, W, H)).toBe(0);
    });
});
