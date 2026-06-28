/**
 * ShapingEngine — HarfBuzz WASM 文字成形引擎封裝
 *
 * Sprint 128 spike 立基（基礎 shape）→ Sprint 265 擴充：
 *   - ShapeOptions：script/language/direction/features/clusterLevel
 *   - 自動 Script 偵測（Unicode block → ISO 15924）
 *   - OpenType features 控制（kern/liga/clig 等可開關）
 *   - measureRun(text, family, sizePt) → 物理寬度（pt）
 *
 * 職責：
 *   - 載入 harfbuzzjs WASM（lazy，第一次 shape 才實際載入）
 *   - 把字型 byte buffer 包裝為 hb.face + hb.font
 *   - 對 (text, font) 呼叫 hb.shape，回傳精確 glyph[]（含 advance / offset）
 *   - 提供 measureRun 取代 ctx.measureText（Phase 6 Layout Engine 用）
 *
 * 規格參考：
 *   - HarfBuzz API docs：harfbuzz.github.io
 *   - ISO 15924 script codes（Latn / Hani / Hira / Kana / Hang / Arab / Hebr / ...）
 *   - OpenType feature tags：https://learn.microsoft.com/en-us/typography/opentype/spec/featurelist
 *
 * 為何 lazy + async：
 *   - WASM 體積 ~200KB（hb.wasm + hb.js）；Sprint 128 bundle audit 判 production
 *     不可接受 → 整合範圍限於 Layout Engine 階段、不進 OoxmlParser 主流程
 *   - canvas-editor 內部用 Browser measureText、不接受外部 metrics；Phase 6 自寫
 *     Layout Engine 才會真正使用此引擎
 */

/**
 * Sprint 279：browser-compat refactor。`createRequire` 移到 lazy fallback
 * 內、由 typeof 環境偵測決定路徑；不在 module top-level import 避免
 * browser ESM resolver 在 load 時就炸（即使 caller 已 inject loader）。
 *
 * 設計：caller-injectable hbModuleLoader（Sprint 64 ProtonClone dependency
 * injection pattern 重現）：
 *   - 預設 = Node 端走 dynamic import('node:module').createRequire('harfbuzzjs')
 *   - Browser caller 必須先呼叫 setHbModuleLoader(() => loadFromBrowser())
 *     才能呼叫 shape() / measureRun()
 *
 * 為何不寫死 browser path：harfbuzzjs WASM ~400KB、不同 browser caller
 * （Phase 6 Layout / canvas-editor fork / 獨立模組）對 wasm 取得路徑需求
 * 不一（CDN / static asset / inline base64），由 caller 決定。
 */

/** 單一 glyph 的成形結果（HarfBuzz 標準 + cluster 字元位置）。 */
export interface ShapedGlyph {
  /** 字型內 glyph index（0 = .notdef，字型不支援該字元） */
  glyphId: number;
  /** Horizontal advance（字型 unitsPerEm 為單位） */
  xAdvance: number;
  /** Vertical advance（橫排為 0） */
  yAdvance: number;
  /** Horizontal placement offset */
  xOffset: number;
  /** Vertical placement offset */
  yOffset: number;
  /** 該 glyph 對應原文字 cluster index */
  cluster: number;
}

/**
 * Sprint 265：shape() 與 measureRun() 的進階選項。
 *
 * - `script` / `language` / `direction`：強制指定 segment 屬性；省略時走
 *   `buffer.guessSegmentProperties()` 自動偵測
 * - `features`：OpenType feature 控制（如 'kern,liga'、'-kern' 關閉）
 * - `clusterLevel`：HarfBuzz cluster level（0 / 1 / 2，預設 0；CJK 通常 0、
 *   Arabic / Indic 複雜文字可能要 1 或 2）
 */
export interface ShapeOptions {
  script?: string;
  language?: string;
  direction?: 'ltr' | 'rtl' | 'ttb' | 'btt';
  features?: string;
  clusterLevel?: 0 | 1 | 2;
}

/** Sprint 265：measureRun() 結果（物理寬度單位 pt + per-glyph 詳細）。 */
export interface RunMetrics {
  /** 整段 run 的水平 advance 總和（pt） */
  widthPt: number;
  /** 整段 run 的垂直 advance 總和（pt、橫排為 0） */
  heightPt: number;
  /** glyph 數（含 cluster 內子 glyph） */
  glyphCount: number;
  /** 每個 glyph 的水平 advance（pt） */
  advancesPt: number[];
  /** shaped glyphs 原始輸出（cluster / offset 等診斷用） */
  glyphs: ShapedGlyph[];
}

