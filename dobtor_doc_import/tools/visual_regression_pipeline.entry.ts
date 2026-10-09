/**
 * Sprint 14 — Visual Regression 瀏覽器端 pipeline 入口
 *
 * 由 rollup.visual_regression.config.js 打包成 IIFE，
 * 在 puppeteer 載入的 harness HTML 內以 `<script>` 標籤掛載。
 *
 * 對外 API（attach 到 window.__dobtorPipeline）：
 *   - render(arrayBuffer, container, options): 解析 .docx → 排版 → 逐頁繪到 <canvas>
 *   - parse(arrayBuffer): 純解析（debug 用）
 *   - layout(documentNode, options): 純排版（debug 用）
 *
 * 為何用 IIFE：
 *   - Puppeteer harness 以本機 file:// 載入 HTML，無 module bundler；
 *     IIFE 自動 attach 到 window，省略 import map 設定。
 *   - 不需要 ESM tree-shake；視覺回歸是手動觸發，bundle size 容忍度高。
 *
 * 設計取捨：
 *   - 使用 BrowserCanvasRenderContext（Sprint 9）+ CanvasRenderer（Sprint 8）
 *   - DPI 預設 150（Sprint 30 修正：goldens 為 1241×1754 = A4 @ 150 DPI；
 *     之前 96 DPI 註解錯誤，造成 pixelmatch crop 比較失準）
 *   - 每頁一個 <canvas class="ce-page">，與舊 harness 的 selector 相容（CLI 不需改 selector）
 */

import { OoxmlParser } from '../static/src/core/ooxml';
import { layoutDocument } from '../static/src/core/layout';
import { CanvasRenderer, BrowserCanvasRenderContext } from '../static/src/core/render';
import type { BrowserCanvas2D } from '../static/src/core/render';
import type { DocumentNode } from '../static/src/core/ooxml/ast/types';
import type { DocumentLayout, LayoutOptions } from '../static/src/core/layout';
import { BrowserTextMetrics } from '../static/src/core/layout/BrowserTextMetrics';
import { FontMetricsAdapter } from '../static/src/core/layout/FontMetricsAdapter';
import { AstCache, IdbAstCache, computeDocxHash } from '../static/src/core/cache/ast_cache';
import type { PipelineAstCache } from '../static/src/core/cache/ast_cache';
import { ImageDecodeCache } from '../static/src/core/cache/image_decode_cache';
import { ImageBitmapIdbCache } from '../static/src/core/cache/image_bitmap_idb_cache';
import {
  LayoutCache,
  hashLayoutOptions,
  composeLayoutKey,
} from '../static/src/core/cache/layout_cache';

