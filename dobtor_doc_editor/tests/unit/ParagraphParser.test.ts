/**
 * ParagraphParser 單元測試 (Sprint 1 issues #4 #5 #6)
 *
 * 用手寫 <w:p> XML 驗證解析輸出對應到 ast/types.ts 的型別。
 * 不依賴 fixture .docx — 純 OOXML 行為單元測試。
 */

import { describe, expect, it } from 'vitest';
import { ParagraphParser } from '../../static/src/core/ooxml/document/ParagraphParser';

const W_NS_DECL = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"';

function parsePXml(innerPXml: string): Element {
  const xml = `<?xml version="1.0"?><w:p ${W_NS_DECL}>${innerPXml}</w:p>`;
  const doc = new DOMParser().parseFromString(xml, 'application/xml');
  return doc.documentElement;
}

const parser = new ParagraphParser();

describe('ParagraphParser — w:r / w:t', () => {
  it('純文字段落，單一 run', () => {
    const p = parsePXml('<w:r><w:t>Hello, 世界</w:t></w:r>');
    const node = parser.parse(p);

    expect(node.type).toBe('paragraph');
    expect(node.runs).toHaveLength(1);
    expect(node.runs[0]).toMatchObject({ type: 'run', text: 'Hello, 世界' });
    expect(node.props).toEqual({});
  });

  it('多個 run 順序保留', () => {
    const p = parsePXml(
      '<w:r><w:t>A</w:t></w:r><w:r><w:t>B</w:t></w:r><w:r><w:t>C</w:t></w:r>',
    );
    const node = parser.parse(p);
    expect(node.runs.map((r) => (r.type === 'run' ? r.text : null))).toEqual([
      'A',
      'B',
      'C',
    ]);
  });

  it('w:t xml:space="preserve" 保留前後空白', () => {
    const p = parsePXml('<w:r><w:t xml:space="preserve">  spaced  </w:t></w:r>');
    const node = parser.parse(p);
    expect(node.runs[0]).toMatchObject({ type: 'run', text: '  spaced  ' });
  });
});

describe('ParagraphParser — w:rPr', () => {
  it('粗體 / 斜體 / 顏色 / 字級', () => {
    const p = parsePXml(`
      <w:r>
        <w:rPr>
          <w:b/>
          <w:i/>
          <w:color w:val="FF0000"/>
          <w:sz w:val="28"/>
        </w:rPr>
        <w:t>X</w:t>
      </w:r>
    `);
    const node = parser.parse(p);
    expect(node.runs[0]).toMatchObject({
      type: 'run',
      text: 'X',
      props: { bold: true, italic: true, color: 'FF0000', fontSize: 14 },
    });
  });

  it('w:b val="0" 為 false（停用粗體）', () => {
    const p = parsePXml('<w:r><w:rPr><w:b w:val="0"/></w:rPr><w:t>A</w:t></w:r>');
    const node = parser.parse(p);
    if (node.runs[0].type !== 'run') throw new Error('expected run');
    expect(node.runs[0].props.bold).toBeUndefined();
  });

  it('CJK 字型 (eastAsia)', () => {
    const p = parsePXml(`
      <w:r>
        <w:rPr><w:rFonts w:ascii="Calibri" w:eastAsia="新細明體"/></w:rPr>
        <w:t>中文</w:t>
      </w:r>
    `);
    const node = parser.parse(p);
    if (node.runs[0].type !== 'run') throw new Error('expected run');
    expect(node.runs[0].props).toMatchObject({
      fontFamily: 'Calibri',
      fontFamilyEastAsia: '新細明體',
    });
  });

  it('底線、刪除線、上下標', () => {
    const p = parsePXml(`
      <w:r>
        <w:rPr>
          <w:u w:val="single"/>
          <w:strike/>
          <w:vertAlign w:val="superscript"/>
        </w:rPr>
        <w:t>x</w:t>
      </w:r>
    `);
    const node = parser.parse(p);
    if (node.runs[0].type !== 'run') throw new Error('expected run');
    expect(node.runs[0].props).toMatchObject({
      underline: 'single',
      strike: true,
      vertAlign: 'superscript',
    });
  });
});

describe('ParagraphParser — w:pPr', () => {
  it('置中對齊 + style ID', () => {
    const p = parsePXml(`
      <w:pPr>
        <w:pStyle w:val="Title"/>
        <w:jc w:val="center"/>
      </w:pPr>
      <w:r><w:t>Title</w:t></w:r>
    `);
    const node = parser.parse(p);
    expect(node.props.alignment).toBe('center');
    expect(node.styleId).toBe('Title');
  });

  it('jc both → justify', () => {
    const p = parsePXml('<w:pPr><w:jc w:val="both"/></w:pPr>');
    const node = parser.parse(p);
    expect(node.props.alignment).toBe('justify');
  });

  it('縮排（twip → pt）', () => {
    // 720 twip = 36 pt = 0.5 inch
    const p = parsePXml(
      '<w:pPr><w:ind w:left="720" w:firstLine="240"/></w:pPr>',
    );
    const node = parser.parse(p);
    expect(node.props.indent).toEqual({ left: 36, firstLine: 12 });
  });

  it('段落間距 + 行距 (atLeast 規則)', () => {
    const p = parsePXml(`
      <w:pPr>
        <w:spacing w:before="120" w:after="60" w:line="480" w:lineRule="atLeast"/>
      </w:pPr>
    `);
    const node = parser.parse(p);
    expect(node.props.spacing).toEqual({
      before: 6, // 120 twip = 6 pt
      after: 3,
      line: { rule: 'atLeast', value: 24 }, // 480 twip = 24 pt
    });
  });

  it('行距 auto 用 240 分母', () => {
    // line=360 + auto → 1.5 倍行距
    const p = parsePXml(
      '<w:pPr><w:spacing w:line="360" w:lineRule="auto"/></w:pPr>',
    );
    const node = parser.parse(p);
    expect(node.props.spacing?.line).toEqual({ rule: 'auto', value: 1.5 });
  });

  it('numbering numId + ilvl', () => {
    const p = parsePXml(`
      <w:pPr><w:numPr><w:ilvl w:val="1"/><w:numId w:val="3"/></w:numPr></w:pPr>
    `);
    const node = parser.parse(p);
    expect(node.props.numId).toBe(3);
    expect(node.props.ilvl).toBe(1);
  });

  it('keepNext + pageBreakBefore 旗標', () => {
    const p = parsePXml('<w:pPr><w:keepNext/><w:pageBreakBefore/></w:pPr>');
    const node = parser.parse(p);
    expect(node.props.keepNext).toBe(true);
    expect(node.props.pageBreakBefore).toBe(true);
  });
});

