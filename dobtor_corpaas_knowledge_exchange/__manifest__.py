# -*- coding: utf-8 -*-
{
    'name': 'CorPaaS 方案知識主從交換',
    'version': '18.0.1.2.0',
    'category': 'Productivity/Knowledge',
    'summary': '主體（admin.corpaas.com）與從屬主控台交換公開知識：先查主體再算、送件入庫、發佈清單、上收提案',
    'description': '''
方案知識主從交換
================

同一套模組，依系統參數 corpaas_knowledge.exchange_mode 切換主體／從屬模式（預設關閉）。

* 主體：簽章端點 lookup／ingest／feed／feedback；入庫紀錄、上收提案審核、發佈清單。
* 從屬：算程式知識前先查主體（主體有就存成唯讀鏡像）、公開的程式知識自動送件、依游標拉發佈清單。
* 只交換文字知識與雜湊；不傳程式原文、截圖、客戶資料。預設私有，公開判定見 models/federated.py。

設計：知識主從改版計畫（第 6～9 節）。
    ''',
    'author': 'Dobtor',
    'website': 'https://www.dobtor.com',
    'license': 'OPL-1',
    'depends': ['dobtor_corpaas_knowledge', 'dobtor_corpaas_knowledge_manual'],
    'external_dependencies': {'python': ['requests']},
    'data': [
        'security/ir.model.access.csv',
        'data/ir_cron.xml',
        'views/exchange_views.xml',
        'views/feedback_wizard_views.xml',
    ],
    'installable': True,
    'application': False,
}
