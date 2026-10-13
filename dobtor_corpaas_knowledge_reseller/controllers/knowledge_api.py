# -*- coding: utf-8 -*-
"""白標經銷商 API —— 方案知識。

    GET  /api/v1/knowledge                              我的方案知識（含專案知識）與狀態
    POST /api/v1/knowledge/project                      以一座服務建立專案知識
         body：{"external_ref": "...", "consent_note": "客戶同意的依據"}
    POST /api/v1/knowledge/<id>/refresh                 立即排一次知識更新
    GET  /api/v1/knowledge/<id>/plan                    待審或生效中的說明書製作計畫摘要
    POST /api/v1/knowledge/<id>/plan/<plan_id>/approve  核准計畫（核准前檢查不過就擋）
    GET  /api/v1/knowledge/<id>/manual                  已上線的說明書（html，圖片以 corpaas-image:<id> 標記）
    GET  /api/v1/knowledge/<id>/image/<att_id>          說明書裡的圖片（只限該說明書引用到的）

只開給這位經銷商的方案（knowledge_reseller_id）。不回程式原文、說明庫、主機資訊。
"""
import base64
import json
import logging

from odoo import http, _
from odoo.exceptions import AccessError, UserError
from odoo.http import request

from odoo.addons.dobtor_infrastructure.controllers.provision_api import (
    _authenticate, _json_response, _error,
)

_logger = logging.getLogger(__name__)

ACTIVE_PLAN_STATES = ('approved', 'expanding', 'canary', 'running', 'done', 'stopped')


