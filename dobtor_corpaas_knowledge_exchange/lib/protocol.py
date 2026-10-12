# -*- coding: utf-8 -*-
"""主從交換協定（知識主從改版計畫第 7 節）。純函式，不碰 ORM。

簽章沿用 dobtor_ai_bridge_help：
  X-KB-Peer: <送件端主控台代碼>、X-KB-Timestamp: <unix 秒>、
  X-KB-Signature: hex(hmac_sha256(金鑰, b"<ts>." + 原始 body bytes))
params 一律帶 schema_version 與 nonce（nonce 被簽章涵蓋，接收端擋重送）。
"""
import hashlib
import hmac
import json
import time
import uuid

import requests

SCHEMA_VERSION = 1
MAX_SKEW = 300

#: 交換的類別 → 模型、識別方式、要帶的欄位。
#:   key      事實類用自然鍵（內容雜湊天生可攜）；範本類用 kb_uid
#:   extra    建立紀錄需要、但不算內容的欄位（不進內容雜湊）
#:   category fact＝依雜湊直接入庫；template＝上收提案、人工審核
KINDS = {
    'code_def': {
        'model': 'corpaas.knowledge.code_def', 'category': 'fact',
        'key': ('def_hash', 'method', 'module'), 'extra': ('path', 'line_start', 'line_end'),
    },
    'code_fact': {
        'model': 'corpaas.knowledge.code_fact', 'category': 'fact',
        'key': ('subject', 'chain_hash'), 'extra': ('verified', 'state'),
    },
    'module_summary': {
        'model': 'corpaas.knowledge.module_summary', 'category': 'fact',
        'key': ('module', 'dir_hash'), 'extra': ('source', 'git_revision'),
    },
    'capability': {
        'model': 'corpaas.knowledge.capability', 'category': 'template',
        'key': ('kb_uid',), 'extra': ('code',),
    },
    'scenario': {
        'model': 'corpaas.knowledge.scenario', 'category': 'template',
        'key': ('kb_uid',), 'extra': ('code',),
    },
    'seed_pack': {
        'model': 'corpaas.knowledge.seed_pack', 'category': 'template',
        'key': ('kb_uid',), 'extra': ('code',),
    },
    'role': {
        'model': 'corpaas.knowledge.role', 'category': 'template',
        'key': ('kb_uid',), 'extra': ('code',),
    },
    'rule': {
        'model': 'corpaas.knowledge.rule', 'category': 'template',
        'key': ('kb_uid',), 'extra': ('source', 'sequence'),
    },
    #: 主體方案的產出：只從主體流向從屬（從屬不送、主體不收）。依（功能點, 畫面指紋）查：
    #: 從屬的畫面指紋與主體相同就引用主體版本（計畫第 11 節）。
    #: adopt_local=False：自然鍵相同的本地區塊（從屬自己寫的、可能已被客戶文章引用）不被改成鏡像。
    'step_block': {
        'model': 'corpaas.knowledge.step_block', 'category': 'output', 'adopt_local': False,
        'key': ('feature_key', 'fingerprint'), 'extra': ('anchor',),
    },
}
#: 鏡像 upsert 的順序：結論要引用段落，段落先寫
ORDER = ('code_def', 'module_summary', 'code_fact', 'capability', 'scenario', 'seed_pack', 'role', 'rule',
         'step_block')
#: 方案可用模組清單（不是可交換紀錄，發佈清單特別處理）
PACKAGE_KIND = 'package'
MODEL_KIND = {v['model']: k for k, v in KINDS.items()}

#: 主體回覆送件的狀態
EXISTS, INGESTED, REVIEW, REJECTED = 'exists', 'ingested', 'review', 'rejected'


def sign(key, ts, body):
    return hmac.new(key.encode('utf-8'), ('%s.' % ts).encode('ascii') + body, hashlib.sha256).hexdigest()


def verify(key, ts, body, sig, now=None):
    """None＝通過；否則回錯誤代碼。"""
    if not (key and sig and ts):
        return 'unsigned'
    try:
        skew = abs((now or time.time()) - int(ts))
    except (TypeError, ValueError):
        return 'bad_signature'
    if skew > MAX_SKEW:
        return 'bad_signature'
    return None if hmac.compare_digest(sign(key, ts, body or b''), sig) else 'bad_signature'


def key_of(kind, payload):
    """紀錄的交換鍵（tuple）。"""
    return tuple(payload.get(f) for f in KINDS[kind]['key'])


def post(url, params, key, peer_code, timeout=20):
    """送一個簽章的 JSON-RPC 請求；回 result dict，失敗拋例外。

    ☠️ 自己序列化成 bytes 再送（簽的與送的是同一串）；`trust_env=False` 不吃容器的
       .netrc／CA 環境，只保留 proxy。金鑰只拿來算 HMAC，不進 log。
    """
    params = dict(params, schema_version=SCHEMA_VERSION, nonce=uuid.uuid4().hex)
    body = json.dumps({'jsonrpc': '2.0', 'method': 'call', 'params': params, 'id': 1},
                      separators=(',', ':'), default=str).encode('utf-8')
    ts = str(int(time.time()))
    headers = {'User-Agent': 'Dobtor-KB-Exchange/1.0', 'Content-Type': 'application/json',
               'X-KB-Peer': peer_code, 'X-KB-Timestamp': ts, 'X-KB-Signature': sign(key, ts, body)}
    with requests.Session() as session:
        session.trust_env = False
        resp = session.post(url, data=body, timeout=timeout, headers=headers,
                            proxies=requests.utils.get_environ_proxies(url))
        resp.raise_for_status()
        result = resp.json()
    if result.get('error'):
        err = result['error'] or {}
        raise ValueError(((err.get('data') or {}).get('message') or err.get('message') or 'error')[:300])
    res = result.get('result') or {}
    if not res.get('ok', True):
        raise ValueError('主體拒絕：%s' % (res.get('error') or 'refused'))
    return res
