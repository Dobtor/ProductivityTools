# -*- coding: utf-8 -*-
"""客戶專屬疊加目錄（知識主從計畫第三期，方案 B）：加購與開發模組不進母體，只在該客戶的說明庫可見。

· 程式碼：依發行標籤把 repo 抓到說明主機的 <疊加根目錄>/<疊加 id>/<repo 目錄>（淺抓、只抓那個標籤）。
· 一次性 odoo shell（清除、示範資料、探測）與服務該說明庫的臨時 Odoo 容器，都多掛這個目錄並延長 addons 路徑。
· 母體容器看不到這些模組：拍照改連臨時容器（解析規則把 <庫名>.internal 指到它）。

★ token 不上指令列：寫進只有 SSH 帳號讀得到的暫存目錄，git 經 GIT_ASKPASS 取用，用完刪掉。
★ 標籤、網址、目錄名一律白名單檢查後才組指令。
"""
import re
import shlex
import uuid

from odoo.addons.dobtor_infrastructure.models.server import custom_sudo

from . import remote

CONTAINER_ROOT = '/mnt/kb-overlay'
_REF = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$')
_URL = re.compile(r'^https://github\.com/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+?(\.git)?$')
_SLUG = re.compile(r'^[a-z0-9][a-z0-9._-]{0,80}$')
_MODULE = re.compile(r'^[A-Za-z0-9_]{1,120}$')


class OverlayError(Exception):
    pass


def repo_slug(url):
    """https://github.com/Dobtor/Sales.git → dobtor-sales"""
    if not _URL.match(url or ''):
        raise OverlayError('只支援 GitHub https 網址：%s' % url)
    owner, name = url.rstrip('/').removesuffix('.git').split('/')[-2:]
    return re.sub(r'[^a-z0-9._-]', '-', ('%s-%s' % (owner, name)).lower())


def check_ref(ref):
    if not _REF.match(ref or '') or '..' in ref:
        raise OverlayError('發行標籤格式不對：%s' % ref)
    return ref


def check_module(name):
    if not _MODULE.match(name or ''):
        raise OverlayError('模組名稱格式不對：%s' % name)
    return name


def fetch(server, dest, url, ref, token=None):
    """把 url 在 ref（標籤或分支）的內容抓到主機的 dest；回傳 commit SHA。已是同一個 SHA 就不重抓。"""
    check_ref(ref)
    repo_slug(url)
    q = shlex.quote
    with server.get_connect() as c:
        cred = None
        try:
            env = 'GIT_TERMINAL_PROMPT=0'
            if token:
                cred = '/tmp/kb_ov_%s' % uuid.uuid4().hex
                c.run('umask 077 && mkdir -p %s' % q(cred), hide=True)
                remote._put(c, cred + '/token', token.encode('utf-8'))
                remote._put(c, cred + '/askpass', (
                    '#!/bin/sh\ncase "$1" in\n  Username*) printf \'%%s\\n\' x-access-token ;;\n'
                    '  *) cat %s ;;\nesac\n' % q(cred + '/token')).encode('utf-8'))
                c.run('chmod 700 %s' % q(cred + '/askpass'), hide=True)
                env += ' GIT_ASKPASS=%s' % q(cred + '/askpass')
            script = (
                'set -e; mkdir -p {d}; cd {d}; '
                '[ -d .git ] || git init -q; '
                'git remote remove origin 2>/dev/null || true; git remote add origin {u}; '
                '{env} git fetch -q --depth 1 origin {r}; '
                'git checkout -q --detach -f FETCH_HEAD; git clean -qfdx; git rev-parse HEAD'
            ).format(d=q(dest), u=q(url), r=q(ref), env=env)
            res = custom_sudo(c, 'sh -c %s' % q(script), dont_raise=True)
        finally:
            if cred:
                c.run('rm -rf %s' % q(cred), hide=True, warn=True)
    out = (getattr(res, 'stdout', '') or '').strip().splitlines()
    sha = out[-1] if out else ''
    if getattr(res, 'exited', 1) or not re.fullmatch(r'[0-9a-f]{40}', sha):
        raise OverlayError('抓取 %s@%s 失敗：%s' % (url, ref, ((getattr(res, 'stderr', '') or '')[-500:])))
    return sha


