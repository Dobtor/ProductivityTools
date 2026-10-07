# -*- coding: utf-8 -*-
{
    'name': 'CorPaaS 方案知識：服務建議書／評估報價／預估成本',
    'version': '18.0.1.1.0',
    'category': 'Productivity/Knowledge',
    'summary': '出口三：客戶痛點 → AI 對應方案能力 → 工項估算 → 建議書 PDF／報價單，'
               '送出凍結快照，工時回寫校正估算',
    'description': '''
CorPaaS 方案知識：服務建議書
============================

方案知識核心的第三個出口。

* 痛點：手動輸入，或匯入售前痛點 xlsx（每張部門表一組）。
* AI 比對能力：痛點＋方案能力（痛點／成果）→ 對應提議（四色、客製參考人天區間）。
* 計算估算：能力 × 工項的工時範本，days = base + ceil(驅動量／單位) × 每單位人天。
* 建議書 HTML／PDF：痛點對應表、能力說明（有行銷模組時引用已發佈文案）、報價表、資料移轉檢核表。
* 建立報價單：訂閱方案（compute_package_price 計價）、加購模組、導入服務人天。
  報價單確認時不自動開通，由「確認開通」選新平台／疊加／換層級。
* 送出後凍結快照、唯讀；工時回寫以移動平均校正工時範本。
* 成本與毛利：人力＋基礎設施＋第三方＋AI 點數；未校準時標示「估算值」。
    ''',
    'author': 'Dobtor',
    'website': 'https://www.dobtor.com',
    'license': 'LGPL-3',
    'depends': ['dobtor_corpaas_knowledge', 'dobtor_corpaas_sale', 'sale_management'],
    'external_dependencies': {'python': ['openpyxl']},
    'data': [
        'security/ir.model.access.csv',
        'data/proposal_data.xml',
        'views/effort_views.xml',
        'views/proposal_views.xml',
        'views/res_config_settings_views.xml',
        'wizard/proposal_import_views.xml',
        'wizard/provision_wizard_views.xml',
        'views/sale_order_views.xml',
        'report/proposal_report.xml',
        'views/proposal_menus.xml',
    ],
    'installable': True,
    'application': False,
}
