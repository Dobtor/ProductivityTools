# QWeb 報表 → 文件範本：轉換器覆蓋範圍與政策

**建立日期**：2026-10-08
**適用範圍**：`models/doc_qweb_converter.py`（`doc.qweb.converter`）與它依賴的
`models/doc_render_mixin.py` 快照管線
**實測環境**：Odoo 18.0-20260908，樣本為 `sale` / `account` / `stock` /
`purchase` 的五張原生報表
**狀態**：五張樣本可轉、可渲染；剩下的缺口都是「刻意不猜」的那一類（§6）

這份文件要回答的是：**哪些 QWeb 構造轉得過去、哪些不行、為什麼不行**，
以及**怎麼自己量一次**。它不是設計說明——設計決策寫在程式碼註解裡，
因為那些註解旁邊就是會壞的那一行。

---

## 1. 兩條鐵律

**① 從 arch 讀，不從值推。**
`t-field="doc.partner_id"` 把路徑寫得清清楚楚，所以簡單路徑直接綁好。
反過來「看渲染出來的值長得像什麼再猜欄位」那條路不做——猜錯不會報錯，
只會印出別人的資料。

**② 旗標化，不要猜。**
認不出來的寫法原樣保留並標成「待確認」（藥丸轉成橘色）＋一條待辦，
而不是自己編一個語意。理由是這個管線所有的失敗策略都是「寧可多印」：
條件求值失敗當成真、來源取不到當成空。猜錯的語意會變成「少印」，
而少印在單據上幾乎追不到。

**③ arch 一定要用 combined。**
`view.arch_db` 只有那張 view 自己寫的一段，模組對報表做的擴充完全看不到。
一定要 `_get_combined_arch()`——實測漏掉 purchase_stock 加上去的整塊
「Shipping address」，而且普查時看到樹裡有 `<xpath>`／`<attribute>`
（那是繼承指令）就是這個原因留下的痕跡。

轉換完如果給了樣本記錄（`convert_report(report, validate_with=record)`），
每個藥丸的表達式都會被試算一遍：算得出來的把「待確認」拿掉，算不出來的
留著並附上真正的錯誤訊息。**強烈建議給樣本**——那是把「規則表猜的」變成
「實測過的」唯一方法。

---

## 2. 支援的 QWeb 構造

| QWeb | 轉成 | 備註 |
|---|---|---|
| `t-field` / `t-out` / `t-esc`（簡單路徑） | 欄位藥丸 | many2one 由管線印 `display_name`：Jinja 的字串化會給 `res.partner(7,)`，偵測到這種 repr 就改用 `display_name` 重算 |
| `t-options` widget `monetary` / `date` / `datetime` / `integer` / `float` | 包成 `format_money` / `format_date` / `format_number` | |
| `t-options` widget `contact` | `format_address(…)` | 依 `fields` 決定要不要帶名稱 |
| `t-options` 的 `date_only` | `format_date(…, 'lang')` | 那不是 widget，採購單用它把 datetime 印成日期 |
| **沒帶 widget 的 float / monetary / integer** | `format_number` / `format_money`（float 看欄位 digits） | 原生 QWeb 也會依型別印，不補會印成 `100.0` |
| **沒帶 widget 的 date / datetime** | `format_date(…, 'lang')` / `'lang_datetime'` | 語言格式；原生印 `10/08/2026` |
| **沒帶 widget 的 selection** | 藥丸只帶 `path`，由渲染層印標籤 | 原生 `t-field` 走 `ir.qweb.field.selection` 印標籤；不處理會印出 `done`（實測兩張 stock 報表） |
| **沒帶 widget 的 many2one / x2many** | 藥丸只帶 `path`，渲染層補 `.display_name` / `names(…)` | 事前依型別，不是事後猜「輸出長得像 repr」 |
| **沒帶 widget 的 boolean** | 不動（`True` 印 "True"、`False` 印空白） | **刻意**：原生 QWeb 對布林沒有 field converter，補 ☑/☐ 會與原生不一致。要方框的範本明寫 `checkmark(object.x)` |
| `<table>` + `<tr t-foreach>` | 重複列（`source='repeat'` 標記） | 只支援「表格列」粒度 |
| `<t t-foreach>` 包 `<tr>` | 同上 | |
| 非表格的 `t-foreach`（`<div>` 清單） | 自動包成**單欄無框表格**再重複 | 迴圈體含表格時不包，標待辦 |
| 迴圈變數 `<var>_index` / `_first` / `_last` / `_size` | `loop_index` / `loop_first` / `loop_last` / `loop_size` | 管線逐列注入；index 與 QWeb 一致 0 起算 |
| `<var>_index + 1` 當項次 | 流水序號藥丸（`op='index'`，1 起算） | |
| `t-if` 在區塊元素上（`div`/`p`/…） | 條件區塊（單欄虛線表格） | |
| `t-if` 在行內元素或 `<t>` 上 | 收得成一句就轉**三元式藥丸**；否則條件區塊 | 後者會多一個換行，有待辦 |
| `t-if` 與取值在同一節點 | 三元式藥丸 | |
| `t-if` 在 `<table>` 上 | 條件區塊包住整張表 | |
| `t-if` / `t-elif` / `t-else` 兄弟鏈 | 純文字或單一取值 → 一顆三元式；否則巢狀「若／否則」區塊 | |
| `<tr t-if>` | 列條件藥丸 | 迴圈內會換成 `line.…`，逐列求值 |
| `<t t-if>` 包住 `<tr>` | 列條件藥丸（`t-else` 取反、`t-elif` 兩者都要） | |
| 同一個 `t-if` 掛在 `<th>` 與 `<td>` | 欄條件 | |
| 列內用 `<t t-if>` 包不同格子組合 | 列型分派（`rowFilter`） | |
| `t-call` 子範本 | **前置展開**：子範本內容就地併入樹裡 | 最多 4 層；循環呼叫會停並標待辦 |
| `t-call` 的參數（子節點或前一個兄弟的 `t-set`） | 每個呼叫點獨立命名後內聯 | 見 §4 |
| `t-call="*document_tax_totals*"` | 內建「稅額彙總」區塊 | 含公司幣別版 |
| `t-call="web.external_layout"` 的 `address` / `information_block` / 標題 | 本文頂端的左右兩欄（無框表格） | 頁首頁尾一律留空交給外框範本 |
| `t-set` 中間變數 | 展開成它的值後再判斷 | 自我指涉（`t-set="x" t-value="o.x"`）會擋住遞迴 |
| `<img t-att-src="image_data_uri(...)">` | 圖片藥丸（路徑） | |
| `<img>` 的 src 是算出來的 | 圖片藥丸（表達式） | 要算出 `data:` URI 或 base64 影像 |
| 條碼圖片 | 條碼藥丸（預設 QR） | 型別與取值欄位要人工確認 |
| `len(x)` | 同名 helper | Jinja 本身沒有 `len` |
| dict 當 `t-foreach` 來源 | 重複（走**值**不走鍵） | 配合 `來源[迴圈變數]` → `line` 收斂 |
| `groups="a,b"` / `groups="!a"` | 併進同節點的 `t-if`（`has_group(…)`） | 逗號是 OR、`!` 是反向；掛在 `t-else` 上的不併，留待辦 |
| `env.user.has_group(…)` | 同名 helper | 沙箱擋 `env`，但 helper 等價 |
| `t-options` widget `barcode` | 條碼藥丸（symbology / width / height / humanreadable） | 型別不在支援清單時退回 Code128 並留待辦 |
| `class` 的 `text-end` / `text-center` / `text-start` | 段落對齊（`rowFlex`） | `<td>` 與裡面的 `<span>` 都看 |
| `class` 的 `fw-bold` / `fst-italic` / `text-muted` | 粗體／斜體／灰字 | 其餘（`col-*`、`mb-*`…）是版面網格，沒有對應物 |
| `style="width: N%"` | colgroup 欄寬 | 沒指定的欄平分剩下的寬度 |
| `t-att-class` 的三元式（含鏈式） | **條件式格式標記** | 條件成立才套用粗體／斜體／顏色／對齊；放在列內＝整列、段落裡＝整段 |
| QWeb 累加器（`current_subtotal`） | **分組重複 + 分組小計** | 「加什麼」與「在什麼條件下切分」都從 arch 讀；抓不到切分條件時留空讓使用者指定 |

