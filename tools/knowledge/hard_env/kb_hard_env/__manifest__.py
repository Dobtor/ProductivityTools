# -*- coding: utf-8 -*-
{
    'name': 'KB 別難測試環境（只給本機測試用）',
    'version': '18.0.1.0.0',
    'summary': '重現方案知識在社群電商方案踩過的坑：彈窗登入、第二家公司、自訂群組、不准刪的單據、限會員選單',
    'license': 'OPL-1',
    'depends': ['website', 'portal'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/data.xml',
    ],
    'installable': True,
}
