/**
 * Sprint 359 — SmartArtSvgRenderer：SmartArtNode 資料模型 → SVG 垂直方塊清單。
 *
 * 真實資料 fidelity audit（2026-05-29）後補：SmartArt 不再只剩線性文字。
 * 紀律 #18：統一垂直方塊清單（誠實表達節點集合、不假裝 1:1 還原版面）。
 */
import { describe, expect, it } from 'vitest';

import { renderSmartArtSvg } from '../../static/src/core/ooxml/diagram/SmartArtSvgRenderer';
import type { SmartArtNode } from '../../static/src/core/ooxml/ast/types';

const mk = (texts: string[], layoutType?: string): SmartArtNode => ({
  rId: 'rId1',
  texts,
  ...(layoutType ? { layoutType } : {}),
});

describe('Sprint 359 — renderSmartArtSvg', () => {
  it('多節點 → SVG 含每個節點文字', () => {
    const svg = renderSmartArtSvg(mk(['規劃', '設計', '施工']));
    expect(svg).not.toBeNull();
    expect(svg!.startsWith('<svg')).toBe(true);
    expect(svg!).toContain('規劃');
    expect(svg!).toContain('設計');
    expect(svg!).toContain('施工');
  });

  it('每節點一個 box <rect>（+ 背景）', () => {
    const svg = renderSmartArtSvg(mk(['A', 'B', 'C']))!;
    const rects = svg.match(/<rect /g) ?? [];
    // 背景 1 + 3 box = 4
    expect(rects.length).toBe(4);
  });

  it('n-1 個連接箭頭（path）', () => {
    const svg = renderSmartArtSvg(mk(['A', 'B', 'C']))!;
    const arrows = svg.match(/<path /g) ?? [];
    expect(arrows.length).toBe(2); // 3 節點 → 2 箭頭
  });

  it('單節點 → 無箭頭', () => {
    const svg = renderSmartArtSvg(mk(['只有一個']))!;
    expect((svg.match(/<path /g) ?? []).length).toBe(0);
  });

  it('空 texts → null', () => {
    expect(renderSmartArtSvg(mk([]))).toBeNull();
  });

  it('全空白 texts → null', () => {
    expect(renderSmartArtSvg(mk(['', '  ', '\t']))).toBeNull();
  });

  it('XML 特殊字元轉義', () => {
    const svg = renderSmartArtSvg(mk(['<危險> & "引號"']))!;
    expect(svg).toContain('&lt;危險&gt;');
    expect(svg).toContain('&amp;');
    expect(svg).not.toContain('<危險>');
  });

  it('過長文字截斷（含 …）', () => {
    const svg = renderSmartArtSvg(mk(['一二三四五六七八九十一二三四五六七八九十廿一廿二廿三']))!;
    expect(svg).toContain('…');
  });

  it('高度隨節點數成長', () => {
    const h1 = renderSmartArtSvg(mk(['A']))!.match(/height="(\d+)"/)![1];
    const h3 = renderSmartArtSvg(mk(['A', 'B', 'C']))!.match(/height="(\d+)"/)![1];
    expect(Number(h3)).toBeGreaterThan(Number(h1));
  });

  it('自訂寬度', () => {
    const svg = renderSmartArtSvg(mk(['A']), { width: 480 })!;
    expect(svg).toContain('width="480"');
  });
});
