/**
 * WatermarkParser.test.ts — Sprint 172（Phase 5.6 浮水印 + 背景、capture-only）
 *
 * 涵蓋：
 *   - 文字浮水印（<v:textpath string>）→ kind='text' + text / font / rotation
 *   - 圖片浮水印（shape id 含 watermark + <v:imagedata r:id>）→ kind='image' + imageRId
 *   - 非浮水印 VML（無 watermark id 的圖片、空 textpath）→ undefined
 *   - 多 shape → 取第一個浮水印
 *   - 防禦：無 shape / 空 / XML 失敗
 */

import { describe, expect, it } from 'vitest';
import { WatermarkParser } from '../../static/src/core/ooxml/watermark/WatermarkParser';

const NS =
  'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" ' +
  'xmlns:v="urn:schemas-microsoft-com:vml" ' +
  'xmlns:o="urn:schemas-microsoft-com:office:office" ' +
  'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"';

/** 把 `<w:pict>` 內容包進最小 header XML。 */
function wrapHeader(pictInner: string): string {
  return `<?xml version="1.0" encoding="UTF-8"?>\n<w:hdr ${NS}><w:p><w:r><w:pict>${pictInner}</w:pict></w:r></w:p></w:hdr>`;
}

describe('WatermarkParser — 文字浮水印', () => {
  it('<v:textpath string> → kind=text + text', () => {
    const r = new WatermarkParser().parse(wrapHeader(
      '<v:shape id="PowerPlusWaterMarkObject1" type="#_x0000_t136">' +
      '<v:textpath string="機密"/></v:shape>',
    ));
    expect(r).toEqual({ kind: 'text', text: '機密' });
  });

  it('textpath style font-family → font（去引號）', () => {
    const r = new WatermarkParser().parse(wrapHeader(
      '<v:shape id="PowerPlusWaterMarkObject1" type="#_x0000_t136">' +
      '<v:textpath style="font-family:&quot;標楷體&quot;;font-size:1pt" string="DRAFT"/></v:shape>',
    ));
    expect(r?.kind).toBe('text');
    expect(r?.text).toBe('DRAFT');
    expect(r?.font).toBe('標楷體');
  });

  it('v:shape style rotation → rotation（度）', () => {
    const r = new WatermarkParser().parse(wrapHeader(
      '<v:shape id="PowerPlusWaterMarkObject1" type="#_x0000_t136" ' +
      'style="position:absolute;rotation:315">' +
      '<v:textpath string="草稿"/></v:shape>',
    ));
    expect(r?.rotation).toBe(315);
  });

  it('textpath string 為空 → 非文字浮水印', () => {
    const r = new WatermarkParser().parse(wrapHeader(
      '<v:shape id="x"><v:textpath string=""/></v:shape>',
    ));
    expect(r).toBeUndefined();
  });
});

describe('WatermarkParser — 圖片浮水印', () => {
  it('shape id 含 watermark + <v:imagedata r:id> → kind=image + imageRId', () => {
    const r = new WatermarkParser().parse(wrapHeader(
      '<v:shape id="WordPictureWatermark123" type="#_x0000_t75">' +
      '<v:imagedata r:id="rId7" o:title="logo"/></v:shape>',
    ));
    expect(r).toEqual({ kind: 'image', imageRId: 'rId7' });
  });

  it('一般圖片 VML（shape id 不含 watermark）→ 不視為浮水印', () => {
    const r = new WatermarkParser().parse(wrapHeader(
      '<v:shape id="CompanyLogo" type="#_x0000_t75">' +
      '<v:imagedata r:id="rId7"/></v:shape>',
    ));
    expect(r).toBeUndefined();
  });
});

describe('WatermarkParser — 多 shape 與防禦', () => {
  it('多 v:shape → 取第一個浮水印', () => {
    const r = new WatermarkParser().parse(
      `<?xml version="1.0"?>\n<w:hdr ${NS}><w:p><w:r><w:pict>` +
      '<v:shape id="a"><v:textpath string="第一"/></v:shape>' +
      '<v:shape id="b"><v:textpath string="第二"/></v:shape>' +
      '</w:pict></w:r></w:p></w:hdr>',
    );
    expect(r?.text).toBe('第一');
  });

  it('無 v:shape → undefined', () => {
    const r = new WatermarkParser().parse(`<w:hdr ${NS}><w:p/></w:hdr>`);
    expect(r).toBeUndefined();
  });

  it('undefined / 空字串 → undefined', () => {
    expect(new WatermarkParser().parse(undefined)).toBeUndefined();
    expect(new WatermarkParser().parse('')).toBeUndefined();
  });

  it('XML 解析失敗 → undefined（不 throw）', () => {
    expect(new WatermarkParser().parse('<w:hdr <<<broken')).toBeUndefined();
  });
});
