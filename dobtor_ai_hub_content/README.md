# Dobtor AI Hub · 知識內容模式（dobtor_ai_hub_content）

CorPaaS 方案知識核心（`dobtor_corpaas_knowledge`）的 AI 出口，裝在 **AI Hub** 那一台。
實作契約：`dobtor_corpaas_knowledge/IMPLEMENTATION_SPEC.md` 的「模組 D」。

## 做了什麼

| 項目 | 內容 |
|------|------|
| 新模式 | `content`（知識內容）加進 `ai.hub.session.mode`、`ai.hub.run.mode`、`ai.hub.artifact.type`、`ai.hub.route.rule.mode` |
| 能力需求 | `MODE_REQUIREMENTS['content'] = ('has_agent_loop',)`，模組載入時寫入 |
| 來源設定 | `ai.hub.source.content_enabled`（預設關）、`content_max_chars`（預設 200000） |
| 新端點 | `POST /ai_hub/api/v1/content_run` |

## 端點

```
POST /ai_hub/api/v1/content_run      (JSON-RPC；header X-AI-Hub-Key = 來源的上行金鑰)
  params: {purpose, prompt, context?}
  → {ok: true, run_id, conversation, quota_left, cost_left}
  → {ok: false, error: unauthorized | content_disabled | invalid_prompt
                       | prompt_too_long | cost_exceeded | quota_exceeded | refused}
```

查結果用既有的 `POST /ai_hub/api/v1/run_status {run_id}`——只有同一把金鑰看得到。

- 每次呼叫開一個新 Session（name = purpose），不續用：續用會帶 `--resume`，
  上一件工作的上下文會混進下一件。
- Run 標 `origin='uplink'`，所以吃來源的每日次數與成本上限。
- 不要求 L2：這個模式不寫對方系統；授權改由 `content_enabled` 決定。
- `context` 收下不採用（主控台的記帳資訊）。

## 開通步驟

1. AI Hub → 來源 → 新增一筆給主控台用的來源（能力等級 L0 即可）。
2. 勾「允許知識內容」→ 上行通道那一組會出現 → 按「產生上行金鑰」。
3. 依主控台的用量調高每日次數／成本上限（預設 50 次、$5，對整個方案的 refresh 可能不夠）。
4. 把 AI Hub 網址與金鑰填進主控台「設定 → 知識核心 → AI Hub」。

## 注意

- ★ Runner 對 content 模式沒有系統提示（`SYSTEM_PROMPTS.get(mode, '')`），
  角色、語言、輸出格式都在主控台送來的 prompt 裡。
- ☠️ `run_status` 回的文字會經過 `brand_sanitize`（`ai_hub.brand_filter`）：
  回覆裡的 “Odoo” 會被換成品牌別名。知識內容若需要保留原字，要在 AI Hub
  關掉 `ai_hub.brand_filter`，或讓主控台的 prompt 本來就不寫那個字。
- 解除安裝時，content 的 Session／Run／產物改回預設模式（保留成本紀錄），
  只為 content 寫的路由規則會刪掉（清空 = 所有模式，會管到別的模式）。

## 測試

```
odoo-bin -d <db> -i dobtor_ai_hub_content --test-tags /dobtor_ai_hub_content --stop-after-init
```
