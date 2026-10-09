/**
 * ChartParser 單元測試（Sprint 182、Phase 5.3 Charts capture-only）
 *
 * 用手寫 `charts/chartN.xml`（`<c:chartSpace>`）驗證 ChartParser 的解析輸出。
 * 不依賴 fixture .docx — 純 OOXML 行為單元測試。
 */

import { describe, expect, it } from 'vitest';
import { ChartParser, chartToText } from '../../static/src/core/ooxml/chart/ChartParser';
import type { ChartNode } from '../../static/src/core/ooxml/ast/types';

const NS =
  'xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" ' +
  'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"';

/** 包成完整 `<c:chartSpace>`：`chartInner` 放進 `<c:chart>`。 */
function chartSpace(chartInner: string): string {
  return `<?xml version="1.0"?><c:chartSpace ${NS}><c:chart>${chartInner}</c:chart></c:chartSpace>`;
}

/** 產 `<c:strCache>` / `<c:numCache>`：vals 依序為 idx 0..N（undefined 表稀疏缺漏）。 */
function cache(tag: 'strCache' | 'numCache', vals: (string | number | undefined)[]): string {
  let pts = '';
  vals.forEach((v, i) => {
    if (v !== undefined) pts += `<c:pt idx="${i}"><c:v>${v}</c:v></c:pt>`;
  });
  return `<c:${tag}><c:ptCount val="${vals.length}"/>${pts}</c:${tag}>`;
}

/** 產一個 `<c:ser>`：name / 類別 / 數值。 */
function ser(name: string | null, cats: string[], vals: (number | undefined)[]): string {
  const tx = name === null
    ? ''
    : `<c:tx><c:strRef><c:f>x</c:f>${cache('strCache', [name])}</c:strRef></c:tx>`;
  const cat = `<c:cat><c:strRef><c:f>x</c:f>${cache('strCache', cats)}</c:strRef></c:cat>`;
  const val = `<c:val><c:numRef><c:f>x</c:f>${cache('numCache', vals)}</c:numRef></c:val>`;
  return `<c:ser>${tx}${cat}${val}</c:ser>`;
}

/** 把 0..N 個 `<c:ser>` 包進 `<c:plotArea><c:{type}>`。 */
function plotArea(type: string, sers: string): string {
  return `<c:plotArea><c:${type}>${sers}</c:${type}></c:plotArea>`;
}

const parser = new ChartParser();

describe('ChartParser — 防禦與邊界', () => {
  it('undefined / 空字串 → undefined', () => {
    expect(parser.parse(undefined, 'rId1')).toBeUndefined();
    expect(parser.parse('', 'rId1')).toBeUndefined();
  });

  it('XML 解析失敗 → undefined（不 throw）', () => {
    expect(parser.parse('<c:chartSpace <broken', 'rId1')).toBeUndefined();
  });

  it('root 非 <c:chartSpace> → undefined', () => {
    expect(parser.parse('<?xml version="1.0"?><foo/>', 'rId1')).toBeUndefined();
  });

  it('無 <c:chart> → undefined', () => {
    expect(parser.parse(`<?xml version="1.0"?><c:chartSpace ${NS}/>`, 'rId1')).toBeUndefined();
  });

  it('無 <c:plotArea> → undefined', () => {
    expect(parser.parse(chartSpace('<c:title/>'), 'rId1')).toBeUndefined();
  });

  it('plotArea 無圖表型別元素 → undefined', () => {
    expect(parser.parse(chartSpace('<c:plotArea><c:catAx/></c:plotArea>'), 'rId1')).toBeUndefined();
  });
});

describe('ChartParser — 圖表型別與標題', () => {
  it('barChart 型別 + rId 寫入', () => {
    const node = parser.parse(chartSpace(plotArea('barChart', ser('S', ['a'], [1]))), 'rId5');
    expect(node?.chartType).toBe('barChart');
    expect(node?.rId).toBe('rId5');
  });

  it('bar3DChart / pieChart / lineChart 型別', () => {
    for (const t of ['bar3DChart', 'pieChart', 'lineChart']) {
      const node = parser.parse(chartSpace(plotArea(t, ser('S', ['a'], [1]))), 'rId1');
      expect(node?.chartType).toBe(t);
    }
  });

  it('<c:title> → title', () => {
    const inner = '<c:title><c:tx><c:rich><a:p><a:r><a:t>季度銷售</a:t></a:r></a:p></c:rich></c:tx></c:title>' +
      plotArea('barChart', ser('S', ['a'], [1]));
    expect(parser.parse(chartSpace(inner), 'rId1')?.title).toBe('季度銷售');
  });

  it('無 <c:title> → 不掛 title key（紀律 #21）', () => {
    const node = parser.parse(chartSpace(plotArea('barChart', ser('S', ['a'], [1]))), 'rId1');
    expect('title' in (node as object)).toBe(false);
  });
});