interface RenderOptions {
  dpi?: number;
  layoutOptions?: LayoutOptions;
  /**
   * Sprint 162：opt-in 啟用 tab stop 解析（Strategy C）。
   *
   * true → 從解析出的 `documentNode.settings.defaultTabStop`（無則 OOXML 預設 36pt）
   * 注入 `LayoutOptions.defaultTabStop`，LineBreaker 把 `\t` 解析為推進到下一個 tab stop。
   * 省略 / false → tab 維持空白寬度（VR 預設路徑、baseline byte-identical）。
   */
  enableTabStops?: boolean;
  /** 限制最多渲染 N 頁，避免極端文件 OOM */
  maxPages?: number;
  /**
   * Sprint 51：AST 快取實例（in-memory sync 或 IDB-backed async 皆可）。
   * 傳入 → 啟用快取；省略 → 維持原行為（VR 預設不啟用）。
   */
  cache?: PipelineAstCache;
  /**
   * Sprint 53：可視頁虛擬化。傳入 true 用預設、物件可指定 prerender 頁數與 rootMargin；
   * 省略 → 維持原行為（所有頁同步 paint，VR 預設行為）。
   *
   * 啟用後：初始只 paint 前 prerenderPages 頁；其餘 canvas 仍創建並占位（白底 + 正確尺寸），
   * 用 IntersectionObserver 在滾動進入 rootMargin 內時才 paint 該頁。
   *
   * VR 截圖會 cropOrPad 補白邊，不啟用 virtualize 時行為與 Sprint 14 完全一致。
   */
  virtualize?: boolean | VirtualizeOptions;
  /**
   * Sprint 54：image decode 結果快取。傳入 → 啟用、preload 時用 dataURL 當 key 撈 HTMLImageElement；
   * 省略 → 維持原行為（每次 render 都重新 decode，VR 預設）。
   */
  imageCache?: ImageDecodeCache;
  /**
   * Sprint 56：ImageBitmap + IDB 跨 page persistence cache。
   *   - 比 imageCache 多兩個能力：(1) 跨 tab/session 命中（IDB L2）(2) 用 ImageBitmap 而非 HTMLImageElement
   *   - 若同時設定 imageCache + imageBitmapCache，imageBitmapCache 優先（兩者互斥）
   *   - 省略 → 維持原行為（VR 預設）
   */
  imageBitmapCache?: ImageBitmapIdbCache;
  /**
   * Sprint 58：Layout 結果快取。
   *   - 命中 → 跳過 layoutDocument（warm 7.5% layout 階段降到 ~0）
   *   - key = docxHash + hash(layoutOptions)；要 docxHash 故需同時開 options.cache（取 AST hash）；未開 cache 時 layoutCache 自動 no-op
   *   - 省略 → 維持原行為（VR 預設）
   */
  layoutCache?: LayoutCache;
  /**
   * Sprint 61：使用 BrowserTextMetrics 取代 EstimateMetrics（用 canvas.measureText 真實字寬）。
   *   - 傳入 BrowserTextMetrics instance 或 true → pipeline 自建 instance + 注入 layoutOptions.metrics
   *   - 省略 / false → 維持 EstimateMetrics（VR 預設、與 Sprint 50-60 baseline 一致）
   *   - layoutCache 若也啟用，layoutCache key 含 layoutOptions hash 自動區分 metrics 模式（不會污染 cache）
   */
  browserTextMetrics?: BrowserTextMetrics | boolean;
  /**
   * Sprint 62：使用 FontMetricsAdapter（opentype.js 真實字型 metric）。
   *   - 傳入 FontMetricsAdapter instance（caller 須已 registerFont 對應字型 bytes）→ pipeline 注入 layoutOptions.metrics
   *   - 省略 → 維持 EstimateMetrics 或前面 metrics 設定
   *   - 優先序：fontAdapter > browserTextMetrics > 預設 EstimateMetrics
   *   - 與 layoutCache 互斥（同 Sprint 61 邏輯）— adapter 是 caller-injected instance、不穩 cache key
   */
  fontAdapter?: FontMetricsAdapter;
}

/** Sprint 53：可視頁虛擬化設定。 */
export interface VirtualizeOptions {
  /** 同步 paint 前 N 頁（預設 2）。0 = 全部 deferred、適合大文件冷啟。 */
  prerenderPages?: number;
  /** IntersectionObserver rootMargin（預設 "200px"）。Pre-paint 進入緩衝區內的下一頁。 */
  rootMargin?: string;
}

/**
 * Sprint 50：pipeline 四段耗時（ms），給 scripts/perf_baseline.mjs 建效能基線用。
 * 純加性欄位 — VR v14 只讀 pageCount/warnings 等，不受影響。
 *
 * Sprint 51：加 hashMs（SHA-256 計算）+ cacheHit 旗標。
 * Sprint 53：加 paintedPages（virtualize 下實際同步 paint 的頁數）。
 */
interface PipelineTiming {
  /** Sprint 51：docx bytes → SHA-256 hex（crypto.subtle）。未啟用 cache 則為 0 */
  hashMs: number;
  /** OoxmlParser.parse(arrayBuffer)：docx zip 解壓 + XML → Document AST。cacheHit=true 時為 0 */
  parseMs: number;
  /** layoutDocument(sections)：AST → DocumentLayout（斷行、表格排版、分頁） */
  layoutMs: number;
  /** preloadImages：media dataURL → HTMLImageElement（含瀏覽器 image decode） */
  preloadMs: number;
  /**
   * Sprint 8：CanvasRenderer 同步 paint 耗時。
   * Sprint 53：virtualize 啟用時只計入初始 paint 的前 prerenderPages 頁；
   *           其餘 deferred 頁由 IntersectionObserver 觸發、不計入此欄位。
   */
  renderMs: number;
  /** 以上各段總和（不含 base64 decode、不含 puppeteer screenshot） */
  totalMs: number;
  /** Sprint 51：本次 render 是否命中 AST cache（未啟用 cache 永遠 false） */
  cacheHit: boolean;
  /** Sprint 53：本次同步 paint 的頁數（virtualize off → = pageCount；on → = prerenderPages 或更少） */
  paintedPages: number;
  /** Sprint 54：本次 preload 命中 image cache 的圖片數（未啟用 imageCache 永遠 0） */
  imageCacheHits: number;
  /** Sprint 56：本次 preload 命中 imageBitmapCache 的 L1 + L2 命中總數（未啟用永遠 0） */
  imageBitmapCacheHits: number;
  /** Sprint 58：本次 layout 是否命中 layoutCache（未啟用永遠 false） */
  layoutCacheHit: boolean;
}

