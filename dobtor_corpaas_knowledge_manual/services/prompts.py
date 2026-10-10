# -*- coding: utf-8 -*-
"""操作說明出口的 AI 提示（繁中）。

★ 共通規則（繁中、不編造、只回 JSON、不寫連結）已由核心的 BASE_INSTRUCTIONS 帶上；
  這裡只寫各任務自己的要求與 JSON 格式。
★ 分工：步驟區塊只寫「怎麼操作」，跨情境共用；情境區塊只寫「在這個情境為什麼這樣做」，
  不得另寫一套完整步驟——所以寫情境區塊時一定把既有步驟區塊帶進去。
"""
import json

ALLOWED_HTML = (
    "HTML 只能用這些標籤：p、strong、em、ul、ol、li、table、thead、tbody、tr、th、td、span、br、blockquote；"
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


def _flows_note(flows):
    if not flows:
        return ''
    return ("\n\n這個模型的狀態流程（系統實測：狀態順序、哪顆按鈕從哪個狀態推到哪個狀態、會開哪個精靈）："
            "%s\n要拍「某狀態才有的按鈕」時，挑示範資料清單裡 state 是那個狀態的記錄。" % _j(flows)[:6000])


DEMO_NOTE = ("示範資料附了說明庫裡的名稱（name）與目前狀態（state）；按鈕只在特定狀態出現，"
             "綁記錄前先對狀態。精靈（暫存模型）不能用網址或 open 打開，要按開啟它的按鈕。")


_IN_SYSTEM = '（步驟詞彙、示範資料說明與清單在前面的固定內容裡）'


def demo_static(demo, limit=30000):
    """寫／修／挑腳本共用的固定內容：步驟詞彙＋示範資料說明＋清單。

    ★ 同一個情境的每次呼叫都一樣：另外送（AI Hub 放進系統提示）才吃得到提示詞快取。
    ★ 太長時整筆整筆刪尾巴（JSON 保持完整），不從中間截斷。"""
    rows = list(demo or [])
    text = _j(rows)
    while len(text) > limit and rows:
        rows = rows[:max(1, int(len(rows) * limit / len(text)) - 1)] if len(rows) > 1 else []
        text = _j(rows)
    return '%s\n\n%s\n示範資料：%s' % (STEP_VOCAB, DEMO_NOTE, text)


def _code_note(code, modules):
    """讀過程式的資訊：模組摘要（用途、規則、前置設定）＋按鈕的程式結論。"""
    out = ''
    if modules:
        out += ("\n\n這個功能所屬模組（讀過程式的摘要：用途、核心規則、前置設定；腳本要符合，例如先完成前置設定、"
                "選符合規則的記錄）：%s" % _j(modules)[:4000])
    if code:
        out += ("\n\n這個模型按鈕在程式裡做什麼（讀過程式的結論：前提、狀態轉換、會開的精靈、需要的設定）：%s"
                % _j(code)[:4000])
    return out


def explore_prompt(feature, archs, demo, roles, screen=None, flows=None, static_demo=False, code=None,
                   modules=None):
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
        "角色：%(roles)s\n\n%(demo_part)s%(flows)s%(code)s\n\n"
        "實際畫面（entry＝打開功能後、record＝打開一筆示範記錄）：%(screen)s\n\n"
        "畫面結構（arch）：%(archs)s"
    ) % {
        'code': _code_note(code, modules),
        'demo_part': _IN_SYSTEM if static_demo else '%s\n示範資料：%s' % (DEMO_NOTE, _j(demo)),
        'flows': _flows_note(flows),
        'screen': _j(screen or {})[:20000], 'delta': _delta_note(feature),
        'name': feature.get('name'), 'key': feature.get('key'), 'kind': feature.get('kind'),
        'model': feature.get('model') or '', 'menu': feature.get('menu_path') or '',
        'action': feature.get('action_xmlid') or '', 'button': feature.get('button_name') or '',
        'vocab': '' if static_demo else STEP_VOCAB, 'roles': _j(roles),
        'archs': _j(archs)[:60000],
    }


def bind_prompt(feature, steps, placeholders, demo, static_demo=False):
    """範本已存在、這個情境還沒有繫結：只挑示範資料，不改腳本。"""
    demo_part = _IN_SYSTEM if static_demo else DEMO_NOTE + "\n示範資料：" + _j(demo)
    return (
        "任務：功能「%(name)s」（%(key)s）已有截圖腳本。請為這個情境挑選示範資料，"
        "把腳本裡的每個佔位符對應到一筆示範資料的 xmlid（挑最能說明功能的那筆）。"
        "不要修改腳本。\n\n"
        "回覆格式：{\"bindings\":{\"<佔位符名>\":\"<xmlid>\"}}\n\n"
        "佔位符：%(ph)s\n\n%(demo)s\n\n腳本：%(steps)s"
    ) % {
        'name': feature.get('name'), 'key': feature.get('key'), 'ph': _j(placeholders),
        'demo': demo_part, 'steps': _j(steps),
    }


