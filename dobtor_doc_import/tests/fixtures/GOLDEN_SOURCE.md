# golden PNG 的渲染來源

```yaml
renderer: libreoffice            # ← 當前
target:   microsoft-word         # ← 目標（2026-10-09 收斂後）
status:   MISMATCH
```

## 為什麼這是一個缺口，而不是一個設定

126 張 golden PNG 全部由 **LibreOffice headless → PDF → pdftoppm → PNG** 產出
（`tests/scripts/generate_golden.sh`）。而 2026-10-09 之後，這個模組的目標收斂成
**1:1 重現 Microsoft Word**。

所以：

> **即使視覺回歸 diff 降到 0%，也只代表「我們渲染得跟 LibreOffice 一樣」，
> 不代表跟 Word 一樣。**

LibreOffice 自己對 Word 的重現就不是 1:1——它的斷行、字距、表格列高、分頁
規則都與 Word 有差。拿它當 1:1 Word 的基準，等於用一把不準的尺去校準。

規畫書 §2.2 的成功指標寫的也是「pixelmatch 對比 **LibreOffice headless** 渲染的
PNG，差異率 <2%」——那個指標在舊範圍下合理（LibreOffice 是當時唯一能自動化的
參考），在新範圍下**不合理**。

## 要補什麼

| 缺件 | 現況 | 需要 |
|---|---|---|
| **Word 渲染的 golden** | 無 | Word 自動化輸出每頁 PNG。可行路徑：Windows + Word COM（`Document.ExportAsFixedFormat` → PDF → PNG）、或 Word Online 的轉檔 API |
| **真正的 Word 字型** | VR 的 `--font-metrics` 用 Debian 替代字型（DroidSansFallback / LiberationSerif） | 標楷體（DFKai-SB）、新細明體（PMingLiU）、微軟正黑體——都是 Windows 授權字型，要在有授權的機器上取 |
| **基準數字** | mean 0.073191（對 LibreOffice，2026-05-25） | 對 Word 重新量一次。**目前完全沒有這個數字** |

## 這份檔案的作用

`tests/unit/golden_source.test.ts` 會讀上面那個 YAML 區塊：

- `renderer` 與 `target` 不一致 → 測試**會紅**，訊息說明「diff 降到 0 也不等於達標」
- 不是要阻止開發，是**不讓這個不一致變成沒人記得的事**

哪天真的拿到 Word 的 golden，把 `renderer` 改成 `microsoft-word`，測試就綠了。
在那之前，每次跑 vitest 都會被提醒一次。
