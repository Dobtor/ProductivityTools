# pt-verify：Odoo 18 模組驗證工具包

把散落在暫存目錄的 `kbr.sh`／`paasr.sh`／`acct.sh`／`mix.sh`／`prodr.sh` 與控制台部署腳本整併成一支 CLI。
本機驗證（V0～V4）、正式機唯讀快照、部署計畫（只產腳本）、部署後唯讀檢查。

> ★ **不是自動閘門**：不掛 git hook、不接 CI。何時跑、跑哪一級由人決定（使用者政策）。
> ★ **本工具不寫正式機**：`snapshot`／`post-check` 只讀；`deploy-plan` 只產生腳本，由使用者用 `!` 執行。

## 指令

```bash
tools/verify/pt-verify run <repo 路徑> --level V0|V1|V2|V3|V4 [--mods a,b] [--base <git-ref>|prod:<目標>] [--keep-db]
                           [--target <目標>] [--snapshot-dir <目錄>] [--installed <檔案>] [--no-cache] [--timeout 分鐘]
tools/verify/pt-verify snapshot <目標>
tools/verify/pt-verify deploy-plan <目標> --mods a,b [--repo <本機 repo>] [--ref HEAD] [--install-new] [--dest mod=子目錄]
                                      [--snapshot-dir <目錄>|--installed <檔案>|--no-refresh-snapshot]
tools/verify/pt-verify post-check <目標> --mods a,b
```

`pt-verify` 是 bash 包裝：優先用 `~/Library/Caches/corpaas-kb/venv/bin/python`（3.12），沒有就用系統 `python3`（3.9 也可）。
只用標準庫。最後一行固定印 `<報告 .md 路徑> <PASS|FAIL|BLOCKED>`；結束碼 0／1／2 對應 PASS／FAIL／BLOCKED。

### 環境（預設值，可用環境變數改）

| 用途 | 預設 | 環境變數 |
|---|---|---|
| 工作區（各 repo） | `~/Documents/GitHub` | `PT_VERIFY_GH` |
| Odoo 18 原碼 | `~/Desktop/Claude/odoo-18.0` | `PT_VERIFY_ODOO` |
| venv、pgserver、報告、快取 | `~/Library/Caches/corpaas-kb` | `PT_VERIFY_KB_HOME` |
| 本機 PG 帳密 | `odoo`／`odoo` | `PT_VERIFY_DB_USER`／`PT_VERIFY_DB_PASSWORD` |

## 等級

| 等級 | 做什麼 | 受測模組（`--mods` 省略時） |
|---|---|---|
| V0 靜態 | 秒級：①新的 `migrations/<版號>/` 但 manifest 版號沒升到該版以上（不高於基準版號也會警告：從基準升級不會跑）②diff 新增的 `_name` 已存在於工作區其他 repo 或 Odoo 18 內建（排除自己與 worktrees）③新模型在 `ir.model.access.csv` 沒有 `model_<name>` 列（AbstractModel 除外）④XML `ref=`／`inherit_id`／`eval="ref(...)"` 指向本模組或本 repo 模組不存在的 xmlid ⑤Python `ast.parse` 語法 | 與 `--base` 的 merge-base 比較有變動的模組目錄（含未追蹤檔） |
| V1 | 全新資料庫 `-i` 受測模組，`--test-enable --test-tags /模組` | 變動模組＋本 repo 內的（遞移）反向相依 |
| V2 | 同 V1，但同時裝目標正式機「會一起裝的整組」（快照已安裝清單 ∩ 受測 repo 模組） | 同 V1 |
| V3 | 先裝基準版本（git ref 用 `git archive` 展開；`prod:<目標>` 用快照原碼），再換新版 `-u` 跑測試；報告 `migrations_ran`、`versions_before/after` | 同 V2 |
| V4 | 用快照的**整套正式機原碼樹**裝基準（正式機已安裝清單 ∩ 相關模組＝受測模組＋其反向相依），再把受測 repo 換成新版 `-u` 跑測試；套用 `prod_overrides.toml` | 同 V1 |

