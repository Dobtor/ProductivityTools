/**
 * Sprint 295 — alignment guide visual indicator (pure-fn rendering data)。
 *
 * Follow-up to Sprint 291 honest gap「alignment guide visual indicator 未做」。
 * Strategy C+ utility extraction：pure-fn module + 12 tests。
 *
 * 紀律 #18 scope-down：本 sprint 不接 doc_editor.js OWL Component（避免破 13
 *   Playwright E2E）；caller 自行 spread 樣式或映射 className。未來 polish
 *   sprint 才 wire 進 doc_editor.js（opt-in feature flag）。
 * 紀律 #21：純資料 transformation、無 side effect、不污染 VR pipeline。
 */
import { describe, expect, it } from 'vitest';

import {
  buildGuideStyles,
  applySnapToRect,
} from '../../static/src/components/doc_editor/alignment_guide_render';
import type { AlignGuide } from '../../static/src/components/doc_editor/overlay_geometry';

const PAGE = { width: 595, height: 842 };

describe('Sprint 295 — buildGuideStyles X axis guides', () => {
  it('X 軸 guide → 垂直線：left=value、top=0、width=lineThickness、height=pageH', () => {
    const guides: AlignGuide[] = [
      { axis: 'x', value: 100, reason: 'page-center' },
    ];
    const styles = buildGuideStyles(guides, PAGE);
    expect(styles).toHaveLength(1);
    expect(styles[0]).toEqual({
      axis: 'x',
      left: 100,
      top: 0,
      width: 1,
      height: 842,
      className: 'guide-page',
      siblingIndex: undefined,
    });
  });

  it('lineThickness=3 → 寬度為 3', () => {
    const guides: AlignGuide[] = [{ axis: 'x', value: 50, reason: 'page-edge-start' }];
    const styles = buildGuideStyles(guides, PAGE, { lineThickness: 3 });
    expect(styles[0].width).toBe(3);
  });
});

describe('Sprint 295 — buildGuideStyles Y axis guides', () => {
  it('Y 軸 guide → 水平線：left=0、top=value、width=pageW、height=lineThickness', () => {
    const guides: AlignGuide[] = [
      { axis: 'y', value: 200, reason: 'page-center' },
    ];
    const styles = buildGuideStyles(guides, PAGE);
    expect(styles[0]).toEqual({
      axis: 'y',
      left: 0,
      top: 200,
      width: 595,
      height: 1,
      className: 'guide-page',
      siblingIndex: undefined,
    });
  });
});

describe('Sprint 295 — buildGuideStyles className 區分', () => {
  it('page-* reason → className = "guide-page"', () => {
    const guides: AlignGuide[] = [
      { axis: 'x', value: 0, reason: 'page-edge-start' },
      { axis: 'y', value: 0, reason: 'page-edge-end' },
      { axis: 'x', value: 100, reason: 'page-center' },
    ];
    const styles = buildGuideStyles(guides, PAGE);
    expect(styles.every((s) => s.className === 'guide-page')).toBe(true);
  });

  it('sibling-* reason → className = "guide-sibling" + siblingIndex preserved', () => {
    const guides: AlignGuide[] = [
      { axis: 'x', value: 50, reason: 'sibling-edge-start', siblingIndex: 0 },
      { axis: 'y', value: 150, reason: 'sibling-center', siblingIndex: 2 },
    ];
    const styles = buildGuideStyles(guides, PAGE);
    expect(styles[0].className).toBe('guide-sibling');
    expect(styles[0].siblingIndex).toBe(0);
    expect(styles[1].className).toBe('guide-sibling');
    expect(styles[1].siblingIndex).toBe(2);
  });

  it('自訂 pageClassName + siblingClassName → 套用', () => {
    const guides: AlignGuide[] = [
      { axis: 'x', value: 0, reason: 'page-edge-start' },
      { axis: 'x', value: 50, reason: 'sibling-edge-start', siblingIndex: 0 },
    ];
    const styles = buildGuideStyles(guides, PAGE, {
      pageClassName: 'g-p',
      siblingClassName: 'g-s',
    });
    expect(styles[0].className).toBe('g-p');
    expect(styles[1].className).toBe('g-s');
  });
});

describe('Sprint 295 — buildGuideStyles 去重', () => {
  it('相同 axis + 相同 value 的多 reason → 合併為 1 條（取第一個）', () => {
    const guides: AlignGuide[] = [
      { axis: 'x', value: 100, reason: 'page-center' },
      { axis: 'x', value: 100, reason: 'sibling-edge-start', siblingIndex: 0 },
      { axis: 'x', value: 100, reason: 'sibling-center', siblingIndex: 1 },
    ];
    const styles = buildGuideStyles(guides, PAGE);
    expect(styles).toHaveLength(1);
    // 第一個是 page-center，className 為 guide-page
    expect(styles[0].className).toBe('guide-page');
  });

  it('同 value 但不同 axis → 不合併（X + Y 各自獨立）', () => {
    const guides: AlignGuide[] = [
      { axis: 'x', value: 100, reason: 'page-center' },
      { axis: 'y', value: 100, reason: 'page-center' },
    ];
    const styles = buildGuideStyles(guides, PAGE);
    expect(styles).toHaveLength(2);
  });

  it('空 guides 陣列 → 回空 styles', () => {
    const styles = buildGuideStyles([], PAGE);
    expect(styles).toEqual([]);
  });
});

describe('Sprint 295 — applySnapToRect', () => {
  it('snapX + snapY 都有 → rect 完全採用 snap 值', () => {
    const rect = { x: 100, y: 200 };
    const snapX: AlignGuide = { axis: 'x', value: 105, reason: 'page-center' };
    const snapY: AlignGuide = { axis: 'y', value: 195, reason: 'sibling-edge-start' };
    expect(applySnapToRect(rect, snapX, snapY)).toEqual({ x: 105, y: 195 });
  });

  it('只 snapX → y 保留原值', () => {
    const rect = { x: 100, y: 200 };
    const snapX: AlignGuide = { axis: 'x', value: 105, reason: 'page-center' };
    expect(applySnapToRect(rect, snapX, undefined)).toEqual({ x: 105, y: 200 });
  });

  it('snapX/snapY 都 undefined → rect 不變', () => {
    const rect = { x: 100, y: 200 };
    expect(applySnapToRect(rect, undefined, undefined)).toEqual({ x: 100, y: 200 });
  });
});
