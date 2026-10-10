# -*- coding: utf-8 -*-
"""版本之間的差異（純函式，不 import odoo，可獨立測試）。

用途：複製新版之後，系統先替「本版處理」起一份草稿 —— 痛點多了哪些、對應換了什麼、
金額與人天動了多少。人再補上客戶實際提出的核對項；AI 只負責潤飾，不負責找差異。

★ 差異從**凍結的快照**算，不從現場資料算：前一版送出之後就不會再變，
  所以「v1.0 → v1.1 動了什麼」不管幾年後重算都得到同一個答案。
"""
import re

_SPACE = re.compile(r'\s+')


def _key(text):
    """痛點的比對鍵：去空白、轉小寫 —— 改個標點不算新痛點。"""
    return _SPACE.sub('', (text or '')).lower()


def _short(text, limit=40):
    text = _SPACE.sub(' ', (text or '').strip())
    return text if len(text) <= limit else text[:limit] + '…'


def _confirmed(pain):
    """一個痛點「客戶最後看到的對應」：{(能力, 顏色)}。沒確認的不算。"""
    return {(m.get('capability') or '（客製）', m.get('color'))
            for m in pain.get('mappings', []) if m.get('confirmed')}


def diff_snapshots(old, new, money=None, color_labels=None):
    """回 `[{'demand': …, 'handling': …}, …]`。

    `old` 是前一版的快照；`new` 是這一版現在的快照（草稿也可以，由 `_snapshot()` 產生）。
    `money` 是金額格式化函式（預設只加千分位），`color_labels` 是顏色代碼 → 中文。
    """
    money = money or (lambda v: '{:,.0f}'.format(v or 0))
    color_labels = color_labels or {}

    def color(c):
        return color_labels.get(c, c or '')

    items = []
    old_pains = {_key(p.get('description')): p for p in old.get('pains', [])}
    new_pains = {_key(p.get('description')): p for p in new.get('pains', [])}

    for key, pain in new_pains.items():
        if key not in old_pains:
            maps = sorted(_confirmed(pain))
            how = '、'.join('%s（%s）' % (cap, color(c)) for cap, c in maps) or '尚未確認對應'
            items.append({'demand': '新增痛點：%s' % _short(pain.get('description')),
                          'handling': '本版納入，對應：%s' % how})
    for key, pain in old_pains.items():
        if key not in new_pains:
            items.append({'demand': '移除痛點：%s' % _short(pain.get('description')),
                          'handling': '本版不再處理'})
    for key, pain in new_pains.items():
        before = old_pains.get(key)
        if not before:
            continue
        was, now = _confirmed(before), _confirmed(pain)
        if was == now:
            continue
        added = sorted(now - was)
        removed = sorted(was - now)
        parts = []
        if added:
            parts.append('改為對應 %s' % '、'.join('%s（%s）' % (c, color(k)) for c, k in added))
        if removed:
            parts.append('不再對應 %s' % '、'.join('%s（%s）' % (c, color(k)) for c, k in removed))
        items.append({'demand': '調整對應：%s' % _short(pain.get('description')),
                      'handling': '；'.join(parts)})

    op, np_ = old.get('prices', {}), new.get('prices', {})
    changes = []
    for field, label, unit in (('implementation_days', '導入人天', ' 天'),
                               ('custom_days', '客製人天', ' 天')):
        a, b = op.get(field) or 0.0, np_.get(field) or 0.0
        if round(a, 2) != round(b, 2):
            changes.append('%s %g → %g%s（%+g）' % (label, a, b, unit, round(b - a, 2)))
    total_a, total_b = op.get('total') or 0.0, np_.get('total') or 0.0
    if round(total_a, 2) != round(total_b, 2):
        pct = ((total_b - total_a) / total_a * 100.0) if total_a else 0.0
        changes.append('首年總額 %s → %s（%s%s）' % (
            money(total_a), money(total_b), '+' if total_b >= total_a else '-',
            '%s%%' % ('%.1f' % abs(pct)) if total_a else money(abs(total_b - total_a))))
    if changes:
        items.append({'demand': '報價金額與人天變動', 'handling': '；'.join(changes)})

    old_pricing, new_pricing = old.get('pricing') or {}, new.get('pricing') or {}
    if old_pricing.get('model') and new_pricing.get('model') \
            and old_pricing['model'] != new_pricing['model']:
        items.append({
            'demand': '計價方式變更',
            'handling': '由「%s」改為「%s」' % (
                old_pricing.get('model_label') or old_pricing['model'],
                new_pricing.get('model_label') or new_pricing['model'])})
    return items
