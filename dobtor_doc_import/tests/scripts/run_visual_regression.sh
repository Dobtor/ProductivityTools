#!/usr/bin/env bash
# run_visual_regression.sh — 視覺回歸 PR block wrapper
#
# 包裝 compare_fixtures.cjs，加上 threshold 判定：
#   平均 diff > MEAN_THRESHOLD (預設 5%) → exit 1
#   最差 diff > WORST_THRESHOLD (預設 10%) → exit 1
#   錯誤 fixture 數 > MAX_ERRORS (預設 0) → exit 1
#
# 用法：
#   bash tests/scripts/run_visual_regression.sh                  # 全跑
#   bash tests/scripts/run_visual_regression.sh --category 03_complex_table
#   MEAN_THRESHOLD=0.03 bash tests/scripts/run_visual_regression.sh   # 嚴格 3%
#
# 退出碼：
#   0  — 通過（或 Phase F 基線蒐集模式 PASS_THRESHOLD=1.0）
#   1  — diff 超標 / 有錯誤 fixture
#   2  — 設定 / 環境問題
#
# 環境變數：
#   MEAN_THRESHOLD    平均 diff% 上限（預設 0.05 = 5%）
#   WORST_THRESHOLD   最差 diff% 上限（預設 0.10 = 10%）
#   MAX_ERRORS        允許的錯誤 fixture 數（預設 0）
#   ODOO_URL / ODOO_DB / ODOO_LOGIN / ODOO_PASSWORD（傳給 compare_fixtures.cjs）
#   PHASE_F_BASELINE  設為 1 時不做 threshold 判定（純基線蒐集）
#
# ☠️ **這些閥門不是驗收門檻**（2026-10-09 稽核階段 7）
#
#   主規畫書 §2.2 要求「pixelmatch 對 LibreOffice headless 差異率 **<2%**」。
#   而這裡的預設是 MEAN 5% / WORST 10%，比需求鬆 2.5 倍以上；
#   v14 pipeline 的 --max-diff 預設更是 0.5（50%），鬆 25 倍。
#
#   這些值的用途是「**不要退步**」——擋的是今天比昨天爛。
#   把它們當成驗收門檻會得出「VR 綠了所以符合需求」這個錯誤結論，
#   而實測 per-page mean 是 7.89%，距 §2.2 差約 4 倍。
#
#   逐條對照見 dobtor_doc_editor/docs/REQUIREMENTS_CONFORMANCE.md。

set -euo pipefail

cd "$(dirname "$0")/../.."

MEAN_THRESHOLD="${MEAN_THRESHOLD:-0.05}"
WORST_THRESHOLD="${WORST_THRESHOLD:-0.10}"
MAX_ERRORS="${MAX_ERRORS:-0}"
PHASE_F_BASELINE="${PHASE_F_BASELINE:-0}"

JSON_OUT="/tmp/visual_regression_$$.json"
trap 'rm -f "$JSON_OUT"' EXIT

echo "=== Visual Regression PR Block Wrapper ==="
echo "MEAN_THRESHOLD  = ${MEAN_THRESHOLD}"
echo "WORST_THRESHOLD = ${WORST_THRESHOLD}"
echo "MAX_ERRORS      = ${MAX_ERRORS}"
echo "PHASE_F_BASELINE= ${PHASE_F_BASELINE}"
echo ""

if ! command -v node >/dev/null 2>&1; then
    echo "✗ node not found in PATH" >&2
    exit 2
fi

if [ ! -f tests/scripts/compare_fixtures.cjs ]; then
    echo "✗ tests/scripts/compare_fixtures.cjs missing" >&2
    exit 2
fi

# 跑視覺回歸並輸出 JSON
node tests/scripts/compare_fixtures.cjs \
    --json-out "$JSON_OUT" \
    "$@"

if [ ! -f "$JSON_OUT" ]; then
    echo "✗ compare_fixtures.cjs did not produce JSON output" >&2
    exit 2
fi

# Phase F 基線模式不做 threshold 判定
if [ "$PHASE_F_BASELINE" = "1" ]; then
    echo ""
    echo "Phase F baseline mode: skipping threshold gate"
    exit 0
fi

# 用 python3 解析 JSON 做 threshold 判定（避免依賴 jq）
python3 - "$JSON_OUT" "$MEAN_THRESHOLD" "$WORST_THRESHOLD" "$MAX_ERRORS" <<'PYEOF'
import json
import sys

json_path = sys.argv[1]
mean_threshold = float(sys.argv[2])
worst_threshold = float(sys.argv[3])
max_errors = int(sys.argv[4])

with open(json_path) as f:
    results = json.load(f)

errors = [r for r in results if r.get('error')]
ok = [r for r in results if not r.get('error') and r.get('meanDiff') is not None]

print(f"\n=== Threshold Gate ===")
print(f"Total fixtures   : {len(results)}")
print(f"Successful       : {len(ok)}")
print(f"Errors           : {len(errors)}")

failures = []

# ☠️ 「一個 fixture 都沒比到」不可以算通過。
#    原本：results 是空陣列 → errors=[] 、ok=[] → failures=[] →
#    印出「✓ Visual regression PASSED」並 exit 0。打錯一個 --category
#    、fixture 目錄搶不到、或 compare_fixtures.cjs 寫出空 JSON，
#    都會走到這條路——閘门在沒量到任何東西的情況下說通過。
#    （跟本模組今天反覆抓到的失效模式是同一個：
#      檢查存在、但它的判決空洞。）
if not results:
    msg = "compare_fixtures.cjs 回了 0 筆結果——這道閘門沒有量到任何東西"
    print(f"✗ {msg}")
    failures.append(msg)
elif not ok:
    msg = f"{len(results)} 筆結果裡沒有任何一筆成功算出 meanDiff"
    print(f"✗ {msg}")
    failures.append(msg)

if len(errors) > max_errors:
    msg = f"errors {len(errors)} > MAX_ERRORS {max_errors}"
    print(f"✗ {msg}")
    for r in errors[:5]:
        print(f"  - {r.get('fixture')}: {r.get('error')}")
    failures.append(msg)

if ok:
    diffs = [r['meanDiff'] for r in ok]
    avg = sum(diffs) / len(diffs)
    worst = max(diffs)
    worst_fixture = max(ok, key=lambda r: r['meanDiff'])

    print(f"Average diff     : {avg*100:.2f}% (threshold {mean_threshold*100:.0f}%)")
    print(f"Worst diff       : {worst*100:.2f}% (threshold {worst_threshold*100:.0f}%) — {worst_fixture['fixture']}")

    if avg > mean_threshold:
        msg = f"average diff {avg*100:.2f}% > MEAN_THRESHOLD {mean_threshold*100:.0f}%"
        print(f"✗ {msg}")
        failures.append(msg)
    if worst > worst_threshold:
        msg = f"worst diff {worst*100:.2f}% > WORST_THRESHOLD {worst_threshold*100:.0f}% ({worst_fixture['fixture']})"
        print(f"✗ {msg}")
        failures.append(msg)

if failures:
    print(f"\n✗ Visual regression FAILED ({len(failures)} gate(s))")
    sys.exit(1)

print(f"\n✓ Visual regression PASSED")
sys.exit(0)
PYEOF
