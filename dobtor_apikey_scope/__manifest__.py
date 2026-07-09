# -*- coding: utf-8 -*-
{
    'name': 'API Key Permission Scope',
    'version': '18.0.1.0.0',
    'category': 'Technical',
    'summary': 'Restrict each API key to a subset of the owner user\'s access groups',
    'description': """
API Key Permission Scope
========================

Standard Odoo API keys inherit the full permissions of the user who owns them.
This module lets you, when generating a key, tick a subset of your own access
groups so the key only carries those permissions. Existing keys can also be
adjusted individually afterwards.

Enforcement is done at the single choke point ``res.users._get_group_ids()``,
so model ACLs (``ir.model.access``), record rules (``ir.rule``) and
``has_group`` checks are all narrowed consistently. Narrowing can only tighten
access, never widen it.
""",
    'author': 'Dobtor',
    'website': 'https://www.dobtor.com',
    'depends': ['base'],
    'data': [
        'security/apikey_scope_security.xml',
        'security/ir.model.access.csv',
        'views/apikey_scope_views.xml',
    ],
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
}
