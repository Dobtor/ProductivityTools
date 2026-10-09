/**
 * BrowserCanvasRenderContext — 將 RenderContext 指令發到瀏覽器 CanvasRenderingContext2D
 *
 * 設計重點：
 *   - pt → px 換算：預設 96/72（web 標準 96dpi），可由 caller 注入 scale 客製
 *   - color hex (6 位、無 #) → CSS string `#RRGGBB`
 *   - font CSS string：`bold italic 12px "Times New Roman"`
 *   - fillText：Canvas 預設 textBaseline = 'alphabetic'，與 Renderer 傳的 baseline 座標相符
 *   - drawImage：rId 直接傳給 caller 提供的 imageResolver；找不到時跳過
 *
 * Sprint 57 fast path（**只 memoize string，不動 save/restore**）：
 *   - Sprint 57 初版嘗試「拿掉 save/restore + 用 cache 跳過相同 setState」於全 42 fixture VR 翻車（mean 0.0749 → 0.0998；06-8估驗計價 page 1 整個表格區黑底紅字 diff 0.67 over threshold 0.5）
 *   - 教訓：**unit test 綠（13 tests）不等於 VR 綠**（Sprint 46/49 cascading chain 第八層紀律再次應驗 — 全 fixture VR 才能確認 byte-identical）
 *   - 退到「保留所有 save/restore + 僅 memoize toCssColor / toCssFont 字串拼接」的最小安全版：
 *     - 對 text-heavy 文件每頁 N 次 fillText 共用相同 font/color → 避免重複拼接 + toFixed
 *     - save/restore 仍每個 op 都保留 → state stack 行為完全等同舊版、VR byte-identical
 *
 * 多頁支援：
 *   - 預設「單一 canvas，一頁一頁畫」：每次 beginPage 在固定 canvas 上 clearRect
 *     + 通知 onPageChange callback（caller 可拷貝到 thumbnail / 另存）
 *   - 多頁印製常用 pattern：caller 在 endPage 內把 canvas → blob/url 收集
 *
 * 不支援的 OOXML 功能（Sprint 9 簡化）：
 *   - 雙線 / 浪線 / dotted style 一律當實線（drawLine 寬度套用即可，style 透傳給 caller 自行處理）
 *   - 文字旋轉（textDirection != lrTb）忽略
 *   - 文字 shadow / outline / emboss 忽略
 */

import type { Pt } from '../ooxml/ast/types';
import type { RenderContext, RenderStrokeStyle, RenderTextStyle } from './types';

/** Canvas API 子集（避免直接依賴 lib.dom.d.ts；vitest Node 環境也能型別檢查） */
export interface BrowserCanvas2D {
  fillStyle: string;
  strokeStyle: string;
  lineWidth: number;
  font: string;
  textBaseline: 'alphabetic' | 'top' | 'middle' | 'bottom' | 'hanging' | 'ideographic';
  textAlign: 'start' | 'end' | 'left' | 'right' | 'center';
  setLineDash?: (segments: number[]) => void;
  fillRect(x: number, y: number, w: number, h: number): void;
  strokeRect(x: number, y: number, w: number, h: number): void;
  fillText(text: string, x: number, y: number): void;
  beginPath(): void;
  moveTo(x: number, y: number): void;
  lineTo(x: number, y: number): void;
  stroke(): void;
  clearRect(x: number, y: number, w: number, h: number): void;
  /**
   * Browser 原生 Canvas 2D `drawImage` 重載（5-arg 或 9-arg）。
   * 9-arg 版本（Sprint 40）用於 `<a:srcRect>` 圖片裁切：傳 src 像素座標 + dest 像素座標。
   */
  drawImage?(image: unknown, ...args: number[]): void;
  save(): void;
  restore(): void;
  translate(x: number, y: number): void;
  rotate(angle: number): void;
}

