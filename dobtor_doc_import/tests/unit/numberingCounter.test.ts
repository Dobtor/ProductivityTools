/**
 * numberingCounter.test.ts — Phase 4.3 Sprint 137（counter state machine）
 *
 * 涵蓋：
 *   - 單一 numId、單一 ilvl：start / +1 / 連續編號
 *   - 多 ilvl：深層 reset 規則（淺層遇深層、深層遇淺層）
 *   - 多 numId：彼此 counter 獨立
 *   - lvlRestart = 0：永不 reset 深層（跨章節連續）
 *   - 缺失 abstractNumbering：placeholder fallback、不 crash
 *   - 缺失 ilvl level：placeholder fallback
 *   - 直接從深 ilvl 起算：淺層用 start 當顯示值（不污染 state）
 *   - reset() / resetNum() / snapshot()
 *   - 紀律 #21：counters / numFmts 只取 0..ilvl 長度
 */

import { describe, expect, it } from 'vitest';
import { NumberingCounterState } from '../../static/src/core/ooxml/numbering/numberingCounter';
import { expandLvlText } from '../../static/src/core/ooxml/numbering/numberingFormatter';
import type { AbstractNumbering, NumberingLevel } from '../../static/src/core/ooxml/ast/types';

function level(ilvl: number, opts: Partial<NumberingLevel> = {}): NumberingLevel {
  return {
    ilvl,
    numFmt: 'decimal',
    text: `%${ilvl + 1}.`,
    start: 1,
    ...opts,
  };
}

function abstractNum(...levels: NumberingLevel[]): AbstractNumbering {
  return { abstractNumId: 0, levels };
}

// ── 單一 numId / 單一 ilvl ──────────────────────────────────────────────────

describe('NumberingCounterState — 單一 numId / 單一 ilvl', () => {
  it('首次出現 ilvl=0：用 start', () => {
    const s = new NumberingCounterState();
    const an = abstractNum(level(0, { start: 1 }));
    const r = s.advance(1, 0, an);
    expect(r.counters).toEqual([1]);
    expect(r.numFmts).toEqual(['decimal']);
  });

  it('連續呼叫同 ilvl：counter +1', () => {
    const s = new NumberingCounterState();
    const an = abstractNum(level(0, { start: 1 }));
    expect(s.advance(1, 0, an).counters).toEqual([1]);
    expect(s.advance(1, 0, an).counters).toEqual([2]);
    expect(s.advance(1, 0, an).counters).toEqual([3]);
  });

  it('start = 5：首次回 5，後續 +1', () => {
    const s = new NumberingCounterState();
    const an = abstractNum(level(0, { start: 5 }));
    expect(s.advance(1, 0, an).counters).toEqual([5]);
    expect(s.advance(1, 0, an).counters).toEqual([6]);
  });

  it('回傳 level 物件供 caller 取 lvlText/indent', () => {
    const s = new NumberingCounterState();
    const an = abstractNum(level(0, { text: '第%1章', numFmt: 'chineseCounting' }));
    const r = s.advance(1, 0, an);
    expect(r.level.text).toBe('第%1章');
    expect(r.level.numFmt).toBe('chineseCounting');
    expect(r.numFmts).toEqual(['chineseCounting']);
  });
});

// ── 多 ilvl 深層 reset 規則 ─────────────────────────────────────────────────