def repair_prompt(feature, steps, bindings, error, dom_text, url, roles=None, demo=None, flows=None,
                  static_demo=False, code=None, modules=None):
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
        "%(demo_part)s%(flows)s%(code)s"
    ) % {
        'code': _code_note(code, modules),
        'demo_part': _IN_SYSTEM if static_demo else '%s\n示範資料：%s' % (DEMO_NOTE, _j(demo or [])[:30000]),
        'flows': _flows_note(flows),
        'name': feature.get('name'), 'key': feature.get('key'), 'vocab': '' if static_demo else STEP_VOCAB,
        'error': (error or '')[:3000], 'url': url or '', 'dom': (dom_text or '')[:6000],
        'steps': _j(steps), 'bindings': _j(bindings or {}), 'roles': _j(roles or []),
    }


#: 文字檢查（article._manual_text_problems）會擋的寫法：起草時就先講清楚，免得卡在核准
WRITING_RULES = (
    "★ 一律繁體中文（台灣用語），不要出現簡體字；標點一律全形（，。；：）；畫面上的欄位與按鈕用畫面"
    "顯示的中文名稱，不要寫技術欄位名（例如 partner_id）；不要留 TODO、XXX 之類的佔位字。\n"
    "★ 分段：一段只講一件事、最多兩三句；一句不超過 60 字；舉例另起一段、以「例如」開頭；"
    "設定的影響另起一段；三個以上並列的欄位或項目用 <ul> 條列，不要用「、」串成一長句。"
    "按鈕寫成按「名稱」、選單路徑寫成「應用 / 選單 / 子選單」，系統會自動排版。\n")


def _flow_note(flow_ctx):
    if not flow_ctx:
        return ''
    return "這個畫面在任務流程中的位置（系統實際的狀態與按鈕）：%s\n\n" % _j(flow_ctx)


def step_block_prompt(feature, steps, shots, elements, flow_ctx=None):
    """步驟區塊：只寫操作步驟，跨情境、跨方案共用。

    ★ 參考說明書的寫法：第一步前講「開始前要先有」，最後一步後講「完成後會看到」——
      讀者照做完才知道自己做對了沒有。"""
    return (
        "任務：為功能「%(name)s」寫「操作步驟」。這段文字會被多個情境、多個方案共用，所以：\n"
        "1. 只寫怎麼操作（去哪裡、按什麼、填什麼、會看到什麼），不寫業務背景、不寫情境用語。\n"
        "2. 依截圖腳本的順序分成數個步驟；每步一個短標題＋說明。\n"
        "3. 截圖上的紅框編號在說明裡以「（圖中 1）」這樣引用。\n"
        "4. 在適當的步驟說明裡放截圖標記 [[shot:<截圖名稱>]]（單獨一段），每張圖只放一次。\n"
        "5. %(allowed)s\n"
        "6. 第一個步驟的說明開頭，用一句「開始前要先有：…」寫出這個操作需要先存在的資料或先完成的"
        "前一步（例如「要先有客戶與商品」「報價單要先確認」；依截圖腳本打開的記錄、要填的欄位、"
        "流程位置判斷）。不要寫「列表要有資料才看得到」這類跟操作無關的條件；新增類的操作通常"
        "不需要先有同一種資料。不需要就省略，不要編造。\n"
        "7. 最後加一個標題為「完成後會看到」的步驟：說明畫面或狀態怎麼變、會產生哪張後續單據、"
        "去哪裡確認結果（依下面的流程位置；沒有流程資訊就寫畫面上會出現的變化）。這一步不放截圖。\n"
        + WRITING_RULES + "%(delta)s%(front)s\n"
        "回覆格式：{\"title\":\"<區塊標題>\",\"steps\":[{\"title\":\"…\",\"html\":\"…\"}]}\n\n"
        "%(flow)s"
        "功能鍵：%(key)s；選單路徑：%(menu)s\n\n截圖名稱：%(shots)s\n\n"
        "標註元素：%(elements)s\n\n截圖腳本：%(steps)s"
    ) % {
        'name': feature.get('name'), 'key': feature.get('key'),
        'menu': feature.get('menu_path') or '', 'allowed': ALLOWED_HTML,
        'delta': _delta_note(feature), 'flow': _flow_note(flow_ctx),
        'shots': _j(shots), 'elements': _j(elements), 'steps': _j(steps),
        'front': _front_note(feature),
    }


_FRONT_WHO = {
    'visitor': ('還沒登入的網站訪客（公開）', '寫他在這一頁看得到什麼、可以做什麼、下一步會到哪一頁'),
    'member': ('已登入的會員（網站入口使用者）', '寫登入後才有的選單與按鈕、在這一頁可以查什麼、做什麼'),
    'web_editor': ('公司內部的網站管理人員（內部使用者）',
                   '寫怎麼從前台左上角的「編輯此內容」進入網站編輯器、改內容、發佈或下架；'
                   '不寫訪客的購物或瀏覽操作'),
}


