"""排方案知識更新。用法：python3 kq.py 14:inc  13:full  14:select（AI 圈選情境與能力）"""
import sys

from rpc import RpcError, rw

PKG = 'infrastructure.solution.package'
for arg in sys.argv[1:]:
    pk, mode = arg.split(':')
    pk = int(pk)
    try:
        if mode == 'select':
            res = rw(PKG, 'action_knowledge_ai_select', [pk])
        elif mode == 'full':
            res = rw(PKG, 'action_knowledge_refresh', [pk])
        else:
            res = rw(PKG, 'knowledge_enqueue_refresh', [pk], full=False, reason='manual')
        print(pk, res)
    except RpcError as e:
        print(pk, 'ERROR', e)
