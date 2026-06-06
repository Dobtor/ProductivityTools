# dobtor_meeting_minutes — Monitoring Guide

## Endpoints

### `/meeting_minutes/health` (JSON)

```bash
curl -X POST -b 'session_id=<your-session>' \
     -H 'Content-Type: application/json' \
     -d '{"jsonrpc":"2.0","method":"call","params":{}}' \
     https://odoo.example.com/meeting_minutes/health
```

**回傳欄位**（Q8/O1）：
- `status`: `ok` | `degraded` | `unhealthy`
- `processing_count`: 當前 processing 錄音數
- `stale_count`: processing 超過 15 分鐘的筆數
- `successes_1h` / `failures_1h`：近 1 小時轉錄成敗
- `failure_rate_1h`: 失敗率 (0.0–1.0)
- `by_state_24h`: 近 24 小時各 state 計數
- `latest_success_at` / `latest_failure_at`: ISO8601

**狀態定義**：
- `unhealthy`: `stale_count > 0` — 需立即介入（worker 死/卡）
- `degraded`: 失敗率 ≥ 50% 且 1 小時內 ≥ 3 筆
- `ok`: 其他

### `/meeting_minutes/metrics` (Prometheus)

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'odoo_meeting_minutes'
    metrics_path: /meeting_minutes/metrics
    scheme: https
    static_configs:
      - targets: ['odoo.example.com']
    basic_auth:  # or bearer_token
      username: 'metrics_user'
      password: 'xxx'
```

**輸出指標**（Q7）：
- `dobtor_mm_recording_total{state}` — gauge
- `dobtor_mm_processing_count` — gauge
- `dobtor_mm_stale_count` — gauge
- `dobtor_mm_transcribe_log_total{state, provider}` — counter（24h 視窗）
- `dobtor_mm_summary_log_total{state}` — counter（24h 視窗）
- `dobtor_mm_transcribe_latency_ms{le=...}` — histogram

## Grafana Dashboard 建議

### Panel 1: Recording States（當前）
```
dobtor_mm_recording_total
```
Pie chart by `state`

### Panel 2: Transcribe Success Rate
```
rate(dobtor_mm_transcribe_log_total{state="success"}[5m])
/
rate(dobtor_mm_transcribe_log_total[5m])
```

### Panel 3: p95 Latency
```
histogram_quantile(0.95, sum(rate(dobtor_mm_transcribe_latency_ms_bucket[5m])) by (le))
```

### Panel 4: Stale Workers
```
dobtor_mm_stale_count
```
Alert if `> 0` for 5 min

## Alerting Rules

```yaml
groups:
  - name: meeting_minutes
    rules:
      - alert: MeetingTranscribeStale
        expr: dobtor_mm_stale_count > 0
        for: 5m
        labels: {severity: critical}
        annotations:
          summary: 'Transcribe worker stuck or died'
          runbook: 'Check ir.cron "Reclaim Stale Transcribe Jobs" is active'

      - alert: MeetingTranscribeHighFailureRate
        expr: |
          sum(rate(dobtor_mm_transcribe_log_total{state!="success"}[15m]))
          /
          sum(rate(dobtor_mm_transcribe_log_total[15m])) > 0.5
        for: 10m
        labels: {severity: warning}
        annotations:
          summary: 'Transcribe failure rate > 50% in last 15 min'
          runbook: 'Check Transcription Logs; likely provider issue'

      - alert: MeetingQuotaExceeded
        expr: increase(dobtor_mm_transcribe_log_total{state="quota_exceeded"}[1h]) > 3
        labels: {severity: warning}
        annotations:
          summary: 'Provider quota hit multiple times'
```

## Logs to Watch

```
[security] Fernet key loaded from <source>
[security] Transcription API key changed by <user>
[security] Fernet key version bumped to <N>
[transcribe] recording=X code=Y: <msg>
[queue] reclaiming N stale running jobs
```

## Runbook: Worker 卡住

1. 看 Grafana 是否 `stale_count > 0`
2. 到 **Meeting Minutes → Transcription Jobs**，filter `state=running`
3. 查 `picked_at` 時間與 `worker_pid`
4. 若 `Reclaim Stale Transcribe Jobs` cron 未啟用 → 啟用
5. 或按 **Cancel** 取消該 job（recording 會回 error）→ 使用者可手動 Retry

## Runbook: 轉錄全部失敗

1. 看 **Transcription Logs** filter `failures`
2. group by `state`：
   - 多數是 `config_error` → 檢查 API key（可能輪換後忘記 re-encrypt）
   - 多數是 `quota_exceeded` → 聯絡 AssemblyAI/OpenAI 加配額
   - 多數是 `network_error` → 防火牆/DNS 問題
   - 多數是 `parse_error` → API 回應格式變了（升級相容性）

## Runbook: 金鑰輪換異常

1. 若使用者抱怨「API key 忽然錯誤」：
   - 檢查 `ir.config_parameter` 的 `dobtor_meeting_minutes.fernet_key_version`
   - 若 stored ciphertext 是 `v1::` 但當前 env 是 v2 無 OLD key → 無法解密
2. 補救：把舊 Fernet key 放回 `DOBTOR_MM_FERNET_KEY_OLD_1` → 重啟 → `action_rotate_transcription_api_key`
