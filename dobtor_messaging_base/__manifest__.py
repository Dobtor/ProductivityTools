# -*- coding: utf-8 -*-
{
    'name': 'Dobtor Messaging Base',
    'version': '18.0.1.1.0',
    'category': 'Productivity/Discuss',
    'summary': 'Provider-agnostic base for external messaging (LINE, Telegram, ...) '
               'plus a company-centric Discuss member panel.',
    'description': """
Dobtor Messaging Base
=====================
共用基底，涵蓋兩大面向：

1. 外部訊息平台抽象（provider 無關）
   * 中性 ``discuss.channel`` 層（provider / source 身分、進出站同步骨架 + dispatcher）。
   * ``messaging.account`` —— 外部身分標準庫（一個聯絡人可掛多個平台帳號）。
   * SSRF 安全媒體下載 mixin、webhook 共用骨架、partner 綁定精靈。
   * 通用前端：無 res.users 聯絡人的 partner 卡、頭像點擊 patch、thread 旗標。
   平台模組（``dobtor_line_message``、``dobtor_telegram_message``）depends 本模組，
   只實作協定特定部分（webhook 驗證、Update 解析、API client、媒體取得）。

2. 以「公司」為主軸的 Discuss 成員面板
   * 公司是統一概念 —— 客戶公司與內部公司一視同仁。
   * 成員依其所屬公司分組（partner.parent_id / 內部使用者退回 user.company_id）。
   * 面板頂部可加入公司（選既有或直接新增），作為分組與指派目標。
   * 可直接把成員指派到公司（寫回 res.partner.parent_id）。
   * 每個公司桶內保留官方「線上 / 離線」呈現。

詳見 ``docs/DESIGN.md``。
    """,
    'author': 'Dobtor SI',
    'website': 'https://www.dobtor.com',
    'depends': [
        'mail',   # discuss.channel, mail.message, personas
        'bus',    # real-time notifications
    ],
    'data': [
        'security/messaging_security.xml',
        'security/ir.model.access.csv',
        'views/messaging_account_views.xml',
        'views/messaging_partner_link_views.xml',
        'views/res_partner_views.xml',
        'views/messaging_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'dobtor_messaging_base/static/src/**/*',
        ],
    },
    'installable': True,
    'auto_install': False,
    'application': False,
    'license': 'LGPL-3',
}
