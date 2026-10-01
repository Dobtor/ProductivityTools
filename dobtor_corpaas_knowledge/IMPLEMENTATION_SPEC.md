# CorPaaS 方案知識核心 — 實作規格（給各出口模組）

設計文件：Claude Docs「CorPaaS 方案知識核心設計」。本檔是實作契約，**以本檔與核心原始碼為準**。
全部模組放在 `/Users/mengdawu/Documents/GitHub/ProductivityTools/`，Odoo 18，繁體中文 UI 字串，
程式註解風格比照核心（★ 標重點、☠️ 標踩過的雷），不寫多餘註解。

## 共同規則

- Odoo 18：`<list>` 不加 string；條件用 `invisible="expr"`；多行條件要加括號；settings 用 `<app>/<block>/<setting>`。
- 不寫 `numbercall` 等已移除欄位；`ir.config_parameter` 種值用 `<function ... set_param>` 不用 record。
- 對外 HTML（slide `html_content`、商品頁）只用 Odoo snippet 與 Bootstrap 5 class：
  `s_alert alert alert-info`、`table table-bordered table-striped align-middle`（thead `table-light`）、
  `badge text-bg-primary`、`d-flex`、`img-fluid rounded border`。**不能有** `<style>` `<script>` `<svg>`。
- 連結一律由系統產生、結構化回傳；AI 不寫連結。
- 所有 AI 呼叫都走 `env['corpaas.knowledge.ai'].ask(purpose, prompt, package=, refresh_token=, record=)`；
  它會記帳、檢查預算（超過拋 `hub_client.BudgetExceeded` → 呼叫端把工作留到下一次，不算失敗），
  回傳解析後的 JSON。prompt 要明確寫出 JSON 格式。
- 內容模型繼承 `corpaas.knowledge.content.mixin`（狀態機 D4）：覆寫
  `_knowledge_revision_fields()`、`_knowledge_requires_review(change)`、`_knowledge_publish()`、
  `_knowledge_unpublish()`。內容被改後呼叫 `rec.knowledge_propose(change, note)`，
  change ∈ new/text/shot/claim/restore。表單 header 按鈕照 `views/catalog_views.xml` 的能力表單樣式。
- 出口對核心的參與一律透過 `_inherit = 'corpaas.knowledge.hooks'`（AbstractModel）覆寫方法並呼叫 super。
- 權限群組：`dobtor_corpaas_knowledge.group_knowledge_editor/approver/manager`。
- 選單掛在 `dobtor_corpaas_knowledge.menu_knowledge_outlets`（出口）下。
- 每個模組要有 `tests/`：純邏輯可測的部分寫 TransactionCase（標 `@tagged('post_install', '-at_install')`），
  需要實機（SSH、docker、AI Hub）的部分用 mock。
- 不要 git commit。不要改 ProductivityTools 既有模組（dobtor_doc_editor 有別的工作階段未提交的變更）。

## 核心提供的東西（dobtor_corpaas_knowledge）

模型：
- `corpaas.knowledge.feature`：feature_key（`<模組>.<種類>:<錨點>`）、module、kind(menu/action/button/wizard/setting/report/route)、
  anchor、name、model、view_mode、view_xmlid、action_xmlid、button_name、menu_path、intents、capability_ids、
  package_ids、missing、usage_score。`views_for_fingerprint()`。
- `corpaas.knowledge.fingerprint`：feature_id、package_id、role_code、form_hash、scope_hash、elements_json、current。
- `corpaas.knowledge.capability`（content mixin）：name、code、feature_ids、scenario_ids、package_ids、pain、outcome、
  differentiator、color(native/dobtor/tuning/custom/as_is)、master_data_models、third_party_costs、resource_profile(JSON)、
  ai_points_monthly、`availability_for(package)` → ('available'|'addon'|'missing', 缺的模組 set)。
- `corpaas.knowledge.scenario`（content mixin）：name、code、xml_module（`__doc_scenario_<code>`）、parent_id、is_base、
  package_ids、glossary、narrative、role_ids、seed_json、`full_seed()`、`all_roles()`、`glossary_map()`、`seed_models()`、
  `text_review_waived()`。
- `corpaas.knowledge.role`：code、name、group_xmlids。
- `corpaas.knowledge.asset`：name、shot_name、feature_id、scenario_id、scope_hash、owner_model、owner_id、attachment_id、
  regions_json（CSS 像素）、phash、width、height、state(current/superseded)、superseded_at、url。
