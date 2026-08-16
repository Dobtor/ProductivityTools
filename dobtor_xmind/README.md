# dobtor_xmind — XMind 2 Clone for Odoo 18

視覺化心智圖編輯器（自訂 render engine，`window.OdooXMind`），可與 `project.project` /
`project.task` 雙向同步，並能以 `/` power-box 內嵌到任何 HTML 欄位。

---

## 1. 資料模型

```
xmind.workbook                 工作簿（一份心智圖）
 ├─ sheet_ids  → xmind.sheet   分頁（一個工作簿多張分頁）
 │   ├─ topic_ids        → xmind.topic          主題樹（_parent_store）
 │   │   └─ marker_ids   → xmind.topic.marker   ← xmind.marker
 │   ├─ relationship_ids → xmind.relationship   關聯線
 │   ├─ boundary_ids     → xmind.boundary       邊界
 │   ├─ summary_ids      → xmind.summary        摘要
 │   ├─ callout_ids      → xmind.callout        標註
 │   └─ floating_topic_ids → xmind.floating.topic
 └─ revision_ids → xmind.revision               版本（每張分頁各留 50 份）
```

`xmind.topic.name` 是 `related='title', store=True`；**寫入時請用 `title`**（`title`
才是 `required=True` 的來源欄位）。

專案整合：`project.task.xmind_topic_id` ↔ `xmind.topic.task_id`，雙向。

---

## 2. 前後端契約：**存檔一定要帶 `sheet_id`**

這是本模組最容易出事的地方，出過三次資料遺失等級的 bug，全部同一個成因 ——
後端把 payload 寫進 `sheet_ids[0]` 而不是使用者當下那張分頁：

| # | 症狀 | 成因 |
|---|------|------|
| 1 | 從分頁 2 切回分頁 1，分頁 1 的內容整個消失 | `save_mindmap_data()` 寫死 `sheet_ids[0]` |
| 2 | 還原舊版本，還原到錯的分頁 | `xmind.revision.action_restore()` 同樣寫死第一張 |
| 3 | 畫布是新分頁的樹，關聯線卻是上一張的 | 切分頁時只換了主題樹，特徵層（關聯／邊界／摘要／標註／浮動主題）沒跟著換 |

現行契約：

- `save_mindmap_data(data, is_auto=False, sheet_id=None)` —— **工作簿有一張以上分頁時
  必須傳 `sheet_id`**；傳了不屬於本工作簿的 id 會 `UserError`。
- 前端 `_saveData()` 一律送 `sheet_id: this._currentSheetId || false`。
- `xmind.revision.sheet_id` 記錄該版本屬於哪張分頁，還原時原路送回；版本修剪也是
  **每張分頁各留 50 份**，不是整本 50 份。
- 切分頁時 `_applyFeaturePayload(result)` 一定要呼叫，而且**沒有資料時要指派空陣列**
  ——「不指派」等於留著上一張的特徵層，下一次存檔就把它們寫進新分頁。
- 換分頁的載入一律走 `_loadSheetIntoCanvas(sheetId)`，它**不存檔**；要不要先存由呼叫端
  決定 —— 切換必須先存（否則當前分頁的編輯被覆蓋），刪除當前分頁則絕對不能存
  （那份畫布屬於已不存在的分頁）。刪除到換上新畫布之間用 `_loadFailed = true`
  擋住自動存檔。

回歸測試：`tests/test_multi_sheet_save.py`（後端）＋
`tests/test_sheet_tour.py` ＋ `static/tests/tours/mindmap_sheet_tour.js`（端到端）。

### 2.1 影子狀態必須對帳

同一個成因的另一種形態：編輯器在畫布之外維護幾份影子陣列（`floatingTopics`、
`boundaries`、`summaries`、`callouts`），但節點本身會被 `onDelete()`、
`onCutTopic()`、`AddNodeCommand.undo()` 這些完全不知道那些陣列存在的路徑移除。

`floatingTopics` 因此有過「刪掉的浮動主題以空白標題復活」的 bug（存檔時
`get_node()` 取到 null，仍照殘留項寫回一筆）。現在由 `_pruneFloatingTopics()`
在**使用該狀態之前**統一對帳（`_saveData()` 與 `_renderAllFloatingTopics()` 各呼叫
一次），而不是在每條移除路徑補 splice —— 下一條新的移除路徑照樣會漏。

**新增任何「畫布之外的節點清單」時請比照辦理。**

### 2.2 存檔是差異更新，不是全刪重建

存檔**不是**全刪重建（曾經是）。`_sync_jsmind_tree()` 以 `component_id` 對帳：
對得上就 `write`、對不上才 `create`、payload 沒提到的才刪。

`component_id` 在前後端之間是完整往返的（`_topic_to_jsmind` 送
`'id': topic.component_id`，`_upsert_jsmind_node` 再存回去），這是整套機制的
前提 —— **改動任何一端的 id 傳遞都會讓對帳失效，症狀是主題被整批重建而不是報錯**。

