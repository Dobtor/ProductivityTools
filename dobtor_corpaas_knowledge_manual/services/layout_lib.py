# -*- coding: utf-8 -*-
"""說明書版面：把內容排成 Odoo 原生（Bootstrap 5）元件。純函式，不 import odoo。

★ 只用前台已載入的 class（web.assets_frontend）：提示框、徽章、手風琴、頁籤、卡片、
  清單群組、figure；顏色只用主題語意色（換佈景主題跟著變）。
★ 組件容量（設計建議「分段與組件的容量」）：
  · 徽章、按鈕外觀、選單路徑只放一個詞；灰色小字只放一行。
  · 表格儲存格只放一句話或幾個徽章，長說明移到手風琴展開內容。
  · 提示框一個主題、最多三段；內部用 alert-heading → 段落 → hr → 補充分層。
  · 同類容器不疊加（提示框裡不放提示框、儲存格裡不放提示框）。
★ 分段：長段落在句號處切開（每段最多兩句）；「例如…」切成引用塊；
  「此功能／此行為由設定…」「方案預設…」切成灰色備註。AI 寫的字一個都不改，只重新排。
"""
import html as html_mod
import re

from lxml import etree
from lxml import html as lhtml

esc = html_mod.escape

#: 一段超過這麼多字才切；切完每段最多兩句
SPLIT_AT = 120
MAX_SENTENCES = 2
#: 一句超過這麼多字＝太長（文字檢查用）
LONG_SENTENCE = 120

_SENT = re.compile(r'(?<=[。！？])')
_EXAMPLE = re.compile(r'^\s*(例如|舉例來說|比如)')
_NOTE = re.compile(r'^\s*(此功能於|此行為由|此為方案核心|方案預設|其餘操作同)')
_GUIDE = re.compile(r'^\s*(請依下方步驟|照下方步驟|請照下方)')
_BUTTON = re.compile(r'(按下?|點選|點擊|點按|再按|並按)「([^」<>]{1,14})」')
_MENU = re.compile(r'「([^」<>/›]{1,12}(?:\s*[/›]\s*[^」<>/›]{1,40}){1,5})」')
_FIELD = re.compile(r'(欄位)「([^」<>]{1,16})」')
_SHOT_ITEM = re.compile(r'(?:「[^」<>]{1,20}」|[^\s，、。：；（）「」<>]{1,12})（圖中\s*\d+）')
_HALF = re.compile(r'(?<=[\u4e00-\u9fff」）%])\s*([,;:])\s*(?=[\u4e00-\u9fff「（])')
_PREREQ = re.compile(r'^\s*開始前要先有[：:]\s*')
_TAGS = re.compile(r'<[^>]+>')


def _fragment(markup):
    return lhtml.fragment_fromstring(markup or '', create_parent='div')


def _inner(el):
    parts = [esc(el.text)] if el.text else []
    for child in el:
        parts.append(etree.tostring(child, encoding='unicode', method='html'))
    return ''.join(parts)


def plain(markup):
    return re.sub(r'\s+', ' ', html_mod.unescape(_TAGS.sub('', markup or ''))).strip()


def full_width(text):
    """中文之間的半形「,」「;」「:」換成全形（實機：AI 常回半形標點，句子也切不開）。"""
    return _HALF.sub(lambda m: {',': '，', ';': '；', ':': '：'}[m.group(1)], text or '')


def sentences(inner_html):
    """段落內文（可含 strong 等行內標籤）在句號處切開；切點不會落在標籤裡。"""
    out, buf = [], ''
    for piece in re.split(r'(<[^>]+>)', inner_html or ''):
        if piece.startswith('<'):
            buf += piece
            continue
        piece = full_width(piece)
        for part in _SENT.split(piece):
            buf += part
            if part and part[-1] in '。！？':
                out.append(buf)
                buf = ''
    if buf.strip():
        out.append(buf)
    return [s.strip() for s in out if plain(s)]


def long_sentences(markup, limit=LONG_SENTENCE):
    """太長的句子（文字檢查用）：回傳前幾個字。"""
    found = []
    root = _fragment(markup)
    for p in root.iter('p', 'li'):
        for s in sentences(_inner(p)):
            if len(plain(s)) > limit:
                found.append(plain(s)[:20])
    return found


# ----------------------------------------------------------------------
# 行內：按鈕名稱、選單路徑、欄位名稱
# ----------------------------------------------------------------------
def button(label, primary=True):
    return '<span class="btn btn-sm %s py-0 px-2 pe-none">%s</span>' % (
        'btn-primary' if primary else 'btn-secondary', esc(label))


