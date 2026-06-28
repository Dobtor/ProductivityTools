/**
 * Sprint 12 — Renderer ops trace fingerprint regression
 *
 * 對 42 fixture 各跑：
 *   .docx → OoxmlParser → layoutDocument → CanvasRenderer + MockRenderContext
 *   → fingerprintOps → snapshot
 *
 * 驗收：
 *   - vitest snapshot 不變（結構性 regression：ops counts、文字 char count、文字 hash）
 *   - 個別 fixture 的指紋穩定，跨 sprint 觀察哪份 fixture 輸出有變
 *
 * 為何不存 full ops trace：
 *   - 1134 fillText × 42 fixture = 50000+ ops，snapshot 難讀
 *   - fingerprint 已能抓出 99% 結構性 regression（counts + char hash）
 *   - 真要看具體變化，跑「只跑單 fixture 的 trace」即可
 *
 * 注意：documentMetadata.now 必須固定（否則 DATE/TIME field 每跑都變）。
 */

import { describe, expect, it } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { resolve } from 'node:path';

import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';
import { layoutDocument } from '../../static/src/core/layout';
import { CanvasRenderer, MockRenderContext, fingerprintOps } from '../../static/src/core/render';

const FIXTURE_ROOT = resolve(__dirname, '../fixtures');

/** 固定 metadata 確保 DATE/TIME 在 snapshot 內穩定 */
const FROZEN_METADATA = {
  now: new Date('2026-01-01T00:00:00Z'),
  author: 'TestAuthor',
  filename: 'TestFile',
};

/**
 * Sprint 179：Phase 5 大三項 fixture 目錄（OMML / SmartArt / Charts parser 驗證用）。
 * 非 VR baseline 的「42 fixture」成員 —— renderer ops fingerprint 不納入。
 */
// Sprint 202：11_perf_synthetic_large 為大檔 perf 量測用、render ops trace 不納入。
const PHASE5_FIXTURE_DIRS = new Set(['07_chart', '08_smartart', '09_omml', '11_perf_synthetic_large']);

function listFixtures(): string[] {
  const out: string[] = [];
  for (const cat of readdirSync(FIXTURE_ROOT)) {
    const catDir = resolve(FIXTURE_ROOT, cat);
    if (PHASE5_FIXTURE_DIRS.has(cat) || !statSync(catDir).isDirectory()) continue;
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

describe('Sprint 12 — Renderer ops fingerprint regression', () => {
  it('全 fixture fingerprint snapshot', () => {
    const summary: Record<string, { total: number; counts: Record<string, number>; textChars: number; textHash: string }> = {};
    for (const rel of FIXTURES) {
      const parser = new OoxmlParser();
      const doc = parser.parse(loadDocxAsBuffer(rel));
      const layout = layoutDocument(doc.sections, {
        headers: doc.headers,
        footers: doc.footers,
        documentMetadata: FROZEN_METADATA,
      });
      const ctx = new MockRenderContext();
      new CanvasRenderer(ctx).render(layout);
      const fp = fingerprintOps(ctx.ops);
      summary[rel] = {
        total: fp.total,
        counts: fp.byKind,
        textChars: fp.textCharCount,
        textHash: fp.textHash,
      };
    }
    expect(summary).toMatchSnapshot();
  });

  it('每類 fixture 的 fingerprint 在 reasonable 範圍', () => {
    // 確保 fingerprint 有合理數量級，預防「整個 Renderer 壞掉但 snapshot 漏抓」
    let totalOps = 0;
    let totalText = 0;
    for (const rel of FIXTURES) {
      const parser = new OoxmlParser();
      const doc = parser.parse(loadDocxAsBuffer(rel));
      const layout = layoutDocument(doc.sections, {
        headers: doc.headers,
        footers: doc.footers,
        documentMetadata: FROZEN_METADATA,
      });
      const ctx = new MockRenderContext();
      new CanvasRenderer(ctx).render(layout);
      const fp = fingerprintOps(ctx.ops);
      totalOps += fp.total;
      totalText += fp.textCharCount;
    }
    // 42 fixture × 平均應該有上萬 ops、數十萬 char
    expect(totalOps).toBeGreaterThan(10000);
    expect(totalText).toBeGreaterThan(50000);
  });
});