- `corpaas.knowledge.sandbox`：package_id、scenario_id、master_instance_id、db_name、state、ready_at、password、
  role_logins(JSON {role_code: login})、`resolve_xmlids(xmlids)` → {xmlid: [model, id]}、`gate_bad_records(pairs)`（D1）。
- `corpaas.knowledge.event`：type(feature_added/feature_removed/scope_changed/form_changed/scenario_changed/rename_candidate/
  divergence/code_changed)、package_id、feature_id、scenario_id、role_code、payload、refresh_token、processed。
- `corpaas.knowledge.selection`：AI 圈選提案。
- `corpaas.knowledge.ai`：`ask(...)`。
- `corpaas.knowledge.help`：`_package_for_database(db_name)`、`_match(package, query, action_xmlid, model, view_type, limit)`
  → [(feature, score)]。
- `infrastructure.solution.package` 擴充：knowledge_enabled、knowledge_scenario_ids、knowledge_capability_ids、
  `_knowledge_master()`、`_knowledge_roles()`、`_provision_module_names()`（既有）、`product_tmpl_id`（既有）。

服務（`odoo.addons.dobtor_corpaas_knowledge.services`）：
- `shooter.run_shots(env, sandbox, shots, settings)` → (result_json, files{relpath: bytes})。
  shots: `[{'id','login','password','steps':[...]}]`；settings 取 `env['res.config.settings'].knowledge_shot_settings()`。
  步驟詞彙（`shot_runner/run.py`）：
  `{"goto":{"action":xmlid,"res_id":id?}}`、`{"goto":{"url":"/odoo/..."}}`、`{"open":{"model","res_id"}}`、
  `{"click":{"button"|"field"|"page"|"selector"|"text"}}`、`{"fill":{"field","value"}}`、
  `{"wait":{"ms"|"selector"}}`、`{"highlight":{"field"|"button"|"page"|"selector","n":1}}`、`{"shot":"name"}`。
  result：`{'shots': {id: {'ok', 'images':[{'name','file','regions':[{n,x,y,w,h}],'records':{model:[ids]}}], 'error','dom_text','error_image'}}}`。
- `phash.dhash(png_bytes)`、`phash.distance(a,b)`。
- `hub_client.BudgetExceeded`、`hub_client.HubError`。
- `fingerprint_lib`（純函式）。

hooks（`corpaas.knowledge.hooks`，出口覆寫）：
- `_knowledge_elements_for(feature, package)` → 截圖腳本範圍元素 list（[{'field':..}|{'button':..}|{'page':..}]）。
- `_knowledge_scenarios_needing_shots(package, events)` → scenario recordset。
- `_knowledge_shoot(package, sandbox, events, ctx)`；ctx 有 `token`（refresh token，給 ai.ask 的 refresh_token）、`full`。
- `_knowledge_dispatch_events(package, events, ctx)`。
- `_knowledge_help_links(package, matches, query, ctx)` → list of dict
  `{feature_key, title, url, kind('manual'|'upsell'), scenario, anchor, fingerprint:{elements, scope_hash}}`。
- `_knowledge_rename_feature(old, new)`、`_knowledge_feature_gone(feature)`、`_knowledge_check_feature_ref(feature)`。

設定參數：`corpaas_knowledge.public_base_url`（連結前綴）、`corpaas_knowledge.phash_threshold`。

## 模組 A：dobtor_corpaas_knowledge_manual（出口一：操作說明 → slide）

depends: `dobtor_corpaas_knowledge`, `website_slides`。

模型：
- `corpaas.knowledge.step_block`（content mixin）：feature_id、fingerprint（scope_hash）、html、anchor（穩定鍵 slug，建立後不變）、
  derived_from_id、sequence。鍵＝功能 × 腳本範圍指紋；跨情境、跨方案共用。
- `corpaas.knowledge.shot_template`：feature_id、fingerprint、steps_json（佔位符 `"{name}"`）、placeholders（JSON list）、
  login_role、elements（由 steps 推導：highlight/click/fill 裡的 field/button/page）。
- `corpaas.knowledge.shot_binding`：template_id、scenario_id、bindings_json（佔位符→xmlid）、roles_json、
  last_result、asset_ids。
