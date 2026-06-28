# A11y 與 i18n 設計（P3-2）

**狀態**：補強衝刺實作  
**對應漏項**：P3-2 — 可訪問性與多語系  
**完成日期**：2026-05-06

---

## 1. 為什麼

ChienYi 主要使用者：
- 中高齡監造主管（45-65 歲）— 需要大字級、清楚的鍵盤操作
- 工地承包商（手機 + PC 混用）— 需要 touch-friendly 按鈕
- 政府業主審查 — 部分機關有 A11y 採購規範
- 視障 / 弱視員工 — 即使現在沒有，2-3 年內可能進來

不做 A11y 的代價是「未來補要砍掉重寫」，本次最小擾動先打底。

## 2. 已落地清單

### 2.1 ARIA 標記

| 元素 | role / aria-* |
|---|---|
| 文件編輯器外層 `.o_dobtor_doc_editor` | `role="application" aria-label="文件編輯器"` |
| 工具列 `.doc-toolbar` | `role="toolbar" aria-label="文件編輯器工具列"` |
| 工具列分隔線 `.doc-toolbar-sep` | `role="separator" aria-hidden="true"` |
| 文件標題 input | `aria-label="文件標題"` |
| 頁面格式 / 縮放 select | `aria-label="頁面格式"` / `aria-label="縮放比例"` |
| 儲存按鈕 | `title="儲存文件 (Ctrl+S)" aria-label aria-keyshortcuts="Control+S"` |
| 版本歷史按鈕 | `title="查看版本歷史 (Alt+H)" aria-label aria-keyshortcuts="Alt+H" aria-haspopup="dialog"` |
| 工作區 `.doc-workspace` | `role="region" aria-label="文件編輯區" aria-busy=動態` |
| 狀態列 `.doc-statusbar` | `role="status" aria-live="polite" aria-atomic="true"` |
| 載入中佔位 | `role="status" aria-live="polite"` |
| 圖示 `<i class="fa">` | `aria-hidden="true"`（旁邊有文字標籤時） |
| 版本面板 dialog | `role="dialog" aria-modal="true" aria-labelledby` |
| Portal 列表 table | `<caption class="visually-hidden">` + `<th scope="col">` + 列項 `aria-label="開啟文件 X"` |

### 2.2 鍵盤導航

`doc_editor.js` setup 內裝 `keydown` 全域 listener，支援：

| 快捷鍵 | 動作 |
|---|---|
| `Ctrl+S` | 儲存（canvas-editor 內建） |
| `Ctrl+Shift+S` | 建立版本快照 |
| `Alt+H` | 開啟版本歷史 |
| `Esc` | 關閉版本歷史對話框 |
| `Ctrl+Z / Ctrl+Y` | 復原 / 重做（canvas-editor 內建） |
| `Tab` | 工具列按鈕間導航（瀏覽器原生） |

unmount 時 `removeEventListener('keydown')` 清掉。

### 2.3 視覺強化（CSS — `doc_editor.css` 末段）

- **Focus visible outline**：所有 button/input/select/textarea 在鍵盤聚焦時顯示 3px 藍色 outline + 2px offset（不影響滑鼠 hover）
- **`.visually-hidden`**：給 caption / sr-only 文字用，視覺隱藏但 sr 可讀
- **大字級基準**：toolbar btn/title 用 `rem` 而非 `px`，使用者調整瀏覽器 root font-size 時整個編輯器跟著縮放
- **觸控區大小**：toolbar 按鈕 `min-width/min-height: 36px`（接近 WCAG 推薦的 44px，受限於既有 layout）
- **`@media (forced-colors: active)`**：Windows 高對比模式時保留邊框
- **`@media (prefers-reduced-motion: reduce)`**：使用者偏好減少動畫時，動畫 / 過渡降到 0.001s

### 2.4 i18n

新增 `i18n/` 目錄：
- `dobtor_doc_editor.pot` — 翻譯來源檔（最小骨架，列出 model/menu/UserError 字串）
- `zh_TW.po` — 繁體中文翻譯（msgid=英文 → msgstr=中文）

未來語系策略：
- **預設語系 = zh_TW**（hardcode 中文 UI 字串會被 sr 直接讀為中文）
- **加 en_US**：未來海外客戶時做，把 hardcode 中文改用 `_t()` runtime translate，msgid 改英文，現有中文移到 zh_TW.po

regenerate `.pot` 命令（W11+ 時跑）：
```bash
docker exec odoo18 odoo -c /etc/odoo/odoo.conf -d odoo18_dev \
  --i18n-export=/tmp/dobtor.pot --modules=dobtor_doc_editor \
  --stop-after-init
docker cp odoo18:/tmp/dobtor.pot \
  /mnt/d/work/odoo18-docker/addons/dobtor_doc_editor/i18n/dobtor_doc_editor.pot
```

## 3. 已知未做（待 W11+）

| 項目 | 說明 | 優先 |
|---|---|---|
| 完整 string sweep | hardcode 中文改 `_t()` | 中（等英文需求出現） |
| canvas-editor 內部 A11y | 編輯區內的選取 / 游標 sr 不可讀 | 低（canvas 本質限制） |
| 觸控區 ≥44px | 目前 36px，理想 44px | 中（影響 layout 大改） |
| 視訊操作教學字幕 | 待 P3-1 客戶導入有教學影片時做 | 低 |
| RTL 支援 | 阿拉伯文 / 希伯來文 | 低（台灣不需要） |
| WCAG AA 對比度全面審計 | 用 axe-core 跑自動化檢查 | 中（W11+ E2E playwright 跟進） |

## 4. 驗收方式

### 4.1 鍵盤導航 smoke test（人工）

1. 不用滑鼠，只用 Tab/Shift+Tab 走完工具列所有按鈕
2. Enter 觸發每個按鈕，確認動作正確
3. Ctrl+Shift+S 開啟版本快照 prompt
4. Alt+H 開啟版本歷史 dialog
5. Esc 關閉 dialog

### 4.2 SR smoke test（人工）

1. macOS：開 VoiceOver（Cmd+F5）
2. Windows：開 NVDA
3. 進入 `/web` 文件編輯器頁
4. 確認 SR 能讀出：
   - 「文件編輯器、應用程式」
   - 「文件編輯器工具列」
   - 每個按鈕的 aria-label
   - 狀態列變化（aria-live=polite 觸發）

### 4.3 自動化（W11+ playwright + axe-core）

```javascript
// 預備：tests/playwright/a11y.spec.ts
import { injectAxe, checkA11y } from '@axe-core/playwright';
test('doc editor passes WCAG AA', async ({ page }) => {
  await page.goto('/web#action=dobtor_doc_editor.action_doc_editor');
  await injectAxe(page);
  await checkA11y(page, null, {
    detailedReport: true,
    detailedReportOptions: { html: true },
  });
});
```

未來實作此 spec 屬 W11+ E2E 範圍，本次只先打底 ARIA 與 i18n 骨架。

---

**附註**：對應計畫檔 [federated-swimming-creek.md](/home/chichi/.claude/plans/federated-swimming-creek.md) 的 P3-2。
