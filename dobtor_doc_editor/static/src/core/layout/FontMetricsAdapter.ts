/**
 * FontMetricsAdapter — 將真實字型 metrics 注入 Layout TextMetrics（Sprint 8 / Phase 2）
 *
 * 設計：
 *   - measureWidth：仍走 EstimateMetrics（HarfBuzz shape 是 async，無法 sync 接入；
 *     真要精確 advance 需在 BoxBuilder 階段預先 batch shape，工程量大留 Sprint 9+）
 *   - measureLineHeight：若已 register 對應字型，用 readFontMetrics + lineHeightPt
 *     真實計算（ascender + descender + lineGap）；否則 fallback EstimateMetrics 的
 *     1.2 × fontSize
 *
 * 為何先做行高、不做寬度：
 *   - 行高直接決定整份文件分頁位置（fixture-level 大幅影響）
 *   - 寬度估算誤差小（±5%）且改用 HarfBuzz async shape 工程量遠大於行高
 *
 * 使用方式：
 *   const adapter = new FontMetricsAdapter();
 *   adapter.registerFont('Times New Roman', timesBytes);
 *   adapter.registerFont('SimSun', simsunBytes);
 *   const layout = layoutDocument(sections, { metrics: adapter });
 *
 * 字型 family 對照：
 *   - 大小寫不敏感（key 內部小寫化）
 *   - 找不到 family 時 fallback EstimateMetrics（不 throw）
 *   - RunProps.fontFamily 為主，eastAsia 留待未來雙字型混排
 */

import type { RunProps, Pt } from '../ooxml/ast/types';
import type { TextMetrics } from './types';
import { EstimateMetrics } from './TextMetrics';
import { readFontMetrics, lineHeightPt } from '../ooxml/font/FontMetrics';
import type { FontMetricsResult } from '../ooxml/font/FontMetrics';

const DEFAULT_FONT_SIZE_PT = 10.5;

export class FontMetricsAdapter implements TextMetrics {
  private estimate = new EstimateMetrics();
  /** key = family.toLowerCase() */
  private metricsCache = new Map<string, FontMetricsResult>();

  /**
   * 註冊字型 byte buffer。Adapter 會立即 parse 一次 metrics 並 cache。
   *
   * @param family 字型 family name（與 RunProps.fontFamily 對應）
   * @param fontBytes TTF / OTF 位元組
   * @throws 若 opentype.js 解析失敗（檔案損毀 / 非字型）
   */
  registerFont(family: string, fontBytes: Uint8Array | ArrayBuffer): void {
    const m = readFontMetrics(fontBytes);
    this.metricsCache.set(family.toLowerCase(), m);
  }

  /**
   * 直接注入已 parse 的 metrics（測試 / 預先 parse 過的字型 metadata）。
   */
  registerMetrics(family: string, metrics: FontMetricsResult): void {
    this.metricsCache.set(family.toLowerCase(), metrics);
  }

  /** 已註冊的 family list（lowercase）。 */
  listFonts(): string[] {
    return Array.from(this.metricsCache.keys());
  }

  /** 是否已註冊指定 family（大小寫不敏感）。 */
  hasFont(family: string): boolean {
    return this.metricsCache.has(family.toLowerCase());
  }

  measureWidth(text: string, props: RunProps): Pt {
    return this.estimate.measureWidth(text, props);
  }

  measureLineHeight(props: RunProps): Pt {
    const family = props.fontFamily;
    if (family) {
      const metrics = this.metricsCache.get(family.toLowerCase());
      if (metrics) {
        const fontSize = props.fontSize ?? DEFAULT_FONT_SIZE_PT;
        return lineHeightPt(metrics, fontSize);
      }
    }
    return this.estimate.measureLineHeight(props);
  }

  /** 清除字型 cache（測試用）。 */
  clear(): void {
    this.metricsCache.clear();
  }
}
