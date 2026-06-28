// rollup.cli.config.js — Node CLI bundle (Phase E)
//
// 輸入：tools/parse_docx_cli.ts
// 輸出：tools/dist/parse_docx_cli.cjs
//
// 用途：Python doc_controller.py 用 subprocess.run(['node', cli_path, ...])
// 呼叫此 CJS bundle 解析 .docx 為 IElement[] JSON。
//
// 為何另開設定檔：
//   主 bundle 是 UMD（給瀏覽器），CLI bundle 是 CJS（給 Node）。
//   兩者 input / output / external 不同，分檔清楚。
//
// External 設計：
//   Node 內建模組（node:fs / node:path / node:process / node:module）標 external，
//   讓 Node runtime 直接 require，bundle 內不打包。

import typescript from '@rollup/plugin-typescript';
import resolve from '@rollup/plugin-node-resolve';
import commonjs from '@rollup/plugin-commonjs';

const NODE_BUILTINS = [
  'node:fs',
  'node:path',
  'node:process',
  'node:module',
  'node:buffer',
  'fs',
  'path',
  'process',
  'module',
  'buffer',
];

export default {
  input: 'tools/parse_docx_cli.ts',

  output: {
    file: 'tools/dist/parse_docx_cli.cjs',
    format: 'cjs',
    sourcemap: false,
    // shebang 讓檔案可直接執行（雖然 Python 還是用 node 啟動）
    banner: '#!/usr/bin/env node',
  },

  external: NODE_BUILTINS,

  plugins: [
    resolve({
      // Node 環境（不是 browser），讓 fflate / 其他 npm 套件選 Node 路徑
      preferBuiltins: true,
    }),
    commonjs(),
    typescript({
      tsconfig: './tsconfig.cli.json',
    }),
  ],
};