interface RenderResult {
  pageCount: number;
  pages: Array<{ widthPt: number; heightPt: number; widthPx: number; heightPx: number }>;
  warnings: string[];
  /** Sprint 15：實際載入的圖片數（dataURL → HTMLImageElement onload 成功） */
  imagesLoaded: number;
  /** Sprint 15：因為 onerror 而跳過的圖片 rId 清單 */
  imageErrors: string[];
  /** Sprint 50：四段耗時基線 */
  timing: PipelineTiming;
}

const DEFAULT_DPI = 150;
/** OOXML §17.15.1.25 `w:defaultTabStop` 預設值：720 twip = 36pt。 */
const OOXML_DEFAULT_TAB_STOP_PT = 36;

function ptToPx(pt: number, dpi: number): number {
  return pt * (dpi / 72);
}

/**
 * Sprint 15：把 documentNode.media（rId → dataURL）pre-load 成 HTMLImageElement Map。
 * Render 是同步的（CanvasRenderer.render → drawImage 期望立即拿到 image），
 * 因此必須先 await 全部 onload 才開始畫。
 *
 * @returns { rId → HTMLImageElement }；onerror 的 rId 不在 Map 內（resolver 回 undefined → 跳過）
 */
async function preloadImages(
  media: Map<string, string>,
  cache?: ImageDecodeCache,
  bitmapCache?: ImageBitmapIdbCache,
): Promise<{
  // Map 元素可能是 HTMLImageElement（傳統 cache 或無 cache）或 ImageBitmap（bitmap cache 命中/寫入）
  // BrowserCanvasRenderContext.drawImage 走 unknown → ctx.drawImage()，兩者皆為 CanvasImageSource
  map: Map<string, CanvasImageSource>;
  errors: string[];
  cacheHits: number;
  bitmapCacheHits: number;
}> {
  const map = new Map<string, CanvasImageSource>();
  const errors: string[] = [];
  const tasks: Promise<void>[] = [];
  let cacheHits = 0;
  let bitmapCacheHits = 0;

  // Sprint 56：bitmapCache 優先（含 L1 + L2）；fallback 到 Sprint 54 imageCache；最後才是 fresh decode
  for (const [rId, dataUrl] of media) {
    if (bitmapCache) {
      // 同步處理：bitmapCache.get 是 async，要平行化所以包進 task
      const task = (async () => {
        const bitmap = await bitmapCache.get(dataUrl);
        if (bitmap) {
          map.set(rId, bitmap);
          bitmapCacheHits++;
          return;
        }
        // miss → 用 Image onload 解碼，再 createImageBitmap 並 put 進 bitmapCache
        // createImageBitmap 不可用時降級為 HTMLImageElement（仍正確 render、但不 promote cache）
        // 必須 await put 完成、確保 IDB transaction commit 才 page.close（否則跨 page L2 hit 失敗）
        // Sprint 56 量測證實：fire-and-forget put 在 page1 close 時 tx 還沒 commit、page2 撈不到
        const imgPromise = new Promise<HTMLImageElement | null>((resolve) => {
          const img = new Image();
          img.onload = () => resolve(img);
          img.onerror = () => {
            errors.push(rId);
            resolve(null);
          };
          img.src = dataUrl;
        });
        const img = await imgPromise;
        if (!img) return;
        try {
          if (typeof createImageBitmap !== 'undefined') {
            const bm = await createImageBitmap(img);
            map.set(rId, bm);
            // 必須 await：保證 IDB tx commit 後才 resolve task；
            // 失敗（IDB quota 等）由 ImageBitmapIdbCache 內部 try/catch 吸收，不會 throw
            await bitmapCache.put(dataUrl, bm);
          } else {
            map.set(rId, img);
          }
        } catch {
          // createImageBitmap 失敗時降級為 HTMLImageElement
          map.set(rId, img);
        }
      })();
      tasks.push(task);
      continue;
    }
    // Sprint 54 path：HTMLImageElement L1-only cache
    if (cache) {
      const cached = cache.get(dataUrl);
      if (cached) {
        map.set(rId, cached);
        cacheHits++;
        continue;
      }
    }
    const img = new Image();
    const task = new Promise<void>((resolve) => {
      img.onload = () => {
        map.set(rId, img);
        if (cache) cache.put(dataUrl, img);
        resolve();
      };
      img.onerror = () => {
        errors.push(rId);
        resolve(); // 不拒絕，讓其他圖繼續
      };
    });
    img.src = dataUrl;
    tasks.push(task);
  }
  await Promise.all(tasks);
  return { map, errors, cacheHits, bitmapCacheHits };
}