def menu_path(path):
    segs = [s.strip() for s in re.split(r'\s*[/›>]\s*', path or '') if s.strip()]
    return '<span class="text-nowrap fw-semibold">%s</span>' % (
        ' <i class="fa fa-angle-right text-body-secondary small"></i> '.join(esc(s) for s in segs))


def inline(markup):
    """文字裡的「按『確認』」換成按鈕外觀、「銷售 / 訂單」換成選單路徑、欄位名稱加粗。

    只動純文字，不碰標籤內容與屬性。"""
    out = []
    for piece in re.split(r'(<[^>]+>)', markup or ''):
        if piece.startswith('<'):
            out.append(piece)
            continue
        piece = full_width(piece)
        piece = _BUTTON.sub(lambda m: m.group(1) + button(html_mod.unescape(m.group(2))), piece)
        piece = _MENU.sub(lambda m: menu_path(html_mod.unescape(m.group(1))), piece)
        piece = _FIELD.sub(lambda m: '%s<span class="fw-semibold">「%s」</span>' % (
            m.group(1), m.group(2)), piece)
        out.append(piece)
    return ''.join(out)


# ----------------------------------------------------------------------
# 分段
# ----------------------------------------------------------------------
def _group(sents):
    """句子 → 段落（每段最多兩句）；例子、備註各自成段。回傳 [(kind, html)]。"""
    out, cur = [], []

    def flush():
        if cur:
            out.append(('p', ''.join(cur)))
            cur.clear()
    for s in sents:
        text = plain(s)
        if _EXAMPLE.match(text):
            flush()
            out.append(('example', s))
        elif _NOTE.match(text):
            flush()
            out.append(('note', s))
        elif _GUIDE.match(text):
            flush()
            out.append(('guide', s))
        else:
            cur.append(s)
            if len(cur) >= MAX_SENTENCES:
                flush()
    flush()
    return out


def _shot_list(html):
    """一句裡列了三個以上「欄位」（圖中 n）→ 前半句＋條列。"""
    items = _SHOT_ITEM.findall(plain(html))
    if len(items) < 3:
        return None
    text = plain(html)
    head = text[:text.index(items[0])]
    # 「列出單號（圖中 1）」「畫面上可設定客戶（圖中 1）」：動詞以前留在前半句
    verb = None
    for verb in re.finditer(r'(可設定|可看到|可以看到|列出|包含|顯示|設定|輸入|選擇|填寫|勾選|有)',
                            items[0].split('（')[0]):
        pass
    if verb:
        head += items[0][:verb.end()]
        items[0] = items[0][verb.end():]
    head = head.rstrip('，：:、 ')
    tail = text[text.index(items[-1].lstrip()) + len(items[-1]):].lstrip('、，等 ').rstrip('。')
    if len(tail) <= 6:   # 「…等欄位。」這種收尾併進前半句
        head, tail = head + (tail and '以下%s' % tail), ''
    lis = ''.join('<li>%s</li>' % inline(esc(i)) for i in items)
    return '<p class="mb-1">%s：</p><ul class="mb-2">%s</ul>%s' % (
        inline(esc(head)), lis, ('<p>%s。</p>' % inline(esc(tail))) if tail else '')


def split_paragraphs(markup, guide=True):
    """長段落切開、例子成引用塊、設定備註成灰色一行；清單與其他元素照舊。"""
    root = _fragment(markup)
    out = []
    if root.text and root.text.strip():
        out.append('<p>%s</p>' % inline(esc(root.text.strip())))
    for el in root:
        tail = el.tail
        el.tail = None
        if el.tag != 'p':
            out.append(inline(etree.tostring(el, encoding='unicode', method='html')))
        else:
            inner = _inner(el)
            sents = sentences(inner)
            if len(plain(inner)) <= SPLIT_AT and len(sents) <= MAX_SENTENCES \
                    and not any(_EXAMPLE.match(plain(s)) or _NOTE.match(plain(s)) for s in sents):
                listed = _shot_list(inner)
                out.append(listed or '<p>%s</p>' % inline(inner))
            else:
                for kind, html in _group(sents):
                    if kind == 'example':
                        out.append('<blockquote class="blockquote fs-6 border-start border-3 '
                                   'border-primary ps-3 my-3">%s</blockquote>' % inline(html))
                    elif kind == 'note':
                        out.append('<p class="small text-body-secondary"><i class="fa fa-cog me-1">'
                                   '</i>%s</p>' % inline(html))
                    elif kind == 'guide':
                        if guide:
                            out.append('<p class="small text-body-secondary">%s</p>' % inline(html))
                    else:
                        out.append(_shot_list(html) or '<p>%s</p>' % inline(html))
        if tail and tail.strip():
            out.append('<p>%s</p>' % inline(esc(tail.strip())))
    return ''.join(out)


