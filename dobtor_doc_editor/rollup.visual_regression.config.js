// rollup.visual_regression.config.js — Sprint 14
//
// 輸入：tools/visual_regression_pipeline.entry.ts
// 輸出：tools/dist/visual_regression_pipeline.iife.js
//
// 用途：給 scripts/visual_regression_v14_harness.html 用的瀏覽器端 IIFE bundle。
//   把 OOXML Parser + Layout + Renderer + BrowserCanvasRenderContext 全部打包，
//   puppeteer 載入 harness 後即可呼叫 window.__dobtorPipeline.render()。
//
// 為何另開設定檔：
//   主 bundle（rollup.config.js）打包 canvas-editor + Parser，給 Odoo 載入。
//   CLI bundle（rollup.cli.config.js）打包 parse_docx_cli，給 Node subprocess。
//   本 bundle 是「只我們自家 pipeline 的瀏覽器版」，三者輸出格式不同（UMD / CJS / IIFE）。
//
// 不打包 canvas-editor：
//   Sprint 14 的視覺回歸是測 Layout + Renderer 的像素輸出，
//   不經 canvas-editor，因此 bundle 不需要 canvas-editor 也不需要 IElement[] 對接層。

import typescript from '@rollup/plugin-typescript';
import resolve from '@rollup/plugin-node-resolve';
import commonjs from '@rollup/plugin-commonjs';

// 把 Node-only 'node:module' alias 成 browser stub，
// 讓 FontMetrics.ts 的 `import { createRequire } from 'node:module'` 在 IIFE 載入時不 throw；
// caller 真呼叫 readFontMetrics() 才會合理錯（瀏覽器本來就無 opentype.js node 載入路徑）。
const NODE_MODULE_STUB_ID = '\0visual_regression__node_module_stub';
const nodeModuleStub = {
  name: 'node-module-browser-stub',
  resolveId(source) {
    if (source === 'node:module') return NODE_MODULE_STUB_ID;
    return null;
  },
  load(id) {
    if (id !== NODE_MODULE_STUB_ID) return null;
    return [
      'export function createRequire() {',
      '  return function browserStubRequire(id) {',
      '    throw new Error(',
      '      "FontMetrics(opentype.js) is not available in the browser visual_regression bundle (require(\\"" + id + "\\"))"',
      '    );',
      '  };',
      '}',
    ].join('\n');
  },
};

export default {
  input: 'tools/visual_regression_pipeline.entry.ts',

  output: {
    file: 'tools/dist/visual_regression_pipeline.iife.js',
    format: 'iife',
    name: 'DobtorPipeline',
    sourcemap: true,
    inlineDynamicImports: true,
  },

  plugins: [
    // 必須在 resolve 之前，攔截 'node:module' import。
    nodeModuleStub,
    // 解析 node_modules 內的模組（fflate / @xmldom/xmldom 等）
    resolve({ browser: true, preferBuiltins: false }),
    // 將 CommonJS 轉成 ESM
    commonjs(),
    // TypeScript 支援
    typescript({
      tsconfig: './tsconfig.visual_regression.json',
    }),
  ],

  // 抑制不影響的警告：xmldom 在 browser 環境下偶有 circular dep 警告
  onwarn(warning, warn) {
    if (warning.code === 'CIRCULAR_DEPENDENCY') return;
    if (warning.code === 'EVAL') return;
    warn(warning);
  },
};