describe('ParagraphParser — inline elements', () => {
  it('w:br type="line" → BreakNode (line)', () => {
    const p = parsePXml(
      '<w:r><w:t>A</w:t><w:br/><w:t>B</w:t></w:r>',
    );
    const node = parser.parse(p);
    expect(node.runs).toHaveLength(3);
    expect(node.runs[1]).toMatchObject({ type: 'break', breakType: 'line' });
  });

  it('w:br type="page" → BreakNode (page)', () => {
    const p = parsePXml('<w:r><w:br w:type="page"/></w:r>');
    const node = parser.parse(p);
    expect(node.runs[0]).toMatchObject({ type: 'break', breakType: 'page' });
  });

  it('w:tab 轉為 \\t', () => {
    const p = parsePXml('<w:r><w:t>A</w:t><w:tab/><w:t>B</w:t></w:r>');
    const node = parser.parse(p);
    expect(node.runs).toHaveLength(1);
    expect(node.runs[0]).toMatchObject({ type: 'run', text: 'A\tB' });
  });

  it('w:fldSimple PAGE 含快取值', () => {
    const p = parsePXml(`
      <w:fldSimple w:instr=" PAGE ">
        <w:r><w:t>3</w:t></w:r>
      </w:fldSimple>
    `);
    const node = parser.parse(p);
    expect(node.runs[0]).toMatchObject({
      type: 'field',
      fieldType: 'PAGE',
      cachedValue: '3',
    });
  });

  it('w:fldSimple unknown instruction 標為 unknown', () => {
    // Sprint 123 前：SEQ 被標為 unknown；現已升為已知集合（見下方 Sprint 123 測試）
    const p = parsePXml('<w:fldSimple w:instr=" XYZGIBBERISH foo bar "/>');
    const node = parser.parse(p);
    expect(node.runs[0]).toMatchObject({ type: 'field', fieldType: 'unknown' });
  });

  it('w:hyperlink 內 run 展平到段落層', () => {
    const p = parsePXml(`
      <w:hyperlink>
        <w:r><w:t>click</w:t></w:r>
        <w:r><w:t> here</w:t></w:r>
      </w:hyperlink>
    `);
    const node = parser.parse(p);
    expect(node.runs).toHaveLength(2);
    expect(node.runs[0]).toMatchObject({ type: 'run', text: 'click' });
    expect(node.runs[1]).toMatchObject({ type: 'run', text: ' here' });
  });
});

describe('ParagraphParser — 邊界情況', () => {
  it('空 <w:p/> 段落 → runs=[], props={}', () => {
    const p = parsePXml('');
    const node = parser.parse(p);
    expect(node.type).toBe('paragraph');
    expect(node.runs).toEqual([]);
    expect(node.props).toEqual({});
    expect(node.styleId).toBeUndefined();
  });

  it('w:r 只有 w:rPr 沒有文字內容 → 不產生 RunNode', () => {
    const p = parsePXml('<w:r><w:rPr><w:b/></w:rPr></w:r>');
    const node = parser.parse(p);
    expect(node.runs).toEqual([]);
  });

  it('未知子節點靜默忽略，不丟例外', () => {
    const p = parsePXml(`
      <w:bookmarkStart w:id="0" w:name="x"/>
      <w:proofErr w:type="spellStart"/>
      <w:r><w:t>OK</w:t></w:r>
    `);
    const node = parser.parse(p);
    expect(node.runs).toHaveLength(1);
    expect(node.runs[0]).toMatchObject({ type: 'run', text: 'OK' });
  });
});

