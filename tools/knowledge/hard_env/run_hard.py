"""本機「刁難測試方案」（計畫第 30 項）：部署前先用真的截圖程式＋瀏覽器重現社群電商方案踩過的坑。

用法：venv 的 python 執行  ~/Library/Caches/corpaas-kb/venv/bin/python tools/knowledge/hard_env/run_hard.py
  （第一次會建資料庫 kbhard，之後沿用；加 --fresh 重建）

檢查項目（每項 PASS／FAIL）：
  1 管理員以 API 登入，登入頁被改成首頁彈窗也進得了後台
  2 訪客開登入頁，經過的網址看得出是「首頁彈窗」
  3 會員（入口網站帳號）登入後拍得到 /my
  4 管理員拍得到只開放給自訂群組的畫面（說明庫管理員要拿全部內部群組）
  5 沒有群組的業務拍那個畫面 → 存取錯誤；唯讀診斷講得出缺哪個群組
  6 已撥款、模組不准刪的客戶單據，清除程式刪得掉
  7 示範資料不會多建第二家公司（重播時略過）
  8 平行拍攝：同一批分 2 組各開瀏覽器，結果與圖檔合併回來
  9 按鈕給的是畫面上的字（AI 常犯），截圖程式改用文字找得到
  10 點不到按鈕時，錯誤訊息附上畫面看得到的按鈕與分頁
  11 客戶的使用者匿名化後，partner 也封存（客戶清單不會出現「已移除使用者」）
"""
import importlib.util
import json
import os
import signal
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
KB = os.environ.get('KB_HOME', os.path.expanduser('~/Library/Caches/corpaas-kb'))
ODOO = os.environ.get('ODOO_SRC', os.path.expanduser('~/Desktop/Claude/odoo-18.0'))
GH = os.environ.get('GH_ROOT', os.path.expanduser('~/Documents/GitHub'))
DB, PW = 'kbhard', 'kb-hard-pw-123'
#: ☠️ 8099 被使用者的 Docker 佔用，截圖程式連到的是 Docker 裡的服務；預設用 8197，啟動前先確認沒人用
PORT = int(os.environ.get('KB_HARD_PORT', 8197))
PY = os.path.join(KB, 'venv', 'bin', 'python')
LAST_JOB = [None]

_spec = importlib.util.spec_from_file_location(
    'kb_scripts', os.path.join(REPO, 'dobtor_corpaas_knowledge', 'services', 'scripts.py'))
scripts = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scripts)


def addons():
    paths = [os.path.join(ODOO, 'addons'), os.path.join(ODOO, 'odoo', 'addons'), HERE]
    return ','.join(paths)


def odoo_args():
    host = open(os.path.join(KB, 'pg_host')).read().strip()
    return ['-d', DB, '--data-dir', os.path.join(KB, 'data'), '--db_host', host, '--db_user', 'odoo',
            '--db_password', 'odoo', '--addons-path', addons()]


def ensure_pg():
    subprocess.run([PY, '-c', "import pgserver; s=pgserver.get_server('%s/pgdata', cleanup_mode=None);"
                    "open('%s/pg_host','w').write(s.get_uri().split('host=')[1])" % (KB, KB)], check=True)


def shell(script):
    """在 kbhard 跑一段 odoo shell 腳本，回傳 MARK 那一行的 JSON。"""
    p = subprocess.run([PY, os.path.join(ODOO, 'odoo-bin'), 'shell'] + odoo_args() + ['--no-http'],
                       input=script, capture_output=True, text=True, cwd=ODOO, timeout=600)
    for line in p.stdout.splitlines():
        if line.startswith(scripts.MARK):
            return json.loads(line[len(scripts.MARK):])
    raise RuntimeError('shell 沒有結果：%s' % (p.stderr[-1500:] or p.stdout[-1500:]))