### 自動改寫的慣用寫法

Jinja 沒有 lambda、也沒有生成式，所以這幾種一定要改寫（不改寫會是
`TemplateSyntaxError`，而求值失敗＝「當真」＝該濾掉的列全部印出來）：

| 原式 | 改寫成 |
|---|---|
| `X.filtered(lambda v: v.attr)` | `X\|selectattr('attr')\|list` |
| `X.filtered(lambda v: not v.attr)` | `X\|rejectattr('attr')\|list` |
| `X.filtered(lambda v: v.attr == 'a')` | `X\|selectattr('attr', '==', 'a')\|list` |
| `X.filtered(lambda v: v.attr not in (…))` | `X\|rejectattr('attr', 'in', (…))\|list` |
| `any(v.attr for v in X)` | `X\|selectattr('attr')\|list\|length > 0` |
| `', '.join([(t.a or t.b) for t in X])` | `X\|map(attribute='b')\|join(', ')`（取 `or` 鏈**最後**一個） |
| `X.sorted(key=lambda …)` | 去掉排序，改用重複列的「排序欄位」 |
| `o.sudo()` | 去掉（沙箱不開放提權） |
| `o._generate_qr_code(...)` | `o.partner_bank_id.build_qr_code_base64(…)`（見 §3） |
| 白名單內的底線方法 | `report_helper(對象, '方法名', …)`（見 §3） |

認不出來的形狀一律原樣保留 ＋ 待辦，**不猜**。

---

## 2.5 格式規則只有一份表

「欄位型別該怎麼格式化」的權威是 `doc.render.mixin`
（`RenderFields._type_format_expression`），在**渲染層**。轉換器呼叫它，
編輯器插入藥丸時**不帶格式**（只帶 `path`），於是：

* 轉換過來的範本與手工做的範本，同一個欄位印出來一樣
* 換語言時 selection 的標籤跟著換，不必重新轉換
* 要改格式規則只有一個地方

優先序：藥丸明寫的 `expression` > `meta.format` > 型別預設。前兩個是使用者
（或原範本的 widget）明講的，預設不會蓋掉它們。

轉換器只套數字與日期（`numeric_only=True`）。