// ─── Sprint 122：OLE / VML pict 降級 placeholder ─────────────────────────────
describe('ParagraphParser — Sprint 122 OLE / pict fallback', () => {
  const O_NS_DECL = 'xmlns:o="urn:schemas-microsoft-com:office:office"';
  const V_NS_DECL = 'xmlns:v="urn:schemas-microsoft-com:vml"';
  const R_NS_DECL = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"';

  function parsePXmlNs(innerPXml: string): Element {
    const xml = `<?xml version="1.0"?><w:p ${W_NS_DECL} ${O_NS_DECL} ${V_NS_DECL} ${R_NS_DECL}>${innerPXml}</w:p>`;
    const doc = new DOMParser().parseFromString(xml, 'application/xml');
    return doc.documentElement;
  }

  it('w:object 帶 ProgID → italic 文字 placeholder「[嵌入物件: <ProgID>]」', () => {
    const p = parsePXmlNs(`
      <w:r>
        <w:object>
          <v:shape id="_x0000_i1025" type="#_x0000_t75"/>
          <o:OLEObject Type="Embed" ProgID="Equation.3" ShapeID="_x0000_i1025" DrawAspect="Content" ObjectID="_1234567" r:id="rId4"/>
        </w:object>
      </w:r>
    `);
    const node = parser.parse(p);
    expect(node.runs).toHaveLength(1);
    expect(node.runs[0]).toMatchObject({
      type: 'run',
      text: '[嵌入物件: Equation.3]',
      props: { italic: true },
    });
  });

  it('w:object 帶 ProgID + v:shape alt → 兩者組合', () => {
    const p = parsePXmlNs(`
      <w:r>
        <w:object>
          <v:shape id="s1" alt="二元二次方程式"/>
          <o:OLEObject ProgID="Equation.3" r:id="rId5"/>
        </w:object>
      </w:r>
    `);
    const node = parser.parse(p);
    expect(node.runs).toHaveLength(1);
    expect(node.runs[0]).toMatchObject({
      type: 'run',
      text: '[嵌入物件: Equation.3 — 二元二次方程式]',
      props: { italic: true },
    });
  });

  it('w:object 完全沒 ProgID / alt → 純「[嵌入物件]」placeholder', () => {
    const p = parsePXmlNs(`
      <w:r>
        <w:object>
          <v:shape id="s2"/>
        </w:object>
      </w:r>
    `);
    const node = parser.parse(p);
    expect(node.runs).toHaveLength(1);
    expect(node.runs[0]).toMatchObject({ type: 'run', text: '[嵌入物件]' });
  });

  it('w:pict 純 VML 圖（無 OLEObject）→「[圖片(VML)]」', () => {
    const p = parsePXmlNs(`
      <w:r>
        <w:pict>
          <v:shape id="img1"/>
        </w:pict>
      </w:r>
    `);
    const node = parser.parse(p);
    expect(node.runs).toHaveLength(1);
    expect(node.runs[0]).toMatchObject({ type: 'run', text: '[圖片(VML)]' });
  });

  it('w:pict 純 VML 帶 alt → 加 alt 補充', () => {
    const p = parsePXmlNs(`
      <w:r>
        <w:pict>
          <v:shape id="img2" alt="logo"/>
        </w:pict>
      </w:r>
    `);
    const node = parser.parse(p);
    expect(node.runs).toHaveLength(1);
    expect(node.runs[0]).toMatchObject({ type: 'run', text: '[圖片(VML): logo]' });
  });

  it('w:pict 內含 OLEObject → 走 OLE 文案（不是 VML 文案）', () => {
    const p = parsePXmlNs(`
      <w:r>
        <w:pict>
          <v:shape id="ole-pict" alt="圖象 OLE"/>
          <o:OLEObject ProgID="Excel.Sheet.12" r:id="rId6"/>
        </w:pict>
      </w:r>
    `);
    const node = parser.parse(p);
    expect(node.runs).toHaveLength(1);
    expect(node.runs[0]).toMatchObject({
      type: 'run',
      text: '[嵌入物件: Excel.Sheet.12 — 圖象 OLE]',
    });
  });

  it('w:object 與 w:t 文字並存 → text run + placeholder run 分離輸出', () => {
    const p = parsePXmlNs(`
      <w:r>
        <w:t>公式：</w:t>
        <w:object>
          <o:OLEObject ProgID="Equation.3" r:id="rId7"/>
        </w:object>
        <w:t>，結束</w:t>
      </w:r>
    `);
    const node = parser.parse(p);
    // text run 1 / OLE placeholder / text run 2
    expect(node.runs).toHaveLength(3);
    expect(node.runs[0]).toMatchObject({ type: 'run', text: '公式：' });
    expect(node.runs[1]).toMatchObject({ type: 'run', text: '[嵌入物件: Equation.3]' });
    expect(node.runs[2]).toMatchObject({ type: 'run', text: '，結束' });
  });

  it('w:object placeholder 繼承 baseProps（rPr bold）+ italic overlay', () => {
    // baseProps 的 italic 會被 placeholder overlay 為 true（不管原本如何）
    const p = parsePXmlNs(`
      <w:r>
        <w:rPr><w:b/></w:rPr>
        <w:object>
          <o:OLEObject ProgID="Equation.3" r:id="rId8"/>
        </w:object>
      </w:r>
    `);
    const node = parser.parse(p);
    expect(node.runs).toHaveLength(1);
    expect(node.runs[0].type).toBe('run');
    const run = node.runs[0] as { type: 'run'; props: { bold?: boolean; italic?: boolean } };
    expect(run.props.bold).toBe(true);
    expect(run.props.italic).toBe(true);
  });
});