def setup(fresh):
    ensure_pg()
    if fresh:
        subprocess.run([PY, '-c', "import psycopg2; c=psycopg2.connect(host=open('%s/pg_host').read().strip(),"
                        "user='odoo',password='odoo',dbname='postgres'); c.autocommit=True;"
                        "c.cursor().execute('DROP DATABASE IF EXISTS %s')" % (KB, DB)], check=True)
    subprocess.run([PY, os.path.join(ODOO, 'odoo-bin')] + odoo_args() +
                   ['-i', 'kb_hard_env', '--without-demo=all', '--stop-after-init', '--workers=0'],
                   check=True, cwd=ODOO, capture_output=True)
    roles = [{'code': 'admin', 'name': '管理', 'groups': ['base.group_system']},
             {'code': 'sales', 'name': '業務', 'groups': ['base.group_user']},
             {'code': 'member', 'name': '會員', 'groups': ['base.group_portal']}]
    seed = [{'xmlid': 'company_rename', 'model': 'res.company', 'values': {'name': 'AI 多建的公司'}}]
    res = shell(scripts.seed_script('__doc_scenario_hard', seed, roles, PW))
    # 客戶的已撥款單據（沒有模組 xmlid＝清除對象）
    shell(scripts._HEAD + "d = env['kb.hard.doc'].sudo().create({'name': '客戶已撥款', 'state': 'paid'})\n"
          "env.cr.commit()\nprint(MARK + json.dumps({'id': d.id}))\n")
    # 客戶的入口網站使用者（沒有模組 xmlid＝要匿名化；使用者刪不掉）
    shell(scripts._HEAD + "U = env['res.users'].sudo().with_context(active_test=False)\n"
          "if not U.search([('login', '=', 'kb_customer_user')]):\n"
          "    U.create({'name': '客戶本人', 'login': 'kb_customer_user',\n"
          "              'groups_id': [(6, 0, [env.ref('base.group_portal').id])]})\n"
          "env.cr.commit()\nprint(MARK + json.dumps({}))\n")
    return res


def run_runner(shots, parallel=1):
    job = tempfile.mkdtemp(prefix='kbhard-job-')
    with open(os.path.join(job, 'job.json'), 'w') as fh:
        json.dump({'base_url': 'http://127.0.0.1:%s' % PORT, 'db': DB, 'width': 1440, 'height': 900,
                   'scale': 1, 'locale': 'zh-TW', 'tz': 'Asia/Taipei', 'frozen_time': '2026-01-15T10:00:00+08:00',
                   'extra_css': '', 'shots': shots, 'parallel': parallel}, fh)
    LAST_JOB[0] = job
    env = dict(os.environ, KB_JOB_DIR=job, PLAYWRIGHT_BROWSERS_PATH=os.path.join(KB, 'ms-playwright'))
    subprocess.run([PY, os.path.join(REPO, 'dobtor_corpaas_knowledge', 'shot_runner', 'run.py')],
                   env=env, capture_output=True, text=True, timeout=900)
    try:
        with open(os.path.join(job, 'out', 'result.json')) as fh:
            return json.load(fh)['shots']
    except (OSError, ValueError, KeyError):
        # 截圖程式整個掛掉：每張都判失敗（不要丟例外讓整個測試中斷）
        return {s['id']: {'ok': False, 'error': '截圖程式沒有結果'} for s in shots}