**`t-field` vs `t-out` 這個問題已經量過並結案（2026-10-09）**：兩者語意確實不同
（`t-field` 走 `ir.qweb.field.<型別>` 的 converter、`t-out` 只是字串化），所以
理論上轉換器該分開處理。實際量的結果是——

* 36 張報表裡「`t-out` / `t-esc` 指向 float / monetary / integer / date /
  datetime 欄位」的節點：**0 個**
* 四張報表的保真度前後對照：**一個 token 都沒變**

原生報表的數字與日期一律走 `t-field`。所以那個分界在這批報表上是純粹的多餘
分支，實作後收回了。真的遇到「某張客製報表用 `t-out` 印金額而我們多格式化了」
再加，加的時候用 §8 的量測腳本確認它真的改變了什麼。詳見 ADR-024。

## 3. 底線方法白名單

沙箱擋掉所有底線開頭的方法——那是提權的主要入口，不放寬。但原生報表確實會
呼叫幾個純計算的輔助方法，擋掉的後果是單據上那一段印成空白而且沒有訊息。
所以開一道窄門：`doc.render.mixin._SAFE_REPORT_METHODS` 是 `(模型, 方法名)`
配對，沙箱裡用 `report_helper(對象, '方法名', …)` 呼叫，**模型與方法名都要
對得上**，不在名單上回空字串。

目前六筆（每一筆都讀過實作、確認不寫資料）：

| 模型 | 方法 | 為什麼安全 |
|---|---|---|
| `account.payment.term` | `_get_amount_due_after_discount` | 只算百分比與四捨五入 |
| `account.payment.term` | `_get_last_discount_date_formatted` | 只格式化日期 |
| `sale.order` | `_get_order_lines_to_report` | 只有 `filtered` |
| `account.move` | `_is_eligible_for_early_payment_discount` | 只有比較與 `filtered` |
| `stock.move` | `_get_report_description_picking` | 只有字串處理 |
| `stock.move.line` | `_get_aggregated_product_quantities` | 只組一個 dict 回傳 |

**要加新的方法**：先想清楚能不能改用 compute / related 欄位——那條路不需要
任何白名單，也不必信任誰。真的要加就繼承 `doc.render.mixin` 覆寫那個集合，
並在註解裡寫出「為什麼安全」。

**`account.move._generate_qr_code` 刻意不在名單上**：它在回傳前
`self.qr_code_method = …`，也就是**印一張 PDF 會改資料**。轉換器改走公開的
`res.partner.bank.build_qr_code_base64()`（參數與原生相同、`qr_method` 留空
讓它自己挑，差別只在不回寫）。`tests/test_pill_pipeline.py` 有一則測試釘住
這個決定。

---

## 4. 子範本展開的三個前提

`t-call` 是**前置展開**（把子範本內容併進樹裡），不是「在呼叫點另外輸出」。
理由：子範本的內容常常是 `<tr>` 或 `<td>`，那些格子屬於呼叫端那張表格，
另外輸出的話 `_emit_table` 找不到它們（它找列用的是「同一棵樹裡最近的
`table` 祖先」）。

展開本身不難，難的是這三件（每一件都讓出貨單整張印不出來過）：

1. **每個呼叫點的變數要獨立命名。** 同一個子範本常被呼叫多次、參數不同
   （出貨單的 `aggregated_lines` 有三處）。不改名的話同一個名字被賦值多次
   會被當成 QWeb 累加器而不內聯，那一整段的取值全變待確認。
   參數常寫成 `t-call` 的「前一個兄弟」，所以只改**最靠近的那個** `t-set`
   與它到呼叫點之間的引用——整層一起改會把後面那組的參數也改掉。
2. **`repeatId` 要以 (迴圈變數, 來源) 為鍵。** 同一個子範本展開到同一張表格
   多次時 id 會撞，而撞了會被當成同一組的「列型」——來源只取第一個，
   於是「第一個來源剛好是 0 筆」就整組不印。
3. **`來源[迴圈變數]` 要在 `t-set` 展開之前收斂成 `line`。** 展開後文字會變成
   `(report_helper(…))[line]['name']`，正則就配不到來源名字了。

---

## 5. 快照管線的 pass 順序

順序有意義，不可對調。完整說明在 `_snapshot_content_json` 的註解裡，這裡只
列順序與一句理由：

1. **展開重複列** — 要在純量求值前，展開產生的列裡 `source='line'` 藥丸必須
   以各自的明細求值。重複列內「沒有 groupId」的條件也在這一步就地解決
   （那種條件要逐筆判斷，第 3 關只有 `object` 可用）。
2. **展開稅額彙總** — 同樣會產生新的列，要在條件之前。
3. **條件（列 → 欄 → 段落）** — 欄一定排在列之後：列條件的標記可能就放在
   某一欄裡，先刪欄會讓那個列條件無聲消失。
4. **清掉空表格** — 1 與 3 都可能把列全部移除。
5. **純量藥丸求值**。
6. **收合空段落（規則 A）** — 必須在求值後。段落裡有表格時不收合
   （表格是獨立區塊，和同段落的藥丸無關）。

---

## 6. 刻意不支援的（連同理由）

