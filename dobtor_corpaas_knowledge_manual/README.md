# dobtor_corpaas_knowledge_manual — 操作說明出口

CorPaaS 方案知識核心（`dobtor_corpaas_knowledge`）的出口一：把「功能 × 情境」的操作說明
自動截圖、標註、推到每個方案產品的文件型 slide 課程。契約見核心的 `IMPLEMENTATION_SPEC.md`「模組 A」。

## 模型

| 模型 | 用途 |
|---|---|
| `corpaas.knowledge.step_block` | 步驟區塊（D4 內容）：功能 × 腳本範圍指紋，跨情境、跨方案共用。`anchor` 建立後不變，分岔沿用母區塊的錨點 |
| `corpaas.knowledge.step_block.merge` | 指紋收斂的合併提案（人工確認後引用改指、被併入的下架） |
| `corpaas.knowledge.shot_template` | 截圖腳本範本：步驟用 `"{name}"` 佔位符；`elements` 由 highlight/click/fill 推導＝指紋的腳本範圍 |
| `corpaas.knowledge.shot_binding` | 範本 × 情境：佔位符 → 示範資料 xmlid；拍攝狀態與素材 |
| `corpaas.knowledge.article` | 文章（D4 內容）：步驟區塊＋情境區塊＋素材；`render_html()` 組裝 |
| `corpaas.knowledge.placement` | 文章 × channel：各自擁有一張 slide；`is_canonical` |
| `corpaas.knowledge.channel_section` | channel 章節（能力；空＝共通操作）對應的 `is_category` slide |
| `slide.channel`（擴充） | `knowledge_product_tmpl_id`（一個方案產品一個 channel）、`knowledge_managed` |

## 流程

★ 鍵一律帶指紋：範本、步驟區塊、文章（功能×情境×指紋）、素材都以腳本範圍指紋為鍵。方案 A 改版只產生
A 那個指紋的新東西，方案 B 的文字與圖不受影響。方案拿到某篇文章＝它目前（任一角色）的指紋等於文章指紋、
且功能是它的候選（圈選核准、改名候選的新鍵除外）。

1. **指紋範圍**：`_knowledge_elements_for` 回傳該方案目前指紋的範本 elements。定義改了（範本被修）→
   核心呼叫 `_knowledge_fingerprint_rebaselined`：範本／區塊／文章／素材原地 old → new，記一筆
   `corpaas.knowledge.manual.rebase` 對照（還沒 refresh 的方案經對照換算）。
2. **挑情境**：沒有這個指紋的範本或繫結、待拍、成功卻沒素材、情境示範資料變了。失敗等修的繫結不算。
3. **拍攝**：新指紋 → 複製舊範本（不叫 AI）；完全沒有範本 → AI 探索 → 解析 xmlid → 一批拍完 →
   D1（`gate_bad_records(records, refs)`）→ dHash 換圖（素材 scope_hash＝範本指紋）→ 失敗（含佔位符／角色）
   列入 AI 修補，連續 3 次失敗停下等人。
4. **分派**：逐方案下架（只撤這個方案的位置，slide 取消發佈不刪；全部方案都沒有才整篇下架）→
   修繫結 → **對帳**（每次 refresh 掃全部候選，不只這次事件）：指紋相符的文章換圖／失效回復／掛上新方案；
   同鍵曾下架 → 送審復原；只有舊指紋的 → 只有本方案在用就原地換鍵，共用就分岔一篇新的（核准後接手本方案
   的同一張 slide）；一篇都沒有 → 起草（同指紋區塊共用，只有別的指紋就以它為底分岔）→ 同功能同指紋的區塊
   有兩份以上 → 合併提案（人工確認）。
5. **發佈**：前台一律用上線快照組裝（文章的標題／情境區塊／區塊清單、各區塊的文字），上線後被改、
   沒審過的文字不會被重拍或重推帶上線；文字與上線版不同時純重拍也要送審。引用新區塊的文章要跟區塊一起核准。
   每個 channel 一個 savepoint：寫 slide（lang=zh_TW）→ 讀回比對 → 重新編號；不一致整個 channel 回滾、
   位置留 `sync_error`、`last_synced_rev` 不動，下一次 refresh 重推。批次核准與一次 refresh 裡每個 channel
   只同步＋重新編號一次（sequence 一條 SQL 寫完）：同 channel 核准 60 篇約每篇 33 次查詢、50 篇 0.7 秒。
   空章節（含下架後變空的）不發佈。channel 帶「產業／方案類型」標籤（方案產品變體的 CorPaaS 標籤）。
6. **審核**：文章審核頁有文字差異（文章與步驟區塊分開）、截圖前後對照（dHash 差距）、影響範圍，
   「依情境批次核准」；核准沒改字 → 情境免審計數 +1，改過或退回 → 歸零。按鈕觸發的 AI 走
   `corpaas.knowledge.ai.enqueue`。

## 陷阱（已處理）

- ☠️ `slide.slide.channel_id` 必填：一張 slide 只能在一個 channel → 每個 placement 自己一張 slide，用 canonical 指向主要位置。
- ☠️ 章節的 `category_id` 由 sequence 計算：每次同步整個 channel 重新編號；廢章節先排到最後再刪
  （原生 unlink 會 `_move_category_slides` 把整個 channel 重排 1..n），刪完再套一次。
- ☠️ 非成員只能開 `is_preview` 的 slide → 全部設 `is_preview=True`。
- ☠️ 文件型 channel 在 promote_strategy 為 specific/none 時預設依發佈日期排序 → 覆寫
  `WebsiteSlides.channel`（`@http.route()` 沿用原路由），knowledge_managed 沒指定 sorting 時用 `sequence`。
- ☠️ slide 的 `is_published` 寫入要 `can_publish`（文件型：負責人或 slides 管理員）→ channel 以 OdooBot 建立，
  之後一律以 channel 負責人身分寫 slide。
- ☠️ `slide.write({'is_published': True})` 每次都重設 `date_published` → 已上線不再寫；文字實質改寫
  （去掉圖片後的文字雜湊變了）才自己重設。純重拍不重設。
- ☠️ `html_content` sanitizer 會吃 `<style>`／`<script>`／`<svg>`／style 定位 → 紅框編號用 PIL 畫進
  「manual 標註版」附件（`public=True`），原圖不動（行銷出口要乾淨版）。

## 前台 canonical

`website.layout` 的 `<link rel="canonical">` 改成 `kb_canonical_url or <原本的網址>`；
`website_slides.slide_main` 在呼叫 layout 前設 `kb_canonical_url = slide._knowledge_canonical_url()`；
全螢幕模板（`slide_fullscreen`）自己的 head canonical 也改成同一個網址。
不是方案知識的頁面值為空，行為與原生相同（不會出現兩個 canonical）。

## 測試

`tests/`：`post_install`，不接 SSH／docker／AI Hub（shooter、sandbox、`corpaas.knowledge.ai.ask` 全 mock）。
涵蓋重新編號、is_preview、canonical、date_published、標註繪圖、拍攝採用／D1／dHash／修腳本／預算、
步驟區塊分岔與合併、新文章草稿、下架、help 連結、改名。