async function render(
  arrayBuffer: ArrayBuffer,
  container: HTMLElement,
  options: RenderOptions = {},
): Promise<RenderResult> {
  const dpi = options.dpi ?? DEFAULT_DPI;

  // Sprint 51：若有 cache，先 hash → 查 cache；miss 才 parse + put。
  // Sprint 50：四段計時。performance.now() 為單調時鐘，不受系統時間調整影響。
  // Sprint 58：layoutCache 也需要 docx hash 當 key；若有 layoutCache 但沒 cache，仍計算 hash
  let hashMs = 0;
  let cacheHit = false;
  let documentNode: DocumentNode | undefined;
  let docxHash: string | null = null;
  const tStart = performance.now();

  if (options.cache || options.layoutCache) {
    const tHashStart = performance.now();
    docxHash = await computeDocxHash(arrayBuffer);
    hashMs = performance.now() - tHashStart;
  }

  if (options.cache && docxHash) {
    const cached = await options.cache.get(docxHash);
    if (cached) {
      documentNode = cached;
      cacheHit = true;
    } else {
      documentNode = new OoxmlParser().parse(arrayBuffer);
      await options.cache.put(docxHash, documentNode);
    }
  } else {
    documentNode = new OoxmlParser().parse(arrayBuffer);
  }
  const tParseEnd = performance.now();
  // parseMs 不含 hashMs：hit 時 parseMs ≈ 0；miss 時 parseMs = 原本 parse 時間
  const parseMs = tParseEnd - tStart - hashMs;

  // Sprint 61-62：metrics 優先序 fontAdapter > browserTextMetrics > 預設 EstimateMetrics
  let effectiveLayoutOptions: LayoutOptions = options.layoutOptions ?? {};
  if (options.fontAdapter) {
    effectiveLayoutOptions = { ...effectiveLayoutOptions, metrics: options.fontAdapter };
  } else if (options.browserTextMetrics) {
    const metrics =
      options.browserTextMetrics instanceof BrowserTextMetrics
        ? options.browserTextMetrics
        : new BrowserTextMetrics();
    effectiveLayoutOptions = { ...effectiveLayoutOptions, metrics };
  }
  // Sprint 139：numbering 注入 = opt-in（caller 顯式傳入 layoutOptions.numbering 才啟用）
  // 預設不注入以維持 VR baseline byte-identical 軌道（紀律 #1.a）；
  // 階段 C 重生 goldens 後可由 caller 顯式 opt-in 衡量改善。

  // Sprint 162：tab stop 解析 opt-in（Strategy C）。enableTabStops=true 才從
  // documentNode.settings.defaultTabStop 注入；省略 → VR baseline byte-identical。
  if (options.enableTabStops) {
    effectiveLayoutOptions = {
      ...effectiveLayoutOptions,
      defaultTabStop: documentNode.settings?.defaultTabStop ?? OOXML_DEFAULT_TAB_STOP_PT,
    };
  }

  // Sprint 58：layout cache lookup（key = docxHash + opts hash）
  // 注意：caller-injected metrics instance（browserTextMetrics / fontAdapter）序列化進 layoutOptions hash 不穩定；
  // 因此 Sprint 61-62 暫不快取此類模式的 layout（避免 cache key 污染）
  let layout: DocumentLayout;
  let layoutCacheHit = false;
  const layoutCacheable =
    options.layoutCache && docxHash && !options.browserTextMetrics && !options.fontAdapter;
  if (layoutCacheable) {
    const optsHash = await hashLayoutOptions(effectiveLayoutOptions);
    const layoutKey = composeLayoutKey(docxHash!, optsHash);
    const cachedLayout = options.layoutCache!.get(layoutKey);
    if (cachedLayout) {
      layout = cachedLayout;
      layoutCacheHit = true;
    } else {
      layout = layoutDocument(documentNode.sections, effectiveLayoutOptions);
      options.layoutCache!.put(layoutKey, layout);
    }
  } else {
    layout = layoutDocument(documentNode.sections, effectiveLayoutOptions);
  }
  const tLayoutEnd = performance.now();

  // Sprint 15：在開畫之前 pre-load 所有 image
  // Sprint 54：若有 imageCache，命中的 dataURL 跳過 decode、直接重用 HTMLImageElement
  // Sprint 56：若有 imageBitmapCache（含 L2 IDB），命中時跳過 Image.onload，直接拿 ImageBitmap
  const {
    map: imageMap,
    errors: imageErrors,
    cacheHits: imageCacheHits,
    bitmapCacheHits: imageBitmapCacheHits,
  } = await preloadImages(documentNode.media, options.imageCache, options.imageBitmapCache);
  const tPreloadEnd = performance.now();
  const imageResolver = (rId: string) => imageMap.get(rId);

  // 清空 container（避免重複呼叫殘留）
  container.innerHTML = '';

  // Sprint 53：可視頁虛擬化解析（true → 預設物件、false/undefined → null、物件 → 原樣）
  const virtOpts: VirtualizeOptions | null =
    options.virtualize === true ? {} : options.virtualize || null;
  const useVirt = virtOpts !== null;
  const prerenderPages = useVirt ? Math.max(0, virtOpts.prerenderPages ?? 2) : Infinity;
  const rootMargin = virtOpts?.rootMargin ?? '200px';

  /**
   * 真正繪圖一頁的內部 helper。已 paint 過則 no-op（避免 IntersectionObserver 抖動重畫）。
   * 同步：CanvasRenderer + drawImage 是 sync ops；imageResolver 從 preloadImages 已備好的 map 取。
   */
  function paintPage(canvas: HTMLCanvasElement, page: DocumentLayout['pages'][number]): void {
    if (canvas.dataset.painted === '1') return;
    const ctx2d = canvas.getContext('2d');
    if (!ctx2d) throw new Error('Canvas2D context unavailable');
    // 先確保白底（即使先前已 fillRect 過，重畫安全）
    ctx2d.fillStyle = '#ffffff';
    ctx2d.fillRect(0, 0, canvas.width, canvas.height);
    const browserCtx = new BrowserCanvasRenderContext(ctx2d as unknown as BrowserCanvas2D, {
      scale: dpi / 72,
      imageResolver,
    });
    // Sprint 171：OOXML <w:background> 文件背景色 → CanvasRenderer 頁底色
    // Sprint 173：OOXML header VML 浮水印 → CanvasRenderer 每頁繪浮水印
    //   無 <w:background> / 無浮水印（多數 docx）→ 不傳 → 預設行為 byte-identical
    const bgColor = documentNode?.background?.color;
    const wm = documentNode?.watermark;
    const renderer = new CanvasRenderer(browserCtx, {
      ...(bgColor ? { pageBackgroundColor: bgColor } : {}),
      ...(wm ? { watermark: wm } : {}),
    });
    renderer.render({ pages: [page], warnings: [] });
    canvas.dataset.painted = '1';
  }

  // Sprint 53：deferred page 共用 IntersectionObserver（一個 observer 管所有 canvas）
  let observer: IntersectionObserver | null = null;
  if (useVirt && typeof IntersectionObserver !== 'undefined') {
    observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          const canvas = entry.target as HTMLCanvasElement;
          const idx = parseInt(canvas.dataset.pageIndex ?? '-1', 10);
          if (idx >= 0 && idx < layout.pages.length) {
            paintPage(canvas, layout.pages[idx]);
          }
          observer?.unobserve(canvas);
        }
      },
      { root: null, rootMargin },
    );
  }

  const limit = Math.min(layout.pages.length, options.maxPages ?? Number.POSITIVE_INFINITY);
  const pages: RenderResult['pages'] = [];
  let paintedPages = 0;
  for (let i = 0; i < limit; i++) {
    const page = layout.pages[i];
    const widthPx = Math.round(ptToPx(page.width, dpi));
    const heightPx = Math.round(ptToPx(page.height, dpi));

    const canvas = document.createElement('canvas');
    canvas.className = 'ce-page';
    canvas.dataset.pageIndex = String(i);
    canvas.width = widthPx;
    canvas.height = heightPx;
    canvas.style.width = `${widthPx}px`;
    canvas.style.height = `${heightPx}px`;
    canvas.style.background = 'white';
    canvas.style.display = 'block';
    canvas.style.marginBottom = '24px';
    canvas.style.boxShadow = '0 0 4px rgba(0,0,0,0.2)';
    container.appendChild(canvas);

    // 先填白底（goldens 也是白底；deferred page 在 paintPage 觸發前對使用者看是白頁）
    const ctx2d = canvas.getContext('2d');
    if (!ctx2d) {
      throw new Error('Canvas2D context unavailable');
    }
    ctx2d.fillStyle = '#ffffff';
    ctx2d.fillRect(0, 0, widthPx, heightPx);

    if (i < prerenderPages) {
      // 同步 paint：在 prerender 範圍內
      paintPage(canvas, page);
      paintedPages++;
    } else if (observer) {
      // deferred：等 IntersectionObserver 觸發
      observer.observe(canvas);
    } else {
      // useVirt 但 IntersectionObserver 不可用 → degrade 為同步 paint（保證內容仍可見）
      paintPage(canvas, page);
      paintedPages++;
    }

    pages.push({ widthPt: page.width, heightPt: page.height, widthPx, heightPx });
  }
  const tRenderEnd = performance.now();

  const timing: PipelineTiming = {
    hashMs,
    parseMs,
    layoutMs: tLayoutEnd - tParseEnd,
    preloadMs: tPreloadEnd - tLayoutEnd,
    renderMs: tRenderEnd - tPreloadEnd,
    totalMs: tRenderEnd - tStart,
    cacheHit,
    paintedPages,
    imageCacheHits,
    imageBitmapCacheHits,
    layoutCacheHit,
  };

  return {
    pageCount: limit,
    pages,
    warnings: layout.warnings,
    imagesLoaded: imageMap.size,
    imageErrors,
    timing,
  };
}