| 構造 | 為什麼不做 |
|---|---|
| `any(u._is_portal() for u in X)` 這類**生成式 + 方法呼叫** | Jinja 沒有生成式，而 `map`/`select` 不能呼叫方法。編一個語意出來比留著語法錯誤危險（前者會少印） |
| **條件欄**（整個 `<td>` 存不存在取決於某個累加器變數） | 「欄條件」機制要求 `<th>` 與 `<td>` 掛同一個 `t-if`；出貨單的 `has_serial_number` 是累加器變數，對不上 |
| **動態 inline 樣式**（`t-att-style` 45、`t-attf-style` 31） | 多是標籤紙的版面幾何（`padding_page`、`visibility:hidden`、SVG 的 `stroke`）。文件模型沒有對應物，硬湊只會得到一個似是而非的版面。逐類留待辦 |
| **`t-attf-class`**（28 處） | `#{…}` / `{{…}}` 內插的字串。裡面多是 `report_type == 'html'` 的螢幕／列印切換與 col-* 網格，對 PDF 沒有意義 |
| SVG / canvas 繪圖 | 標籤報表用 SVG 畫線。文件模型只有文字、表格、圖片 |
| `.sudo()` | 沙箱不開放提權。欄位受 ACL 限制讀不到的話，要在 `doc.report` 層先算好 |
| 外部 / 靜態 URL 圖片 | 匯出不該在使用者按下載時去連外——那會讓匯出時間取決於第三方網站，在無外網的容器還會直接卡住 |
| 任意區塊重複（非表格列） | canvas-editor 的元素串列是扁平的，任意區塊的起訖標記在使用者編輯時極易被拆散。表格列有天然邊界 |

---

## 7. 五張原生報表實測（2026-10-08）

### 7.1 轉換與試算

都給了樣本記錄試算，都「內容齊全、標記無殘留」：

| 報表 | 藥丸 | 條件 | 試算成功 | 試算失敗 | 待確認 |
|---|---|---|---|---|---|
| `sale.action_report_saleorder` | 54 | 21 | 43 | 0 | 4 |
| `sale.action_report_pro_forma_invoice` | 54 | 21 | 43 | 0 | 4 |
| `account.account_invoices` | 115 | 52 | 91 | 0 | 6 |
| `stock.action_report_delivery` | 144 | 56 | 51 | 0 | 39 |
| `purchase.action_report_purchase_order` | 49 | 13 | 41 | 1 | 1 |

- 採購單那一個失敗就是 §6 的生成式。
- 出貨單的「待確認 39 / 未試算 78」偏高是因為它有兩套明細表（未驗證走
  `move_ids`、已驗證走彙總的 `move_line_ids`），一筆樣本只會命中一套。
  兩套分別用「已確認」與「已驗證」的揀貨單實測過都印得出來。

### 7.2 輸出比對（與原生報表的 HTML 逐 token 比）

「表達式算得出來」不等於「印出來一樣」。這一項的量法：兩邊都渲染成 HTML、
去標籤、比對可見 token 的多重集合。

**量的時候有兩個坑**（兩個都踩過，第一次量出「完全一致」的假結果）：

1. `doc.report` 的綁定會接管 `_render_qweb_html`。**原生一定要先渲染**，
   建綁定之後所謂的「原生」就是我們自己的輸出。
2. 量完要把綁定拆掉，否則下一個用到同一張報表的案例也會被接管。

| 報表 | 原生 token | 我們 | 漏印 | 多印 |
|---|---|---|---|---|
| `sale.action_report_saleorder` | 60 | 71 | 2 | 13 |
| `account.account_invoices` | 42 | 54 | 2 | 14 |
| `purchase.action_report_purchase_order` | 59 | 79 | 4 | 24 |

銷售訂單與發票剩下的 2 個漏印都是 `Odoo` 與 `Report`——原生的 `<title>`，
不是單據內容。採購單多的那 2 個是電話號碼的斷詞（`+1`、`555-555-5556`
在我們這邊黏在一起）。

多印的主要來源：

- 位址區塊取了第一個分支（有待辦），發票上還會印兩次。
- 頁碼「第 N / M 頁」是我們的外框印的，原生在 HTML 階段是空的（PDF 才填）。
- 條件求值失敗時「寧可多印」的代價看得見：採購單印出原生沒印的行銷區塊。

多印的主要來源：

- 位址區塊取了第一個分支（有待辦），發票上還會印兩次。
- 頁碼「第 N / M 頁」是我們的外框印的，原生在 HTML 階段是空的（PDF 才填）。
- 條件求值失敗時「寧可多印」的代價看得見：採購單印出原生沒印的行銷區塊。

## 7.5 附頁的頁數實測（2026-10-08，手動）

`TestAppendPagesEndToEnd` 在本機 rig 永遠是 **skip**：測試模式下 Odoo 會把
`_render_qweb_pdf` 短路成 HTML（怕 worker 不夠跑 wkhtmltopdf），用
`force_report_rendering` 強制的話，wkhtmltopdf 會回頭向同一個 Odoo 行程要
assets，而 `--workers=0` 只有一條執行緒——死結到 timeout（實測一則卡 5 分鐘）。

所以頁數是用 `odoo shell` 手動量的（shell 不對外服務 HTTP，沒有那個死結）：

| 情境 | 頁數 | 預期 |
|---|---|---|
| 沒有附頁（本體） | 1 | — |
| ＋固定 PDF（2 頁） | 3 | 1+2 ✓ |
| 固定 PDF 放前面 | 3 | 頁數同、順序不同 ✓ |
| 固定 PDF ＋記錄自備（各 2 頁） | 5 | 1+2+2 ✓ |
| 記錄關掉附頁（opt_out） | 1 | 回到本體 ✓ |
| **兩筆一起印** | **6** | **(1+2)×2 ✓** |