def lead_intro(markup):
    """情境說明：第一句當導言（lead），其餘照分段規則；不再整段放進提示框。

    已經是提示框（方案核心警示）的元素原樣保留。"""
    root = _fragment(markup)
    first = None
    for el in root:
        if el.tag == 'p' and plain(_inner(el)):
            first = el
            break
    if first is None:
        return split_paragraphs(markup)
    sents = sentences(_inner(first))
    lead = '<p class="lead">%s</p>' % inline(sents[0]) if sents else ''
    rest_first = ''.join(sents[1:])
    if rest_first:
        new = lhtml.fragment_fromstring('<p>%s</p>' % rest_first)
        new.tail = first.tail
        first.addprevious(new)
    root.remove(first)
    return lead + split_paragraphs(_inner(root))


# ----------------------------------------------------------------------
# 元件
# ----------------------------------------------------------------------
def alert(kind, title, body, icon):
    return ('<div class="s_alert alert alert-%s" role="status"><h6 class="alert-heading">'
            '<i class="fa %s me-1"></i>%s</h6>%s</div>') % (kind, icon, esc(title), body)


def accordion(uid, items, open_first=False):
    """items: [(標題 HTML, 內容 HTML)]。標題只放一行；內容可多段。"""
    parts = []
    for i, (title, body) in enumerate(items):
        cid = '%s-%s' % (uid, i)
        show = open_first and i == 0
        parts.append(
            '<div class="accordion-item"><h2 class="accordion-header">'
            '<button class="accordion-button%s" type="button" data-bs-toggle="collapse" '
            'data-bs-target="#%s" aria-expanded="%s" aria-controls="%s">%s</button></h2>'
            '<div id="%s" class="accordion-collapse collapse%s"><div class="accordion-body">%s'
            '</div></div></div>' % ('' if show else ' collapsed', cid, 'true' if show else 'false',
                                   cid, title, cid, ' show' if show else '', body))
    return '<div class="accordion mb-3" id="%s">%s</div>' % (uid, ''.join(parts))


def tabs(uid, items):
    """items: [(頁籤名稱, 內容 HTML)]。"""
    heads, panes = [], []
    for i, (title, body) in enumerate(items):
        pid = '%s-%s' % (uid, i)
        heads.append('<li class="nav-item" role="presentation"><button class="nav-link%s" '
                     'data-bs-toggle="tab" data-bs-target="#%s" type="button" role="tab" '
                     'aria-controls="%s" aria-selected="%s">%s</button></li>' % (
                         ' active' if i == 0 else '', pid, pid, 'true' if i == 0 else 'false',
                         esc(title)))
        panes.append('<div class="tab-pane fade%s" id="%s" role="tabpanel">%s</div>' % (
            ' show active' if i == 0 else '', pid, body))
    return ('<ul class="nav nav-tabs" role="tablist">%s</ul><div class="tab-content border '
            'border-top-0 rounded-bottom p-3 mb-3">%s</div>') % (''.join(heads), ''.join(panes))


def badge(text, tone='primary', pill=True):
    return '<span class="badge%s text-bg-%s">%s</span>' % (
        ' rounded-pill' if pill else '', tone, esc(text))


def outline_badge(text):
    return '<span class="badge rounded-pill border text-body-secondary fw-normal">%s</span>' % esc(text)


def figure(img_html, caption):
    """img_html 是 <img …>；加上陰影與圖說。"""
    img = img_html.replace('class="img-fluid rounded border"',
                           'class="figure-img img-fluid rounded border shadow-sm"')
    cap = '<figcaption class="figure-caption">%s</figcaption>' % esc(caption) if caption else ''
    return '<figure class="figure d-block my-3">%s%s</figure>' % (img, cap)


