# -*- coding: utf-8 -*-
{
    'name': 'CorPaaS 方案知識 × 白標經銷商',
    'version': '18.0.1.1.0',
    'category': 'Productivity/Knowledge',
    'summary': '經銷商在自己的白標後台管理他代管客戶的專案知識：建立、核准說明書製作計畫、取回已發佈的說明書；AI 費用進批發月結',
    'description': '''
方案知識 × 白標經銷商
=====================

知識照樣在 CorPaaS 主控台產生（盤點、讀程式、說明庫、截圖都需要主機權限，不能放到經銷商那邊），
這個橋接模組只做這幾件事：

* 範圍：方案的 knowledge_reseller_id（經銷商上架的方案、經銷商代管客戶的專案知識）
* API：/api/v1/knowledge…（建立專案知識、看計畫、核准、立即更新、取回說明書與圖片），
  webhook knowledge_plan_review／knowledge_published
* 目錄項行銷內容：/api/v1/catalog/<catalog_ref>/marketing（已核准的能力卡片＋本期新增，
  所有經銷商可用、範圍同目錄；行銷出口沒裝就回空的）
* 計費：這些方案的 AI 費用記到經銷商的批發月結單

知識核心不認得經銷商；這裡是唯一的接點。
    ''',
    'author': 'Dobtor',
    'website': 'https://www.dobtor.com',
    'license': 'OPL-1',
    'depends': ['dobtor_corpaas_knowledge', 'dobtor_corpaas_knowledge_manual',
                'dobtor_corpaas_reseller'],
    'data': [
        'views/package_views.xml',
    ],
    'installable': True,
    'auto_install': True,
}
