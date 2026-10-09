/**
 * Sprint 282 — Phase 1 optional bucket 第 1 項：`<w:ruby>` 注音/振假名 capture
 *
 * OOXML §17.3.3.25。Capture-only：parser 把 ruby 結構讀進 AST（含 annotationRuns
 * / baseRuns / RubyProps）；不 render / 不 writer round-trip（留 follow-up sprint）。
 *
 * 紀律 #21：與 Sprint 145-153 capture-only 9 連同模式。
 */
import { describe, expect, it } from 'vitest';
import { DOMParser } from '@xmldom/xmldom';

import { ParagraphParser } from '../../static/src/core/ooxml/document/ParagraphParser';
import type { RubyNode } from '../../static/src/core/ooxml/ast/types';

function parseParagraph(xml: string) {
  const wrapped = `<w:p xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">${xml}</w:p>`;
  const doc = new DOMParser().parseFromString(wrapped, 'application/xml');
  const pEl = doc.documentElement!;
  const parser = new ParagraphParser();
  return parser.parse(pEl);
}

function getRubyNodes(p: ReturnType<typeof parseParagraph>): RubyNode[] {
  return p.runs.filter((n): n is RubyNode => n.type === 'ruby');
}

describe('Sprint 282 — w:ruby capture', () => {
  it('基本 ruby：「漢字」(ㄏㄢˋㄗˋ) 注音、parser 讀出 annotation + base', () => {
    const xml = `
      <w:r>
        <w:ruby>
          <w:rubyPr>
            <w:rubyAlign w:val="distributeSpace"/>
            <w:hps w:val="14"/>
            <w:hpsRaise w:val="36"/>
            <w:hpsBaseText w:val="28"/>
            <w:lid w:val="zh-TW"/>
          </w:rubyPr>
          <w:rt>
            <w:r><w:t>ㄏㄢˋㄗˋ</w:t></w:r>
          </w:rt>
          <w:rubyBase>
            <w:r><w:t>漢字</w:t></w:r>
          </w:rubyBase>
        </w:ruby>
      </w:r>
    `;
    const p = parseParagraph(xml);
    const rubies = getRubyNodes(p);
    expect(rubies).toHaveLength(1);
    expect(rubies[0].annotationRuns).toHaveLength(1);
    expect(rubies[0].annotationRuns[0].text).toBe('ㄏㄢˋㄗˋ');
    expect(rubies[0].baseRuns).toHaveLength(1);
    expect(rubies[0].baseRuns[0].text).toBe('漢字');
    expect(rubies[0].props).toEqual({
      align: 'distributeSpace',
      hps: 14,
      hpsRaise: 36,
      hpsBaseText: 28,
      lid: 'zh-TW',
    });
  });

  it('日文振假名「漢字」(かんじ)、align=center', () => {
    const xml = `
      <w:r>
        <w:ruby>
          <w:rubyPr>
            <w:rubyAlign w:val="center"/>
            <w:hps w:val="10"/>
            <w:hpsBaseText w:val="20"/>
            <w:lid w:val="ja-JP"/>
          </w:rubyPr>
          <w:rt><w:r><w:t>かんじ</w:t></w:r></w:rt>
          <w:rubyBase><w:r><w:t>漢字</w:t></w:r></w:rubyBase>
        </w:ruby>
      </w:r>
    `;
    const p = parseParagraph(xml);
    const rubies = getRubyNodes(p);
    expect(rubies).toHaveLength(1);
    expect(rubies[0].annotationRuns[0].text).toBe('かんじ');
    expect(rubies[0].baseRuns[0].text).toBe('漢字');
    expect(rubies[0].props?.align).toBe('center');
    expect(rubies[0].props?.lid).toBe('ja-JP');
  });

  it('缺 rubyPr → props 為 undefined（不寫空 object）', () => {
    const xml = `
      <w:r>
        <w:ruby>
          <w:rt><w:r><w:t>a</w:t></w:r></w:rt>
          <w:rubyBase><w:r><w:t>A</w:t></w:r></w:rubyBase>
        </w:ruby>
      </w:r>
    `;
    const p = parseParagraph(xml);
    const rubies = getRubyNodes(p);
    expect(rubies).toHaveLength(1);
    expect(rubies[0].props).toBeUndefined();
    expect(rubies[0].annotationRuns[0].text).toBe('a');
    expect(rubies[0].baseRuns[0].text).toBe('A');
  });

  it('rt + rubyBase 皆空 → ruby node 不 emit（避免污染 AST）', () => {
    const xml = `
      <w:r>
        <w:ruby>
          <w:rubyPr><w:rubyAlign w:val="center"/></w:rubyPr>
        </w:ruby>
      </w:r>
    `;
    const p = parseParagraph(xml);
    expect(getRubyNodes(p)).toHaveLength(0);
  });

  it('rubyAlign 非法 val → align undefined（其他 props 仍解析）', () => {
    const xml = `
      <w:r>
        <w:ruby>
          <w:rubyPr>
            <w:rubyAlign w:val="invalidValue"/>
            <w:hps w:val="14"/>
          </w:rubyPr>
          <w:rt><w:r><w:t>a</w:t></w:r></w:rt>
          <w:rubyBase><w:r><w:t>A</w:t></w:r></w:rubyBase>
        </w:ruby>
      </w:r>
    `;
    const p = parseParagraph(xml);
    const r = getRubyNodes(p)[0];
    expect(r.props?.align).toBeUndefined();
    expect(r.props?.hps).toBe(14);
  });

  it('w:dirty val="1" → dirty=true；val="0" → dirty=false', () => {
    const xmlTrue = `
      <w:r><w:ruby>
        <w:rubyPr><w:dirty w:val="1"/></w:rubyPr>
        <w:rt><w:r><w:t>a</w:t></w:r></w:rt>
        <w:rubyBase><w:r><w:t>A</w:t></w:r></w:rubyBase>
      </w:ruby></w:r>
    `;
    expect(getRubyNodes(parseParagraph(xmlTrue))[0].props?.dirty).toBe(true);

    const xmlFalse = `
      <w:r><w:ruby>
        <w:rubyPr><w:dirty w:val="0"/></w:rubyPr>
        <w:rt><w:r><w:t>a</w:t></w:r></w:rt>
        <w:rubyBase><w:r><w:t>A</w:t></w:r></w:rubyBase>
      </w:ruby></w:r>
    `;
    expect(getRubyNodes(parseParagraph(xmlFalse))[0].props?.dirty).toBe(false);
  });

  it('Ruby 與 plain text 共存於同一 paragraph、順序保留', () => {
    const xml = `
      <w:r><w:t>start </w:t></w:r>
      <w:r>
        <w:ruby>
          <w:rubyPr><w:rubyAlign w:val="center"/></w:rubyPr>
          <w:rt><w:r><w:t>ㄈㄚˇ</w:t></w:r></w:rt>
          <w:rubyBase><w:r><w:t>法</w:t></w:r></w:rubyBase>
        </w:ruby>
      </w:r>
      <w:r><w:t> end</w:t></w:r>
    `;
    const p = parseParagraph(xml);
    expect(p.runs).toHaveLength(3);
    expect(p.runs[0].type).toBe('run');
    expect(p.runs[1].type).toBe('ruby');
    expect(p.runs[2].type).toBe('run');
    expect((p.runs[0] as { text: string }).text).toBe('start ');
    expect((p.runs[2] as { text: string }).text).toBe(' end');
  });

  it('多字 base + 連續注音（"漢字" 整體一個 ruby、不拆分）', () => {
    const xml = `
      <w:r>
        <w:ruby>
          <w:rubyPr><w:rubyAlign w:val="distributeSpace"/></w:rubyPr>
          <w:rt><w:r><w:t>ㄏㄢˋ</w:t></w:r><w:r><w:t>ㄗˋ</w:t></w:r></w:rt>
          <w:rubyBase><w:r><w:t>漢</w:t></w:r><w:r><w:t>字</w:t></w:r></w:rubyBase>
        </w:ruby>
      </w:r>
    `;
    const p = parseParagraph(xml);
    const r = getRubyNodes(p)[0];
    expect(r.annotationRuns).toHaveLength(2);
    expect(r.annotationRuns.map((x) => x.text).join('')).toBe('ㄏㄢˋㄗˋ');
    expect(r.baseRuns.map((x) => x.text).join('')).toBe('漢字');
  });
});
