"""逐篇核准一個情境裡截圖已就緒的待審文章（被擋的列出原因）。用法：python3 approve.py <情境 id>"""
import sys
from collections import Counter

from rpc import RpcError, ro, rw

sc = int(sys.argv[1])
arts = ro('corpaas.knowledge.article', 'search_read', [('scenario_id', '=', sc), ('state', '=', 'review')],
          fields=['name'])
ok, bad = 0, []
for a in arts:
    try:
        rw('corpaas.knowledge.article', 'action_approve', [a['id']])
        ok += 1
    except RpcError as e:
        bad.append((a['name'], str(e).split('：', 1)[-1][:120]))
print('核准 %s 篇，擋下 %s 篇' % (ok, len(bad)))
for reason, n in Counter(r for _n, r in bad).most_common(10):
    print(' ', n, '×', reason)