def has_module(server, repo_dir, module):
    check_module(module)
    res = remote.run(server, 'test -f %s && echo OK' % shlex.quote('%s/%s/__manifest__.py' % (repo_dir, module)),
                     dont_raise=True)
    return 'OK' in (getattr(res, 'stdout', '') or '')


def base_addons_path(env, instance):
    """母體設定檔裡的 addons_path（容器內路徑）。"""
    inst = instance.sudo()
    conf_file = '%s/%s' % (inst.conf_path.rstrip('/'), inst.odoo_image_id.odoo_config_file or 'odoo.conf')
    res = remote.run(inst.server_id, 'grep -E "^[[:space:]]*addons_path" %s' % shlex.quote(conf_file),
                     dont_raise=True)
    line = (getattr(res, 'stdout', '') or '').strip().splitlines()
    if not line or '=' not in line[-1]:
        raise OverlayError('讀不到母體的 addons_path（%s）' % conf_file)
    return line[-1].split('=', 1)[1].strip()


def docker_args(host_dir, repo_dirs, base_path):
    """一次性容器與臨時 Odoo 容器要多加的參數：唯讀掛疊加目錄、addons 路徑接在母體後面。"""
    for d in repo_dirs:
        if not _SLUG.match(d):
            raise OverlayError('疊加目錄名稱不對：%s' % d)
    paths = [p for p in (base_path or '').split(',') if p.strip()] + \
            ['%s/%s' % (CONTAINER_ROOT, d) for d in repo_dirs]
    return '-v %s:%s:ro' % (shlex.quote(host_dir), CONTAINER_ROOT), '--addons-path=%s' % shlex.quote(','.join(paths))


def serve_name(db_name):
    return 'kb-ov-%s' % re.sub(r'[^a-z0-9-]', '-', db_name.lower())[:60]


def serve_start(env, instance, db_name, mount_arg, addons_arg):
    """服務單一說明庫的臨時 Odoo（拍照用）：同映像、唯讀掛程式碼與設定、只服務這個庫。"""
    inst = instance.sudo()
    img = inst.odoo_image_id
    Database = env['infrastructure.database'].sudo()
    name = serve_name(db_name)
    q = shlex.quote
    mem = env['ir.config_parameter'].sudo().get_param('corpaas_knowledge.overlay_serve_memory') or '1g'
    cmd = (
        'docker rm -f {n} >/dev/null 2>&1; docker run -d --name {n} --network {net} --memory {mem} --cpus 1 '
        '-v {conf_dir}:{etc}:ro -v {src}:{addons}:ro {mount} --entrypoint odoo {image} '
        '-c {conf} {addons_arg} -d {db} --db-filter={flt} --workers=0 --max-cron-threads=0 '
        '--http-port=8069 --logfile=/dev/stderr{pg}'
    ).format(n=q(name), net=q(inst.server_id.docker_network_name or 'bridge'), mem=q(mem),
             conf_dir=q(inst.conf_path), etc=q(img.odoo_etc_dir or '/etc/odoo'), src=q(inst.sources_path),
             addons=q(img.odoo_extra_addons_dir or '/mnt/extra-addons'), mount=mount_arg,
             image=q('%s:%s' % (img.pull_name, inst.odoo_image_tag_id.name)),
             conf=q(Database._instance_conf_path(instance)), addons_arg=addons_arg, db=q(db_name),
             flt=q('^%s$' % re.escape(db_name)), pg=Database._pg_direct_cli_args(instance=instance))
    remote.run(inst.server_id, cmd)
    # 等它起來（最多 90 秒）
    remote.run(inst.server_id, 'for i in $(seq 1 45); do docker exec %s python3 -c "import urllib.request;'
               'urllib.request.urlopen(\'http://127.0.0.1:8069/web/login\', timeout=2)" >/dev/null 2>&1 '
               '&& exit 0; sleep 2; done; exit 1' % q(name))
    return name


def serve_stop(server, db_name):
    remote.run(server, 'docker rm -f %s' % shlex.quote(serve_name(db_name)), dont_raise=True)