每一級都會先跑 V0（便宜）；V0 有 error 等級的問題也會讓該次 FAIL。

**合併前至少 V0～V2；部署前至少 V3；動到「正式機已安裝且版本不同」的模組要 V4。**

### 判定

- **BLOCKED**：相依推導找不到模組（會寫明誰依賴它）、缺基準／快照、pgserver 起不來、基準版本本身裝不起來、沒有可驗證的模組。
- **FAIL**：有「新增失敗」、載入／安裝錯誤（Failed to load registry、CRITICAL、模組沒變成 installed、odoo-bin 非 0 結束且 log 沒有測試失敗）、V0 error、或有 `tests/` 的模組卻 0 項測試（不把「什麼都沒跑」當通過）。
- 非測試的 ERROR log（例如 pgserver 沒有 pg_trgm）列在報告「僅供參考」，不影響判定。

### 基準差集（只回報新增失敗）

失敗清單先扣掉 repo 的 `.claude/skills/verify/known_flaky.txt`（一行一個 `Class.test_name  原因`，`#` 開頭為註解），
剩下的若非空，才跑「基準版本同等級」比對（V1/V2：基準 tree 全新安裝；V3：基準→基準升級；V4：正式機原碼→正式機原碼升級），
以 `base sha＋等級＋mods＋安裝集合` 雜湊快取在 `~/Library/Caches/corpaas-kb/verify-cache/`（`--no-cache` 重跑）。
沒有失敗就不跑基準（省一半時間）。

### addons 路徑自動推導

從受測模組 manifest 的 `depends` 遞迴：受測 repo（或 worktree）排第一 → Odoo 18 內建 addons 與 venv 的
`site-packages/odoo/addons` → 工作區裡找到的 repo（第一層 repo 或一層子目錄如 `OCA/<repo>`）。
排除：`*-worktrees`、git worktree 檢出（`.git` 是檔案）、其他版本的 Odoo 原碼樹（有 `odoo-bin`）、受測 repo 本身與其主 repo。
同名模組在多個 repo 時：系列 18（manifest 版號 `18.0.*`）優先 → 已被選用的 repo → 版號較高 → 第一層 → 字母序，並寫進報告。
如 addons 路徑上別的 repo 會遮蔽選中的那份，會自動把選中的目錄往前挪，挪不動就在報告標 ⚠。**沒有寫死任何 repo 清單。**

### 資料庫與 port

- 庫名 `v_<repo>_<分支簡稱>_<等級>_<時分>`（小寫英數底線、≤ 60 字；基準比對加 `_b`），結束一定 drop（`--keep-db` 保留）。
- port 從 8150–8199 用 socket 挑空的。
- 用本機 pgserver（`~/Library/Caches/corpaas-kb/pgdata`），PATH 會加 `corpaas-kb/bin`（cloc）。

### 報告

`~/Library/Caches/corpaas-kb/verify-reports/<repo>/<YYYYmmdd-HHMMSS>-<等級>.md` 與同名 `.json`，
欄位：level, repo, branch, sha, base, mods, db, port, command, tests_total, failed, errors, skipped, new_failures,
migrations_ran, versions_before, versions_after, overrides, log, duration, verdict（另有 notes、v0_issues、failures、
load_errors、addons_path、logs…）。各步驟 odoo log 同目錄 `<時間>-<等級>-<步驟>.log`。

## 正式機目標：`targets.toml`

`[[target]]` 一筆一個：name、deploy_mode（`host`／`control_panel`）、ssh_host、ssh_key、container、db、sources_path、url、
pause_crons、queue_busy_sql、kill_pattern、odoo_conf、container_log_dir；control_panel 另有 control_panel_instance_id／database_id。
**「待確認」的欄位留空字串**——需要它的指令會拒絕，不會猜。目前：admin.corpaas.com（完整）、admin.dobtor.com（原碼路徑由控制台實例 #49 推得、未 SSH 確認；佇列排程待確認）、
demo-accounting（控制台實例 240／資料庫 238；容器、原碼路徑、網址由控制台唯讀 RPC 查得、未 SSH 確認）。

