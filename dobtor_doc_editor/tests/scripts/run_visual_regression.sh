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
    echo "::error::node not found in PATH" >&2
    exit 2
fi

if [ ! -f tests/scripts/compare_fixtures.cjs ]; then
    echo "::error::tests/scripts/compare_fixtures.cjs missing" >&2
    exit 2
fi

# 跑視覺回歸並輸出 JSON
node tests/scripts/compare_fixtures.cjs \
    --json-out "$JSON_OUT" \
    "$@"

if [ ! -f "$JSON_OUT" ]; then
    echo "::error::compare_fixtures.cjs did not produce JSON output" >&2
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

if len(errors) > max_errors:
    msg = f"errors {len(errors)} > MAX_ERRORS {max_errors}"
    print(f"::error::{msg}")
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
        print(f"::error::{msg}")
        failures.append(msg)
    if worst > worst_threshold:
        msg = f"worst diff {worst*100:.2f}% > WORST_THRESHOLD {worst_threshold*100:.0f}% ({worst_fixture['fixture']})"
        print(f"::error::{msg}")
        failures.append(msg)

if failures:
    print(f"\n::error::Visual regression FAILED ({len(failures)} gate(s))")
    sys.exit(1)

print(f"\n✓ Visual regression PASSED")
sys.exit(0)
PYEOF
