/**
 * Sprint Y58 — CLI flag 透傳真實路徑測試（Phase E parse_docx_cli.cjs）
 *
 * 用 `child_process.spawnSync` 跑真實 build 出來的 `tools/dist/parse_docx_cli.cjs`，
 * 模擬 Python controller `_ts_parse_docx_to_elements` 的 subprocess 呼叫，
 * 驗證新增的兩個 flag 真的把 mapper options 串通到 IElement[] 輸出。
 *
 * 鎖死的不變量：
 *   1. 預設行為（無 flag）：頁碼 textbox 文字仍丟失（與 Sprint Y57 audit 一致）
 *   2. `--float-textbox`：頁碼文字出現在 IElement
 *   3. `--anchored-image`：IElement.anchor 透傳（floatTextBox 來源）
 *   4. CLI stdout 印 `flags=...` 摘要，方便 Odoo log 追查
 *   5. 兩個 flag 預設 false，向後相容（既有 `--elements --svg-graphics` 路徑不變）
 *
 * 真實標的：
 *   tests/fixtures/01_simple/03.1120815-監造會議記錄.docx
 *     - 5 個 wp:anchor（4 個非空頁碼 + 1 個空）
 *     - 0 個嵌入圖片
 *     - Sprint Y57 audit 已落定為 mapper drop 的代表性 fixture
 */

import { spawnSync } from 'node:child_process';
import { existsSync, mkdtempSync, readFileSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve, join } from 'node:path';

import { describe, expect, it, beforeAll, afterAll } from 'vitest';

const CLI = resolve(__dirname, '../../tools/dist/parse_docx_cli.cjs');
const FIXTURE = resolve(
  __dirname,
  '../fixtures/01_simple/03.1120815-監造會議記錄.docx',
);

interface CliResult {
  rc: number;
  stdout: string;
  stderr: string;
  json: unknown;
}

