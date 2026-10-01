# -*- coding: utf-8 -*-
{
    'name': 'CorPaaS 服務建議書 × 專案：結案自動工時回寫',
    'version': '18.0.1.0.0',
    'category': 'Productivity/Knowledge',
    'summary': '導入專案進到摺疊（結案）階段時，自動把實際工時回寫校正工時範本',
    'description': '''
橋接模組：dobtor_corpaas_knowledge_proposal ＋ sale_project ＋ hr_timesheet 同時存在時自動安裝。
專案階段變成摺疊（fold＝結案）時，對報價單關聯的服務建議書呼叫「工時回寫」。
安裝時把預設「導入服務（人天）」設為確認報價單即建專案（project_only），工時才有地方記。
    ''',
    'author': 'Dobtor',
    'website': 'https://www.dobtor.com',
    'license': 'LGPL-3',
    'depends': ['dobtor_corpaas_knowledge_proposal', 'sale_project', 'hr_timesheet'],
    'data': [],
    'post_init_hook': '_post_init_hook',
    'installable': True,
    'auto_install': True,
    'application': False,
}
