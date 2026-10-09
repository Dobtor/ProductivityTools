/**
 * Sprint 10 — Renderer smoke 對全 fixture
 *
 * 對 42 fixture 各跑：
 *   .docx → OoxmlParser → layoutDocument → CanvasRenderer + MockRenderContext
 *
 * 驗收：
 *   - 不 throw
 *   - 每頁 beginPage / endPage 對稱
 *   - fillText 數量 >= 1（fixture 至少有一個段落 box）
 *   - drawLine 出現於含表格的 fixture（02_std_table / 03_complex_table 等）
 *
 * 並輸出 Renderer 端統計 snapshot（每 fixture 的 ops counts）。
 */

import { describe, expect, it } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { resolve } from 'node:path';

import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';
import { layoutDocument } from '../../static/src/core/layout';
import { CanvasRenderer, MockRenderContext } from '../../static/src/core/render';

const FIXTURE_ROOT = resolve(__dirname, '../fixtures');

function listFixtures(): string[] {
  const out: string[] = [];
  for (const cat of readdirSync(FIXTURE_ROOT)) {
    const catDir = resolve(FIXTURE_ROOT, cat);
    if (!statSync(catDir).isDirectory()) continue;
    for (const f of readdirSync(catDir)) {
      if (f.endsWith('.docx')) out.push(`${cat}/${f}`);
    }
  }
  return out.sort();
}

function loadDocxAsBuffer(rel: string): ArrayBuffer {
  const buf = readFileSync(resolve(FIXTURE_ROOT, rel));
  return buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
}

const FIXTURES = listFixtures();

describe('Sprint 10 — Renderer smoke 對全 fixture', () => {
  it.each(FIXTURES)('%s 跑通 Layout → Renderer 不 throw', (rel) => {
    const parser = new OoxmlParser();
    const doc = parser.parse(loadDocxAsBuffer(rel));
    const layout = layoutDocument(doc.sections);
    expect(layout.pages.length).toBeGreaterThanOrEqual(1);

    const ctx = new MockRenderContext();
    expect(() => new CanvasRenderer(ctx).render(layout)).not.toThrow();

    const counts = ctx.counts();
    // beginPage / endPage 對稱
    expect(counts.beginPage).toBe(layout.pages.length);
    expect(counts.endPage).toBe(layout.pages.length);
    // 至少一個 fillText
    expect(counts.fillText).toBeGreaterThanOrEqual(1);
  });

  it('表格類 fixture 至少出現 drawLine（cell 邊框）', () => {
    const tableFixtures = FIXTURES.filter(
      (f) => f.startsWith('02_std_table') || f.startsWith('03_complex_table'),
    );
    expect(tableFixtures.length).toBeGreaterThan(0);
    for (const rel of tableFixtures) {
      const parser = new OoxmlParser();
      const doc = parser.parse(loadDocxAsBuffer(rel));
      const layout = layoutDocument(doc.sections);
      const ctx = new MockRenderContext();
      new CanvasRenderer(ctx).render(layout);
      // 不強求每張表格 fixture 都有邊框（部分 fixture 用 nil borders），
      // 但作為一個整類，至少其中 50% 應 > 0 drawLine
    }
    // 統計類斷言
    let withBorders = 0;
    for (const rel of tableFixtures) {
      const parser = new OoxmlParser();
      const doc = parser.parse(loadDocxAsBuffer(rel));
      const layout = layoutDocument(doc.sections);
      const ctx = new MockRenderContext();
      new CanvasRenderer(ctx).render(layout);
      if (ctx.filter('drawLine').length > 0) withBorders++;
    }
    expect(withBorders / tableFixtures.length).toBeGreaterThan(0.5);
  });

  it('輸出每類 fixture 的 Renderer ops 平均（非 assertion，僅 console）', () => {
    const byCategory = new Map<string, { count: number; fillText: number; drawLine: number; fillRect: number }>();
    for (const rel of FIXTURES) {
      const cat = rel.split('/')[0];
      const parser = new OoxmlParser();
      const doc = parser.parse(loadDocxAsBuffer(rel));
      const layout = layoutDocument(doc.sections);
      const ctx = new MockRenderContext();
      new CanvasRenderer(ctx).render(layout);
      const counts = ctx.counts();
      const acc = byCategory.get(cat) ?? { count: 0, fillText: 0, drawLine: 0, fillRect: 0 };
      acc.count++;
      acc.fillText += counts.fillText;
      acc.drawLine += counts.drawLine;
      acc.fillRect += counts.fillRect;
      byCategory.set(cat, acc);
    }
    const lines: string[] = ['Sprint 10 Renderer ops avg by category:'];
    for (const [cat, acc] of byCategory) {
      lines.push(
        `  ${cat}: avgFillText=${(acc.fillText / acc.count).toFixed(1)}, ` +
        `avgDrawLine=${(acc.drawLine / acc.count).toFixed(1)}, ` +
        `avgFillRect=${(acc.fillRect / acc.count).toFixed(1)}`,
      );
    }
    console.log(lines.join('\n'));
    expect(byCategory.size).toBeGreaterThan(0);
  });
});
