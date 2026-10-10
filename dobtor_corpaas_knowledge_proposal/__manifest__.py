# -*- coding: utf-8 -*-
{
    'name': 'CorPaaS 方案知識：服務建議書／評估報價／預估成本',
    'version': '18.0.2.0.0',
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
* Word／PDF 輸出（2.0）：文件範本綁在既有的列印動作上，由 dobtor_doc_editor 輸出；
  文件是版本資料的投影，已送出的版本讀凍結快照，重新輸出永遠和送出時一致。
* 案件與版本（2.0）：一個案件底下有 v1.0、v1.1、v2.0…，一個商機可以有多個案件（追加報價）；
  提案直接依賴 sale_crm，建報價單帶商機，送出時更新商機預估收入與留言。
    ''',
    'author': 'Dobtor',
    'website': 'https://www.dobtor.com',
    'license': 'LGPL-3',
    'depends': ['dobtor_corpaas_knowledge', 'dobtor_corpaas_sale', 'sale_management',
                'sale_crm', 'dobtor_doc_editor', 'dobtor_meeting_minutes'],
    'external_dependencies': {'python': ['openpyxl']},
    'data': [
        'security/ir.model.access.csv',
        'data/proposal_data.xml',
        'data/clause_data.xml',
        'views/effort_views.xml',
        'views/proposal_views.xml',
        'views/case_views.xml',
        'views/lead_source_views.xml',
        'views/res_config_settings_views.xml',
        'wizard/proposal_import_views.xml',
        'wizard/provision_wizard_views.xml',
        'views/sale_order_views.xml',
        'report/proposal_report.xml',
        'views/proposal_menus.xml',
        'views/clause_views.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
}
