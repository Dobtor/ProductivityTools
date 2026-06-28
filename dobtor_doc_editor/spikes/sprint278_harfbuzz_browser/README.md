# Sprint 278 — Phase 2.1 HarfBuzz browser-side spike

詳細結果見 [`docs/sprint278_phase2_1_harfbuzz_browser_spike.md`](../../docs/sprint278_phase2_1_harfbuzz_browser_spike.md)。

## Reproduction（從 clean clone 重跑 spike）

```bash
cd dobtor_doc_editor/spikes/sprint278_harfbuzz_browser

# 1. Copy harfbuzzjs files + test font（gitignored、不入 repo）
mkdir -p vendor
cp ../../node_modules/harfbuzzjs/hb.js vendor/
cp ../../node_modules/harfbuzzjs/hb.wasm vendor/
cp ../../node_modules/harfbuzzjs/hbjs.js vendor/
cp /usr/share/fonts/truetype/dejavu/DejaVuSans.ttf .

# 2. Serve & open
python3 -m http.server 8278 &
# 開 http://localhost:8278/index.html

# 3. 比對 Node 端 byte-identical parity
cd ../..
./node_modules/.bin/vitest run tests/unit/sprint278_harfbuzz_node_parity.test.ts
```

## 預期輸出

Browser console + `window.__sprint278_result`：

```json
{
  "exitCode": 0,
  "glyphCount": 11,
  "totalWidthPt": 67.271484375,
  "sampleGlyph": { "glyphId": 43, "xAdvance": 9.0234375, ... },
  "kernDeltaPt": -0.767578125,
  "wasmLoadMs": 52.4,
  "upem": 2048
}
```

Node vitest stdout：

```
[sprint278-node] {
  "totalWidthPt": 67.271484375,
  "glyphCount": 11,
  "glyph0": { "glyphId": 43, "xAdvancePt": 9.0234375, ... }
}
[sprint278-node] AV kern on= 15.650390625 off= 16.41796875 delta= -0.767578125
```

**Node ↔ Browser Δ = 0 全表**（含 kerning pair）。

## 檔案說明

| 檔 | 用途 | git |
|---|---|---|
| `index.html` | Browser spike harness（~210 行） | ✓ |
| `node_compare.mjs` | Node 端 parity 比對腳本 | ✓ |
| `.gitignore` | 排除 heavy binaries | ✓ |
| `README.md` | 本檔 | ✓ |
| `vendor/hb.js` | harfbuzzjs Emscripten loader | ✗（reproducible） |
| `vendor/hb.wasm` | HarfBuzz WASM binary 397 KB | ✗（reproducible） |
| `vendor/hbjs.js` | harfbuzzjs high-level wrapper | ✗（reproducible） |
| `DejaVuSans.ttf` | test font 760 KB | ✗（system font） |
