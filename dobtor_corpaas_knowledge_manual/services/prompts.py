# -*- coding: utf-8 -*-
"""操作說明出口的 AI 提示（繁中）。

★ 共通規則（繁中、不編造、只回 JSON、不寫連結）已由核心的 BASE_INSTRUCTIONS 帶上；
  這裡只寫各任務自己的要求與 JSON 格式。
★ 分工：步驟區塊只寫「怎麼操作」，跨情境共用；情境區塊只寫「在這個情境為什麼這樣做」，
  不得另寫一套完整步驟——所以寫情境區塊時一定把既有步驟區塊帶進去。
"""
import json

ALLOWED_HTML = (
    "HTML 只能用這些標籤：p、strong、em、ul、ol、li、table、thead、tbody、tr、th、td、span、br；"
    "class 只能用：s_alert alert alert-info、table table-bordered table-striped align-middle"
    "（thead 用 table-light）、badge text-bg-primary、d-flex。"
    "不可以有 <style>、<script>、<svg>、<a>、style 屬性或任何網址。"
)

STEP_VOCAB = (
    "步驟詞彙（每步是只有一個鍵的物件）：\n"
    '{"goto":{"action":"<動作 xmlid>","res_id":"{佔位符}"?}}、'
    '{"open":{"model":"<模型>","res_id":"{佔位符}"}}、'
    '{"click":{"button"|"field"|"page"|"selector"|"text":"…"}}、{"fill":{"field":"…","value":"…"}}、'
    '{"wait":{"ms":500}|{"selector":"…"}}、{"highlight":{"field"|"button"|"page"|"selector":"…","n":1}}、'
    '{"shot":"<截圖名稱，英數底線>"}。\n'
    "highlight 會在截圖上畫紅框並編號（n），請標出這一步使用者要看或要按的元素；"
    "每張 shot 前的 highlight 屬於那張圖。示範記錄一律用佔位符 \"{名稱}\"，不要寫死 id。"
    "不要用網址開頁面（goto 只能用 action）。"
)


def _j(value):
    return json.dumps(value, ensure_ascii=False)


def _delta_note(feature):
    """改過的官方畫面（K21）：只說明我們加的部分，標準操作交給 Odoo 官方文件。"""
    delta = feature.get('delta') or []
    if not delta:
        return ''
    return ("\n★ 這是 Odoo 官方畫面，我們的模組只加了這些元素：%s。"
            "只需要拍出並說明這些差異；標準操作不要重寫，寫一句「其餘操作同 Odoo 官方說明」即可。\n"
            % _j(delta))


def explore_prompt(feature, archs, demo, roles, screen=None):
    """沒有截圖腳本範本的功能：看畫面結構與示範資料，寫出範本與繫結。"""
    return (
        "任務：為功能「%(name)s」寫一份無頭瀏覽器截圖腳本（操作說明用）。\n"
        "功能鍵：%(key)s；種類：%(kind)s；模型：%(model)s；選單路徑：%(menu)s；"
        "動作 xmlid：%(action)s；按鈕：%(button)s\n\n"
        "%(vocab)s\n\n"
        "要求：\n"
        "1. 從打開功能開始，走到能說明這個功能的畫面，拍 1–4 張圖；每張圖標出 1–5 個重點元素。\n"
        "2. 只用畫面上確實看得到的欄位、按鈕、分頁名稱：以「實際畫面」為準（那是用示範帳號"
        "真的打開畫面抓到的），arch 只當參考；實際畫面沒有的元素不要用。\n"
        "3. 需要既有記錄時，用佔位符並在 bindings 對應到下列示範資料的 xmlid。\n"
        "4. login_role 從角色清單挑最適合操作這個功能的一個 code。\n%(delta)s\n"
        "回覆格式：{\"login_role\":\"<code>\",\"steps\":[…],"
        "\"bindings\":{\"<佔位符名>\":\"<xmlid>\"},\"note\":\"<一句話說明>\"}\n\n"
        "角色：%(roles)s\n\n示範資料（xmlid, model）：%(demo)s\n\n"
        "實際畫面（entry＝打開功能後、record＝打開一筆示範記錄）：%(screen)s\n\n"
        "畫面結構（arch）：%(archs)s"
    ) % {
        'screen': _j(screen or {})[:20000], 'delta': _delta_note(feature),
        'name': feature.get('name'), 'key': feature.get('key'), 'kind': feature.get('kind'),
        'model': feature.get('model') or '', 'menu': feature.get('menu_path') or '',
        'action': feature.get('action_xmlid') or '', 'button': feature.get('button_name') or '',
        'vocab': STEP_VOCAB, 'roles': _j(roles), 'demo': _j(demo),
        'archs': _j(archs)[:60000],
    }


def bind_prompt(feature, steps, placeholders, demo):
    """範本已存在、這個情境還沒有繫結：只挑示範資料，不改腳本。"""
    return (
        "任務：功能「%(name)s」（%(key)s）已有截圖腳本。請為這個情境挑選示範資料，"
        "把腳本裡的每個佔位符對應到一筆示範資料的 xmlid（挑最能說明功能的那筆）。"
        "不要修改腳本。\n\n"
        "回覆格式：{\"bindings\":{\"<佔位符名>\":\"<xmlid>\"}}\n\n"
        "佔位符：%(ph)s\n\n示範資料（xmlid, model）：%(demo)s\n\n腳本：%(steps)s"
    ) % {
        'name': feature.get('name'), 'key': feature.get('key'), 'ph': _j(placeholders),
        'demo': _j(demo), 'steps': _j(steps),
    }


