# Dobtor Messaging Base — 架構與設計規劃

> 版本：18.0.1.0.0 ｜ 狀態：骨架（skeleton）
> 目的：作為 `dobtor_line_message`、`dobtor_telegram_message` 等多個「外部訊息平台 ↔ Odoo Discuss 雙向同步」模組的共用基底。

---

## 0. 一句話結論

LINE 與 Telegram 在**概念層**高度同構，但在**協定層**幾乎沒有一行能直接共用。
因此本模組抽象的是「**流程骨架 + 平台實作鉤子（provider dispatcher）**」，
而不是抽象 API 細節。抽象機制沿用團隊既有的 `tw.einvoice.provider` dispatcher 模式
（Selection `code` + 動態方法 `_%s_xxx`）。

```
dobtor_messaging_base        ← 本模組：provider 無關的骨架/mixin/前端/精靈/身分
   ├─ dobtor_line_message        ← 既有，改 depends base，只留 LINE 協定實作
   └─ dobtor_telegram_message    ← 新增，只寫 Telegram 協定實作
```

---

## 1. LINE vs Telegram 協定對照（決定抽象邊界）

| 面向 | LINE | Telegram（core.telegram.org/bots/api） | 共用？ |
|------|------|----------------------------------------|--------|
| API base | `api.line.me`，Bearer access token | `api.telegram.org/bot<token>/METHOD` | ❌ 各自 |
| **Webhook 驗證** | HMAC-SHA256(raw body, channel secret) 比對 `X-Line-Signature` | 比對 `X-Telegram-Bot-Api-Secret-Token` header（setWebhook 的 secret_token）+ 可選 IP 白名單 149.154.160.0/20、91.108.4.0/22 | ❌ 各自 |
| 進站結構 | `events[]`，每筆 `type` + `source.{type,userId/groupId/roomId}` | `Update` 物件，擇一 `message/edited_message/callback_query/my_chat_member/...` | ❌ 各自 parse |
| 來源識別 | user/group/room + 三種 id | `chat.id`（私聊=正數=user id；群組/超群=負數）+ `from.id`=作者 | ⚠️ 正規化後共用 |
| **媒體取得** | `getMessageContent(messageId)` 直接回 bytes | 兩步：`getFile(file_id)` → `file_path` → 下載 `api.telegram.org/file/bot<token>/<file_path>` | ❌ 各自 |
| 送訊息 | `send_text/image/video/audio/file_message` | `sendMessage/sendPhoto/sendVideo/sendAudio/sendDocument/sendSticker/sendLocation` | ⚠️ 介面共用、實作各自 |
| 出站附件 | 帶 Odoo 公開 URL 給 LINE | 同樣可 `photo=<公開URL>`（或 multipart / 重用 file_id） | ✅ 模式可共用 |
| 個人資料 | `getProfile`/`getGroupMemberProfile` | `getChat`/`getChatMember`/`getUserProfilePhotos` | ❌ 各自 |
| 貼圖 | CDN URL by stickerId（PNG/APNG） | `file_id` 下載（WEBP / TGS Lottie / WEBM） | ❌ 各自 |
| 歡迎/上線觸發 | `follow` 事件 + `replyToken`（短效，需快回） | `/start` 指令 或 `my_chat_member` 更新；**無 reply token**，直接 `sendMessage(chat_id)` | ❌ 各自 |
| 群組可見性 | 加好友/入群即可收 | **預設 privacy mode 開**，群組只收指令/回覆；要全收需 BotFather 關閉 | ⚠️ 設計需注意 |

**關鍵啟示**：`replyToken`、HMAC、`getMessageContent`、貼圖 URL 都是 LINE 特有假設，
**不可**塞進共用層。共用層的送訊息介面以 **`chat_id`（= source_id）** 為主，
reply token 當 LINE 專屬可選參數。

---

## 2. 共用 vs 平台特定 拆分

### ✅ 放進 base（provider 無關）

1. **`discuss.channel` 中性 mixin**：`messaging_provider`（可擴充 Selection）、
   `messaging_source_type`（正規化 user/group）、`messaging_source_id`、
   `is_messaging_channel`、`messaging_sync_enabled`、`messaging_category`、
   `messaging_sort_sequence`、`messaging_last_sync_date`、`messaging_picture_url`。
