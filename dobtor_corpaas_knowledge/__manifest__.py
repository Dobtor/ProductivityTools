# -*- coding: utf-8 -*-
{
    'name': 'CorPaaS 方案知識核心',
    'version': '18.0.1.7.0',
    'category': 'Productivity/Knowledge',
    'summary': '監控方案母體改版，自動盤點功能、算畫面指紋、重建說明庫並無頭截圖；'
               '說明書／行銷／建議書三個出口共用的事實層',
    'description': '''
CorPaaS 方案知識核心
====================

一個共用層、三個出口（操作說明 slide、產品行銷、建議書報價）。本模組只放**事實層**：

* 功能點：從黃金庫自動盤點（選單、動作、按鈕、精靈、設定、報表），穩定鍵 D3。
* 畫面指紋：依角色在黃金庫交易內算 get_views，結尾 rollback（D2）。
* 能力／情境／素材／圈選提案／失效事件／改名候選。
* 說明庫：方案母體裡的內部資料庫，從黃金庫複製、清除業務資料（D1）、重播情境（D6）。
* 無頭截圖：主控台經 SSH 在說明主機跑一次性 Playwright 容器（D8）。
* 內容狀態機與修訂（D4），供各出口繼承。
* 公開 help API（租戶端查說明連結）。

設計文件：CorPaaS 方案知識核心設計（Claude Docs）。
    ''',
    'author': 'Dobtor',
    'website': 'https://www.dobtor.com',
    'license': 'LGPL-3',
    'depends': ['mail', 'dobtor_corpaas_template'],
    'external_dependencies': {'python': ['requests', 'PIL']},
    'data': [
        'security/knowledge_security.xml',
        'security/ir.model.access.csv',
        'data/ir_config_parameter.xml',
        'data/ir_cron.xml',
        'views/knowledge_menus.xml',
        'views/feature_views.xml',
        'views/flow_views.xml',
        'views/coverage_views.xml',
        'views/toggle_views.xml',
        'views/catalog_views.xml',
        'views/sandbox_views.xml',
        'views/run_views.xml',
        'views/template_source_views.xml',
        'views/solution_package_views.xml',
        'views/res_config_settings_views.xml',
        'views/help_key_views.xml',
        'views/knowledge_package_views.xml',
        'wizard/reject_wizard_views.xml',
    ],
    'installable': True,
    'application': False,
}
