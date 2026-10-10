"""讓 AI 讀得到方案程式（計畫第 43、49、50 項）的正式機步驟。由使用者執行：

    python3 tools/knowledge/deploy/ai_access.py hub              # AI Hub 兩個模組下載新版＋更新，重啟 Runner
    python3 tools/knowledge/deploy/ai_access.py mount <實例 id>   # 勾實例唯讀掛載、Runner 加 /odoo-core 掛載、重新部署、同步來源
    python3 tools/knowledge/deploy/ai_access.py enable           # 打開提示詞快取與程式知識語意層

★ 會動正式機：mount 會重建 AI Runner 容器（進行中的 AI 呼叫會中斷），請在知識佇列空的時候跑。
★ 最後一步要在 AI Hub 後台手動做：來源「CorPaaS 主控台」→「知識內容可讀的實例」加上該實例。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from rpc import ro, rw  # noqa: E402

AI_INSTANCE = int(os.environ.get('AI_HUB_INSTANCE_ID', 213))
HUB_MODULES = ('dobtor_ai_hub', 'dobtor_ai_hub_content')
CORE_HOST, CORE_MOUNT = '/srv/ai-src/odoo', '/odoo-core'


def step(label, fn):
    try:
        res = fn()
        print('OK  ', label, '' if res in (None, True) else res)
        return res
    except Exception as e:  # noqa: BLE001
        print('FAIL', label, str(e)[:300])
        sys.exit(1)


def runner_for(instance_id):
    server = ro('infrastructure.instance', 'read', [instance_id], fields=['server_id'])[0]['server_id'][0]
    runners = ro('infrastructure.ai_runner', 'search_read', [('server_id', '=', server)], fields=['name'])
    if not runners:
        sys.exit('實例 %s 的主機上沒有 AI Runner' % instance_id)
    return runners[0]['id']


def hub():
    mods = ro('infrastructure.instance_module', 'search_read',
              [('instance_id', '=', AI_INSTANCE), ('technical_name', 'in', list(HUB_MODULES))],
              fields=['technical_name'])
    if len(mods) != len(HUB_MODULES):
        sys.exit('實例 %s 找不到 %s' % (AI_INSTANCE, HUB_MODULES))
    for m in sorted(mods, key=lambda x: HUB_MODULES.index(x['technical_name'])):
        # ★ 先下載（拉新程式碼）再更新；確認技術名稱對了才按（見 memory：搜尋還沒套用就按會按錯列）
        step('下載新版 %s' % m['technical_name'],
             lambda: rw('infrastructure.instance_module', 'action_direct_download', [m['id']], unsafe=True))
        step('更新模組 %s' % m['technical_name'],
             lambda: rw('infrastructure.instance_module', 'action_direct_update', [m['id']], unsafe=True))
    rid = runner_for(AI_INSTANCE)
    step('重啟 Runner（載入新的 runner 程式）', lambda: rw('infrastructure.ai_runner', 'action_restart', [rid], unsafe=True))


def mount(instance_id):
    step('實例 %s 勾「AI 讀取原始碼」' % instance_id,
         lambda: rw('infrastructure.instance', 'write', [instance_id], {'ai_source_mount': True}, unsafe=True))
    rid = runner_for(instance_id)
    have = ro('infrastructure.ai_runner.mount', 'search_read',
              [('runner_id', '=', rid), ('host_path', '=', CORE_HOST)], fields=['container_path'])
    if not have:
        step('Runner 加唯讀掛載 %s → %s' % (CORE_HOST, CORE_MOUNT),
             lambda: rw('infrastructure.ai_runner.mount', 'create',
                        {'runner_id': rid, 'host_path': CORE_HOST, 'container_path': CORE_MOUNT,
                         'read_only': True}, unsafe=True))
    step('重新部署 Runner（重建容器）', lambda: rw('infrastructure.ai_runner', 'action_deploy', [rid], unsafe=True))
    step('檢查掛載', lambda: rw('infrastructure.ai_runner', 'action_check_mounts', [rid], unsafe=True))
    step('同步來源到 AI Hub', lambda: rw('infrastructure.ai_runner', 'action_sync_targets', [rid], unsafe=True))
    print('\n最後一步（AI Hub 後台）：來源「CorPaaS 主控台」→「知識內容可讀的實例」加上實例 %s 的來源。'
          % instance_id)


def enable():
    for key in ('corpaas_knowledge.hub_system_prompt', 'corpaas_knowledge.code_semantic'):
        step('系統參數 %s = 1' % key,
             lambda: rw('ir.config_parameter', 'set_param', key, '1', unsafe=True))


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    if cmd == 'hub':
        hub()
    elif cmd == 'mount' and len(sys.argv) > 2:
        mount(int(sys.argv[2]))
    elif cmd == 'enable':
        enable()
    else:
        sys.exit(__doc__)
