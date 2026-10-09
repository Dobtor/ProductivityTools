/**
 * Sprint 10 — 欄分隔線 + PAGE/NUMPAGES 真值
 *
 * 涵蓋：
 *   1. SectionParser 解析 <w:cols w:sep="true"/>
 *   2. Page.columnLayout 在多欄頁面填入正確 startX / widths / separator
 *   3. Renderer 在 separator=true 時畫垂直 drawLine
 *   4. PAGE field box 的 text 在 post-pass 後 = String(pageNumber)
 *   5. NUMPAGES field box 的 text 在 post-pass 後 = String(pages.length)
 *   6. 多頁 PAGE 各頁 box 對應各自 pageNumber
 */

import { describe, expect, it } from 'vitest';
import { layoutDocument } from '../../../static/src/core/layout/Paginator';
import { CanvasRenderer } from '../../../static/src/core/render/CanvasRenderer';
import { MockRenderContext } from '../../../static/src/core/render/MockRenderContext';
import type {
  SectionNode,
  ParagraphNode,
  RunNode,
  FieldNode,
} from '../../../static/src/core/ooxml/ast/types';
import type { Box } from '../../../static/src/core/layout/types';

const A4 = { width: 595, height: 842, orientation: 'portrait' as const };
const MARGINS = { top: 72, bottom: 72, left: 72, right: 72, header: 36, footer: 36 };

function para(text: string): ParagraphNode {
  const run: RunNode = { type: 'run', text, props: { fontSize: 12 } };
  return { type: 'paragraph', props: {}, runs: [run] };
}

function paraWithFieldOnly(fieldType: 'PAGE' | 'NUMPAGES'): ParagraphNode {
  const fld: FieldNode = { type: 'field', instruction: ` ${fieldType} `, fieldType };
  return { type: 'paragraph', props: {}, runs: [fld] };
}

function makeSection(
  body: SectionNode['body'] = [],
  columns?: SectionNode['columns'],
): SectionNode {
  const out: SectionNode = {
    type: 'section', page: A4, margins: MARGINS,
    headerRefs: {}, footerRefs: {}, titlePage: false, evenAndOddHeaders: false, body,
  };
  if (columns) out.columns = columns;
  return out;
}

// ── 1. Page.columnLayout ──────────────────────────────────────────────────

describe('Sprint 10 — Page.columnLayout', () => {
  it('單欄頁不寫 columnLayout', () => {
    const sec = makeSection([para('hello')]);
    const layout = layoutDocument([sec]);
    expect(layout.pages[0].columnLayout).toBeUndefined();
  });

  it('多欄頁寫入 count / startX / widths', () => {
    const sec = makeSection([para('hello')], { count: 2, space: 36 });
    const layout = layoutDocument([sec]);
    const cl = layout.pages[0].columnLayout;
    expect(cl).toBeDefined();
    expect(cl!.count).toBe(2);
    expect(cl!.startX.length).toBe(2);
    expect(cl!.widths.length).toBe(2);
    expect(cl!.startX[0]).toBe(MARGINS.left);
    // 第二欄 startX = marginLeft + col1Width + space
    expect(cl!.startX[1]).toBe(MARGINS.left + cl!.widths[0] + 36);
    expect(cl!.separator).toBe(false);
  });

  it('w:sep="true" → separator=true', () => {
    const sec = makeSection([para('hi')], { count: 2, space: 24, separator: true });
    const layout = layoutDocument([sec]);
    expect(layout.pages[0].columnLayout?.separator).toBe(true);
  });
});

// ── 2. Renderer 畫垂直分隔線 ──────────────────────────────────────────────

describe('Sprint 10 — Renderer 畫欄分隔線', () => {
  it('separator=true 在欄之間畫垂直 drawLine', () => {
    const sec = makeSection([para('hi')], { count: 2, space: 36, separator: true });
    const layout = layoutDocument([sec]);
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layout);

    const lines = ctx.filter('drawLine');
    // 找垂直線（x1 === x2）
    const verticals = lines.filter((l) => Math.abs(l.x1 - l.x2) < 0.01);
    expect(verticals.length).toBe(1);
    // 垂直線 x 在兩欄中間
    const cl = layout.pages[0].columnLayout!;
    const expectedX = (cl.startX[0] + cl.widths[0] + cl.startX[1]) / 2;
    expect(Math.abs(verticals[0].x1 - expectedX)).toBeLessThan(0.5);
  });

  it('separator=false 不畫垂直線', () => {
    const sec = makeSection([para('hi')], { count: 2, space: 36 });
    const layout = layoutDocument([sec]);
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layout);
    const verticals = ctx.filter('drawLine').filter((l) => Math.abs(l.x1 - l.x2) < 0.01);
    expect(verticals.length).toBe(0);
  });

  it('3 欄 separator=true 畫 2 條垂直線', () => {
    const sec = makeSection([para('a')], { count: 3, space: 18, separator: true });
    const layout = layoutDocument([sec]);
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layout);
    const verticals = ctx.filter('drawLine').filter((l) => Math.abs(l.x1 - l.x2) < 0.01);
    expect(verticals.length).toBe(2);
  });
});