最後一列是重點：它證明附頁是**逐筆**合併的。在 `_render_qweb_pdf` 之後才動手
的話會變成「本體A＋本體B＋附頁」＝ 4 頁，而**單筆列印時完全看不出差別**。

CI 若以多個 worker 跑，那一組測試就會真的執行。

## 7.8 引擎天花板（wkhtmltopdf）——已知、不打算硬解

這三件不是缺陷，是 wkhtmltopdf 的性質。寫在這裡，免得有人再花時間去試。

| 限制 | 後果 | 現在怎麼處理 |
|---|---|---|
| **頁首頁尾是整份 PDF 共用一份** | 多筆列印時頁首頁尾只能以第一筆記錄求值；逐筆範本覆寫也改不了外框 | 以第一筆求值並在 `_build_report_html` 的註解寫明；外框不同時留 warning log |
| **頁首頁尾每頁重載、只拿得到網址參數** | 「首頁不同／奇偶頁不同」沒有版面開關可用 | 頁面範圍標記 ＋ 一小段依 `page` 掛 class 的 script（§2 的對照表） |
| **測試模式下 Odoo 把 `_render_qweb_pdf` 短路成 HTML** | 附頁的頁數沒辦法在 `--workers=0` 的 rig 上測（強制渲染會與 wkhtmltopdf 的回呼死結） | 那組測試在 `workers=0` 時 skip 並明講，頁數改用 §7.5 的手動量測 |

真正的解法是換 PDF 引擎（headless Chrome 之類），那是另一個量級的決定，
不在這個模組的範圍內。要動之前先把 §7.5 的六個情境與 §7 的保真度量一次當基準。

## 7.9 已知的偶發失敗（2026-10-09 量過）

`TestControllerSecurityBoundary.test_upload_template_null_byte_filename_rejected`
會偶發失敗。量出來的數字：

| 情境 | 結果 |
|---|---|
| 單獨跑那個類別（6 則） | **6/6 綠** |
| 整份測試（588 則） | 今天 9 次裡紅 1 次 |

症狀是回應不是 JSON——測試自己的註解寫著「200 有兩種來源（上傳真的成功、
或請求被導去登入頁）」，也就是 session 沒建立。`setUp` 裡有
`self.authenticate('admin', 'admin')`，所以不是忘了登入。

單獨跑全綠、整份跑才偶發，指向**單 worker 下的 HTTP 競爭**：`HttpCase` 的
請求由同一個行程的另一條執行緒服務，而測試本身握著 cursor。同一個原因讓附頁
的端到端測試在 `--workers=0` 下直接死結（§7.5）。

### 查過什麼、排除了什麼（2026-10-09）

| 嫌疑 | 結果 |
|---|---|
| `setUp` 忘了登入 | ✗ 有 `self.authenticate('admin', 'admin')` |
| `registry.clear_cache()` 讓 session 失效（`_compute_session_token` 是 `@ormcache('sid')`，而 `test_report_engine.py` 有一處 clear_cache）| ✗ **寫探測測試實證排除**：連續清五次再打請求，session 都還活著 |
| 單 worker 的 HTTP 競爭 | 無法證實也無法排除——10 次專門重現的執行都沒再出現 |

**根因沒找到。** 唯一那次出現是在我剛改動測試檔案集合（藥丸測試拆成五支）
的那一次執行之後；檔案集合穩定下來之後 13 次連續全綠，另外 10 次專門重現
也沒出現。

### 找到的真缺陷：`type='http'` 路由會回 HTML

追這個症狀（「回應不是 JSON」）時挖出一個**與偶發無關、一直存在**的缺陷。

#### 業務情境——這一類缺陷已經發生過一次

2026-06-29（`0ef991b`）：「修正模板上傳『Unexpected token `<`』」。使用者在
編輯器按「匯入」選一個 `.docx` 要當列印模板，觸發點是**伺服器沒裝
python-docx**（manifest 刻意不宣告成 `external_dependencies`，所以模組裝得
起來、只有這支會炸）或**選到改過副檔名的假 docx**（`BadZipFile`）。

機制：`type='http'` 路由的例外被 `HttpDispatcher.handle_error` 映射成
werkzeug 的 `BadRequest(args[0])` / `Forbidden`，werkzeug 渲成
`<!doctype html>…<p>訊息</p>`。前端 `resp.json()` 撞上 `<` 就是那個錯誤。

那次修了兩邊（後端把 try 包大、前端加 `_readJsonResponse` 剝標籤當訊息），
但修法是**逐點補，不是結構保證**。四個月後稽核發現 try 仍然沒包到最開頭。

#### 2026-10-09 稽核量到的實際缺口

| 路由 | try 之前 | 實際會發生什麼 |
|---|---|---|
| `upload_template` | 4 行 | **真缺口**。`_require_document()` 拋 `AccessError`（只有讀取權限的協作者）、`MissingError`（編輯期間文件被刪）、`ValueError`（`doc_id` 非數字） |
| `import_document` | 11 行 | 那幾行都是 `return _json_resp(...)` **自己回 JSON**，不是拋例外。掛 decorator 是**預防性**的——那段只要有人往裡面加東西就會漏 |

