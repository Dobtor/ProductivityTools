import os, subprocess, sys, datetime
S = os.path.dirname(os.path.abspath(__file__))
GH = os.path.expanduser('~/Documents/GitHub')
CASES = os.path.join(GH, 'ProductivityTools/tools/knowledge/cases/finance_tw_2026_11.json')

R = {
 'Knowledge': dict(wt='Knowledge-worktrees/decisions', cases=False, rep='dobtor_corpaas_knowledge',
   intro='方案知識七模組（dobtor_corpaas_knowledge＋六個出口／交換／經銷商模組）。',
   group='''- **admin.corpaas.com**（主體；`host` 部署，目標名 `admin.corpaas.com`）：七個模組**全部**已安裝。正式機原碼子目錄是 `ProductivityTools/`（不是 `Knowledge/`，見 D-KN-006），`deploy-plan` 會把既有模組放回原位。
- 從屬主控台尚未登記在 targets.toml（要驗證從屬端時先補 targets）。
- 組合安裝必含七模組一起裝：只測核心看不出模型同名（D-KN-001）。''',
   v2='--target admin.corpaas.com', v4target='admin.corpaas.com',
   extra='''- 2026-11-03 快照：正式機 `dobtor_corpaas_knowledge_proposal` 18.0.1.1.0、`_reseller` 18.0.1.2.0，與本 repo 版號不同 → 動到這兩個（或它們的相依）部署前要 V4。
- 已知不穩定：`TestRefresh` 兩項（見 `known_flaky.txt`），工具會自動略過，不要因此判 FAIL。'''),
 'PAAS': dict(headnote='本 repo 的 origin/HEAD 指向 `dev-14.0`（不是 18.0），不給的話 V0 會把整個 18.0 的模型都當成「新增」而誤報。', wt='PAAS-worktrees/decisions', cases=False, rep='dobtor_corpaas_product',
   intro='CorPaaS 營運端控制台、租戶端代理、經銷商端模組，共 30 個。',
   group='''- **admin.corpaas.com**（營運端控制台；`host` 部署，一律主機手動部署 D-PA-003；目標名 `admin.corpaas.com`）：裝 22 個——`dobtor_infrastructure`／`_ai`／`_aws`／`_cost`／`_github`／`_google_cloud`、`dobtor_github_connector`、`dobtor_corpaas_database`／`_product`／`_sale`／`_template`／`_website`／`_theme`／`_partner`、`dobtor_corpaas_reseller`／`_reseller_repo`／`_reseller_portal`／`_reseller_portal_partner`／`_reseller_emergency`、`dobtor_corpaas_emergency_access`、`dobtor_database_tools`、`dobtor_database_activity_stats`。
- **每個租戶實例**（經控制台部署，例：`demo-accounting`）：`dobtor_database_tools`、`dobtor_license_control`、`session_redis`、`bus_alt_connection`。
- **白標經銷商自己的 Odoo**：`corpaas_partner_connector`／`_portal`／`_knowledge`／`_knowledge_notes`（未登記 targets）。
- `dobtor_corpaas_legacy_code` 不可安裝（D-PA-002），不要放進 `--mods`。''',
   v2='--target admin.corpaas.com', v4target='admin.corpaas.com',
   extra='''- 測 github_connector／infrastructure_github 相關要先設 `github.source_code_local_path`，否則 fixture 全掛。
- 租戶端模組（database_tools、license_control 等）V2 用 `--target demo-accounting`（尚無快照時整組＝受測模組本身，報告會註明）。'''),
 'Accounting': dict(headnote='本 repo 的 origin/HEAD 指向 `master`（不是 18.0），不給的話 V0 會把整個 18.0 的模型都當成「新增」而誤報。', wt='Accounting-worktrees/decisions', cases=True, rep='dobtor_account_close',
   intro='台灣會計 11 個模組（立沖帳核心、傳票、關帳、票據、本票、固定資產、在建工程、請款、銀行對帳、發票 SMS、在地化設定）。',
   group='''- **demo-accounting**（控制台部署，目標名 `demo-accounting`；實例 #240／資料庫 #238）：`dobtor_accounting`、`dobtor_account_voucher`、`dobtor_account_close`、`dobtor_account_check`、`dobtor_account_asset`、`dobtor_account_payment_request`、`dobtor_account_reconcile`；同庫另有 Dobtor-Report `dobtor_finance_reports`、Uniform-Invoice `dobtor_uniform_invoice`（控制台模組表 2026-11-03；版號以 `ir.module.module` 為準）。
- **admin.corpaas.com**：只有 `dobtor_accounting`（快照 2026-11-03，18.0.3.3.0）。
- 客戶正式機（SIG、蔦燒、駿伸等）各自版本不同，尚未登記 targets。
- ⚠ 跨 repo 整組（Accounting＋`dobtor_uniform_invoice`＋`dobtor_tax_filing`）pt-verify 目前不支援（V2 整組只取「已安裝 ∩ 本 repo」、`--mods` 只收本 repo 模組）；改動會影響 account.move 共同行為時，另對 Uniform-Invoice 跑同等級 V1/V2，報告兩份都附。''',
   v2='--target demo-accounting', v4target='demo-accounting',
   extra='''- demo-accounting 還沒有快照：V2/V3/V4 前先跑 `"$PTV" snapshot demo-accounting`（唯讀：tar 讀原碼＋唯讀交易查已安裝清單）。沒有快照時 V2 會退回「整組＝受測模組」，報告會註明——那不算完成 V2。
- demo-accounting 是控制台部署：`deploy-plan demo-accounting` 只印控制台步驟（同 repo 每個改到的模組各自按下載、資料庫按更新）；部署後查 `ir.module.module.latest_version`，不信控制台「完成」。
- 財會方案案例（`finance_tw_2026_11.json`）的 code 對照在 `feature-map.md`；改到案例覆蓋的行為，要同步更新案例或決策（D-AC-001～010）。'''),
 'Dobtor-Report': dict(wt='Dobtor-Report-worktrees/verify-skill', cases=False, rep='dobtor_finance_reports_voucher',
   intro='財報平台 28 個模組（核心引擎、試算表平台、稅務／資金／資產／合併／IFRS／預算、產業報表）。',
   group='''- **admin.corpaas.com**（目標名 `admin.corpaas.com`）：`dobtor_finance_reports`（快照 18.0.12.4.0）、`dobtor_spreadsheet`（18.0.3.7.1）。
- **demo-accounting**（目標名 `demo-accounting`）：`dobtor_finance_reports`。
- 多數產業／延伸模組（`_tax_tw`、`_treasury_tw`、`_asset_tw`、`_close_tw`、`_voucher` 等）依賴 Accounting 模組；`--mods` 只收本 repo 模組，相依的 Accounting 模組由 addons 路徑自動找到。''',
   v2='--target demo-accounting', v4target='admin.corpaas.com',
   extra='''- 部分報表測試量大（核心 >60 個類別），V1 指定 `--mods` 時預設會加反向相依；只想測單一模組時明確列出、並在報告說明範圍。'''),
 'Uniform-Invoice': dict(wt='Uniform-Invoice-worktrees/verify-skill', cases=True, rep='dobtor_tax_filing',
   intro='台灣統一發票 5 個模組（核心 `dobtor_uniform_invoice`、營業稅申報 `dobtor_tax_filing`、三家加值中心串接 ecpay／ezpay／tradevan）。',
   group='''- **demo-accounting**（目標名 `demo-accounting`）：`dobtor_uniform_invoice`（與 Accounting 七模組同庫）。
- **admin.corpaas.com**：`dobtor_uniform_invoice`（快照 18.0.1.14.0）、`dobtor_uniform_invoice_ezpay`（18.0.1.3.0）。
- ⚠ 與 Accounting 的跨 repo 組合 pt-verify 目前不支援（只收本 repo 模組）；改到 account.move 繼承點時，另對 Accounting 跑同等級驗證並附兩份報告。''',
   v2='--target demo-accounting', v4target='admin.corpaas.com',
   extra='''- `TestTradeVanE2E`（`tradevan_live` 標籤、`-standard`）真的呼叫關貿，缺帳號／私鑰就 skip；pt-verify 的 `--test-tags /模組` 預設不跑它，要實打另外手動跑並在回報說明。
- 財會方案案例（`ui_*`）的 code 對照在 `feature-map.md`。'''),
 'website-user': dict(headnote='本 repo 的 origin/HEAD 指向 `dev-14.0`（不是 18.0），不給的話 V0 會把整個 18.0 的模型都當成「新增」而誤報。', wt='website-user-worktrees/verify-skill', cases=False, rep='dobtor_user_signup',
   intro='前台會員／市集／錢包 27 個模組。',
   group='''- **admin.corpaas.com**（目標名 `admin.corpaas.com`）：11 個——`dobtor_user_apps`、`_contact_info`、`_profile`、`_signup`、`_order`、`_referral`、`_wallet`、`_oauth_manager`、`dobtor_referral_share`、`dobtor_membership`、`dobtor_topup_sale`。
- 市集（`dobtor_marketplace*`）、商會（`dobtor_chamber`）等裝在各客戶實例，尚未登記 targets。
- `prod_overrides.toml` 對 admin.corpaas.com 有一筆 website-user 替代（`dobtor_topup_sale` 找不到 `wallet_pay_form`）：V4 時快照裡的 website-user 會換成本機 `dev-18.0`，報告 `overrides` 會列出。''',
   v2='--target admin.corpaas.com', v4target='admin.corpaas.com',
   extra='''- 很多模組沒有 tests/（見 `feature-map.md`）：這些模組 V1 只證明「裝得起來」，前台行為要另外人工或 tour 驗證，回報時講清楚。'''),
}

