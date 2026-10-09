#!/usr/bin/env bash
# run_done_check.sh — 「完成了嗎」的單一判決。
#
# 判準清單與每條的理由在 docs/DONE_CRITERIA.md。這支腳本必須實作**同一組 ID**
# ——由 tests/test_done_criteria.py 強制（文件與腳本的 ID 集合不一致就紅）。
#
# 退出碼：
#   0  全部判準通過
#   1  有判準沒過
#   2  環境不具備（容器沒跑、缺工具）——**不是通過**
#
# ☠️ 為什麼 2 要跟 0 分開：本模組一整天抓到的失效模式就是「沒量到東西卻說
#    通過」。環境不具備時必須明說，不可以沉默地少跑幾條然後回 0。
#
# 用法：
#   make done                      # 全部
#   make done DONE_SKIP=tour       # 跳過指定 ID（會在摘要裡標成 SKIP 並讓退出碼 = 2）
set -u

cd "$(dirname "$0")/../.."          # → dobtor_doc_editor/
CORE_DIR="$PWD"
IMPORT_DIR="$(cd .. && pwd)/dobtor_doc_import"
REPO_ROOT="$(cd .. && pwd)"

ODOO_CONTAINER="${ODOO_CONTAINER:-qcodoo}"
PG_CONTAINER="${PG_CONTAINER:-qcpg}"
PG_HOST="${PG_HOST:-$PG_CONTAINER}"
ODOO_DB="${ODOO_DB:-docedit}"
STANDALONE_DB="${STANDALONE_DB:-doneonly}"
ADDONS_PATH="${ADDONS_PATH:-/usr/lib/python3/dist-packages/odoo/addons,/mnt/dm,/mnt/ds,/mnt/pt,/mnt/fw}"
PG_ARGS="--db_host=$PG_HOST --db_user=odoo --db_password=odoo"
COMMON="--without-demo= --workers=0 --max-cron-threads=0 --stop-after-init"
DONE_SKIP="${DONE_SKIP:-}"

PASS=(); FAIL=(); SKIP=()

# ☠️ 失敗的 log 要保留得住。第一版每條判準都寫固定檔名（/tmp/done_core_tests.log），
#    所以下一次跑成功就把前一次失敗的現場覆寫掉。2026-10-09 稽核階段 8 就碰上了：
#    core-tests 紅了一次，而我查 log 時已經被第二次執行覆寫——證據沒了。
#    「偶發失敗出現的當下要先把 log 存下來」是本模組自己的教訓，而這支腳本違反了它。
TS="$(date +%Y%m%d-%H%M%S)"
keep_log() {
    # $1 = 判準 id、$2 = 從哪份 log 保留
    local dest="/tmp/done_FAILED_$1_$TS.log"
    [ -f "$2" ] && cp "$2" "$dest" && echo "        證據已保留：$dest"
}

ok()   { PASS+=("$1"); printf '  \033[32m✓\033[0m %-24s %s\n' "$1" "${2:-}"; }
bad()  { FAIL+=("$1"); printf '  \033[31m✗\033[0m %-24s %s\n' "$1" "${2:-}"; }
skip() { SKIP+=("$1"); printf '  \033[33m–\033[0m %-24s %s\n' "$1" "${2:-}"; }

skipped() { case " $DONE_SKIP " in *" $1 "*) return 0;; *) return 1;; esac; }

# 從 Odoo 的 log 抽出「0 failed, 0 error(s) of N tests」且 N > 0。
# ☠️ 判準是 [1-9][0-9]*——打錯 tag 時 Odoo 回「of 0 tests」，那不算過。
assert_odoo_result() {
    local id="$1" log="$2"
    local line
    line=$(grep -a 'tests\.result' "$log" | tail -1)
    if [ -z "$line" ]; then
        bad "$id" "log 裡找不到 tests.result ——測試可能根本沒跑"
        return
    fi
    if echo "$line" | grep -aqE ': 0 failed, 0 error\(s\) of [1-9][0-9]* tests'; then
        ok "$id" "$(echo "$line" | grep -aoE 'of [0-9]+ tests')"
    else
        bad "$id" "$(echo "$line" | sed 's/^.*tests\.result: //')"
        # 紅的那一刻就把 log 存起來——Odoo 測試最會偶發，而下一次執行會覆寫它
        keep_log "$id" "$log"
        grep -a 'FAIL:\|ERROR: Test\|ERROR: test' "$log" | head -5 | sed 's/^/        /'
    fi
}

echo "=== 完工判準（docs/DONE_CRITERIA.md）==="

# ── 環境 ──────────────────────────────────────────────────────────────────
for c in "$ODOO_CONTAINER" "$PG_CONTAINER"; do
    docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$c" || {
        echo "✗ 環境不具備：容器 $c 沒在跑。"
        echo "  （這是退出碼 2，不是通過——見 docs/DONE_CRITERIA.md）"
        exit 2
    }
done

