"""清除方案知識與已發佈手冊，從零重跑（不可復原）。

    python3 tools/knowledge/reset_knowledge.py 13 14          # 試跑：全部做一遍、印出筆數、最後回滾
    python3 tools/knowledge/reset_knowledge.py 13 14 --yes    # 真的清（含刪說明庫資料庫）

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
        'corpaas.knowledge.code_tree', 'corpaas.knowledge.code_def', 'corpaas.knowledge.code_fact']
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
env = env(context=dict(env.context, active_test=False, tracking_disable=True, mail_notrack=True))
out = {'deleted': {}, 'dropped': [], 'errors': []}
busy = env['corpaas.knowledge.run'].sudo().search([('state', '=', 'running')])
if busy:
    raise SystemExit('還有進行中的更新 %%s：先停止' %% busy.ids)
# 1. 說明庫：真的清時先刪資料庫（試跑不刪）
for sb in env['corpaas.knowledge.sandbox'].sudo().search([('state', '!=', 'dropped')]):
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
models = sorted(m for m in env.registry if m.startswith('corpaas.knowledge.') and m not in KEEP
                and not env[m]._abstract and env[m]._auto)
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


def main():
    args = [a for a in sys.argv[1:] if a != '--yes']
    dry = '--yes' not in sys.argv
    pkgs = [int(a) for a in args if a.isdigit()]
    if not pkgs:
        sys.exit(__doc__)
    script = SCRIPT % {'dry': dry, 'keep': KEEP, 'pkgs': pkgs, 'reset': PKG_RESET, 'mark': MARK}
    host, key = setting('DEPLOY_HOST'), os.path.expandvars(setting('DEPLOY_KEY'))
    ctr, db = setting('DEPLOY_CONTAINER'), setting('DEPLOY_DB')
    cmd = ['ssh', '-i', key, host,
           'docker exec -i %s odoo shell -c /etc/odoo/odoo.conf -d %s --no-http --logfile=/dev/null' % (ctr, db)]
    res = subprocess.run(cmd, input=script, capture_output=True, text=True, timeout=1800)
    line = next((l for l in res.stdout.splitlines() if l.startswith(MARK)), None)
    if not line:
        sys.exit('沒有結果：\n%s\n%s' % (res.stdout[-2000:], res.stderr[-2000:]))
    out = json.loads(line[len(MARK):])
    print('試跑（已回滾）' if dry else '已清除')
    for m, n in sorted(out['deleted'].items(), key=lambda kv: -kv[1]):
        print('  %6s  %s' % (n, m))
    print('保留：', out['kept'])
    if out['dropped']:
        print('刪除說明庫資料庫：', out['dropped'])
    if out['errors']:
        print('錯誤：', out['errors'])


if __name__ == '__main__':
    main()
