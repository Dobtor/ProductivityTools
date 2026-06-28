# NOTICE — Third-Party Components

This product, **dobtor_doc_editor** (LGPL-3.0), bundles or depends on the following
third-party components. Each component remains under its own license, listed below.

## 1. Frontend dependencies (npm — bundled into `canvas-editor-custom.umd.js`)

| Package | Version | License | Source | Used For |
|---|---|---|---|---|
| @hufe921/canvas-editor | 0.9.128 | MIT | https://github.com/Hufe921/canvas-editor | Core canvas-based document editor |
| fflate | ^0.8.2 | MIT | https://github.com/101arrowz/fflate | Fast zip / deflate (used by docx import / OOXML Parser) |
| harfbuzzjs | ^0.10.3 | MIT (parts: Apache-2.0 — Zephyr libc / emmalloc) | https://github.com/harfbuzz/harfbuzzjs | Text shaping (planned Phase 2 layout engine) |
| opentype.js | ^1.3.5 | MIT | https://opentype.js.org/ | Font metrics / glyph parsing |

Full license texts are in [LICENSES/](LICENSES/):
- [canvas-editor.LICENSE](LICENSES/canvas-editor.LICENSE)
- [fflate.LICENSE](LICENSES/fflate.LICENSE)
- [harfbuzzjs.LICENSE](LICENSES/harfbuzzjs.LICENSE)
- [opentype.js.LICENSE](LICENSES/opentype.js.LICENSE)

## 2. Frontend dev-only dependencies (not shipped)

These are used at build / test time only and **do not** ship with the bundle:

| Package | License | Notes |
|---|---|---|
| rollup | MIT | Bundler |
| @rollup/plugin-* | MIT | Build plugins |
| typescript | Apache-2.0 | Compiler |
| tslib | 0BSD | TS runtime helpers |
| @types/node | MIT | Type defs |
| @xmldom/xmldom | MIT | DOM polyfill for tests |
| glob | ISC | Test discovery |
| patch-package | MIT | Patch management for canvas-editor fork |
| pixelmatch | ISC | Visual regression |
| pngjs | MIT | PNG IO for visual regression |
| puppeteer | Apache-2.0 | Browser automation for visual regression |
| vitest | MIT | Test runner |

These are in `package.json` as `devDependencies`; they have **no runtime distribution
implication** for the Odoo module.

## 3. Python runtime dependencies (system packages, expected on container)

| Package | License | Purpose |
|---|---|---|
| python-docx | MIT | DOCX parsing fallback path |
| docxtpl | LGPL-2.1+ | Jinja2 + DOCX template filling (`/dobtor_doc/fill_template`) |
| Jinja2 | BSD-3-Clause | Template engine; we use `jinja2.sandbox.SandboxedEnvironment` |
| lxml | BSD-3-Clause | XML parsing |
| Pillow (PIL) | HPND (BSD-like) | Image handling |

These are not bundled — they come from the Odoo container's Python environment.

## 4. Bundled fixtures (`tests/fixtures/`)

| Source | Purpose | License |
|---|---|---|
| 100+ ChienYi internal DOCX (監造會議 / 自主檢查 / 混凝土查驗 …) | Visual-regression / parser conformance fixtures | Internal — not for redistribution |
| 251 PNG golden snapshots | Reference rendering by LibreOffice headless | Internal — derivative of the DOCX fixtures |

⚠️ **Action required if open-sourcing**: Either (a) replace internal fixtures with
synthetic public ones before publishing, or (b) keep fixtures private and ship the
module separately from `tests/fixtures/`.

## 5. Module's own license

`dobtor_doc_editor` itself is licensed under **LGPL-3.0** (see `__manifest__.py`).
This is compatible with all dependencies listed in §1-§3.

LGPL-3.0 specifically requires that recipients of the binary form be informed of:
1. The components used and their licenses (this NOTICE.md);
2. The right to obtain corresponding source code (Odoo addons are source-distributed
   so this is automatic);
3. The right to modify and replace LGPL-licensed components.

## 6. Attribution requirements summary

For commercial deployment of ChienYi or any product including this module:

- [x] **MIT components** (canvas-editor, fflate, harfbuzzjs core, opentype.js):
      Attribution included in §1 above.
- [x] **Apache-2.0 components** (parts of harfbuzzjs):
      License notice + attribution included; no NOTICE-file requirement triggered
      because no Apache-licensed components carry their own NOTICE files in our usage.
- [x] **BSD / ISC components** (Jinja2, lxml, dev-only packages):
      Attribution in §3 / §2 satisfies the typical 2-clause requirements.

If a customer requests a formal SBOM (Software Bill of Materials), this file plus
`package.json` + `LICENSES/` + the Python container's `pip freeze` constitute a
complete one. Generated SBOMs (e.g. CycloneDX) can be produced on-demand using
`npm run sbom` (TODO — to be added when first formal SBOM is requested).

---

**Last reviewed**: 2026-05-06 (補強衝刺 P3-3)  
**Next review trigger**: when adding/removing any production dependency in `package.json`,
or when bumping `@hufe921/canvas-editor` major version.