- `corpaas.knowledge.article`（content mixin）：feature_id、scenario_id、fingerprint、step_block_ids、scenario_html、
  shot_binding_id、asset_ids、capability_id（決定章節）、title、`render_html()` 組裝（步驟區塊＋情境區塊＋素材，
  紅框編號標註：用 CSS 絕對定位的 div 疊在圖上會被 sanitize 吃掉，所以**在伺服端用 PIL 把紅框 #E02424 與編號徽章畫進圖**，
  另存一份「manual 標註版」attachment；原圖不動）。每個步驟標題帶 `id="<anchor>"`。
- `corpaas.knowledge.placement`：article_id、channel_id、package_id、capability_id、slide_id、sequence、last_synced_rev、
  is_canonical。
- `corpaas.knowledge.channel_section`：channel_id、capability_id（空＝共通操作）、slide_id（is_category）。
- `slide.channel` 擴充：knowledge_product_tmpl_id（一個方案一個 channel）、knowledge_managed。

同步（D4 `_knowledge_publish` → placement 同步）：
- channel：每個 `product.template` 一個文件型（channel_type='documentation'）、visibility='public'、enroll='public'、
  promote_strategy='none'、is_published。
- 每次同步**整個 channel 重新編號**：章節依能力 sequence，章節 sequence 以 100 為間距（100, 200…），
  文章 101, 102…；共通操作最後。章節是 `is_category=True` 的 slide（category_id 由 sequence 計算，不能直接寫）。
- slide：`slide_category='article'`、`is_preview=True`（★ 非成員只能開 is_preview）、`html_content`、
  `tag_ids`＝情境標籤（`slide.tag`，名稱「情境：<名稱>」）。寫後讀回比對。
- 刪章節前先處理底下文章（原生 unlink 會把文章搬到上一章節）。
- 文字實質改寫時重設 `date_published`（「新」標記）；純重拍不重設。
- 功能消失：取消發佈（is_published=False），不刪除。
- 同一篇文章多個 placement：`is_canonical` 預設最先建立者；覆寫 slide 頁（website_slides 的 slide 詳細頁模板）在
  `<head>` 輸出 `<link rel="canonical">` 指向主要 placement 的 slide 網址。
- 覆寫 website_slides `channel()` 路由（controllers/main.py 的 WebsiteSlides.channel）：knowledge_managed 的課程，
  沒指定 sorting 時預設 `sequence`（★ 文件型在 promote_strategy 為 specific/none 時預設 latest）。
  覆寫方式要繼承真正擁有該 route 的 class（odoo.addons.website_slides.controllers.main.WebsiteSlides）並保留 route 裝飾器。

hooks 覆寫：
- `_knowledge_elements_for`：該功能目前的 shot_template 的 elements。
- `_knowledge_scenarios_needing_shots`：events 裡 scope_changed/feature_added 的功能，其 binding 的情境；
  scenario_changed 的情境；以及還沒有素材的 binding 的情境。
- `_knowledge_shoot`：對 sandbox 的情境，找需要拍的 binding（scope 變了、沒素材、上次失敗）：
  1. 沒有 template 的功能（且被圈選核准、屬於方案能力）→ AI 探索：給功能的 view arch（用 sandbox 的 odoo shell
     `get_views`，可呼叫 `remote.shell_json`）、menu_path、示範資料 xmlid 清單、角色，請 AI 產生 template steps＋binding。
  2. 解析 binding：`sandbox.resolve_xmlids()` 把佔位符換成 `{"model","res_id"}`/`res_id`；登入用
     `json.loads(sandbox.role_logins)[login_role]` 與 `sandbox.password`（sudo 讀）。
  3. `shooter.run_shots()` 一次跑一批（同一 sandbox 的所有待拍 binding）。
  4. 每張圖：D1 `sandbox.gate_bad_records(image['records'])` 有不合格就不採用、記錯誤；否則 dHash 與舊素材比，
     距離 ≥ 門檻才換圖（舊素材 state=superseded、superseded_at）；建立 asset（owner_model='corpaas.knowledge.shot_binding'）。
  5. 失敗的 binding → AI 修 template（給錯誤、dom_text、steps）→ 下次 refresh 再試（不在同一次重試，避免燒預算）。
  6. BudgetExceeded 直接停止剩下的 AI 工作。
