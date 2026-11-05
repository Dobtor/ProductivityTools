"""清除方案知識與已發佈手冊，從零重跑（不可復原）。

    python3 tools/knowledge/reset_knowledge.py 13 14          # 試跑：全部做一遍、印出筆數、最後回滾
    python3 tools/knowledge/reset_knowledge.py 13 14 --yes    # 真的清（含刪說明庫資料庫）
        # 方案有進行中的說明書製作計畫時會擋下，要清加 --force-active-plans；清完會在方案留言
    python3 tools/knowledge/reset_knowledge.py 13 14 --outputs-only [--yes]
        # 只清產出（截圖腳本、截圖、文章、步驟、教學、缺口、已發佈手冊），保留已核准的盤點、情境、能力、流程
    python3 tools/knowledge/reset_knowledge.py 13 14 --code [--yes]
        # 連程式知識（模組摘要、段落、結論）一起清，只留程式碼版本（已抽出的官方原碼）：程式知識格式改版後重測用
    python3 tools/knowledge/reset_knowledge.py 13 14 --all [--yes]
        # 全部清、什麼都不留：含 --code，再加 AI 呼叫／更新／驗收紀錄、環境規則、角色、示範資料包，
        # 以及行銷（宣稱、卡片、本期新增）與知識交換（發佈清單）；只留程式碼版本與交換對端設定
    python3 tools/knowledge/reset_knowledge.py 13 14 --all [--yes]
        # 全部清、什麼都不留：含 --code，再加上 AI 呼叫／更新／驗收紀錄、環境規則、角色、示範資料包，
        # 以及行銷（宣稱、卡片、本期新增）與知識交換（發佈清單）；只留程式碼版本與交換對端設定

保留：AI 呼叫／更新／驗收紀錄（比較用）、環境規則、角色範本、示範資料包、程式知識（跟映像版本綁定）。
方案上的設定（自動化等級、門檻）保留；方案上算出來的狀態（方案檔案、範圍快照、指紋）清掉。
整段在同一個交易裡跑：任何一步失敗就全部回滾。
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MARK = '__RESET__:'

#: 不清的模型（比較用的歷史、機制本身、跟映像綁定的程式知識）
KEEP = ['corpaas.knowledge.ai.call', 'corpaas.knowledge.run', 'corpaas.knowledge.acceptance_log',
        'corpaas.knowledge.rule', 'corpaas.knowledge.role', 'corpaas.knowledge.seed_pack',
        'corpaas.knowledge.code_tree', 'corpaas.knowledge.code_def', 'corpaas.knowledge.code_fact',
        'corpaas.knowledge.module_summary']
#: --outputs-only 另外保留的（盤點與已核准的提案：重跑不必再人工核准一次）
CATALOG = ['corpaas.knowledge.feature', 'corpaas.knowledge.feature.class', 'corpaas.knowledge.feature.entry',
           'corpaas.knowledge.capability', 'corpaas.knowledge.scenario', 'corpaas.knowledge.flow',
           'corpaas.knowledge.flow.step', 'corpaas.knowledge.flow.transition', 'corpaas.knowledge.selection',
           'corpaas.knowledge.toggle', 'corpaas.knowledge.toggle.state', 'corpaas.knowledge.coverage',
           'corpaas.knowledge.official_doc', 'corpaas.knowledge.fingerprint', 'corpaas.knowledge.event',
           'corpaas.knowledge.sandbox',
           # 說明書製作計畫（決策紀錄）與上線後意見：只清產出時保留
           'corpaas.knowledge.plan', 'corpaas.knowledge.plan.item', 'corpaas.knowledge.scope_line',
           'corpaas.knowledge.check', 'corpaas.knowledge.source_module', 'corpaas.knowledge.module_relation',
           'corpaas.knowledge.feedback', 'corpaas.knowledge.feedback.session']
#: --code 另外清掉的程式知識；程式碼版本（code_tree：已抽出的官方原碼，跟映像版本綁定、內容不會變）照樣保留
CODE = ['corpaas.knowledge.code_def', 'corpaas.knowledge.code_fact', 'corpaas.knowledge.module_summary']
#: --all 仍保留的：程式碼版本（官方原碼，跟映像綁定）與交換對端主控台（連線設定，不是知識）
ALL_KEEP = ['corpaas.knowledge.code_tree', 'corpaas.knowledge.exchange.peer']
#: 預設只清核心與說明書模組；--all 再加行銷與知識交換模組（建議書等業務資料一律不動）
BASE_MODULES = ['dobtor_corpaas_knowledge', 'dobtor_corpaas_knowledge_manual']
ALL_MODULES = BASE_MODULES + ['dobtor_corpaas_knowledge_marketing', 'dobtor_corpaas_knowledge_exchange']
#: 方案上要清掉的「算出來的狀態」
PKG_RESET = ['knowledge_cost_plan_at', 'knowledge_cost_plan_html', 'knowledge_fp_image', 'knowledge_fp_manifest',
             'knowledge_image_digest', 'knowledge_last_refresh', 'knowledge_last_token', 'knowledge_pending_full',
             'knowledge_pending_reason', 'knowledge_profile_json', 'knowledge_scope_snapshot']

SCRIPT = r'''
import json
DRY = %(dry)r
KEEP = set(%(keep)r)
PKGS = %(pkgs)r
PKG_RESET = %(reset)r
MARK = %(mark)r
RESET_MODULES = tuple(%(modules)r)
env = env(context=dict(env.context, active_test=False, tracking_disable=True, mail_notrack=True))
out = {'deleted': {}, 'dropped': [], 'errors': []}
busy = env['corpaas.knowledge.run'].sudo().search([('state', '=', 'running')])
if busy:
    raise SystemExit('還有進行中的更新 %%s：先停止' %% busy.ids)
# 1. 說明庫：真的清時先刪資料庫（試跑不刪；只清產出時說明庫留著）
for sb in env['corpaas.knowledge.sandbox'].sudo().search([('state', '!=', 'dropped')]) if 'corpaas.knowledge.sandbox' not in KEEP else []:
    if not DRY:
        try:
            sb.drop()
            out['dropped'].append(sb.db_name)
        except Exception as e:
            out['errors'].append('drop %%s: %%s' %% (sb.db_name, e))
# 2. 已發佈手冊：知識管理的 channel（含 slide）、知識產生的流程圖
chans = env['slide.channel'].sudo().search([('knowledge_managed', '=', True)])
slides = env['slide.slide'].sudo().search([('channel_id', 'in', chans.ids)])
out['deleted']['slide.slide'] = len(slides)
out['deleted']['slide.channel'] = len(chans)
if 'bpmn.diagram' in env and 'knowledge_flow_id' in env['bpmn.diagram']._fields:
    diags = env['bpmn.diagram'].sudo().search(['|', '|', ('knowledge_flow_id', '!=', False),
        ('knowledge_capability_id', '!=', False), ('knowledge_package_id', '!=', False)])
    out['deleted']['bpmn.diagram'] = len(diags)
    diags.unlink()
slides.unlink()
chans.unlink()
# 3. 知識模型：除了保留的全部清
# ☠️ 不能用 TRUNCATE ... CASCADE：它會把「有外鍵指過來的表」整張清空（全站 slide、流程圖、驗收紀錄），
#    不是只清指過來的那幾列。用逐表 DELETE：每個外鍵照它自己的規則（設空值／串聯）處理那幾列；
#    被 restrict 擋住的下一輪再刪，直到沒有進展。
# ★ 只清核心與說明書模組自己定義的模型：建議書模組（建議書、案件、開發項目…）同樣是 corpaas.knowledge.*，
#   那是業務資料，清除知識產出時不能動
models = sorted(m for m in env.registry if m.startswith('corpaas.knowledge.') and m not in KEEP
                and not env[m]._abstract and env[m]._auto and env[m]._original_module in RESET_MODULES)
for m in models:
    env.cr.execute('SELECT count(*) FROM "%%s"' %% env[m]._table)
    n = env.cr.fetchone()[0]
    if n:
        out['deleted'][m] = n
left = list(models)
for _pass in range(10):
    stuck = []
    for m in left:
        try:
            with env.cr.savepoint():
                if m == 'corpaas.knowledge.revision':
                    # ★ 保留模型（示範資料包等）的修訂要留著：上線版內容存在修訂裡，刪了資料包就沒有核准版
                    #   ☠️ 實機（2026-10-11）：資料包留著、修訂全刪，說明庫建不起來「還沒有核准過的版本」
                    env.cr.execute('DELETE FROM "%%s" WHERE res_model NOT IN %%%%s' %% env[m]._table, [tuple(KEEP)])
                else:
                    env.cr.execute('DELETE FROM "%%s"' %% env[m]._table)
        except Exception as e:
            stuck.append(m)
            last = str(e)[:200]
    if not stuck or len(stuck) == len(left):
        left = stuck
        break
    left = stuck
if left:
    raise SystemExit('刪不掉：%%s（%%s）' %% (left, last))
# 截圖、素材的附件
att = env['ir.attachment'].sudo().search([('res_model', 'in', models)])
out['deleted']['ir.attachment'] = len(att)
att.unlink()
# 程式碼版本：抽原碼失敗的那幾筆清掉「上次嘗試」，重跑時馬上再抽（不等一天）
if 'corpaas.knowledge.code_tree' in env:
    env['corpaas.knowledge.code_tree'].sudo().search([('core_path', 'in', [False, ''])]).write({'core_tried': False})
# 4. 方案上算出來的狀態
pk = env['infrastructure.solution.package'].sudo().browse(PKGS).exists()
pk.write({f: False for f in PKG_RESET if f in pk._fields})
env.invalidate_all()
# 保留的模型確認沒被串聯刪掉
out['kept'] = {m: env[m].sudo().search_count([]) for m in KEEP if m in env}
if DRY:
    env.cr.rollback()
else:
    env.cr.commit()
print(MARK + json.dumps(out, ensure_ascii=False, default=str))
'''


def setting(key):
    sys.path.insert(0, HERE)
    from rpc import _setting
    return _setting(key)


ACTIVE_PLAN_STATES = ('ledger', 'readiness', 'blocked', 'draft', 'review', 'approved', 'expanding', 'canary',
                      'running')


def active_plans(pkgs):
    """這些方案進行中的計畫：['方案 23：計畫 30（canary）']。讀不到就當沒有（不擋）。"""
    sys.path.insert(0, HERE)
    try:
        from rpc import ro
        rows = ro('corpaas.knowledge.plan', 'search_read',
                  [('package_id', 'in', pkgs), ('state', 'in', list(ACTIVE_PLAN_STATES))],
                  fields=['package_id', 'state', 'version'])
    except Exception:  # noqa: BLE001
        return []
    return ['方案 %s：計畫 %s（v%s，%s）' % (r['package_id'][0], r['id'], r['version'], r['state']) for r in rows]


def note_reset(pkgs, outputs_only, full):
    """清除後在方案留言：誰、清了什麼（別的工作階段與使用者才看得到發生過）。"""
    sys.path.insert(0, HERE)
    try:
        from rpc import rw
        what = '全部清（含紀錄與設定）' if full else ('只清產出' if outputs_only else '清除方案知識與已發佈手冊')
        rw('infrastructure.solution.package', 'message_post', pkgs, unsafe=True,
           body='tools/knowledge/reset_knowledge.py 已執行：%s。若不是你要的，請找執行的人。' % what)
    except Exception as e:  # noqa: BLE001
        print('（留言失敗：%s）' % str(e)[:100])


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    dry = '--yes' not in sys.argv
    outputs_only = '--outputs-only' in sys.argv
    full = '--all' in sys.argv
    if full and outputs_only:
        sys.exit('--all 與 --outputs-only 不能一起用')
    keep = ALL_KEEP if full else [m for m in KEEP if '--code' not in sys.argv or m not in CODE]
    pkgs = [int(a) for a in args if a.isdigit()]
    if not pkgs:
        sys.exit(__doc__)
    # ★ 護欄：方案有進行中的說明書製作計畫時，真的清除要加 --force-active-plans
    #   ☠️ 實機（2026-11-05 方案 23）：計畫、盤點與執行紀錄被別的工作階段整批清掉，使用者與另一個工作階段都不知道
    if not dry and not outputs_only and '--force-active-plans' not in sys.argv:
        active = active_plans(pkgs)
        if active:
            sys.exit('這些方案有進行中的說明書製作計畫，清除會連計畫一起刪（--outputs-only 才會保留計畫）：\n  %s\n'
                     '確定要清請加 --force-active-plans。' % '\n  '.join(active))
    script = SCRIPT % {'dry': dry, 'keep': keep + (CATALOG if outputs_only else []), 'pkgs': pkgs,
                       'reset': [] if outputs_only else PKG_RESET, 'mark': MARK,
                       'modules': ALL_MODULES if full else BASE_MODULES}
    host, key = setting('DEPLOY_HOST'), os.path.expandvars(setting('DEPLOY_KEY'))
    ctr, db = setting('DEPLOY_CONTAINER'), setting('DEPLOY_DB')
    cmd = ['ssh', '-i', key, host,
           'docker exec -i %s odoo shell -c /etc/odoo/odoo.conf -d %s --no-http --logfile=/dev/null' % (ctr, db)]
    res = subprocess.run(cmd, input=script, capture_output=True, text=True, timeout=1800)
    line = next((l for l in res.stdout.splitlines() if l.startswith(MARK)), None)
    if not line:
        sys.exit('沒有結果：\n%s\n%s' % (res.stdout[-2000:], res.stderr[-2000:]))
    out = json.loads(line[len(MARK):])
    print(('試跑（已回滾）' if dry else '已清除') + ('（只清產出）' if outputs_only else '')
          + ('（全部清，含紀錄與設定）' if full else '（含程式知識）' if '--code' in sys.argv else ''))
    for m, n in sorted(out['deleted'].items(), key=lambda kv: -kv[1]):
        print('  %6s  %s' % (n, m))
    print('保留：', out['kept'])
    if out['dropped']:
        print('刪除說明庫資料庫：', out['dropped'])
    if out['errors']:
        print('錯誤：', out['errors'])
    if not dry:
        note_reset(pkgs, outputs_only, full)


if __name__ == '__main__':
    main()
