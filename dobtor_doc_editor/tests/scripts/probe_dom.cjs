/**
 * probe_dom.cjs — 實機探查 canvas-editor 在 /dobtor_doc_editor/test 的 DOM 結構
 * 一次性除錯腳本，找出 page canvas 的選擇器
 */
'use strict';
const puppeteer = require('puppeteer');

const ODOO_BASE_URL = 'http://localhost:8069';
const ODOO_DB = 'odoo18_dev';

(async () => {
  const browser = await puppeteer.launch({
    headless: 'new',
    args: ['--no-sandbox', '--disable-setuid-sandbox'],
  });

  // login
  const lp = await browser.newPage();
  await lp.goto(`${ODOO_BASE_URL}/web/login`, { waitUntil: 'domcontentloaded' });
  const r = await lp.evaluate(async (url, db, l, p) => {
    const resp = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ jsonrpc: '2.0', method: 'call', params: { db, login: l, password: p } }),
    });
    return await resp.json();
  }, `${ODOO_BASE_URL}/web/session/authenticate`, ODOO_DB, 'admin', 'admin');
  console.log('login uid:', r.result?.uid);
  await lp.close();

  const page = await browser.newPage();
  page.on('console', m => console.log(`[browser ${m.type()}]`, m.text()));
  page.on('pageerror', e => console.log(`[browser ERROR]`, e.message));

  await page.setViewport({ width: 1400, height: 2000, deviceScaleFactor: 1.5625 });

  const fixture = '01_simple/03.1120815-監造會議記錄.docx';
  const url = `${ODOO_BASE_URL}/dobtor_doc_editor/test?fixture=${encodeURIComponent(fixture)}`;
  console.log('navigate:', url);

  await page.goto(url, { waitUntil: 'networkidle2', timeout: 60000 });

  // wait for ready or 15s timeout
  try {
    await page.waitForFunction(() => window.__canvasEditorReady === true, { timeout: 15000 });
    console.log('ready flag set');
  } catch (e) {
    console.log('ready flag timeout, continuing anyway');
  }

  await new Promise(r => setTimeout(r, 1500));

  // dump DOM info
  const info = await page.evaluate(() => {
    function describe(el, depth=0) {
      if (!el) return null;
      return {
        tag: el.tagName,
        cls: el.className,
        id: el.id,
        rect: el.getBoundingClientRect ? el.getBoundingClientRect().toJSON() : null,
        children: depth < 3 ? Array.from(el.children).map(c => describe(c, depth+1)) : '...',
      };
    }
    const container = document.getElementById('ce-test-container');
    return {
      docEditor: !!window._docEditor,
      ready: !!window.__canvasEditorReady,
      canvasEditorWindow: !!window['canvas-editor'],
      bodyClass: document.body.className,
      containerHTML: container ? container.outerHTML.slice(0, 500) : 'NO CONTAINER',
      containerStructure: container ? describe(container) : null,
      allCanvases: Array.from(document.querySelectorAll('canvas')).map(c => ({
        cls: c.className,
        id: c.id,
        w: c.width, h: c.height,
        cssW: c.clientWidth, cssH: c.clientHeight,
        visible: c.offsetParent !== null,
        parentCls: c.parentElement?.className,
        parentId: c.parentElement?.id,
        parentTag: c.parentElement?.tagName,
      })),
    };
  });

  console.log('canvas-editor on window:', info.canvasEditorWindow);
  console.log('window._docEditor:', info.docEditor);
  console.log('ready:', info.ready);
  console.log('container HTML (first 500):', info.containerHTML);
  console.log('all canvases:', JSON.stringify(info.allCanvases, null, 2));
  console.log('container structure:', JSON.stringify(info.containerStructure, null, 2));

  await page.close();
  await browser.close();
})();
