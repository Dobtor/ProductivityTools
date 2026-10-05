# -*- coding: utf-8 -*-
{
    'name': 'CorPaaS 方案知識：操作說明',
    'version': '18.0.1.0.4',
    'category': 'Productivity/Knowledge',
    'summary': '方案知識出口一：功能 × 情境的操作說明，自動截圖標註、推到方案的文件型 slide 課程',
    'description': '''
CorPaaS 方案知識：操作說明（出口一）
==================================

* 步驟區塊：功能 × 腳本範圍指紋，跨情境、跨方案共用；畫面改版依新指紋分岔，收斂時提議合併。
* 截圖腳本範本＋情境繫結：AI 探索畫面寫腳本、佔位符對到示範資料，失敗由 AI 修補。
* 文章：步驟區塊＋情境區塊＋紅框編號標註圖（伺服端 PIL 畫進圖，原圖不動）。
* 發佈：每個方案產品一個文件型 slide 課程，章節＝能力，整個課程每次重新編號；
  多個課程引用同一篇文章時輸出 canonical。
* help API：命中的功能回傳公開 slide 連結＋錨點＋指紋（租戶端 D5 比對）。
    ''',
    'author': 'Dobtor',
    'website': 'https://www.dobtor.com',
    'license': 'LGPL-3',
    'depends': ['dobtor_corpaas_knowledge', 'website_slides'],
    'external_dependencies': {'python': ['PIL', 'lxml']},
    'data': [
        'security/ir.model.access.csv',
        'views/manual_menus.xml',
        'views/article_views.xml',
        'views/step_block_views.xml',
        'views/shot_views.xml',
        'views/placement_views.xml',
        'views/website_slides_templates.xml',
    ],
    'installable': True,
    'application': False,
}