export interface BrowserCanvasRenderOptions {
  /**
   * pt → px 縮放（每 pt 多少 px）。預設 96/72 ≈ 1.333（標準 web dpi）。
   * 高 DPI 螢幕可傳 96/72 × devicePixelRatio。
   */
  scale?: number;
  /**
   * 圖片解析器：給定 rId 回傳 HTMLImageElement / ImageBitmap / 任何 Canvas 接受的來源。
   * undefined 時 drawImage 變 no-op（測試 / 純文字場景常用）。
   */
  imageResolver?: (href: string) => unknown | undefined;
  /** 每頁開始時是否 clearRect（單一 canvas 重用情境）。預設 true。 */
  clearOnBeginPage?: boolean;
  /** 頁面切換 callback：endPage 後呼叫，caller 可拷貝 / save 此 canvas 內容。 */
  onPageEnd?: (pageNumber: number, width: Pt, height: Pt) => void;
}

const PT_PER_INCH = 72;
const PX_PER_INCH = 96;
const DEFAULT_SCALE = PX_PER_INCH / PT_PER_INCH;

/**
 * Sprint 59 path coalescing：合併連續相同 style 的 drawLine 為單一 beginPath + stroke。
 * 觸發 flush：style 變化 / fillRect / fillText / drawImage / save / restore / translate / rotate / beginPage / endPage。
 */
interface PendingPath {
  strokeCss: string;
  lineWidth: number;
  dashKey: string;
  segments: Array<{ x1: number; y1: number; x2: number; y2: number }>;
}

function dashKeyOf(style: RenderStrokeStyle['style']): string {
  if (style === 'dashed' || style === 'dashSmallGap') return 'dashed';
  if (style === 'dotted') return 'dotted';
  return 'solid';
}

export class BrowserCanvasRenderContext implements RenderContext {
  private scale: number;
  private resolveImage?: (href: string) => unknown | undefined;
  private clearOnBeginPage: boolean;
  private onPageEnd?: (pageNumber: number, width: Pt, height: Pt) => void;
  private currentPage = 0;
  private currentWidth = 0;
  private currentHeight = 0;
  // Sprint 59：drawLine 批次緩衝。null = 無 pending
  private pendingPath: PendingPath | null = null;

  constructor(private canvas2d: BrowserCanvas2D, opts: BrowserCanvasRenderOptions = {}) {
    this.scale = opts.scale ?? DEFAULT_SCALE;
    this.resolveImage = opts.imageResolver;
    this.clearOnBeginPage = opts.clearOnBeginPage ?? true;
    this.onPageEnd = opts.onPageEnd;
  }

  /**
   * Sprint 59：把 pending drawLine 批次一次 stroke 出來。
   *
   * 觸發點：任何「非 drawLine 的繪圖 op」前 + style 變化時。
   * Canvas spec：一個 stroke() 對 path 內所有 sub-path 用當前 state 繪出；
   *   sub-path 之間獨立、與分多次 stroke() 結果像素相同（同 strokeStyle/lineWidth/dash/lineCap/lineJoin）。
   */
  private flushPath(): void {
    const p = this.pendingPath;
    if (!p || p.segments.length === 0) {
      this.pendingPath = null;
      return;
    }
    this.pendingPath = null;
    this.canvas2d.save();
    this.canvas2d.strokeStyle = p.strokeCss;
    this.canvas2d.lineWidth = p.lineWidth;
    if (this.canvas2d.setLineDash) {
      if (p.dashKey === 'dashed') this.canvas2d.setLineDash([4, 2]);
      else if (p.dashKey === 'dotted') this.canvas2d.setLineDash([1, 2]);
      else this.canvas2d.setLineDash([]);
    }
    this.canvas2d.beginPath();
    for (let i = 0; i < p.segments.length; i++) {
      const s = p.segments[i];
      this.canvas2d.moveTo(s.x1, s.y1);
      this.canvas2d.lineTo(s.x2, s.y2);
    }
    this.canvas2d.stroke();
    this.canvas2d.restore();
  }

  beginPage(pageNumber: number, width: Pt, height: Pt): void {
    this.flushPath();
    this.currentPage = pageNumber;
    this.currentWidth = width;
    this.currentHeight = height;
    if (this.clearOnBeginPage) {
      this.canvas2d.clearRect(0, 0, width * this.scale, height * this.scale);
    }
  }