⚠️ 不要把 `import_document` 寫成「正常的錯誤路徑全部回 HTML」——量過了，
它的暴露面比第一版紀錄講的小。

症狀也要講精確：使用者**不是**「按了沒反應」。6 月加的 `_readJsonResponse`
會剝標籤取前 200 字當訊息，所以訊息不是消失，是**降級**。實測 werkzeug
3.0.1 的錯誤頁，使用者看到的是：

```
上傳失敗：伺服器錯誤 (HTTP 400)：400 Bad Request Bad Request 此功能僅適用於文件；目前編輯的是範本，請先從文件開啟。
```

而那些 guard 的訊息都是**設計過要給使用者看的提示**（`_require_document` 的
docstring 寫明「寧可在這裡明確擋下並告訴使用者原因」）。

查證過兩個原本懷疑的情境，**都不成立**：範本模式與輸出模式下
`state.docId` 是 null（`doc_editor.js:612`），而 `_handleImportFile` 沒有
docId 時根本不打後端、直接走 canvas 預覽。所以「範本模式按匯入」打不到這支，
id 也不會跨模型送錯。

#### 修法與目的

`DocControllerBase.json_http_route`：包住那一類路由，任何漏出來的例外一律變成
帶 `error` 的 JSON（UserError / MissingError / AccessError 給 400，其餘 500
並記 log）。四則測試，移掉 decorator 會全部變紅（驗過）。

目的有三層，第一層才是使用者感覺得到的：

1. **讓設計好的訊息原樣送達**——走回前端主路徑
   `if (!result.success) throw new Error(result.error)`，使用者看到
   「上傳失敗：文件不存在或已被刪除。」而不是夾著兩次 `Bad Request` 的半英文。
2. **把保證從「正則剝標籤」移到結構上**。6 月那個 fallback 能成立，只因為
   werkzeug 剛好把訊息放在 body、而且 `_readJsonResponse` 一直在剝標籤。
   任何人新寫一個呼叫端、寫出最自然的 `await resp.json()`，就退回
   `Unexpected token '<'`。所以測試裡有一則**讀原始碼**掃「有 `type='http'`
   且回 JSON 卻沒掛 decorator」。
3. **讓症狀沒有歧義**——「回應不是 JSON」從此不可能來自 handler。

誠實的界線：**500 那一路，使用者看到的訊息兩邊都一樣籠統**（werkzeug 的
`InternalServerError` 本來就不帶描述）。真正的體驗差異在上面那三個 400 情境。
500 那一路能補的只有「可追」——見下一節。

⚠️ 寫那四則測試時第一版有一則是**假綠**：我查 `__wrapped__` 有沒有值，但
`http.route` 自己就用 `functools.wraps`，所以移掉我的 decorator 之後它照樣綠
——查的是 Odoo 的包裝不是我的。改成讀原始碼判斷「有 type='http' 且回 JSON
卻沒掛 decorator」，這樣才對得上「有人加新路由忘記掛」那個情境。

### 收尾三件（2026-10-09 第二批）

把上面那份分析剩下的三個缺口補完。

#### 1. session 逾時——唯一還活著的使用者可見缺陷

`SessionExpiredException` **不走**例外映射：`HttpDispatcher.handle_error` 對它
是特例，直接 `redirect_query('/web/login', ..., code=303)`。而 `fetch()` 預設
`redirect: "follow"`，所以呼叫端拿到的是**登入頁 HTML、status 200**，不是 4xx。

業務情境：編輯器是會開著好幾小時的畫面（寫合約、排版報表）。午休回來按
「匯入」，session 已經過期 → `_readJsonResponse` 把登入頁剝成純文字：

```
上傳失敗：伺服器錯誤 (HTTP 200)：Odoo 電子郵件 密碼 登入 管理資料庫…
```

修法：`doc_editor_shared.js` 的純函式 `isSessionExpiredResponse(resp)`
（`resp.redirected` 且 `pathname === '/web/login'`），`_readJsonResponse` 在
讀 body 之前先問它 → 丟「連線已逾時，請重新登入後再試。」。

效果：這條線上**兩個來源都有名字了**——handler 那半回 JSON（decorator），
auth 那半被辨識成逾時。剝標籤那段因此降為真正的最後一道（反向代理的錯誤頁、
不經 Odoo 的 502），保留是因為不花成本，而拿掉之後同一個症狀會退回
`Unexpected token '<'`。

#### 2. 500 那一路給得出可追的指標

非預期例外的**內容**不能給使用者（會洩 traceback），但**指標**可以：
`json_http_route` 產一組 8 碼 ref，同時進 log（`ref=…`）與回應訊息
（「伺服器錯誤（代碼 3f9a1c20），請提供此代碼給管理員。」）。

效果：使用者報修時那串字能一次 grep 到那筆 traceback。沒有它的話 log 裡可能
有幾十筆同樣訊息，對不起來。測試
`test_unexpected_exception_returns_traceable_ref` 斷言**兩邊是同一組代碼**
——只驗其中一邊的話，各自有代碼但對不起來也會綠。

#### 3. 紀錄本身的更正

第一版的 commit 訊息、`doc_controller_base.py` 的註解、
`TestHttpRoutesAlwaysReturnJson` 的 docstring 與本節，都把 `import_document`
的暴露面與使用者看到的症狀講重了。commit 訊息改不了，其餘三處已據實更正。
講重了跟講輕了一樣是失準——下一個讀註解的人會以為修掉了一個比實際更大的洞，
也會因為註解誇大而對 decorator 的必要性打折。