def skill(name, d):
    headnote = d.get('headnote', '本 repo 目前就是 `dev-18.0`；寫明是為了不依賴遠端預設分支。')
    return f'''---
name: verify
description: {name} repo 合併前／部署前的驗證步驟——用 pt-verify 跑 V0～V4、看哪些模組正式機會一起裝、回報必附報告路徑。由人決定何時跑；不是自動閘門（不掛 hook、不接 CI）。
---

# {name}：驗證（pt-verify）

{d['intro']}功能 → 測試類別對照見同目錄 `feature-map.md`；已知不穩定測試在 `known_flaky.txt`（工具會自動從失敗清單扣掉）。

## 工具路徑

```bash
PTV=~/Documents/GitHub/ProductivityTools/tools/verify/pt-verify
# 工具還在 feat/verify-tools 分支（尚未合併進 ProductivityTools 主目錄）時改用 worktree：
[ -x "$PTV" ] || PTV=~/Documents/GitHub/ProductivityTools-worktrees/verify-tools/tools/verify/pt-verify
"$PTV" --help    # 說明：同目錄 README.md
```

`<wt>` 是你的 worktree 路徑（例：`~/Documents/GitHub/{d['wt']}`）。不要在主目錄驗證別人正在改的東西。

## 正式環境會一起裝的整組

{d['group']}

目標名對應 `ProductivityTools/tools/verify/targets.toml`。V2 的「整組」＝該目標快照的已安裝清單 ∩ 本 repo 模組（自動算，報告 notes 會列出）。

## 什麼時候跑哪一級

| 時機 | 至少 | 指令範例 |
|---|---|---|
| 改完、合併前 | V0～V2 | `"$PTV" run <wt> --level V0 --base origin/dev-18.0`（省略 `--mods`＝與基準比較有變動的模組） |
| | | `"$PTV" run <wt> --level V1 --base origin/dev-18.0 --mods {d['rep']}`（全新庫 `-i`＋該模組測試，自動加本 repo 反向相依） |
| | | `"$PTV" run <wt> --level V2 --base origin/dev-18.0 {d['v2']}`（加上正式機整組一起裝） |
| 部署前 | V3 | `"$PTV" run <wt> --level V3 --base prod:{d['v4target']}`（先裝正式機版本再 `-u` 換新版，報告 migrations_ran） |
| 正式機已安裝、且本機版號與正式機不同 | V4 | `"$PTV" run <wt> --level V4 --target {d['v4target']}`（正式機整套原碼樹演練，套用 prod_overrides.toml） |

- **V0～V2 一律給 `--base origin/dev-18.0`**：省略時工具用 origin/HEAD，{headnote}
- 判斷「正式機已安裝且版本不同」：`"$PTV" run <wt> --level V0 --base prod:<目標>` 會在報告列出與正式機原碼不同（或正式機沒有）的模組；或直接比對快照 `~/Library/Caches/corpaas-kb/prod/<目標>/<日期>/installed.json` 與 manifest 版號。
- 快照過舊或沒有：`"$PTV" snapshot <目標>`（唯讀）。正式機寫入（V5 部署）只由使用者用 `!` 執行 `deploy-plan` 產生的腳本。
{d['extra']}

## 判定與回報

- 最後一行固定是 `<報告 .md 路徑> <PASS|FAIL|BLOCKED>`（結束碼 0／1／2）。報告在 `~/Library/Caches/corpaas-kb/verify-reports/<repo>/<時間>-<等級>.md`（同名 `.json`）。
- **回報一律附報告路徑與 verdict**；沒有報告的「測試全過」不採信。BLOCKED 要寫出原因（缺快照、相依找不到…），不能當 PASS。
- 只看「新增失敗」：失敗清單先扣 `known_flaky.txt`，再與基準版本同等級比對。新發現的不穩定測試，確認基準也會失敗後才加進 `known_flaky.txt`（附原因與來源報告路徑）。
- 有 `tests/` 的模組卻 0 項測試會判 FAIL（多半是 `tests/__init__.py` 沒匯入）。
'''

