/**
 * Phase 1（Sprint 1 補完）— AST 結構快照回歸測試
 *
 * 目的：對 42 份 fixture 各算一份「結構指紋」（paragraph 數、table 數、image 數、
 *      table colgroup 統計、文字字元數、首尾文字片段），用 vitest snapshot 釘住。
 *      Parser 任何結構性 regression 都會在這裡跳出來。
 *
 * 為什麼不直接 dump 整個 IElement[]：
 *   - 完整 dump 太大（單檔最多 339 個 element），每次 review 像瞎子摸象
 *   - 文字內容夾在 valueList / trList 裡，diff 噪音太大
 *
 * 為什麼不在 03_e2e_mapper.test.ts 直接加：
 *   - 那邊是邏輯 assertion（`expect(...).toBeGreaterThan(0)`），不適合釘 snapshot
 *   - 切開一支獨立的 test file，回歸失敗時 reviewer 一看檔名就知道是「結構漂移」
 *
 * 何時要 -u（更新 snapshot）：
 *   - 新增 fixture
 *   - Parser 已知行為變更（並 PR review 通過）
 *   - 不可在「不知道為什麼變」的時候 -u
 */

import { describe, expect, it } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { resolve } from 'node:path';
import { createHash } from 'node:crypto';

import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';
import { ToCanvasEditor } from '../../static/src/core/ooxml/mapper/ToCanvasEditor';
import type { CEElement } from '../../static/src/core/ooxml/mapper/ToCanvasEditor';

const FIXTURE_ROOT = resolve(__dirname, '../fixtures');

interface Fingerprint {
  category: string;
  filename: string;
  totalElements: number;
  paragraphTerminators: number;
  tableCount: number;
  imageCount: number;
  hyperlinkCount: number;
  /** colgroup 欄寬總和（單位 px，整數） */
  colWidthSum: number[];
  /** 表格大小（rows × cols） */
  tableShapes: string[];
  /** 文字總長 */
  textLength: number;
  /** 文字前 80 字（趨勢偵測，不釘到全文）*/
  textHead: string;
  /** 文字 SHA1（變動檢測；不要釘整段，避免微改噪音）*/
  textSha1: string;
}

/**
 * Sprint 179：Phase 5 大三項 fixture 目錄（OMML / SmartArt / Charts parser 驗證用）。
 * 非 VR baseline 的「42 fixture」成員 —— AST 結構快照不納入。
 * Sprint 202：11_perf_synthetic_large 為 Phase 7 大檔 perf 量測用合成 fixture、AST snapshot 不納入。
 */
const PHASE5_FIXTURE_DIRS = new Set(['07_chart', '08_smartart', '09_omml', '11_perf_synthetic_large']);

function listFixtures(): string[] {
  const out: string[] = [];
  for (const cat of readdirSync(FIXTURE_ROOT)) {
    const catDir = resolve(FIXTURE_ROOT, cat);
    if (PHASE5_FIXTURE_DIRS.has(cat) || !statSync(catDir).isDirectory()) continue;
    for (const f of readdirSync(catDir)) {
      if (f.endsWith('.docx')) {
        out.push(`${cat}/${f}`);
      }
    }
  }
  return out.sort();
}

function loadDocxAsBuffer(relativePath: string): ArrayBuffer {
  const buf = readFileSync(resolve(FIXTURE_ROOT, relativePath));
  return buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
}

/** 遞迴掃所有 element 收結構統計與所有文字 */
function walk(
  els: ReadonlyArray<CEElement>,
  acc: {
    total: number;
    terminators: number;
    tables: number;
    images: number;
    hyperlinks: number;
    colWidthSums: number[];
    tableShapes: string[];
    text: string[];
  },
): void {
  for (const e of els) {
    acc.total++;
    if (e.value === '\n') acc.terminators++;
    if (e.type === 'image') acc.images++;
    if (e.type === 'hyperlink') acc.hyperlinks++;
    if (e.type === 'table') {
      acc.tables++;
      const colSum = (e.colgroup ?? []).reduce(
        (s, c) => s + Math.round((c as { width?: number }).width ?? 0),
        0,
      );
      acc.colWidthSums.push(colSum);
      const rows = e.trList?.length ?? 0;
      const cols = e.colgroup?.length ?? 0;
      acc.tableShapes.push(`${rows}x${cols}`);
    }
    // 純文字
    if (
      e.value &&
      e.value !== '\n' &&
      e.type !== 'image' &&
      typeof e.value === 'string'
    ) {
      acc.text.push(e.value);
    }
    if (e.valueList) walk(e.valueList as ReadonlyArray<CEElement>, acc);
    if (e.trList) {
      for (const tr of e.trList) {
        for (const td of tr.tdList) {
          walk(td.value as ReadonlyArray<CEElement>, acc);
        }
      }
    }
  }
}

function fingerprint(relativePath: string): Fingerprint {
  const [category, filename] = relativePath.split('/');
  const parser = new OoxmlParser();
  const mapper = new ToCanvasEditor();
  const doc = parser.parse(loadDocxAsBuffer(relativePath));
  const elements = mapper.convert(doc);

  const acc = {
    total: 0,
    terminators: 0,
    tables: 0,
    images: 0,
    hyperlinks: 0,
    colWidthSums: [] as number[],
    tableShapes: [] as string[],
    text: [] as string[],
  };
  walk(elements, acc);

  const fullText = acc.text.join('');
  return {
    category,
    filename,
    totalElements: acc.total,
    paragraphTerminators: acc.terminators,
    tableCount: acc.tables,
    imageCount: acc.images,
    hyperlinkCount: acc.hyperlinks,
    colWidthSum: acc.colWidthSums,
    tableShapes: acc.tableShapes,
    textLength: fullText.length,
    textHead: fullText.slice(0, 80),
    textSha1: createHash('sha1').update(fullText).digest('hex'),
  };
}

const FIXTURES = listFixtures();

describe('Sprint 1 — AST 結構快照（42 fixtures）', () => {
  it.each(FIXTURES)('%s 結構指紋符合 snapshot', (relativePath) => {
    const fp = fingerprint(relativePath);
    expect(fp).toMatchSnapshot();
  });
});
