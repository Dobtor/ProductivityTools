/**
 * Sprint 11 — Page header / footer 渲染
 *
 * 涵蓋：
 *   1. 預設 header/footer 套用到所有頁
 *   2. titlePage：第一頁用 first，其他頁用 default
 *   3. evenAndOddHeaders：偶頁用 even、奇頁用 default
 *   4. Header 起點 y = section.margins.header
 *   5. Footer 結束 y = pageHeight - section.margins.footer
 *   6. PAGE 欄位在 footer 內也會被替換為當頁 pageNumber
 *   7. NUMPAGES 在 header 內 = 總頁數
 *   8. 沒傳 headers/footers map → 不畫 header/footer（與 Sprint 10 行為一致）
 */

import { describe, expect, it } from 'vitest';
import { readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { layoutDocument } from '../../../static/src/core/layout/Paginator';
import { OoxmlParser } from '../../../static/src/core/ooxml/OoxmlParser';
import type {
  SectionNode,
  ParagraphNode,
  RunNode,
  FieldNode,
  HeaderFooterContent,
  BreakNode,
} from '../../../static/src/core/ooxml/ast/types';
import type { Box } from '../../../static/src/core/layout/types';

const A4 = { width: 595, height: 842, orientation: 'portrait' as const };
const MARGINS = { top: 72, bottom: 72, left: 72, right: 72, header: 36, footer: 36 };

function para(text: string): ParagraphNode {
  const run: RunNode = { type: 'run', text, props: { fontSize: 12 } };
  return { type: 'paragraph', props: {}, runs: [run] };
}

function paraField(fieldType: 'PAGE' | 'NUMPAGES'): ParagraphNode {
  const fld: FieldNode = { type: 'field', instruction: ` ${fieldType} `, fieldType };
  return { type: 'paragraph', props: {}, runs: [fld] };
}

function paraText(text: string): ParagraphNode {
  return para(text);
}

function makeSection(
  body: SectionNode['body'],
  refs: { headerRefs?: SectionNode['headerRefs']; footerRefs?: SectionNode['footerRefs']; titlePage?: boolean; evenAndOddHeaders?: boolean } = {},
): SectionNode {
  return {
    type: 'section', page: A4, margins: MARGINS,
    headerRefs: refs.headerRefs ?? {},
    footerRefs: refs.footerRefs ?? {},
    titlePage: refs.titlePage ?? false,
    evenAndOddHeaders: refs.evenAndOddHeaders ?? false,
    body,
  };
}

function header(rId: string, content: HeaderFooterContent['content']): HeaderFooterContent {
  return { rId, content };
}

// ── helpers ────────────────────────────────────────────────────────────

function findLineEntries(
  layout: { pages: import('../../../static/src/core/layout/types').Page[] },
): Array<{ pageNumber: number; y: number; texts: string[] }> {
  const out: Array<{ pageNumber: number; y: number; texts: string[] }> = [];
  for (const page of layout.pages) {
    for (const e of page.entries) {
      if (e.kind === 'line') {
        const texts = e.line.items
          .filter((it): it is Box => it.kind === 'box')
          .map((b) => b.text);
        out.push({ pageNumber: page.pageNumber, y: e.y, texts });
      }
    }
  }
  return out;
}

// ── 1. 預設 header / footer ───────────────────────────────────────────

describe('Sprint 11 — 預設 header/footer 套用所有頁', () => {
  it('default header 出現在每頁', () => {
    const headers = new Map<string, HeaderFooterContent>([
      ['rH1', header('rH1', [paraText('HDR')])],
    ]);
    const sec = makeSection([paraText('body 1'), paraText('body 2')], {
      headerRefs: { default: 'rH1' },
    });
    const layout = layoutDocument([sec], { headers });
    const lineEntries = findLineEntries(layout);
    const headerEntries = lineEntries.filter((l) => l.texts.includes('HDR'));
    expect(headerEntries.length).toBe(layout.pages.length);
    // header y = margins.header
    for (const e of headerEntries) {
      expect(e.y).toBe(MARGINS.header);
    }
  });

  it('default footer 出現在每頁，y 在 page bottom 區', () => {
    const footers = new Map<string, HeaderFooterContent>([
      ['rF1', header('rF1', [paraText('FOOT')])],
    ]);
    const sec = makeSection([paraText('content')], {
      footerRefs: { default: 'rF1' },
    });
    const layout = layoutDocument([sec], { footers });
    const lineEntries = findLineEntries(layout);
    const footerEntries = lineEntries.filter((l) => l.texts.includes('FOOT'));
    expect(footerEntries.length).toBe(layout.pages.length);
    // footer 在 page bottom 區（pageHeight - footer margin 之上）
    for (const e of footerEntries) {
      expect(e.y).toBeGreaterThan(A4.height - MARGINS.footer - 50);
      expect(e.y).toBeLessThan(A4.height - MARGINS.footer);
    }
  });

  it('沒傳 headers/footers map → 沒有 header/footer entries', () => {
    const sec = makeSection([paraText('body')], {
      headerRefs: { default: 'rH1' }, footerRefs: { default: 'rF1' },
    });
    // 不傳 headers/footers
    const layout = layoutDocument([sec]);
    const lineEntries = findLineEntries(layout);
    // 只有 body
    expect(lineEntries.length).toBe(1);
    expect(lineEntries[0].texts.join('')).toContain('body');
  });
});

// ── 2. titlePage ───────────────────────────────────────────────────────

describe('Sprint 11 — titlePage', () => {
  it('titlePage=true 時第一頁用 first，其餘頁用 default', () => {
    const headers = new Map<string, HeaderFooterContent>([
      ['rDef', header('rDef', [paraText('DEFAULT_HDR')])],
      ['rFirst', header('rFirst', [paraText('FIRST_HDR')])],
    ]);
    // 強制兩頁
    const breakRun: RunNode = { type: 'run', text: 'p1', props: { fontSize: 12 } };
    const br: BreakNode = { type: 'break', breakType: 'page' };
    const p1: ParagraphNode = { type: 'paragraph', props: {}, runs: [breakRun, br] };
    const p2 = paraText('page 2 content');
    const sec = makeSection([p1, p2], {
      headerRefs: { default: 'rDef', first: 'rFirst' },
      titlePage: true,
    });
    const layout = layoutDocument([sec], { headers });
    expect(layout.pages.length).toBe(2);
    const lineEntries = findLineEntries(layout);
    const firstHdr = lineEntries.filter((l) => l.pageNumber === 1 && l.texts.some((t) => t.includes('FIRST_HDR')));
    const defHdrPage2 = lineEntries.filter((l) => l.pageNumber === 2 && l.texts.some((t) => t.includes('DEFAULT_HDR')));
    expect(firstHdr.length).toBe(1);
    expect(defHdrPage2.length).toBe(1);
  });

  it('titlePage=false 時第一頁也用 default（非 first）', () => {
    const headers = new Map<string, HeaderFooterContent>([
      ['rDef', header('rDef', [paraText('DEFAULT_HDR')])],
      ['rFirst', header('rFirst', [paraText('FIRST_HDR')])],
    ]);
    const sec = makeSection([paraText('only page')], {
      headerRefs: { default: 'rDef', first: 'rFirst' },
      titlePage: false,
    });
    const layout = layoutDocument([sec], { headers });
    const lineEntries = findLineEntries(layout);
    const firstUsed = lineEntries.some((l) => l.texts.some((t) => t.includes('FIRST_HDR')));
    const defaultUsed = lineEntries.some((l) => l.texts.some((t) => t.includes('DEFAULT_HDR')));
    expect(firstUsed).toBe(false);
    expect(defaultUsed).toBe(true);
  });
});

// ── 3. evenAndOddHeaders ─────────────────────────────────────────────────

describe('Sprint 11 — evenAndOddHeaders', () => {
  it('偶頁用 even、奇頁用 default', () => {
    const headers = new Map<string, HeaderFooterContent>([
      ['rOdd', header('rOdd', [paraText('ODD_HDR')])],
      ['rEven', header('rEven', [paraText('EVEN_HDR')])],
    ]);
    // 強制 3 頁
    const br: BreakNode = { type: 'break', breakType: 'page' };
    const r1: RunNode = { type: 'run', text: 'p1', props: { fontSize: 12 } };
    const r2: RunNode = { type: 'run', text: 'p2', props: { fontSize: 12 } };
    const p1: ParagraphNode = { type: 'paragraph', props: {}, runs: [r1, br] };
    const p2: ParagraphNode = { type: 'paragraph', props: {}, runs: [r2, br] };
    const p3 = paraText('p3');
    const sec = makeSection([p1, p2, p3], {
      headerRefs: { default: 'rOdd', even: 'rEven' },
      evenAndOddHeaders: true,
    });
    const layout = layoutDocument([sec], { headers });
    expect(layout.pages.length).toBe(3);
    const lineEntries = findLineEntries(layout);
    const page1 = lineEntries.filter((l) => l.pageNumber === 1);
    const page2 = lineEntries.filter((l) => l.pageNumber === 2);
    const page3 = lineEntries.filter((l) => l.pageNumber === 3);
    expect(page1.some((l) => l.texts.some((t) => t.includes('ODD_HDR')))).toBe(true);
    expect(page2.some((l) => l.texts.some((t) => t.includes('EVEN_HDR')))).toBe(true);
    expect(page3.some((l) => l.texts.some((t) => t.includes('ODD_HDR')))).toBe(true);
  });
});

// ── 4. PAGE / NUMPAGES 在 header / footer 內 ────────────────────────────

describe('Sprint 11 — PAGE / NUMPAGES in header / footer', () => {
  it('footer 內 PAGE 自動填入當頁 pageNumber', () => {
    const footers = new Map<string, HeaderFooterContent>([
      ['rF', header('rF', [paraField('PAGE')])],
    ]);
    // 三頁
    const br: BreakNode = { type: 'break', breakType: 'page' };
    const r1: RunNode = { type: 'run', text: 'a', props: { fontSize: 12 } };
    const r2: RunNode = { type: 'run', text: 'b', props: { fontSize: 12 } };
    const p1: ParagraphNode = { type: 'paragraph', props: {}, runs: [r1, br] };
    const p2: ParagraphNode = { type: 'paragraph', props: {}, runs: [r2, br] };
    const p3 = paraText('c');
    const sec = makeSection([p1, p2, p3], { footerRefs: { default: 'rF' } });
    const layout = layoutDocument([sec], { footers });
    expect(layout.pages.length).toBe(3);

    // 每頁 footer 應有「當頁頁碼」box
    for (const page of layout.pages) {
      const fieldBoxes: Box[] = [];
      for (const e of page.entries) {
        if (e.kind === 'line') {
          for (const item of e.line.items) {
            if (item.kind === 'box' && item.fieldType === 'PAGE') fieldBoxes.push(item);
          }
        }
      }
      expect(fieldBoxes.length).toBe(1);
      expect(fieldBoxes[0].text).toBe(String(page.pageNumber));
    }
  });

  it('header 內 NUMPAGES = 總頁數', () => {
    const headers = new Map<string, HeaderFooterContent>([
      ['rH', header('rH', [paraField('NUMPAGES')])],
    ]);
    const body: SectionNode['body'] = [];
    for (let i = 0; i < 100; i++) body.push(paraText(`x ${i}`));
    const sec = makeSection(body, { headerRefs: { default: 'rH' } });
    const layout = layoutDocument([sec], { headers });
    expect(layout.pages.length).toBeGreaterThan(1);
    // 找 header 內的 NUMPAGES box
    const totalPages = layout.pages.length;
    for (const page of layout.pages) {
      const numpages: Box[] = [];
      for (const e of page.entries) {
        if (e.kind === 'line') {
          for (const item of e.line.items) {
            if (item.kind === 'box' && item.fieldType === 'NUMPAGES') numpages.push(item);
          }
        }
      }
      expect(numpages.length).toBe(1);
      expect(numpages[0].text).toBe(String(totalPages));
    }
  });
});

// ── 5. Fixture-level 整合（真實 docx）─────────────────────────────────────

describe('Sprint 11 — fixture-level header/footer 整合', () => {
  it('05_header_footer 類 fixture：傳入 documentNode.headers/footers 後 pages 含 header line', () => {
    const dir = resolve(__dirname, '../../fixtures/05_header_footer');
    const files = readdirSync(dir).filter((f) => f.endsWith('.docx'));
    expect(files.length).toBeGreaterThan(0);

    let totalHeaderLines = 0;
    let pagesWithHeader = 0;
    let totalPages = 0;
    for (const fname of files.slice(0, 3)) { // 抽 3 份避免 test 太久
      const buf = readFileSync(resolve(dir, fname));
      const doc = new OoxmlParser().parse(buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength));
      const layout = layoutDocument(doc.sections, {
        headers: doc.headers,
        footers: doc.footers,
      });
      totalPages += layout.pages.length;
      for (const page of layout.pages) {
        let hasHeader = false;
        for (const e of page.entries) {
          if (e.kind === 'line' && e.y < 72) {
            // y < marginTop 視為頁首區
            totalHeaderLines++;
            hasHeader = true;
          }
        }
        if (hasHeader) pagesWithHeader++;
      }
    }
    // 至少要有些頁面有 header
    expect(totalPages).toBeGreaterThan(0);
    expect(totalHeaderLines).toBeGreaterThan(0);
    expect(pagesWithHeader).toBeGreaterThan(0);
  });
});

