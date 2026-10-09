/**
 * Sprint 16 — 全 fixture 頁數 baseline lock
 *
 * 目的：把每個 fixture 的「我們 layout 算出的 pages.length」鎖到 vitest snapshot，
 * 並列出 golden PNG 數做對照。後續 sprint 改 Paginator 時，本 snapshot 變動即
 * 強制 review（避免無意間退步）。
 *
 * 設計：
 *   - 不 assert pages.length === goldenCount（目前還對不上）
 *   - 改用 snapshot 鎖整個 mapping，使「改善」與「退步」都會被 vitest -u 流程察覺
 *
 * 為何不直接 assert 等於 golden：
 *   docx → Word 渲染的 page count 受很多 Word-internal 規則影響（cantSplit、
 *   trHeight w:hRule、自動 image row break 等），不是「實作對 = 一定等於」。
 *   把 baseline 凍結反而是更實用的回歸護欄；diff 對齊由 visual_regression
 *   逐步收斂。
 */

import { describe, expect, it } from 'vitest';
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { resolve } from 'node:path';

import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';
import { layoutDocument } from '../../static/src/core/layout';

const FIXTURE_ROOT = resolve(__dirname, '../fixtures');

/**
 * Sprint 179：Phase 5 大三項 fixture 目錄（OMML / SmartArt / Charts parser 驗證用）。
 * 非 VR baseline 的「42 fixture」成員 —— page count baseline 不納入。
 */
// Sprint 202：11_perf_synthetic_large 為大檔 perf 量測用、page count baseline 不納入。
const PHASE5_FIXTURE_DIRS = new Set(['07_chart', '08_smartart', '09_omml', '11_perf_synthetic_large']);

function listFixtures(): string[] {
  const out: string[] = [];
  for (const cat of readdirSync(FIXTURE_ROOT)) {
    const catDir = resolve(FIXTURE_ROOT, cat);
    if (cat.startsWith('.') || PHASE5_FIXTURE_DIRS.has(cat) || !statSync(catDir).isDirectory()) {
      continue;
    }
    for (const f of readdirSync(catDir)) {
      if (f.endsWith('.docx')) out.push(`${cat}/${f}`);
    }
  }
  return out.sort();
}

function loadDocx(rel: string): ArrayBuffer {
  const buf = readFileSync(resolve(FIXTURE_ROOT, rel));
  return buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
}

function countGoldens(rel: string): number {
  const [cat, filename] = rel.split('/');
  const base = filename.replace(/\.docx$/, '');
  const goldenDir = resolve(FIXTURE_ROOT, cat, 'golden');
  if (!existsSync(goldenDir)) return 0;
  return readdirSync(goldenDir).filter(
    (f) =>
      f.endsWith('.png') &&
      !f.includes('_diff') &&
      !f.endsWith('_v14_diff.png') &&
      f.startsWith(`${base}-`),
  ).length;
}

describe('Sprint 16 — fixture page count baseline', () => {
  it('鎖定每 fixture 的 pages.length（與 golden 對照）', () => {
    const fixtures = listFixtures();
    const baseline: Record<string, { ours: number; golden: number; delta: number }> = {};

    for (const rel of fixtures) {
      const doc = new OoxmlParser().parse(loadDocx(rel));
      const layout = layoutDocument(doc.sections);
      const ours = layout.pages.length;
      const golden = countGoldens(rel);
      baseline[rel] = { ours, golden, delta: ours - golden };
    }

    expect(baseline).toMatchSnapshot();
  });

  it('總計指標：鎖 mismatch 數量', () => {
    const fixtures = listFixtures();
    let mismatched = 0;
    let totalDelta = 0;
    for (const rel of fixtures) {
      const doc = new OoxmlParser().parse(loadDocx(rel));
      const layout = layoutDocument(doc.sections);
      const golden = countGoldens(rel);
      const delta = layout.pages.length - golden;
      if (delta !== 0) mismatched++;
      totalDelta += delta;
    }

    expect({ mismatched, totalDelta, total: fixtures.length }).toMatchSnapshot();
  });
});