def main():
    fresh = '--fresh' in sys.argv
    import socket
    with socket.socket() as so:
        if so.connect_ex(('127.0.0.1', PORT)) == 0:
            sys.exit('埠 %s 已被佔用，請用 KB_HARD_PORT 換一個' % PORT)
    seed = setup(fresh)
    server = subprocess.Popen([PY, os.path.join(ODOO, 'odoo-bin')] + odoo_args() +
                              ['--http-port', str(PORT), '--workers=0', '--max-cron-threads=0',
                               '--db-filter', '^%s$' % DB], cwd=ODOO, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)
    checks = []
    try:
        import urllib.request
        for _i in range(90):   # 等 Odoo 真的能回應（載入模組要一段時間）
            try:
                urllib.request.urlopen('http://127.0.0.1:%s/web/health' % PORT, timeout=3)
                break
            except Exception:  # noqa: BLE001
                time.sleep(2)
        act = '/odoo/action-kb_hard_env.action_doc'
        # 資料庫會沿用：上一次點過「標記撥款」，先退回草稿
        draft = shell(scripts._HEAD + "d = env.ref('kb_hard_env.doc_draft')\nd.state = 'draft'\nenv.cr.commit()\n"
                      "print(MARK + json.dumps({'id': d.id}))\n")['id']
        miss = run_runner([{'id': 'miss', 'login': 'doc_admin', 'password': PW, 'steps': [
            {'goto': {'action': 'kb_hard_env.action_doc', 'res_id': draft}},
            {'click': {'button': '不存在的按鈕'}}, {'shot': 'never'}]}])['miss']
        merr = miss.get('error') or ''
        checks.append(('10 點不到按鈕時，錯誤列出畫面看得到的按鈕', '看得到的按鈕' in merr and 'action_mark_paid' in merr,
                       merr[:300]))
        btn = run_runner([{'id': 'button', 'login': 'doc_admin', 'password': PW, 'steps': [
            {'goto': {'action': 'kb_hard_env.action_doc', 'res_id': draft}},
            {'click': {'button': '標記撥款'}}, {'shot': 'after_click'}]}])['button']
        checks.append(('9 按鈕給的是畫面文字（不是技術名）也點得到', btn.get('ok'), btn.get('error')))
        shots = run_runner([
            {'id': 'admin', 'login': 'doc_admin', 'password': PW, 'steps': [
                {'goto': {'action': 'kb_hard_env.action_doc'}}, {'wait': {'ms': 800}}, {'shot': 'admin_doc'}]},
            {'id': 'probe', 'login': None, 'frontend': True, 'password': '', 'steps': [
                {'goto': {'url': '/web/login'}}, {'wait': {'ms': 800}}]},
            {'id': 'member', 'login': 'doc_member', 'password': PW, 'frontend': True, 'steps': [
                {'goto': {'url': '/my'}}, {'wait': {'ms': 800}}, {'shot': 'member_my'}]},
            {'id': 'sales', 'login': 'doc_sales', 'password': PW, 'steps': [
                {'goto': {'action': 'kb_hard_env.action_doc'}}, {'wait': {'ms': 800}}, {'shot': 'sales_doc'}]},
        ], parallel=2)
        checks.append(('8 平行拍攝（2 組）每張都有結果、檔案合併回來',
                       len(shots) == 4 and all('平行拍攝的子程序' not in (v.get('error') or '') for v in shots.values())
                       and all(os.path.exists(os.path.join(LAST_JOB[0], 'out', i['file']))
                               for v in shots.values() for i in v.get('images') or []),
                       {k: (v.get('ok'), (v.get('error') or '')[:80]) for k, v in shots.items()}))
        checks.append(('1 管理員 API 登入進得了後台（登入頁是彈窗）', shots['admin'].get('ok'), shots['admin'].get('error')))
        navs = shots['probe'].get('navigations') or []
        checks.append(('2 訪客開登入頁看得出是首頁彈窗', any('popup=login' in n for n in navs), navs))
        checks.append(('3 會員拍得到 /my', shots['member'].get('ok'), shots['member'].get('error')))
        adm = shots['admin']
        checks.append(('4 管理員拍得到自訂群組的畫面（有圖、停在那個動作）',
                       adm.get('ok') and any(i.get('name') == 'admin_doc' for i in adm.get('images') or [])
                       and '/odoo/action-' in (adm.get('url') or ''), adm.get('url') or act))
        err = shots['sales'].get('error') or ''
        diag = shell(scripts.access_diag_script('doc_sales', 'kb.hard.doc'))
        text = scripts.access_diag_text(diag)
        checks.append(('5 業務存取錯誤＋診斷講得出缺的群組',
                       (not shots['sales'].get('ok')) and 'group_doc_manager' in text, text or err[:200]))
        purge = shell(scripts.purge_script(['kb.hard.doc']))
        left = shell(scripts._HEAD + "print(MARK + json.dumps({'n': env['kb.hard.doc'].sudo().search_count("
                     "[('name', '=', '客戶已撥款')])}))\n")
        kept = shell(scripts._HEAD + "print(MARK + json.dumps({'n': bool(env.ref('kb_hard_env.doc_paid', "
                     "raise_if_not_found=False))}))\n")
        checks.append(('6 已撥款客戶單據清除得掉、模組自帶的單據保留', left['n'] == 0 and kept['n'],
                       {'deleted': purge.get('deleted'), 'module_doc_kept': kept['n']}))
        cust = shell(scripts._HEAD + "u = env['res.users'].sudo().with_context(active_test=False).search("
                     "['|', ('login', '=', 'kb_customer_user'), ('login', '=like', 'removed_%')], limit=1, order='id desc')\n"
                     "print(MARK + json.dumps({'name': u.partner_id.name, 'active': u.partner_id.active}))\n")
        checks.append(('11 客戶的使用者匿名化，連 partner 一起封存（清單不會出現）',
                       cust['name'] != '客戶本人' and cust['active'] is False, cust))
        companies = shell(scripts._HEAD + "print(MARK + json.dumps({'n': env['res.company'].sudo().search_count("
                          "[('name', '=', 'AI 多建的公司')])}))\n")
        checks.append(('7 示範資料不多建公司', companies['n'] == 0, seed.get('skipped')))
    finally:
        server.send_signal(signal.SIGINT)
        server.wait(timeout=30)
    bad = 0
    for name, ok, detail in checks:
        print('%s  %s%s' % ('PASS' if ok else 'FAIL', name, '' if ok else '  ← %s' % str(detail)[:300]))
        bad += 0 if ok else 1
    print('\n%s／%s 通過' % (len(checks) - bad, len(checks)))
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