// ─── Sprint 123：field code 完整覆蓋（PAGE / DATE / SEQ / TOC / 複式 fldChar）──
describe('ParagraphParser — Sprint 123 field codes', () => {
  it('w:fldSimple SEQ 被分類為 SEQ（不是 unknown）', () => {
    const p = parsePXml('<w:fldSimple w:instr=" SEQ Figure \\* ARABIC "><w:r><w:t>3</w:t></w:r></w:fldSimple>');
    const node = parser.parse(p);
    expect(node.runs).toHaveLength(1);
    expect(node.runs[0]).toMatchObject({
      type: 'field',
      fieldType: 'SEQ',
      cachedValue: '3',
    });
  });

  it('w:fldSimple TOC 分類', () => {
    const p = parsePXml('<w:fldSimple w:instr=" TOC \\o &quot;1-3&quot; \\h \\z "/>');
    const node = parser.parse(p);
    expect(node.runs).toHaveLength(1);
    expect(node.runs[0]).toMatchObject({ type: 'field', fieldType: 'TOC' });
  });

  it('w:fldSimple REF / HYPERLINK / STYLEREF 分類', () => {
    // 注意：instruction 內含 " 必須在 XML 屬性中以 &quot; 表達
    const cases = [
      [' REF _Ref12345 \\h ', 'REF'],
      [' HYPERLINK &quot;http://example.com&quot; ', 'HYPERLINK'],
      [' STYLEREF &quot;Heading 1&quot; \\l ', 'STYLEREF'],
    ] as const;
    for (const [instr, expected] of cases) {
      const p = parsePXml(`<w:fldSimple w:instr="${instr}"/>`);
      const node = parser.parse(p);
      expect(node.runs[0]).toMatchObject({ type: 'field', fieldType: expected });
    }
  });

  it('複式 fldChar PAGE 跨 5 個 w:r 收集為單一 FieldNode', () => {
    // 標準 OOXML §17.16.1.7 複式 field：begin → instrText → separate → cachedValue → end
    const p = parsePXml(`
      <w:r><w:fldChar w:fldCharType="begin"/></w:r>
      <w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>
      <w:r><w:fldChar w:fldCharType="separate"/></w:r>
      <w:r><w:t>7</w:t></w:r>
      <w:r><w:fldChar w:fldCharType="end"/></w:r>
    `);
    const node = parser.parse(p);
    expect(node.runs).toHaveLength(1);
    expect(node.runs[0]).toMatchObject({
      type: 'field',
      fieldType: 'PAGE',
      cachedValue: '7',
    });
    // 注意：instruction trim 過、可能是 'PAGE' 或保留 spacing
    const fieldNode = node.runs[0] as { type: 'field'; instruction: string };
    expect(fieldNode.instruction).toBe('PAGE');
  });

  it('複式 fldChar instrText 跨多 w:r 串接（OOXML 規格允許）', () => {
    // Word 偶會把 long instruction 切多個 instrText
    const p = parsePXml(`
      <w:r><w:fldChar w:fldCharType="begin"/></w:r>
      <w:r><w:instrText xml:space="preserve"> SEQ </w:instrText></w:r>
      <w:r><w:instrText xml:space="preserve">Table </w:instrText></w:r>
      <w:r><w:instrText xml:space="preserve">\\* ARABIC </w:instrText></w:r>
      <w:r><w:fldChar w:fldCharType="separate"/></w:r>
      <w:r><w:t>2</w:t></w:r>
      <w:r><w:fldChar w:fldCharType="end"/></w:r>
    `);
    const node = parser.parse(p);
    expect(node.runs).toHaveLength(1);
    expect(node.runs[0]).toMatchObject({
      type: 'field',
      fieldType: 'SEQ',
      cachedValue: '2',
    });
    const fieldNode = node.runs[0] as { type: 'field'; instruction: string };
    expect(fieldNode.instruction).toContain('SEQ');
    expect(fieldNode.instruction).toContain('Table');
  });

  it('複式 fldChar 無 cachedValue（separate 後立刻 end）', () => {
    const p = parsePXml(`
      <w:r><w:fldChar w:fldCharType="begin"/></w:r>
      <w:r><w:instrText> NUMPAGES </w:instrText></w:r>
      <w:r><w:fldChar w:fldCharType="separate"/></w:r>
      <w:r><w:fldChar w:fldCharType="end"/></w:r>
    `);
    const node = parser.parse(p);
    expect(node.runs).toHaveLength(1);
    expect(node.runs[0]).toMatchObject({ type: 'field', fieldType: 'NUMPAGES' });
    // 沒 cachedValue → 該 key 不存在
    expect((node.runs[0] as Record<string, unknown>).cachedValue).toBeUndefined();
  });

  it('複式 fldChar 段落結尾未閉合（malformed） → emit 已收集部分為 unknown', () => {
    // begin 後 instrText、但沒 end — 段落結束時應 emit
    const p = parsePXml(`
      <w:r><w:fldChar w:fldCharType="begin"/></w:r>
      <w:r><w:instrText> PAGE </w:instrText></w:r>
    `);
    const node = parser.parse(p);
    expect(node.runs).toHaveLength(1);
    expect(node.runs[0]).toMatchObject({ type: 'field', fieldType: 'PAGE' });
  });

  it('複式 fldChar 與普通文字並存（field 前後有 plain run）', () => {
    const p = parsePXml(`
      <w:r><w:t>Page </w:t></w:r>
      <w:r><w:fldChar w:fldCharType="begin"/></w:r>
      <w:r><w:instrText> PAGE </w:instrText></w:r>
      <w:r><w:fldChar w:fldCharType="separate"/></w:r>
      <w:r><w:t>3</w:t></w:r>
      <w:r><w:fldChar w:fldCharType="end"/></w:r>
      <w:r><w:t> of </w:t></w:r>
      <w:r><w:fldChar w:fldCharType="begin"/></w:r>
      <w:r><w:instrText> NUMPAGES </w:instrText></w:r>
      <w:r><w:fldChar w:fldCharType="separate"/></w:r>
      <w:r><w:t>10</w:t></w:r>
      <w:r><w:fldChar w:fldCharType="end"/></w:r>
    `);
    const node = parser.parse(p);
    // run "Page " / field PAGE / run " of " / field NUMPAGES
    expect(node.runs).toHaveLength(4);
    expect(node.runs[0]).toMatchObject({ type: 'run', text: 'Page ' });
    expect(node.runs[1]).toMatchObject({ type: 'field', fieldType: 'PAGE', cachedValue: '3' });
    expect(node.runs[2]).toMatchObject({ type: 'run', text: ' of ' });
    expect(node.runs[3]).toMatchObject({ type: 'field', fieldType: 'NUMPAGES', cachedValue: '10' });
  });

  it('複式 fldChar TOC instruction 含換行 / 多空白 trim 正常', () => {
    const p = parsePXml(`
      <w:r><w:fldChar w:fldCharType="begin"/></w:r>
      <w:r><w:instrText>  TOC \\o "1-3" \\h \\z  </w:instrText></w:r>
      <w:r><w:fldChar w:fldCharType="separate"/></w:r>
      <w:r><w:t>目錄占位</w:t></w:r>
      <w:r><w:fldChar w:fldCharType="end"/></w:r>
    `);
    const node = parser.parse(p);
    expect(node.runs).toHaveLength(1);
    expect(node.runs[0]).toMatchObject({
      type: 'field',
      fieldType: 'TOC',
      cachedValue: '目錄占位',
    });
  });
});