function runCli(args: string[]): CliResult {
  const tmp = mkdtempSync(join(tmpdir(), 'y58-'));
  const out = join(tmp, 'out.json');
  try {
    const proc = spawnSync('node', [CLI, FIXTURE, out, ...args], {
      encoding: 'utf8',
      timeout: 60_000,
    });
    const json = proc.status === 0 && existsSync(out)
      ? JSON.parse(readFileSync(out, 'utf8'))
      : null;
    return {
      rc: proc.status ?? -1,
      stdout: proc.stdout ?? '',
      stderr: proc.stderr ?? '',
      json,
    };
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
}

/** 遞迴蒐集所有 value（同 Sprint Y57 audit script，含 value=list / trList / tdList / valueList） */
function flattenText(node: unknown, out: string[] = []): string {
  if (Array.isArray(node)) {
    for (const c of node) flattenText(c, out);
    return out.join('');
  }
  if (node && typeof node === 'object') {
    const n = node as Record<string, unknown>;
    const v = n.value;
    if (typeof v === 'string') out.push(v);
    else if (Array.isArray(v)) for (const c of v) flattenText(c, out);
    for (const k of ['trList', 'tdList', 'valueList']) {
      const sub = n[k];
      if (Array.isArray(sub)) for (const c of sub) flattenText(c, out);
    }
  }
  return out.join('');
}

/** 遞迴計算帶 `.anchor` 透傳的 IElement 數 */
function countAnchored(node: unknown): { total: number; sources: string[] } {
  let total = 0;
  const sources: string[] = [];
  function visit(n: unknown): void {
    if (Array.isArray(n)) {
      for (const c of n) visit(c);
      return;
    }
    if (n && typeof n === 'object') {
      const obj = n as Record<string, unknown>;
      if (obj.anchor && typeof obj.anchor === 'object') {
        total += 1;
        const src = (obj.anchor as { source?: string }).source;
        if (src) sources.push(src);
      }
      const v = obj.value;
      if (Array.isArray(v)) for (const c of v) visit(c);
      for (const k of ['trList', 'tdList', 'valueList']) {
        const sub = obj[k];
        if (Array.isArray(sub)) for (const c of sub) visit(c);
      }
    }
  }
  visit(node);
  return { total, sources };
}

beforeAll(() => {
  if (!existsSync(CLI)) {
    throw new Error(
      `CLI bundle 不存在 (${CLI}). 跑 \`npm run build:cli\` 再執行此 sprint Y58 整合測試。`,
    );
  }
  if (!existsSync(FIXTURE)) {
    throw new Error(`Sprint Y57 標的 fixture 缺漏: ${FIXTURE}`);
  }
});

describe('Sprint Y58 — CLI flag 真實路徑透傳', () => {
  // 1. 預設行為（無 flag）：與 Sprint Y57 audit 一致（textbox drop）
  it('預設無 flag：CLI 不展平頁碼 textbox（與 Y57 audit 一致）', () => {
    const r = runCli(['--elements']);
    expect(r.rc).toBe(0);
    expect(r.json).toBeTruthy();
    expect(Array.isArray(r.json)).toBe(true);
    const text = flattenText(r.json);
    // 與 Y57 audit 報告完全一致：頁碼字串 0 次匹配
    const pageNumMatch = text.match(/第[\s\d]*頁，共[\s\d]*頁/g) ?? [];
    expect(pageNumMatch.length).toBe(0);
    // 也不應有任何 anchor 透傳
    expect(countAnchored(r.json).total).toBe(0);
    // stdout 應印 flags=none
    expect(r.stdout).toContain('flags=none');
  });

  // 2. --float-textbox：頁碼字串出現在 IElement
  it('--float-textbox：4 個非空 anchor 頁碼字串都展平進 IElement', () => {
    const r = runCli(['--elements', '--float-textbox']);
    expect(r.rc).toBe(0);
    const text = flattenText(r.json);
    const pageNums = text.match(/第[\s\d]*頁，共[\s\d]*頁/g) ?? [];
    // 4 個非空 anchor（'第1頁，共3頁' / '第2頁，共3頁' / '第3頁，共3頁' / '第4頁，共4頁'）
    expect(pageNums.length).toBe(4);
    expect(new Set(pageNums)).toEqual(
      new Set(['第1頁，共3頁', '第2頁，共3頁', '第3頁，共3頁', '第4頁，共4頁']),
    );
    // 但仍不應有 anchor 透傳（因為沒開 --anchored-image）
    expect(countAnchored(r.json).total).toBe(0);
    expect(r.stdout).toContain('flags=float-textbox');
  });

  // 3. --anchored-image：anchor 透傳但 textbox 內容仍 drop（兩個 flag 互相獨立）
  it('--anchored-image 單獨：textbox 不展平故沒有對應 IElement，故無 anchor 透傳', () => {
    const r = runCli(['--elements', '--anchored-image']);
    expect(r.rc).toBe(0);
    // 沒展平 → 沒 textbox 元素可掛 → anchor=0
    // 但既有的 floatImage 因為 fixture 沒有，所以也是 0
    expect(countAnchored(r.json).total).toBe(0);
    expect(r.stdout).toContain('flags=anchored-image');
  });

  // 4. 兩個 flag 同開：textbox 展平 + anchor 透傳
  it('--float-textbox + --anchored-image：頁碼字串展平 + anchor.source=floatTextBox', () => {
    const r = runCli(['--elements', '--float-textbox', '--anchored-image']);
    expect(r.rc).toBe(0);
    const text = flattenText(r.json);
    expect((text.match(/第[\s\d]*頁，共[\s\d]*頁/g) ?? []).length).toBe(4);

    const { total, sources } = countAnchored(r.json);
    // 5 個 wp:anchor（4 非空 + 1 空 paragraphs）都會被 mapper 看到、
    // 空 paragraphs case 會掛在段落終止符 '\n' 上（Sprint A review 已確認此 corner 行為），
    // 所以共 5 個 IElement 帶 anchor。
    expect(total).toBe(5);
    expect(sources.every((s) => s === 'floatTextBox')).toBe(true);
    expect(r.stdout).toContain('flags=float-textbox+anchored-image');
  });

  // 5. --svg-graphics 與新 flag 同時開：彼此獨立透傳、不互相干擾
  it('--svg-graphics + --float-textbox + --anchored-image：三 flag 都能正確透傳', () => {
    const r = runCli([
      '--elements',
      '--svg-graphics',
      '--float-textbox',
      '--anchored-image',
    ]);
    expect(r.rc).toBe(0);
    expect(r.stdout).toContain('flags=svg-graphics+float-textbox+anchored-image');
    const text = flattenText(r.json);
    expect((text.match(/第[\s\d]*頁，共[\s\d]*頁/g) ?? []).length).toBe(4);
  });
});

describe('Sprint Y58 — CLI 部署落差安全網', () => {
  // 6. usage 訊息列出兩個新 flag
  it('缺參數時 usage 訊息包含 --float-textbox / --anchored-image', () => {
    const proc = spawnSync('node', [CLI], { encoding: 'utf8' });
    expect(proc.status).toBe(1);
    expect(proc.stderr).toContain('--float-textbox');
    expect(proc.stderr).toContain('--anchored-image');
  });

  // 7. 未知 flag 不 crash（向後相容 — Python controller 升級早於 CLI rebuild 時關鍵）
  it('遇到未知 flag 不 crash、靜默忽略', () => {
    const tmp = mkdtempSync(join(tmpdir(), 'y58-unknown-'));
    const out = join(tmp, 'out.json');
    try {
      const proc = spawnSync(
        'node',
        [CLI, FIXTURE, out, '--elements', '--fake-future-flag-xyz'],
        { encoding: 'utf8', timeout: 60_000 },
      );
      expect(proc.status).toBe(0);
      expect(existsSync(out)).toBe(true);
    } finally {
      rmSync(tmp, { recursive: true, force: true });
    }
  });
});

// ── Phase E 真實 controller 路徑：emulate _ts_parse_docx_to_elements 的 subprocess 呼叫 ──

describe('Sprint Y58 — 模擬 Python controller subprocess 真實呼叫', () => {
  // 8. Python controller 預設 (float_textbox=False, anchored_image=False) 行為
  it('controller 預設不傳兩 flag：產出與 Sprint 358-359 後路徑 byte-identical（無 anchor、無 textbox）', () => {
    // _ts_parse_docx_to_elements 預設 argv =
    //   ['node', cli_path, in, out, '--elements', '--svg-graphics']
    const r = runCli(['--elements', '--svg-graphics']);
    expect(r.rc).toBe(0);
    const text = flattenText(r.json);
    expect((text.match(/第[\s\d]*頁，共[\s\d]*頁/g) ?? []).length).toBe(0);
    expect(countAnchored(r.json).total).toBe(0);
  });

  // 9. controller opt-in 路徑（query string float_textbox=1&anchored_image=1）
  it('controller opt-in（兩 flag=true）：真實 controller subprocess argv 達成完整透傳', () => {
    const r = runCli([
      '--elements',
      '--svg-graphics',
      '--float-textbox',
      '--anchored-image',
    ]);
    expect(r.rc).toBe(0);
    const text = flattenText(r.json);
    expect((text.match(/第[\s\d]*頁，共[\s\d]*頁/g) ?? []).length).toBe(4);
    expect(countAnchored(r.json).total).toBe(5);
  });
});
