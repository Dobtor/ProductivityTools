# 方案知識營運工具

不是 Odoo 模組（沒有 `__manifest__.py`，Odoo 不會載入）。取代先前放在 `/tmp` 暫存區、會被 macOS 定期清掉的小工具。

## 第一次設定

```bash
# 1. 正式機連線密碼存入鑰匙圈（請在「終端機」App 執行；在 Claude Code 用 ! 執行收不到輸入，會存成空白）
security add-generic-password -s corpaas-knowledge-rpc -a admin -w
# 2. 本機測試環境（~/Library/Caches/corpaas-kb：虛擬環境、內嵌 PostgreSQL、檔案庫）
tools/knowledge/setup_local.sh
# 3. 刁難測試要的瀏覽器（約 150MB）
uv pip install --python ~/Library/Caches/corpaas-kb/venv/bin/python playwright==1.48.0
PLAYWRIGHT_BROWSERS_PATH=~/Library/Caches/corpaas-kb/ms-playwright ~/Library/Caches/corpaas-kb/venv/bin/python -m playwright install chromium
```

## 日常

| 工具 | 用途 |
| --- | --- |
| `kb.sh [-i]` | 本機跑知識模組（核心、說明書、建議書）的全部測試（第一次用 `-i`） |
| `kq.py 14:inc` / `14:full` / `14:select` | 排方案知識更新／全量／AI 圈選情境與能力 |
| `watch.py <佇列> <方案>` | 盯更新到結束 |
| `approve.py <情境>` | 核准沒被自審擋下的待審文章（例外清單不批次核准） |
| `deploy/build_bundle.sh <標籤> [上一包]` | 打包 git HEAD、檢查正式機有沒有被改過、印出部署指令 |
| `deploy/deploy_runner.sh` | 只換截圖程式（不升級模組、不重啟、不必等佇列） |
| `hard_env/run_hard.py [--fresh]` | 本機刁難測試：真的截圖程式＋瀏覽器跑 11 項（彈窗登入、會員前台、自訂群組、缺群組的診斷、不准刪單據、不多建公司、平行拍攝、按鈕文字定位、點不到時列出畫面按鈕、匿名使用者封存）（用 venv 的 python；部署前先跑） |

`rpc.py` 提供 `ro()`（只允許讀取方法）與 `rw()`（寫入），錯誤會帶完整訊息。

## 文章核准與抽查（人要做的事）

方案的「自動化等級」在方案表單的知識頁籤：保守（文章都要人核准）、標準（預設，自審通過自動上線）、全自動（AI 有審到、事實都過就上線，一律列入抽查）。

| 要看什麼 | 在哪裡 |
| --- | --- |
| 例外清單（自審不過、等人處理） | 文章清單 → 篩選「例外清單」；文章表單的「自審」區塊寫了原因 |
| 待抽查（自動上線的隨機 5%，每輪至少 1 篇） | 文章清單 → 篩選「待抽查」；看完按「抽查正確」或「抽查退回」（退回率目標 < 10%） |
| 這一輪卡在哪 | 更新執行紀錄 → 「儀表板」分頁（階段、AI 用途、失敗與斷路、缺口、漏斗） |

自審在每次知識更新的出口階段自動跑；內容與截圖都沒變的文章不重審。要重跑就排一次更新（`kq.py 14:inc`）。
