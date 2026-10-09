/**
 * Sprint 12 — 完整 field 系統 (DATE / TIME / AUTHOR / FILENAME)
 *
 * 涵蓋：
 *   1. DATE 欄位用 documentMetadata.now 格式化
 *   2. TIME 欄位用 timeFormat 格式化
 *   3. AUTHOR / FILENAME 欄位讀 metadata
 *   4. metadata 缺欄位時保留 placeholder
 *   5. 自訂 dateFormat
 *   6. 多頁文件 PAGE 仍然正確（regression）
 *   7. header / footer 內 DATE 也會替換
 */

import { describe, expect, it } from 'vitest';
import { layoutDocument } from '../../../static/src/core/layout/Paginator';
import type {
  SectionNode,
  ParagraphNode,
  RunNode,
  FieldNode,
  HeaderFooterContent,
} from '../../../static/src/core/ooxml/ast/types';
import type { Box } from '../../../static/src/core/layout/types';

const A4 = { width: 595, height: 842, orientation: 'portrait' as const };
const MARGINS = { top: 72, bottom: 72, left: 72, right: 72, header: 36, footer: 36 };

function paraField(fieldType: 'DATE' | 'TIME' | 'AUTHOR' | 'FILENAME' | 'PAGE'): ParagraphNode {
  const fld: FieldNode = { type: 'field', instruction: ` ${fieldType} `, fieldType };
  return { type: 'paragraph', props: {}, runs: [fld] };
}

function makeSection(body: SectionNode['body']): SectionNode {
  return {
    type: 'section', page: A4, margins: MARGINS,
    headerRefs: {}, footerRefs: {}, titlePage: false, evenAndOddHeaders: false, body,
  };
}

function findFieldBox(layout: { pages: import('../../../static/src/core/layout/types').Page[] }, type: string): Box | undefined {
  for (const page of layout.pages) {
    for (const e of page.entries) {
      if (e.kind === 'line') {
        for (const it of e.line.items) {
          if (it.kind === 'box' && it.fieldType === type) return it;
        }
      }
    }
  }
  return undefined;
}

// ── DATE / TIME ────────────────────────────────────────────────────────────

describe('Sprint 12 — DATE / TIME 欄位', () => {
  it('DATE 預設格式 yyyy/MM/dd', () => {
    const sec = makeSection([paraField('DATE')]);
    const layout = layoutDocument([sec], {
      documentMetadata: { now: new Date(2026, 4, 8) }, // 2026-05-08
    });
    const box = findFieldBox(layout, 'DATE');
    expect(box?.text).toBe('2026/05/08');
  });

  it('自訂 dateFormat', () => {
    const sec = makeSection([paraField('DATE')]);
    const layout = layoutDocument([sec], {
      documentMetadata: {
        now: new Date(2026, 11, 31), // 2026-12-31
        dateFormat: 'yyyy-MM-dd',
      },
    });
    const box = findFieldBox(layout, 'DATE');
    expect(box?.text).toBe('2026-12-31');
  });

  it('TIME 預設格式 HH:mm', () => {
    const sec = makeSection([paraField('TIME')]);
    const layout = layoutDocument([sec], {
      documentMetadata: { now: new Date(2026, 4, 8, 14, 30, 45) },
    });
    const box = findFieldBox(layout, 'TIME');
    expect(box?.text).toBe('14:30');
  });

  it('TIME 帶秒：HH:mm:ss', () => {
    const sec = makeSection([paraField('TIME')]);
    const layout = layoutDocument([sec], {
      documentMetadata: {
        now: new Date(2026, 4, 8, 9, 5, 7),
        timeFormat: 'HH:mm:ss',
      },
    });
    const box = findFieldBox(layout, 'TIME');
    expect(box?.text).toBe('09:05:07');
  });

  it('沒傳 documentMetadata → DATE 用 new Date()（不 throw）', () => {
    const sec = makeSection([paraField('DATE')]);
    const layout = layoutDocument([sec]);
    const box = findFieldBox(layout, 'DATE');
    expect(box?.text).toMatch(/^\d{4}\/\d{2}\/\d{2}$/);
  });
});

// ── AUTHOR / FILENAME ─────────────────────────────────────────────────────

describe('Sprint 12 — AUTHOR / FILENAME 欄位', () => {
  it('AUTHOR 從 metadata 取', () => {
    const sec = makeSection([paraField('AUTHOR')]);
    const layout = layoutDocument([sec], {
      documentMetadata: { author: '張三' },
    });
    const box = findFieldBox(layout, 'AUTHOR');
    expect(box?.text).toBe('張三');
  });

  it('FILENAME 從 metadata 取', () => {
    const sec = makeSection([paraField('FILENAME')]);
    const layout = layoutDocument([sec], {
      documentMetadata: { filename: '監造日誌.docx' },
    });
    const box = findFieldBox(layout, 'FILENAME');
    expect(box?.text).toBe('監造日誌.docx');
  });

  it('metadata 沒傳 author → AUTHOR 保留 placeholder', () => {
    const sec = makeSection([paraField('AUTHOR')]);
    const layout = layoutDocument([sec]);
    const box = findFieldBox(layout, 'AUTHOR');
    // placeholder = 'Author' (from BoxBuilder)
    expect(box?.text).toBe('Author');
  });
});

// ── PAGE regression ───────────────────────────────────────────────────────

describe('Sprint 12 — PAGE 仍正常（Sprint 10 regression）', () => {
  it('PAGE 真值不被 DATE/TIME 處理流程影響', () => {
    const sec = makeSection([paraField('PAGE')]);
    const layout = layoutDocument([sec], {
      documentMetadata: { now: new Date(2026, 0, 1) },
    });
    const box = findFieldBox(layout, 'PAGE');
    expect(box?.text).toBe('1');
  });
});

// ── header / footer DATE ──────────────────────────────────────────────────

describe('Sprint 12 — DATE 在 header / footer', () => {
  it('footer 內 DATE 自動填值', () => {
    const footers = new Map<string, HeaderFooterContent>([
      ['rF', { rId: 'rF', content: [paraField('DATE')] }],
    ]);
    const r1: RunNode = { type: 'run', text: 'body', props: { fontSize: 12 } };
    const p1: ParagraphNode = { type: 'paragraph', props: {}, runs: [r1] };
    const sec: SectionNode = {
      type: 'section', page: A4, margins: MARGINS,
      headerRefs: {}, footerRefs: { default: 'rF' },
      titlePage: false, evenAndOddHeaders: false, body: [p1],
    };
    const layout = layoutDocument([sec], {
      footers,
      documentMetadata: { now: new Date(2026, 6, 4) },
    });
    const box = findFieldBox(layout, 'DATE');
    expect(box?.text).toBe('2026/07/04');
  });
});