  endPage(): void {
    this.flushPath();
    if (this.onPageEnd) {
      this.onPageEnd(this.currentPage, this.currentWidth, this.currentHeight);
    }
  }

  fillRect(x: Pt, y: Pt, width: Pt, height: Pt, color: string): void {
    this.flushPath();
    this.canvas2d.save();
    this.canvas2d.fillStyle = toCssColor(color);
    this.canvas2d.fillRect(this.px(x), this.px(y), this.px(width), this.px(height));
    this.canvas2d.restore();
  }

  drawLine(x1: Pt, y1: Pt, x2: Pt, y2: Pt, style: RenderStrokeStyle): void {
    // Sprint 59：path coalescing — 相同 style 的連續 drawLine 累積到 pendingPath，flush 時批次 stroke
    const strokeCss = toCssColor(style.color);
    const lineWidth = Math.max(this.px(style.width), 1); // 至少 1px 避免消失
    const dashKey = dashKeyOf(style.style);
    const seg = {
      x1: this.px(x1),
      y1: this.px(y1),
      x2: this.px(x2),
      y2: this.px(y2),
    };
    const p = this.pendingPath;
    if (p && p.strokeCss === strokeCss && p.lineWidth === lineWidth && p.dashKey === dashKey) {
      p.segments.push(seg);
      return;
    }
    // style 變化：先 flush 舊批次再開新批次
    this.flushPath();
    this.pendingPath = { strokeCss, lineWidth, dashKey, segments: [seg] };
  }

  fillText(text: string, x: Pt, y: Pt, style: RenderTextStyle): void {
    this.flushPath();
    this.canvas2d.save();
    // font 字級必須是 px（且 scale 過），CSS 不接受 pt
    this.canvas2d.font = toCssFont(style, this.scale);
    this.canvas2d.fillStyle = toCssColor(style.color ?? '000000');
    this.canvas2d.textBaseline = 'alphabetic';
    this.canvas2d.textAlign = 'start';
    this.canvas2d.fillText(text, this.px(x), this.px(y));
    this.canvas2d.restore();
  }

  drawImage(
    href: string,
    x: Pt,
    y: Pt,
    width: Pt,
    height: Pt,
    srcRect?: { leftPct: number; topPct: number; rightPct: number; bottomPct: number },
  ): void {
    this.flushPath();
    if (!this.resolveImage || !this.canvas2d.drawImage) return;
    const img = this.resolveImage(href);
    if (img === undefined || img === null) return;
    const dx = this.px(x), dy = this.px(y), dw = this.px(width), dh = this.px(height);

    if (srcRect) {
      // Sprint 40：9-arg drawImage 走 source 裁切。
      // img 必須有 naturalWidth / naturalHeight / width / height（HTMLImageElement、ImageBitmap、HTMLCanvasElement、HTMLVideoElement、SVGImageElement 都符合）
      const src = img as { naturalWidth?: number; naturalHeight?: number; width?: number; height?: number };
      const sw0 = src.naturalWidth ?? src.width ?? 0;
      const sh0 = src.naturalHeight ?? src.height ?? 0;
      if (sw0 > 0 && sh0 > 0) {
        const sx = sw0 * srcRect.leftPct;
        const sy = sh0 * srcRect.topPct;
        const sw = sw0 * (1 - srcRect.leftPct - srcRect.rightPct);
        const sh = sh0 * (1 - srcRect.topPct - srcRect.bottomPct);
        this.canvas2d.drawImage(img, sx, sy, sw, sh, dx, dy, dw, dh);
        return;
      }
      // 無法取得 source 像素 → 降級 5-arg（不裁切）
    }
    this.canvas2d.drawImage(img, dx, dy, dw, dh);
  }