class ResellerKnowledgeApi(http.Controller):

    def _auth(self):
        try:
            return _authenticate(), None
        except AccessError as e:
            return None, _error(str(e), code='unauthorized', status=401)

    def _body(self):
        try:
            data = json.loads(request.httprequest.data or '{}')
            return data if isinstance(data, dict) else {}
        except (ValueError, TypeError):
            return {}

    def _own(self, reseller, pkg_id):
        pkg = request.env['infrastructure.solution.package'].sudo().browse(pkg_id).exists()
        if not pkg or pkg.knowledge_reseller_id != reseller:
            return None
        return pkg

    def _ref_of(self, pkg):
        db = pkg.knowledge_project_database_id
        if not db:
            return None
        req = request.env['infrastructure.provision.request'].sudo().search(
            [('database_id', '=', db.id), ('external_ref', '!=', False)], limit=1)
        return req.external_ref or None

    def _plans(self, pkg):
        return request.env['corpaas.knowledge.plan'].sudo().search(
            [('package_id', '=', pkg.id)], order='id desc')

    def _summary(self, pkg):
        plans = self._plans(pkg)
        current = plans.filtered(lambda p: p.state not in ('superseded',))[:1]
        pls = request.env['corpaas.knowledge.placement'].sudo().search(
            [('package_id', '=', pkg.id), ('manual_retired', '=', False),
             ('slide_id', '!=', False)])
        return {
            'id': pkg.id,
            'name': pkg.display_name,
            'kind': pkg.knowledge_kind,
            'external_ref': self._ref_of(pkg),
            'enabled': bool(pkg.knowledge_enabled),
            'plan': {
                'id': current.id, 'state': current.state, 'version': current.version,
                'needs_approval': current.state == 'review',
                'cost_actual_usd': round(current.cost_actual or 0.0, 2),
                'stop_reason': current.stop_reason or None,
            } if current else None,
            'manual_articles': len(pls.filtered(lambda p: p.slide_id.is_published)),
        }

    # ------------------------------------------------------------------
    @http.route('/api/v1/knowledge', type='http', auth='public', methods=['GET'], csrf=False)
    def knowledge_list(self, **kw):
        reseller, err = self._auth()
        if err:
            return err
        pkgs = request.env['infrastructure.solution.package'].sudo().search(
            [('knowledge_reseller_id', '=', reseller.id)], order='id')
        return _json_response({'knowledge': [self._summary(p) for p in pkgs]})

    @http.route('/api/v1/knowledge/project', type='http', auth='public', methods=['POST'],
                csrf=False)
    def knowledge_project(self, **kw):
        reseller, err = self._auth()
        if err:
            return err
        data = self._body()
        req = request.env['infrastructure.provision.request'].sudo().search([
            ('reseller_id', '=', reseller.id),
            ('external_ref', '=', data.get('external_ref') or '')], limit=1)
        if not req.database_id:
            return _error(_('Service not found.'), code='not_found', status=404)
        try:
            pkg = request.env['infrastructure.solution.package'].sudo()._reseller_create_project(
                reseller, req.database_id, data.get('consent_note'))
        except UserError as e:
            return _error(str(e), code='conflict', status=409)
        _logger.info('project knowledge %s created by reseller %s for %s',
                     pkg.id, reseller.display_name, req.external_ref)
        return _json_response(self._summary(pkg), status=201)

    @http.route('/api/v1/knowledge/<int:pkg_id>/refresh', type='http', auth='public',
                methods=['POST'], csrf=False)
    def knowledge_refresh(self, pkg_id, **kw):
        reseller, err = self._auth()
        if err:
            return err
        pkg = self._own(reseller, pkg_id)
        if not pkg:
            return _error(_('Knowledge not found.'), code='not_found', status=404)
        pkg.knowledge_enqueue_refresh(full=False, reason='manual')
        return _json_response({'id': pkg.id, 'status': 'queued'}, status=202)

    @http.route('/api/v1/knowledge/<int:pkg_id>/plan', type='http', auth='public',
                methods=['GET'], csrf=False)
    def knowledge_plan(self, pkg_id, **kw):
        reseller, err = self._auth()
        if err:
            return err
        pkg = self._own(reseller, pkg_id)
        if not pkg:
            return _error(_('Knowledge not found.'), code='not_found', status=404)
        plan = self._plans(pkg).filtered(lambda p: p.state != 'superseded')[:1]
        if not plan:
            return _json_response({'id': pkg.id, 'plan': None})
        items = {}
        for it in plan.item_ids:
            items.setdefault(it.kind, []).append({
                'id': it.id, 'name': it.name, 'summary': (it.summary or '')[:500],
                'answer': it.answer or None, 'confirmed': bool(it.confirmed)})
        return _json_response({'id': pkg.id, 'plan': {
            'id': plan.id, 'state': plan.state, 'version': plan.version,
            'reader': plan.reader, 'budget_usd': plan.budget,
            'cost_estimate_usd': round(plan.cost_estimate or 0.0, 2),
            'items': items,
        }})

    @http.route('/api/v1/knowledge/<int:pkg_id>/plan/<int:plan_id>/approve', type='http',
                auth='public', methods=['POST'], csrf=False)
    def knowledge_plan_approve(self, pkg_id, plan_id, **kw):
        reseller, err = self._auth()
        if err:
            return err
        pkg = self._own(reseller, pkg_id)
        plan = request.env['corpaas.knowledge.plan'].sudo().browse(plan_id).exists()
        if not pkg or not plan or plan.package_id != pkg:
            return _error(_('Plan not found.'), code='not_found', status=404)
        if plan.state != 'review':
            return _error(_('Only plans under review can be approved.'),
                          code='not_ready', status=409)
        check = plan.run_checks('t2')
        if check.state == 'block':
            return _error(_('Pre-approval checks failed: %s') % check.blocking_text(),
                          code='checks_failed', status=409)
        plan.message_post(body=_('由經銷商 %s 經白標後台核准。') % reseller.display_name)
        plan._plan_approve('manual')
        return _json_response({'id': pkg.id, 'plan_id': plan.id, 'status': 'approved'})

    @http.route('/api/v1/knowledge/<int:pkg_id>/manual', type='http', auth='public',
                methods=['GET'], csrf=False)
    def knowledge_manual(self, pkg_id, **kw):
        reseller, err = self._auth()
        if err:
            return err
        pkg = self._own(reseller, pkg_id)
        if not pkg:
            return _error(_('Knowledge not found.'), code='not_found', status=404)
        payload, _images = pkg._reseller_manual_export()
        return _json_response(payload)

    @http.route('/api/v1/knowledge/<int:pkg_id>/image/<int:att_id>', type='http',
                auth='public', methods=['GET'], csrf=False)
    def knowledge_image(self, pkg_id, att_id, **kw):
        reseller, err = self._auth()
        if err:
            return err
        pkg = self._own(reseller, pkg_id)
        if not pkg:
            return _error(_('Knowledge not found.'), code='not_found', status=404)
        _payload, images = pkg._reseller_manual_export()
        if att_id not in images:
            return _error(_('Image not found.'), code='not_found', status=404)
        att = request.env['ir.attachment'].sudo().browse(att_id).exists()
        if not att or not att.datas:
            return _error(_('Image not found.'), code='not_found', status=404)
        return request.make_response(
            base64.b64decode(att.datas),
            headers=[('Content-Type', att.mimetype or 'application/octet-stream'),
                     ('Cache-Control', 'private, max-age=3600')])
