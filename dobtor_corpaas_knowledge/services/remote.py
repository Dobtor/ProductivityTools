# -*- coding: utf-8 -*-
"""對說明主機的遠端操作：以「資料庫名稱」跑 odoo shell、上傳／取回檔案、跑容器。

★ 為什麼不用 `infrastructure.database._shell_exec`：那支綁在一筆資料庫記錄上，
  而說明庫刻意**不建** infrastructure.database 記錄——建了就會被服務盤點、
  授權推送、容量計算、計量、dbfilter 收斂全部當成客戶庫（D7）。這裡照抄同一條
  指令（同樣直連底層 PG、同樣以 marker 行回傳），只把庫名換成參數。
"""
import base64
import io
import json
import logging
import shlex
import tarfile
import uuid

from odoo.addons.dobtor_infrastructure.models.server import custom_sudo

_logger = logging.getLogger(__name__)

MARK = '__CORPAAS_SHELL__:'


class RemoteError(Exception):
    pass


def _db_helper(env):
    return env['infrastructure.database'].sudo()


def _isolated_enabled(env):
    val = env['ir.config_parameter'].sudo().get_param('corpaas_knowledge.isolated_analysis', '1')
    return str(val).strip().lower() not in ('0', 'false', 'off', 'no')


def _isolated_cmd(env, instance, db_name, tmp):
    """一次性分析容器：同一個映像、唯讀掛同一份程式碼與設定，限記憶體，跑完即刪。

    ★ 不 docker exec 進母體：那是正在服務共享租戶的正式容器，每次分析都在裡面多開一個
      完整 Odoo（數百 MB），還會和它的 worker 搶 CPU。
    ★ --entrypoint odoo：官方映像的 entrypoint 會依環境變數補 --db_host 等參數，蓋掉設定檔。
    """
    inst = instance.sudo()
    img = inst.odoo_image_id
    image = '%s:%s' % (img.pull_name, inst.odoo_image_tag_id.name)
    etc = img.odoo_etc_dir or '/etc/odoo'
    addons = img.odoo_extra_addons_dir or '/mnt/extra-addons'
    Database = _db_helper(env)
    conf = Database._instance_conf_path(instance)
    mem = env['ir.config_parameter'].sudo().get_param(
        'corpaas_knowledge.analysis_memory') or '1g'
    return (
        "cat %(tmp)s | docker run --rm -i --network %(net)s --memory %(mem)s --cpus 1 "
        "-v %(conf_dir)s:%(etc)s:ro -v %(src)s:%(addons)s:ro --entrypoint odoo %(image)s "
        "shell -c %(conf)s --no-http --logfile=/dev/stderr --stop-after-init -d %(db)s%(pg)s"
    ) % {
        'tmp': shlex.quote(tmp), 'net': shlex.quote(inst.server_id.docker_network_name or 'bridge'),
        'mem': shlex.quote(mem), 'conf_dir': shlex.quote(inst.conf_path), 'etc': shlex.quote(etc),
        'src': shlex.quote(inst.sources_path), 'addons': shlex.quote(addons),
        'image': shlex.quote(image), 'conf': shlex.quote(conf), 'db': shlex.quote(db_name),
        'pg': Database._pg_direct_cli_args(instance=instance),
    }


