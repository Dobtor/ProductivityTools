# -*- coding: utf-8 -*-
"""主控台 → AI Hub 的 content 模式呼叫。

契約（由 dobtor_ai_hub_content 提供）：
  POST {hub}/ai_hub/api/v1/content_run   (JSON-RPC, X-AI-Hub-Key)
       params: {purpose, prompt, context: {...}} → {ok, run_id}
  POST {hub}/ai_hub/api/v1/run_status    (既有)  params: {run_id} → {done, state, text, cost_usd}

★ AI 只回文字，JSON 由主控台解析；解析不了就當失敗（不猜）。
"""
import json
import logging
import re
import time

import requests

_logger = logging.getLogger(__name__)

TERMINAL_STATES = ('done', 'failed', 'interrupted', 'cancelled')

_JSON_BLOCK = re.compile(r'```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```', re.S)


class HubError(Exception):
    pass


class BudgetExceeded(HubError):
    pass


#: Hub 每次受理 content_run 都回報來源的今日剩餘（成本／次數）；最近一次的值放這裡，
#: 由 corpaas.knowledge.ai 存進系統參數給成本規劃器（D3）用。
LAST_QUOTA = {}

#: Hub 拒絕的原因裡，代表「今日額度用完」的：當預算用完處理（留到隔天），不是失敗
QUOTA_ERRORS = ('cost_exceeded', 'quota_exceeded')


def _rpc(url, key, params, timeout=60):
    """☠️ 網路錯誤一律轉成 HubError：呼叫端只接 HubError，漏出一個 ConnectionError
    就讓整次知識更新回滾（佇列不重試），連那次的帳都不見。"""
    payload = {'jsonrpc': '2.0', 'method': 'call', 'params': params, 'id': 1}
    try:
        resp = requests.post(url, json=payload, timeout=timeout,
                             headers={'X-AI-Hub-Key': key})
        resp.raise_for_status()
        body = resp.json()
    except (requests.RequestException, ValueError) as e:
        raise HubError('AI Hub 連線失敗：%s' % str(e)[:300]) from None
    if body.get('error'):
        raise HubError(json.dumps(body['error'])[:1000])
    return body.get('result') or {}


def extract_json(text):
    """從模型回覆取出 JSON：優先 ```json 區塊，其次整段。"""
    if not text:
        raise HubError('AI 沒有回覆內容')
    m = _JSON_BLOCK.search(text)
    candidate = m.group(1) if m else text.strip()
    try:
        return json.loads(candidate)
    except ValueError:
        start = min([i for i in (candidate.find('{'), candidate.find('[')) if i >= 0] or [-1])
        if start >= 0:
            try:
                return json.loads(candidate[start:])
            except ValueError:
                pass
    raise HubError('AI 回覆不是合法 JSON：%s' % text[:500])


def call(hub_url, key, purpose, prompt, context=None, poll_every=5, timeout=900, system=None):
    """送出並等待完成。回傳 (text, cost_usd, run_id)。

    system：固定內容（規則、詞彙、示範資料清單），Hub 放進系統提示，連續呼叫內容相同時吃提示詞快取。
    ★ 只有 Hub 支援（content_run 回 system_ok）時才可以送；呼叫端由系統參數開關決定。"""
    if not hub_url or not key:
        raise HubError('尚未設定 AI Hub 網址或金鑰')
    base = hub_url.rstrip('/')
    params = {'purpose': purpose, 'prompt': prompt, 'context': context or {}}
    if system:
        params['system'] = system
    res = _rpc(base + '/ai_hub/api/v1/content_run', key, params)
    if res.get('ok') and system and not res.get('system_ok'):
        # 舊版 Hub 不認得 system：這次的固定內容沒送到，不能用這個結果
        raise HubError('AI Hub 不支援 system（請先升級 dobtor_ai_hub_content，或關掉 corpaas_knowledge.hub_system_prompt）')
    if not res.get('ok'):
        err = BudgetExceeded if res.get('error') in QUOTA_ERRORS else HubError
        if err is BudgetExceeded:
            LAST_QUOTA.update(cost_left=0.0, at=time.time())
        raise err('AI Hub 拒絕：%s %s' % (res.get('error'), res.get('detail') or ''))
    if 'cost_left' in res or 'quota_left' in res:
        LAST_QUOTA.update(cost_left=res.get('cost_left'), quota_left=res.get('quota_left'),
                          at=time.time())
    run_id = res['run_id']
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(poll_every)
        st = _rpc(base + '/ai_hub/api/v1/run_status', key, {'run_id': run_id})
        if not st.get('ok'):
            raise HubError('查詢執行狀態失敗：%s' % st.get('error'))
        # ★ 除了 `done` 也看 state：Hub 的回應欄位曾在改版時被漏掉，只認單一欄位
        #   會讓每次呼叫都輪詢到逾時。
        if st.get('done') or st.get('state') in TERMINAL_STATES:
            if st.get('state') != 'done':
                raise HubError('AI 執行未完成（%s）：%s' % (st.get('state'),
                                                         (st.get('text') or '')[:500]))
            return st.get('text') or '', float(st.get('cost_usd') or 0.0), run_id
    raise HubError('AI 執行逾時（run %s）' % run_id)
