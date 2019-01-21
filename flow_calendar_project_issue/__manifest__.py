# -*- coding: utf-8 -*-
# Copyright 2017-2018 Nova Code (http://www.novacode.nl)
# See LICENSE file for full licensing details.

{
    'name': 'Flow Calendar Project Issue',
    'summary': 'Plan your Project Issues in the Odoo Calendar.',
    'description': 'Plan your Project Issues in the Odoo Calendar.',
    'version': '1.0',
    'author': 'Nova Code',
    'website': 'https://www.novacode.nl',
    'license': 'OPL-1',
    'price': 50.00,
    'currency': 'EUR',
    'category': 'Project',
    'depends': [
        'base',
        'flow_calendar',
        'project_issue',
        'web_calendar'
    ],
    'data': [
        'views/flow_calendar_project_issue_views.xml',
    ],
    'qweb': [
        'static/src/xml/flow_calendar_project_issue.xml'
    ],
    'images': [
        'static/description/flow_calendar_project_issue_banner.jpg',
    ]
}
