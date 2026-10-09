/**
 * parse_docx_cli — 從命令行解析 .docx → AST JSON / canvas-editor IElement[]
 *
 * 用途（Phase E）：
 *   Python controller (doc_controller.py) 會用 subprocess 呼叫此 CLI，
 *   把 .docx 轉為 IElement[] 給 Odoo 前端 doc_editor.js 元件初始化。
 *
 * 使用：
 *   node parse_docx_cli.js <input.docx> <output.json> [flags]
 *
 *   --ast              輸出 DocumentNode（AST，含完整結構與 metadata）
 *   --elements         輸出 IElement[]（canvas-editor 初始化資料；預設模式）
 *   --svg-graphics     Sprint 358-359：SmartArt/Chart 渲成 SVG image
 *   --float-textbox    Sprint Y58：展平 wp:anchor + w:txbxContent 文字到 IElement stream
 *   --anchored-image   Sprint Y58：透傳 wp:anchor 屬性到 IElement.anchor
 *                      （給前端 plugin / round-trip writer / 排版 layer 消費）
 *
 * 輸出格式：JSON（pretty-printed for readability，可由 controller 直接傳給前端）
 *
 * 退出碼：
 *   0   成功
 *   1   參數錯誤
 *   2   檔案讀取失敗
 *   3   解析失敗（通常是 .docx 損壞）
 */

import { readFileSync, writeFileSync } from 'node:fs';
import { argv, exit, stderr, stdout } from 'node:process';
import { DOMParser, XMLSerializer } from '@xmldom/xmldom';

// 把 @xmldom/xmldom 的 DOMParser 注入 globalThis，與 tests/setup.ts 一致
// PackageReader / DocumentParser / 其他 Parser 都依賴 globalThis.DOMParser
(globalThis as { DOMParser?: typeof DOMParser }).DOMParser =
  DOMParser as unknown as typeof globalThis.DOMParser;
(globalThis as { XMLSerializer?: typeof XMLSerializer }).XMLSerializer =
  XMLSerializer as unknown as typeof globalThis.XMLSerializer;

import { OoxmlParser } from '../static/src/core/ooxml/OoxmlParser';
import { ToCanvasEditor } from '../static/src/core/ooxml/mapper/ToCanvasEditor';

interface CliArgs {
  inputPath: string;
  outputPath: string;
  mode: 'ast' | 'elements';
  svgGraphics: boolean;
  /** Sprint Y58: 展平 wp:anchor + w:txbxContent 文字到 IElement stream */
  floatTextBox: boolean;
  /** Sprint Y58: 透傳 wp:anchor 屬性到 IElement.anchor（floatImage + floatTextBox 共用） */
  anchoredImage: boolean;
}

function parseArgs(args: string[]): CliArgs {
  // args 已扣除 node + script，剩 [input, output, ...flags]
  let mode: CliArgs['mode'] = 'elements';
  let svgGraphics = false;
  let floatTextBox = false;
  let anchoredImage = false;
  let inputPath: string | undefined;
  let outputPath: string | undefined;
  for (const a of args) {
    if (a === '--ast') mode = 'ast';
    else if (a === '--elements') mode = 'elements';
    else if (a === '--svg-graphics') svgGraphics = true; // Sprint 358-359：SmartArt/Chart 渲成 SVG image
    else if (a === '--float-textbox') floatTextBox = true; // Sprint Y58
    else if (a === '--anchored-image') anchoredImage = true; // Sprint Y58
    else if (!inputPath) inputPath = a;
    else if (!outputPath) outputPath = a;
  }
  if (!inputPath || !outputPath) {
    stderr.write(
      'Usage: parse_docx_cli <input.docx> <output.json> [--ast | --elements] '
        + '[--svg-graphics] [--float-textbox] [--anchored-image]\n',
    );
    exit(1);
  }
  return {
    inputPath: inputPath!,
    outputPath: outputPath!,
    mode,
    svgGraphics,
    floatTextBox,
    anchoredImage,
  };
}

function main(): void {
  const args = parseArgs(argv.slice(2));

  // Step 1：讀檔
  let buffer: Buffer;
  try {
    buffer = readFileSync(args.inputPath);
  } catch (e) {
    stderr.write(`Error: cannot read input file "${args.inputPath}": ${(e as Error).message}\n`);
    exit(2);
    return;
  }

  // Step 2：解析
  let json: string;
  try {
    const ab = buffer.buffer.slice(
      buffer.byteOffset,
      buffer.byteOffset + buffer.byteLength,
    ) as ArrayBuffer;
    const parser = new OoxmlParser();
    const doc = parser.parse(ab);

    if (args.mode === 'ast') {
      // AST 含 Map 與 BlockNode，要用 replacer 處理 Map
      json = JSON.stringify(serializeForJson(doc), null, 2);
    } else {
      const mapper = new ToCanvasEditor({
        renderGraphicsAsSvg: args.svgGraphics,
        renderFloatTextBox: args.floatTextBox,
        preserveAnchorMetadata: args.anchoredImage,
      });
      const elements = mapper.convert(doc);
      json = JSON.stringify(elements, null, 2);
    }
  } catch (e) {
    stderr.write(`Error: parse failed — ${(e as Error).message}\n`);
    exit(3);
    return;
  }

  // Step 3：寫檔
  try {
    writeFileSync(args.outputPath, json, 'utf8');
  } catch (e) {
    stderr.write(`Error: cannot write output "${args.outputPath}": ${(e as Error).message}\n`);
    exit(2);
    return;
  }

  const flagSummary = [
    args.svgGraphics && 'svg-graphics',
    args.floatTextBox && 'float-textbox',
    args.anchoredImage && 'anchored-image',
  ]
    .filter((s): s is string => Boolean(s))
    .join('+') || 'none';
  stdout.write(
    `OK: parsed ${args.inputPath} → ${args.outputPath} `
      + `(mode=${args.mode}, flags=${flagSummary}, ${json.length} bytes)\n`,
  );
}

/**
 * 把 DocumentNode 內的 Map 轉成 plain object 給 JSON.stringify 用。
 *
 * Map / Set 預設不會被 JSON.stringify 序列化（會變空物件）。
 */
function serializeForJson(value: unknown): unknown {
  if (value instanceof Map) {
    const obj: Record<string, unknown> = {};
    for (const [k, v] of value) {
      obj[String(k)] = serializeForJson(v);
    }
    return obj;
  }
  if (Array.isArray(value)) {
    return value.map(serializeForJson);
  }
  if (value !== null && typeof value === 'object') {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value)) {
      out[k] = serializeForJson(v);
    }
    return out;
  }
  return value;
}

main();
