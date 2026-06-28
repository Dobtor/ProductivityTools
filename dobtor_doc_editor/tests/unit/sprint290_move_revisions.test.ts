/**
 * Sprint 290 — ④ Phase 5.4+5.5 追蹤修訂 + 註解 backend / AST / parser side。
 *
 * 本 sprint = ④ cluster 第 1 sprint，scope-down 到 parser/AST 補完整：
 *
 *   - Sprint 174 已 capture `<w:ins>` / `<w:del>`
 *   - Sprint 290 補 `<w:moveFrom>` / `<w:moveTo>` 移動追蹤（OOXML §17.13.5.22/25）
 *   - 紀律 #18 scope-down：UI accept/reject 面板、註解互動面板留 future cluster；
 *     此 sprint 補 parser 完整、為 future UI 鋪資料層
 *
 * 紀律 #21：capture-only — render 端不消費新 type，不污染 VR pipeline。
 */
import { describe, expect, it } from 'vitest';

import { ParagraphParser } from '../../static/src/core/ooxml/document/ParagraphParser';
import type { ParagraphNode, RunNode } from '../../static/src/core/ooxml/ast/types';

const W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"';

function parseParagraph(inner: string): ParagraphNode {
  const xml = `<?xml version="1.0"?><w:document ${W_NS}><w:body><w:p>${inner}</w:p></w:body></w:document>`;
  const doc = new DOMParser().parseFromString(xml, 'application/xml');
  const pEl = doc.getElementsByTagName('w:p')[0];
  return new ParagraphParser({} as never).parse(pEl);
}

function findRuns(p: ParagraphNode): RunNode[] {
  return p.runs.filter((r): r is RunNode => r.type === 'run');
}

describe('Sprint 290 — w:moveFrom (移動來源) capture', () => {
  it('w:moveFrom 包裹 w:r → run.revision.type === "moveFrom"', () => {
    const p = parseParagraph(`
      <w:moveFrom w:id="3" w:author="Alice" w:date="2026-05-27T09:00:00Z">
        <w:r><w:delText>原始位置文字</w:delText></w:r>
      </w:moveFrom>
    `);
    const runs = findRuns(p);
    expect(runs).toHaveLength(1);
    expect(runs[0].text).toBe('原始位置文字');
    expect(runs[0].revision?.type).toBe('moveFrom');
    expect(runs[0].revision?.author).toBe('Alice');
    expect(runs[0].revision?.date).toBe('2026-05-27T09:00:00Z');
    expect(runs[0].revision?.id).toBe(3);
  });

  it('w:moveFrom 內含多 w:r → 全部 run 都標 moveFrom revision', () => {
    const p = parseParagraph(`
      <w:moveFrom w:id="5" w:author="Bob">
        <w:r><w:delText>第一段</w:delText></w:r>
        <w:r><w:delText>第二段</w:delText></w:r>
      </w:moveFrom>
    `);
    const runs = findRuns(p);
    expect(runs).toHaveLength(2);
    expect(runs.every((r) => r.revision?.type === 'moveFrom')).toBe(true);
    expect(runs.every((r) => r.revision?.author === 'Bob')).toBe(true);
  });
});

describe('Sprint 290 — w:moveTo (移動目的) capture', () => {
  it('w:moveTo 包裹 w:r → run.revision.type === "moveTo"', () => {
    const p = parseParagraph(`
      <w:moveTo w:id="3" w:author="Alice" w:date="2026-05-27T09:30:00Z">
        <w:r><w:t>移動後位置文字</w:t></w:r>
      </w:moveTo>
    `);
    const runs = findRuns(p);
    expect(runs).toHaveLength(1);
    expect(runs[0].text).toBe('移動後位置文字');
    expect(runs[0].revision?.type).toBe('moveTo');
    expect(runs[0].revision?.id).toBe(3);
  });

  it('w:moveTo 屬性全缺 → revision.type === "moveTo" 但 author/date/id 全 undefined', () => {
    const p = parseParagraph(`
      <w:moveTo>
        <w:r><w:t>無屬性</w:t></w:r>
      </w:moveTo>
    `);
    const runs = findRuns(p);
    expect(runs[0].revision?.type).toBe('moveTo');
    expect(runs[0].revision?.author).toBeUndefined();
    expect(runs[0].revision?.date).toBeUndefined();
    expect(runs[0].revision?.id).toBeUndefined();
  });
});

describe('Sprint 290 — moveFrom / moveTo 與既有 ins/del 並存', () => {
  it('段落混合 normal + ins + del + moveFrom + moveTo → 各 run 各自的 revision 正確', () => {
    const p = parseParagraph(`
      <w:r><w:t>普通</w:t></w:r>
      <w:ins w:id="1" w:author="A"><w:r><w:t>插入</w:t></w:r></w:ins>
      <w:del w:id="2" w:author="A"><w:r><w:delText>刪除</w:delText></w:r></w:del>
      <w:moveFrom w:id="3" w:author="A"><w:r><w:delText>移走</w:delText></w:r></w:moveFrom>
      <w:moveTo w:id="3" w:author="A"><w:r><w:t>放這裡</w:t></w:r></w:moveTo>
    `);
    const runs = findRuns(p);
    expect(runs).toHaveLength(5);
    expect(runs[0].text).toBe('普通');
    expect(runs[0].revision).toBeUndefined();
    expect(runs[1].text).toBe('插入');
    expect(runs[1].revision?.type).toBe('ins');
    expect(runs[2].text).toBe('刪除');
    expect(runs[2].revision?.type).toBe('del');
    expect(runs[3].text).toBe('移走');
    expect(runs[3].revision?.type).toBe('moveFrom');
    expect(runs[4].text).toBe('放這裡');
    expect(runs[4].revision?.type).toBe('moveTo');
    // 同 id 表示同一移動操作
    expect(runs[3].revision?.id).toBe(runs[4].revision?.id);
  });
});

describe('Sprint 290 — RunRevision 型別涵蓋 4 種', () => {
  it('TypeScript 編譯期：RunRevision.type 接受 ins/del/moveFrom/moveTo 四值', () => {
    // 純編譯期型別驗證：if 編譯不過、tsc step 會擋
    const p = parseParagraph(`
      <w:moveTo><w:r><w:t>X</w:t></w:r></w:moveTo>
    `);
    const runs = findRuns(p);
    const t = runs[0].revision?.type;
    expect(['ins', 'del', 'moveFrom', 'moveTo']).toContain(t);
  });
});
