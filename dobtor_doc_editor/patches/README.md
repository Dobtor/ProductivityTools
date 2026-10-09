# patches/ — canvas-editor 第三方修補

此目錄存放 [patch-package](https://github.com/ds300/patch-package) 對 `node_modules/@hufe921/canvas-editor` 的差分檔。

## 為什麼用 patch-package 而不是 git fork？

| 階段 | 機制 | 適用時機 |
|------|------|----------|
| **Day 1 ~ Sprint 5** | patch-package | patch 量少（< 10 檔），可承受每次 `npm install` 重套 |
| **Sprint 6 起** | git submodule fork | 大規模改動 Renderer / Layout 層，需獨立分支管理 |

當下我們在 Day 1 階段，先用 patch-package。

## 工作流程

### 修改 canvas-editor 源碼

```bash
cd /mnt/d/work/odoo18-docker/addons/dobtor_doc_editor

# 1. 直接編輯 node_modules 內檔案
vi node_modules/@hufe921/canvas-editor/dist/src/editor/...

# 2. 產出 patch 檔
npx patch-package @hufe921/canvas-editor

# 此時會在 patches/ 產出 @hufe921+canvas-editor+0.9.128.patch
git add patches/
git commit -m "patch(canvas-editor): 描述修改原因"
```

### 套用 patch（CI 與其他開發者）

```bash
npm install
# postinstall hook 會自動執行 `patch-package`，把 patches/ 套回 node_modules/
```

## Patch 紀錄規範

每個 patch 必須在 `docs/patches/` 對應一份 markdown 說明：

```
docs/patches/001_table_vmerge_cross_page.md
docs/patches/002_line_metrics_harfbuzz_hook.md
...
```

格式：
- **Patch 檔名**：對應 patches/ 中的 .patch 檔
- **修改範圍**：哪些檔案、為什麼
- **上游 Issue**：若已回報 hufe921/canvas-editor，附連結
- **遷移路徑**：如果上游接受 PR 後此 patch 可移除，記錄條件

## 升級 canvas-editor 版本

1. 先讀完所有 patches/ 中的 .patch，確認上游新版是否已修復
2. `npm install @hufe921/canvas-editor@<new-version>`
3. `npm install` 看哪些 patches 套不上 → 手動解 conflict → `npx patch-package` 重新產出
4. 跑 `make test-fixtures` 全套回歸
5. Commit 含「patches 升級對照表」

## 何時切換到 git submodule fork

當下列任一情境發生時：

- `patches/` 累積 > 10 檔
- 單個 patch 超過 500 行
- 需要修改 canvas-editor 核心架構（不只是補洞）
- 需要持續對特定 commit 維護（與 npm 版本脫鉤）

切換時：
1. fork [Hufe921/canvas-editor](https://github.com/Hufe921/canvas-editor) 到 ChienYi 組織
2. `git submodule add <fork-url> vendor/canvas-editor`
3. `package.json` 把 `@hufe921/canvas-editor` 改成 `"file:./vendor/canvas-editor"`
4. 把 patches/ 內容 squash 進 fork 的分支
5. 移除 patches/ 目錄
