# -*- coding: utf-8 -*-

import binascii

from odoo import fields, http, _
from odoo.exceptions import AccessError, MissingError
from odoo.http import request

from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager


class MeetingPortal(CustomerPortal):
    """會議記錄 Portal 控制器

    Sudo 使用原則：
    - 僅在已通過 access_token / signature_token 驗證後使用 sudo
    - 所有 sudo search 必須帶 note_id 過濾，避免跨 note 資料洩漏
    - 公開訪客（_is_public）必須持 signature_token 才能留言/被識別
    """

    # ===== 內部 helper =====
    @staticmethod
    def _safe_int(val):
        try:
            return int(val)
        except (ValueError, TypeError):
            return False

    @staticmethod
    def _lookup_signature(note_sudo, sig_id, signature_token):
        """依 note_id + signature_token 精確查找單筆簽名記錄

        此處用 sudo 因為 public user 沒有 note.signature 讀權限，
        但 domain 鎖住 note_id 與 token，不會洩漏他人資料。
        """
        if not (note_sudo and sig_id and signature_token):
            return None
        return request.env['note.signature'].sudo().search([
            ('id', '=', sig_id),
            ('access_token', '=', signature_token),
            ('note_id', '=', note_sudo.id),
        ], limit=1) or None

    def _prepare_home_portal_values(self, counters):
        """準備首頁計數器"""
        values = super()._prepare_home_portal_values(counters)
        partner = request.env.user.partner_id

        if 'meeting_count' in counters:
            NoteNote = request.env['note.note']
            meeting_count = NoteNote.search_count(
                self._prepare_meetings_domain(partner)
            ) if NoteNote.has_access('read') else 0
            values['meeting_count'] = meeting_count

        return values

    def _prepare_meetings_domain(self, partner):
        """準備會議記錄的搜尋條件

        單次查詢：直接在 domain 中使用 calendar_event_ids.partner_ids
        取代原本的兩次 search。
        """
        return [
            ('note_type', '=', 'meeting'),
            '|',
            ('signer_ids', 'in', [partner.id]),
            ('calendar_event_ids.partner_ids', 'in', [partner.id]),
        ]

    def _get_meeting_searchbar_sortings(self):
        """會議記錄排序選項"""
        return {
            'date': {'label': _('Date'), 'order': 'create_date desc'},
            'name': {'label': _('Name'), 'order': 'name'},
            'state': {'label': _('Status'), 'order': 'state'},
        }

    def _get_meeting_searchbar_filters(self):
        """會議記錄篩選選項"""
        return {
            'all': {'label': _('All'), 'domain': []},
            'draft': {'label': _('Draft'), 'domain': [('state', '=', 'draft')]},
            'sent': {'label': _('Sent'), 'domain': [('state', '=', 'sent')]},
            'partial': {'label': _('Partially Signed'), 'domain': [('state', '=', 'partial')]},
            'signed': {'label': _('Fully Signed'), 'domain': [('state', '=', 'signed')]},
        }

    @http.route(['/my/meetings', '/my/meetings/page/<int:page>'],
                type='http', auth="user", website=True)
    def portal_my_meetings(self, page=1, date_begin=None, date_end=None,
                           sortby=None, filterby=None, **kwargs):
        """會議記錄列表"""
        NoteNote = request.env['note.note']
        partner = request.env.user.partner_id

        if not sortby:
            sortby = 'date'

        searchbar_sortings = self._get_meeting_searchbar_sortings()
        searchbar_filters = self._get_meeting_searchbar_filters()

        if not filterby:
            filterby = 'all'

        domain = self._prepare_meetings_domain(partner)
        domain += searchbar_filters[filterby]['domain']

        if date_begin and date_end:
            domain += [
                ('create_date', '>', date_begin),
                ('create_date', '<=', date_end)
            ]

        # 計算筆數
        meeting_count = NoteNote.search_count(domain)

        # 分頁
        pager = portal_pager(
            url='/my/meetings',
            url_args={'date_begin': date_begin, 'date_end': date_end,
                      'sortby': sortby, 'filterby': filterby},
            total=meeting_count,
            page=page,
            step=self._items_per_page,
        )

        # 查詢資料
        sort_order = searchbar_sortings[sortby]['order']
        meetings = NoteNote.search(
            domain,
            order=sort_order,
            limit=self._items_per_page,
            offset=pager['offset'],
        )

        values = self._prepare_portal_layout_values()
        values.update({
            'date': date_begin,
            'meetings': meetings.sudo(),
            'page_name': 'meeting',
            'pager': pager,
            'default_url': '/my/meetings',
            'sortby': sortby,
            'filterby': filterby,
            'searchbar_sortings': searchbar_sortings,
            'searchbar_filters': searchbar_filters,
        })

        return request.render('dobtor_meeting_minutes.portal_my_meetings', values)

    @http.route(['/my/meeting/<int:note_id>'],
                type='http', auth="public", website=True)
    def portal_meeting_page(self, note_id, access_token=None,
                            signature_id=None, signature_token=None,
                            report_type=None, download=False, message=False, **kwargs):
        """單一會議記錄檢視頁面"""
        try:
            # active_test=False: 已封存的會議記錄仍可透過 Portal 檢視/簽名
            note_sudo = self._document_check_access(
                'note.note', note_id, access_token=access_token
            )
        except (AccessError, MissingError):
            return request.redirect('/my')

        # 確認是會議記錄
        if note_sudo.note_type != 'meeting':
            return request.redirect('/my')

        # PDF 下載
        if report_type in ('html', 'pdf', 'text'):
            return self._show_report(
                model=note_sudo,
                report_type=report_type,
                report_ref='dobtor_meeting_minutes.action_report_meeting_minutes',
                download=download,
            )

        # 記錄瀏覽 — 僅在可識別真實身份時留言，避免假冒
        if request.env.user.share and access_token:
            today = fields.Date.today().isoformat()
            session_key = f'view_meeting_{note_sudo.id}'
            if request.session.get(session_key) != today:
                request.session[session_key] = today
                viewer_partner = None
                if not request.env.user._is_public():
                    viewer_partner = request.env.user.partner_id
                elif signature_id and signature_token:
                    sig = self._lookup_signature(
                        note_sudo, self._safe_int(signature_id), signature_token,
                    )
                    if sig:
                        viewer_partner = sig.partner_id
                if viewer_partner:
                    note_sudo.message_post(
                        author_id=viewer_partner.id,
                        body=_('Meeting minutes viewed by %s', viewer_partner.name),
                        message_type='notification',
                    )

        # 檢查當前用戶的簽名狀態
        # 安全備註：此處 sudo 僅限於以 signature_token 驗證時，
        # domain 已鎖定 note_id + access_token，無法跨 note 取得他人簽名
        current_signature = None
        needs_signature = False
        partner = None

        if signature_id and signature_token:
            sig_id = self._safe_int(signature_id)
            if sig_id:
                signature = self._lookup_signature(
                    note_sudo, sig_id, signature_token,
                )
                if signature:
                    current_signature = signature
                    partner = signature.partner_id
                    needs_signature = note_sudo._has_to_be_signed_by(partner)
        elif not request.env.user._is_public():
            # 登入用戶
            partner = request.env.user.partner_id
            current_signature = note_sudo._get_signature_for_partner(partner)
            needs_signature = note_sudo._has_to_be_signed_by(partner)

        # 取得附件 — domain 已鎖定 note_id，sudo 作用範圍最小化
        attachments = request.env['ir.attachment'].sudo().search([
            ('res_model', '=', 'note.note'),
            ('res_id', '=', note_sudo.id),
        ])

        # 對於登入用戶，使用其簽名記錄的 id 和 token
        if current_signature and not signature_id:
            signature_id = current_signature.id
            signature_token = current_signature.access_token

        values = {
            'note': note_sudo,
            'page_name': 'meeting',
            'message': message,
            'report_type': 'html',
            'partner': partner,
            'current_signature': current_signature,
            'needs_signature': needs_signature,
            'signature_id': signature_id,
            'signature_token': signature_token,
            'attachments': attachments,
        }

        history_session_key = 'my_meetings_history'
        values = self._get_page_view_values(
            note_sudo, access_token, values, history_session_key, False, **kwargs
        )

        return request.render('dobtor_meeting_minutes.meeting_portal_template', values)

    @http.route(['/my/meeting/<int:note_id>/sign'],
                type='json', auth="public", website=True)
    def portal_meeting_sign(self, note_id, access_token=None,
                            signature_id=None, signature_token=None,
                            name=None, signature=None):
        """簽名確認"""
        # 驗證文件存取權（JSON route 需從 query string 讀取 token）
        args = request.httprequest.args
        access_token = access_token or args.get('access_token')
        signature_id = signature_id or args.get('signature_id')
        signature_token = signature_token or args.get('signature_token')
        try:
            note_sudo = self._document_check_access(
                'note.note', note_id, access_token=access_token
            )
        except (AccessError, MissingError):
            return {'error': _('Invalid meeting minutes.')}

        # 確認是會議記錄
        if note_sudo.note_type != 'meeting':
            return {'error': _('This is not a meeting minutes.')}

        # 驗證簽名記錄
        signature_record = None
        if signature_id and signature_token:
            signature_record = self._lookup_signature(
                note_sudo, self._safe_int(signature_id), signature_token,
            )
        elif not request.env.user._is_public():
            partner = request.env.user.partner_id
            signature_record = note_sudo._get_signature_for_partner(partner)

        if not signature_record:
            return {'error': _('Invalid signature request.')}

        if signature_record.is_signed:
            return {'error': _('This has already been signed.')}

        if not signature:
            return {'error': _('Signature is missing.')}

        # 執行簽名
        try:
            signature_record.action_sign(name, signature)
        except (TypeError, binascii.Error):
            return {'error': _('Invalid signature data.')}

        # 發送通知
        author = signature_record.partner_id
        note_sudo.message_post(
            author_id=author.id,
            body=_('Meeting minutes signed by %s', name or author.name),
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )

        # 如果全部簽名完成，生成最終 PDF
        if note_sudo.all_signed:
            pdf = request.env['ir.actions.report'].sudo()._render_qweb_pdf(
                'dobtor_meeting_minutes.action_report_meeting_minutes',
                [note_sudo.id]
            )[0]
            note_sudo.message_post(
                attachments=[(f'{note_sudo.name} - Signed.pdf', pdf)],
                body=_('All signers have signed. Final signed document attached.'),
                message_type='notification',
            )

        # 建構重導向 URL
        query_params = f'?access_token={note_sudo.access_token}'
        if signature_id and signature_token:
            query_params += f'&signature_id={signature_id}&signature_token={signature_token}'
        query_params += '&message=sign_ok'

        return {
            'force_refresh': True,
            'redirect_url': f'{note_sudo.access_url}{query_params}',
        }

    @http.route(['/my/meeting/<int:note_id>/message'],
                type='http', auth="public", methods=['POST'], website=True)
    def portal_meeting_post_message(self, note_id, access_token=None,
                                    signature_id=None, signature_token=None, **kwargs):
        """Portal 上留言評論

        安全性：
        - 公開用戶必須同時提供有效的 signature_id + signature_token 才能留言，
          防止任何持有 access_token 的訪客假冒簽名者發言。
        - 若僅持 access_token（無 signature token）且未登入，拒絕留言。
        - author_id 嚴格對應到簽名記錄的 partner_id 或登入用戶的 partner_id，
          不再退回使用任意 signer/attendee。
        """
        try:
            note_sudo = self._document_check_access(
                'note.note', note_id, access_token=access_token
            )
        except (AccessError, MissingError):
            return request.redirect('/my')

        message_content = (kwargs.get('message') or '').strip()
        if not message_content:
            return request.redirect(note_sudo.get_portal_url())

        if len(message_content) > 4000:
            message_content = message_content[:4000]

        author_partner = None
        if not request.env.user._is_public():
            author_partner = request.env.user.partner_id
        elif signature_id and signature_token:
            sig = self._lookup_signature(
                note_sudo, self._safe_int(signature_id), signature_token,
            )
            if sig:
                author_partner = sig.partner_id

        if not author_partner:
            # 公開訪客無 signature token → 拒絕留言
            return request.redirect(f'{note_sudo.get_portal_url()}&message=not_authorized')

        note_sudo.message_post(
            author_id=author_partner.id,
            body=message_content,
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )
        return request.redirect(note_sudo.get_portal_url())

    @http.route(['/my/meeting/<int:note_id>/attachment/<int:attachment_id>'],
                type='http', auth="public", website=True)
    def portal_meeting_attachment(self, note_id, attachment_id,
                                  access_token=None, **kwargs):
        """下載會議記錄附件"""
        try:
            note_sudo = self._document_check_access(
                'note.note', note_id, access_token=access_token
            )
        except (AccessError, MissingError):
            return request.redirect('/my')

        # 驗證附件屬於此會議記錄
        attachment = request.env['ir.attachment'].sudo().search([
            ('id', '=', attachment_id),
            ('res_model', '=', 'note.note'),
            ('res_id', '=', note_sudo.id),
        ], limit=1)

        if not attachment:
            return request.redirect('/my')

        return request.env['ir.binary']._get_stream_from(
            attachment
        ).get_response(as_attachment=True)
