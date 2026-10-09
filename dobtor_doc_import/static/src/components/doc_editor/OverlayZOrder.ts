/**
 * OverlayZOrder — Sprint 356。
 *
 * Sprint 291/.../351 overlay 系列第十三輪深推。overlay item（image / textbox /
 * shape）有重疊時需要 **z-order 管理**：bring-to-front / send-to-back / 上移一層 /
 * 下移一層。OOXML drawing 的 `relativeHeight`（Sprint 287 已 capture）就是 z-order。
 *
 * 本 sprint 提供純資料 z-order model：
 *   - 維護一個 ordered id list（index 0 = 最底、末端 = 最頂）
 *   - bringToFront / sendToBack / bringForward / sendBackward
 *   - zIndexOf / orderedIds / normalize（回 0..n-1 連續 z）
 *
 * 紀律 #18 scope-down：
 *   - 純 id 排序 model；caller 自己對應到 render 的 relativeHeight
 *   - 不接 doc_editor.js OWL real path（紀律 #21）
 *   - 不處理 group/巢狀 z（caller 自管）
 *
 * 紀律 #21：純資料 model；不污染 doc_editor.js。
 */

export class OverlayZOrder {
  /** index 0 = 最底層、末端 = 最頂層 */
  private order: string[] = [];

  constructor(initialIds: ReadonlyArray<string> = []) {
    // 去重、保留首次出現順序
    const seen = new Set<string>();
    for (const id of initialIds) {
      if (!seen.has(id)) {
        seen.add(id);
        this.order.push(id);
      }
    }
  }

  /** 新增到最頂層（已存在 → no-op）。 */
  add(id: string): void {
    if (!this.order.includes(id)) this.order.push(id);
  }

  /** 移除（不存在 → no-op）。 */
  remove(id: string): boolean {
    const i = this.order.indexOf(id);
    if (i < 0) return false;
    this.order.splice(i, 1);
    return true;
  }

  /** 移到最頂層。不存在 → false。 */
  bringToFront(id: string): boolean {
    const i = this.order.indexOf(id);
    if (i < 0) return false;
    this.order.splice(i, 1);
    this.order.push(id);
    return true;
  }

  /** 移到最底層。 */
  sendToBack(id: string): boolean {
    const i = this.order.indexOf(id);
    if (i < 0) return false;
    this.order.splice(i, 1);
    this.order.unshift(id);
    return true;
  }

  /** 上移一層（已在頂 → no-op 但回 true）。不存在 → false。 */
  bringForward(id: string): boolean {
    const i = this.order.indexOf(id);
    if (i < 0) return false;
    if (i < this.order.length - 1) {
      [this.order[i], this.order[i + 1]] = [this.order[i + 1], this.order[i]];
    }
    return true;
  }

  /** 下移一層（已在底 → no-op 但回 true）。 */
  sendBackward(id: string): boolean {
    const i = this.order.indexOf(id);
    if (i < 0) return false;
    if (i > 0) {
      [this.order[i], this.order[i - 1]] = [this.order[i - 1], this.order[i]];
    }
    return true;
  }

  /** z-index（0 = 最底）；不存在 → -1。 */
  zIndexOf(id: string): number {
    return this.order.indexOf(id);
  }

  /** 由底到頂的 id 順序（copy）。 */
  orderedIds(): string[] {
    return [...this.order];
  }

  size(): number {
    return this.order.length;
  }

  /**
   * 回每個 id 對應的 z（0..n-1 連續整數）。caller 想套到 relativeHeight 用。
   */
  normalize(): Map<string, number> {
    const map = new Map<string, number>();
    this.order.forEach((id, idx) => map.set(id, idx));
    return map;
  }

  has(id: string): boolean {
    return this.order.includes(id);
  }
}