# ── git-clean / git-pushed ────────────────────────────────────────────────
if skipped git-clean; then skip git-clean "DONE_SKIP"; else
    DIRTY=$(git -C "$REPO_ROOT" status --porcelain)
    if [ -z "$DIRTY" ]; then
        ok git-clean
    else
        # ☠️ 要列出**是哪幾個檔案**，不是只說「有 N 個變更」。
        #    2026-10-09 這條判準紅過一次而事後重现不出來，就是因為訊息
        #    只印數量。闘門失敗時必須自己說出原因——這是本模組
        #    今天在 session 探針上學到的同一件事。
        #
        #    也要知道：`make done` 自己會跑 `npm run build:all`
        #    （artifacts-reproducible）。若那個建置**不是** reproducible，
        #    這一輮的 artifacts-reproducible 會紅，而**下一輮的 git-clean
        #    也會紅**。那不是 bug，是同一件事的兩個症狀。
        bad git-clean "$(echo "$DIRTY" | wc -l | tr -d ' ') 個未提交的變更"
        echo "$DIRTY" | head -10 | sed 's/^/        /'
        [ "$(echo "$DIRTY" | wc -l)" -gt 10 ] && echo "        …（只列前 10 個）"
    fi
fi

if skipped git-pushed; then skip git-pushed "DONE_SKIP"; else
    BR=$(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD)
    if git -C "$REPO_ROOT" rev-parse --verify -q "origin/$BR" >/dev/null; then
        AHEAD=$(git -C "$REPO_ROOT" rev-list --count "origin/$BR..HEAD")
        [ "$AHEAD" = "0" ] && ok git-pushed || bad git-pushed "$AHEAD 個提交還沒推"
    else
        bad git-pushed "找不到 origin/$BR"
    fi
fi

# ── core-static / import-static ───────────────────────────────────────────
if skipped core-static; then skip core-static "DONE_SKIP"; else
    if make -C "$CORE_DIR" ci-all >/tmp/done_core_static.log 2>&1; then
        ok core-static
    else
        bad core-static "見 /tmp/done_core_static.log"
        keep_log core-static /tmp/done_core_static.log
    fi
fi

if skipped import-static; then skip import-static "DONE_SKIP"; else
    if make -C "$IMPORT_DIR" ci-all >/tmp/done_import_static.log 2>&1; then
        ok import-static "typecheck + vitest + 三產物"
    else
        bad import-static "見 /tmp/done_import_static.log"
        keep_log import-static /tmp/done_import_static.log
    fi
fi

# ── core-tests ────────────────────────────────────────────────────────────
if skipped core-tests; then skip core-tests "DONE_SKIP"; else
    docker exec "$ODOO_CONTAINER" odoo -d "$ODOO_DB" $PG_ARGS \
        --addons-path="$ADDONS_PATH" -u dobtor_doc_editor \
        --test-enable --test-tags '/dobtor_doc_editor' \
        $COMMON --http-port=8099 --log-level=test >/tmp/done_core_tests.log 2>&1
    assert_odoo_result core-tests /tmp/done_core_tests.log
fi

# ── import-tests ──────────────────────────────────────────────────────────
if skipped import-tests; then skip import-tests "DONE_SKIP"; else
    docker exec "$ODOO_CONTAINER" odoo -d "$ODOO_DB" $PG_ARGS \
        --addons-path="$ADDONS_PATH" -u dobtor_doc_import \
        --test-enable --test-tags '/dobtor_doc_import' \
        $COMMON --http-port=8099 --log-level=test >/tmp/done_import_tests.log 2>&1
    assert_odoo_result import-tests /tmp/done_import_tests.log
fi

# ── core-standalone ───────────────────────────────────────────────────────
if skipped core-standalone; then skip core-standalone "DONE_SKIP"; else
    docker exec "$PG_CONTAINER" psql -U odoo -d postgres \
        -c "DROP DATABASE IF EXISTS $STANDALONE_DB;" >/dev/null 2>&1
    docker exec "$ODOO_CONTAINER" odoo -d "$STANDALONE_DB" $PG_ARGS \
        --addons-path="$ADDONS_PATH" -i sale,account,stock,purchase \
        $COMMON --http-port=8096 --log-level=warn >/dev/null 2>&1
    docker exec "$ODOO_CONTAINER" odoo -d "$STANDALONE_DB" $PG_ARGS \
        --addons-path="$ADDONS_PATH" -i dobtor_doc_editor \
        --test-enable --test-tags '/dobtor_doc_editor' \
        $COMMON --http-port=8096 --log-level=test >/tmp/done_standalone.log 2>&1
    STATE=$(docker exec "$PG_CONTAINER" psql -U odoo -d "$STANDALONE_DB" -t -A -c \
        "select state from ir_module_module where name='dobtor_doc_import';" 2>/dev/null | tr -d '[:space:]')
    if [ "$STATE" != "uninstalled" ]; then
        bad core-standalone "dobtor_doc_import 在獨立庫裡的狀態是 '$STATE'（應為 uninstalled）"
    else
        assert_odoo_result core-standalone /tmp/done_standalone.log
    fi
fi