2. **出站骨架**：`message_post` override → `_messaging_should_sync_outbound`
   （用中性 `_from_messaging` context 防迴圈）→ 動態派發 `_{provider}_send_message`。
3. **進站共用 helper**（給各 controller 呼叫）：
   `_messaging_get_or_create_channel`、`_messaging_get_or_create_partner`、
   `_messaging_post_inbound`（統一包 `_from_messaging=True`）、成員管理。
4. **`_messaging_download_safe`**：SSRF 防護下載（HTTPS、信任網域、magic bytes、
   大小上限）。各 provider 只傳自己的信任網域清單。
5. **身分模型 `messaging.account`**（見 §3.2）。
6. **前端通用件**：`MessagingPartnerCard`（讀 res.partner，中性）、成員清單/訊息作者
   頭像 patch（判斷 `persona.userId` 缺失 → 開卡）、`thread_model.isMessagingChannel`、
   側欄圖示、composer IME patch。
7. **通用精靈**：partner 綁定（本模組已含 `messaging.partner.link`）、頻道合併（規劃中）。
8. **通用設定**：`operator_partner_ids`、歡迎訊息骨架。

### ❌ 留在各平台模組（協定特定）

- webhook 路由 + 驗證（HMAC vs secret_token+IP）
- Update/event 解析 → 正規化成中性 dict
- API client service（`line.api.service` vs `telegram.api.service`）
- 媒體下載策略（直接 content vs getFile 兩步）
- 貼圖處理、歡迎觸發、reply token
- 各自 `res.config.settings` 的 token 欄位

---

## 3. 核心抽象設計

### 3.1 Provider dispatcher（沿用 einvoice 模式）

中性 mixin 上：

```python
def _messaging_dispatch(self, hook, *args):
    self.ensure_one()
    return getattr(self, f'_{self.messaging_provider}_{hook}')(*args)
```

- 出站：`message_post` → `_messaging_dispatch('send_message', message, kwargs)`
  → provider 實作 `_line_send_message` / `_telegram_send_message`。
- `messaging_provider` 用「方法式 Selection」（`_selection_messaging_provider`），
  provider 模組 override 該方法 append 自己；base 預設為空，因此 base 單獨安裝時 inert。

**Provider 必須實作的鉤子契約**（在各自的 `discuss.channel` 繼承中）：

| 鉤子 | 簽名 | 說明 |
|------|------|------|
| `_<code>_send_message` | `(self, message, message_kwargs)` | 把 Odoo 訊息送到該平台 |

**Provider 控制器 / service 必須提供**：webhook 驗證、Update 解析、媒體下載、
個人資料查詢——這些不在 base 派發，由各 controller 自行處理後呼叫 base 的進站 helper。

### 3.2 身分模型：`messaging.account`

比「在 res.partner 加一堆 `xxx_user_id` 欄位」乾淨，且天然支援**一人同時有 LINE+Telegram**：

```
messaging.account
  partner_id        M2O res.partner (ondelete cascade)
  provider          Selection（與 channel 同源）
  external_user_id  Char
  username / display_name / line/tg 等中性 profile 欄位
  _sql: unique(provider, external_user_id)
```

`_messaging_get_or_create_partner(provider, ext_id, profile)`：
先查 account → 回 partner；沒有則建 partner + account。
**綁定精靈**把 account 從孤兒 partner 改掛到目標客戶 + 重指訊息 author_id。

> ⚠️ **LINE 的特殊耦合**：現有 `res.partner.line_user_id` 來自 `dobtor_line_login`
> （OAuth 登入也在寫它）。LINE 不要貿然拔掉。建議：base 用 `messaging.account` 當標準
> 身分；LINE 模組提供一次性 migration 把既有 `line_user_id` 同步成 account 列，並讓
> login 模組繼續維護 line_user_id（兩者並存，account 為查詢入口）。這是刻意取捨，避免
> 動到正在運作的登入流程。

### 3.3 中性化的 `_channel_basic_info` / 前端

`_channel_basic_info` 回傳 `is_messaging_channel`、`messaging_provider`、
`messaging_category`、icon class；前端 `thread_model`、側欄、頭像卡全部吃中性欄位。
新 provider 只需提供自己的 icon 與 category 文案。

---

## 4. 既有 LINE 模組遷移：兩條路

