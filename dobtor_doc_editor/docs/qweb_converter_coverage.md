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

轉換器只套數字與日期（`numeric_only=True`）。那組範圍是已經量過保真度的現狀；
原生 QWeb 對 `t-out` 的數字其實也不格式化，要不要分 `t-field` / `t-out` 得連著
重新量一次才能動。詳見 ADR-024。

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

