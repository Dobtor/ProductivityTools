# ☠️☠️ 這是 dobtor_corpaas_knowledge/services/fingerprint_lib.py 的**逐字複本**（本行註解區塊除外）。
#    兩份必須完全一致：主控台在黃金庫算出的 scope_hash 與租戶端這裡算出的，
#    是用同一段程式比的——任何一邊改了，所有說明都會被標成「你的畫面可能與說明不同」。
#    改那一份就要同步複製過來；FINGERPRINT_VERSION 不同時本模組不做比對。
# -*- coding: utf-8 -*-
"""畫面指紋（D2）——純函式，不 import odoo。

★ 為什麼要純函式：同一份原始碼會被「嵌進」送到黃金庫執行的 odoo shell 腳本裡
  （見 services/scripts.py 的 `fingerprint_script`）。主控台這側與容器那側用的是
  **同一段程式**，兩邊算出來的雜湊才比得起來。改這支就等於改了指紋的定義——
  所有既有指紋都會變，下一次 refresh 會把整個方案標成失效。要改請同時升
  `FINGERPRINT_VERSION`，讓主控台知道那是定義改了，不是畫面改了。

兩層指紋：
  · form_hash：整份合併 arch 的雜湊。只用來觸發「檢查」，不觸發重拍。
  · scope_hash：截圖腳本實際碰到的元素，連同祖先節點的關鍵屬性。決定重拍。
"""
import hashlib
import re
import xml.etree.ElementTree as ET

FINGERPRINT_VERSION = 1

#: 影響「畫面長相」的屬性。其他屬性（class、context、options…）不列入：
#: 它們改了畫面通常不變，列進來只會製造無謂的重拍。
SCOPE_ATTRS = ('name', 'string', 'invisible', 'readonly', 'required',
               'groups', 'column_invisible', 'widget', 'type')

_WS = re.compile(r'\s+')


def _norm_text(text):
    return _WS.sub(' ', (text or '').strip())


def normalize_arch(arch):
    """把 arch 正規化成穩定字串：去空白、屬性排序。解析失敗回原字串去空白。"""
    try:
        root = ET.fromstring(arch)
    except ET.ParseError:
        return _norm_text(arch)
    return _serialize(root)


def _serialize(node):
    attrs = ' '.join('%s="%s"' % (k, _norm_text(v))
                     for k, v in sorted(node.attrib.items()))
    inner = ''.join(_serialize(child) for child in node)
    text = _norm_text(node.text)
    return '<%s %s>%s%s</%s>' % (node.tag, attrs, text, inner, node.tag)


def sha(text):
    return hashlib.sha256((text or '').encode('utf-8')).hexdigest()[:32]


def form_hash(archs):
    """多份 arch（form/list/search…）合成一個雜湊。archs: {view_type: arch}。"""
    parts = ['%s:%s' % (k, normalize_arch(v)) for k, v in sorted((archs or {}).items())]
    return sha('|'.join(parts))


def _match(node, element):
    """element: {'field': name} / {'button': name} / {'page': name|string} / {'xpath_tag': tag}"""
    if 'field' in element:
        return node.tag == 'field' and node.attrib.get('name') == element['field']
    if 'button' in element:
        return node.tag == 'button' and node.attrib.get('name') == element['button']
    if 'page' in element:
        want = element['page']
        return node.tag == 'page' and want in (node.attrib.get('name'),
                                               node.attrib.get('string'))
    return False


def _scope_parts(root, elements):
    """回傳 (parts, found_keys)。parts 是每個元素「自己＋祖先」關鍵屬性的字串。"""
    parents = {child: parent for parent in root.iter() for child in parent}
    parts, found = [], []
    for element in elements or []:
        key = '%s=%s' % next(iter(element.items()))
        hits = [n for n in root.iter() if _match(n, element)]
        if not hits:
            parts.append('%s:MISSING' % key)
            continue
        found.append(key)
        for n in hits:
            chain, cur = [], n
            while cur is not None:
                attrs = ','.join('%s=%s' % (a, _norm_text(cur.attrib.get(a)))
                                 for a in SCOPE_ATTRS if a in cur.attrib)
                chain.append('%s[%s]' % (cur.tag, attrs))
                cur = parents.get(cur)
            parts.append('%s:%s' % (key, '>'.join(reversed(chain))))
    return parts, found


def scope_hash(archs, elements, menu_path='', view_mode=''):
    """腳本範圍指紋。archs: {view_type: arch}；elements: 截圖腳本碰到的元素清單。"""
    parts = ['menu:%s' % _norm_text(menu_path), 'mode:%s' % (view_mode or '')]
    found_all = []
    for view_type, arch in sorted((archs or {}).items()):
        try:
            root = ET.fromstring(arch)
        except ET.ParseError:
            parts.append('%s:UNPARSEABLE' % view_type)
            continue
        p, found = _scope_parts(root, elements)
        parts.extend('%s/%s' % (view_type, x) for x in p)
        found_all.extend(found)
    return sha('|'.join(parts)), sorted(set(found_all))


def similarity(a, b):
    """兩份元素簽章（字串集合）的 Jaccard 相似度，用於 D3 改名偵測。"""
    a, b = set(a or ()), set(b or ())
    if not a and not b:
        return 1.0
    return len(a & b) / float(len(a | b))


def signature(archs):
    """一份畫面的元素簽章：所有具名 field/button 的集合（改名偵測用）。"""
    sig = set()
    for view_type, arch in (archs or {}).items():
        try:
            root = ET.fromstring(arch)
        except ET.ParseError:
            continue
        for n in root.iter():
            if n.tag in ('field', 'button') and n.attrib.get('name'):
                sig.add('%s/%s:%s' % (view_type, n.tag, n.attrib['name']))
    return sorted(sig)
