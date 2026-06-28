/**
 * units — OOXML 度量單位轉換工具
 *
 * OOXML 慣用單位：
 *   - twip (1/20 pt) — w:sz、w:tblW (w:dxa)
 *   - half-point (1/2 pt) — w:sz of w:rPr font size
 *   - eighth-point (1/8 pt) — w:sz of border width
 *   - EMU (English Metric Unit, 1/914400 inch) — DrawingML wp:extent
 *
 * 全模組一律以 pt 為標準（見 ast/types.ts: Pt）。
 */

export const TWIP_PER_PT = 20;
export const HALF_POINT_PER_PT = 2;
export const EIGHTH_POINT_PER_PT = 8;
export const EMU_PER_INCH = 914_400;
export const PT_PER_INCH = 72;
export const EMU_PER_PT = EMU_PER_INCH / PT_PER_INCH; // 12700

export function twipToPt(twip: number): number {
  return twip / TWIP_PER_PT;
}

export function halfPointToPt(hp: number): number {
  return hp / HALF_POINT_PER_PT;
}

export function eighthPointToPt(ep: number): number {
  return ep / EIGHTH_POINT_PER_PT;
}

export function emuToPt(emu: number): number {
  return emu / EMU_PER_PT;
}

export function ptToPx(pt: number, dpi = 96): number {
  return (pt / PT_PER_INCH) * dpi;
}