/** Sprint 266：Glyph cache 統計（診斷 / 效能調校用）。 */
export interface ShapingCacheStats {
  hits: number;
  misses: number;
  entries: number;
  maxEntries: number;
  /** 命中率（0..1）；無 lookup 時為 NaN */
  hitRate: number;
}

/** harfbuzzjs 的最小型別宣告（避開直接 import 它的型別檔） */
interface HBInstance {
  createBlob: (data: Uint8Array) => unknown;
  createFace: (blob: unknown) => unknown;
  createFont: (face: unknown) => unknown;
  createBuffer: () => HBBuffer;
  shape: (font: unknown, buffer: unknown, features?: string) => void;
}

interface HBBuffer {
  addText: (text: string) => void;
  guessSegmentProperties: () => void;
  setDirection?: (dir: 'ltr' | 'rtl' | 'ttb' | 'btt') => void;
  setScript?: (script: string) => void;
  setLanguage?: (lang: string) => void;
  setClusterLevel?: (level: number) => void;
  json: () => Array<{
    ax: number;
    ay: number;
    dx: number;
    dy: number;
    g: number;
    cl: number;
  }>;
}

/**
 * 載入 harfbuzzjs（CJS Promise pattern）。
 *
 * harfbuzzjs index.js 是 `module.exports = new Promise(...)`：
 *   - 在純 Node CJS：直接 await require('harfbuzzjs')
 *   - 在 ESM / vitest：用 createRequire 取 CJS module.exports，再 await
 *
 * Sprint 279：caller-injectable loader。
 *   - 預設（Node）：dynamic `import('node:module')` + createRequire path
 *   - Browser：caller 須先呼叫 setHbModuleLoader(loader) 注入
 *
 * 此函式封裝了載入細節並 cache 結果。
 */
let hbInstancePromise: Promise<HBInstance> | undefined;
let hbModuleLoader: (() => Promise<HBInstance>) | undefined;

/**
 * Sprint 279：注入 harfbuzzjs 載入器（browser 端使用）。
 *
 * Browser 典型 caller：
 * ```ts
 * setHbModuleLoader(async () => {
 *   const createHarfBuzz = (window as any).createHarfBuzz;
 *   const hbjs = (window as any).hbjs;
 *   const mod = await createHarfBuzz({ locateFile: (p) => '/static/wasm/' + p });
 *   return hbjs(mod) as HBInstance;
 * });
 * ```
 *
 * 紀律 #21：純 setter / 不副作用、不開始載入 wasm；caller 自負 race 風險。
 * 注入後第一次 shape() 才會 invoke loader。重複注入會 reset cache。
 */
export function setHbModuleLoader(loader: () => Promise<HBInstance>): void {
  hbModuleLoader = loader;
  hbInstancePromise = undefined;  // reset cache，下次 shape() 走新 loader
}

/**
 * Sprint 279：reset cache（測試用、不對外暴露 cache 清除予 production）。
 *
 * 紀律 #21：vitest 測試 setHbModuleLoader 後互不污染。
 * 預設 export `__resetHbForTesting` 已存在（Sprint 128 加）、本 helper
 * 與其分工 — resetHbModuleLoader 也清 loader injection。
 */
export function __resetHbModuleLoaderForTesting(): void {
  hbModuleLoader = undefined;
  hbInstancePromise = undefined;
}

async function loadHb(): Promise<HBInstance> {
  if (!hbInstancePromise) {
    if (hbModuleLoader) {
      // Sprint 279：caller-injected path（browser / 自訂 wasm 來源）
      hbInstancePromise = hbModuleLoader();
    } else {
      // 預設 Node 路徑：dynamic import 避免在 browser bundle 時 ESM
      // resolver 看到 'node:module' top-level import 直接拒絕
      hbInstancePromise = (async () => {
        const { createRequire } = await import('node:module');
        const localRequire = createRequire(import.meta.url);
        const mod = localRequire('harfbuzzjs');
        return (mod as Promise<HBInstance>);
      })();
    }
  }
  return hbInstancePromise;
}

interface FontEntry {
  bytes: Uint8Array;
  hbFont?: unknown;  // 第一次 shape 時 lazy 建立
  unitsPerEm?: number;  // Sprint 265：lazy 取 opentype.js parse 結果、measureRun 換算 pt 用
}