// ── 6. fallback 規則 ────────────────────────────────────────────────────

describe('Sprint 11 — header/footer fallback', () => {
  it('section 只有 first 沒有 default：當第一頁用 first；後續頁也 fallback first（無 default）', () => {
    const headers = new Map<string, HeaderFooterContent>([
      ['rFirst', header('rFirst', [paraText('ONLY_FIRST')])],
    ]);
    // 兩頁
    const br: BreakNode = { type: 'break', breakType: 'page' };
    const r1: RunNode = { type: 'run', text: 'p1', props: { fontSize: 12 } };
    const p1: ParagraphNode = { type: 'paragraph', props: {}, runs: [r1, br] };
    const p2 = paraText('p2');
    const sec = makeSection([p1, p2], {
      headerRefs: { first: 'rFirst' }, titlePage: true,
    });
    const layout = layoutDocument([sec], { headers });
    const lineEntries = findLineEntries(layout);
    // 第一頁有 ONLY_FIRST，第二頁也有（fallback）
    const p1Hdr = lineEntries.filter((l) => l.pageNumber === 1 && l.texts.some((t) => t.includes('ONLY_FIRST')));
    const p2Hdr = lineEntries.filter((l) => l.pageNumber === 2 && l.texts.some((t) => t.includes('ONLY_FIRST')));
    expect(p1Hdr.length).toBe(1);
    expect(p2Hdr.length).toBe(1);
  });
});