  // Sprint 34：座標變換 API（垂直文字 cell 旋轉用）
  // Sprint 59：所有 transform / state-stack op 前必須 flushPath（pending 線段必須以「當下 transform」繪出，
  //   否則 save() 改 transform 後 stroke 會把舊線段畫到錯誤座標）
  save(): void {
    this.flushPath();
    this.canvas2d.save();
  }
  restore(): void {
    this.flushPath();
    this.canvas2d.restore();
  }
  translate(dx: Pt, dy: Pt): void {
    this.flushPath();
    this.canvas2d.translate(this.px(dx), this.px(dy));
  }
  rotate(rad: number): void {
    this.flushPath();
    this.canvas2d.rotate(rad);
  }

  /**
   * Sprint 59：對外明確 flush 點。CanvasRenderer 在 render() 收尾時可呼叫確保最後一批 line 出來。
   *
   * 內部 ops 已在每個非 drawLine op 前自動 flush；此 method 只給「caller 想保證流程結束前 paint 完」
   * 的場景（VR 截圖前、unit test 觀察 stroke 次數等）。
   */
  flush(): void {
    this.flushPath();
  }

  /** pt → px 整數化（避免亞像素模糊）。 */
  private px(pt: Pt): number {
    return pt * this.scale;
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Sprint 57 string memoization（安全版：只 memoize 字串輸出、不動 canvas state）
//
// 對 text-heavy 文件，per-page 數百次 fillText 共用相同 (bold|italic|fontSize|family)；
// memoize 後跳過 toFixed + 字串拼接，但每次 canvas.font = X 仍照舊（V8 解析仍跑）。
// 量化助益：較弱（純字串拼接 vs V8 font parse），但完全安全、VR byte-identical。
// ─────────────────────────────────────────────────────────────────────────────

const colorCache: Map<string, string> = new Map();
const COLOR_CACHE_MAX = 256;

/** 6 位 hex（不含 #）→ CSS color。容忍已含 # 與 3 位 short form。 */
export function toCssColor(color: string): string {
  if (!color) return '#000000';
  const cached = colorCache.get(color);
  if (cached) return cached;
  let c = color.trim();
  let result: string;
  if (c.startsWith('#')) result = c;
  else if (c.length === 3) result = `#${c[0]}${c[0]}${c[1]}${c[1]}${c[2]}${c[2]}`;
  else result = `#${c}`;
  // 簡單封頂：滿了清掉重來（color 種類有限、不會頻繁觸發）
  if (colorCache.size >= COLOR_CACHE_MAX) colorCache.clear();
  colorCache.set(color, result);
  return result;
}

const fontCache: Map<string, string> = new Map();
const FONT_CACHE_MAX = 512;

/**
 * RenderTextStyle → CSS font string（自動把 fontSize_pt × scale 轉為 px）。
 *
 * Canvas font 字級必須用 px 單位；scale 預設 96/72。
 *
 * Sprint 57：memoize on (bold|italic|fontSize|fontFamily|scale) key 避免重複拼接 + toFixed。
 */
export function toCssFont(style: RenderTextStyle, scale: number = DEFAULT_SCALE): string {
  const key = `${style.bold ? '1' : '0'}|${style.italic ? '1' : '0'}|${style.fontSize}|${style.fontFamily ?? ''}|${scale}`;
  const cached = fontCache.get(key);
  if (cached) return cached;
  const parts: string[] = [];
  if (style.italic) parts.push('italic');
  if (style.bold) parts.push('bold');
  parts.push(`${(style.fontSize * scale).toFixed(2)}px`);
  parts.push(formatFontFamily(style.fontFamily));
  const result = parts.join(' ');
  if (fontCache.size >= FONT_CACHE_MAX) fontCache.clear();
  fontCache.set(key, result);
  return result;
}

function formatFontFamily(family?: string): string {
  if (!family) return 'sans-serif';
  // 含空白 / 引號的 family name 用雙引號包
  if (/[\s,]/.test(family)) return `"${family.replace(/"/g, '\\"')}"`;
  return family;
}

/** Sprint 57 測試用：清空 memoize cache（避免 vitest 跨檔案污染）。 */
export function _clearRenderCachesForTest(): void {
  colorCache.clear();
  fontCache.clear();
}