def shell_exec(env, instance, db_name, script, isolated=False):
    """在 `instance` 的 Odoo 容器內，對 `db_name` 跑 odoo shell；回傳 stdout。

    腳本不 commit 就不會留下任何東西（shell 結束時 rollback）。
    ★ 腳本先以 SFTP 上傳成暫存檔再 `cat` 進容器，不放在指令列上：
      ☠️ 單一參數上限 128 KB（MAX_ARG_STRLEN），示範資料腳本一大就直接失敗；
      ☠️ 指令列在主機的行程清單裡人人看得到，示範帳號密碼會外露。
    """
    Database = _db_helper(env)
    conf = Database._instance_conf_path(instance)
    container = shlex.quote(instance.odoo_container)
    tmp = '/tmp/kb_shell_%s.py' % uuid.uuid4().hex
    with instance.server_id.get_connect() as c:
        _put(c, tmp, script.encode('utf-8'))
        try:
            if isolated:
                cmd = _isolated_cmd(env, instance, db_name, tmp)
            else:
                cmd = (
                    "cat %s | docker exec -i %s odoo shell -c %s --no-http "
                    "--logfile=/dev/stderr --stop-after-init -d %s%s" % (
                        shlex.quote(tmp), container, shlex.quote(conf), shlex.quote(db_name),
                        Database._pg_direct_cli_args(instance=instance)))
            res = custom_sudo(c, cmd, dont_raise=isolated)
        finally:
            custom_sudo(c, 'rm -f %s' % shlex.quote(tmp), dont_raise=True)
    return getattr(res, 'stdout', '') or ''


def _put(connection, remote_path, data):
    """SFTP 上傳到使用者可寫的暫存位置（權限 600）。"""
    connection.put(io.BytesIO(data), remote=remote_path)
    connection.run('chmod 600 %s' % shlex.quote(remote_path), hide=True)


def parse_marker(out):
    result = None
    for line in (out or '').splitlines():
        line = line.strip()
        if line.startswith(MARK):
            try:
                result = json.loads(line[len(MARK):])
            except ValueError as e:
                _logger.warning('[knowledge] marker 解析失敗：%s', e)
    return result


def shell_json(env, instance, db_name, script, isolated=False):
    """isolated=True：唯讀分析優先用一次性容器；起不來（映像沒拉、掛載路徑不對…）就記一筆
    警告、退回 docker exec 進母體，分析照樣完成。"""
    if isolated and _isolated_enabled(env):
        try:
            out = shell_exec(env, instance, db_name, script, isolated=True)
            res = parse_marker(out)
            if res is not None:
                return res
            _logger.warning('[knowledge] 一次性分析容器沒有回傳結果，改用母體容器：%s',
                            (out or '')[-500:])
        except Exception as e:  # noqa: BLE001
            _logger.warning('[knowledge] 一次性分析容器失敗，改用母體容器：%s', e)
    out = shell_exec(env, instance, db_name, script)
    res = parse_marker(out)
    if res is None:
        raise RemoteError('odoo shell 沒有回傳結果（%s）：%s'
                          % (db_name, (out or '')[-2000:]))
    return res


def run(server, command, dont_raise=False):
    with server.get_connect() as c:
        res = custom_sudo(c, command, dont_raise=dont_raise)
    return res


def put_bytes(server, remote_path, data):
    """把位元組寫到主機的 remote_path（先 SFTP 到 /tmp，再以 sudo 搬到目的地）。"""
    tmp = '/tmp/kb_put_%s' % uuid.uuid4().hex
    directory = remote_path.rsplit('/', 1)[0]
    with server.get_connect() as c:
        _put(c, tmp, data)
        custom_sudo(c, 'mkdir -p %s && mv %s %s' % (
            shlex.quote(directory), shlex.quote(tmp), shlex.quote(remote_path)))


def fetch_dir(server, remote_dir):
    """把主機上的目錄打包取回：{相對路徑: bytes}。"""
    cmd = 'tar -C %s -czf - . | base64 -w0' % shlex.quote(remote_dir)
    res = run(server, cmd)
    raw = base64.b64decode((getattr(res, 'stdout', '') or '').strip() or b'')
    files = {}
    if not raw:
        return files
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            fh = tar.extractfile(member)
            if fh:
                files[member.name.lstrip('./')] = fh.read()
    return files


def remove_dir(server, remote_dir):
    if not remote_dir or remote_dir in ('/', '/opt', '/opt/knowledge'):
        raise RemoteError('拒絕刪除危險路徑：%s' % remote_dir)
    run(server, 'rm -rf %s' % shlex.quote(remote_dir), dont_raise=True)