def repair_prompt(feature, steps, bindings, error, dom_text, url, roles=None, demo=None):
    """截圖失敗（含佔位符對不到示範資料、角色沒有帳號）：依錯誤修腳本或繫結。

    下一次 refresh 才重試。
    """
    return (
        "任務：功能「%(name)s」（%(key)s）的截圖腳本執行失敗，請修正。\n"
        "只改造成失敗的部分，其他照舊；截圖名稱不要改（素材以名稱對應）。\n"
        "錯誤若是「找不到示範資料」→ 改 bindings 對到下列示範資料裡確實存在的 xmlid；"
        "錯誤若是「沒有角色的帳號」→ login_role 改用角色清單裡的 code。\n\n"
        "%(vocab)s\n\n"
        "回覆格式：{\"steps\":[…],\"bindings\":{…}（沒改可省略）,"
        "\"login_role\":\"<code>\"（沒改可省略）,\"reason\":\"<修了什麼>\"}\n\n"
        "錯誤：%(error)s\n\n失敗時網址：%(url)s\n\n失敗時畫面文字：%(dom)s\n\n"
        "目前腳本：%(steps)s\n\n目前繫結：%(bindings)s\n\n角色：%(roles)s\n\n"
        "示範資料（xmlid, model）：%(demo)s"
    ) % {
        'name': feature.get('name'), 'key': feature.get('key'), 'vocab': STEP_VOCAB,
        'error': (error or '')[:3000], 'url': url or '', 'dom': (dom_text or '')[:6000],
        'steps': _j(steps), 'bindings': _j(bindings or {}), 'roles': _j(roles or []),
        'demo': _j(demo or [])[:30000],
    }


def step_block_prompt(feature, steps, shots, elements):
    """步驟區塊：只寫操作步驟，跨情境、跨方案共用。"""
    return (
        "任務：為功能「%(name)s」寫「操作步驟」。這段文字會被多個情境、多個方案共用，所以：\n"
        "1. 只寫怎麼操作（去哪裡、按什麼、填什麼、會看到什麼），不寫業務背景、不寫情境用語。\n"
        "2. 依截圖腳本的順序分成數個步驟；每步一個短標題＋說明。\n"
        "3. 截圖上的紅框編號在說明裡以「（圖中 1）」這樣引用。\n"
        "4. 在適當的步驟說明裡放截圖標記 [[shot:<截圖名稱>]]（單獨一段），每張圖只放一次。\n"
        "5. %(allowed)s\n%(delta)s\n"
        "回覆格式：{\"title\":\"<區塊標題>\",\"steps\":[{\"title\":\"…\",\"html\":\"…\"}]}\n\n"
        "功能鍵：%(key)s；選單路徑：%(menu)s\n\n截圖名稱：%(shots)s\n\n"
        "標註元素：%(elements)s\n\n截圖腳本：%(steps)s"
    ) % {
        'name': feature.get('name'), 'key': feature.get('key'),
        'menu': feature.get('menu_path') or '', 'allowed': ALLOWED_HTML,
        'delta': _delta_note(feature),
        'shots': _j(shots), 'elements': _j(elements), 'steps': _j(steps),
    }


def fork_prompt(feature, old_html, old_found, new_found, steps):
    """畫面指紋變了：以既有步驟區塊為底，只改差異。"""
    return (
        "任務：功能「%(name)s」的畫面改版了（腳本範圍內的欄位／按鈕／分頁有變）。"
        "下面是既有的操作步驟。請判斷文字是否需要修改：\n"
        "· 不需要（只是截圖外觀變了）→ 回 {\"changed\": false}\n"
        "· 需要 → 以既有步驟為底，只改受影響的句子，其餘逐字保留；[[shot:…]] 標記保留。\n"
        "%(allowed)s\n\n"
        "回覆格式：{\"changed\":true|false,\"title\":\"…\","
        "\"steps\":[{\"title\":\"…\",\"html\":\"…\"}],\"reason\":\"<改了什麼>\"}\n\n"
        "改版前畫面找得到的元素：%(old)s\n改版後畫面找得到的元素：%(new)s\n\n"
        "截圖腳本：%(steps)s\n\n既有步驟（HTML）：%(html)s"
    ) % {
        'name': feature.get('name'), 'allowed': ALLOWED_HTML, 'old': _j(old_found),
        'new': _j(new_found), 'steps': _j(steps), 'html': old_html or '',
    }


def scenario_prompt(scenario, glossary, feature, capability, step_html):
    """情境區塊：在這個情境下為什麼這樣做；帶入既有步驟區塊，禁止重寫步驟。"""
    return (
        "任務：為情境「%(sc)s」寫一段「情境說明」，放在功能「%(name)s」的操作步驟前面。\n"
        "1. 說明在這個情境裡，使用者為什麼、在什麼時機要做這件事，做完帶來什麼結果。\n"
        "2. 套用用語對照（左邊是系統原詞，右邊是這個情境的說法）。\n"
        "3. ★ 不得另寫一套完整操作步驟——操作步驟已經在下面，會原樣放在你的說明後面。"
        "最多用一兩句話提示「照下方步驟操作」。\n"
        "4. 100–250 字。%(allowed)s\n\n"
        "回覆格式：{\"title\":\"<文章標題，用情境用語>\",\"html\":\"…\"}\n\n"
        "情境敘事：%(narrative)s\n\n用語對照：%(glossary)s\n\n"
        "所屬能力：%(cap)s（痛點：%(pain)s；成果：%(outcome)s）\n\n"
        "既有操作步驟（不要重寫）：%(steps)s"
    ) % {
        'sc': scenario.get('name'), 'name': feature.get('name'), 'allowed': ALLOWED_HTML,
        'narrative': (scenario.get('narrative') or '')[:3000], 'glossary': _j(glossary),
        'cap': capability.get('name') or '', 'pain': capability.get('pain') or '',
        'outcome': capability.get('outcome') or '', 'steps': step_html or '',
    }
