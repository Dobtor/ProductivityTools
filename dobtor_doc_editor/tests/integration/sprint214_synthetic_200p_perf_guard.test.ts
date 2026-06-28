/**
 * Sprint 214 — Phase 7 200p+ synthetic fixture + perf guard
 *
 * Sprint 202 落地 49p synthetic fixture / Sprint 203 vitest perf guard、
 * Sprint 213 attestation 對 >200 頁標示「未實測、合成可線性外推」（49p
 * 線性 ×4 推估 200p ≈ cold 6.3s / warm 3.0s）。本 sprint 把外推轉為實測
 * fact、補上 Phase 7 大文件最終量化證據。
 *
 * 設計（紀律 #18 scope-down）：
 *   - 沿用 Sprint 202 generator pattern、章節數 ×4 = 500 章 × 11 段 =
 *     5500 段 → 預期 ~200 頁
 *   - 沿用 Sprint 203 vitest perf guard pattern、parse + layout 階段
 *     timing、3× CI safety
 *   - 沿用 11_perf_synthetic_large/ 已排除 VR pipeline 屬性、無新 exclude
 *
 * 閾值策略（紀律 #2、無 magic number）：
 *   - 49p 線性外推 ×4 + 3× CI safety
 *   - PARSE_TIME_THRESHOLD_MS = 2400 (4× Sprint 203 的 600)
 *   - LAYOUT_TIME_THRESHOLD_MS = 6000 (4× 1500)
 *   - TOTAL_TIME_THRESHOLD_MS = 8000 (4× 2000)
 *
 * 三層 SOP：
 *   - L1 vitest：本 test 即 L1 / 同時為 200p perf regression guard
 *   - L2 VR：fixture 落在已排除目錄、不入 VR pipeline
 *   - L3 perf：vitest 內測（parse + layout）；render 仍由 perf_baseline.mjs
 */

import { describe, expect, it } from 'vitest';
import { existsSync, readFileSync, writeFileSync, statSync } from 'node:fs';
import { resolve } from 'node:path';
import { performance } from 'node:perf_hooks';
import { OoxmlWriter } from '../../static/src/core/ooxml/export/OoxmlWriter';
import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';
import { layoutDocument } from '../../static/src/core/layout';
import type {
  DocumentNode,
  ParagraphNode,
  RunNode,
  SectionNode,
  RunProps,
} from '../../static/src/core/ooxml/ast/types';

const FIXTURE_DIR = resolve(__dirname, '../fixtures/11_perf_synthetic_large');
const FIXTURE_PATH = resolve(FIXTURE_DIR, 'text_200p.docx');

/** 規格（紀律 #2、無 magic number）：Sprint 202 章節數 ×4 = 200p 目標。 */
const SYNTHETIC_CHAPTERS = 500;
const PARAGRAPHS_PER_CHAPTER = 10;
const EXPECTED_PARAGRAPH_COUNT = SYNTHETIC_CHAPTERS * (PARAGRAPHS_PER_CHAPTER + 1); // = 5500
const HEADING_FONT_SIZE_PT = 14;

/** 49p 量得 ~49 頁、4× 章節線性推 ~196 頁、容寬 [180, 230]。 */
const EXPECTED_PAGE_COUNT_MIN = 180;
const EXPECTED_PAGE_COUNT_MAX = 230;

/** 閾值 = Sprint 203 49p 閾值 ×4（線性 fixture scaling）+ 3× CI safety 已包含於 Sprint 203 baseline。 */
const PARSE_TIME_THRESHOLD_MS = 2400;
const LAYOUT_TIME_THRESHOLD_MS = 6000;
const TOTAL_TIME_THRESHOLD_MS = 8000;

const writer = new OoxmlWriter();
const parser = new OoxmlParser();

/** 與 Sprint 202 共用之模板（保持 cache-friendly 對等、deterministic）。 */
const BODY_PARAGRAPH_TEMPLATES = [
  '本章節說明監造作業流程的細節要點，含品質管控、安全衛生注意事項與相關法規遵循指引。所有條目應由現場監造人員逐項確認並記錄。',
  '依據契約規格與設計圖說執行施工查驗，發現異常應立即通知承包商與設計單位、並於施工日誌中詳實記載。',
  '材料進場前需完成試驗報告與品質證明文件審查，未通過審查者不得進場使用。每批進場數量與時間需登載完備。',
  '人員機具進出工地應依規定刷卡或登錄、並按勞動部相關規範完成教育訓練與防護具配戴。',
  '本項作業預估工期、實際工期、停工天數、累計完成率等指標、應於每週工地會議檢討差異並研擬補救對策。',
  '環境保護措施含粉塵抑制、廢水處理、噪音管制等項目，承包商應依環評承諾事項按月提報執行情形。',
  '緊急應變計畫含火警、地震、墜落、溺水等情境分項演練、每年至少辦理乙次桌上演習與實地演練。',
  '相關佐證照片、檢驗紀錄、會議簽到表、申請書、核准函等文件、應於工程結束後彙整為竣工成果報告。',
];

