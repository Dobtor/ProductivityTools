"""Portal 路由（W2-3 P0-1）

提供 portal user（如 ChienYi 承包商、業主代表）線上編輯被授權的文件。

設計原則：
    - 沿用 Odoo 18 的 portal.CustomerPortal（標準 portal 框架）
    - 不依賴 construction_portal 的 cy_pc_layout（保持模組獨立性）
    - ChienYi 整合層（doc.linked.mixin，W5-6）才會用 cy_pc_layout

權限：
    - portal user 只能看 collaborator_ids 包含自己的文件（ir.rule 已限制）
    - portal user 不能建立、不能刪除（ACL 鎖死）
    - 寫入透過 doc.check_access_rule('write') 二次驗證
"""

import json
import logging

from odoo import http
from odoo.exceptions import AccessError, MissingError
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager

_logger = logging.getLogger(__name__)


class DobtorDocPortal(CustomerPortal):
    """Portal 端文件存取入口。"""

    # ── /my counters ─────────────────────────────────────────────────

    def _prepare_home_portal_values(self, counters):
        """在 /my 首頁顯示「我的文件」計數。"""
        values = super()._prepare_home_portal_values(counters)
        if 'doc_count' in counters:
            values['doc_count'] = self._get_documents_domain_count()
        return values

    def _get_documents_domain(self):
        """目前 portal user 可看到的文件 domain（依靠 ir.rule 過濾）。"""
        # ir.rule rule_doc_document_portal 已限制只能看 collaborator_ids in [user.id]
        # 這裡可加額外條件（例如排除 archived）
        return [('active', '=', True)] if 'active' in request.env['doc.document']._fields else []

    def _get_documents_domain_count(self):
        return request.env['doc.document'].search_count(self._get_documents_domain())

    # ── /my/documents 列表 ────────────────────────────────────────────

    @http.route(['/my/documents', '/my/documents/page/<int:page>'],
                type='http', auth='user', website=True)
    def portal_my_documents(self, page=1, sortby='date', search=None, **kw):
        """文件列表（portal + internal user 都可用）。

        - portal user：受 ir.rule 限制，只看到自己被加為協作者的文件
        - internal user：依 group_doc_editor 規則（自己的或協作者的或同公司的）
        """
        DocDocument = request.env['doc.document']

        domain = self._get_documents_domain()
        if search:
            domain += [('name', 'ilike', search)]

        sort_options = {
            'date': {'label': '最後更新', 'order': 'write_date desc'},
            'name': {'label': '名稱', 'order': 'name asc'},
        }
        order = sort_options.get(sortby, sort_options['date'])['order']

        total = DocDocument.search_count(domain)
        page_size = 20

        pager = portal_pager(
            url='/my/documents',
            url_args={'sortby': sortby, 'search': search},
            total=total,
            page=page,
            step=page_size,
        )

        documents = DocDocument.search(
            domain,
            order=order,
            limit=page_size,
            offset=pager['offset'],
        )

        values = {
            'documents': documents,
            'page_name': 'documents',
            'pager': pager,
            'sortby': sortby,
            'search': search or '',
            'sort_options': sort_options,
            'default_url': '/my/documents',
        }
        return request.render('dobtor_doc_editor.portal_my_documents', values)

    # ── /my/documents/<id> 編輯 ──────────────────────────────────────

    @http.route(['/my/documents/<int:doc_id>'],
                type='http', auth='user', website=True)
    def portal_document_view(self, doc_id, access_token=None, **kw):
        """文件檢視 / 編輯頁。

        portal user 看到此頁時，doc_editor JS 會載入 canvas-editor。
        實際讀寫透過既有的 /dobtor_doc/load 與 /dobtor_doc/save JSON 路由。
        """
        try:
            doc_sudo = self._document_check_access('doc.document', doc_id, access_token)
        except (AccessError, MissingError):
            return request.redirect('/my')

        # 計算 portal user 是否為協作者：ir.rule 已限制 portal user 只能看到自己是
        # collaborator 的文件，所以走到這一行的 portal user 必然有寫入權限。保留旗標
        # 給 internal user 場景（例如 admin 用 portal URL 預覽他人的文件）使用。
        user = request.env.user
        is_portal_user = user.has_group('base.group_portal')
        is_collaborator = user in doc_sudo.collaborator_ids
        # readonly 條件：非 collaborator 且非 internal owner / company 同事
        # （internal user 走 ir.rule 規則 group_doc_editor，已在 controller 上面驗證 read 權限）
        readonly = is_portal_user and not is_collaborator

        # 給 <owl-component props="..."> 用的 JSON 字串（public_component_service 會 JSON.parse）
        editor_props_json = json.dumps({
            'docId': doc_sudo.id,
            'readonly': readonly,
        })

        values = {
            'doc': doc_sudo,
            'page_name': 'documents',
            'is_portal_user': is_portal_user,
            'editor_props_json': editor_props_json,
            'editor_readonly': readonly,
        }
        return request.render('dobtor_doc_editor.portal_document_view', values)

    def _document_check_access(self, model_name, doc_id, access_token=None):
        """權限檢查（沿用 CustomerPortal 標準方式）。"""
        document_sudo = request.env[model_name].browse(doc_id).sudo().exists()
        if not document_sudo:
            raise MissingError(f"找不到文件 id={doc_id}")
        try:
            # 不用 sudo 觸發 ir.rule 檢查
            request.env[model_name].browse(doc_id).check_access_rights('read')
            request.env[model_name].browse(doc_id).check_access_rule('read')
        except AccessError:
            if not access_token:
                raise
            # access_token 機制可在後續 sprint 加上「公開連結分享」時實作
            raise
        return document_sudo
