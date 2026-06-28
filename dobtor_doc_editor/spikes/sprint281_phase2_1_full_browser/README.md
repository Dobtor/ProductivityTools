# Sprint 281 — Phase 2.1 full chain browser e2e spike

詳細結果見 [`docs/sprint281_phase2_1_full_chain_e2e.md`](../../docs/sprint281_phase2_1_full_chain_e2e.md)。

## Reproduction

```bash
cd dobtor_doc_editor

# 1. Restore Sprint 278 vendor binaries（gitignored）
mkdir -p spikes/sprint278_harfbuzz_browser/vendor
cp node_modules/harfbuzzjs/{hb.js,hb.wasm,hbjs.js} spikes/sprint278_harfbuzz_browser/vendor/
cp /usr/share/fonts/truetype/dejavu/DejaVuSans.ttf spikes/sprint278_harfbuzz_browser/

# 2. Build Sprint 281 bundle（esbuild、~640KB IIFE、含 opentype.js + ShapingEngine）
./node_modules/.bin/esbuild spikes/sprint281_phase2_1_full_browser/entry.ts \
  --bundle --platform=browser --format=iife \
  --global-name=Sprint281Bundle --target=es2020 \
  --external:node:module \
  --outfile=spikes/sprint281_phase2_1_full_browser/bundle.js

# 3. Serve（spikes/ root、相對路徑解析 sprint278 vendor）
cd spikes && python3 -m http.server 8281

# 4. Open http://localhost:8281/sprint281_phase2_1_full_browser/index.html

# 5. Node 端 parity 對照
cd ..
./node_modules/.bin/vitest run tests/unit/sprint281_phase2_1_full_chain_node_parity.test.ts
```

## 預期輸出

Browser console + `window.__sprint281_result`：

```json
{
  "exitCode": 0,
  "chainAttempted": 2,
  "chainLoadedFrom": "DejaVuSans",
  "shapeGlyphCount": 11,
  "shapeWidthPt": 67.271484375,
  "shapeGlyph0": { "glyphId": 43, "xAdvance": 1540, ... },
  "metrics": { "unitsPerEm": 2048, "ascender": 1901, "typoAscender": 1556, ... },
  "naturalHeightPt": 16.37109375,
  "autoHeightPt": 24.556640625,
  "exactHeightPt": 18,
  "atLeastHeightPt": 20
}
```

Node 端 parity Δ=0 全表（每欄位對 browser 完全一致到尾數位）。

## 鏈

```
setHbModuleLoader → 注入 createHarfBuzz + hbjs（Sprint 279）
   ↓
loadShapingFontWithChain → primary 404 → fallback DejaVuSans 200（Sprint 280）
   ↓
engine.measureRun → HarfBuzz shape 11 glyphs（Sprint 265）
   ↓
readFontMetrics → opentype.js 讀 ascender/typoMetrics（Sprint 62 / 268）
   ↓
resolveOoxmlLineHeight → auto/exact/atLeast 三 rule（Sprint 267）
```

## 檔案

| 檔 | 用途 | git |
|---|---|---|
| `entry.ts` | esbuild bundle 入口 | ✓ |
| `index.html` | spike harness | ✓ |
| `.gitignore` | 排除 bundle.js | ✓ |
| `README.md` | 本檔 | ✓ |
| `bundle.js` | esbuild 產物 ~640KB | ✗（reproducible） |
