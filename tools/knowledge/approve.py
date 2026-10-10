"""核准一個情境裡「沒被自審擋下」的待審文章（被擋的列出原因）。用法：python3 approve.py <情境 id>

★ 自審不過的（例外清單）不在這裡批次核准：要人逐篇看過、在文章畫面處理（計畫第 22 項單一核准關卡）。
"""
import sys
from collections import Counter

from rpc import RpcError, ro, rw

sc = int(sys.argv[1])
arts = ro('corpaas.knowledge.article', 'search_read', [('scenario_id', '=', sc), ('state', '=', 'review')],
          fields=['name', 'manual_review_state'])
exceptions = [a for a in arts if a['manual_review_state'] == 'fail']
ok, bad = 0, []
for a in arts:
    if a in exceptions:
        continue
    try:
        rw('corpaas.knowledge.article', 'action_approve', [a['id']])
        ok += 1
    except RpcError as e:
        bad.append((a['name'], str(e).split('：', 1)[-1][:120]))
print('核准 %s 篇，擋下 %s 篇，例外清單 %s 篇（請在文章畫面逐篇處理）' % (ok, len(bad), len(exceptions)))
for reason, n in Counter(r for _n, r in bad).most_common(10):
    print(' ', n, '×', reason)