function makeRun(text: string, props: RunProps = {}): RunNode {
  return { type: 'run', text, props };
}

function makeParagraph(runs: ParagraphNode['runs']): ParagraphNode {
  return { type: 'paragraph', runs, props: {} };
}

function makeSection(body: SectionNode['body']): SectionNode {
  return {
    type: 'section',
    page: { width: 595.3, height: 841.9, orientation: 'portrait' },
    margins: { top: 72, bottom: 72, left: 72, right: 72, header: 36, footer: 36 },
    headerRefs: {},
    footerRefs: {},
    titlePage: false,
    evenAndOddHeaders: false,
    body,
  };
}

function makeDoc(sections: SectionNode[]): DocumentNode {
  return {
    type: 'document',
    sections,
    headers: new Map(),
    footers: new Map(),
    footnotes: new Map(),
    endnotes: new Map(),
    comments: new Map(),
    settings: {},
    fontTable: new Map(),
    webSettings: {},
    styles: new Map(),
    numbering: new Map(),
    media: new Map(),
    docProps: {},
    appProps: {},
    customProps: new Map(),
    contentTypes: { defaults: new Map(), overrides: new Map() },
    latentStyles: {},
  };
}

function buildSynthetic200pDoc(): DocumentNode {
  const blocks: ParagraphNode[] = [];
  for (let chapter = 1; chapter <= SYNTHETIC_CHAPTERS; chapter++) {
    blocks.push(
      makeParagraph([
        makeRun(`第 ${chapter} 章　監造作業章節標題`, { b: true, size: HEADING_FONT_SIZE_PT }),
      ]),
    );
    for (let i = 0; i < PARAGRAPHS_PER_CHAPTER; i++) {
      const tpl = BODY_PARAGRAPH_TEMPLATES[(chapter * PARAGRAPHS_PER_CHAPTER + i) % BODY_PARAGRAPH_TEMPLATES.length];
      blocks.push(makeParagraph([makeRun(`${chapter}.${i + 1}　${tpl}`)]));
    }
  }
  return makeDoc([makeSection(blocks)]);
}

function ensureFixture(): ArrayBuffer {
  if (!existsSync(FIXTURE_PATH)) {
    const doc = buildSynthetic200pDoc();
    const bytes = writer.write(doc);
    writeFileSync(FIXTURE_PATH, bytes);
  }
  const buf = readFileSync(FIXTURE_PATH);
  return buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength) as ArrayBuffer;
}

describe('Sprint 214 — Phase 7 200p+ synthetic fixture + perf guard', () => {
  it('fixture 入 git、檔案大小 > 0、parser 段落數對齊 5500', () => {
    const arr = ensureFixture();
    const stat = statSync(FIXTURE_PATH);
    expect(stat.size).toBeGreaterThan(0);

    const doc = parser.parse(arr);
    let paragraphCount = 0;
    for (const sec of doc.sections) {
      for (const block of sec.body) {
        if (block.type === 'paragraph') paragraphCount++;
      }
    }
    expect(paragraphCount).toBe(EXPECTED_PARAGRAPH_COUNT);
  });

  it('parse + layout 時間在閾值內、頁數 180-230', () => {
    const arr = ensureFixture();

    const parseStart = performance.now();
    const doc = parser.parse(arr);
    const parseMs = performance.now() - parseStart;

    const layoutStart = performance.now();
    const layout = layoutDocument(doc.sections);
    const layoutMs = performance.now() - layoutStart;

    const totalMs = parseMs + layoutMs;

    // eslint-disable-next-line no-console
    console.log(
      `[sprint214] parse=${parseMs.toFixed(1)}ms layout=${layoutMs.toFixed(1)}ms ` +
        `total=${totalMs.toFixed(1)}ms pages=${layout.pages.length} ` +
        `fixture=${statSync(FIXTURE_PATH).size}bytes`,
    );

    // 49p 線性外推對比觀測（Sprint 213 attestation 預期 cold ~6.3s / warm ~3.0s）
    // eslint-disable-next-line no-console
    console.log(
      `[sprint214] vs 49p linear extrapolation: parse=${parseMs.toFixed(1)}ms vs ` +
        `~200ms（49p ×4 of ~50ms）/ layout=${layoutMs.toFixed(1)}ms vs ` +
        `~400ms（49p ×4 of ~100ms）`,
    );

    expect(layout.pages.length).toBeGreaterThanOrEqual(EXPECTED_PAGE_COUNT_MIN);
    expect(layout.pages.length).toBeLessThanOrEqual(EXPECTED_PAGE_COUNT_MAX);

    expect(parseMs).toBeLessThan(PARSE_TIME_THRESHOLD_MS);
    expect(layoutMs).toBeLessThan(LAYOUT_TIME_THRESHOLD_MS);
    expect(totalMs).toBeLessThan(TOTAL_TIME_THRESHOLD_MS);
  }, 30000); // 30s timeout for 200p layout
});