// ─── Sprint 125：bookmark range 完整覆蓋 ─────────────────────────────────────
describe('ParagraphParser — Sprint 125 bookmark range', () => {
  it('段落內單一 bookmark（直屬 w:p 層級）→ paragraph.bookmarks=[name]', () => {
    const p = parsePXml(`
      <w:bookmarkStart w:id="0" w:name="ch1"/>
      <w:r><w:t>Chapter 1</w:t></w:r>
      <w:bookmarkEnd w:id="0"/>
    `);
    const node = parser.parse(p);
    expect(node.bookmarks).toEqual(['ch1']);
    expect(node.runs).toHaveLength(1);
    expect(node.runs[0]).toMatchObject({ type: 'run', text: 'Chapter 1' });
  });

  it('w:r 內嵌 bookmarkStart → 仍被段落層 capture', () => {
    // 真實 Word docx：bookmark 偶會被放在 w:r 內部（w:rPr 旁）
    const p = parsePXml(`
      <w:r>
        <w:bookmarkStart w:id="1" w:name="inline_bm"/>
        <w:t>inline anchor here</w:t>
        <w:bookmarkEnd w:id="1"/>
      </w:r>
    `);
    const node = parser.parse(p);
    expect(node.bookmarks).toEqual(['inline_bm']);
    expect(node.runs[0]).toMatchObject({ text: 'inline anchor here' });
  });

  it('多個 bookmark 都被收集、去重', () => {
    const p = parsePXml(`
      <w:bookmarkStart w:id="0" w:name="a"/>
      <w:bookmarkStart w:id="1" w:name="b"/>
      <w:r><w:t>two anchors</w:t></w:r>
      <w:bookmarkEnd w:id="0"/>
      <w:bookmarkEnd w:id="1"/>
      <w:bookmarkStart w:id="2" w:name="a"/>
      <w:bookmarkEnd w:id="2"/>
    `);
    const node = parser.parse(p);
    // 去重後 ['a', 'b']
    expect(node.bookmarks).toEqual(['a', 'b']);
  });

  it('沒 bookmark 的段落 → bookmarks key 不存在（避免 AST diff noise）', () => {
    const p = parsePXml('<w:r><w:t>plain</w:t></w:r>');
    const node = parser.parse(p);
    expect(node.bookmarks).toBeUndefined();
  });

  it('Word 自動生成的 _GoBack 也被捕捉（fixture 真實 case）', () => {
    // 42 fixture 內 20 個 bookmark 全是 _GoBack；本 test 鎖定不丟此 case
    const p = parsePXml(`
      <w:r><w:t>some text</w:t></w:r>
      <w:bookmarkStart w:id="0" w:name="_GoBack"/>
      <w:bookmarkEnd w:id="0"/>
    `);
    const node = parser.parse(p);
    expect(node.bookmarks).toEqual(['_GoBack']);
  });

  it('bookmark 名稱缺失（malformed）→ 不收集、不 throw', () => {
    // ECMA-376 spec name 必填；現實 docx 偶有 attr missing
    const p = parsePXml(`
      <w:bookmarkStart w:id="0"/>
      <w:r><w:t>no name bookmark</w:t></w:r>
      <w:bookmarkEnd w:id="0"/>
    `);
    const node = parser.parse(p);
    expect(node.bookmarks).toBeUndefined();
    expect(node.runs[0]).toMatchObject({ text: 'no name bookmark' });
  });

  it('hyperlink 內 w:r 含 bookmarkStart → 段落層也 capture', () => {
    const p = parsePXml(`
      <w:hyperlink w:anchor="external">
        <w:r>
          <w:bookmarkStart w:id="0" w:name="hl_inner"/>
          <w:t>link text</w:t>
          <w:bookmarkEnd w:id="0"/>
        </w:r>
      </w:hyperlink>
    `);
    const node = parser.parse(p);
    expect(node.bookmarks).toEqual(['hl_inner']);
    // hyperlink 內 run 仍保留
    expect(node.runs[0]).toMatchObject({ type: 'run', text: 'link text' });
  });

  it('bookmark 與 field 共存 → 兩者都 capture', () => {
    const p = parsePXml(`
      <w:bookmarkStart w:id="0" w:name="ref_target"/>
      <w:r><w:fldChar w:fldCharType="begin"/></w:r>
      <w:r><w:instrText> PAGE </w:instrText></w:r>
      <w:r><w:fldChar w:fldCharType="separate"/></w:r>
      <w:r><w:t>3</w:t></w:r>
      <w:r><w:fldChar w:fldCharType="end"/></w:r>
      <w:bookmarkEnd w:id="0"/>
    `);
    const node = parser.parse(p);
    expect(node.bookmarks).toEqual(['ref_target']);
    expect(node.runs).toHaveLength(1);
    expect(node.runs[0]).toMatchObject({ type: 'field', fieldType: 'PAGE', cachedValue: '3' });
  });
});

// ── Sprint 133：w:pBdr (段落邊框) + w:shd (段落底色) ────────────────────────

