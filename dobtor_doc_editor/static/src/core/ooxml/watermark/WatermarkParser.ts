/**
 * WatermarkParser — 從 header*.xml 抽出文件浮水印（Phase 5.6 浮水印 + 背景）
 *
 * Sprint 172（capture-only）：
 *   Word「設計 → 浮水印」儲存為 header part 內 `<w:pict>` 的 VML `<v:shape>`：
 *     - 文字浮水印：`<v:shape type="#_x0000_t136">` WordArt、含 `<v:textpath string="...">`
 *     - 圖片浮水印：`<v:shape id="...watermark...">`、含 `<v:imagedata r:id="...">`
 *
 * 解析範圍（對應 DocumentWatermark interface）：
 *   - kind 'text'  → text（textpath string）、font（textpath style font-family）
 *   - kind 'image' → imageRId（imagedata r:id）
 *   - rotation     → v:shape style 的 rotation（度）
 *
 * 偵測準則：
 *   - `<v:textpath>` 帶非空 `string` → 文字浮水印（header 內 WordArt 幾乎必為浮水印）
 *   - `<v:imagedata>` + shape id 含 "watermark"（Word 命名 WordPictureWatermark*）→ 圖片浮水印
 *
 * Scope-down（紀律 #18）：capture-only，render（每頁繪旋轉浮水印）留 Sprint 173；
 * 只 capture 第一個浮水印 shape；不解析 fill 透明度 / shape 尺寸。
 *
 * 防禦：undefined / 空 / XML 失敗 / 無浮水印 → 回 undefined（不阻塞 OoxmlParser）。
 */

import type { DocumentWatermark } from '../ast/types';

export class WatermarkParser {
  /**
   * 從單一 header XML 抽出第一個浮水印。
   *
   * @param headerXml header*.xml 完整字串；undefined / 空 → undefined
   * @returns DocumentWatermark 或 undefined（此 header 無浮水印）
   */
  parse(headerXml: string | undefined): DocumentWatermark | undefined {
    if (!headerXml) return undefined;

    let doc: Document;
    try {
      doc = parseXml(headerXml);
    } catch {
      return undefined;
    }
    const root = doc.documentElement;
    if (!root) return undefined;

    const shapes = root.getElementsByTagName('v:shape');
    for (let i = 0; i < shapes.length; i++) {
      const shape = shapes[i];
      const wm = parseShape(shape);
      if (wm) return wm;
    }
    return undefined;
  }
}

/** 嘗試把單一 `<v:shape>` 解為浮水印；非浮水印 → undefined。 */
function parseShape(shape: Element): DocumentWatermark | undefined {
  const shapeStyle = shape.getAttribute('style');
  const rotation = parseRotation(shapeStyle);

  // 文字浮水印：<v:textpath string="...">
  const textpath = firstByTag(shape, 'v:textpath');
  if (textpath) {
    const text = textpath.getAttribute('string');
    if (text) {
      const out: DocumentWatermark = { kind: 'text', text };
      const font = styleProp(textpath.getAttribute('style'), 'font-family');
      if (font) out.font = stripQuotes(font);
      if (rotation !== undefined) out.rotation = rotation;
      return out;
    }
  }

  // 圖片浮水印：shape id 含 "watermark" + <v:imagedata r:id="...">
  const id = shape.getAttribute('id') ?? '';
  if (/watermark/i.test(id)) {
    const imagedata = firstByTag(shape, 'v:imagedata');
    if (imagedata) {
      const rId = imagedata.getAttribute('r:id') ?? imagedata.getAttribute('o:relid');
      const out: DocumentWatermark = { kind: 'image' };
      if (rId) out.imageRId = rId;
      if (rotation !== undefined) out.rotation = rotation;
      return out;
    }
  }

  return undefined;
}

/** 取第一個 tagName 相符的後代元素。 */
function firstByTag(el: Element, tagName: string): Element | undefined {
  const found = el.getElementsByTagName(tagName);
  return found.length > 0 ? found[0] : undefined;
}

/** 從 CSS-like style 字串取某屬性值（如 "font-family:標楷體;font-size:1pt"）。 */
function styleProp(style: string | null, prop: string): string | undefined {
  if (!style) return undefined;
  for (const decl of style.split(';')) {
    const idx = decl.indexOf(':');
    if (idx < 0) continue;
    if (decl.slice(0, idx).trim().toLowerCase() === prop) {
      return decl.slice(idx + 1).trim();
    }
  }
  return undefined;
}

/** 從 v:shape style 取 rotation（度）；無 / 非數 → undefined。 */
function parseRotation(style: string | null): number | undefined {
  const raw = styleProp(style, 'rotation');
  if (raw === undefined) return undefined;
  const n = parseFloat(raw);
  return Number.isFinite(n) ? n : undefined;
}

/** 去除前後成對的單 / 雙引號。 */
function stripQuotes(s: string): string {
  if (s.length >= 2) {
    const first = s[0];
    const last = s[s.length - 1];
    if ((first === '"' && last === '"') || (first === "'" && last === "'")) {
      return s.slice(1, -1);
    }
  }
  return s;
}

function parseXml(xml: string): Document {
  if (typeof DOMParser === 'undefined') {
    throw new Error(
      'WatermarkParser: DOMParser not available — Node tests must use vitest setup with @xmldom/xmldom',
    );
  }
  const doc = new DOMParser().parseFromString(xml, 'application/xml');
  const errors = doc.getElementsByTagName('parsererror');
  if (errors.length > 0) {
    throw new Error(`WatermarkParser: XML parse error — ${errors[0].textContent}`);
  }
  return doc;
}
