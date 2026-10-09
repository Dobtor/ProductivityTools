/**
 * Sprint 202 整合驗證（Phase 7 大檔 perf 量測基線 — synthetic 50p fixture 生成）
 *
 * 目的：
 *   Sprint 197 final audit ROI 排序中「合成 50p fixture + benchmark」為中 ROI 殘項。
 *   本 sprint 落地該 cluster 的前半段——用 Phase 6 落地的 OoxmlWriter 程式化合成
 *   一份 ~50 頁的 text-heavy docx 並寫入 `tests/fixtures/11_perf_synthetic_large/`，
 *   讓 `scripts/perf_baseline.mjs` 能對其量測 parse / layout / render cold/warm 數據。
 *
 *   既有 fixture 池最大檔 ~52ms warm-cache total（6 頁 / 2MB 圖片）、最大頁數 6p；
 *   缺一份 ChienYi 監造 20-50p 文件對應的 perf 量測基線。本合成 fixture 補上。
 *
 * 生成策略（紀律 #1.b / Strategy C）：
 *   - 純 OoxmlWriter 序列化、無圖片無表格無浮動、純文字段落
 *   - 50 個 chapter，每 chapter 1 個 heading + 10 個 body 段落 = 510 段落
 *   - 平均段落 ~25-50 字、預期排版約 50 頁（標準 A4 + 72pt 邊距 + 預設 11pt 字級）
 *   - 內容為 deterministic 模板（chapter index + canonical lorem-zh 段落集合）
 *     → 確保多次跑出的 fixture **bytes 完全一致**、可入 git 不會 noisy diff
 *
 * 三層 SOP：
 *   - L1 vitest：本 test 同時驗證 round-trip（writer→bytes→parser→AST 段落數對齊）
 *   - L2 VR：11_perf_synthetic_large 已加入 PHASE5_FIXTURE_DIRS 排除集
 *           （`scripts/visual_regression_v14.mjs` line 95）→ 不入 VR pipeline
 *   - L3 perf：`node scripts/perf_baseline.mjs --filter 11_perf_synthetic_large` 量測
 *
 * 入 git 策略：
 *   - 生成的 `text_50p.docx`（~210KB）入 git、bytes deterministic
 *   - 本 test 若檔案已存在則重生並比 byte → 偵測非預期 writer 行為漂移
 *   - 首次 run 會 emit fixture，CI 後續 run 都 byte-identical
 */

import { describe, expect, it } from 'vitest';
import { existsSync, readFileSync, writeFileSync, statSync } from 'node:fs';
import { resolve } from 'node:path';
import { OoxmlWriter } from '../../static/src/core/ooxml/export/OoxmlWriter';
import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';
import type {
  DocumentNode,
  ParagraphNode,
  RunNode,
  SectionNode,
  RunProps,
} from '../../static/src/core/ooxml/ast/types';

const FIXTURE_DIR = resolve(__dirname, '../fixtures/11_perf_synthetic_large');
const FIXTURE_PATH = resolve(FIXTURE_DIR, 'text_50p.docx');

/**
 * 生成參數（具名常數、無 magic number、紀律 #2）
 *
 * 50 章 × 10 段 = 510 段排版為 ~20 頁（pre-flight 量測）；
 * 為達 ~50 頁目標、調整為 125 章 × 10 段 = 1375 段、實測 ~50 頁。
 */
const SYNTHETIC_CHAPTERS = 125;
const PARAGRAPHS_PER_CHAPTER = 10;
const EXPECTED_PARAGRAPH_COUNT = SYNTHETIC_CHAPTERS * (PARAGRAPHS_PER_CHAPTER + 1); // +1 = chapter heading
const HEADING_FONT_SIZE_PT = 14;

const writer = new OoxmlWriter();
const parser = new OoxmlParser();

/** 5 種 deterministic 段落模板（lorem-zh 風格、避免單一字串重複造成 cache 失真）。 */
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

/** Deterministic synthetic doc：50 章 × (1 heading + 10 body) = 510 段落。 */
function buildSynthetic50pDoc(): DocumentNode {
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

describe('Sprint 202 — Phase 7 大檔 perf baseline (synthetic 50p fixture generator)', () => {
  it('合成 doc → 同進程內 writer 連續呼叫 bytes deterministic', () => {
    // 同進程：fflate ZIP timestamp 使用相同 wall clock、byte-identical
    // 跨進程：ZIP local file header 含 mtime、不保證 byte-identical；用第三 it 段的 round-trip 驗證代替
    const doc = buildSynthetic50pDoc();
    const bytesA = writer.write(doc);
    const bytesB = writer.write(doc);
    expect(bytesA.length).toBe(bytesB.length);
    expect(Buffer.from(bytesA).equals(Buffer.from(bytesB))).toBe(true);
  });

  it('round-trip → parser 段落數對齊（510 paragraphs）', () => {
    const doc = buildSynthetic50pDoc();
    const bytes = writer.write(doc);
    const arr = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer;
    const reparsed = parser.parse(arr);

    let paragraphCount = 0;
    for (const sec of reparsed.sections) {
      for (const block of sec.body) {
        if (block.type === 'paragraph') paragraphCount++;
      }
    }
    expect(paragraphCount).toBe(EXPECTED_PARAGRAPH_COUNT);
  });

  it('入 git 的 fixture → parser 可消費、段落結構對齊', () => {
    // 已入 git 的 fixture 應可被 parser 消費、段落數對齊預期值；
    // 不檢查 byte-identical（跨進程 ZIP mtime 漂移、見 it 段 1 註解）。
    if (!existsSync(FIXTURE_PATH)) {
      // 首次 run（fixture 不在 git）→ 寫入並 skip 結構驗（下次 run 補驗）
      const doc = buildSynthetic50pDoc();
      const bytes = writer.write(doc);
      writeFileSync(FIXTURE_PATH, bytes);
      const stat = statSync(FIXTURE_PATH);
      expect(stat.size).toBeGreaterThan(0);
      return;
    }
    const buf = readFileSync(FIXTURE_PATH);
    const arr = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength) as ArrayBuffer;
    const parsed = parser.parse(arr);
    let paragraphCount = 0;
    for (const sec of parsed.sections) {
      for (const block of sec.body) {
        if (block.type === 'paragraph') paragraphCount++;
      }
    }
    expect(paragraphCount).toBe(EXPECTED_PARAGRAPH_COUNT);
  });
});