改掉的是什麼：舊作法每次存檔都 `unlink()` 整棵樹再重建，於是**每顆主題的資料庫
id 每次存檔都會換一批**。指向 `xmind.topic` 的外部參考全部會斷，當時只有
`project.task.xmind_topic_id` 一條，靠 payload 的 `taskId` 事後補接才沒出事；
再加第二個關聯欄位就會靜默失聯。現在 id 是穩定的，那段補接退化成防呆。
存檔成本也從 O(節點數) 降為 O(異動數)＋一次比對。

寫這一段程式時要記得的兩件事：

- **`create` 改成 `write` 之後，「有值才設」的欄位會出事。** 舊作法下新記錄天然
  帶預設值，所以 `if payload.get(x): topic.x = ...` 剛好等價於「照 payload 重建」；
  主題會存活之後，同樣的寫法會讓使用者**永遠取消不掉**該設定。`project_managed`
  與 `task_id` 都因此改成明確指派。
- **「整組取代」語意的子物件（標記、附件）更新時必須先清空**，否則每存一次檔就
  疊加一輪。

特徵層（關聯線／外框／括弧總結／標註／浮動主題）仍是整組取代 —— 筆數少、彼此
有引用關係，逐筆對帳不划算。它們靠 `component_id` 找主題，所以受惠於 id 穩定。

回歸測試：`tests/test_diff_save.py`（14 個案例，含父子顛倒、重複 id、搬家、
子物件不疊加、關聯雙向清除）。

---

## 3. 已知限制

### 3.1 `.xmind` 匯出的涵蓋範圍

`action_export_xmind()` 產生的 zip 含 `content.json` / `metadata.json` /
`manifest.json`，可被本模組自己的 `import_xmind_file()` 完整讀回（往返測試見
`tests/test_xmind_export.py`）。樣式以 XMind Zen 的 inline style 表達，不另外輸出
`styles.xml`；用 XMind 桌面版開啟時，主題結構與文字完整，細部樣式可能被套用該版本的
預設主題。

匯出寫進獨立的 `ir.attachment`，**不會**動到 `xmind_file`（那是匯入來源欄位）。
`export_svg()` 是舊行為，會覆蓋 `xmind_file`；匯入後再匯出 SVG 就無法重新匯入該檔。

### 3.2 翻譯

原文一律用**英文**，中文由 `i18n/zh_TW.po` 提供 —— 這是 Odoo 慣例，也是唯一能同時
服務中文與非中文客戶的做法。

歷史上這裡曾經分裂：JS 用英文原文、XML 模板卻硬寫了 278 處中文（屬性 51 處、
文字節點 222 處、外加 2 個 `AutoComplete` 的 `placeholder` prop）。後果是**同一條
工具列上中英夾雜**，而且模板那些中文再怎麼補 .po 都不會變 —— OWL 元件 prop 的
運算式根本不在 Odoo 的翻譯抽取範圍內。現已全部改為英文原文並把原有中文回填成
`msgstr`，所以畫面維持全中文。

新增字串時：

- JS 一律 `_t("English source")`；
- OWL 模板的文字節點與 `title` / `placeholder` / `alt` / `label` 屬性直接寫英文，
  Odoo 會抽取；
- **元件 prop（`<AutoComplete placeholder="'…'"/>` 這種運算式）不會被抽取** ——
  要翻譯就在元件上開一個 getter 回傳 `_t(...)`，再把 getter 綁到 prop。

補翻譯的正確流程（**不要手寫 .po**，缺 `#. odoo-javascript` 標記等於沒作用）：

```bash
# 1) 升級模組，讓新字串進入抽取來源
odoo -d <db> -u dobtor_xmind --stop-after-init
# 2) 匯出母檔
odoo -d <db> --i18n-export=/tmp/dobtor_xmind.pot --modules=dobtor_xmind --stop-after-init
# 3) 用母檔對照 i18n/zh_TW.po 補 msgstr，再放回 i18n/
```

## 4. HTTP 路由

編輯器全部走 `/xmind/...`（`type='json'`, `auth='user'`）：

| 路由 | 用途 |
|------|------|
| `/xmind/workbook/<id>/data` | 載入工作簿（第一張分頁 + 特徵層） |
| `/xmind/workbook/<id>/save` | **單一交易**寫入主題樹與全部特徵層 |
| `/xmind/workbook/<id>/sheets` | 分頁清單 |
| `/xmind/workbook/<id>/sheet/create` \| `<sid>/rename` \| `<sid>/delete` | 分頁維護 |
| `/xmind/workbook/<id>/sheet/<sid>/data` | 切分頁：主題樹 + 該分頁的特徵層 |
| `/xmind/workbook/<id>/settings` | 分頁設定（版面／主題） |
| `/xmind/workbook/<id>/thumbnail` | 前端算好的縮圖回寫 |
| `/xmind/workbook/<id>/revisions[/<rid>/preview\|restore]` | 版本 |
| `/xmind/workbook/<id>/project_sync` | 心智圖 → 專案任務 |
| `/xmind/markers` | 標記主檔 |

