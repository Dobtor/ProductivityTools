# dobtor_corpaas_knowledge_marketing — 產品行銷出口（商品頁）

CorPaaS 方案知識核心（`dobtor_corpaas_knowledge`）的出口二。契約：
`dobtor_corpaas_knowledge/IMPLEMENTATION_SPEC.md`「模組 B」。

## 模型

| 模型 | 用途 |
|------|------|
| `corpaas.knowledge.pitch` | 能力卡片（content mixin）：能力、情境、標題、內文、乾淨版截圖、方案商品。**一律人工核准**。 |
| `corpaas.knowledge.claim` | 宣稱：文字＋錨定功能點（`feature_ids`），`state` ok/check。 |
| `corpaas.knowledge.release_note` | 本期新增（content mixin）：一次 refresh 一篇，一律核准。 |
| `product.template`（擴充） | `knowledge_pitch_ids`、`knowledge_release_note_ids`、`_knowledge_package()`、`_knowledge_upsell_capabilities()`。 |

## 行為

- **上線快照**：核准（`_knowledge_publish`）時把內容寫進 `live_json`，商品頁只讀快照。
  編輯中／送審中／失效中的卡片，前台仍是上一次核准的版本。下架清掉快照。已發佈的卡片改過後可以再「送審」。
- **上線欄位防護**（`corpaas.knowledge.marketing.guarded`）：`state`、`live_json`、`images_hidden`
  （宣稱的 `state` 也是）只能由狀態機與事件派送（context `knowledge_marketing_publish`）寫入；
  表單／RPC 直接寫會被擋。複製一律回草稿。
- **依方案判斷存在**：卡片掛 `package_id`（建立時帶入商品頁對應的方案）；功能是否還在用
  `feature.is_present_in(package)`。別的方案拿掉同一個功能，這個方案的卡片不動。
- **宣稱錨定**：`feature_removed`（功能在該方案真的不在了，且沒有改名候選——本次 `rename_candidate`
  事件或待確認／已確認的 `corpaas.knowledge.rename`）→ 引用它的宣稱 `check`、卡片失效、`images_hidden`。
  商品頁不顯示待查的宣稱。核准前每句宣稱都要錨定到方案裡存在的功能點（至少一個），且不能有待查宣稱：
  改錨定到現有功能會自動回正常；「確認無誤」只在錨定的功能都還在時可用。核准不會把待查洗成正常。
- **畫面大改**（`scope_changed`）：只把卡片的截圖換成同一張的最新版（連同上線快照），宣稱與狀態不動。
  `form_changed` 不動。
- **本期新增**：同一次 refresh 的 `feature_added`，已掛在方案能力上、或 AI 分類提議（未排除）
  歸入能力者 → AI 起草 → `knowledge_propose('claim')`。預算用完先留草稿（`ai_pending`），下次 refresh 補寫。
  提到的功能從方案消失 → 這篇失效，商品頁只顯示 published 的最新一篇。
  已發佈的一篇可按「發給既有訂戶」：開郵件精靈（mass_mail、每人一封），收件人＝這個方案變體
  （套件指定的變體，或同分支的變體）在用合約行（`dobtor.contract.line` state new／inprogress、未過期）的客戶；
  不會自動寄。
- **AI 按鈕一律排入佇列**：卡片「AI 起草行銷文案」、能力「AI 起草行銷文案」、本期新增「AI 重新起草」
  → `corpaas.knowledge.ai.enqueue(record, '_ai_draft_run', package)`；refresh 期間的起草仍同步。
  AI 的 HTML 經 `html_guard.clean`：標籤／class／屬性都是白名單（拿掉 style/script/svg/img、id、data-*，
  `<a>` 只留文字）。
- **截圖**：只從核心 `corpaas.knowledge.asset`（state=current、屬於能力在方案裡的功能點）挑，同情境優先；
  被重拍取代的圖在前台自動跟到同 shot 的最新版。公開顯示用 attachment access token。
- **商品頁**：CorPaaS 方案詳情頁是 `dobtor_corpaas_website.corpaas_solution_content`
  （`/corpaas/solution/<product.product id>`），區塊掛在「產品簡介」（`div.soldx-intro`）之後；
  `/shop` 的 `website_sale.product` 也在 `#product_full_description` 之後顯示。
  方案由頁面的變體解析（`_knowledge_package(variant)`：變體專屬套件優先、其次通用套件、同分支、已上架優先）。
  內容：這個方案的能力卡片、最近一篇本期新增、加購可得。
- **加購可得**：只看掛在這個方案上的能力（`package.knowledge_capability_ids`，published／stale），
  缺的模組全部可單獨販售＝addon（與 `availability_for` 同規則，但整頁只查一次模組），
  連到同分支的 `is_sellable` 模組產品 `/module/content/<id>`。
- **help API**：`_knowledge_help_links` super 後補 `kind='upsell'`：命中功能的能力在方案是 addon，
  或問句直接比中 addon 能力 → 連到 `public_base_url + /corpaas/solution/<方案變體 id>#kb-addon-<code>`。

## 權限

編輯者可建立／修改卡片與本期新增、增刪宣稱；核准者核准、退回、下架、確認宣稱；管理者可刪除。
前台不開公開模型權限：`_knowledge_marketing_values()` 以 sudo 只讀核准快照，出錯只記 log、不讓商品頁 500。

## 測試

`tests/`（`post_install`、`-at_install`；AI 與佇列以 mock 取代）：上線欄位防護、已發佈再送審、
宣稱錨定（依方案、改名候選不算消失）、畫面大改只換圖、待查宣稱不上商品頁、核准要求宣稱已處理、
本期新增起草／不重複／預算用完下次補／功能消失失效／發給訂戶、upsell 依方案且只查一次、
AI 按鈕排入佇列、還原修訂重建宣稱、HTML 白名單。