function parse(arrayBuffer: ArrayBuffer): DocumentNode {
  return new OoxmlParser().parse(arrayBuffer);
}

function layout(documentNode: DocumentNode, options: LayoutOptions = {}): DocumentLayout {
  return layoutDocument(documentNode.sections, options);
}

// 對外掛載
(window as unknown as { __dobtorPipeline: unknown }).__dobtorPipeline = {
  version: 'sprint62',
  render,
  parse,
  layout,
  // Sprint 51：給 scripts/perf_baseline.mjs --cache 模式用
  AstCache,
  // Sprint 52：給 scripts/perf_baseline.mjs --cache-persist 模式用（IDB-backed）
  IdbAstCache,
  // Sprint 54：給 scripts/perf_baseline.mjs --image-cache 模式用
  ImageDecodeCache,
  // Sprint 56：給 scripts/perf_baseline.mjs --image-bitmap-cache / --image-bitmap-persist 模式用
  ImageBitmapIdbCache,
  // Sprint 58：給 scripts/perf_baseline.mjs --layout-cache 模式用
  LayoutCache,
  // Sprint 61：給 scripts/perf_baseline.mjs --browser-metrics 模式用
  BrowserTextMetrics,
  // Sprint 62：給 scripts/visual_regression_v14.mjs --font-metrics 模式用
  FontMetricsAdapter,
  computeDocxHash,
};
