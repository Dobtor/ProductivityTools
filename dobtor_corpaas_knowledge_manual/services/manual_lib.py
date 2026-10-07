# -*- coding: utf-8 -*-
"""操作說明出口的純函式：截圖腳本、佔位符、HTML 清洗與組裝輔助。

不 import odoo，可獨立測試。
"""
import hashlib
import html as html_mod
import re

from lxml import etree
from lxml import html as lhtml

STEP_KINDS = ('goto', 'open', 'click', 'fill', 'wait', 'highlight', 'shot')
ELEMENT_KEYS = ('field', 'button', 'page')
#: 會碰到畫面元素、因此進入腳本範圍指紋的步驟
ELEMENT_STEPS = ('highlight', 'click', 'fill')

_WHOLE_PH = re.compile(r'^\{([A-Za-z_][A-Za-z0-9_]*)\}$')
_INLINE_PH = re.compile(r'\{([A-Za-z_][A-Za-z0-9_]*)\}')
_SHOT_P = re.compile(r'<p[^>]*>\s*\[\[shot:([\w.-]+)\]\]\s*</p>')
_SHOT_BARE = re.compile(r'\[\[shot:([\w.-]+)\]\]')
_IMG_TAG = re.compile(r'<img\b[^>]*>', re.I)
_TAG = re.compile(r'<[^>]+>')
_WS = re.compile(r'\s+')

#: ☠️ slide.html_content 的 sanitizer 會吃掉這些；AI 產出先清掉，讀回比對才有意義
FORBIDDEN_TAGS = ('style', 'script', 'svg', 'iframe', 'form', 'object', 'embed', 'link',
                  'meta')


def slugify(text, fallback='step'):
    s = re.sub(r'[^a-z0-9]+', '-', (text or '').lower()).strip('-')
    return s[:48].strip('-') or fallback


def make_anchor(feature_key):
    """步驟區塊的穩定鍵：可讀的 slug＋功能鍵雜湊（同名錨點不同功能也不撞）。"""
    digest = hashlib.sha1((feature_key or '').encode('utf-8')).hexdigest()[:6]
    tail = (feature_key or '').split(':', 1)[-1]
    return '%s-%s' % (slugify(tail, 'kb'), digest)


# ----------------------------------------------------------------------
# 截圖腳本
# ----------------------------------------------------------------------
def validate_steps(steps):
    """AI 寫的腳本先驗過：只能用 shot_runner 的步驟詞彙。錯誤拋 ValueError。"""
    if not isinstance(steps, list) or not steps:
        raise ValueError('steps 必須是非空 list')
    shots = 0
    for idx, step in enumerate(steps):
        if not isinstance(step, dict) or len(step) != 1:
            raise ValueError('步驟 %s 必須是只有一個鍵的物件' % idx)
        kind = next(iter(step))
        if kind not in STEP_KINDS:
            raise ValueError('步驟 %s 使用未知動作 %s' % (idx, kind))
        arg = step[kind]
        if kind == 'goto' and not (isinstance(arg, dict) and arg.get('action')
                                   and 'url' not in arg):
            # ☠️ 網址會被品牌過濾改寫（'odoo' 字樣被換掉）→ 腳本在說明庫裡開錯頁；
            #   goto 一律用動作 xmlid。
            raise ValueError('步驟 %s：goto 只能用 action（不可用 url）' % idx)
        if kind == 'shot':
            name = arg if isinstance(arg, str) else (arg or {}).get('name')
            if not name or not re.match(r'^[\w.-]+$', str(name)):
                raise ValueError('步驟 %s 的截圖名稱不合法' % idx)
            shots += 1
        elif not isinstance(arg, (dict, str)):
            raise ValueError('步驟 %s 的參數格式錯誤' % idx)
    if not shots:
        raise ValueError('腳本沒有任何 shot 步驟')
    return True


