/**
 * Sprint 61 — BrowserTextMetrics（canvas.measureText 真實字寬）
 *
 * 規劃書 §11.28 Sprint 61 候選 = HarfBuzz / opentype.js 真實字型 metric；
 * Sprint 60 probe 後重新評估 — 因 font 檔案 1-5MB 通常需 user 提供（標楷體授權 / 開源替代 Noto 較大），
 * 本 sprint 走「用 browser 內建 canvas.measureText 取得真實字寬」的 alternative：
 *
 *   - 不需 font 檔案 bundle（用瀏覽器系統字型）
 *   - 真實 advance width 取代 EstimateMetrics 的 0.5/0.55/1.15 em 估算
 *   - LRU cache（per font+size key）→ 同一字型同字串只 measure 一次
 *   - 非 browser 環境（vitest / node）自動 fallback EstimateMetrics（不破壞既有 layout 測試）
 *
 * 範圍限制：
 *   - 只取代 measureWidth；measureLineHeight 仍用 EstimateMetrics 1.2 em（canvas.measureText
 *     有 fontBoundingBox{Ascent,Descent}/actualBoundingBox 但跨瀏覽器支援度不一）
 *   - 為 opt-in pipeline option；default 仍 EstimateMetrics（與 Sprint 50-60 baseline 一致）
 *
 * Sprint 28 對 CJK 1.15em empirical 修正可能會被覆蓋 —— 真實字寬下 layout 行為可能變動，
 * 需要全 42 fixture VR 量測（Sprint 57 教訓）才能判定是否成為 default。
 */

import type { RunProps, Pt } from '../ooxml/ast/types';
import type { TextMetrics } from './types';
import { EstimateMetrics } from './TextMetrics';

const DEFAULT_FONT_SIZE_PT = 10.5;
const DEFAULT_CACHE_MAX = 4096;

/** Canvas 2D 介面子集（只需 font / measureText）— 用於 mock 與真實 canvas 共用型別。 */
export interface MeasureCanvas2D {
  font: string;
  measureText(text: string): { width: number };
}

export interface BrowserTextMetricsOptions {
  /**
   * 注入 canvas2d context（測試 / 非 browser 環境用 mock）；
   * 不傳則 BrowserTextMetrics 嘗試 `document.createElement('canvas').getContext('2d')`。
   */
  canvas2d?: MeasureCanvas2D;
  /** LRU cache max entries（default 4096）。 */
  cacheMax?: number;
  /**
   * canvas.measureText 失敗 / 不可用時的 fallback。預設新建 EstimateMetrics。
   * caller 可注入共用 instance（避免每個 layout pass 重建 cache）。
   */
  fallback?: TextMetrics;
}

/**
 * 用 canvas.measureText 取得真實字寬的 TextMetrics 實作。
 *
 * 為何重要：
 *   - EstimateMetrics 對 CJK 字寬用 1.15 em 估算（Sprint 28 empirical），對 Latin 用 0.5 em
 *   - 不同字型實際 advance width 偏差 ±5-15%（粗體 / 寬扁字 / italic）
 *   - 真實字寬 → layout 行寬計算更準 → wrap 行數 / 分頁位置更準 → VR mean 可改善
 *
 * 限制：
 *   - 結果隨 browser / 系統字型可用性變動（不同機器渲染可能不同字型）
 *   - 但對 same browser baseline 而言可重現
 *   - measureLineHeight 仍走 fallback（canvas API line height 不可靠）
 */
export class BrowserTextMetrics implements TextMetrics {
  private readonly canvas: MeasureCanvas2D | null;
  private readonly cache: Map<string, number> = new Map();
  private readonly cacheMax: number;
  private readonly fallback: TextMetrics;
  private hits = 0;
  private misses = 0;
  private fallbackUses = 0;

  constructor(opts: BrowserTextMetricsOptions = {}) {
    this.cacheMax = opts.cacheMax ?? DEFAULT_CACHE_MAX;
    this.fallback = opts.fallback ?? new EstimateMetrics();
    if (opts.canvas2d) {
      this.canvas = opts.canvas2d;
    } else {
      // 嘗試自動取得 canvas2d（browser / puppeteer 環境）
      this.canvas = tryCreateCanvas();
    }
  }

  measureWidth(text: string, props: RunProps): Pt {
    if (!text) return 0;
    if (!this.canvas) {
      this.fallbackUses++;
      return this.fallback.measureWidth(text, props);
    }
    const fontSize = props.fontSize ?? DEFAULT_FONT_SIZE_PT;
    const bold = props.bold === true;
    const italic = props.italic === true;
    const family = props.fontFamily ?? 'sans-serif';
    // Cache key 包含影響字寬的所有因子；spacing 後處理（額外加）
    const key = `${bold ? 'B' : ''}${italic ? 'I' : ''}|${fontSize}|${family}|${text}`;
    const cached = this.cache.get(key);
    if (cached !== undefined) {
      this.hits++;
      // LRU touch（保證新近用到的 entry 不被 evict）
      this.cache.delete(key);
      this.cache.set(key, cached);
      return cached + spacingExtra(text, props);
    }
    this.misses++;
    // 設定 canvas font 並 measure
    // font CSS：italic bold {fontSize}pt {family}（Canvas font 接受 pt 單位、無需 px 轉換）
    const fontParts: string[] = [];
    if (italic) fontParts.push('italic');
    if (bold) fontParts.push('bold');
    fontParts.push(`${fontSize}pt`);
    fontParts.push(formatFontFamily(family));
    try {
      this.canvas.font = fontParts.join(' ');
      const w = this.canvas.measureText(text).width;
      const width = w + 0; // ensure number
      // LRU evict 最舊
      if (this.cache.size >= this.cacheMax) {
        const oldestKey = this.cache.keys().next().value;
        if (oldestKey !== undefined) this.cache.delete(oldestKey);
      }
      this.cache.set(key, width);
      return width + spacingExtra(text, props);
    } catch {
      // measure 失敗（canvas/font 不可用）→ fallback
      this.fallbackUses++;
      return this.fallback.measureWidth(text, props);
    }
  }

  measureLineHeight(props: RunProps): Pt {
    // Sprint 61 範圍：line height 仍走 fallback；canvas API line height 跨瀏覽器不可靠
    return this.fallback.measureLineHeight(props);
  }

  stats(): { hits: number; misses: number; size: number; fallbackUses: number } {
    return {
      hits: this.hits,
      misses: this.misses,
      size: this.cache.size,
      fallbackUses: this.fallbackUses,
    };
  }

  clear(): void {
    this.cache.clear();
    this.hits = 0;
    this.misses = 0;
    this.fallbackUses = 0;
  }
}

function tryCreateCanvas(): MeasureCanvas2D | null {
  try {
    if (typeof document === 'undefined') return null;
    const canvas = document.createElement('canvas');
    canvas.width = 1;
    canvas.height = 1;
    const ctx = canvas.getContext('2d');
    return ctx as unknown as MeasureCanvas2D;
  } catch {
    return null;
  }
}

function formatFontFamily(family: string): string {
  if (/[\s,]/.test(family)) return `"${family.replace(/"/g, '\\"')}"`;
  return family;
}

function spacingExtra(text: string, props: RunProps): Pt {
  if (typeof props.spacing !== 'number' || props.spacing === 0) return 0;
  return props.spacing * Array.from(text).length;
}
