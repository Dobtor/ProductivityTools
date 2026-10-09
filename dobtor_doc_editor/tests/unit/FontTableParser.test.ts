/**
 * FontTableParser.test.ts — Sprint 147 (Phase 1 capture-only)
 *
 * 涵蓋:
 *   - 真實 fixture 結構解析(摘自 03_complex_table/送審管制.docx)
 *   - 各欄位獨立 test:name / altName / charset / family / pitch / panose1 / sig
 *   - 列舉值驗證 + 未知值降級(family / pitch)
 *   - 紀律 #21:sig 全空時不掛 key
 *   - 防禦邊界:undefined / 空 / XML 失敗 / 缺 name 的 font 條目跳過
 *   - CJK 字型名稱(中文 unicode)正確解析
 */

import { describe, expect, it } from 'vitest';
import { FontTableParser } from '../../static/src/core/ooxml/font-table/FontTableParser';

const NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"';

function wrap(inner: string): string {
  return `<?xml version="1.0" encoding="UTF-8"?>\n<w:fonts ${NS}>${inner}</w:fonts>`;
}

// ── 基本欄位 ────────────────────────────────────────────────────────────────

describe('FontTableParser — 基本欄位', () => {
  it('w:font w:name="..." → 進入 Map (key = name)', () => {
    const r = new FontTableParser().parse(
      wrap('<w:font w:name="Arial"></w:font>'),
    );
    expect(r.size).toBe(1);
    expect(r.get('Arial')?.name).toBe('Arial');
  });

  it('CJK 字型名稱(中文 Unicode)正確 key 化', () => {
    const r = new FontTableParser().parse(
      wrap(
        '<w:font w:name="標楷體"/>' +
          '<w:font w:name="細明體"/>' +
          '<w:font w:name="新細明體"/>',
      ),
    );
    expect(r.size).toBe(3);
    expect(r.has('標楷體')).toBe(true);
    expect(r.has('細明體')).toBe(true);
    expect(r.has('新細明體')).toBe(true);
  });

  it('w:altName w:val="..." → entry.altName', () => {
    const r = new FontTableParser().parse(
      wrap('<w:font w:name="細明體"><w:altName w:val="MingLiU"/></w:font>'),
    );
    expect(r.get('細明體')?.altName).toBe('MingLiU');
  });

  it('w:charset w:val 保留為 hex 字串(不轉數字)', () => {
    const r = new FontTableParser().parse(
      wrap('<w:font w:name="細明體"><w:charset w:val="88"/></w:font>'),
    );
    expect(r.get('細明體')?.charset).toBe('88');
  });

  it('w:panose1 w:val 保留 10-byte hex 字串', () => {
    const r = new FontTableParser().parse(
      wrap('<w:font w:name="Arial"><w:panose1 w:val="020B0604020202020204"/></w:font>'),
    );
    expect(r.get('Arial')?.panose1).toBe('020B0604020202020204');
  });
});

// ── family / pitch 列舉 ─────────────────────────────────────────────────────

describe('FontTableParser — family / pitch 列舉', () => {
  it('family 6 種合法值都接受', () => {
    for (const f of ['auto', 'decorative', 'modern', 'roman', 'script', 'swiss']) {
      const r = new FontTableParser().parse(
        wrap(`<w:font w:name="${f}Font"><w:family w:val="${f}"/></w:font>`),
      );
      expect(r.get(`${f}Font`)?.family).toBe(f);
    }
  });

  it('family 未知值 → undefined 降級', () => {
    const r = new FontTableParser().parse(
      wrap('<w:font w:name="X"><w:family w:val="unknownFamily"/></w:font>'),
    );
    expect(r.get('X')?.family).toBeUndefined();
  });

  it('pitch 3 種合法值都接受', () => {
    for (const p of ['fixed', 'variable', 'default']) {
      const r = new FontTableParser().parse(
        wrap(`<w:font w:name="${p}Pitch"><w:pitch w:val="${p}"/></w:font>`),
      );
      expect(r.get(`${p}Pitch`)?.pitch).toBe(p);
    }
  });

  it('pitch 未知值 → undefined 降級', () => {
    const r = new FontTableParser().parse(
      wrap('<w:font w:name="Y"><w:pitch w:val="unknownPitch"/></w:font>'),
    );
    expect(r.get('Y')?.pitch).toBeUndefined();
  });
});

// ── sig (Unicode + Code Page 簽章) ──────────────────────────────────────────

