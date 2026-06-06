# dobtor_meeting_minutes — Deployment Checklist

## 1. 前置需求

- Odoo 18.0+
- Python 3.10+（`cryptography` 隨 Odoo 打包）
- PostgreSQL 12+（使用 `FOR UPDATE SKIP LOCKED`）
- 相依模組：`dobtor_mail_activity`、`dobtor_ai_chatbot`、`calendar`、`portal`

## 2. Fernet 加密金鑰設置（S4/Q2）

**必做**：在 Odoo 啟動前將 Fernet key 放入環境變數或 `odoo.conf`，**避免靠自動產生（存於 DB backup 會有洩漏風險）**。

### 選項 A：環境變數（推薦）

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# → 輸出一串 44 字元的 base64 key

export DOBTOR_MM_FERNET_KEY="<上面產生的 key>"
```

在 systemd service 檔裡設定：

```ini
[Service]
Environment="DOBTOR_MM_FERNET_KEY=..."
```

### 選項 B：odoo.conf

```ini
[options]
dobtor_meeting_minutes_fernet_key = <44-char base64 key>
```

### 金鑰輪換流程（Q2）

1. 在 env 或 conf **增加** 舊 key 到 `DOBTOR_MM_FERNET_KEY_OLD_1`（最多 9 把舊 key）
2. 將 `DOBTOR_MM_FERNET_KEY` 換成新 key
3. 重啟 Odoo（清 `_KEY_CACHE`）
4. Settings → Meeting Minutes → Run Key Rotation（呼叫 `action_rotate_transcription_api_key`）
5. 或啟用 cron **Re-encrypt API Keys After Rotation**（預設關閉）自動 re-encrypt

## 3. 模組安裝/升級

```bash
./odoo-bin -d <db> -u dobtor_meeting_minutes --stop-after-init
```

## 4. 執行測試

```bash
./odoo-bin -d <db> -i dobtor_meeting_minutes --test-enable --stop-after-init
```

預期通過 **70+ 測試案例**（mask_secrets, TranscribeError, transcribe_log, state_recompute, call_http, portal_security, crypto_roundtrip）。

## 5. 後台驗證

1. Settings → Meeting Minutes
   - 選 provider、填 API key（會看到 `●●●●abcd` 遮蔽顯示）
   - 按「Run Test」確認 provider 可連
2. Meeting Minutes 選單應見：
   - **Meeting Minutes**（主入口）
   - **Transcription Jobs**（Q1 佇列 Dashboard，管理員）
   - **Transcription Logs**（錯誤分析，管理員）
   - **Summary Logs**（摘要歷史，管理員）
   - **Summary Templates**（Prompt 範本管理，管理員）

## 6. Cron 設定

| Cron 名稱 | 預設 | 建議 |
|---|---|---|
| Cleanup Stale Processing Recordings | 每 15 分鐘，active | 保持 |
| Cleanup Old Transcribe Logs | 每天 | 保持 |
| Auto-retry Failed Transcriptions | 停用 | 視業務啟用 |
| Reclaim Stale Transcribe Jobs | 每 5 分鐘，active | 保持（關鍵：崩潰恢復）|
| Process Transcribe Job Queue | 每 2 分鐘，active | 保持（關鍵：崩潰恢復）|
| Re-encrypt API Keys After Rotation | 停用 | 輪換期間暫時啟用 |

## 7. Portal 設定驗證

- 會議 Meeting Minutes 現有 `note_note_rule_portal` record rule：
  - portal user 可讀自己為 signer 或 calendar_event 與會者的 meeting
- 留言/瀏覽記錄：**必須**持有效 `signature_token` 才認定為發言者

## 8. i18n

產生 .pot：

```bash
./odoo-bin -d <db> \
    --i18n-export=addons/dobtor_meeting_minutes/i18n/dobtor_meeting_minutes.pot \
    --modules=dobtor_meeting_minutes \
    --stop-after-init
```

翻譯 zh_TW：

```bash
./odoo-bin -d <db> \
    --i18n-export=addons/dobtor_meeting_minutes/i18n/zh_TW.po \
    --modules=dobtor_meeting_minutes \
    --language=zh_TW \
    --stop-after-init
```

## 9. 常見問題

### Q: Fernet 金鑰遺失怎麼辦？
A: 原本加密的 API key 無法復原。需進 Settings 重新輸入 API key；系統會用新金鑰重新加密。

### Q: Job 卡住不動？
A: `Reclaim Stale Transcribe Jobs` cron（5 分鐘）會偵測 stale running → pending；`Process Transcribe Job Queue` cron 會接手處理。

### Q: 升級後舊 API key 仍然能用嗎？
A: 可以。`crypto.decrypt` 對無 `ENC::` prefix 的值自動當純文字處理（向後相容）。下次 set_values 才加密。