def steps_layout(blocks, anchor_prefix=''):
    """步驟區塊（h4 + 內文…）→ 版面：「開始前要先有」黃框、編號步驟、「完成後會看到」綠框。

    blocks: [(錨點, 區塊名稱, 已換好圖片的 HTML)]。每個區塊保留一個帶錨點的 h3
    （help API 用「網址＃錨點」直接跳到這段）。回傳 (HTML, 大綱 [(錨點, 標題)])。"""
    pre, steps_html, done_html, outline = [], [], [], []
    n = 0
    for anchor, name, html in blocks:
        steps_html.append('<h3 id="%s" class="h4 mt-4 pb-2 border-bottom">%s</h3>' % (
            esc(anchor), esc(name or '')))
        head_at = len(steps_html)
        root = _fragment(html)
        sections, cur = [], None
        lead = []
        for el in list(root):
            if el.tag == 'h4':
                cur = {'id': el.get('id'), 'title': plain(_inner(el)).lstrip('0123456789 ').strip(),
                       'body': []}
                sections.append(cur)
            elif cur is None:
                lead.append(etree.tostring(el, encoding='unicode', method='html'))
            else:
                cur['body'].append(etree.tostring(el, encoding='unicode', method='html'))
        for sec in sections:
            body = ''.join(sec['body'])
            if sec['title'].startswith('完成後會看到'):
                done_html.append(split_paragraphs(body, guide=False))
                continue
            first = _fragment(body)
            p0 = next((e for e in first if e.tag == 'p'), None)
            if p0 is not None:
                inner = _inner(p0)
                sents = sentences(inner)
                if sents and _PREREQ.match(plain(sents[0])):
                    pre.append('<p class="mb-0">%s</p>' % inline(_PREREQ.sub('', sents[0], count=1)))
                    rest = ''.join(sents[1:])
                    if rest:
                        new = lhtml.fragment_fromstring('<p>%s</p>' % rest)
                        new.tail = p0.tail
                        p0.addprevious(new)
                    first.remove(p0)
                    body = _inner(first)
            n += 1
            sid = sec['id'] or '%s-s%s' % (anchor_prefix or anchor, n)
            outline.append((sid, sec['title']))
            steps_html.append(
                '<div class="o_kb_step d-flex gap-3 mt-4"><div class="flex-shrink-0 pt-1">'
                '<span class="badge rounded-pill text-bg-primary fs-6">%s</span></div>'
                '<div class="flex-grow-1 min-w-0"><h4 id="%s" class="h5 fw-semibold">%s</h4>%s'
                '</div></div>' % (n, sid, esc(sec['title']), split_paragraphs(body)))
        if lead:
            steps_html.insert(head_at, split_paragraphs(''.join(lead)))
    parts = []
    if pre:
        parts.append(alert('warning', '開始前要先有', ''.join(pre), 'fa-exclamation-triangle'))
    parts.extend(steps_html)
    if done_html:
        parts.append(alert('success', '完成後會看到', ''.join(done_html), 'fa-check-circle'))
    return ''.join(parts), outline


def outline_nav(outline):
    """本篇大綱：步驟三個以上才放。"""
    if len(outline) < 3:
        return ''
    return '<nav class="nav nav-pills small flex-wrap gap-1 mb-3">%s</nav>' % ''.join(
        '<a class="nav-link border py-1 px-2" href="#%s">%s. %s</a>' % (esc(sid), i, esc(t))
        for i, (sid, t) in enumerate(outline, start=1))


def flow_position(flows):
    """流程位置徽章列。flows: [{'name', 'states': [標籤], 'from', 'to'}]（from/to 可空）。"""
    rows = []
    for f in flows:
        pills = []
        for s in f['states']:
            if f.get('to') and s == f['to']:
                pills.append(badge(s, 'primary'))
            elif f.get('from') and s == f['from']:
                pills.append(badge(s, 'secondary'))
            else:
                pills.append(outline_badge(s))
        rows.append('<div class="d-flex flex-wrap align-items-center gap-1 small mb-1">'
                    '<span class="text-body-secondary me-1"><i class="fa fa-random me-1"></i>%s</span>'
                    '%s%s</div>' % (esc(f['name']), ' <i class="fa fa-angle-right text-body-secondary">'
                                    '</i> '.join(pills),
                                    (' <span class="text-body-secondary ms-1">（%s）</span>'
                                     % esc(f['button'])) if f.get('button') else ''))
    return '<div class="o_kb_flowpos mb-3">%s</div>' % ''.join(rows) if rows else ''


def page(body, width='52rem'):
    """整頁外層：限制閱讀寬度、置中。"""
    return '<div class="o_kb_page mx-auto" style="max-width:%s">%s</div>' % (width, body)