### snapshot（唯讀）

`ssh … 'cd <sources_path> && tar czf - --exclude=__pycache__ --exclude=.git .'` 解到
`~/Library/Caches/corpaas-kb/prod/<目標>/<YYYYmmdd>/src/`；再以容器內 python＋psycopg2 的**唯讀交易**
（`set_session(readonly=True)`）查 `ir_module_module` 已安裝模組與版本存成 `installed.json`（`meta.json` 記 addons_path）。

`run` 用 `--target <目標>` 取最新快照；或 `--snapshot-dir <目錄>`（有 `src/` 就用 `src/`，否則目錄本身就是原碼樹）＋
`--installed <檔>`（`.json` 或逗號／換行分隔文字檔）。

### `prod_overrides.toml`

V4 整套原碼樹裡要換成本機版本的 repo（每筆寫原因、登記日、推翻條件；推翻條件成立就刪）。報告 `overrides` 列出實際套用了哪些。

### deploy-plan（只產生，不執行）

- `host` 模式：**預設先重抓快照**（同 `pt-verify snapshot <目標>`，唯讀），再用這份當下快照產生漂移比對，避免舊快照誤報漂移；重抓失敗就報錯停下，不會默默退回舊快照。給了 `--snapshot-dir`／`--installed` 就沿用指定的、不重抓；`--no-refresh-snapshot`（例如離線時）改用最新的既有快照，不是今天的會印提醒。
  輸出到 `~/Library/Caches/corpaas-kb/deploy/<目標>/<時間>/`：
  `bundle_<i>.tgz`（`git archive <ref>` 指定模組）、`expect_<i>.md5`（來自上述快照，整行 `LC_ALL=C` 排序）、
  `remote.sh`（漂移比對 → 暫停排程 → 等佇列 → 備份 → 換碼 → `-u`（鎖類錯誤重試）→ 失敗還原 → 重啟 → 恢復排程）、`deploy.sh`、`plan.json`，
  最後一行印 `! bash …/deploy.sh` 給使用者執行。
  - 分組＝「正式機原碼子目錄 → 模組清單」：已在正式機的模組放回原位（例：知識模組在正式機是 `ProductivityTools/`），新模組放 `--dest` 或本機 repo 同名子目錄。
  - 空清單防護：只有新模組的分組不做 find／md5、不備份；模組有未 commit 變更會擋下（`--allow-dirty` 才放行）；正式機未安裝的模組預設只換碼不安裝（`--install-new` 才 `-i`）；沒有要升級／安裝的就拒絕。
- `control_panel` 模式：不產腳本，印出控制台要做的動作（實例模組**每個模組各自按下載**、資料庫模組按更新）。

### post-check（唯讀）

GET `<url>/web/login` 的 HTTP 狀態；有 `PT_VERIFY_RPC_KEY_<目標名大寫、非英數改底線>`（帳號 `PT_VERIFY_RPC_LOGIN_<同>` 或 targets 的 rpc_login）
才用 `/jsonrpc` 讀 `ir.module.module` 的 state／latest_version，缺金鑰就略過並標示。

## 權限

| 動作 | 誰執行 | 會不會寫正式機 |
|---|---|---|
| V0～V4 | Claude／人都可 | 否（只寫本機 pgserver 暫存庫，結束 drop） |
| snapshot | Claude／人都可 | 否（tar 讀檔＋唯讀交易） |
| deploy-plan | Claude／人都可 | 否（只產生檔案） |
| **V5 部署（執行 deploy.sh）** | **只有使用者用 `!` 執行** | **是** |
| post-check | Claude／人都可 | 否 |

## 測試

```bash
cd tools/verify && python3 -m unittest discover -s tests -v
```

涵蓋路徑推導、V0 各規則、報告欄位、差集、port、庫名、TOML、snapshot（假 ssh／docker）、deploy-plan（預設先重抓快照／指定快照不重抓／重抓失敗停下、空清單防護、排序、
remote.sh 在本機用假 docker 實跑：漂移擋下、空分組不掃整個目錄、換碼、`-u`）。