- `_knowledge_dispatch_events`：
  - scope_changed → 相關 article：如果只有截圖換了且文字不需改 → `knowledge_reshoot_done()`；
    步驟區塊需要依新指紋分岔 → 以既有步驟區塊為底請 AI 只改差異（新 step_block 記 derived_from_id），
    article 走 `knowledge_propose('text')`。
  - 指紋收斂（兩個 step_block 同 feature 同 scope_hash）→ 建立「合併步驟區塊」提案（可用 corpaas.knowledge.selection
    或自有模型），人工確認後併回一份、引用改指。
  - feature_added（已被圈選核准到能力）→ 產生新文章草稿（AI 寫步驟區塊（若該功能×指紋還沒有）與情境區塊）→ `knowledge_propose('new')`。
  - feature_removed（且沒有改名候選）→ article.action_retire()。
- `_knowledge_help_links`：命中的功能 → 該方案情境下已發佈 article 的 slide 網址（public_base_url + slide.website_url
  + `#anchor`）、情境名、fingerprint 元素與 scope_hash（給租戶端 D5 比對）。
- `_knowledge_rename_feature`：article/step_block/template 的 feature_id 改指新功能。

AI prompt 要求（全部寫在模組裡，繁中）：步驟區塊只寫操作步驟（HTML，只能用上面允許的 class）；情境區塊寫
「在這個情境下為什麼這樣做」並套用 glossary；**不得另寫完整步驟**（帶入既有步驟區塊）。

視圖：article（含待核差異頁、截圖預覽）、step_block、template/binding、placement、channel section；
選單「操作說明」在出口下。

## 模組 B：dobtor_corpaas_knowledge_marketing（出口二：產品行銷 → 商品頁）

depends: `dobtor_corpaas_knowledge`, `dobtor_corpaas_website`, `website_sale`。

模型：
- `corpaas.knowledge.pitch`（content mixin）：capability_id、scenario_id（可空）、headline、body_html（痛點→成果、情境故事）、
  asset_ids（乾淨版截圖；由 manual 素材挑選，沒有 manual 模組時可空）、product_tmpl_id、sequence。
  `_knowledge_requires_review` → **一律 True**（宣稱一律核准）。
- `corpaas.knowledge.claim`：pitch_id、text、capability_id、feature_ids（宣稱錨定）、state(ok/check)、reason。
- `corpaas.knowledge.release_note`（content mixin）：product_tmpl_id、package_id、refresh_token、title、body_html、
  feature_ids、published_date。
- `product.template` 擴充：knowledge_pitch_ids、knowledge_release_note_ids、`_knowledge_upsell_capabilities()`。

行為：
- 宣稱錨定：hooks `_knowledge_dispatch_events` 收到 feature_removed / scope_changed（大改）→ 引用該功能的 claim
  state='check'、pitch `knowledge_mark_stale()` 並暫時撤下圖（前台不顯示該 pitch 的圖）。
- 本期新增：同一次 refresh 的 feature_added（已歸入能力的）→ AI 寫 release_note 草稿 → `knowledge_propose('claim')`。
- AI 產生 pitch：按鈕「AI 起草行銷文案」（capability＋scenario＋glossary → headline/body/claims）。
- 商品頁：繼承 `website_sale.product` 模板（先查 dobtor_corpaas_website 是否已覆寫商品頁，找對應的 xpath 錨點；
  Odoo 18 原始碼在 `/Users/mengdawu/Desktop/Claude/odoo-18.0/addons/website_sale/views/templates.xml`），
  在商品描述下方加一個容器：能力卡片（published pitch）、本期新增（最近 published release note）、加購可得
  （capability.availability_for(package)=='addon' 的能力，連到對應 is_sellable 模組產品 `infrastructure.repository.module.product_id`）。
  方案 package 取 `product_tmpl.infra_modules_integ_ids` 裡 `published_version_id` 有值的那個。
  圖片以乾淨版（原圖）顯示，`img-fluid rounded border`，不加紅框。
- hooks `_knowledge_help_links`：super 後，若查詢命中的功能在該方案不可用但為 addon，加一筆 kind='upsell' 連到商品頁。

## 模組 C：dobtor_corpaas_knowledge_proposal（出口三：建議書／報價／成本）

