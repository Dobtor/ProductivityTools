#!/usr/bin/env node
// Probe: verify FontMetricsAdapter actually registers fonts + invocation
import { readFileSync } from 'node:fs';
const puppeteer = (await import('puppeteer')).default;
const ROOT = '/mnt/d/work/odoo18-docker/addons/dobtor_doc_editor';
const HARNESS = `${ROOT}/scripts/visual_regression_v14_harness.html`;
const fixture = `${ROOT}/tests/fixtures/02_std_table/1121006-磺港溪再造C段護岸及步道整建工程(延壽橋至三合橋)週報.docx`;

const fonts = {
  'Times New Roman': '/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf',
  '標楷體': '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf',
  '微軟正黑體': '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf',
  '新細明體': '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf',
  'Arial': '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
};
const fontBytes = {};
for (const [k, p] of Object.entries(fonts)) fontBytes[k] = readFileSync(p).toString('base64');

const browser = await puppeteer.launch({ headless: true, args: ['--no-sandbox'] });
const page = await browser.newPage();
page.on('console', m => console.log('[browser]', m.text()));
await page.goto(`file://${HARNESS}`, { waitUntil: 'load' });
await page.waitForFunction(() => !!window.__dobtorPipeline);

const b64 = readFileSync(fixture).toString('base64');

const result = await page.evaluate((docxB64, fontBytes) => {
  const pipeline = window.__dobtorPipeline;
  // Manually build adapter + register fonts
  const adapter = new pipeline.FontMetricsAdapter();
  for (const [family, b64] of Object.entries(fontBytes)) {
    try {
      const bin = atob(b64);
      const u8 = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
      adapter.registerFont(family, u8);
      console.log(`registered: ${family} → cache size now ${adapter.listFonts().length}`);
    } catch (e) {
      console.log(`registerFont FAIL ${family}: ${e.message}`);
    }
  }
  console.log('Adapter listFonts:', adapter.listFonts());

  // Probe measureLineHeight directly for known docx families
  const test = (family, fontSize) => {
    const h = adapter.measureLineHeight({ fontFamily: family, fontSize });
    console.log(`measureLineHeight(${family} ${fontSize}pt) = ${h.toFixed(3)}pt`);
  };
  test('標楷體', 12);
  test('Times New Roman', 12);
  test('Arial', 12);
  test('unknown-family', 12);  // should fallback to EstimateMetrics 1.2 × 12 = 14.4

  // Now run actual render with adapter
  function base64ToArrayBuffer(b64) {
    const bin = atob(b64);
    const u8 = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
    return u8.buffer;
  }
  const buf = base64ToArrayBuffer(docxB64);
  const container = document.createElement('div');
  document.body.appendChild(container);
  return pipeline.render(buf, container, { dpi: 150, fontAdapter: adapter }).then(r => ({
    pageCount: r.pageCount,
    pages: r.pages.length,
    adapterFamilies: adapter.listFonts(),
  }));
}, b64, fontBytes);

console.log('\nrender result:', result);
await browser.close();
