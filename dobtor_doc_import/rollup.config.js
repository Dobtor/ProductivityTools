// rollup.config.js — dobtor_doc_editor Frontend Build
//
// 輸入：static/src/core/ooxml/index.ts（我們的 OOXML Parser 入口）
// 輸出：static/src/lib/canvas_editor/canvas-editor-custom.umd.js
//
// 打包策略：
//   將 OOXML Parser TypeScript 原始碼，加上被 patch-package 修改過的
//   @hufe921/canvas-editor，一起打包成單一 UMD bundle。
//   Odoo 的靜態資源系統直接引用這個 bundle，不需要任何 npm 工具鏈。
//
// 注意：Phase 1 開始前 static/src/core/ooxml/ 尚未存在，
//   build 會失敗——這是預期行為，Phase 1 建立 Parser 後再執行 build。

import typescript from '@rollup/plugin-typescript';
import resolve from '@rollup/plugin-node-resolve';
import commonjs from '@rollup/plugin-commonjs';

export default {
  input: 'static/src/core/ooxml/index.ts',

  output: {
    file: 'static/src/lib/canvas_editor/canvas-editor-custom.umd.js',
    format: 'umd',
    name: 'DobtorCanvasEditor',
    // 不設 globals — canvas-editor 打包進 bundle，不作為外部依賴
    sourcemap: true,
  },

  plugins: [
    // 解析 node_modules 內的模組（包含被 patch 修改的 canvas-editor）
    resolve({ browser: true }),
    // 將 CommonJS 模組轉換為 ES Module（canvas-editor 內部使用 CJS）
    commonjs(),
    // TypeScript 支援（我們的 OOXML Parser）
    typescript({ tsconfig: './tsconfig.json' }),
  ],
};
