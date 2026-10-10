"""盯一張知識更新佇列到結束（每 2 分鐘印一次有變化的狀態）。用法：python3 watch.py <佇列 id> <方案 id>"""
import sys
import time

from rpc import ro

qid, pkg = int(sys.argv[1]), int(sys.argv[2])
last = None
deadline = time.time() + 6 * 3600   # 更新紀錄卡在進行中（worker 被殺）時不要永遠盯下去
while time.time() < deadline:
    try:
        runs = ro('corpaas.knowledge.run', 'search_read', [('package_id', '=', pkg)],
                  fields=['state', 'stage', 'ai_cost', 'error'], order='id desc', limit=1)
        qs = ro('corpaas.queue', 'search_read', [('channel', '=', 'knowledge'),
                                                 ('state', 'in', ['pending', 'processing'])],
                fields=['id', 'operate', 'state'], order='id')
        snap = repr(([(r['id'], r['state'], r['stage'], round(r['ai_cost'], 2)) for r in runs], qs))
        if snap != last:
            print(time.strftime('%H:%M'), snap, flush=True)
            last = snap
        # 結束＝這張佇列做完、而且這個方案最新一筆更新紀錄不在進行中（別的方案排隊不影響）
        got = ro('corpaas.queue', 'search_read', [('id', '=', qid)], fields=['state'])
        q = got[0]['state'] if got else 'gone'
        if q not in ('pending', 'processing') and not (runs and runs[0]['state'] == 'running'):
            r = ro('corpaas.knowledge.run', 'search_read', [('package_id', '=', pkg)],
                   fields=['summary', 'ai_cost'], order='id desc', limit=1)
            print('FINAL', r, flush=True)
            break
    except Exception as e:  # noqa: BLE001 — 網路斷一下就下次再看
        print('poll error', str(e)[:200], flush=True)
    time.sleep(120)
else:
    print('盯了 6 小時還沒結束：請看更新紀錄是不是卡住', flush=True)
