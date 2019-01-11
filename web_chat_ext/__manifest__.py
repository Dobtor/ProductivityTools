# -*- coding: utf-8 -*-
{
    'name': 'Web Chat Extension',
    'version': '1.0',
    'category': 'Web',
    'sequence': 6,
    'author': 'Webveer',
    'summary': 'This module allows you to attach file and emoji in anywhere in chat popup.',
    'description': """

=======================
This module allows you to attach file and emoji in anywhere in chat popup.


""",
    'depends': ['web','mail'],
    'data': [
        # 'views/web.xml'
    ],
    'qweb': [
        'static/src/xml/web.xml'
    ],
    'images': [
        'static/description/chat.jpg',
    ],
    'installable': True,
    'website': '',
    'auto_install': False,
    'price': 7,
    'currency': 'EUR',
}
