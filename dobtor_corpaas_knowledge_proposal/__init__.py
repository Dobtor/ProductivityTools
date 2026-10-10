# -*- coding: utf-8 -*-
from . import models
from . import wizard


def post_init_hook(env):
    """新裝時建立服務建議書的文件範本與它在列印動作上的綁定。

    ★ 升級（1.x → 2.0）走 migrations/18.0.2.0.0/post-migrate.py，那裡做同一件事。
    """
    env['corpaas.knowledge.proposal']._ensure_doc_template()
