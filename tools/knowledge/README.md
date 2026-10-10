# 方案知識營運工具

不是 Odoo 模組（沒有 `__manifest__.py`，Odoo 不會載入）。取代先前放在 `/tmp` 暫存區、會被 macOS 定期清掉的小工具。

## 第一次設定

```bash
# 1. 正式機連線密碼存入鑰匙圈（請在「終端機」App 執行；在 Claude Code 用 ! 執行收不到輸入，會存成空白）
security add-generic-password -s corpaas-knowledge-rpc -a admin -w
# 2. 本機測試環境（~/Library/Caches/corpaas-kb：虛擬環境、內嵌 PostgreSQL、檔案庫）
tools/knowledge/setup_local.sh
```

## 日常

| 工具 | 用途 |
| --- | --- |
| `kb.sh [-i]` | 本機跑三個知識模組的全部測試（第一次用 `-i`） |
| `kq.py 14:inc` / `14:full` / `14:select` | 排方案知識更新／全量／AI 圈選情境與能力 |
| `watch.py <佇列> <方案>` | 盯更新到結束 |
| `approve.py <情境>` | 逐篇核准截圖已就緒的待審文章 |
| `deploy/build_bundle.sh <標籤> [上一包]` | 打包 git HEAD、檢查正式機有沒有被改過、印出部署指令 |
| `deploy/deploy_runner.sh` | 只換截圖程式（不升級模組、不重啟、不必等佇列） |

`rpc.py` 提供 `ro()`（只允許讀取方法）與 `rw()`（寫入），錯誤會帶完整訊息。