/**
 * Sprint 265：以 Unicode block 啟發式偵測 ISO 15924 script code。
 *
 * 對齊 OOXML 多語混排場景：W:rFonts 內 hAnsi / eastAsia / cs 三組字型分流；
 * shape 時可用此函式判定文字主要 script、再決定走哪組字型 metric。
 *
 * 偵測規則（取第一個非空白字元的 Unicode block）：
 *   - 0x4E00-0x9FFF：CJK Unified Ideographs → 'hani'（Han）
 *   - 0x3040-0x309F：Hiragana → 'hira'
 *   - 0x30A0-0x30FF：Katakana → 'kana'
 *   - 0xAC00-0xD7AF：Hangul Syllables → 'hang'
 *   - 0x0600-0x06FF：Arabic → 'arab'
 *   - 0x0590-0x05FF：Hebrew → 'hebr'
 *   - 0x0900-0x097F：Devanagari → 'deva'
 *   - 0x0E00-0x0E7F：Thai → 'thai'
 *   - 預設：'latn'（Latin、含 ASCII + Latin-1 Supplement + Cyrillic 等）
 *
 * 紀律 #21：未知 → 'latn'（最廣支援的 fallback）；caller 可用
 *   `buffer.guessSegmentProperties()`（HarfBuzz 內建）覆蓋。
 */
export function detectScript(text: string): string {
  for (const ch of text) {
    const cp = ch.codePointAt(0);
    if (cp === undefined) continue;
    if (cp <= 0x20) continue; // 跳空白與控制字元
    if (cp >= 0x4E00 && cp <= 0x9FFF) return 'hani';
    if (cp >= 0x3400 && cp <= 0x4DBF) return 'hani'; // CJK Ext A
    if (cp >= 0x20000 && cp <= 0x2A6DF) return 'hani'; // CJK Ext B
    if (cp >= 0x3040 && cp <= 0x309F) return 'hira';
    if (cp >= 0x30A0 && cp <= 0x30FF) return 'kana';
    if (cp >= 0xAC00 && cp <= 0xD7AF) return 'hang';
    if (cp >= 0x0600 && cp <= 0x06FF) return 'arab';
    if (cp >= 0x0590 && cp <= 0x05FF) return 'hebr';
    if (cp >= 0x0900 && cp <= 0x097F) return 'deva';
    if (cp >= 0x0E00 && cp <= 0x0E7F) return 'thai';
    return 'latn';
  }
  return 'latn';
}

/**
 * Sprint 265：script → BCP 47 language code 啟發式預設。
 *
 * 多數 user 用 ChienYi 為繁體中文場景；給 hani → zh-tw、其他保留 hb 預設行為。
 */
export function defaultLanguageForScript(script: string): string {
  switch (script) {
    case 'hani': return 'zh-tw';
    case 'hira':
    case 'kana': return 'ja';
    case 'hang': return 'ko';
    case 'arab': return 'ar';
    case 'hebr': return 'he';
    case 'deva': return 'hi';
    case 'thai': return 'th';
    default: return 'en';
  }
}

/**
 * Sprint 265：script → direction 啟發式（RTL 偵測）。
 */
export function defaultDirectionForScript(script: string): 'ltr' | 'rtl' {
  return (script === 'arab' || script === 'hebr') ? 'rtl' : 'ltr';
}

/** Sprint 266：cache 預設容量上限（FIFO 淘汰）。 */
const DEFAULT_SHAPE_CACHE_MAX_ENTRIES = 10000;

export class ShapingEngine {
  /** 已載入的字型（key = font family name）。 */
  private fonts = new Map<string, FontEntry>();

  /**
   * Sprint 266：Glyph cache — 對齊 (text, family, sizePt, options) → ShapedGlyph[]。
   *
   * Layout pass 對重複 run（同 props + 同 text）秒回；典型場景：
   *   - 同段落 multi-line 重排（baseline + 試算）
   *   - 連續頁同 header / footer 重複渲染
   *   - VR baseline 大規模重跑
   *
   * 淘汰策略：FIFO（Map preserves insertion order；簡單、無 LRU 開銷）。
   * 紀律 #21：cache 是純記憶體加速、可隨時 clearShapeCache 重置、不影響正確性。
   */
  private shapeCache = new Map<string, ShapedGlyph[]>();
  private shapeCacheHits = 0;
  private shapeCacheMisses = 0;
  private shapeCacheMaxEntries = DEFAULT_SHAPE_CACHE_MAX_ENTRIES;

  /**
   * 註冊字型 byte buffer（從檔案 / 網路 / Odoo Asset 取得後傳入）。
   *
   * @param family 字型 family name（與 RunProps.fontFamily 對應）
   * @param bytes 字型檔位元組（TTF / OTF）
   */
  loadFont(family: string, bytes: Uint8Array): void {
    this.fonts.set(family, { bytes });
  }