describe('NumberingCounterState — 多 ilvl 深層 reset', () => {
  it('ilvl 0 → 1 → 1 → 2：深層獨立計數', () => {
    const s = new NumberingCounterState();
    const an = abstractNum(level(0), level(1), level(2));
    expect(s.advance(1, 0, an).counters).toEqual([1]);
    expect(s.advance(1, 1, an).counters).toEqual([1, 1]);
    expect(s.advance(1, 1, an).counters).toEqual([1, 2]);
    expect(s.advance(1, 2, an).counters).toEqual([1, 2, 1]);
  });

  it('深層 → 淺層：淺層 +1、深層 reset', () => {
    const s = new NumberingCounterState();
    const an = abstractNum(level(0), level(1));
    s.advance(1, 0, an); // [1]
    s.advance(1, 1, an); // [1,1]
    s.advance(1, 1, an); // [1,2]
    // 回到 ilvl=0：淺層 +1、深層 reset
    const r = s.advance(1, 0, an);
    expect(r.counters).toEqual([2]);
    // 再進深層：應從 start 起算
    const r2 = s.advance(1, 1, an);
    expect(r2.counters).toEqual([2, 1]);
  });

  it('ilvl 0 → 2（跳過 1）：1 用 start 當顯示值、不污染 state', () => {
    const s = new NumberingCounterState();
    const an = abstractNum(level(0, { start: 1 }), level(1, { start: 5 }), level(2, { start: 1 }));
    s.advance(1, 0, an); // [1]
    const r = s.advance(1, 2, an);
    // counters[1] 從未真正 advance、顯示用 start=5
    expect(r.counters).toEqual([1, 5, 1]);
    // 確認 state：再 advance ilvl=1 應該回 5（不是 6）
    const r2 = s.advance(1, 1, an);
    expect(r2.counters).toEqual([1, 5]);
    // 再 advance ilvl=1 才 +1
    const r3 = s.advance(1, 1, an);
    expect(r3.counters).toEqual([1, 6]);
  });
});

// ── 多 numId 互相獨立 ──────────────────────────────────────────────────────

describe('NumberingCounterState — 多 numId 互相獨立', () => {
  it('numId=1 和 numId=2 彼此獨立計數', () => {
    const s = new NumberingCounterState();
    const an = abstractNum(level(0));
    expect(s.advance(1, 0, an).counters).toEqual([1]);
    expect(s.advance(2, 0, an).counters).toEqual([1]); // numId=2 從 start 起算
    expect(s.advance(1, 0, an).counters).toEqual([2]); // numId=1 繼續
    expect(s.advance(2, 0, an).counters).toEqual([2]); // numId=2 繼續
  });
});

// ── lvlRestart=0：永不 reset 深層 ──────────────────────────────────────────

describe('NumberingCounterState — lvlRestart=0 跨章節連續', () => {
  it('深層 level 標 lvlRestart=0：淺層 advance 不 reset 深層', () => {
    const s = new NumberingCounterState();
    const an = abstractNum(level(0), level(1, { lvlRestart: 0 }));
    s.advance(1, 0, an); // [1]
    s.advance(1, 1, an); // [1,1]
    s.advance(1, 1, an); // [1,2]
    // 回到 ilvl=0、再進深層應接 3（不是 1）
    s.advance(1, 0, an); // [2]
    const r = s.advance(1, 1, an);
    expect(r.counters).toEqual([2, 3]);
  });

  it('深層無 lvlRestart：預設 reset', () => {
    const s = new NumberingCounterState();
    const an = abstractNum(level(0), level(1));
    s.advance(1, 0, an);
    s.advance(1, 1, an);
    s.advance(1, 1, an);
    s.advance(1, 0, an);
    const r = s.advance(1, 1, an);
    expect(r.counters).toEqual([2, 1]); // 深層 reset 後從 start 起算
  });
});

// ── 缺失 / 防禦 ────────────────────────────────────────────────────────────

describe('NumberingCounterState — 防禦缺失', () => {
  it('缺 abstractNumbering：placeholder level（decimal/start=1）', () => {
    const s = new NumberingCounterState();
    const r = s.advance(99, 0, undefined);
    expect(r.counters).toEqual([1]);
    expect(r.numFmts).toEqual(['decimal']);
    expect(r.level.numFmt).toBe('decimal');
    expect(r.level.text).toBe('%1.');
  });

  it('缺對應 ilvl level：placeholder fallback', () => {
    const s = new NumberingCounterState();
    const an = abstractNum(level(0)); // 只有 ilvl=0
    const r = s.advance(1, 3, an); // 要 ilvl=3
    expect(r.counters[3]).toBe(1);
    expect(r.numFmts[3]).toBe('decimal');
    expect(r.level.ilvl).toBe(3);
  });

  it('連續呼叫相同缺 ilvl：仍正常 +1', () => {
    const s = new NumberingCounterState();
    const an = abstractNum(level(0));
    expect(s.advance(1, 2, an).counters[2]).toBe(1);
    expect(s.advance(1, 2, an).counters[2]).toBe(2);
  });
});

