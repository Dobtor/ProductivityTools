# Dobtor AI Bridge · 此畫面說明（dobtor_ai_bridge_help）

CorPaaS 方案知識核心的**租戶端**出口，裝在客戶的 Odoo 18 上（依賴 `dobtor_ai_bridge_backend`）。
實作契約：`dobtor_corpaas_knowledge/IMPLEMENTATION_SPEC.md` 的「模組 E」。

## 使用者看到什麼

- 後台 AI 助理面板的情境列多一顆 **「此畫面說明」**：用目前畫面的 model／action／view_type
  查說明，列成按鈕，開新分頁。每條顯示標題、情境名；`kind = upsell` 標「加購功能」。
- 在面板**提問**時，同一句話也會拿去查說明，結果列在 AI 回答下方「相關說明」。
- 畫面與說明拍攝時不同（D5）時加註 **「你的畫面可能與說明不同」**。

★ 連結**不經過 AI**：主控台產生 → 本站伺服器轉查 → 面板自己渲染。面板原本的
`linkHref()` 只收本站相對路徑、markdown 不渲染連結，那道防外洩設計不動。

## 設定（設定 → AI Bridge → 此畫面說明）

| 參數 | 預設 | 用途 |
|------|------|------|
| `dobtor_ai_help.console_url` | `https://admin.corpaas.com` | 向哪台主控台查 |
| `dobtor_ai_help.database` | 空＝`env.cr.dbname` | 主控台用它找出本庫的方案 |
| `dobtor_ai_help.public_domains` | `www.corpaas.com` | 允許顯示的說明網域（逗號分隔） |
| `dobtor_ai_help.console_key` | 空（由主控台下發） | 請求簽章金鑰；設定頁只顯示「有／沒有」，不顯示值 |

★ 主控台網址：設定頁與主控台下發**共用同一個 ICP** `dobtor_ai_help.console_url`。主控台下發金鑰時會
一併把它改成自己的網址——這是刻意的：金鑰只在簽發它的主控台有效，送到別台必定 `bad_signature`。
管理者之後手動改網址也會生效（最後寫入者為準），但要記得換主控台就得由新主控台重新下發金鑰。

只顯示 **https** 且網域是主控台或公開說明網域的連結；伺服器與瀏覽器各擋一次。

## 後端

`POST /dobtor_ai/help/links`（type=json, auth=user，需「AI 助理使用者」群組）
參數 `query?`、`action`（xmlid 或數字 id）、`model`、`view_type`
→ `{ok, results: [{feature_key, title, url, kind, scenario, diverged}], hosts, package?, error?}`

- 伺服器端 `requests` POST 主控台 `/corpaas/knowledge/v1/help`，timeout 8 秒；
  `trust_env = False`，只從環境變數取 proxy（並照 no_proxy）。
- 主控台不通、拒絕、回錯：一律回空清單（`ok: false, error`），面板不跳錯。
- 數字 action id 先轉 xmlid（主控台只認 xmlid；各庫 id 不同）。
- `groups`：目前使用者群組的 xmlid（排序、略過沒有 xmlid 的，最多 200 個）；主控台用來做角色過濾
  （功能點 `group_xmlids` 與它無交集就不回）與說明文章排序。

### 請求簽章（help 與 divergence 兩支都簽）

```
X-KB-Database:  <庫名，同 params.database>
X-KB-Timestamp: <unix 秒>
X-KB-Signature: hex(hmac_sha256(console_key, b"<timestamp>." + 原始 request body bytes))
```

- ☠️ body 由本模組 `json.dumps(...).encode()` 後以 `data=` 送出（不用 `json=`），簽的 bytes 就是送出的 bytes。
- 沒有金鑰：照樣送但不帶 Timestamp／Signature；主控台要求簽章時回 `error: 'unsigned'`，面板照常（空清單），
  設定頁顯示「尚未收到主控台下發的金鑰」。主控台回 `unsigned`／`bad_signature` 會記一筆 warning（不含金鑰）。
- ☠️ 金鑰絕不寫進 log、例外訊息或送到瀏覽器（設定頁欄位是 compute 的 bool）。

### D5 指紋比對

結果帶 `fingerprint.elements` 與 `scope_hash` 時，以**目前使用者**、`lang` 跑
`env[model].get_views(views)`，用 `lib/fingerprint_lib.py` 算 `scope_hash`：

- 不一致 → `diverged: true`，並在背景執行緒 POST 主控台 `/corpaas/knowledge/v1/divergence`
  （同一庫、同一功能點、同一個實際值 6 小時內只回報一次）。
- 算不了（沒權限、模型不存在、指紋版本不同）→ 不標，不回報。
- 自然語言查詢時不借用目前畫面的 model（功能點可能在別的畫面）。

`fingerprint` 內本模組會讀的鍵：`elements`、`scope_hashes`（各角色；落在任一份就不算分歧，回報時 expected 取第一個）、`scope_hash`（沒有清單時的退路）、`views`（`[[view_xmlid|false, type]]`）、
`menu_path`、`view_mode`、`model`、`lang`（預設 zh_TW）、`version`。
沒有 `views` 時照主控台 `views_for_fingerprint` 的規則由 `view_mode` 推。

☠️ `lib/fingerprint_lib.py` 是主控台 `services/fingerprint_lib.py` 的逐字複本，兩份必須一致。

## 測試

```
odoo-bin -d <db> -i dobtor_ai_bridge_help --test-tags /dobtor_ai_bridge_help --stop-after-init
```