depends: `dobtor_corpaas_knowledge`, `dobtor_corpaas_sale`, `sale_management`；`hr_timesheet` 選用（用 `'account.analytic.line' in env` 判斷）。
先讀 `/Users/mengdawu/Documents/GitHub/PAAS/dobtor_corpaas_product/models/package_pricing.py`（`corpaas.package.tier.line`
`_unit_price_for(ccu)`、`_ccu_cost_for(ccu)`、`base_fee`）與 `product.py` 的 `compute_package_price`（若存在）決定訂閱費算法，
**不自己發明價格邏輯**。`dobtor_infrastructure_cost` 若有可用的主機成本資料就引用，否則成本以設定頁的「每 GB／每 worker 月成本」估算並標示估算值。

模型（設計文件第 10 節）：
- `corpaas.knowledge.proposal`：partner_id、product_tmpl_id、package_id、tier(shared/independent/custom)、ccu、
  state(draft/sent/won/lost)、snapshot_json（sent 時凍結：能力、敘事、工項、價格）、sale_order_id、
  subscription_amount、implementation_amount、custom_amount、total、internal_cost、margin、margin_rate、html（建議書內容）。
  sent 後唯讀（write 擋下，snapshot 以外欄位不可改）。
- `corpaas.knowledge.pain`：proposal_id、department、description、source(manual/import)。
- `corpaas.knowledge.mapping`：pain_id、capability_id、color、addon_product_id、note、confirmed。
- `corpaas.knowledge.effort_template`：capability_id、activity(requirements/migration/training/golive/pm)、base_days、
  driver(companies/users/roles/records_100/integrations/sessions/none)、per_unit_days、unit_size。
- `corpaas.knowledge.estimate_line`：proposal_id、mapping_id、activity、driver_qty、days、day_rate、internal_day_cost、
  amount、internal_cost、is_custom、note。
  days = base_days + ceil(driver_qty / unit_size) × per_unit_days。
- 設定：日費率、內部人天成本、第三方預設。

流程：
1. 痛點輸入：手動，或匯入售前 xlsx（openpyxl；每張部門表欄位：`# | 客戶提問／痛點 | 現況說明 | 解決方案 | 現有 or 客製 | 對應原生功能／模組 | 報價重點`，
   第 2 列表頭、第 3 列起資料；匯入 精靈）。
2. 「AI 比對能力」按鈕：痛點＋方案能力（含 pain/outcome）→ mapping 提議（color、客製參考人天區間寫進 note）。
3. 「計算估算」：依 mapping 與 effort_template 產生 estimate_line；driver_qty 由提案上的欄位（公司數、使用者數、
   角色數、主資料筆數 by model、串接數、訓練場次）決定；主資料清單取自情境的 `seed_models()`（資料移轉檢核表）。
4. 建議書 HTML：組合行銷層已發佈的 pitch（若 marketing 模組已安裝，用 `'corpaas.knowledge.pitch' in env`）與能力 pain/outcome、
   痛點對應表、報價表、需要客戶提供的資料清單；可列印（QWeb report PDF）。
5. 「建立報價單」：sale.order＋明細（訂閱方案產品、加購模組產品、導入服務工項用一個服務產品＋數量＝人天）。
6. 「送出」：state=sent，寫 snapshot_json，之後唯讀。
7. 工時回寫：`action_feedback_actuals()` 讀 sale.order 關聯專案的 timesheet（task 名稱或 tag 帶能力 code），
   依能力×activity 算實際人天，更新 effort_template.base_days（移動平均，記錄校正歷史）。
8. 成本：internal_cost = Σ days × internal_day_cost ＋ 基礎設施月成本（capability.resource_profile 相對權重 × 設定的單價）×12 ＋
   第三方＋AI 點數；margin。資源特徵未校準 → 建議書成本頁標「估算值」。

## 模組 D：dobtor_ai_hub_content（AI Hub 端，content 模式）

depends: `dobtor_ai_hub`（原始碼 `/Users/mengdawu/Documents/GitHub/AI/dobtor_ai_hub`，**不要修改它**）。
- `selection_add` 把 `('content', '知識內容')` 加到 `ai.hub.session.mode`、`ai.hub.run.mode`、`ai.hub.artifact.type`、
  `ai.hub.route.rule.mode`（ondelete 設定）。
