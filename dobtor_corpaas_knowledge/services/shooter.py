# -*- coding: utf-8 -*-
"""主控台這側的截圖派工：準備 job 目錄 → docker run 一次性容器 → 取回結果。"""
import json
import logging
import os
import shlex
import uuid

from . import remote

_logger = logging.getLogger(__name__)

_RUNNER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'shot_runner', 'run.py')

JOBS_ROOT = '/opt/knowledge/jobs'
DEFAULT_IMAGE = 'mcr.microsoft.com/playwright/python:v1.48.0-jammy'
FROZEN_TIME = '2026-01-15T10:00:00+08:00'


class ShotError(Exception):
    pass


def run_shots(env, sandbox, shots, settings):
    """在說明庫所在主機跑一批截圖。

    shots: [{'id', 'login', 'password', 'steps': [...]}]（步驟裡的記錄已解析成 id）
    settings: dict，見 res.config.settings 的 knowledge_* 參數。
    回傳 (result_json, files)；files 為 {相對路徑: bytes}。
    """
    instance = sandbox.master_instance_id
    server = instance.server_id
    token = uuid.uuid4().hex[:12]
    job_dir = '%s/%s' % (JOBS_ROOT, token)
    host = '%s.internal' % sandbox.db_name
    port = settings.get('odoo_port') or 8069
    job = {
        'base_url': 'http://%s:%s' % (host, port),
        # 把 <庫名>.internal 映射到母體容器名；docker 內建 DNS 會解析容器名。
        'resolver_rule': 'MAP %s %s' % (host, instance.odoo_container),
        'width': 1440, 'height': 900, 'scale': 2,
        'locale': 'zh-TW', 'tz': 'Asia/Taipei',
        'frozen_time': FROZEN_TIME,
        'extra_css': settings.get('extra_css') or '',
        'shots': shots,
    }
    with open(_RUNNER, 'rb') as fh:
        runner_src = fh.read()
    remote.put_bytes(server, job_dir + '/run.py', runner_src)
    remote.put_bytes(server, job_dir + '/job.json',
                     json.dumps(job, ensure_ascii=False).encode('utf-8'))
    fonts = settings.get('fonts_dir') or '/usr/share/fonts/opentype/noto'
    image = settings.get('image') or DEFAULT_IMAGE
    network = server.docker_network_name
    cmd = (
        'FONTS=%(fonts)s; FONT_ARG=""; '
        'if [ -d "$FONTS" ]; then FONT_ARG="-v $FONTS:/usr/share/fonts/kb-cjk:ro"; fi; '
        'docker run --rm --network %(net)s --memory %(mem)s --cpus %(cpus)s '
        '-v %(job)s:/job $FONT_ARG %(image)s python /job/run.py'
    ) % {
        'fonts': shlex.quote(fonts), 'net': shlex.quote(network),
        'mem': shlex.quote(settings.get('memory') or '1.5g'),
        'cpus': shlex.quote(str(settings.get('cpus') or 1)),
        'job': shlex.quote(job_dir), 'image': shlex.quote(image),
    }
    try:
        res = remote.run(server, cmd, dont_raise=True)
        files = remote.fetch_dir(server, job_dir + '/out')
    finally:
        remote.remove_dir(server, job_dir)
    raw = files.pop('result.json', None)
    if not raw:
        raise ShotError('截圖容器沒有產出結果：%s'
                        % ((getattr(res, 'stderr', '') or getattr(res, 'stdout', '') or '')[-2000:]))
    return json.loads(raw.decode('utf-8')), files
