# PDF 匯出引擎評估報告（W9-10 P2-3）

**狀態**：W9-10 補強衝刺實作  
**對應漏項**：P2-3 — PDF 匯出引擎選型未說明  
**完成日期**：2026-05-06

---

## 1. 現況確認

讀 `models/doc_document.py:522-545`：

```python
def _generate_pdf(self, record=None):
    """使用 Odoo 內建 wkhtmltopdf 產生 PDF。"""
    full_html = self._build_full_html(rendered_body=...)
    Report = self.env['ir.actions.report']
    pdf_bytes = Report._run_wkhtmltopdf([full_html], ...)
    return pdf_bytes
```

當前 PDF 引擎 = **wkhtmltopdf**（透過 Odoo `ir.actions.report._run_wkhtmltopdf`）。

DOCX 匯出用 **LibreOffice headless**（`soffice --headless`），見 [doc_document.py:589-614](../models/doc_document.py#L589)。

匯入路徑（`/dobtor_doc/import`）也用 **LibreOffice headless**，見 [doc_controller.py:528+](../controllers/doc_controller.py#L528)。

---

## 2. wkhtmltopdf 已知問題

| 問題 | 影響 |
|---|---|
| **官方已停止維護**（2023 年起 archived） | 安全更新停止；新 CSS3 / web font / SVG 特性無進一步支援 |
| **CJK 字型 fallback 偶爾失敗** | 中文文件部分字元變方塊 |
| **Canvas 元素不渲染**（dobtor 用 canvas-editor 是 Canvas 渲染） | 直接從 canvas-editor 截 HTML 給 wkhtmltopdf 會失精度 |
| **複雜 CSS（flex / grid）支援不完整** | 多欄、複雜表格可能跑版 |
| **SVG 嵌入字型不支援** | 數學公式（OMML → KaTeX → SVG）字型可能糊掉 |

對 dobtor 而言**最關鍵的問題**：canvas-editor 是基於 Canvas 渲染，wkhtmltopdf 不支援 Canvas，所以目前的 PDF 路徑是「DOM 序列化成 HTML」，不是「直接從 canvas 渲染」。這會導致 PDF 內容與螢幕看到的有差距。

## 3. 三個替代選項對比

### 3.1 LibreOffice headless（沿用既有 DOCX 路徑）

```bash
# 把 HTML / DOCX 經 LibreOffice 轉 PDF
soffice --headless --convert-to pdf input.docx --outdir /tmp/
```

| 維度 | 評分 |
|---|---|
| 成熟度 | ✅ 高（活躍維護，支援 OOXML 規格） |
| CJK 字型 | ⚠️ 視容器字型而定；Linux 容器需安裝思源黑體 / Noto CJK |
| 容器負擔 | ⚠️ 中（~150MB；已在 ChienYi container 內，不另增） |
| 渲染精度 vs canvas-editor 螢幕 | ❌ 低（LibreOffice 內部排版引擎與 canvas-editor 完全不同） |
| 大文件效能 | ⚠️ 中（每份文件 1-3 秒 cold start） |
| 與既有架構整合 | ✅ 已用於 DOCX 匯出，再加 PDF 不增依賴 |

**適用場景**：DOCX → PDF 轉換時用，因為已經先過 LibreOffice 渲染了再轉就一致。

### 3.2 Chromium headless（新方案）

```bash
chromium --headless --print-to-pdf=output.pdf --no-margins http://localhost/preview
# 或用 puppeteer / playwright
```

| 維度 | 評分 |
|---|---|
| 成熟度 | ✅ 極高（活躍維護，最新 Web 標準） |
| CJK 字型 | ✅ 高（用瀏覽器標準字型 fallback） |
| 容器負擔 | ❌ 高（Chromium ~300MB+；puppeteer 已在 dev deps 但 prod 不該 ship） |
| **渲染精度 vs canvas-editor 螢幕** | ✅ **完美**（用同一個 Canvas 渲染管線） |
| 大文件效能 | ✅ 高（GPU 加速） |
| 與既有架構整合 | ⚠️ 需建獨立 service（不在 odoo container 內，避免肥化） |

**適用場景**：canvas-editor 內容直接匯出 PDF（精度最高），代價是要建獨立 service。

### 3.3 自寫 Canvas → PDF（極端路線）

用 `pdf-lib` 或 `pdfkit` 把 canvas-editor 的 IElement[] 重新渲染成 PDF。

| 維度 | 評分 |
|---|---|
| 成熟度 | ❌ 完全自寫，bug 多 |
| CJK 字型 | ⚠️ 取決於是否整合 HarfBuzz |
| 容器負擔 | ✅ 低（純 npm dep） |
| 渲染精度 | ⚠️ 中（與 canvas-editor 不一致） |
| 開發成本 | ❌ **極高**（重寫 1/3 個排版引擎） |

**適用場景**：暫不考慮（投入產出比差）。

## 4. 建議方案

### 4.1 短期（W11+ 主線完成前）：保持 wkhtmltopdf + LibreOffice 雙路徑

- HTML 路徑（編輯中文件直接 PDF）：wkhtmltopdf（沿用）
- DOCX → PDF 路徑（匯入後或匯出後）：LibreOffice headless（沿用）
- 對齊到「使用者抱怨字型才換」

### 4.2 中期（W11+ 後，Phase 5 完成時）：切到 LibreOffice 為單一引擎

- 把所有 PDF 路徑統一走 LibreOffice
- 解決 wkhtmltopdf 失維護風險
- 代價：CJK 字型需在 container 內預裝

### 4.3 長期（高保真匯入 A 級達成後）：考慮 Chromium headless

- 待 dobtor_doc_editor 已能處理 95% docx 還原，再投入 PDF 引擎升級
- 用 sidecar service 模式（獨立 Docker container），非綁進 Odoo 主 container

## 5. CJK 字型清單（W9-10 部分驗收）

ChienYi Docker container（odoo18）需確認下列字型已安裝：

```dockerfile
# Dockerfile 應有
RUN apt-get update && apt-get install -y \
    fonts-noto-cjk \
    fonts-noto-cjk-extra \
    fonts-arphic-uming \
    fonts-arphic-ukai
```

驗證指令：

```bash
docker exec odoo18 fc-list :lang=zh-tw | head
docker exec odoo18 fc-list :lang=ja | head
```

**現況**：未確認（屬於 W11+ Docker 整合範圍）。建議在 Phase 4.5 結束前納入容器構建檢查。

## 6. 實作檢查清單

- [x] 文件化當前 PDF 引擎（wkhtmltopdf）
- [x] 文件化當前 DOCX 引擎（LibreOffice）
- [x] 列出 wkhtmltopdf 已知問題
- [x] 對比 3 個替代方案
- [x] 提出短中長期建議
- [ ] CJK 字型 container 安裝（屬 W11+ 範圍）
- [ ] 對齊到主線後切換策略決策

## 7. 與 scope_decision.md 的關係

[scope_decision.md](scope_decision.md) §3 表格中：

> | 系統自動產出、無人工編輯 | ✅ QWeb | ❌ dobtor |

QWeb PDF 報表用 wkhtmltopdf 走的是 Odoo 標準路徑，**不在本評估範圍內**。本文件討論的是 dobtor_doc_editor 自身 export 的 PDF 路徑（編輯中文件 → PDF）。

這兩條 PDF 通路目前都用 wkhtmltopdf；長期換 LibreOffice 時兩條一起換可降低 ChienYi 整體維護成本。

---

**附註**：此評估對應規劃文件 `dobtor_doc_editor_高保真匯入開發規劃.md` 的 §5.5b Phase 4.5 P2-3，與 plan `d-work-doc-editor-pure-duckling.md` 的 W9-10 段。
