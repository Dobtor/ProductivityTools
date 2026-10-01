# -*- coding: utf-8 -*-
{
    'name': 'Dobtor AI Bridge · 此畫面說明',
    'version': '18.0.1.0.0',
    'category': 'Productivity/AI',
    'summary': '後台助理面板加上「此畫面說明」：向 CorPaaS 主控台查這個畫面的操作說明連結',
    'description': '''
Dobtor AI Bridge · 此畫面說明（租戶端）
==================================================

CorPaaS 方案知識核心的租戶端出口。後台助理面板多一顆「此畫面說明」，
提問時也會在回答下方附上相關說明頁。

* 連結由**主控台**依本庫的方案比對產生，本站伺服器轉查、面板自己渲染；
  **不經過 AI、也不讓模型寫連結**。
* 只顯示 https、且網域是主控台或設定的公開說明網域的連結，一律開新分頁。
* D5：用目前使用者的畫面算腳本範圍指紋，與說明拍攝時不一致就標
  「你的畫面可能與說明不同」，並回報主控台。
    ''',
    'author': 'Dobtor',
    'website': 'https://www.dobtor.com',
    'license': 'LGPL-3',
    'depends': ['dobtor_ai_bridge_backend'],
    'external_dependencies': {'python': ['requests']},
    'data': [
        'views/res_config_settings_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'dobtor_ai_bridge_help/static/src/help/help_panel.js',
            'dobtor_ai_bridge_help/static/src/help/help_panel.xml',
            'dobtor_ai_bridge_help/static/src/help/help_panel.scss',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
