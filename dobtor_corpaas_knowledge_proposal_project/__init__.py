# -*- coding: utf-8 -*-
from . import models


def _post_init_hook(env):
    """預設「導入服務（人天）」改成確認報價單就建專案（project_only）。

    ★ service_tracking 是 sale_project 的欄位，建議書模組不依賴 sale_project，所以在這個橋接模組設。
      沒有專案就沒有工時，也就不會有結案回寫。
    ★ 只改仍是預設「不追蹤」的：已經被人改成別的追蹤方式就尊重那個設定。
    """
    service = env.ref('dobtor_corpaas_knowledge_proposal.product_implementation_service',
                      raise_if_not_found=False)
    if service and service.service_tracking == 'no':
        service.service_tracking = 'project_only'
