# -*- coding: utf-8 -*-
{
    'name': 'Dobtor AI Hub · 知識內容模式',
    'version': '18.0.1.2.0',
    'category': 'Productivity/AI',
    'summary': '讓 CorPaaS 主控台以上行金鑰請 AI Hub 產生知識內容（content 模式）',
    'description': '''
Dobtor AI Hub · 知識內容模式
========================================

CorPaaS 方案知識核心（dobtor_corpaas_knowledge）的 AI 出口。主控台把「整理功能說明、
寫行銷文案、估建議書」這類工作送進來，拿回一段文字，JSON 由主控台自己解析。

* 新模式 ``content`` （知識內容）：Session／Run／產物／路由規則都認得它。
* 新端點 ``POST /ai_hub/api/v1/content_run`` ：沿用上行金鑰與每日配額／成本上限，
  結果沿用既有的 ``/ai_hub/api/v1/run_status`` 。
* 來源上的「允許知識內容」開關，預設關閉。

★ Runner 對不認得的模式沒有系統提示，所以角色與輸出格式全在 prompt 裡——
  由主控台負責，不在這裡另寫一份。
    ''',
    'author': 'Dobtor',
    'website': 'https://www.dobtor.com',
    'license': 'LGPL-3',
    'depends': ['dobtor_ai_hub'],
    'data': [
        'views/ai_hub_source_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
