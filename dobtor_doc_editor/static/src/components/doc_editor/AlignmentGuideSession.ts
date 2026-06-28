/**
 * AlignmentGuideSession — Sprint 306。
 *
 * Sprint 291 / 295 / 301 補了對齊輔助線的 pure-fn 計算（computeAlignGuides /
 * buildGuideStyles / applySnapToRect）；本 sprint 補 **狀態機 wrapper**：
 *
 *   - drag start：caller 呼叫 `start(rect, siblings, bounds)` 進入 active
 *   - drag move：caller 呼叫 `update(newRect)` 計算 guide + snap target
 *   - drag end：caller 呼叫 `end()` 進入 idle
 *
 * 提供 active state、visible guide styles（用 Sprint 295 buildGuideStyles 產出）、
 * snapped rect（用 Sprint 291 applySnapToRect 套用）；caller 拿 `getRenderData()`
 * 直接交給 view layer 渲染。
 *
 * 紀律 #18 scope-down：
 *   - 不接 doc_editor.js OWL Component real path（紀律 #21、同 Sprint 295 / 301
 *     政策、避免破 13 Playwright E2E）
 *   - 不做 RAF batching（caller 自管 60fps；session 純 synchronous reducer pattern）
 *   - 不支援多 axis 不同 snap source（同 axis 只一條 snap target、Sprint 291 pickSnapTargets）
 *
 * 紀律 #21：純 stateful class、無 DOM / OWL / RAF / setTimeout 依賴；可在
 *   browser / Node 都跑單元測試。
 */

import {
  computeAlignGuides,
  pickSnapTargets,
  type AlignGuide,
  type Rect,
  type Bounds,
} from './overlay_geometry';
import {
  buildGuideStyles,
  type GuideStyle,
  type BuildGuideStylesOptions,
} from './alignment_guide_render';

export type GuideSessionState = 'idle' | 'active';

export interface AlignmentGuideSessionOptions {
  /** 對齊 threshold（snap 範圍）；預設 4 */
  threshold?: number;
  /** Build guide styles 視覺參數 passthrough */
  guideStyles?: BuildGuideStylesOptions;
}

export interface AlignmentGuideRenderData {
  state: GuideSessionState;
  /** 當前可見的對齊輔助線（active 時非空） */
  guides: GuideStyle[];
  /** snap 套用後的 rect（caller 用此覆寫 drag preview）；idle 時 null */
  snappedRect: Rect | null;
  /** snap 來源 guide（X / Y 軸各一條，用於 visual 高亮命中那條）；idle 時 undefined */
  snapX?: AlignGuide;
  snapY?: AlignGuide;
}

/**
 * Drag-and-snap session。
 *
 * 用法：
 *   const session = new AlignmentGuideSession({ threshold: 4 });
 *   onDragStart: session.start(initialRect, siblings, pageBounds);
 *   onDragMove:  session.update(rectFollowingMouse);
 *                view.render(session.getRenderData());
 *   onDragEnd:   session.end();
 */
export class AlignmentGuideSession {
  private state: GuideSessionState = 'idle';
  private siblings: readonly Rect[] = [];
  private bounds: Bounds = { width: 0, height: 0 };
  private readonly threshold: number;
  private readonly guideStylesOpts: BuildGuideStylesOptions;
  private renderData: AlignmentGuideRenderData = {
    state: 'idle',
    guides: [],
    snappedRect: null,
  };

  constructor(opts: AlignmentGuideSessionOptions = {}) {
    this.threshold = opts.threshold ?? 4;
    this.guideStylesOpts = opts.guideStyles ?? {};
  }

  /** Drag 開始：固定 siblings + bounds、計算 initial guides。 */
  start(rect: Rect, siblings: readonly Rect[], bounds: Bounds): void {
    this.state = 'active';
    this.siblings = siblings;
    this.bounds = bounds;
    this.recompute(rect);
  }

  /** Drag 移動：重新計算 guides + snap target。 */
  update(rect: Rect): void {
    if (this.state !== 'active') return;
    this.recompute(rect);
  }

  /** Drag 結束：清 guides、回 idle。 */
  end(): void {
    this.state = 'idle';
    this.siblings = [];
    this.renderData = { state: 'idle', guides: [], snappedRect: null };
  }

  getState(): GuideSessionState {
    return this.state;
  }

  getRenderData(): AlignmentGuideRenderData {
    return this.renderData;
  }

  private recompute(rect: Rect): void {
    const guides = computeAlignGuides(rect, this.siblings, this.bounds, this.threshold);
    const { snapX, snapY } = pickSnapTargets(rect, guides);
    const snappedRect: Rect = {
      ...rect,
      x: snapX?.value ?? rect.x,
      y: snapY?.value ?? rect.y,
    };
    const styles = buildGuideStyles(guides, this.bounds, this.guideStylesOpts);
    this.renderData = {
      state: 'active',
      guides: styles,
      snappedRect,
      snapX,
      snapY,
    };
  }
}
