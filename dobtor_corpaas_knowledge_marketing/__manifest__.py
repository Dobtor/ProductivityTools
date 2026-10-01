# -*- coding: utf-8 -*-
{
    'name': 'CorPaaS 方案知識：產品行銷出口',
    'version': '18.0.1.0.0',
    'category': 'Productivity/Knowledge',
    'summary': '方案知識核心的出口二：能力卡片、宣稱錨定、本期新增、加購可得，推到方案商品頁',
    'description': '''
CorPaaS 方案知識：產品行銷出口
==============================

* 能力卡片（pitch）：能力＋情境＋用語對照 → AI 起草標題／內文／宣稱，一律人工核准才上線。
* 宣稱錨定（claim）：每一句宣稱綁定功能點；功能消失或畫面大改 → 宣稱待查、卡片失效並暫時撤圖。
* 本期新增（release note）：同一次更新新增、且已歸入能力的功能 → AI 起草 → 送審。
* 加購可得：能力在方案中缺的模組都可單獨販售 → 商品頁列出並連到模組商品；help API 回 upsell 連結。

設計文件：CorPaaS 方案知識核心設計（Claude Docs）；實作契約見
dobtor_corpaas_knowledge/IMPLEMENTATION_SPEC.md「模組 B」。
    ''',
    'author': 'Dobtor',
    'website': 'https://www.dobtor.com',
    'license': 'LGPL-3',
    'depends': ['dobtor_corpaas_knowledge', 'dobtor_corpaas_website', 'website_sale'],
    'external_dependencies': {'python': ['lxml']},
    'data': [
        'security/ir.model.access.csv',
        'views/pitch_views.xml',
        'views/release_note_views.xml',
        'views/capability_views.xml',
        'views/product_template_views.xml',
        'views/marketing_menus.xml',
        'views/website_templates.xml',
    ],
    'installable': True,
    'application': False,
}