# ── tour ──────────────────────────────────────────────────────────────────
if skipped tour; then skip tour "DONE_SKIP"; else
    if bash "$CORE_DIR/tests/scripts/run_local_rig.sh" tour >/tmp/done_tour.log 2>&1; then
        ok tour "$(grep -ao '\[[0-9]*/[0-9]*\] Tour [a-z_]*' /tmp/done_tour.log | tail -1)"
    else
        bad tour "見 /tmp/done_tour.log"
        keep_log tour /tmp/done_tour.log
    fi
fi

# ── artifacts-present ─────────────────────────────────────────────────────
ARTIFACTS=(
    "$IMPORT_DIR/static/src/lib/canvas_editor/canvas-editor-custom.umd.js"
    "$IMPORT_DIR/tools/dist/parse_docx_cli.cjs"
    "$IMPORT_DIR/tools/dist/visual_regression_pipeline.iife.js"
)
if skipped artifacts-present; then skip artifacts-present "DONE_SKIP"; else
    MISSING=()
    for a in "${ARTIFACTS[@]}"; do [ -f "$a" ] || MISSING+=("$(basename "$a")"); done
    [ ${#MISSING[@]} -eq 0 ] && ok artifacts-present "3 個" \
        || bad artifacts-present "缺 ${MISSING[*]}"
fi

# ── artifacts-reproducible ────────────────────────────────────────────────
if skipped artifacts-reproducible; then skip artifacts-reproducible "DONE_SKIP"; else
    if (cd "$IMPORT_DIR" && npm run build:all >/tmp/done_build.log 2>&1); then
        DIRTY=$(git -C "$REPO_ROOT" status --porcelain -- dobtor_doc_import/static/src/lib dobtor_doc_import/tools/dist)
        [ -z "$DIRTY" ] && ok artifacts-reproducible "重建後 byte-identical" \
            || bad artifacts-reproducible "重建後產物與版控不一致：$(echo "$DIRTY" | tr '\n' ' ')"
    else
        bad artifacts-reproducible "build:all 失敗，見 /tmp/done_build.log"
    fi
fi

# ── no-public-routes ──────────────────────────────────────────────────────
# ☠️ 用 AST 不用 grep：同一類誤判在本模組出現過三次（最後一次把 docstring
#    裡的文字也數進去了）。
if skipped no-public-routes; then skip no-public-routes "DONE_SKIP"; else
    PUB=$(cd "$REPO_ROOT" && python3 - <<'PY'
import ast, pathlib
out = []
for mod in ('dobtor_doc_editor', 'dobtor_doc_import'):
    for f in sorted(pathlib.Path(mod, 'controllers').rglob('*.py')):
        for node in ast.walk(ast.parse(f.read_text(encoding='utf8'))):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for d in node.decorator_list:
                if not isinstance(d, ast.Call):
                    continue
                if (getattr(d.func, 'attr', None) or getattr(d.func, 'id', None)) != 'route':
                    continue
                kw = {k.arg: (k.value.value if isinstance(k.value, ast.Constant) else '?')
                      for k in d.keywords}
                if kw.get('auth', 'user') == 'public':
                    out.append('%s::%s' % (f.name, node.name))
print(' '.join(out))
PY
)
    [ -z "$PUB" ] && ok no-public-routes "0 條" || bad no-public-routes "還有：$PUB"
fi

# ── upgrade-path ──────────────────────────────────────────────────────────
if skipped upgrade-path; then skip upgrade-path "DONE_SKIP"; else
    if bash "$CORE_DIR/tests/scripts/run_upgrade_check.sh" >/tmp/done_upgrade.log 2>&1; then
        ok upgrade-path "兩支 migration 都執行且改到資料"
    else
        RC=$?
        if [ "$RC" = "2" ]; then
            skip upgrade-path "環境不具備（見 /tmp/done_upgrade.log）"
        else
            bad upgrade-path "見 /tmp/done_upgrade.log"
            keep_log upgrade-path /tmp/done_upgrade.log
        fi
    fi
fi

# ── 判決 ──────────────────────────────────────────────────────────────────
echo
echo "通過 ${#PASS[@]} / 沒過 ${#FAIL[@]} / 跳過 ${#SKIP[@]}"
# ☠️ 判準是「PASS 與 FAIL **都**空」才叫沒跑成。第一版只看 PASS，於是
#    「只跑了一條而且它失敗」會印出「一條判準都沒跑成」——那句話不對，
#    而且會蓋掉真正的失敗原因。2026-10-09 階段 8 的負向驗證抓到的。
if [ ${#PASS[@]} -eq 0 ] && [ ${#FAIL[@]} -eq 0 ]; then
    echo "✗ 一條判準都沒跑成（全部被跳過或環境不具備）——這不是通過。"
    exit 2
fi
if [ ${#FAIL[@]} -gt 0 ]; then
    echo "✗ 沒完成。沒過的判準：${FAIL[*]}"
    exit 1
fi
if [ ${#SKIP[@]} -gt 0 ]; then
    echo "– 其餘通過，但有判準被跳過：${SKIP[*]}（DONE_SKIP）"
    echo "  跳過的判準不算通過，所以退出碼是 2 而不是 0。"
    exit 2
fi
echo "✓ 完成：${#PASS[@]} 條判準全部通過。"
exit 0