describe('FontTableParser — sig 簽章', () => {
  it('完整 sig 6 屬性', () => {
    const r = new FontTableParser().parse(
      wrap(
        '<w:font w:name="Arial">' +
          '<w:sig w:usb0="E0002EFF" w:usb1="C000785B" w:usb2="00000009" ' +
          'w:usb3="00000000" w:csb0="000001FF" w:csb1="00000000"/>' +
          '</w:font>',
      ),
    );
    expect(r.get('Arial')?.sig).toEqual({
      usb0: 'E0002EFF',
      usb1: 'C000785B',
      usb2: '00000009',
      usb3: '00000000',
      csb0: '000001FF',
      csb1: '00000000',
    });
  });

  it('部分 sig 屬性(只 usb0 / csb0) → 只掛存在的', () => {
    const r = new FontTableParser().parse(
      wrap('<w:font w:name="X"><w:sig w:usb0="A0" w:csb0="01"/></w:font>'),
    );
    expect(r.get('X')?.sig).toEqual({ usb0: 'A0', csb0: '01' });
  });

  it('sig 全空(無屬性)→ entry.sig undefined (紀律 #21)', () => {
    const r = new FontTableParser().parse(
      wrap('<w:font w:name="X"><w:sig/></w:font>'),
    );
    expect(r.get('X')?.sig).toBeUndefined();
  });
});

// ── 真實 fixture 樣本(整合 test) ────────────────────────────────────────────

describe('FontTableParser — 真實 fixture 樣本', () => {
  it('解析 3 個常見字型(標楷體 + Times New Roman + 細明體)', () => {
    const xml = wrap(
      '<w:font w:name="標楷體">' +
        '<w:panose1 w:val="03000509000000000000"/>' +
        '<w:charset w:val="88"/>' +
        '<w:family w:val="script"/>' +
        '<w:pitch w:val="fixed"/>' +
        '<w:sig w:usb0="00000003" w:csb0="00100001"/>' +
        '</w:font>' +
        '<w:font w:name="Times New Roman">' +
        '<w:panose1 w:val="02020603050405020304"/>' +
        '<w:charset w:val="00"/>' +
        '<w:family w:val="roman"/>' +
        '<w:pitch w:val="variable"/>' +
        '</w:font>' +
        '<w:font w:name="細明體">' +
        '<w:altName w:val="MingLiU"/>' +
        '<w:panose1 w:val="02020509000000000000"/>' +
        '<w:charset w:val="88"/>' +
        '<w:family w:val="modern"/>' +
        '<w:pitch w:val="fixed"/>' +
        '</w:font>',
    );
    const r = new FontTableParser().parse(xml);
    expect(r.size).toBe(3);

    const kai = r.get('標楷體')!;
    expect(kai.family).toBe('script');
    expect(kai.pitch).toBe('fixed');
    expect(kai.charset).toBe('88');
    expect(kai.sig?.usb0).toBe('00000003');

    const times = r.get('Times New Roman')!;
    expect(times.family).toBe('roman');
    expect(times.pitch).toBe('variable');
    expect(times.altName).toBeUndefined();
    expect(times.sig).toBeUndefined();

    const ming = r.get('細明體')!;
    expect(ming.altName).toBe('MingLiU');
    expect(ming.family).toBe('modern');
  });
});

// ── 防禦邊界 ────────────────────────────────────────────────────────────────

describe('FontTableParser — 防禦邊界', () => {
  it('undefined → 回空 Map', () => {
    expect(new FontTableParser().parse(undefined).size).toBe(0);
  });

  it('空字串 → 回空 Map', () => {
    expect(new FontTableParser().parse('').size).toBe(0);
  });

  it('壞 XML → 回空 Map (不 throw)', () => {
    expect(new FontTableParser().parse('<w:fonts><not closed>').size).toBe(0);
  });

  it('完全空 w:fonts (無 font 子元素) → 回空 Map', () => {
    expect(new FontTableParser().parse(wrap('')).size).toBe(0);
  });

  it('w:font 缺 name 屬性 → 跳過此條目', () => {
    const r = new FontTableParser().parse(
      wrap(
        '<w:font><w:family w:val="roman"/></w:font>' +
          '<w:font w:name="Arial"/>',
      ),
    );
    expect(r.size).toBe(1);
    expect(r.has('Arial')).toBe(true);
  });

  it('w:altName 缺 val 屬性 → 不掛 altName', () => {
    const r = new FontTableParser().parse(
      wrap('<w:font w:name="X"><w:altName/></w:font>'),
    );
    expect(r.get('X')?.altName).toBeUndefined();
  });

  it('多 font 條目順序保留(Map 保插入順序)', () => {
    const r = new FontTableParser().parse(
      wrap(
        '<w:font w:name="First"/>' +
          '<w:font w:name="Second"/>' +
          '<w:font w:name="Third"/>',
      ),
    );
    expect(Array.from(r.keys())).toEqual(['First', 'Second', 'Third']);
  });
});
