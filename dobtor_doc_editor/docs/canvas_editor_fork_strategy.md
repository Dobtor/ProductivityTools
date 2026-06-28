# canvas-editor Fork 策略

## 背景

`@hufe921/canvas-editor` 是本模組 docx 編輯器的渲染基礎。規劃文件預期會對它做大量修補（接收 OoxmlParser 產出的 LineMetrics、表格 vMerge 跨頁、CJK 避頭尾、自訂 Layout Engine 等）。本文件記錄兩種 fork 策略的選擇邏輯與切換時機。

## 兩條路徑

```
            [小修補：API 接點 / bug fix]
                        ↓
                 patch-package 流程
                        ↓
              patches/*.patch + docs/patches/*.md
                        ↓
              npm install 自動 apply

            [大改：Layout Engine 替換 / Renderer 重寫]
                        ↓
                Git Submodule fork
                        ↓
        vendor/canvas-editor/（自家 GitHub fork）
                        ↓
        package.json 指向 file:./vendor/canvas-editor
```

## 切換決策表

| 情境 | 推薦策略 | 原因 |
|------|---------|------|
| 加 LineMetrics 接點（10 行內） | patch-package | patch 量極小，CI 套用快 |
| 修小 bug（< 50 行） | patch-package | 易追蹤、易回報上游 |
| 表格邊框 omit on cross-page（中型） | patch-package | 還在單檔修補範圍 |
| 重寫 Layout Engine（大型） | submodule fork | 跨多檔大幅改動，patch 維護成本爆炸 |
| 自寫 Renderer 取代 canvas-editor 渲染 | submodule fork | 等於 fork 分裂維護 |
| 跟特定 commit 而非 npm 版本（不穩定追蹤） | submodule fork | npm 版本鎖定不適用 |

## 量化判斷標準

當下列**任一**條件達到，從 patch-package 切到 submodule：

- `patches/` 累積 **> 10 個 patch 檔**
- **單一 patch > 500 行**
- 需要修改 canvas-editor **核心架構**（如 `Draw.ts` 主流程）
- 需要 **跟特定 commit**（不穩定追蹤上游）

## 為何不直接用 submodule（強推 patch-package 為當前狀態）

| 維度 | patch-package | submodule |
|------|---------------|-----------|
| **CI 設定** | 0 步驟（npm install 自動） | 需 `git submodule update --init` |
| **新人入門** | 看 patches/ 即可 | 需理解 fork 分支策略 |
| **追蹤上游** | npm 版本號明確 | 需手動 merge upstream |
| **回報 PR** | 容易：patch 可直接貼到 issue | 需從 fork commit history 抽 |
| **修改規模** | 適合單檔 < 500 行 | 適合多檔大改 |
| **Bundle 大小** | 同 npm 版本 | 可裁減（移除不用模組） |

當下我們在 **Sprint 0-5 階段**，patch 量極小（甚至為零），**強推 patch-package**。

## 當前狀態（2026-05-05 截至）

- `patches/` 目錄存在但**無實際 patch**
- node_modules 為原版 `@hufe921/canvas-editor@0.9.128`
- `package.json` 已配 `postinstall: patch-package` hook（CI 友好）
- `vendor/canvas-editor/` **不存在**（Phase D 才考慮建立 submodule fork）

## 切換流程（patch-package → submodule）

當決策表觸發時：

1. **Fork** [Hufe921/canvas-editor](https://github.com/Hufe921/canvas-editor) 到 ChienYi 組織
2. 建 submodule：
   ```bash
   git submodule add https://github.com/<chienyi-org>/canvas-editor.git vendor/canvas-editor
   cd vendor/canvas-editor && git checkout -b chienyi-main
   ```
3. 改 `package.json`：
   ```json
   "@hufe921/canvas-editor": "file:./vendor/canvas-editor"
   ```
4. **squash patches/ 進 fork**：
   ```bash
   for p in patches/*.patch; do
     cd vendor/canvas-editor
     patch -p1 < ../../$p
     git add -A
     git commit -m "$(basename $p .patch)"
     cd ../..
   done
   ```
5. **移除 patches/**（保留 README.md 作切換歷史紀錄）
6. 寫 `vendor/canvas-editor/SYNC.md` 說明：
   - upstream tracking branch（通常 `main` 或 `master`）
   - 內部分支策略（chienyi-main vs feature branches）
   - 升級流程（fetch upstream → merge → 跑 fixture 回歸）

## 上游回報原則

不論用哪條策略，**修補必須有 upstream 回報路徑**：

- patch-package：每個 patch 在 `docs/patches/NNN_*.md` 必填「Upstream Issue / PR」欄位
- submodule：每個 commit 必含 `Upstream-Issue:` trailer 或 PR 連結

回報目的：避免 fork 永久脫離主線，讓未來「升級到 canvas-editor 1.0」是可行的。

## 參考

- patch-package GitHub：https://github.com/ds300/patch-package
- canvas-editor upstream：https://github.com/Hufe921/canvas-editor
- 規劃文件 §3 架構決策：`dobtor_doc_editor_高保真匯入開發規劃.md`
- patches/ 操作流程：`patches/README.md`
