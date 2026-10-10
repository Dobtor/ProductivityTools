# -*- coding: utf-8 -*-
"""content_run：主控台送一件知識內容工作進來。

契約（主控台端見 dobtor_corpaas_knowledge/services/hub_client.py）：
  POST /ai_hub/api/v1/content_run   (JSON-RPC, X-AI-Hub-Key)
       params: {purpose, prompt, context?} → {ok, run_id, conversation}
  結果沿用既有的 /ai_hub/api/v1/run_status（只有同一個來源看得到）。

★ 與 website_chat 的差別：
  · 每次都開新 Session —— 知識內容是一件一件的工作，不是對話；續用 Session
    會帶上 `--resume`，上一件工作的上下文會污染下一件。
  · 不要求 L2：這個模式不寫對方的系統，改由 `content_enabled` 另外授權。
  · 配額與成本上限照用 —— 花的一樣是我們的額度。
"""
import logging

from odoo import _, fields, http
from odoo.http import request

from odoo.addons.dobtor_ai_hub.controllers.uplink import AiHubUplink

_logger = logging.getLogger(__name__)

MAX_PURPOSE = 120
TERMINAL_STATES = ('done', 'failed', 'interrupted', 'cancelled')


class AiHubContentUplink(AiHubUplink):

    @http.route('/ai_hub/api/v1/content_run', type='json', auth='none',
                csrf=False, methods=['POST'], readonly=False)
    def content_run(self, purpose=None, prompt=None, context=None, system=None, **kw):
        source, err = self._auth()
        if err:
            return err
        if not source.content_enabled:
            return {'ok': False, 'error': 'content_disabled',
                    'detail': _('此來源未開放知識內容')}
        if not prompt or not isinstance(prompt, str) or not prompt.strip():
            return {'ok': False, 'error': 'invalid_prompt'}
        if system is not None and not isinstance(system, str):
            return {'ok': False, 'error': 'invalid_prompt', 'detail': 'system 要是字串'}
        limit = source.content_limit()
        if len(prompt) + len(system or '') > limit:
            return {'ok': False, 'error': 'prompt_too_long',
                    'detail': _('prompt 超過上限（%s 字元）') % limit}
        blocked = source.uplink_blocked_reason()
        if blocked:
            return {'ok': False, 'error': blocked[0], 'detail': blocked[1]}

        name = (purpose if isinstance(purpose, str) else '').strip()[:MAX_PURPOSE] \
            or _('知識內容')
        env = request.env
        session = env['ai.hub.session'].sudo().create({
            'name': name,
            'source_id': source.id,
            'mode': 'content',
            # ☠️ auth='none' 的請求沒有使用者，預設值 env.user 是空的。
            'user_id': env.ref('base.user_root').id,
        })
        run = session.start_run(prompt, mode='content')
        if not run:
            return {'ok': False, 'error': 'refused',
                    'detail': _('未能建立執行（可能已達成本上限）')}
        # ★ origin 一定要標：配額與今日成本只算 uplink 的 Run，漏標就是免費額度。
        # ★ system：呼叫端的固定內容放進系統提示（吃提示詞快取）；派工在交易提交後才讀，寫在這裡來得及
        run.sudo().write({'origin': 'uplink', 'origin_message': name,
                          'extra_system_prompt': (system or '').strip() or False})
        source.sudo().uplink_last_used = fields.Datetime.now()
        # ★ uplink_used_today 是非儲存 compute，uplink_blocked_reason() 時已被快取，
        #   不清掉的話回報的剩餘額度會少算這一次。
        source.invalidate_recordset(['uplink_used_today', 'uplink_cost_today'])
        _logger.info('AI Hub content: source=%s run=%s purpose=%s（%s 字元）',
                     source.id, run.id, name, len(prompt))
        return {'ok': True, 'run_id': run.id, 'conversation': session.id, 'system_ok': True,
                'quota_left': source.uplink_quota_left(),
                'cost_left': source.uplink_cost_left()}

    @http.route()
    def run_status(self, run_id=None, refs=None, **kw):
        """content 模式的結果不經品牌過濾，原文交回主控台。

        ☠️ brand_sanitize 會把整詞「odoo」換成品牌別名：AI 回的 JSON 裡的
          `/odoo/action-…` 路徑、說明文字裡的「Odoo」會被改掉，截圖腳本因此壞掉。
          這層過濾是給**終端使用者**看的回覆用的；content 的讀者是主控台程式，
          對外內容另外有人工核准把關。
        ★ 擁有權檢查沿用上層：super() 回 ok 才代表這個 Run 屬於這把金鑰的來源。
        """
        res = super().run_status(run_id=run_id, refs=refs, **kw)
        if isinstance(res, dict) and res.get('ok'):
            run = request.env['ai.hub.run'].sudo().browse(int(run_id)).exists()
            if run and run.mode == 'content':
                res['text'] = run.stream_buffer or run.result_text or ''
                # ☠️ 上游 run_status 曾在改版時漏掉 `done`（2026-09-29 3009080），主控台就一直
                #   輪詢到逾時。content 的讀者只有主控台，這裡自己保證一定有。
                res.setdefault('done', run.state in TERMINAL_STATES)
        return res
