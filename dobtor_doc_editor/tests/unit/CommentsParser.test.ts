/**
 * CommentsParser.test.ts — Sprint 176（Phase 5.5 註解、capture-only）
 *
 * 涵蓋：
 *   - `<w:comment>` id / author / date / initials + 內容段落
 *   - 多則註解
 *   - 缺 author/date/initials → 只掛 id + content
 *   - w:id 非數字 → 跳過
 *   - 無 comments.xml / 空 / XML 失敗 → 空 Map
 */

import { describe, expect, it } from 'vitest';
import { CommentsParser, commentToText } from '../../static/src/core/ooxml/comments/CommentsParser';

const NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"';

function wrap(inner: string): string {
  return `<?xml version="1.0" encoding="UTF-8"?>\n<w:comments ${NS}>${inner}</w:comments>`;
}

describe('CommentsParser — 基本解析', () => {
  it('單則註解 → id / author / date / initials + content', () => {
    const r = new CommentsParser().parse(wrap(
      '<w:comment w:id="0" w:author="Alice" w:date="2024-01-02T10:00:00Z" w:initials="A">' +
      '<w:p><w:r><w:t>這段需要修改</w:t></w:r></w:p></w:comment>',
    ));
    expect(r.size).toBe(1);
    const c = r.get(0)!;
    expect(c.id).toBe(0);
    expect(c.author).toBe('Alice');
    expect(c.date).toBe('2024-01-02T10:00:00Z');
    expect(c.initials).toBe('A');
    expect(c.content.length).toBe(1);
  });

  it('註解內容段落文字正確解析', () => {
    const r = new CommentsParser().parse(wrap(
      '<w:comment w:id="1" w:author="Bob"><w:p><w:r><w:t>請補充說明</w:t></w:r></w:p></w:comment>',
    ));
    const c = r.get(1)!;
    const para = c.content[0];
    expect(para.type).toBe('paragraph');
    if (para.type === 'paragraph') {
      const run = para.runs[0];
      expect(run.type === 'run' && run.text).toBe('請補充說明');
    }
  });

  it('多則註解 → Map 各 id', () => {
    const r = new CommentsParser().parse(wrap(
      '<w:comment w:id="0" w:author="A"><w:p><w:r><w:t>一</w:t></w:r></w:p></w:comment>' +
      '<w:comment w:id="1" w:author="B"><w:p><w:r><w:t>二</w:t></w:r></w:p></w:comment>',
    ));
    expect(r.size).toBe(2);
    expect(r.get(0)?.author).toBe('A');
    expect(r.get(1)?.author).toBe('B');
  });

  it('缺 author/date/initials → 只掛 id + content', () => {
    const r = new CommentsParser().parse(wrap(
      '<w:comment w:id="3"><w:p><w:r><w:t>x</w:t></w:r></w:p></w:comment>',
    ));
    const c = r.get(3)!;
    expect(c.id).toBe(3);
    expect(c.author).toBeUndefined();
    expect(c.date).toBeUndefined();
    expect(c.initials).toBeUndefined();
  });
});

describe('CommentsParser — 防禦邊界', () => {
  it('w:id 非數字 → 跳過', () => {
    const r = new CommentsParser().parse(wrap(
      '<w:comment w:id="abc" w:author="A"><w:p/></w:comment>',
    ));
    expect(r.size).toBe(0);
  });

  it('無 w:id → 跳過', () => {
    const r = new CommentsParser().parse(wrap('<w:comment w:author="A"><w:p/></w:comment>'));
    expect(r.size).toBe(0);
  });

  it('undefined / 空字串 → 空 Map', () => {
    expect(new CommentsParser().parse(undefined).size).toBe(0);
    expect(new CommentsParser().parse('').size).toBe(0);
  });

  it('XML 解析失敗 → 空 Map（不 throw）', () => {
    expect(new CommentsParser().parse('<w:comments <<<broken').size).toBe(0);
  });

  it('非 w:comment 子元素忽略', () => {
    const r = new CommentsParser().parse(wrap(
      '<w:other/><w:comment w:id="0" w:author="A"><w:p/></w:comment>',
    ));
    expect(r.size).toBe(1);
  });
});

describe('CommentsParser — Sprint 184 commentToText 純文字攤平', () => {
  const parse = (inner: string) => new CommentsParser().parse(wrap(inner));

  it('單段落註解 → 段落文字', () => {
    const c = parse('<w:comment w:id="0"><w:p><w:r><w:t>這段需要修改</w:t></w:r></w:p></w:comment>').get(0)!;
    expect(commentToText(c)).toBe('這段需要修改');
  });

  it('同段落多 run → 拼接', () => {
    const c = parse(
      '<w:comment w:id="0"><w:p><w:r><w:t>請</w:t></w:r><w:r><w:t>補充</w:t></w:r></w:p></w:comment>',
    ).get(0)!;
    expect(commentToText(c)).toBe('請補充');
  });

  it('多段落 → 以空白串接', () => {
    const c = parse(
      '<w:comment w:id="0">' +
      '<w:p><w:r><w:t>第一段</w:t></w:r></w:p>' +
      '<w:p><w:r><w:t>第二段</w:t></w:r></w:p></w:comment>',
    ).get(0)!;
    expect(commentToText(c)).toBe('第一段 第二段');
  });

  it('註解內表格 → 遞迴 cell 文字', () => {
    const c = parse(
      '<w:comment w:id="0"><w:tbl>' +
      '<w:tr><w:tc><w:p><w:r><w:t>格一</w:t></w:r></w:p></w:tc>' +
      '<w:tc><w:p><w:r><w:t>格二</w:t></w:r></w:p></w:tc></w:tr>' +
      '</w:tbl></w:comment>',
    ).get(0)!;
    expect(commentToText(c)).toBe('格一 格二');
  });

  it('空註解內容 → 空字串', () => {
    const c = parse('<w:comment w:id="0"><w:p/></w:comment>').get(0)!;
    expect(commentToText(c)).toBe('');
  });
});
