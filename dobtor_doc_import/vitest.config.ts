import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    // 用純 Node 環境 + setup 檔注入 @xmldom/xmldom 的 DOMParser
    // happy-dom 的 DOMParser 對 prefix 命名空間（<w:p>）會誤當 HTML 解，不適用
    environment: 'node',
    setupFiles: ['./tests/setup.ts'],
    include: ['tests/unit/**/*.test.ts', 'tests/integration/**/*.test.ts'],
    globals: false,
  },
});
