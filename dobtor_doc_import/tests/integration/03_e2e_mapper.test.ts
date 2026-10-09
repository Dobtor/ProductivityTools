/**
 * Phase D.3 端到端整合測試 — DocumentNode → IElement[]
 *
 * 對所有 fixture 跑：
 *   .docx → OoxmlParser.parse() → ToCanvasEditor.convert() → IElement[]
 *
 * 驗收：
 *   - 所有 fixture 不 throw
 *   - IElement[] 非空且結構正確（含段落終止符 \n）
 *   - 圖片 fixture 能正確輸出 type=image 元素
 *   - 表格 fixture 能正確輸出 type=table 元素
 *
 * 不在此測試範圍：
 *   - pixelmatch vs LibreOffice golden（需要 puppeteer + canvas-editor headless render）
 *     → 留 Phase F（規劃 §6.2 Visual Regression Pipeline）
 */

import { describe, expect, it } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { resolve } from 'node:path';

import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';
import { ToCanvasEditor } from '../../static/src/core/ooxml/mapper/ToCanvasEditor';

const FIXTURE_ROOT = resolve(__dirname, '../fixtures');

function listFixtures(): string[] {
  const out: string[] = [];
  for (const cat of readdirSync(FIXTURE_ROOT)) {
    const catDir = resolve(FIXTURE_ROOT, cat);
    if (!statSync(catDir).isDirectory()) continue;
    for (const f of readdirSync(catDir)) {
      if (f.endsWith('.docx')) {
        out.push(`${cat}/${f}`);
      }
    }
  }
  return out;
}

function loadDocxAsBuffer(relativePath: string): ArrayBuffer {
  const buf = readFileSync(resolve(FIXTURE_ROOT, relativePath));
  return buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
}

const FIXTURES = listFixtures();
const parser = new OoxmlParser();
const mapper = new ToCanvasEditor();

describe('Phase D.3 — DocumentNode → IElement[] mapper 對全 fixture 不 throw', () => {
  it.each(FIXTURES)(
    '%s 跑通 OoxmlParser → ToCanvasEditor 並輸出非空 IElement[]',
    (relativePath) => {
      const buffer = loadDocxAsBuffer(relativePath);
      const doc = parser.parse(buffer);
      const elements = mapper.convert(doc);

      // 結構驗證
      expect(elements.length).toBeGreaterThan(0);

      // 每個 fixture 至少有一個段落終止符
      const hasNewline = elements.some((e) => e.value === '\n');
      expect(hasNewline).toBe(true);

      // 不應有 undefined value（mapper 必須給每個元素 value 欄位）
      for (const el of elements) {
        expect(el.value).toBeDefined();
      }
    },
  );
});

/**
 * 遞迴抽出所有文字 IElement value（含 valueList / table cell.value）。
 *
 * 監造會議記錄等 fixture 把實際內容放在表格 cell 內，平面 traverse 抓不到。
 */
function flattenText(els: ReadonlyArray<{ value: string; valueList?: ReadonlyArray<unknown>; trList?: ReadonlyArray<{ tdList: ReadonlyArray<{ value: ReadonlyArray<unknown> }> }> }>): string {
  let out = '';
  for (const e of els) {
    out += e.value;
    if (e.valueList) {
      out += flattenText(e.valueList as Parameters<typeof flattenText>[0]);
    }
    if (e.trList) {
      for (const tr of e.trList) {
        for (const td of tr.tdList) {
          out += flattenText(td.value as Parameters<typeof flattenText>[0]);
        }
      }
    }
  }
  return out;
}

describe('Phase D.3 — 特定 fixture 內容檢查', () => {
  it('01_simple 監造會議記錄的 IElement[] 含中文字元（內容多在表格 cell 內）', () => {
    const doc = parser.parse(
      loadDocxAsBuffer('01_simple/03.1120210-監造會議記錄-1120801.docx'),
    );
    const elements = mapper.convert(doc);
    const allText = flattenText(elements);
    expect(allText).toMatch(/監造|會議|出席|工程/);
  });

  it('02_std_table 週報含 type=table IElement', () => {
    const doc = parser.parse(
      loadDocxAsBuffer(
        '02_std_table/1120928-磺港溪再造C段護岸及步道整建工程(延壽橋至三合橋)週報.docx',
      ),
    );
    const elements = mapper.convert(doc);
    const tables = elements.filter((e) => e.type === 'table');
    expect(tables.length).toBeGreaterThan(0);
    // 第一張表至少有 colgroup + trList
    expect(tables[0].colgroup).toBeDefined();
    expect(tables[0].trList).toBeDefined();
    expect(tables[0].trList!.length).toBeGreaterThan(0);
  });

  it('03_complex_table 14欄送審管制：表格 + colgroup 14 欄', () => {
    const doc = parser.parse(
      loadDocxAsBuffer('03_complex_table/送審管制.docx'),
    );
    const elements = mapper.convert(doc);
    const tables = elements.filter((e) => e.type === 'table');
    expect(tables.length).toBeGreaterThan(0);
    // 至少有一張表 colgroup 達 14 欄
    const has14Col = tables.some((t) => (t.colgroup?.length ?? 0) >= 14);
    expect(has14Col).toBe(true);
  });

  it('04_with_image 含 type=image 元素，每個 image 有 width/height/dataURL', () => {
    const doc = parser.parse(
      loadDocxAsBuffer('04_with_image/05.112磺港溪監造會議照片.docx'),
    );
    const elements = mapper.convert(doc);
    // 圖片可能在 valueList 內（被 hyperlink 包），也可能直接在 root
    const collectImages = (els: typeof elements): typeof elements => {
      const out: typeof elements = [];
      for (const e of els) {
        if (e.type === 'image') out.push(e);
        if (e.valueList) out.push(...collectImages(e.valueList));
        if (e.trList) {
          for (const tr of e.trList) {
            for (const td of tr.tdList) out.push(...collectImages(td.value));
          }
        }
      }
      return out;
    };
    const images = collectImages(elements);
    expect(images.length).toBeGreaterThan(0);
    for (const img of images.slice(0, 5)) {
      expect(img.value).toMatch(/^data:image\//);
      expect(img.width).toBeGreaterThan(0);
      expect(img.height).toBeGreaterThan(0);
    }
  });
});

describe('Phase D.3 — 統計輸出（非 assertion，僅 console.log）', () => {
  it('輸出每類 fixture 的 IElement 平均數量', () => {
    const stats = new Map<string, number[]>();
    for (const path of FIXTURES) {
      const cat = path.split('/')[0];
      const doc = parser.parse(loadDocxAsBuffer(path));
      const elements = mapper.convert(doc);
      if (!stats.has(cat)) stats.set(cat, []);
      stats.get(cat)!.push(elements.length);
    }
    const lines: string[] = [];
    for (const [cat, counts] of stats) {
      const avg = counts.reduce((a, b) => a + b, 0) / counts.length;
      const max = Math.max(...counts);
      const min = Math.min(...counts);
      lines.push(`  ${cat}: avg=${avg.toFixed(0)}, min=${min}, max=${max}, n=${counts.length}`);
    }
    // 用 expect(true) 讓測試通過；console.log 是 e2e 觀察數據
    console.log('\n[Phase D.3 IElement 數量統計]\n' + lines.join('\n'));
    expect(true).toBe(true);
  });
});
