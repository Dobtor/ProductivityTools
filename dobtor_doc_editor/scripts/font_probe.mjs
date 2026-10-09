import { existsSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = '/mnt/d/work/odoo18-docker/addons/dobtor_doc_editor';
const HARNESS = `${ROOT}/scripts/visual_regression_v14_harness.html`;
const fixture = `${ROOT}/tests/fixtures/02_std_table/1121006-磺港溪再造C段護岸及步道整建工程(延壽橋至三合橋)週報.docx`;

const puppeteer = (await import('puppeteer')).default;
const browser = await puppeteer.launch({ headless: true, args: ['--no-sandbox'] });
const page = await browser.newPage();
await page.goto(`file://${HARNESS}`, { waitUntil: 'load' });
await page.waitForFunction(() => !!window.__dobtorPipeline);

const b64 = readFileSync(fixture).toString('base64');

// Collect font families used in this docx
const fontFamilies = await page.evaluate((docxB64) => {
  function base64ToArrayBuffer(b64) {
    const bin = atob(b64);
    const u8 = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
    return u8.buffer;
  }
  const buf = base64ToArrayBuffer(docxB64);
  const doc = window.__dobtorPipeline.parse(buf);
  const families = new Set();
  function visit(node) {
    if (!node) return;
    if (typeof node === 'object') {
      if (node.fontFamily) families.add(node.fontFamily);
      if (node.runProps?.fontFamily) families.add(node.runProps.fontFamily);
      for (const k in node) {
        if (k === 'runProps') continue;
        const v = node[k];
        if (Array.isArray(v)) v.forEach(visit);
        else if (typeof v === 'object') visit(v);
      }
    }
  }
  visit(doc);
  return Array.from(families);
}, b64);

console.log('Font families used in 02 週報 docx:', fontFamilies);
await browser.close();
