# -*- coding: utf-8 -*-
"""集中常數定義

所有跨檔案共用的 selection 值、錯誤代碼、時限、預設值皆於此定義，
避免散落各 model 導致新增/刪除選項時漏改。
"""

# ============================================================
# Recording 相關限制
# ============================================================
MAX_RECORDING_DURATION = 7200   # 2 小時，單位秒
MAX_FILE_SIZE = 200 * 1024 * 1024  # 200 MB

# ============================================================
# Transcribe 執行
# ============================================================
# Stale processing 清理門檻（分鐘）— 小於此值視為仍執行中
# 需涵蓋：上傳(300s) + 提交(60s) + 輪詢(600s) + 緩衝 = 至少 20 分鐘
STALE_PROCESSING_MINUTES = 30

# 自動重試退避（分鐘）— key 為上一次 attempt_no
AUTO_RETRY_BACKOFF_MINUTES = {1: 5, 2: 15, 3: 45}
AUTO_RETRY_MAX_ATTEMPTS = 3

# 連續失敗通知門檻
CONSECUTIVE_FAILURE_ALERT = 3

# HTTP response 擷取上限（bytes，寫 log 前遮蔽）
RESPONSE_SNIPPET_LIMIT = 2000

# Log 保留天數
LOG_RETENTION_DAYS_SUCCESS = 30
LOG_RETENTION_DAYS_FAILURE = 180

# ============================================================
# Selection: Recording state
# ============================================================
RECORDING_STATE_SELECTION = [
    ('uploaded', 'Uploaded'),
    ('processing', 'Processing'),
    ('done', 'Transcribed'),
    ('error', 'Error'),
]

# ============================================================
# Selection: Note transcript_state
# ============================================================
TRANSCRIPT_STATE_SELECTION = [
    ('none', 'None'),
    ('processing', 'Processing'),
    ('done', 'Done'),
    ('partial', 'Partially Done'),
    ('error', 'Error'),
]

# ============================================================
# Selection: Transcribe log state (error classification)
# ============================================================
TRANSCRIBE_LOG_STATE_SELECTION = [
    ('success', 'Success'),
    ('config_error', 'Config Error'),
    ('upload_failed', 'Upload Failed'),
    ('http_error', 'HTTP Error'),
    ('timeout', 'Timeout'),
    ('quota_exceeded', 'Quota Exceeded'),
    ('parse_error', 'Parse Error'),
    ('network_error', 'Network Error'),
    ('stale_worker', 'Stale Worker'),
    ('internal_error', 'Internal Error'),
]

# 可重試的錯誤類型（對暫時性錯誤退避後重試）
RETRIABLE_ERROR_CODES = frozenset({
    'network_error', 'timeout', 'stale_worker', 'upload_failed',
})

# 有效的 TranscribeError code（raise 時允許的集合）
VALID_TRANSCRIBE_ERROR_CODES = frozenset({
    'config_error', 'upload_failed', 'http_error', 'timeout',
    'quota_exceeded', 'parse_error', 'network_error', 'internal_error',
})

# state badge 顯示分類（給 view decoration 使用）
LOG_STATE_DECORATIONS = {
    'success': 'success',
    'timeout': 'warning',
    'network_error': 'warning',
    'stale_worker': 'warning',
    'upload_failed': 'warning',
    'config_error': 'danger',
    'http_error': 'danger',
    'quota_exceeded': 'danger',
    'parse_error': 'danger',
    'internal_error': 'danger',
}

# ============================================================
# Selection: Provider
# ============================================================
TRANSCRIPTION_PROVIDER_SELECTION = [
    ('assemblyai', 'AssemblyAI (Recommended)'),
    ('api', 'OpenAI Whisper API'),
    ('remote', 'Remote whisperX Service'),
]

# ============================================================
# Timeout（秒）
# ============================================================
HTTP_TIMEOUT_UPLOAD = 300
HTTP_TIMEOUT_SUBMIT = 60
HTTP_TIMEOUT_POLL = 30
HTTP_TIMEOUT_FULL = 600
MAX_POLL_WAIT = 600
POLL_INTERVAL = 5