HDR = '''# {name}：功能地圖

模組 → 關鍵流程（表單表頭的狀態列／主要按鈕）→ 呼叫該按鈕的測試類別{case_hdr}。

- 產生方式：{date} 在 `{wt}`（{sha}）解析各模組 `__manifest__.py`、views 的 `<header>`，再 grep `tests/` 找「方法名 + `(`」出現在哪些測試類別。依方法名比對，同名方法（例如 `action_post`）可能配到別的模型的測試；「（無測試直接呼叫）」只代表沒有直接呼叫，不代表沒有覆蓋。
- 只列含 `test_` 方法的類別（基底類別不列）。改了流程或新增測試後請順手更新本檔。
{case_note}
'''

def main():
    for name, d in R.items():
        wt = os.path.join(GH, d['wt'])
        sha = subprocess.check_output(['git', '-C', wt, 'rev-parse', '--short', 'HEAD'], text=True).strip()
        args = [sys.executable, os.path.join(S, 'fmap.py'), wt] + ([CASES] if d['cases'] else [])
        body = subprocess.check_output(args, text=True)
        out = os.path.join(wt, '.claude', 'skills', 'verify')
        os.makedirs(out, exist_ok=True)
        case_hdr = ' → 財會方案知識案例 code' if d['cases'] else ''
        case_note = ('- 知識案例來源：`~/Documents/GitHub/ProductivityTools/tools/knowledge/cases/finance_tw_2026_11.json`（ProductivityTools 6e34933）。'
                     '表格的案例欄依案例的 `when` 方法＋模型對到按鈕；「測試類別」行的案例依案例 `source_ref` 的測試檔對到。\n') if d['cases'] else ''
        with open(os.path.join(out, 'feature-map.md'), 'w', encoding='utf-8') as f:
            f.write(HDR.format(name=name, case_hdr=case_hdr, date='2026-11-03', wt=d['wt'], sha=sha, case_note=case_note) + '\n' + body)
        with open(os.path.join(out, 'SKILL.md'), 'w', encoding='utf-8') as f:
            f.write(skill(name, d))
        print('wrote', out)
main()