  /** 列出已載入的字型 family。 */
  listFonts(): string[] {
    return Array.from(this.fonts.keys());
  }

  /**
   * 對指定字型 + 文字做 shaping。
   *
   * Sprint 265：加 ShapeOptions（script/language/direction/features/clusterLevel）。
   *   省略時走 buffer.guessSegmentProperties() 自動偵測。
   *
   * @param text 原文字（可含 CJK / 西文混排 / 連字 / 變音符號）
   * @param family 字型 family name（必須先呼叫 loadFont 註冊）
   * @param sizePt 字級（點 pt）— Phase 6 Layout Engine 換算 advance 為 pt 用
   * @param options 進階成形選項（Sprint 265）
   * @returns ShapedGlyph[]，依文字順序排列
   * @throws Error 若字型未註冊或 hb 載入失敗
   */
  async shape(
    text: string,
    family: string,
    _sizePt: number,
    options?: ShapeOptions,
  ): Promise<ShapedGlyph[]> {
    const entry = this.fonts.get(family);
    if (!entry) {
      throw new Error(`ShapingEngine: font "${family}" not loaded — call loadFont() first`);
    }
    // Sprint 266：cache lookup（命中則直接回；未命中走 hb.shape 後寫入）
    const cacheKey = this.makeShapeCacheKey(text, family, _sizePt, options);
    const cached = this.shapeCache.get(cacheKey);
    if (cached !== undefined) {
      this.shapeCacheHits++;
      return cached;
    }
    this.shapeCacheMisses++;

    const hb = await loadHb();

    // Lazy 建立 hb.face / hb.font（每個 family 只建一次）
    if (!entry.hbFont) {
      const blob = hb.createBlob(entry.bytes);
      const face = hb.createFace(blob);
      entry.hbFont = hb.createFont(face);
    }

    const buffer = hb.createBuffer();
    buffer.addText(text);

    // Sprint 265：先套用顯式 options、無則退回 guessSegmentProperties
    const hasExplicit = options?.script !== undefined
      || options?.language !== undefined
      || options?.direction !== undefined;
    if (hasExplicit) {
      if (options?.direction !== undefined && buffer.setDirection) buffer.setDirection(options.direction);
      if (options?.script !== undefined && buffer.setScript) buffer.setScript(options.script);
      if (options?.language !== undefined && buffer.setLanguage) buffer.setLanguage(options.language);
      // 若 caller 只指定部分 → 其餘走 guessSegmentProperties
      if (options?.script === undefined || options?.language === undefined || options?.direction === undefined) {
        buffer.guessSegmentProperties();
      }
    } else {
      buffer.guessSegmentProperties();
    }
    if (options?.clusterLevel !== undefined && buffer.setClusterLevel) {
      buffer.setClusterLevel(options.clusterLevel);
    }

    // Sprint 265：features 字串（comma-separated OpenType tags、'-kern' 可關閉）
    hb.shape(entry.hbFont!, buffer, options?.features);

    const glyphs: ShapedGlyph[] = buffer.json().map((g) => ({
      glyphId: g.g,
      xAdvance: g.ax,
      yAdvance: g.ay,
      xOffset: g.dx,
      yOffset: g.dy,
      cluster: g.cl,
    }));
    // Sprint 266：寫入 cache（達上限時 FIFO 淘汰最早 entry）
    if (this.shapeCache.size >= this.shapeCacheMaxEntries) {
      const oldestKey = this.shapeCache.keys().next().value;
      if (oldestKey !== undefined) this.shapeCache.delete(oldestKey);
    }
    this.shapeCache.set(cacheKey, glyphs);
    return glyphs;
  }

  /**
   * Sprint 266：生成 cache key（穩定字串，無 JSON 鍵序差異）。
   *
   * 包含所有可能影響 shaping 結果的因素：font family、sizePt、script、language、
   * direction、features、clusterLevel、text。sizePt 在 hb.shape 不影響 advance
   * 設計單位（unitsPerEm-relative），但 measureRun 用 sizePt 換算 pt——key
   * 內含 sizePt 是為 measureRun 階段的衍生 cache（per-size advance 已 scale）。
   * 但目前 shape() 結果為 design units、與 sizePt 無關；為簡化、cache 仍依
   * sizePt 區分（保守、未來收緊：可只用 design units cache 然後 scale）。
   */
  private makeShapeCacheKey(
    text: string,
    family: string,
    sizePt: number,
    options?: ShapeOptions,
  ): string {
    const parts = [
      family,
      String(sizePt),
      options?.script ?? '',
      options?.language ?? '',
      options?.direction ?? '',
      options?.features ?? '',
      String(options?.clusterLevel ?? ''),
      text,
    ];
    return parts.join('');
  }