| | 策略 A：徹底重構 | 策略 B：加法式漸進（推薦） |
|--|--|--|
| 做法 | `line_*` 欄位全改名 `messaging_*` | base 用中性欄位；LINE 先共用前端/精靈/下載/身分，channel 的 `line_*` 暫留並用薄鉤子對接 |
| 長期品質 | 最高、零重複 | 仍有少量重複 |
| 風險 | **高**：遷移線上資料、改所有視圖、重寫 merge SQL、全模組回歸 | **低**：不動既有資料與 webhook，逐步收斂 |
| 適合 | 全新、無線上資料 | **目前情況（admin.dobtor.com 已上線且有資料）** |

→ 建議走 **B**。抽象是為了服務 Telegram 新需求（正當），用最小擾動把 LINE 接上來。

---

## 5. 落地順序（每步可獨立 commit / 上線）

1. **建 base**（本骨架）：上移零風險高複用三塊——`MessagingPartnerCard`、SSRF 下載 helper、
   partner 綁定精靈。LINE 改 depends base 並指向 base 版本。
2. base 加 **中性 channel mixin + dispatcher + `messaging.account`**；LINE 薄鉤子接上
   （line_user_id ↔ account migration）。
3. **新建 `dobtor_telegram_message`**：`telegram.api.service`（getFile 兩步下載、send*）、
   `/telegram/webhook`（secret_token 比對 + IP 白名單）、Update parser、設定 bot_token/secret_token。
   頻道/歸戶/出站/前端/綁定全繼承 base。
4. LINE 的 webhook/service 留在 LINE，僅把共用 helper 呼叫切到 base。

---

## 6. Telegram 實作備忘（設計階段就要定）

1. **群組全收訊息**：必須在 BotFather 關閉 bot privacy mode，否則群組只收指令/回覆。
2. **chat.id 規則**：私聊=正數=user id；群組/超群=負數。`messaging_source_id` 直接存
   `chat.id`（字串化）；`messaging_source_type` 依 `chat.type` 正規化（private→user，
   group/supergroup→group）。作者用 `message.from.id`。
3. **出站附件**：沿用「Odoo 附件公開 URL」模式（`sendPhoto(photo=url)`），可重用 LINE 作法。
4. **secret_token**：用 `hmac.compare_digest` 常數時間比對 header，fail-fast，
   位置對齊 LINE 的 verify。
5. **媒體下載**：`getFile` → `file_path` → 下載 URL 含 token，**勿記錄到 log**。
6. **單一 webhook/ bot**：Telegram 一個 bot 只能一個 webhook；`allowed_updates` 控制收哪些。
7. **歡迎流程**：以 `/start` 指令或 `my_chat_member`（status 變 member）觸發，
   直接 `sendMessage(chat_id, welcome)`，無 reply token。

---

## 7. 本模組檔案地圖（骨架）

```
dobtor_messaging_base/
  models/
    messaging_api_mixin.py     AbstractModel：SSRF 安全下載 + magic bytes（provider service 繼承）
    messaging_account.py       身分模型 messaging.account
    discuss_channel.py         中性欄位 + dispatcher + 進/出站 helper（多數 provider 鉤子為抽象）
    res_partner.py             messaging_account_ids、messaging_channel_count、綁定入口
    res_config_settings.py     operator_partner_ids、welcome（中性骨架）
  wizards/
    messaging_partner_link.py  綁定外部聯絡人到既有客戶（泛化自 line.partner.link）
  controllers/
    messaging_webhook.py       MessagingWebhookMixin：給 provider 控制器繼承的共用步驟與抽象鉤子
  static/src/js/
    messaging_partner_card.js  MessagingPartnerCard（讀 res.partner）
    channel_member_list_patch.js  成員清單頭像 → 開 partner 卡（無 user 時）
    message_author_patch.js    訊息作者頭像 → 開 partner 卡（限 messaging channel）
    thread_model_patch.js      Thread.isMessagingChannel / provider getter
  static/src/xml/
    messaging_partner_card.xml
  security/
    messaging_security.xml     group_messaging_manager
    ir.model.access.csv
  views/
    messaging_account_views.xml, messaging_partner_link_views.xml,
    res_partner_views.xml, messaging_menus.xml
```

> 標記為「抽象鉤子」的方法在 base 內以 `NotImplementedError` 或空實作呈現，
> 由 provider 模組填上。base 單獨安裝時不註冊任何 provider，故所有派發路徑 inert，可安全安裝。