describe('ParagraphParser — Sprint 133 pBdr + shd', () => {
  it('w:pBdr 完整 4 邊 → props.borders 含四邊 BorderDef', () => {
    const p = parsePXml(`
      <w:pPr>
        <w:pBdr>
          <w:top w:val="single" w:sz="4" w:space="1" w:color="000000"/>
          <w:bottom w:val="single" w:sz="4" w:space="1" w:color="000000"/>
          <w:left w:val="single" w:sz="4" w:space="4" w:color="auto"/>
          <w:right w:val="single" w:sz="4" w:space="4" w:color="auto"/>
        </w:pBdr>
      </w:pPr>
      <w:r><w:t>bordered</w:t></w:r>
    `);
    const node = parser.parse(p);
    expect(node.props.borders?.top).toMatchObject({ style: 'single', width: 0.5, color: '000000' });
    expect(node.props.borders?.bottom?.style).toBe('single');
    expect(node.props.borders?.left?.color).toBe('auto');
    expect(node.props.borders?.right?.space).toBe(4);
  });

  it('w:pBdr 部分邊（只 top）→ props.borders 只含 top key', () => {
    const p = parsePXml(`
      <w:pPr>
        <w:pBdr>
          <w:top w:val="double" w:sz="16" w:color="FF0000"/>
        </w:pBdr>
      </w:pPr>
    `);
    const node = parser.parse(p);
    expect(node.props.borders?.top).toMatchObject({ style: 'double', color: 'FF0000' });
    expect(node.props.borders?.top?.width).toBeCloseTo(2.0, 2); // 16/8 = 2pt
    expect(node.props.borders?.bottom).toBeUndefined();
    expect(node.props.borders?.left).toBeUndefined();
    expect(node.props.borders?.right).toBeUndefined();
  });

  it('w:pBdr 全空（無子邊）→ props.borders 不掛 key（紀律 #21）', () => {
    const p = parsePXml(`
      <w:pPr>
        <w:pBdr></w:pBdr>
      </w:pPr>
    `);
    const node = parser.parse(p);
    expect(node.props.borders).toBeUndefined();
  });

  it('w:pBdr 子邊缺 w:val → 該邊 silent drop（無效邊）', () => {
    const p = parsePXml(`
      <w:pPr>
        <w:pBdr>
          <w:top w:sz="4" w:color="000000"/>
          <w:bottom w:val="single" w:sz="4" w:color="000000"/>
        </w:pBdr>
      </w:pPr>
    `);
    const node = parser.parse(p);
    expect(node.props.borders?.top).toBeUndefined();
    expect(node.props.borders?.bottom?.style).toBe('single');
  });

  it('w:pBdr w:start / w:end 別名對應 left / right（OOXML logical direction）', () => {
    const p = parsePXml(`
      <w:pPr>
        <w:pBdr>
          <w:start w:val="dotted" w:sz="8" w:color="00FF00"/>
          <w:end w:val="dashed" w:sz="8" w:color="0000FF"/>
        </w:pBdr>
      </w:pPr>
    `);
    const node = parser.parse(p);
    expect(node.props.borders?.left?.style).toBe('dotted');
    expect(node.props.borders?.left?.color).toBe('00FF00');
    expect(node.props.borders?.right?.style).toBe('dashed');
    expect(node.props.borders?.right?.color).toBe('0000FF');
  });

  it('w:pBdr 含 w:between / w:bar（defer）→ silent drop、不影響其他邊', () => {
    const p = parsePXml(`
      <w:pPr>
        <w:pBdr>
          <w:top w:val="single" w:sz="4" w:color="000000"/>
          <w:between w:val="single" w:sz="4" w:color="000000"/>
          <w:bar w:val="single" w:sz="4" w:color="000000"/>
        </w:pBdr>
      </w:pPr>
    `);
    const node = parser.parse(p);
    expect(node.props.borders?.top?.style).toBe('single');
    // between / bar 不掛在 borders 4 邊 (defer to future)
    expect(Object.keys(node.props.borders ?? {})).toEqual(['top']);
  });

  it('w:shd 完整 → props.shading 含 fill + color + pattern', () => {
    const p = parsePXml(`
      <w:pPr>
        <w:shd w:val="clear" w:fill="DEEAF6" w:color="auto"/>
      </w:pPr>
      <w:r><w:t>shaded</w:t></w:r>
    `);
    const node = parser.parse(p);
    expect(node.props.shading).toMatchObject({
      fill: 'DEEAF6',
      color: 'auto',
      pattern: 'clear',
    });
  });

  it('w:shd 只有 fill → 其他 key 不掛', () => {
    const p = parsePXml(`
      <w:pPr>
        <w:shd w:fill="FFFF00"/>
      </w:pPr>
    `);
    const node = parser.parse(p);
    expect(node.props.shading?.fill).toBe('FFFF00');
    expect(node.props.shading?.color).toBeUndefined();
    expect(node.props.shading?.pattern).toBeUndefined();
  });

  it('w:shd 全空（無屬性）→ props.shading 不掛 key（紀律 #21）', () => {
    const p = parsePXml(`
      <w:pPr>
        <w:shd/>
      </w:pPr>
    `);
    const node = parser.parse(p);
    expect(node.props.shading).toBeUndefined();
  });

  it('pBdr + shd 同時存在 → 互不干擾', () => {
    const p = parsePXml(`
      <w:pPr>
        <w:pBdr>
          <w:top w:val="single" w:sz="4" w:color="000000"/>
        </w:pBdr>
        <w:shd w:val="clear" w:fill="DEEAF6"/>
      </w:pPr>
      <w:r><w:t>boxed + shaded</w:t></w:r>
    `);
    const node = parser.parse(p);
    expect(node.props.borders?.top?.style).toBe('single');
    expect(node.props.shading?.fill).toBe('DEEAF6');
  });

  it('普通段落（無 pBdr / shd）→ borders / shading 都不掛 key', () => {
    const p = parsePXml('<w:r><w:t>normal</w:t></w:r>');
    const node = parser.parse(p);
    expect(node.props.borders).toBeUndefined();
    expect(node.props.shading).toBeUndefined();
  });
});

// ── Sprint 134：w:textAlignment + w:framePr ─────────────────────────────────

describe('ParagraphParser — Sprint 134 textAlignment', () => {
  it.each([
    ['auto', 'auto'],
    ['top', 'top'],
    ['center', 'center'],
    ['baseline', 'baseline'],
    ['bottom', 'bottom'],
  ] as const)('w:textAlignment="%s" → props.textAlignment="%s"', (raw, expected) => {
    const p = parsePXml(`
      <w:pPr><w:textAlignment w:val="${raw}"/></w:pPr>
      <w:r><w:t>x</w:t></w:r>
    `);
    const node = parser.parse(p);
    expect(node.props.textAlignment).toBe(expected);
  });

  it('w:textAlignment 無效值（如 "garbage"）→ silent drop、不掛 key', () => {
    const p = parsePXml(`
      <w:pPr><w:textAlignment w:val="garbage"/></w:pPr>
    `);
    const node = parser.parse(p);
    expect(node.props.textAlignment).toBeUndefined();
  });

  it('w:textAlignment 缺 w:val → silent drop', () => {
    const p = parsePXml(`<w:pPr><w:textAlignment/></w:pPr>`);
    const node = parser.parse(p);
    expect(node.props.textAlignment).toBeUndefined();
  });

  it('普通段落（無 textAlignment）→ 不掛 key', () => {
    const p = parsePXml('<w:r><w:t>normal</w:t></w:r>');
    const node = parser.parse(p);
    expect(node.props.textAlignment).toBeUndefined();
  });
});