describe('ChartParser — 數列（series）', () => {
  it('單一數列：name / categories / values', () => {
    const node = parser.parse(
      chartSpace(plotArea('barChart', ser('營收', ['Q1', 'Q2', 'Q3'], [10, 20, 30]))),
      'rId1',
    );
    expect(node?.series).toHaveLength(1);
    expect(node?.series[0]).toEqual({
      name: '營收',
      categories: ['Q1', 'Q2', 'Q3'],
      values: [10, 20, 30],
    });
  });

  it('多數列 → 依序保留', () => {
    const node = parser.parse(
      chartSpace(plotArea('barChart',
        ser('甲', ['a'], [1]) + ser('乙', ['a'], [2]) + ser('丙', ['a'], [3]))),
      'rId1',
    );
    expect(node?.series.map((s) => s.name)).toEqual(['甲', '乙', '丙']);
  });

  it('數列無 <c:tx> → 不掛 name key（紀律 #21）', () => {
    const node = parser.parse(chartSpace(plotArea('barChart', ser(null, ['a'], [1]))), 'rId1');
    expect('name' in node!.series[0]).toBe(false);
  });

  it('圖表型別元素無 <c:ser> → series 為空陣列', () => {
    const node = parser.parse(chartSpace(plotArea('barChart', '')), 'rId1');
    expect(node?.series).toEqual([]);
  });
});

describe('ChartParser — 快取點對位', () => {
  it('稀疏 idx → 缺漏類別補空字串、缺漏數值補 null', () => {
    // ptCount=4，但只給 idx 0 與 3
    const catXml = `<c:cat><c:strRef>${'<c:strCache><c:ptCount val="4"/>' +
      '<c:pt idx="0"><c:v>頭</c:v></c:pt><c:pt idx="3"><c:v>尾</c:v></c:pt></c:strCache>'}</c:strRef></c:cat>`;
    const valXml = `<c:val><c:numRef>${'<c:numCache><c:ptCount val="4"/>' +
      '<c:pt idx="0"><c:v>5</c:v></c:pt><c:pt idx="3"><c:v>8</c:v></c:pt></c:numCache>'}</c:numRef></c:val>`;
    const node = parser.parse(
      chartSpace(plotArea('barChart', `<c:ser>${catXml}${valXml}</c:ser>`)),
      'rId1',
    );
    expect(node?.series[0].categories).toEqual(['頭', '', '', '尾']);
    expect(node?.series[0].values).toEqual([5, null, null, 8]);
  });

  it('非數值 <c:v> → values 該點為 null', () => {
    const node = parser.parse(
      chartSpace(plotArea('barChart', ser('S', ['a', 'b'], [undefined, undefined]))),
      'rId1',
    );
    // ser() 對 undefined 不產 pt → ptCount=2、兩點皆缺 → 皆 null
    expect(node?.series[0].values).toEqual([null, null]);
  });

  it('ptCount 缺漏 → 長度退回最大 idx+1', () => {
    const catXml = '<c:cat><c:strRef><c:strCache>' +
      '<c:pt idx="0"><c:v>x</c:v></c:pt><c:pt idx="2"><c:v>z</c:v></c:pt>' +
      '</c:strCache></c:strRef></c:cat>';
    const node = parser.parse(
      chartSpace(plotArea('barChart', `<c:ser>${catXml}</c:ser>`)),
      'rId1',
    );
    expect(node?.series[0].categories).toEqual(['x', '', 'z']);
  });

  it('小數與負數值正確解析', () => {
    const node = parser.parse(
      chartSpace(plotArea('lineChart', ser('S', ['a', 'b', 'c'], [3.14, -2, 0]))),
      'rId1',
    );
    expect(node?.series[0].values).toEqual([3.14, -2, 0]);
  });
});

describe('ChartParser — Sprint 183 chartToText 線性文字 fallback', () => {
  const mk = (over: Partial<ChartNode>): ChartNode => ({
    rId: 'rId1', chartType: 'barChart', series: [], ...over,
  });

  it('無數列 → 空字串', () => {
    expect(chartToText(mk({}))).toBe('');
  });

  it('僅標題、無數列 → 只回標題', () => {
    expect(chartToText(mk({ title: '季度銷售' }))).toBe('季度銷售');
  });

  it('單數列：名稱 + 類別=值 配對', () => {
    expect(chartToText(mk({
      series: [{ name: '營收', categories: ['Q1', 'Q2'], values: [10, 20] }],
    }))).toBe('營收: Q1=10, Q2=20');
  });

  it('標題 + 多數列 → 標題 + "; " 串接', () => {
    expect(chartToText(mk({
      title: '進度',
      series: [
        { name: '甲', categories: ['a'], values: [1] },
        { name: '乙', categories: ['a'], values: [2] },
      ],
    }))).toBe('進度 甲: a=1; 乙: a=2');
  });

  it('null 數值 → 只顯示類別（無 =值）', () => {
    expect(chartToText(mk({
      series: [{ name: 'S', categories: ['x', 'y'], values: [null, 5] }],
    }))).toBe('S: x, y=5');
  });

  it('類別空白且數值 null 的點 → 跳過', () => {
    expect(chartToText(mk({
      series: [{ name: 'S', categories: ['a', '', 'c'], values: [1, null, 3] }],
    }))).toBe('S: a=1, c=3');
  });

  it('數列無 name → 只回配對', () => {
    expect(chartToText(mk({
      series: [{ categories: ['a', 'b'], values: [1, 2] }],
    }))).toBe('a=1, b=2');
  });
});
