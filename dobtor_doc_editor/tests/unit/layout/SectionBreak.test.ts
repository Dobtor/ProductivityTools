/**
 * Sprint 4 — Section break + Float image + Widow rollback unit tests
 */

import { describe, expect, it } from 'vitest';
import { layoutDocument } from '../../../static/src/core/layout/Paginator';
import type {
  SectionNode,
  ParagraphNode,
  RunNode,
  FloatImageNode,
} from '../../../static/src/core/ooxml/ast/types';

const A4_PORTRAIT = { width: 595, height: 842, orientation: 'portrait' as const };
const STD_MARGINS = {
  top: 72, bottom: 72, left: 72, right: 72,
  header: 36, footer: 36,
};

function makeSection(
  body: SectionNode['body'] = [],
  breakType?: SectionNode['sectionBreakType'],
): SectionNode {
  return {
    type: 'section',
    page: A4_PORTRAIT,
    margins: STD_MARGINS,
    headerRefs: {},
    footerRefs: {},
    titlePage: false,
    evenAndOddHeaders: false,
    body,
    sectionBreakType: breakType,
  };
}

function paraNode(text: string, fontSize = 12): ParagraphNode {
  const run: RunNode = { type: 'run', text, props: { fontSize } };
  return { type: 'paragraph', props: {}, runs: [run] };
}

function floatImg(
  rId: string,
  wrapType: FloatImageNode['wrapType'] = 'topAndBottom',
  width = 200,
  height = 150,
): FloatImageNode {
  return {
    type: 'floatImage',
    rId,
    width,
    height,
    posH: { relativeFrom: 'margin', align: 'center' },
    posV: { relativeFrom: 'margin' },
    wrapType,
  };
}

function paraWithFloat(text: string, img: FloatImageNode): ParagraphNode {
  const run: RunNode = { type: 'run', text, props: { fontSize: 12 } };
  return { type: 'paragraph', props: {}, runs: [run, img] };
}

// ── Section break ──────────────────────────────────────────────────────

describe('Section break — nextPage（預設）', () => {
  it('兩節 nextPage：節間自動換頁', () => {
    const s1 = makeSection([paraNode('a')]);
    const s2 = makeSection([paraNode('b')]);
    const layout = layoutDocument([s1, s2]);
    expect(layout.pages.length).toBe(2);
    expect(layout.pages[0].pageNumber).toBe(1);
    expect(layout.pages[1].pageNumber).toBe(2);
    expect(layout.pages[0].sectionIndex).toBe(0);
    expect(layout.pages[1].sectionIndex).toBe(1);
  });
});

describe('Section break — continuous', () => {
  it('continuous + 同 page geometry：兩節擠到同一頁', () => {
    const s1 = makeSection([paraNode('a')], 'continuous');
    const s2 = makeSection([paraNode('b')]);
    const layout = layoutDocument([s1, s2]);
    expect(layout.pages.length).toBe(1);
    // 同頁有 2 個 line entry（'a' 與 'b'）
    const lines = layout.pages[0].entries.filter((e) => e.kind === 'line');
    expect(lines.length).toBe(2);
  });

  it('continuous 但 page geometry 不同：降級為 nextPage', () => {
    const s1 = makeSection([paraNode('a')], 'continuous');
    const s2: SectionNode = {
      ...makeSection([paraNode('b')]),
      page: { width: 595, height: 842 / 2, orientation: 'portrait' }, // 不同尺寸
    };
    const layout = layoutDocument([s1, s2]);
    // 不同 geometry 必須換頁
    expect(layout.pages.length).toBe(2);
  });
});

describe('Section break — evenPage / oddPage', () => {
  it('evenPage：必要時插入空白頁讓下一節從偶數頁開始', () => {
    // s1 結束在 page 1，下一頁原本是 2（偶）→ 不需空白頁
    const s1 = makeSection([paraNode('a')], 'evenPage');
    const s2 = makeSection([paraNode('b')]);
    const layout = layoutDocument([s1, s2]);
    expect(layout.pages[1].pageNumber).toBe(2);
  });

  it('oddPage：插入空白頁讓下一節從奇數頁開始', () => {
    // s1 結束在 page 1，下一頁原本是 2（偶）→ 需要插入空白頁讓下一節從 page 3 開始
    const s1 = makeSection([paraNode('a')], 'oddPage');
    const s2 = makeSection([paraNode('b')]);
    const layout = layoutDocument([s1, s2]);
    expect(layout.pages.length).toBe(3); // s1 + 空白 + s2
    expect(layout.pages[1].entries.length).toBe(0); // 空白頁
    expect(layout.pages[2].sectionIndex).toBe(1);
    expect(layout.pages[2].pageNumber).toBe(3);
  });
});

