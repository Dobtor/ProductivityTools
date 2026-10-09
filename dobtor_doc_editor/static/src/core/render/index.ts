/**
 * Renderer 公開入口（Sprint 8 / Phase 5）
 *
 * 用法：
 *   import { CanvasRenderer, MockRenderContext } from 'core/render';
 *   const ctx = new MockRenderContext();
 *   const renderer = new CanvasRenderer(ctx);
 *   renderer.render(layoutDocument(sections));
 *   // ctx.ops 包含整份文件的繪圖指令序列
 */

export type {
  RenderContext,
  RenderTextStyle,
  RenderStrokeStyle,
} from './types';

export { MockRenderContext } from './MockRenderContext';
export type { RenderOp } from './MockRenderContext';

export { CanvasRenderer } from './CanvasRenderer';
export type { CanvasRenderOptions } from './CanvasRenderer';

export {
  BrowserCanvasRenderContext,
  toCssColor,
  toCssFont,
} from './BrowserCanvasRenderContext';
export type {
  BrowserCanvas2D,
  BrowserCanvasRenderOptions,
} from './BrowserCanvasRenderContext';

export {
  serializeOps,
  serializeOpsToJson,
  serializeOpsToNdjson,
  fingerprintOps,
} from './serializeOps';
export type { SerializeOpsOptions, OpsFingerprint } from './serializeOps';
