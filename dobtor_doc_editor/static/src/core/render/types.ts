/**
 * Renderer 共用型別（Sprint 8 / Phase 5）
 *
 * 設計原則：
 *   - RenderContext 是平台無關介面：Mock / Browser Canvas / 未來 PDF 等實作都遵守
 *   - 座標單位 pt（與 Layout Engine 一致）；座標系原點 = 頁面左上 (0,0)
 *   - Renderer 不做任何 Layout 計算，純照 DocumentLayout 把指令送到 Context
 */

import type { Pt, BorderStyle } from '../ooxml/ast/types';

/** 文字繪製樣式（合併自 RunProps，但只取 Renderer 需要的欄位） */
export interface RenderTextStyle {
  fontFamily?: string;
  fontSize: Pt;
  bold?: boolean;
  italic?: boolean;
  /** 6 位 hex 顏色（不含 #）；undefined → 由 Context 決定預設黑色 */
  color?: string;
  /** Sprint 9：底線樣式（OOXML w:u）；'none' / undefined 不畫 */
  underline?: 'none' | 'single' | 'double' | 'dotted' | 'dashed' | 'thick' | 'wave' | string;
  /** Sprint 9：刪除線（OOXML w:strike） */
  strike?: boolean;
  /** Sprint 9：螢光底色（OOXML w:highlight），6 位 hex */
  highlight?: string;
}

/** 線條繪製樣式（邊框、刪除線等） */
export interface RenderStrokeStyle {
  /** 6 位 hex 顏色 */
  color: string;
  /** 線寬 pt；< 0.25 視為「細線」由 Context 決定如何抗鋸齒 */
  width: Pt;
  /** OOXML 邊框樣式；非 single/double/dashed/dotted 一律當 single 畫 */
  style?: BorderStyle;
}

/**
 * RenderContext — 抽象繪圖指令介面
 *
 * 每頁繪製流程：
 *   beginPage(...) → fillRect(背景) → fillText / drawLine / drawImage ... → endPage()
 *
 * 實作義務：
 *   - beginPage 必須先於任何繪圖呼叫；endPage 之後不應再有任何呼叫
 *   - 指令順序保留：Renderer 預期後送的 op 蓋在前送 op 上面（圖層疊放）
 */
export interface RenderContext {
  beginPage(pageNumber: number, width: Pt, height: Pt): void;
  endPage(): void;

  /** 純色填滿矩形（頁面背景 / cell shading 用） */
  fillRect(x: Pt, y: Pt, width: Pt, height: Pt, color: string): void;

  /** 線段（cell border / 段落分隔線用） */
  drawLine(x1: Pt, y1: Pt, x2: Pt, y2: Pt, style: RenderStrokeStyle): void;

  /**
   * 繪製文字。位置是 baseline 起點（左下角附近，依字型 ascender 上推）。
   *
   * Sprint 8：fillText 用 (x, y) = baseline anchor，遵守 Canvas API 慣例。
   * Renderer 在呼叫前已把 LinePageEntry.y + line.baseline 傳入。
   */
  fillText(text: string, x: Pt, y: Pt, style: RenderTextStyle): void;

  /**
   * 繪製內嵌 / 浮動圖片。href 是 OOXML rId 解析後的引用（Renderer 不解析來源；
   * 由 Context 端決定如何取資料：File system / blob URL / canvas-editor asset）。
   *
   * Sprint 40：第 6 參數 srcRect（0–1 分數）為 DrawingML `<a:srcRect>` 裁切；
   * 不傳時等同畫整張 source 圖到 (x,y)-(x+width, y+height) 的目標矩形；
   * 傳時 Context 應算 source 像素座標 sx/sy/sw/sh 並用 9-arg drawImage 畫裁切後的區塊
   * 到同樣的目標矩形（裁切後再 stretch 到 destination）。
   */
  drawImage(
    href: string,
    x: Pt,
    y: Pt,
    width: Pt,
    height: Pt,
    srcRect?: { leftPct: number; topPct: number; rightPct: number; bottomPct: number },
  ): void;

  /**
   * Sprint 34：座標變換 API（垂直文字 cell / 旋轉繪製用）。
   *
   * 呼叫順序保證：save → translate / rotate → 繪圖呼叫 → restore
   * Mock 實作可記錄事件用於測試斷言；Browser Canvas 直接 delegate ctx.save/translate/rotate/restore。
   *
   * 旋轉角單位：弧度（Math.PI / 2 = 90° 順時針，符合 Canvas 2D 慣例：y 軸朝下時 +π/2 = 順時針）。
   */
  save(): void;
  restore(): void;
  translate(dx: Pt, dy: Pt): void;
  rotate(rad: number): void;
}