- `MODE_REQUIREMENTS['content'] = ('has_agent_loop',)`（在模組載入時更新 dict；檔案 models/ai_hub_route.py）。
- `ai.hub.source` 加 `content_enabled` Boolean（預設 False）＋ `content_max_chars`。
- 新端點 `POST /ai_hub/api/v1/content_run`（type='json', auth='none', csrf=False）：用既有 `AiHubUplink._auth()`
  驗 `X-AI-Hub-Key`；要求 `source.content_enabled`；`uplink_blocked_reason()` 的配額/成本上限照用；
  prompt 上限預設 200000 字元；建 session（mode='content'，每次新 session，name=purpose）→ `session.start_run(prompt, mode='content')`
  → run.write origin='uplink'；回 `{ok, run_id, conversation}`。查結果沿用既有 `/ai_hub/api/v1/run_status`（同一來源才看得到）。
- ★ Runner 對未知 mode 的 SYSTEM_PROMPTS 回空字串（`runner/provider_claude.py:119`），所以角色指示全部在 prompt 裡；
  content 模式不需要任何工具（預設 allowed tools 即可），不注入 bridge（若 source 有 bridge 設定也無害）。
- 測試：端點權限（無金鑰、未啟用、超長）、selection 可用。

## 模組 E：dobtor_ai_bridge_help（租戶端）

depends: `dobtor_ai_bridge_backend`（原始碼 `/Users/mengdawu/Documents/GitHub/AI/dobtor_ai_bridge_backend`、
`dobtor_ai_bridge`，**不要修改它們**；讀 `static/src/panel/panel.js`、`systray/backend_context.js`、
`controllers/assistant.py`）。
- 設定：主控台網址（`dobtor_ai_help.console_url`，預設 https://admin.corpaas.com）、本庫名稱（預設 `env.cr.dbname`）。
- 後端路由 `/dobtor_ai/help/links`（type=json, auth=user）：參數 query?、action（xmlid 或 id）、model、view_type
  → 伺服器端 POST 主控台 `/corpaas/knowledge/v1/help`（requests，timeout 8s，不吃 proxy 設定外的環境變數），
  回 results。action 是數字 id 時先轉 xmlid。
- D5：對每個結果，若有 `fingerprint.elements` 與 `scope_hash`，在租戶端以目前使用者計算腳本範圍指紋
  （把 `dobtor_corpaas_knowledge/services/fingerprint_lib.py` 複製一份到本模組 `lib/fingerprint_lib.py`，
  註明兩份必須一致；用 `env[model].get_views(...)` 取 arch）→ 不一致在結果加 `diverged: true`，
  並非同步 POST 主控台 `/corpaas/knowledge/v1/divergence`。
- 前端：在助理面板加「此畫面說明」按鈕（patch 面板元件或 systray；用 `assistantContextRegistry` 的 backend context 取
  model/action/view_type）→ 呼叫 `/dobtor_ai/help/links` → 以按鈕列表顯示結果（標題、情境名、`diverged` 時加註
  「你的畫面可能與說明不同」），開新分頁。自然語言提問送出時，同時用使用者的問句呼叫一次 links，
  把結果顯示在回答下方（不經 LLM、不讓模型寫連結）。`linkHref()` 目前只收相對路徑：本模組自己渲染連結，
  只允許 `console_url` 同網域或設定的公開說明網域（https）。
- 資產 bundle：`web.assets_backend`。OWL 注意事項：模板裡 `Boolean` 等全域是 undefined；patch 用 `@web/core/utils/patch`。
- 測試：路由在主控台無回應時回空結果不炸；xmlid 轉換；指紋比對 diverged 旗標。

## 修正第一輪（設計審查後，2026-09-29）

核心（dobtor_corpaas_knowledge）同時由主控者修改；出口模組**不要改核心**，照下列名稱寫。

1. **AI 非同步作業**：`env['corpaas.knowledge.ai'].enqueue(record, method_name, package, note='')`
   → 建 `corpaas.knowledge.ai.job` 並排入 corpaas.queue（package 上的 operate `knowledge_ai_job`，
   channel `knowledge` 併發 1），回傳 `display_notification` action。佇列作業以原使用者身分執行
   `getattr(record, method_name)()`；該方法自己呼叫 `ask(...)` 與寫回結果；例外記在 job 上並
   message_post 到 record（若 record 有 mail.thread）。
   ★ 所有會呼叫 AI 的**按鈕**都改成：按鈕 `action_xxx` → `enqueue(self, '_xxx_run', package)`；
   實際工作放在 `_xxx_run`（不可在 HTTP 請求內同步呼叫 ask）。