// ── reset / resetNum / snapshot ────────────────────────────────────────────

describe('NumberingCounterState — lifecycle', () => {
  it('reset() 清空全部 numId state', () => {
    const s = new NumberingCounterState();
    const an = abstractNum(level(0));
    s.advance(1, 0, an);
    s.advance(2, 0, an);
    s.reset();
    expect(s.snapshot().size).toBe(0);
    // reset 後重新從 start
    expect(s.advance(1, 0, an).counters).toEqual([1]);
  });

  it('resetNum(N) 只清 N 的 state、其他保留', () => {
    const s = new NumberingCounterState();
    const an = abstractNum(level(0));
    s.advance(1, 0, an); // [1]
    s.advance(2, 0, an); // [1]
    s.advance(1, 0, an); // [2]
    s.resetNum(1);
    expect(s.advance(1, 0, an).counters).toEqual([1]); // 重啟
    expect(s.advance(2, 0, an).counters).toEqual([2]); // 未受影響
  });

  it('snapshot() 是 deep copy、修改不影響 state', () => {
    const s = new NumberingCounterState();
    const an = abstractNum(level(0));
    s.advance(1, 0, an);
    const snap = s.snapshot();
    const arr = snap.get(1)!;
    arr[0] = 999;
    // 內部 state 不受影響
    expect(s.advance(1, 0, an).counters).toEqual([2]);
  });
});

// ── 紀律 #21 邊界 ──────────────────────────────────────────────────────────

describe('NumberingCounterState — 紀律 #21 counters 長度收斂', () => {
  it('ilvl=0 時 counters 長度 = 1', () => {
    const s = new NumberingCounterState();
    const an = abstractNum(level(0), level(1), level(2), level(3));
    const r = s.advance(1, 0, an);
    expect(r.counters.length).toBe(1);
    expect(r.numFmts.length).toBe(1);
  });

  it('ilvl=2 時 counters 長度 = 3（不含深層 undefined）', () => {
    const s = new NumberingCounterState();
    const an = abstractNum(level(0), level(1), level(2), level(3), level(4));
    const r = s.advance(1, 2, an);
    expect(r.counters.length).toBe(3);
    expect(r.numFmts.length).toBe(3);
  });
});

// ── 整合：expandLvlText 串接驗證 ──────────────────────────────────────────

describe('NumberingCounterState — 與 expandLvlText 串接（整合預演）', () => {
  // 本 sprint 未 wire-up 到 mapper、但驗證 counter 輸出能直接餵給 expandLvlText
  it('counter 輸出搭配 expandLvlText：「1.2.」風格多層', () => {
const s = new NumberingCounterState();
    const an = abstractNum(level(0), level(1));
    s.advance(1, 0, an); // [1]
    const r = s.advance(1, 1, an); // [1,1]
    expect(expandLvlText('%1.%2.', r.counters, r.numFmts)).toBe('1.1.');
    const r2 = s.advance(1, 1, an); // [1,2]
    expect(expandLvlText('%1.%2.', r2.counters, r2.numFmts)).toBe('1.2.');
  });

  it('中文章節「第%1章」', () => {
const s = new NumberingCounterState();
    const an = abstractNum(level(0, { numFmt: 'chineseCounting', text: '第%1章' }));
    s.advance(1, 0, an); // [1]
    const r = s.advance(1, 0, an); // [2]
    expect(expandLvlText('第%1章', r.counters, r.numFmts)).toBe('第二章');
  });
});