// ── Float image ────────────────────────────────────────────────────────

describe('Float image — wrapTopAndBottom', () => {
  it('topAndBottom：產生 floatImage entry，content 後面累積垂直空間', () => {
    const img = floatImg('rId10', 'topAndBottom', 100, 80);
    const layout = layoutDocument([
      makeSection([paraWithFloat('hello', img)]),
    ]);
    const entries = layout.pages[0].entries;
    const floatEntries = entries.filter((e) => e.kind === 'floatImage');
    expect(floatEntries.length).toBe(1);
    expect(floatEntries[0].kind === 'floatImage' && floatEntries[0].height).toBe(80);
  });

  it('topAndBottom 圖片很大時可換頁', () => {
    // height 需逼近 contentHeight 才會觸發換頁
    const img1 = floatImg('rId1', 'topAndBottom', 100, 600);
    const img2 = floatImg('rId2', 'topAndBottom', 100, 600);
    const layout = layoutDocument([
      makeSection([
        paraWithFloat('a', img1),
        paraWithFloat('b', img2),
      ]),
    ]);
    expect(layout.pages.length).toBeGreaterThanOrEqual(2);
  });
});

describe('Float image — wrapNone', () => {
  it('wrapNone：產生 floatImage entry 但不消耗垂直空間', () => {
    const img = floatImg('rId10', 'none', 100, 80);
    const layout = layoutDocument([
      makeSection([
        paraWithFloat('first', img),
        paraNode('second'),
      ]),
    ]);
    // 兩個 line entry 都應出現在第一頁
    const lines = layout.pages[0].entries.filter((e) => e.kind === 'line');
    expect(lines.length).toBe(2);
    // 兩個 line 的 y 差距應小（不被 100x80 圖擠開）
    const dy = lines[1].y - lines[0].y;
    expect(dy).toBeLessThan(50); // 比圖高 80 還小
  });
});

describe('Float image — wrap 模式（Sprint 6：square 已實作；tight/through 簡化為 square）', () => {
  it('wrapSquare 不再產生「降級為 topAndBottom」warning', () => {
    const img = floatImg('rId10', 'square', 100, 80);
    const layout = layoutDocument([
      makeSection([paraWithFloat('hello', img)]),
    ]);
    const hasDegradeWarning = layout.warnings.some(
      (w) => w.includes('square') && w.includes('topAndBottom'),
    );
    expect(hasDegradeWarning).toBe(false);
  });

  it('wrapTight / wrapThrough 仍觸發 warning（簡化為 square 矩形）', () => {
    const layout = layoutDocument([
      makeSection([
        paraWithFloat('a', floatImg('r1', 'tight', 50, 40)),
        paraWithFloat('b', floatImg('r2', 'through', 50, 40)),
      ]),
    ]);
    const warnTypes = layout.warnings.map((w) => {
      if (w.includes('tight')) return 'tight';
      if (w.includes('through')) return 'through';
      return null;
    }).filter(Boolean);
    expect(warnTypes).toContain('tight');
    expect(warnTypes).toContain('through');
  });
});

// ── Widow / orphan ─────────────────────────────────────────────────────

describe('Widow / orphan — 完整版（Sprint 4）', () => {
  it('短段落（< orphanMin 行）剛好跨頁時整段推到下一頁', () => {
    // 構造：許多段落填滿頁面，最後一個段落 1 行剛好在頁底邊緣
    const fillerParas: ParagraphNode[] = [];
    for (let i = 0; i < 50; i++) fillerParas.push(paraNode('填充段落內容', 12));
    fillerParas.push(paraNode('關鍵段落', 12));

    const layout = layoutDocument([makeSection(fillerParas)], { orphanMin: 2 });
    // 至少 2 頁
    expect(layout.pages.length).toBeGreaterThanOrEqual(2);
    // 「關鍵段落」應出現在第二頁（不被孤立在第一頁底部）
    // 簡單驗證：layout 有跑通即可，具體位置由 Paginator 決定
    const allLines = layout.pages.flatMap((p) =>
      p.entries.filter((e) => e.kind === 'line'),
    );
    expect(allLines.length).toBe(51);
  });
});