def _walk_strings(value, fn, key=None):
    if isinstance(value, dict):
        return {k: _walk_strings(v, fn, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_walk_strings(v, fn, key) for v in value]
    if isinstance(value, str):
        return fn(value, key)
    return value


def placeholders_in(steps):
    names = set()

    def grab(s, _key):
        names.update(_INLINE_PH.findall(s))
        return s
    _walk_strings(steps or [], grab)
    return sorted(names)


def elements_from_steps(steps):
    """[{'field': x} | {'button': x} | {'page': x}]，依出現順序去重。"""
    out, seen = [], set()
    for step in steps or []:
        if not isinstance(step, dict) or not step:
            continue
        kind = next(iter(step))
        arg = step[kind]
        if kind not in ELEMENT_STEPS or not isinstance(arg, dict):
            continue
        for key in ELEMENT_KEYS:
            if arg.get(key):
                sig = (key, arg[key])
                if sig not in seen:
                    seen.add(sig)
                    out.append({key: arg[key]})
    return out


def shot_names(steps):
    names = []
    for step in steps or []:
        if isinstance(step, dict) and 'shot' in step:
            arg = step['shot']
            name = arg if isinstance(arg, str) else (arg or {}).get('name')
            if name and name not in names:
                names.append(name)
    return names


def fill_placeholders(steps, resolved):
    """把 "{name}" 換成說明庫裡的記錄。

    resolved: {name: [model, id]}。
    · 整串是佔位符且鍵是 res_id → 換成 id
    · 整串是佔位符、其他位置 → 換成 {"model", "res_id"}（給 open 用）
    · 夾在字串裡（如網址）→ 換成 id
    回傳 (新 steps, 缺少的佔位符集合)。
    """
    missing = set()

    def sub(s, key):
        m = _WHOLE_PH.match(s)
        if m:
            name = m.group(1)
            if name not in resolved:
                missing.add(name)
                return s
            model, rid = resolved[name]
            if key == 'res_id':
                return rid
            return {'model': model, 'res_id': rid}

        def inline(mm):
            if mm.group(1) not in resolved:
                missing.add(mm.group(1))
                return mm.group(0)
            return str(resolved[mm.group(1)][1])
        return _INLINE_PH.sub(inline, s)

    return _walk_strings(steps or [], sub), missing


# ----------------------------------------------------------------------
# HTML
# ----------------------------------------------------------------------
def _fragment(markup):
    return lhtml.fragment_fromstring(markup or '', create_parent='div')


def _inner(root):
    parts = [html_mod.escape(root.text)] if root.text else []
    for child in root:
        parts.append(etree.tostring(child, encoding='unicode', method='html'))
    return ''.join(parts)


def clean_html(markup):
    """AI 產出的 HTML：去掉會被 sanitize 吃掉或違反規則的東西。

    ★ 連結一律由系統產生——<a> 拆掉只留文字。
    """
    if not markup or not markup.strip():
        return ''
    root = _fragment(markup)
    for bad in root.xpath('|'.join('.//%s' % t for t in FORBIDDEN_TAGS)):
        bad.drop_tree()
    for a in root.xpath('.//a'):
        a.drop_tag()
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        for att in list(el.attrib):
            if att in ('style', 'href') or att.startswith('on'):
                del el.attrib[att]
    return _inner(root)


def stamp_heading_ids(markup, anchor):
    """步驟標題（h4）依序帶 id="<anchor>-<n>"：人改過 HTML 也會被補回。"""
    if not markup:
        return ''
    root = _fragment(markup)
    for n, h in enumerate(root.xpath('.//h4'), start=1):
        h.set('id', '%s-%s' % (anchor, n))
    return _inner(root)


def steps_to_html(steps, anchor):
    """AI 回的 [{'title','html'}] → 步驟區塊 HTML。"""
    parts = []
    for n, step in enumerate(steps or [], start=1):
        title = html_mod.escape((step or {}).get('title') or '')
        body = clean_html((step or {}).get('html') or '')
        parts.append('<h4 id="%s-%s"><span class="badge text-bg-primary">%s</span> %s</h4>%s'
                     % (anchor, n, n, title, body))
    return ''.join(parts)


def replace_shot_markers(markup, images):
    """[[shot:<name>]] → 圖片 HTML。回傳 (html, 用到的名稱集合)。"""
    used = set()

    def rep(m):
        name = m.group(1)
        if name in images:
            used.add(name)
            return images[name]
        return ''
    out = _SHOT_P.sub(rep, markup or '')
    out = _SHOT_BARE.sub(rep, out)
    return out, used


def text_signature(markup):
    """去掉圖片與標籤後的文字雜湊：判斷是不是「文字實質改寫」。"""
    text = _IMG_TAG.sub('', markup or '')
    text = _WS.sub(' ', html_mod.unescape(_TAG.sub(' ', text))).strip()
    return hashlib.sha256(text.encode('utf-8')).hexdigest()[:32]


def readback_lost(sent, got):
    """寫進 slide 後讀回比對：sanitizer 吃掉了什麼。回傳描述 list（空＝一致）。"""
    lost = []
    sent, got = sent or '', got or ''
    if len(_IMG_TAG.findall(got)) < len(_IMG_TAG.findall(sent)):
        lost.append('圖片')
    ids_sent = set(re.findall(r'\bid="([^"]+)"', sent))
    ids_got = set(re.findall(r'\bid="([^"]+)"', got))
    if ids_sent - ids_got:
        lost.append('錨點 id：%s' % ', '.join(sorted(ids_sent - ids_got)[:5]))
    for tag in FORBIDDEN_TAGS[:3]:
        if '<%s' % tag in got.lower():
            lost.append('殘留 <%s>' % tag)
    return lost


_TAG_PREFIX = re.compile(r'^\s*(?:[【\[][^】\]]{1,12}[】\]]\s*)+')


def clean_title(title, scenario_name=None):
    """文章標題去掉內部標籤（【標準進階】）與情境名（「XX情境 - 付款服務商」）。

    ★ 實機：AI 把功能分類與情境名寫進標題，租戶讀者看不懂也不需要。"""
    t = _TAG_PREFIX.sub('', title or '').strip()
    if scenario_name:
        name = re.escape(scenario_name.strip())
        t = re.sub(r'^%s\s*[-－—–:：|｜]\s*' % name, '', t)
        t = re.sub(r'\s*[-－—–:：|｜]\s*%s$' % name, '', t)
    return t.strip() or (title or '').strip()