#### JS 純函式怎麼測

這個模組沒有 hoot／QUnit 基礎設施，而 `web.assets_unit_tests` 要瀏覽器 runner
——CI 刻意不跑瀏覽器。但 `doc_editor_shared.js` **零相依**（它存在的理由就是
切斷循環 import），所以 node 可以直接載入它。

`tests/js/test_shared_pure.mjs`：讀檔 → `data:text/javascript` 動態 import →
斷言。7 則，掛進 static CI（擋 PR）。移掉偵測會變紅（驗過）。

☠️ 不能寫 `import "../../static/.../doc_editor_shared.js"`：那個目錄沒有
`package.json`，node 會把 `.js` 當 CommonJS 解析，撞到 `export` 就掛。
這支測試開頭另外斷言「shared 不能出現 import」——哪天它有了相依，該修的是
那件事，不是繞過這個斷言。

### 做了什麼（不是遮蔽）

1. **`setUp` 加 session 健康檢查**（`_assert_session_alive`）：打一次
   `/web/session/get_session_info`，不是 JSON 就在**那裡**失敗並說
   「session 不可用，後面的失敗都是這個造成的」。
   下一次若再發生，失敗會直指原因，而不是看起來像被測路由壞了。
2. **那一則在請求前就地重新登入**：把「登入」縮到緊貼「動作」之前，讓它只
   依賴自己那一刻的狀態，不依賴 setUp 到斷言之間整個 suite 的全域狀態。
   這一則要測的是「multipart 檔名含 null byte 的處理」，不是「session 撐不撐
   得過整份測試」——後者若真的壞了，健康檢查會在它自己的斷言上說出來。

3. **失敗訊息自己帶診斷**：不是 JSON 時，訊息會印出轉址紀錄、session 在
   store 裡還有沒有 `uid`、token 對不對得上，並明說「handler 不可能回非
   JSON，所以是 auth 層導去登入頁」。下一次發生，一次就定位。

改完之後**連續 34 次全綠**（1 + 8 + 25）。中間那 25 次是帶著證據蒐集跑的
（每次都把回應、session uid、token 比對寫進檔案），26 筆紀錄全部 `ok=True`。

**那不證明根因消失了**，只證明：在這個 rig 的條件下重現不出來。
原始發生率是 14 次紅 1 次，34 次綠在統計上壓不下那個區間。

☠️ **CI 升 v3（阻擋式）的前提**：阻擋式 gate 配上偶發失敗等於訓練大家無視
紅燈，比沒有 gate 更糟。backend workflow 停在 v2.5（PR 上跑但不擋）；
升 v3 的條件是**夜間連續三次全綠**——而那三次現在也同時是這一則的觀察期。

⚠️ 量測時踩到的坑：用 `--log-level=warn` 跑會**看不到 `tests.result` 那一行**
（它是 INFO），於是看起來像「沒有結果」。量 flaky 率要用 `--log-level=test`。

## 7.10 「寫好了但從沒真的執行過」——順著這條線索查全模組（2026-10-09）

static CI 第一次真的在 GitHub 上跑（`77ebe40` 寫好之後一直沒推，所以從沒執行
過）就紅在**檢查本身**判準太寬。那件事給了一條可以複用的線索：**模組裡還有
什麼是「寫好了、看起來在運作、但其實從沒被執行或驗證過」的？**

### 查了四類，結果

| 類別 | 結果 |
|---|---|
| 測試的 tag | **綠**。113 個類別全部有效帶 tag（四個沒寫 `@tagged` 的繼承 `NativeReportCase`，Odoo 的 `test_tags` 是類別屬性會被繼承）。沒有任何測試被標成不在標準範圍 |
| 五支 cron 的方法 | **都存在、都在對的模型上**。⚠️ `gc_old_logs` 在 `doc.editor.error.log`（30 天）與 `doc.editor.export.log`（180 天）**同名不同實作**，用檔案全文搜尋會誤判成「測過了」 |
| cron 有沒有被測試呼叫 | **一支沒有**：`_cron_health_check_no_alias`，每天跑 |
| 吞掉例外卻沒 savepoint | 掃到 7 處，**只有 1 處是真的**（詳下） |

### 真缺陷：`record_export()` 的承諾做不到

`doc.editor.export.log` **整支模型零測試**，四支方法（`record_export` /
`gc_old_logs` / `get_no_alias_summary` / `_cron_health_check_no_alias`）
一個都沒被測過，其中一支每天跑。這比紀律 13 的「半死測試」更糟：不是測試
沒人跑，是**production 程式碼每天在無人看管下跑，而沒有任何東西證明它還
能跑**。

而 `record_export` 的 docstring 寫：

> 任何例外都吞掉——log 失敗絕不可擋住下載。

☠️ **try/except 只接得住 Python 例外**。資料庫層的錯誤（FK / NOT NULL /
型別）會讓 PostgreSQL 整筆交易進入 aborted，於是吞掉之後呼叫端接下來的 DB
動作全部失敗——`action_export_pdf` 在那一行之後**4 行**就
`ir.attachment.create(...)`。

實測（移掉 savepoint 再跑）：

```
psycopg2.errors.InFailedSqlTransaction: current transaction is aborted,
commands ignored until end of transaction block
```