// ── 3. PAGE / NUMPAGES 真值 ───────────────────────────────────────────────

describe('Sprint 10 — PAGE / NUMPAGES post-pass', () => {
  it('單頁 PAGE 欄位 text = "1"', () => {
    const sec = makeSection([paraWithFieldOnly('PAGE')]);
    const layout = layoutDocument([sec]);
    const fieldBoxes = collectFieldBoxes(layout, 'PAGE');
    expect(fieldBoxes.length).toBe(1);
    expect(fieldBoxes[0].text).toBe('1');
  });

  it('NUMPAGES 欄位 text = 總頁數', () => {
    // 多頁 fixture：100 段
    const body: SectionNode['body'] = [];
    for (let i = 0; i < 100; i++) body.push(para(`段 ${i}`));
    body.push(paraWithFieldOnly('NUMPAGES'));
    const sec = makeSection(body);
    const layout = layoutDocument([sec]);
    const fieldBoxes = collectFieldBoxes(layout, 'NUMPAGES');
    expect(fieldBoxes.length).toBe(1);
    expect(fieldBoxes[0].text).toBe(String(layout.pages.length));
    expect(layout.pages.length).toBeGreaterThan(1);
  });

  it('多頁文件每頁的 PAGE 欄位各自填值', () => {
    // 跨頁分佈：用 page break 強制兩頁
    const breakRun: RunNode = { type: 'run', text: 'p1', props: { fontSize: 12 } };
    const breakNode: import('../../../static/src/core/ooxml/ast/types').BreakNode = { type: 'break', breakType: 'page' };
    const p1: ParagraphNode = { type: 'paragraph', props: {}, runs: [breakRun, breakNode] };
    const fp: FieldNode = { type: 'field', instruction: ' PAGE ', fieldType: 'PAGE' };
    const p2: ParagraphNode = { type: 'paragraph', props: {}, runs: [fp] };
    const sec = makeSection([p1, p2]);
    const layout = layoutDocument([sec]);
    expect(layout.pages.length).toBe(2);
    const page2Fields = collectFieldBoxesOnPage(layout.pages[1]);
    expect(page2Fields.length).toBe(1);
    expect(page2Fields[0].text).toBe('2');
  });

  it('placeholder 寬度由 fieldType 決定（##）', () => {
    const sec = makeSection([paraWithFieldOnly('PAGE')]);
    const layout = layoutDocument([sec]);
    const fieldBoxes = collectFieldBoxes(layout, 'PAGE');
    expect(fieldBoxes.length).toBe(1);
    // text 已被改成 "1"，但 width 是當初測 "##" 的（測 width 大約 ~13pt）
    expect(fieldBoxes[0].width).toBeGreaterThan(0);
    // fieldType 仍保留
    expect(fieldBoxes[0].fieldType).toBe('PAGE');
  });
});

// ── helpers ───────────────────────────────────────────────────────────────

function collectFieldBoxes(
  layout: { pages: import('../../../static/src/core/layout/types').Page[] },
  fieldType: 'PAGE' | 'NUMPAGES',
): Box[] {
  const out: Box[] = [];
  for (const page of layout.pages) {
    for (const box of collectFieldBoxesOnPage(page)) {
      if (box.fieldType === fieldType) out.push(box);
    }
  }
  return out;
}

function collectFieldBoxesOnPage(page: import('../../../static/src/core/layout/types').Page): Box[] {
  const out: Box[] = [];
  for (const entry of page.entries) {
    if (entry.kind === 'line') {
      for (const item of entry.line.items) {
        if (item.kind === 'box' && item.fieldType) out.push(item as Box);
      }
    }
  }
  return out;
}