def _front_note(feature):
    """網站前台頁：依使用者類型（公開／網站入口／內部使用者）寫他看得到的選單與按鈕。"""
    if feature.get('kind') != 'route':
        return ''
    who, what = _FRONT_WHO.get(feature.get('audience'), _FRONT_WHO['visitor'])
    menus = feature.get('front_menus') or []
    return ("\n★ 這是網站前台頁面（網址 %s），讀者是%s：用「在網站上點…」的說法，%s；"
            "不要寫後台選單路徑。%s" % (
                feature.get('anchor') or '', who, what,
                ('這種使用者在網站選單上看得到：%s（只提這些，別的選單他看不到）。'
                 % '、'.join(menus[:20])) if menus else ''))


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


def _class_note(feature):
    """功能分類（基礎／進階 × 標準／專用 ＋ 方案核心）要寫進情境說明的部分。"""
    c = feature.get('class') or {}
    if not c:
        return ''
    lines = ["\n★ 功能分類：%s%s。文章標題前加上【%s】。" % (
        c.get('classification_label') or '', '（方案核心）' if c.get('core') else '',
        c.get('classification_label') or '')]
    if c.get('tier') == 'advanced' and c.get('toggle_paths'):
        lines.append("開頭第一句寫明：「此功能於 %s 開啟（方案預設已開啟）」。"
                     % '、'.join(c['toggle_paths']))
    if c.get('tier') == 'advanced' and (c.get('core') or c.get('downstream_bom')):
        extra = ('，並一併移除：%s' % '、'.join(c['downstream_bom'])) if c.get('downstream_bom') \
            else ''
        lines.append("加一段警示（s_alert alert alert-info）：「此為方案核心功能，關閉上述設定會移除"
                     "本功能%s，請勿關閉。」" % extra)
    if c.get('advanced_elements'):
        lines.append("畫面上這些元素屬於進階功能，提到時標註「（進階）」並說明由哪個設定開啟：%s。"
                     % _j(c['advanced_elements']))
    if c.get('behavior'):
        lines.append("這個功能的行為受下列設定影響，用一句話註明（例如「此行為由設定 ○○ 決定，"
                     "方案預設：△△」）：%s。" % _j(c['behavior']))
    return '\n'.join(lines) + '\n'


def scenario_prompt(scenario, glossary, feature, capability, step_html, demo=None):
    """情境區塊：在這個情境下為什麼這樣做；帶入既有步驟區塊，禁止重寫步驟。"""
    return (
        "任務：為情境「%(sc)s」寫一段「情境說明」，放在功能「%(name)s」的操作步驟前面。\n"
        "1. 說明在這個情境裡，使用者為什麼、在什麼時機要做這件事，做完帶來什麼結果。\n"
        "2. 套用用語對照（左邊是系統原詞，右邊是這個情境的說法）：直接用右邊的說法，"
        "不要加「（系統原文 X）」之類的旁註。\n" + WRITING_RULES +
        "3. ★ 不得另寫一套完整操作步驟——操作步驟已經在下面，會原樣放在你的說明後面。"
        "最多用一兩句話提示「照下方步驟操作」。\n"
        "4. 100–250 字。%(allowed)s\n"
        "5. 舉例時用下面「截圖裡的示範資料」的實際名稱與數字（客戶、商品、數量、金額），"
        "讓讀者能對照截圖；示範資料沒有的數字不要編。沒有示範資料就不舉數字。\n%(cls)s\n"
        "★ 標題寫使用者要完成的事（例如「建立報價單並轉成訂單」），不要加分類標籤"
        "（如【標準功能】【標準進階】），也不要放情境名稱或示範資料裡的客戶、商品、公司名稱"
        "（標題要能套用在任何公司）。\n"
        "回覆格式：{\"title\":\"<文章標題，用情境用語>\",\"html\":\"…\"}\n\n"
        "情境敘事：%(narrative)s\n\n用語對照：%(glossary)s\n\n"
        "所屬能力：%(cap)s（痛點：%(pain)s；成果：%(outcome)s）\n\n"
        "截圖裡的示範資料：%(demo)s\n\n"
        "既有操作步驟（不要重寫）：%(steps)s"
    ) % {
        'demo': _j(demo or [])[:4000],
        'sc': scenario.get('name'), 'name': feature.get('name'), 'allowed': ALLOWED_HTML,
        'cls': _class_note(feature),
        'narrative': (scenario.get('narrative') or '')[:3000], 'glossary': _j(glossary),
        'cap': capability.get('name') or '', 'pain': capability.get('pain') or '',
        'outcome': capability.get('outcome') or '', 'steps': step_html or '',
    }
