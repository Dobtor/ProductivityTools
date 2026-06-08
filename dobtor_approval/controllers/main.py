# -*- coding: utf-8 -*-
"""前端攔截與能力查詢 controller — DESIGN.md §5.2-A、TIERS §3.1。"""
import logging

from odoo import http, _
from odoo.http import request

_logger = logging.getLogger(__name__)


class DobtorApprovalController(http.Controller):

    @http.route('/dobtor_approval/enabled_features', type='json', auth='user')
    def enabled_features(self):
        """回傳目前公司啟用的能力 key list（設計器據以過濾調色盤/面板）。"""
        company = request.env.company
        return sorted(company._bpmn_enabled_features())

    @http.route('/dobtor_approval/check_bpmn_gate', type='json', auth='user')
    def check_bpmn_gate(self, model, method, res_id):
        """前端按鈕點擊前檢查：此 (model, method, res_id) 是否需簽核且未核准。

        :return: {
            'gated': bool,           # 是否被閘門攔截
            'already_approved': bool,
            'process_name': str,
        }
        """
        env = request.env
        if not env.company._bpmn_feature_enabled('action_gate'):
            return {'gated': False}
        if model not in env:
            return {'gated': False}
        record = env[model].browse(int(res_id)).exists()
        if not record:
            return {'gated': False}
        gate = env['bpmn.action.gate']._match(model, method, record)
        if not gate:
            return {'gated': False}
        approved = env['bpmn.process.instance'].search_count([
            ('process_id', '=', gate.process_id.id),
            ('res_model', '=', model),
            ('res_id', '=', record.id),
            ('state', '=', 'approved'),
        ])
        return {
            'gated': not bool(approved),
            'already_approved': bool(approved),
            'process_name': gate.process_id.name,
        }

    @http.route('/dobtor_approval/start_gate', type='json', auth='user')
    def start_gate(self, model, method, res_id):
        """前端確認攔截後，主動起一個簽核實例（記 pending action）。"""
        env = request.env
        if not env.company._bpmn_feature_enabled('action_gate'):
            return {'started': False}
        if model not in env:
            return {'started': False}
        record = env[model].browse(int(res_id)).exists()
        if not record:
            return {'started': False}
        gate = env['bpmn.action.gate']._match(model, method, record)
        if not gate:
            return {'started': False}
        running = env['bpmn.process.instance'].search_count([
            ('process_id', '=', gate.process_id.id),
            ('res_model', '=', model),
            ('res_id', '=', record.id),
            ('state', '=', 'running'),
        ])
        if running:
            return {'started': True, 'already_running': True,
                    'process_name': gate.process_id.name}
        instance = gate.process_id.start(
            res_model=model, res_id=record.id, applicant=env.user,
            pending_action={'model': model, 'method': method, 'res_ids': [record.id]})
        import json
        instance.write({
            'gate_id': gate.id,
            'gate_snapshot': json.dumps(gate._snapshot(record), default=str),
        })
        return {'started': True, 'process_name': gate.process_id.name}
