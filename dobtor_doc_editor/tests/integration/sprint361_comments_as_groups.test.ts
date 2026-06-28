/**
 * Sprint 361 — Phase 5.5 註解互動 panel · Slice 1.A：mapper 用 groupIds 標記範圍。
 *
 * 真實 ChienYi corpus 0 份含註解（已於 2026-05-30 grounding-check 確認），所以走
 * libreoffice 測試 corpus 的標準註解 fixture 驗 mapper 正確性。
 *
 * 鎖定 opt-in 契約：不開旗標 → 既有 `[註解 作者: 內容]` inline 文字 fallback；
 * 開旗標 → 註解段落的 IElement 掛 `groupIds=[String(commentId)]`，inline 文字不再
 * 輸出，並由 `getCommentAnchors()` 回傳前端 panel 消費所需 metadata。
 *
 * Parser-side 已知邊界：若 docx 把 commentRangeStart/End 放在獨立的空 `<w:p>` 包住
 * 實際被註解的段落（例：`paragraphWithComments.docx`），ParagraphParser 目前把
 * commentRefs 掛在空 marker 段落、非實際文字段落 → 此時 groupIds 會落在空段而不
 * highlight 文字。本測試挑了 `annotation-formatting.docx`（refs 落在文字段落）驗
 * mapper 端契約；marker-paragraph 對齊問題留 Slice 1.A.2 在 parser 側處理。
 */
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';
import { ToCanvasEditor } from '../../static/src/core/ooxml/mapper/ToCanvasEditor';
import type { CEElement } from '../../static/src/core/ooxml/mapper/ToCanvasEditor';

const FIXTURE = '10_ooxml_libreoffice/note/annotation-formatting.docx';

async function parseFixture() {
  const buf = readFileSync(resolve(__dirname, '../fixtures', FIXTURE));
  const arr = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
  return new OoxmlParser().parse(arr as ArrayBuffer);
}

/** 遞迴展開（含 table cell trList/tdList、hyperlink valueList）。 */
function allElements(els: CEElement[]): CEElement[] {
  const out: CEElement[] = [];
  const walk = (arr: CEElement[] | undefined): void => {
    if (!Array.isArray(arr)) return;
    for (const e of arr) {
      if (!e || typeof e !== 'object') continue;
      out.push(e);
      if (e.type === 'table' && Array.isArray(e.trList)) {
        for (const tr of e.trList) for (const td of tr.tdList ?? []) walk(td.value as CEElement[] | undefined);
      }
      if (Array.isArray(e.valueList)) walk(e.valueList as CEElement[] | undefined);
    }
  };
  walk(els);
  return out;
}

describe('Sprint 361 — 註解 groupIds opt-in（Slice 1.A）', () => {
  it('fixture 真的有註解（sanity）', async () => {
    const doc = await parseFixture();
    expect(doc.comments.size).toBeGreaterThan(0);
  });

  it('預設（不開旗標）：保留 [註解 作者: 內容] inline 文字、無 groupIds、無 anchors', async () => {
    const doc = await parseFixture();
    const mapper = new ToCanvasEditor();
    const els = mapper.convert(doc);
    const all = allElements(els);

    const inlineMarker = all.filter((e) => typeof e.value === 'string' && e.value === '[' ).length;
    // 比較精準的偵測：把所有字串值串起來看有沒有 `[註解` 子字串
    const joined = all.map((e) => (typeof e.value === 'string' ? e.value : '')).join('');
    expect(joined).toContain('[註解');

    const withGroup = all.filter((e) => Array.isArray(e.groupIds) && e.groupIds.length > 0);
    expect(withGroup.length).toBe(0);

    expect(mapper.getCommentAnchors().length).toBe(0);
    // 邊界：inlineMarker 計數只是為了避免 lint 告警；真正斷言看 joined
    expect(inlineMarker).toBeGreaterThanOrEqual(0);
  });

  it('開旗標：無 inline [註解…] 文字、commented 段落 IElement 帶 groupIds、anchors 對齊', async () => {
    const doc = await parseFixture();
    const mapper = new ToCanvasEditor({ renderCommentsAsGroups: true });
    const els = mapper.convert(doc);
    const all = allElements(els);

    const joined = all.map((e) => (typeof e.value === 'string' ? e.value : '')).join('');
    expect(joined).not.toContain('[註解');

    const grouped = all.filter((e) => Array.isArray(e.groupIds) && e.groupIds.length > 0);
    expect(grouped.length).toBeGreaterThan(0);

    const anchors = mapper.getCommentAnchors();
    expect(anchors.length).toBeGreaterThan(0);

    // groupId 一致性：所有 groupIds 的字串都應出現在 anchors[].groupId
    const anchorIds = new Set(anchors.map((a) => a.groupId));
    for (const el of grouped) {
      for (const gid of el.groupIds ?? []) {
        expect(anchorIds.has(gid)).toBe(true);
      }
    }

    // anchor 至少有 author 欄位（可能為空字串、不是 undefined）
    for (const a of anchors) {
      expect(typeof a.author).toBe('string');
      expect(typeof a.body).toBe('string');
      expect(a.groupId).toBe(String(a.id));
    }
  });
});
