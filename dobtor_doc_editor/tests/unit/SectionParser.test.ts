/**
 * SectionParser 單元測試 (Phase B.3)
 *
 * 驗證頁面尺寸 / margin / column / header-footer ref 解析。
 * 多節切分由 DocumentParser.walkBodyAsSections 處理，整合測試在 02_phase_a_smoke。
 */

import { describe, expect, it } from 'vitest';
import { SectionParser } from '../../static/src/core/ooxml/section/SectionParser';
import { DocumentParser } from '../../static/src/core/ooxml/document/DocumentParser';

const W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"';
const R_NS = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"';

const parser = new SectionParser();
const docParser = new DocumentParser();

function parseSectPrFragment(inner: string): Element {
  // 用 DOMParser 直接解析 <w:sectPr> 片段
  const xml = `<?xml version="1.0"?><w:document ${W_NS} ${R_NS}><w:body><w:sectPr>${inner}</w:sectPr></w:body></w:document>`;
  const doc = new DOMParser().parseFromString(xml, 'application/xml');
  return doc.getElementsByTagName('w:sectPr')[0];
}

describe('SectionParser — 預設值', () => {
  it('undefined sectPr 用 A4 portrait + 1 inch margins', () => {
    const sec = parser.parse(undefined);
    expect(sec.page.width).toBeCloseTo(595.3, 1);
    expect(sec.page.height).toBeCloseTo(841.9, 1);
    expect(sec.page.orientation).toBe('portrait');
    expect(sec.margins.top).toBe(72);
    expect(sec.margins.left).toBe(72);
  });
});

describe('SectionParser — 頁面尺寸', () => {
  it('w:pgSz w:w/w:h 換算為 pt', () => {
    const el = parseSectPrFragment('<w:pgSz w:w="11906" w:h="16838"/>');
    const sec = parser.parse(el);
    // 11906 twip / 20 = 595.3 pt（A4 寬）
    expect(sec.page.width).toBeCloseTo(595.3, 1);
    expect(sec.page.height).toBeCloseTo(841.9, 1);
  });

  it('w:orient="landscape" 設為 landscape', () => {
    const el = parseSectPrFragment(
      '<w:pgSz w:w="16838" w:h="11906" w:orient="landscape"/>',
    );
    const sec = parser.parse(el);
    expect(sec.page.orientation).toBe('landscape');
  });
});

describe('SectionParser — 邊界', () => {
  it('w:pgMar 全屬性', () => {
    const el = parseSectPrFragment(
      '<w:pgMar w:top="1440" w:bottom="1440" w:left="1800" w:right="1800" w:header="720" w:footer="720" w:gutter="100"/>',
    );
    const sec = parser.parse(el);
    expect(sec.margins.top).toBe(72); // 1440 twip = 72pt
    expect(sec.margins.left).toBe(90); // 1800 twip = 90pt
    expect(sec.margins.header).toBe(36); // 720 twip = 36pt
    expect(sec.margins.gutter).toBe(5); // 100 twip = 5pt
  });

  it('w:start / w:end 替代 w:left / w:right', () => {
    const el = parseSectPrFragment(
      '<w:pgMar w:top="1440" w:bottom="1440" w:start="900" w:end="900" w:header="720" w:footer="720"/>',
    );
    const sec = parser.parse(el);
    expect(sec.margins.left).toBe(45); // 900 twip = 45pt
    expect(sec.margins.right).toBe(45);
  });
});

describe('SectionParser — header/footer references', () => {
  it('default / first / even 三種 type', () => {
    const el = parseSectPrFragment(
      '<w:headerReference w:type="default" r:id="rId10"/>' +
        '<w:headerReference w:type="first" r:id="rId11"/>' +
        '<w:footerReference w:type="default" r:id="rId12"/>' +
        '<w:footerReference w:type="even" r:id="rId13"/>',
    );
    const sec = parser.parse(el);
    expect(sec.headerRefs.default).toBe('rId10');
    expect(sec.headerRefs.first).toBe('rId11');
    expect(sec.footerRefs.default).toBe('rId12');
    expect(sec.footerRefs.even).toBe('rId13');
  });

  it('titlePg 旗標', () => {
    const el = parseSectPrFragment('<w:titlePg/>');
    const sec = parser.parse(el);
    expect(sec.titlePage).toBe(true);
  });
});