2. **指紋重新基準**（D2/B6）：核心比對指紋時，若前後 `elements_json`（腳本範圍元素集合）不同，
   視為「定義改了」而不是「畫面改了」：不發事件，改呼叫掛勾
   `corpaas.knowledge.hooks._knowledge_fingerprint_rebaselined(feature, package, role_code, old_scope_hash, new_scope_hash)`
   → 出口把該 package 下引用 old 的 template／step_block／article／asset 的指紋改成 new。
3. **功能點依方案存在**（per-package presence）：`feature.package_ids` = 目前存在於哪些方案；
   新增 `feature.missing_package_ids`；`feature.missing`（stored compute）= 所有方案都沒有了。
   `feature_added`／`feature_removed` 事件都是**每個方案各自**發。新方法
   `feature.is_present_in(package)`。出口的下架（retire）必須**只下架該方案的 placement**，
   不能因為別的方案沒有就全域下架。
4. **情境核准版示範資料**：`scenario.live_seed()`（已核准版本的 full_seed，含祖先；沒有核准版就拋
   UserError）。說明庫重建只用這個。
   `scenario.note_article_review(clean)`：文章（該情境）核准時呼叫，`clean=True`＝核准者沒改文字
   → 計數 +1；退回或改過 → 歸零。`text_review_waived()` 依此計數。
5. **說明庫**：名稱改為 `docsbx-p<方案id>-s<情境id>`；新增 `purged_at`；D1 檢查放行
   「清除之後建立」的記錄。`sandbox.gate_bad_records(records, refs=None)`：
   records = `{model: [ids]}`；refs = `{"model|field": [ids]}`（many2one／x2many 值，核心自己查
   comodel）。run.py 的 image 會多一個 `refs` 欄位，且 recorder 登入後不再於每張圖之間重置（累積＝較嚴）。
6. **改名偵測**：只對 kind in (menu, action, button) 且雙方簽章都非空時提候選。
7. 事件去重：同方案待執行的 knowledge_refresh 合併為一張（全量需求記在 package 上）。
8. help API：未知資料庫回 `{ok: True, results: []}`（不再洩漏是否存在）；限流改以 database+IP。

## 修正第二輪：補齊已知缺口（2026-09-30）

1. **租戶請求簽章**（help／divergence）：
   - 租戶送出時加標頭：`X-KB-Database: <庫名>`、`X-KB-Timestamp: <unix 秒>`、
     `X-KB-Signature: hex(hmac_sha256(key, "<timestamp>.<原始 request body bytes>"))`。
   - 主控台以 `infrastructure.database.knowledge_help_key`（該庫名）驗證，時間差 ≤ 300 秒；
     標頭的庫名必須等於參數 `database`。
   - `corpaas_knowledge.help_require_signature`（預設 'True'）：未簽或驗證失敗 → `{ok: False, error: 'unsigned'|'bad_signature'}`。
   - 金鑰下發：主控台 `infrastructure.database.action_knowledge_push_help_key()` 產生金鑰、存在該庫記錄，
     以平台既有的 `_shell_set_param` 寫進租戶 ICP：`dobtor_ai_help.console_key`（以及
     `dobtor_ai_help.console_url` = 主控台 web.base.url）。每日排程替「知識已啟用的方案」底下還沒有金鑰的庫下發。
2. **角色過濾**：help 參數多一個 `groups: [xmlid, …]`（租戶端送目前使用者的群組 xmlid）。
   主控台：功能點 `group_xmlids` 有值且與使用者群組無交集 → 不回；說明文章依情境角色群組與使用者群組的交集排序。
3. **截圖探測步驟**（AI 探索用）：截圖腳本新增 `{"probe": "<name>"}`：截圖＋回傳畫面上實際可見的
   互動元素 `{'buttons': [{name, text}], 'fields': [{name, label, widget}], 'tabs': [{name, text}], 'breadcrumbs': [...]}`，
   放在 image 的 `probe` 欄位（這張圖不當素材）。AI 探索（manual）先對目標畫面跑一次 probe，把結果連同 view arch 給 AI。