各特徵層原本各有一支 `/save` 路由，已移除：它們會各自開一個交易，中途失敗就留下
半套資料，而且同樣寫死 `sheet_ids[0]`。現在一律由 `/save` 一次寫完。
`_replace_relationships` / `_replace_boundaries` / `_replace_summaries` /
`_replace_callouts` / `_replace_floating_topics` 這些模型方法**仍在使用**，只是不再
直接對外開放。

---

## 5. 前端結構

`static/src/js/mindmap_editor.js`（約 6,300 行）是命令式的 god-component：把自訂
render engine 掛在原生 DOM ref 上，畫布不走 OWL 反應式重繪。

模組**不使用任何瀏覽器原生對話框**（`prompt` / `confirm` / `alert`）。原生對話框
會凍結 JS 執行緒、tour 與 hoot 一律過不去，而且 Safari 允許使用者永久關閉它們。
確認一律用 `ConfirmationDialog`，輸入用本模組的 `MindmapPromptDialog`。

字型 Open Sans 自帶於 `static/lib/fonts/`（OFL-1.1），不走 CDN —— 它同時是縮圖
繪製與 SVG 匯出的度量基準，CDN 在離線／CSP 環境靜默失敗會讓匯出的字寬對不上。

反應式的部分刻意抽成子元件，變動時只重繪自己、不碰畫布：

| 檔案 | 職責 |
|------|------|
| `mindmap_project_bar.js` | 右上角客戶／專案選單 |
| `mindmap_pager.js` | 分頁器 |
| `mindmap_search.js` | 工具列中央的主題搜尋／篩選（6 個條件，對照 `project.task` 搜尋視圖） |
| `mindmap_templates_data.js` | 內建範本（純資料，無元件狀態） |
| `mindmap_prompt_dialog.js` | 取代 `window.prompt()` 的多欄位輸入對話框 |
| `mindmap_sheet_tabs.js` | 畫布底部的分頁列（OWL 子元件，有 tour 覆蓋） |
| `mindmap_context_menu.js` | 右鍵選單（節點／標記／空白處／關連線） |
| `command_stack.js` | undo/redo |
| `xmind_features.js` | 特徵層 renderer |

工具列樣式對齊 `dobtor_project` 的甘特圖工具列（`.o_gantt_toolbar`）：按鈕靠左並以
直分隔線分組、搜尋框置中、客戶／專案與檢視切換靠右。

### 5.1 兩種抽出方式，用途不同

- **抽成 OWL 子元件**（`mindmap_sheet_tabs.js`）：狀態放進 `useState`，變動時只
  重繪自己。分頁列挑這條路是因為它有 tour 護欄 —— 改壞了跑得出來。
- **抽成 manager 類別**（`mindmap_context_menu.js`，比照 `DragDropManager` /
  `RelationshipManager`）：建構子收 `editor`，相依從隱式的 `this` 變成參數。
  右鍵選單走這條，是因為它是命令式地建 DOM 掛到 `document` 上（一次只有一個），
  改成元件要連 overlay 服務一起重做，而那 547 行目前沒有任何自動化測試護欄。

**待辦**：`mindmap_editor.js` 仍有 6,300 行。剩下的大區段是「render-engine
Events」（666）與「Internal Methods」（657）—— 它們直接操作 jsMind 實例與畫布
DOM，是這個 god-component 的本體，不是可以搬走的 UI 塊。要再小下去得先讓畫布
本身有測試護欄。

---

## 6. 測試

```bash
odoo -d <db> -u dobtor_xmind --test-enable --test-tags /dobtor_xmind
```

| 檔案 | 涵蓋 |
|------|------|
| `tests/test_project_sync.py` | 任務 ↔ 主題層級同步 |
| `tests/test_multi_sheet_save.py` | 多分頁存檔／還原寫到正確的分頁 |
| `tests/test_diff_save.py` | 差異更新：id 穩定、父子顛倒、搬家、重複 id、子物件不疊加、關聯雙向清除 |
| `tests/test_xmind_export.py` | `.xmind` 匯出 → 自家匯入端的往返 |
| `tests/test_sheet_tour.py` + tour | 分頁切換／新增／刪除的端到端（含跑完後回頭斷言資料庫） |

hoot 單元測試（`static/tests/*.test.js`，`web.assets_unit_tests`）：

| 檔案 | 涵蓋 |
|------|------|
| `mindmap_editor_state.test.js` | `_pruneFloatingTopics` 的影子狀態對帳、搜尋篩選述詞、關連線端點可見性 |
| `mindmap_templates_data.test.js` | 內建範本的結構契約與 id 唯一性 |