describe('SectionParser — 分欄', () => {
  it('多欄等寬', () => {
    const el = parseSectPrFragment('<w:cols w:num="2" w:space="720"/>');
    const sec = parser.parse(el);
    expect(sec.columns?.count).toBe(2);
    expect(sec.columns?.space).toBe(36); // 720 twip = 36pt
    expect(sec.columns?.equalWidth).toBe(true);
  });

  it('單欄不寫入 columns 欄位', () => {
    const el = parseSectPrFragment('<w:cols w:num="1"/>');
    const sec = parser.parse(el);
    expect(sec.columns).toBeUndefined();
  });

  it('equalWidth=0 設為 false', () => {
    const el = parseSectPrFragment('<w:cols w:num="3" w:equalWidth="0"/>');
    const sec = parser.parse(el);
    expect(sec.columns?.equalWidth).toBe(false);
  });
});

describe('DocumentParser.walkBodyAsSections — 多節切分', () => {
  function wrap(bodyInner: string): string {
    return `<?xml version="1.0"?><w:document ${W_NS} ${R_NS}><w:body>${bodyInner}</w:body></w:document>`;
  }

  it('單節（只有 body 末尾 sectPr）', () => {
    const xml = wrap(
      '<w:p><w:r><w:t>A</w:t></w:r></w:p>' +
        '<w:p><w:r><w:t>B</w:t></w:r></w:p>' +
        '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr>',
    );
    const sections = docParser.walkBodyAsSections(xml);
    expect(sections).toHaveLength(1);
    expect(sections[0].blocks).toHaveLength(2);
    expect(sections[0].sectPrEl).toBeDefined();
  });

  it('段內 sectPr 切兩節', () => {
    const xml = wrap(
      '<w:p><w:r><w:t>A</w:t></w:r></w:p>' +
        '<w:p><w:pPr><w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr></w:pPr><w:r><w:t>B</w:t></w:r></w:p>' +
        '<w:p><w:r><w:t>C</w:t></w:r></w:p>' +
        '<w:sectPr><w:pgSz w:w="16838" w:h="11906" w:orient="landscape"/></w:sectPr>',
    );
    const sections = docParser.walkBodyAsSections(xml);
    expect(sections).toHaveLength(2);
    // 第一節：A + B（含段內 sectPr 的段落）
    expect(sections[0].blocks).toHaveLength(2);
    // 第二節：C
    expect(sections[1].blocks).toHaveLength(1);
  });

  it('完全沒有 sectPr 時用單一無 sectPr 的 section', () => {
    const xml = wrap('<w:p><w:r><w:t>X</w:t></w:r></w:p>');
    const sections = docParser.walkBodyAsSections(xml);
    expect(sections).toHaveLength(1);
    expect(sections[0].sectPrEl).toBeUndefined();
    expect(sections[0].blocks).toHaveLength(1);
  });

  // Sprint 200：writer Sprint 191 emit 的 anchor paragraph 應被 skip
  it('Sprint 200：writer anchor paragraph (無 run + pPr 只含 sectPr) 不計入 blocks', () => {
    const xml = wrap(
      '<w:p><w:r><w:t>A</w:t></w:r></w:p>' +
        // Anchor paragraph：空段含 sectPr——Sprint 191 writer emit 格式
        '<w:p><w:pPr><w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr></w:pPr></w:p>' +
        '<w:p><w:r><w:t>B</w:t></w:r></w:p>' +
        '<w:sectPr><w:pgSz w:w="16838" w:h="11906" w:orient="landscape"/></w:sectPr>',
    );
    const sections = docParser.walkBodyAsSections(xml);
    expect(sections).toHaveLength(2);
    // 第一節：只 A、anchor 段被 skip（不像 Sprint 191 前會看到 [A, anchor]）
    expect(sections[0].blocks).toHaveLength(1);
    expect(sections[0].sectPrEl).toBeDefined();
    // 第二節：B
    expect(sections[1].blocks).toHaveLength(1);
  });

  // Sprint 200：真實 docx 的「最後段帶 run + sectPr」必須保留為實段（非 anchor）
  it('Sprint 200：含 run 的最後段帶 sectPr 不視為 anchor、計入 blocks', () => {
    const xml = wrap(
      // 真實 Word case：最後段有 run + 段內 sectPr
      '<w:p><w:pPr><w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr></w:pPr><w:r><w:t>Last</w:t></w:r></w:p>' +
        '<w:p><w:r><w:t>Next</w:t></w:r></w:p>' +
        '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr>',
    );
    const sections = docParser.walkBodyAsSections(xml);
    expect(sections).toHaveLength(2);
    // 第一節：保留含 run 的段
    expect(sections[0].blocks).toHaveLength(1);
    expect(sections[1].blocks).toHaveLength(1);
  });

  // Sprint 200：空段但 pPr 含 rPr 等非 sectPr 屬性 → 不視為 anchor（保留視覺意圖）
  it('Sprint 200：pPr 含 rPr 等其他屬性的空段不視為 anchor', () => {
    const xml = wrap(
      '<w:p><w:r><w:t>A</w:t></w:r></w:p>' +
        // pPr 含 rPr + sectPr（非單一 sectPr 子）→ 保留
        '<w:p><w:pPr><w:rPr><w:sz w:val="24"/></w:rPr><w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr></w:pPr></w:p>' +
        '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr>',
    );
    const sections = docParser.walkBodyAsSections(xml);
    expect(sections).toHaveLength(2);
    expect(sections[0].blocks).toHaveLength(2); // A + 含 rPr 的空段
  });

  // Sprint 29：docGrid 解析
  it('w:docGrid type=lines linePitch=364 → 解析 lines + 18.2pt', () => {
    const el = parseSectPrFragment('<w:docGrid w:type="lines" w:linePitch="364"/>');
    const sec = parser.parse(el);
    expect(sec.docGrid).toBeDefined();
    expect(sec.docGrid?.type).toBe('lines');
    expect(sec.docGrid?.linePitch).toBeCloseTo(18.2, 4);
  });

  it('w:docGrid type=default → 不寫入 docGrid（保 snapshot 穩定）', () => {
    const el = parseSectPrFragment('<w:docGrid w:type="default" w:linePitch="360"/>');
    const sec = parser.parse(el);
    expect(sec.docGrid).toBeUndefined();
  });

  it('w:docGrid linePitch 缺失 → linePitch=0', () => {
    const el = parseSectPrFragment('<w:docGrid w:type="lines"/>');
    const sec = parser.parse(el);
    expect(sec.docGrid?.type).toBe('lines');
    expect(sec.docGrid?.linePitch).toBe(0);
  });

  it('無 w:docGrid → docGrid 不存在（向下相容）', () => {
    const el = parseSectPrFragment('<w:pgSz w:w="11906" w:h="16838"/>');
    const sec = parser.parse(el);
    expect(sec.docGrid).toBeUndefined();
  });

  it('連續 OoxmlParser 流程：兩節用不同頁面尺寸', () => {
    const xml = wrap(
      '<w:p><w:pPr><w:sectPr><w:pgSz w:w="11906" w:h="16838" w:orient="portrait"/></w:sectPr></w:pPr><w:r><w:t>P1</w:t></w:r></w:p>' +
        '<w:p><w:r><w:t>P2</w:t></w:r></w:p>' +
        '<w:sectPr><w:pgSz w:w="16838" w:h="11906" w:orient="landscape"/></w:sectPr>',
    );
    const sections = docParser.walkBodyAsSections(xml);
    expect(sections).toHaveLength(2);

    const sec1 = parser.parse(sections[0].sectPrEl);
    const sec2 = parser.parse(sections[1].sectPrEl);
    expect(sec1.page.orientation).toBe('portrait');
    expect(sec2.page.orientation).toBe('landscape');
  });
});