  /**
   * Sprint 266：取得 cache 統計（hit/miss/entries/hitRate）。
   *
   * 觀測點：
   *   - hitRate 應隨 Layout pass 累積上升（同段落 trial-and-error 重排會大量 hit）
   *   - misses 不會降；hits 線性增長
   *   - entries 受 maxEntries 上限制約（FIFO 淘汰）
   */
  getCacheStats(): ShapingCacheStats {
    const total = this.shapeCacheHits + this.shapeCacheMisses;
    return {
      hits: this.shapeCacheHits,
      misses: this.shapeCacheMisses,
      entries: this.shapeCache.size,
      maxEntries: this.shapeCacheMaxEntries,
      hitRate: total > 0 ? this.shapeCacheHits / total : NaN,
    };
  }

  /** Sprint 266：清除 cache（測試 / 字型 / 文件熱更新場景）。 */
  clearShapeCache(): void {
    this.shapeCache.clear();
    this.shapeCacheHits = 0;
    this.shapeCacheMisses = 0;
  }

  /** Sprint 266：調整 cache 容量上限（仍走 FIFO 淘汰）。 */
  setShapeCacheMaxEntries(n: number): void {
    if (n < 0 || !Number.isFinite(n)) throw new Error(`setShapeCacheMaxEntries: invalid n=${n}`);
    this.shapeCacheMaxEntries = Math.floor(n);
    // 立即淘汰超量 entries
    while (this.shapeCache.size > this.shapeCacheMaxEntries) {
      const oldestKey = this.shapeCache.keys().next().value;
      if (oldestKey === undefined) break;
      this.shapeCache.delete(oldestKey);
    }
  }

  /**
   * Sprint 265：取得字型 unitsPerEm（lazy 透過 opentype.js parse 一次）。
   *
   * measureRun() 換算 design unit → pt 需要此值；caller 直接呼叫 measureRun
   * 不需手動載入 FontMetrics。
   */
  private async getUnitsPerEm(family: string): Promise<number> {
    const entry = this.fonts.get(family);
    if (!entry) throw new Error(`ShapingEngine: font "${family}" not loaded`);
    if (entry.unitsPerEm === undefined) {
      const { readFontMetrics } = await import('./FontMetrics');
      const metrics = readFontMetrics(entry.bytes);
      entry.unitsPerEm = metrics.unitsPerEm;
    }
    return entry.unitsPerEm;
  }

  /**
   * Sprint 265：取代 ctx.measureText —— 用 HarfBuzz 真實 shaping 量測 run 寬度。
   *
   * 與 ctx.measureText 差異：
   *   - 支援 OpenType kerning / ligature（ctx.measureText 對 'fi' 不會 ligate）
   *   - 支援 Script-aware shaping（Arabic / Indic / CJK 複雜文字正確）
   *   - 回傳 per-glyph advancesPt 陣列（line-breaking 演算法可用）
   *
   * 自動偵測：未給 options.script 時、用 detectScript(text) 判定 + 對應 language +
   * direction。caller 可覆蓋。
   *
   * @returns RunMetrics — widthPt / heightPt / glyphCount / advancesPt[] / glyphs[]
   */
  async measureRun(
    text: string,
    family: string,
    sizePt: number,
    options?: ShapeOptions,
  ): Promise<RunMetrics> {
    const detectedScript = detectScript(text);
    const fullOptions: ShapeOptions = {
      script: options?.script ?? detectedScript,
      language: options?.language ?? defaultLanguageForScript(detectedScript),
      direction: options?.direction ?? defaultDirectionForScript(detectedScript),
      features: options?.features,
      clusterLevel: options?.clusterLevel,
    };
    const glyphs = await this.shape(text, family, sizePt, fullOptions);
    const unitsPerEm = await this.getUnitsPerEm(family);
    const scale = sizePt / unitsPerEm;
    const advancesPt = glyphs.map((g) => g.xAdvance * scale);
    const widthPt = advancesPt.reduce((a, b) => a + b, 0);
    const heightPt = glyphs.reduce((acc, g) => acc + g.yAdvance * scale, 0);
    return { widthPt, heightPt, glyphCount: glyphs.length, advancesPt, glyphs };
  }

  /** 清除字型快取（測試 / 字型熱更新用）。 */
  clear(): void {
    this.fonts.clear();
  }
}

/** 重置全域 hb instance（測試用） */
export function __resetHbForTesting(): void {
  hbInstancePromise = undefined;
}