describe('ParagraphParser — Sprint 134 framePr', () => {
  it('完整 framePr：w/h + hRule + hSpace/vSpace + wrap + hAnchor/vAnchor', () => {
    const p = parsePXml(`
      <w:pPr>
        <w:framePr w:w="2880" w:h="1440" w:hRule="exact"
                   w:hSpace="180" w:vSpace="180"
                   w:wrap="around"
                   w:hAnchor="margin" w:vAnchor="page"
                   w:xAlign="left" w:yAlign="top"/>
      </w:pPr>
    `);
    const node = parser.parse(p);
    const f = node.props.framePr!;
    expect(f.width).toBeCloseTo(144, 1);   // 2880 twip / 20 = 144pt
    expect(f.height).toBeCloseTo(72, 1);   // 1440 twip / 20 = 72pt
    expect(f.hRule).toBe('exact');
    expect(f.hSpace).toBeCloseTo(9, 1);    // 180 twip / 20 = 9pt
    expect(f.vSpace).toBeCloseTo(9, 1);
    expect(f.wrap).toBe('around');
    expect(f.hAnchor).toBe('margin');
    expect(f.vAnchor).toBe('page');
    expect(f.xAlign).toBe('left');
    expect(f.yAlign).toBe('top');
  });

  it('絕對位置 x / y（與 xAlign / yAlign 互斥的另一種寫法）', () => {
    const p = parsePXml(`
      <w:pPr>
        <w:framePr w:w="1440" w:x="720" w:y="1440" w:wrap="none"/>
      </w:pPr>
    `);
    const node = parser.parse(p);
    const f = node.props.framePr!;
    expect(f.x).toBeCloseTo(36, 1);    // 720 twip / 20 = 36pt
    expect(f.y).toBeCloseTo(72, 1);    // 1440 twip / 20 = 72pt
    expect(f.wrap).toBe('none');
    expect(f.xAlign).toBeUndefined();  // 未設、不掛
    expect(f.yAlign).toBeUndefined();
  });

  it('framePr 部分屬性 → 其他 key 不掛（紀律 #21）', () => {
    const p = parsePXml(`
      <w:pPr>
        <w:framePr w:wrap="tight"/>
      </w:pPr>
    `);
    const node = parser.parse(p);
    const f = node.props.framePr!;
    expect(f.wrap).toBe('tight');
    expect(f.width).toBeUndefined();
    expect(f.height).toBeUndefined();
    expect(f.hRule).toBeUndefined();
  });

  it('framePr 全空 → 不掛 key（紀律 #21）', () => {
    const p = parsePXml(`<w:pPr><w:framePr/></w:pPr>`);
    const node = parser.parse(p);
    expect(node.props.framePr).toBeUndefined();
  });

  it('framePr 無效列舉值（hRule="garbage"、wrap="invalid"）→ silent drop、其他屬性仍保留', () => {
    const p = parsePXml(`
      <w:pPr>
        <w:framePr w:w="1440" w:hRule="garbage" w:wrap="invalid" w:hAnchor="bogus"/>
      </w:pPr>
    `);
    const node = parser.parse(p);
    const f = node.props.framePr!;
    expect(f.width).toBeCloseTo(72, 1);
    expect(f.hRule).toBeUndefined();
    expect(f.wrap).toBeUndefined();
    expect(f.hAnchor).toBeUndefined();
  });

  it('普通段落（無 framePr）→ 不掛 key', () => {
    const p = parsePXml('<w:r><w:t>plain</w:t></w:r>');
    const node = parser.parse(p);
    expect(node.props.framePr).toBeUndefined();
  });

  it('framePr + textAlignment + pBdr + shd 同存 → 互不干擾', () => {
    const p = parsePXml(`
      <w:pPr>
        <w:framePr w:w="2880" w:wrap="around"/>
        <w:textAlignment w:val="center"/>
        <w:pBdr><w:top w:val="single" w:sz="4" w:color="000000"/></w:pBdr>
        <w:shd w:val="clear" w:fill="EEEEEE"/>
      </w:pPr>
      <w:r><w:t>everything</w:t></w:r>
    `);
    const node = parser.parse(p);
    expect(node.props.framePr?.wrap).toBe('around');
    expect(node.props.textAlignment).toBe('center');
    expect(node.props.borders?.top?.style).toBe('single');
    expect(node.props.shading?.fill).toBe('EEEEEE');
  });
});

describe('ParagraphParser — Sprint 174 追蹤修訂 <w:ins> / <w:del>', () => {
  it('<w:ins> 包裹 run → revision type=ins + author/date/id', () => {
    const p = parsePXml(
      '<w:ins w:id="3" w:author="Alice" w:date="2024-01-02T10:00:00Z">' +
      '<w:r><w:t>新增文字</w:t></w:r></w:ins>',
    );
    const node = parser.parse(p);
    expect(node.runs).toHaveLength(1);
    const run = node.runs[0];
    expect(run.type).toBe('run');
    if (run.type === 'run') {
      expect(run.text).toBe('新增文字');
      expect(run.revision).toEqual({
        type: 'ins', author: 'Alice', date: '2024-01-02T10:00:00Z', id: 3,
      });
    }
  });

  it('<w:del> 包裹 run、文字來自 <w:delText> → revision type=del', () => {
    const p = parsePXml(
      '<w:del w:id="5" w:author="Bob" w:date="2024-02-03T08:00:00Z">' +
      '<w:r><w:delText>刪除文字</w:delText></w:r></w:del>',
    );
    const node = parser.parse(p);
    expect(node.runs).toHaveLength(1);
    const run = node.runs[0];
    if (run.type === 'run') {
      expect(run.text).toBe('刪除文字');
      expect(run.revision).toEqual({
        type: 'del', author: 'Bob', date: '2024-02-03T08:00:00Z', id: 5,
      });
    }
  });

  it('<w:ins> 無 author/date → revision 只有 type', () => {
    const p = parsePXml('<w:ins w:id="1"><w:r><w:t>x</w:t></w:r></w:ins>');
    const node = parser.parse(p);
    const run = node.runs[0];
    if (run.type === 'run') {
      expect(run.revision).toEqual({ type: 'ins', id: 1 });
    }
  });

  it('<w:ins> 內多個 run → 全部標記同一 revision', () => {
    const p = parsePXml(
      '<w:ins w:id="2" w:author="A"><w:r><w:t>一</w:t></w:r>' +
      '<w:r><w:t>二</w:t></w:r></w:ins>',
    );
    const node = parser.parse(p);
    expect(node.runs).toHaveLength(2);
    for (const run of node.runs) {
      if (run.type === 'run') {
        expect(run.revision?.type).toBe('ins');
        expect(run.revision?.author).toBe('A');
      }
    }
  });

  it('追蹤修訂 run 與一般 run 混排 → 順序保留、只有修訂 run 帶 revision', () => {
    const p = parsePXml(
      '<w:r><w:t>前</w:t></w:r>' +
      '<w:ins w:id="1" w:author="A"><w:r><w:t>插</w:t></w:r></w:ins>' +
      '<w:r><w:t>後</w:t></w:r>',
    );
    const node = parser.parse(p);
    expect(node.runs.map((r) => (r.type === 'run' ? r.text : null))).toEqual(['前', '插', '後']);
    expect(node.runs[0].type === 'run' && node.runs[0].revision).toBeUndefined();
    expect(node.runs[1].type === 'run' && node.runs[1].revision?.type).toBe('ins');
    expect(node.runs[2].type === 'run' && node.runs[2].revision).toBeUndefined();
  });

  it('w:id 非數字 → revision.id 不掛', () => {
    const p = parsePXml('<w:ins w:id="abc" w:author="A"><w:r><w:t>x</w:t></w:r></w:ins>');
    const node = parser.parse(p);
    const run = node.runs[0];
    if (run.type === 'run') {
      expect(run.revision?.id).toBeUndefined();
      expect(run.revision?.author).toBe('A');
    }
  });
});