所以那句承諾原本是**做不到的**：下載照樣壞，只是壞在一個跟真正原因無關的
地方。修法是 `with self.env.cr.savepoint():`——同一個理由模組**自己**已經
寫在 `doc_controller_devtools.py:83`（那裡先踩過），只是沒套到這裡。

### 另外六處為什麼不動

- `doc_controller.py:254` / `:352`、`doc_convert.py:513`：我的 AST 掃描
  **誤判**——那幾個 `.write(` 是**檔案**寫入（`f.write(bytes)`）不是 ORM。
- `doc_controller_template.py:235` / `:279` / `:310`：真的是 ORM
  create/write/unlink，但吞掉之後**立刻 return**、沒有後續 DB 動作。那幾支
  route 一次只做一件事，交易被中止正好就是想要的結果。依「不對正常運作的
  程式做多餘優化」不動。

### 補了八則測試

`TestExportLog`：`record_export` 寫入與 `record_ref`、**交易被圍住**（移掉
savepoint 會紅，驗過）、`gc_old_logs(180)`、`get_no_alias_summary` 的計數與
時間窗、cron 有沒有寫出可被監控抓取的 warning、以及**沒問題時不可以留
warning**（每天叫一次狼來了就沒人看了）。

☠️ 那一則刻意失敗的測試要 `mute_logger('odoo.sql_db', '…doc_telemetry')`：
不消音的話每次跑測試都在 log 裡留一筆 ERROR——那正是「訓練大家無視紅燈」，
跟「阻擋式 gate 不該配上偶發失敗」是同一個理由。

### 這條線索的用法

下次想找缺陷又沒有症狀可循時，問這三個問題比通讀程式碼有效：

1. 這段**什麼時候真的被執行過**？（cron / CI / 只在本機 / 從來沒有）
2. 它的 docstring **承諾**了什麼？那個承諾**可驗證**嗎？
3. 同一個教訓模組裡**別處**有沒有寫過？（有就是漏套，不是新發現）

## 8. 怎麼自己量一次

```bash
# 全部 backend 測試（含原生報表的整合測試：實際轉換 + 渲染 + 斷言內容）
# 預設讀 /etc/odoo/odoo.conf；資料庫在另一個容器時用 ODOO_ARGS 自帶連線參數
docker exec <容器> env ODOO_DB=<db> HTTP_PORT=8169 \
  ODOO_ARGS="--db_host=<pg> --db_user=odoo --db_password=odoo \
             --addons-path=<paths> --without-demo=" \
  bash /mnt/pt/dobtor_doc_editor/tests/scripts/run_backend_tests.sh \
  --tag=dobtor_doc_editor
```

整合測試在 `tests/test_qweb_converter_native.py`。它只斷言兩件不該變的事：
**試算失敗必須是 0**（採購單例外，白名單在測試裡寫明）、
**單據上該出現的字要出現、標記文字不可殘留**。
刻意不斷言「幾顆藥丸、幾條待辦」——那種數字會隨 Odoo 小版本變動，
拿它當基準的測試遲早變成「改版就紅」。

`sale` / `account` / `stock` / `purchase` 沒裝時那幾則會**明講跳過**
（訊息寫「原生報表轉換未驗證」），不會靜默略過。要讓它們真的跑：

```bash
# 以本機 rig 為例
docker exec qcodoo odoo -d <db> --db_host=... --addons-path=... \
  -i sale,account,stock,purchase --without-demo= --workers=0 \
  --max-cron-threads=0 --stop-after-init
```

規則層面的單元測試在 `tests/test_qweb_converter.py`，arch 一律是自己寫的
最小範例、不依賴原生報表的 XML。兩層都要有：單元測試擋語法層面的回歸，
整合測試擋「規則互相影響」那一類——後者實際發生過（白名單改寫接上去之後
明細來源的判斷失效，銷售訂單的品名與章節整批消失，而單元測試全綠）。

---

## 9. 踩過的坑（每條都有對應的測試）

- `./tbody/tr` 找不到包在 `<t t-foreach>` 裡的列，而表頭那一列找得到，
  所以 fallback 不會啟動——轉出一張只有表頭的明細表。
- `colspan="99"` 是 QWeb 的「跨滿整列」慣用寫法，加總會得到 99 欄的 colgroup。
- 分組被 `filter` 吃掉：`not line.display_type` 會先把章節列濾掉，
  分組就再也找不到分隔點。
- `canvas-editor` 的 `getValue()` 不序列化 `id`，所以不能用 id 差異找新插入的
  表格（要用內容簽章，而且要刻意忽略幾何值）。
- Jinja 的 `Undefined` 在屬性存取時就 raise，所以 `format_money(x, currrency)`
  這種打錯字會炸掉整份文件。
- 不存在的欄位在條件裡是 **falsy 而不是錯誤**，語意與「求值失敗」相反。
- `0.0 == False`：`value in (None, False)` 會把金額剛好是 0 的那一期印成空白。
- 判斷「有沒有綁到根變數」不可以寫 `'line.' in expr`：dict 迴圈變數寫的是
  下標 `line['date']`，帶點的字串比對會判成「不是明細欄位」。
- 段落邊界只認 `value == '\n'`，而表格元素的 `value` 是空字串——
  段落收合會把同段落的表格一起帶走。
- `_table` 是 Odoo 的保留屬性，定義成方法會讓整個模組載不起來。

