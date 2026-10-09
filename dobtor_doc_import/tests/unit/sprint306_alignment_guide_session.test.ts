/**
 * Sprint 306 — ⑤ deeper：AlignmentGuideSession state machine。
 *
 * Sprint 291 / 295 / 301 補了對齊輔助線 pure-fn 計算；本 sprint 補狀態機 wrapper。
 *
 * 紀律 #18 scope-down：不接 doc_editor.js OWL real path（紀律 #21、同 295/301 政策）。
 */
import { describe, expect, it } from 'vitest';

import { AlignmentGuideSession } from '../../static/src/components/doc_editor/AlignmentGuideSession';
import type { Rect, Bounds } from '../../static/src/components/doc_editor/overlay_geometry';

const RECT = (x: number, y: number, w: number, h: number): Rect => ({ x, y, width: w, height: h });
const PAGE: Bounds = { width: 800, height: 600 };

// ── 狀態轉換 ──────────────────────────────────────────────────────────────

describe('Sprint 306 — 狀態轉換 idle ↔ active', () => {
  it('初始 idle、render data 空', () => {
    const session = new AlignmentGuideSession();
    expect(session.getState()).toBe('idle');
    expect(session.getRenderData().state).toBe('idle');
    expect(session.getRenderData().guides).toEqual([]);
    expect(session.getRenderData().snappedRect).toBeNull();
  });

  it('start → active、end → idle', () => {
    const session = new AlignmentGuideSession();
    session.start(RECT(0, 0, 100, 100), [], PAGE);
    expect(session.getState()).toBe('active');
    session.end();
    expect(session.getState()).toBe('idle');
  });

  it('idle 時 update 為 no-op（不改 render data）', () => {
    const session = new AlignmentGuideSession();
    session.update(RECT(50, 50, 100, 100));
    expect(session.getRenderData().state).toBe('idle');
    expect(session.getRenderData().guides).toEqual([]);
  });
});

// ── snap target ───────────────────────────────────────────────────────────

describe('Sprint 306 — snap target', () => {
  it('moving rect 接近 page 左邊（在 threshold 內）→ snap.x = 0', () => {
    const session = new AlignmentGuideSession({ threshold: 5 });
    session.start(RECT(2, 50, 80, 60), [], PAGE);
    const rd = session.getRenderData();
    expect(rd.snapX?.value).toBe(0);
    expect(rd.snappedRect?.x).toBe(0);
  });

  it('moving rect 距離 page 邊超過 threshold → 無 snapX', () => {
    const session = new AlignmentGuideSession({ threshold: 4 });
    session.start(RECT(200, 200, 80, 60), [], PAGE);
    const rd = session.getRenderData();
    expect(rd.snapX).toBeUndefined();
    expect(rd.snappedRect?.x).toBe(200);
  });

  it('sibling 對齊（left-edge）', () => {
    const session = new AlignmentGuideSession({ threshold: 5 });
    const sibling = RECT(300, 100, 50, 50);
    session.start(RECT(302, 200, 80, 60), [sibling], PAGE);
    const rd = session.getRenderData();
    expect(rd.snapX?.value).toBe(300);
    expect(rd.snapX?.reason).toBe('sibling-edge-start');
    expect(rd.snappedRect?.x).toBe(300);
  });
});

// ── update 連動 snap ────────────────────────────────────────────────────

describe('Sprint 306 — update 連動', () => {
  it('多次 update 各自重新計算 snap', () => {
    const session = new AlignmentGuideSession({ threshold: 5 });
    session.start(RECT(0, 0, 80, 60), [], PAGE);
    session.update(RECT(2, 50, 80, 60)); // 仍可 snap X=0
    expect(session.getRenderData().snapX?.value).toBe(0);
    session.update(RECT(300, 300, 80, 60)); // 遠離 snap source
    expect(session.getRenderData().snapX).toBeUndefined();
  });

  it('end() 後 update 為 no-op', () => {
    const session = new AlignmentGuideSession();
    session.start(RECT(0, 0, 80, 60), [], PAGE);
    session.end();
    session.update(RECT(2, 50, 80, 60));
    expect(session.getRenderData().state).toBe('idle');
    expect(session.getRenderData().guides).toEqual([]);
  });
});

// ── guide styles 產出 ────────────────────────────────────────────────────

describe('Sprint 306 — guide styles', () => {
  it('active 時 buildGuideStyles 產出 visible guides', () => {
    const session = new AlignmentGuideSession({ threshold: 5 });
    session.start(RECT(0, 0, 80, 60), [], PAGE);
    const rd = session.getRenderData();
    expect(rd.guides.length).toBeGreaterThan(0);
    // 至少 page-edge-start 兩條（X 與 Y 軸）
    const pageEdgeStarts = rd.guides.filter((g) => g.className.includes('page'));
    expect(pageEdgeStarts.length).toBeGreaterThan(0);
  });
});