describe('ParagraphParser — Sprint 177 註解錨點 commentRange/commentReference', () => {
  it('commentRangeStart + commentReference → commentRefs 收集 id', () => {
    const p = parsePXml(
      '<w:commentRangeStart w:id="0"/>' +
      '<w:r><w:t>被註解的文字</w:t></w:r>' +
      '<w:commentRangeEnd w:id="0"/>' +
      '<w:r><w:commentReference w:id="0"/></w:r>',
    );
    const node = parser.parse(p);
    expect(node.commentRefs).toEqual([0]);
  });

  it('多個註解 id → 升序去重', () => {
    const p = parsePXml(
      '<w:commentRangeStart w:id="3"/><w:commentRangeStart w:id="1"/>' +
      '<w:r><w:commentReference w:id="3"/></w:r>' +
      '<w:r><w:commentReference w:id="1"/></w:r>',
    );
    const node = parser.parse(p);
    expect(node.commentRefs).toEqual([1, 3]);
  });

  it('無註解 → commentRefs 不掛', () => {
    const p = parsePXml('<w:r><w:t>一般段落</w:t></w:r>');
    expect(parser.parse(p).commentRefs).toBeUndefined();
  });

  it('w:id 非數字 → 跳過', () => {
    const p = parsePXml('<w:commentRangeStart w:id="abc"/><w:r><w:t>x</w:t></w:r>');
    expect(parser.parse(p).commentRefs).toBeUndefined();
  });

  it('hyperlink 內 w:r 的 commentReference 也收集', () => {
    const p = parsePXml(
      '<w:hyperlink w:anchor="bm1"><w:r><w:commentReference w:id="5"/>' +
      '<w:t>連結</w:t></w:r></w:hyperlink>',
    );
    expect(parser.parse(p).commentRefs).toEqual([5]);
  });
});

describe('ParagraphParser — Sprint 179 OMML 數學公式 <m:oMath>', () => {
  const M_NS = 'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"';

  /** 建 `<w:p>`（含 w: 與 m: 兩命名空間）並解析。 */
  function parsePXmlM(innerPXml: string): Element {
    const xml = `<?xml version="1.0"?><w:p ${W_NS_DECL} ${M_NS}>${innerPXml}</w:p>`;
    const doc = new DOMParser().parseFromString(xml, 'application/xml');
    return doc.documentElement;
  }

  it('段落直屬 <m:oMath> → math 行內公式（display=false）', () => {
    const p = parsePXmlM('<m:oMath><m:r><m:t>x</m:t></m:r></m:oMath>');
    const node = parser.parse(p);
    expect(node.math).toHaveLength(1);
    expect(node.math?.[0].display).toBe(false);
    expect(node.math?.[0].omml).toEqual([
      { tag: 'r', children: [{ tag: 't', text: 'x' }] },
    ]);
  });

  it('<m:oMathPara> 包裹 <m:oMath> → display 公式（display=true）', () => {
    const p = parsePXmlM(
      '<m:oMathPara><m:oMath><m:r><m:t>E</m:t></m:r></m:oMath></m:oMathPara>',
    );
    const node = parser.parse(p);
    expect(node.math).toHaveLength(1);
    expect(node.math?.[0].display).toBe(true);
  });

  it('分數公式 <m:f> → omml 樹保留 num/den 結構', () => {
    const p = parsePXmlM(
      '<m:oMath><m:f>' +
      '<m:num><m:r><m:t>a</m:t></m:r></m:num>' +
      '<m:den><m:r><m:t>b</m:t></m:r></m:den>' +
      '</m:f></m:oMath>',
    );
    const node = parser.parse(p);
    expect(node.math?.[0].omml[0].tag).toBe('f');
    expect(node.math?.[0].omml[0].children?.map((c) => c.tag)).toEqual(['num', 'den']);
  });

  it('<m:oMathPara> 含多個 <m:oMath> → 各自一個 display MathNode', () => {
    const p = parsePXmlM(
      '<m:oMathPara>' +
      '<m:oMath><m:r><m:t>1</m:t></m:r></m:oMath>' +
      '<m:oMath><m:r><m:t>2</m:t></m:r></m:oMath>' +
      '</m:oMathPara>',
    );
    const node = parser.parse(p);
    expect(node.math).toHaveLength(2);
    expect(node.math?.every((m) => m.display)).toBe(true);
  });

  it('公式與一般 run 混排 → runs 不受影響、math 收進側陣列', () => {
    const p = parsePXmlM(
      '<w:r><w:t>前</w:t></w:r>' +
      '<m:oMath><m:r><m:t>y</m:t></m:r></m:oMath>' +
      '<w:r><w:t>後</w:t></w:r>',
    );
    const node = parser.parse(p);
    expect(node.runs.map((r) => (r.type === 'run' ? r.text : null))).toEqual(['前', '後']);
    expect(node.math).toHaveLength(1);
  });

  it('多個行內 <m:oMath> → 順序保留', () => {
    const p = parsePXmlM(
      '<m:oMath><m:r><m:t>P</m:t></m:r></m:oMath>' +
      '<m:oMath><m:r><m:t>Q</m:t></m:r></m:oMath>',
    );
    const node = parser.parse(p);
    expect(node.math?.map((m) => m.omml[0].children?.[0].text)).toEqual(['P', 'Q']);
  });

  it('無公式段落 → math 不掛 key（紀律 #21）', () => {
    const p = parsePXmlM('<w:r><w:t>一般段落</w:t></w:r>');
    expect(parser.parse(p).math).toBeUndefined();
  });

  it('空 <m:oMath> → math 收一個 omml 為空的 MathNode', () => {
    const p = parsePXmlM('<m:oMath/>');
    const node = parser.parse(p);
    expect(node.math).toHaveLength(1);
    expect(node.math?.[0].omml).toEqual([]);
  });
});
