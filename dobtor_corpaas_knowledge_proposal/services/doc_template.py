# -*- coding: utf-8 -*-
"""服務建議書的文件範本（dobtor_doc_editor 的 content_json）產生器。

純函式，不 import odoo：範本長什麼樣是最需要反覆改的東西，要能不啟動 Odoo 就驗。

★ 範本只讀 `data.*`（`doc_report_values()` 回的 dict）：已送出的版本 data 來自凍結快照，
  所以「重新輸出」得到的文件永遠和送出時一致；草稿 data 來自現場資料。
★ 章節編號由程式動態給（`data.chap.<鍵>`）：沒有資料的章節整章消失，編號仍然連續，
  和既有報價規格書「一、二、三…」的樣子一致。
★ 沒資料的章節怎麼消失：標題段落與表頭列各放一個條件標記。表頭列也要放 ——
  只拿掉標題的話，零筆明細只會把資料列清空，留下一條只有表頭的空表格。

藥丸格式（取自 dobtor_doc_editor 的測試與出貨範本）：
    {'type': 'label', 'value': 標籤, 'extension': {'dobtorField': {'source': …, …}}}
    source='expression'  Jinja 表達式，`object` 是建議書，`data` 是 doc_report_values()
    source='condition'   段落／表格列層級的條件，假則整段（列）移除
    source='repeat'      放在某一列的任一格，宣告該列對 sourceExpression 的清單重複
    source='line'        重複列內的欄位，path 相對於當前這一筆
"""
import json

#: 內容寬度（canvas-editor 的 A4、左右邊距 96px 時的可用寬度）
WIDTH = 718

NL = {'value': '\n'}

#: 外觀取自既有報價規格書（預建 v6、以賽亞 v2.0、SKF 7.4）共同的作法：
#: 微軟正黑體、內文 10.5pt（＝14px）、章節標題 15pt、封面標題 27pt、主題色標題。
#: 每份文件有自己的主題色；這裡取 SKF 那份的藍。表頭底色在 `docx_polish`（用同一個色）。
FONT = 'Microsoft JhengHei'
BODY_SIZE = 14
THEME = '#1F4E79'
THEME_LIGHT = '#2E75B6'
GRAY = '#666666'

_PILL_STYLE = {'backgroundColor': '#e3f2fd', 'color': '#1976d2'}


# ----------------------------------------------------------------------
# 元素
# ----------------------------------------------------------------------
def text(value, size=None, bold=False, color=None):
    # ★ 字型要寫在每個元素上：doc_editor 轉 DOCX 時才會連東亞字型（eastAsia）一起設，
    #   沒設的話 Word 會用預設字型，中文字體就不是我們要的那一個。
    el = {'value': value, 'font': FONT, 'size': size or BODY_SIZE}
    if bold:
        el['bold'] = True
    if color:
        el['color'] = color
    return el


def pill(label, expression=None, source='expression', size=None, bold=False, color=None,
         **meta):
    meta = dict(meta, labelText=label, source=source)
    if expression is not None:
        meta['expression'] = expression
    el = {'type': 'label', 'value': label, 'label': dict(_PILL_STYLE),
          'extension': {'dobtorField': meta}, 'font': FONT, 'size': size or BODY_SIZE}
    if bold:
        el['bold'] = True
    if color:
        el['color'] = color
    return el


def page_break():
    return {'type': 'pageBreak', 'value': '\n'}


def condition(expression):
    """條件標記：放在段落或表格列裡，條件為假時整段（列）移除，成立時標記本身不印。"""
    return pill('條件', source='condition', expression=expression)


def para(*elements, center=False):
    """一個段落＝若干元素＋結尾換行；置中要設在換行元素上（canvas-editor 的慣例）。"""
    nl = dict(NL, rowFlex='center') if center else dict(NL)
    return list(elements) + [nl]


def blank():
    return [dict(NL)]


def heading(key, title, show_expr=None, size=20):
    """章節標題：編號是動態的（`data.chap.<鍵>`），沒資料的章節整段消失。"""
    els = []
    if show_expr:
        els.append(condition(show_expr))
    els.append(pill(title, "(data.chap.%s or '') ~ '、%s'" % (key, title), size=size, bold=True,
                    color=THEME))
    return para(*els)


def _cell(*elements, **kw):
    return dict({'value': list(elements) + [dict(NL)]}, **kw)


def table(widths, header, fields, source_expr, repeat_id, show_expr=None, bold_header=True):
    """表頭一列＋資料一列（對 `source_expr` 重複）。

    `fields` 是每欄在重複列內的 line 欄位 path；欄數必須與表頭一致。
    ★ 表頭列也放條件標記（見模組說明），所以 show_expr 會用兩次。
    """
    assert len(widths) == len(header) == len(fields), 'columns mismatch'
    head_cells = []
    for i, label in enumerate(header):
        els = [text(label, bold=bold_header)]
        if i == 0 and show_expr:
            els.insert(0, condition(show_expr))
        head_cells.append(_cell(*els))
    body_cells = []
    for i, path in enumerate(fields):
        els = [pill(path, source='line', path=path)]
        if i == 0:
            els.insert(0, pill('明細', source='repeat', sourceExpression=source_expr,
                               repeatId=repeat_id))
        body_cells.append(_cell(*els))
    return {
        'type': 'table', 'value': '',
        'trList': [{'tdList': head_cells}, {'tdList': body_cells}],
        'colgroup': [{'width': w} for w in widths],
    }


# ----------------------------------------------------------------------
# 範本
# ----------------------------------------------------------------------
def separate_tables(main):
    """每張表後面補一個換行，除非後面本來就是換行。

    ☠️ 段落的邊界是 `value == '\\n'` 的元素，表格本身不是邊界。表格後面直接接一個條件段落時，
       兩者會被當成**同一個段落**：條件為假，連前面那張表一起被刪掉 —— 而且不報錯。
       （工時制的預算大類表就是這樣不見的：後面緊接著「計費明細」小標題，工時制時它為假。）
    """
    out = []
    for idx, el in enumerate(main):
        out.append(el)
        if isinstance(el, dict) and el.get('type') == 'table':
            nxt = main[idx + 1] if idx + 1 < len(main) else None
            if not (isinstance(nxt, dict) and nxt.get('value') == '\n'):
                out.append(dict(NL))
    return out


def build():
    """回傳 content_json 的 dict（header／main／footer）。"""
    main = []

    # --- 封面 ---------------------------------------------------------
    main += blank()
    main += para(pill('客戶', 'data.cover.customer', size=36, bold=True, color=THEME), center=True)
    main += para(pill('標題', 'data.cover.title', size=27, bold=True, color=THEME), center=True)
    main += para(pill('副標', 'data.cover.subtitle', size=17, color=THEME_LIGHT), center=True)
    main += blank()
    main += para(text('文件版本：', bold=True), pill('版號', 'data.cover.version_no'),
                 text('　｜　日期：', bold=True), pill('日期', 'data.cover.date'), center=True)
    main += para(condition('data.cover.purpose'), text('文件用途：', bold=True),
                 pill('用途', 'data.cover.purpose'), center=True)
    main += para(condition('data.cover.basis'), text('報價基礎：', bold=True),
                 pill('報價基礎', 'data.cover.basis'), center=True)
    main += blank()
    main += para(pill('公司', 'data.cover.company', size=17, bold=True), center=True)
    main += para(text('CONFIDENTIAL / 機密', size=13, color=GRAY), center=True)
    main.append(page_break())

    # --- 需求核對與本版處理 ----------------------------------------------
    main += heading('changes', '需求核對與本版處理', 'data.show.changes')
    main.append(table([50, 250, 300, 118], ['#', '貴公司核對項', '本版處理', '對應章節'],
                      ['ref_no', 'demand', 'handling', 'chapter'],
                      'data.changes', 'changes', 'data.show.changes'))
    main += blank()

    # --- 系統總覽 -----------------------------------------------------------
    main += heading('overview', '系統總覽', 'data.show.overview')
    main += para(condition('data.show.overview'), text('客戶業務概述', size=14, bold=True))
    main += para(condition('data.overview.narrative'), pill('概述', 'data.overview.narrative'))
    main += para(condition('data.show.drivers'), text('導入規模', size=14, bold=True))
    main.append(table([359, 359], ['項目', '數量'], ['name', 'value'],
                      'data.drivers', 'drivers', 'data.show.drivers'))
    main += blank()

    # --- 解決方案總覽 -------------------------------------------------------
    main += heading('solution', '解決方案總覽', 'data.show.solution')
    main.append(table([150, 250, 218, 100], ['能力', '解決的痛點', '帶來的成果', '分類'],
                      ['name', 'pain', 'outcome', 'color_label'],
                      'data.caps', 'caps', 'data.show.solution'))
    main += blank()

    # --- 需求 × 解決方案對照 --------------------------------------------------
    main += heading('matrix', '需求 × 解決方案對照（現有／客製標注）', 'data.show.matrix')
    main.append(table([40, 250, 270, 158], ['#', '貴公司需求', '系統做法', '分類'],
                      ['no', 'description', 'how', 'color_label'],
                      'data.matrix', 'matrix', 'data.show.matrix'))
    main += blank()

    # --- 資料移轉 -----------------------------------------------------------
    main += heading('migration', '資料移轉範圍與客戶交付義務', 'data.show.migration')
    main.append(table([250, 250, 118, 100], ['資料集', '系統模型', '預估筆數', '客戶已提供'],
                      ['label', 'model', 'records', 'provided'],
                      'data.masters', 'masters', 'data.show.migration'))
    main += blank()

    # --- 範圍界線 -----------------------------------------------------------
    main += heading('scope', '範圍界線', 'data.show.scope')
    main.append(table([130, 220, 368], ['類別', '項目', '說明'],
                      ['kind_label', 'name', 'detail'],
                      'data.scope', 'scope', 'data.show.scope'))
    main += blank()

    # --- 預算規劃 -----------------------------------------------------------
    main += heading('budget', '預算規劃', 'data.show.budget')
    main += para(condition('data.show.budget_time'), text('工時與預算配比', size=14, bold=True))
    main += para(condition('data.show.budget_time'), pill('工時摘要', 'data.budget.summary'))
    main.append(table([150, 240, 100, 80, 148],
                      ['預算大類', '涵蓋內容', '工時 (h)', '占比', '金額 (NTD)'],
                      ['name', 'scope_text', 'hours', 'ratio', 'amount'],
                      'data.budget_units', 'budget_units', 'data.show.budget_time'))
    main += para(condition('data.show.budget_sub'), text('計費明細', size=14, bold=True))
    main.append(table([130, 400, 188], ['項目', '內容', '金額（首年）'],
                      ['item', 'content', 'amount'],
                      'data.budget_lines', 'budget_lines', 'data.show.budget_sub'))
    main += para(condition('data.show.budget'), text('合計（首年）：', bold=True),
                 pill('合計', 'data.budget.total'))
    main += para(condition('data.budget.cap'), text('客戶預算上限：', bold=True),
                 pill('預算', 'data.budget.cap'), text('　'), pill('差額', 'data.budget.gap'))
    main += blank()

    # --- 期程 ---------------------------------------------------------------
    main += heading('phases', '導入期程與里程碑', 'data.show.phases')
    main.append(table([50, 130, 200, 90, 70, 178],
                      ['階段', '名稱', '內容', '期間', '工時 (h)', '里程碑'],
                      ['code', 'name', 'content', 'period', 'hours', 'milestone'],
                      'data.phases', 'phases', 'data.show.phases'))
    main += blank()

    # --- 驗收與付款 ---------------------------------------------------------
    main += heading('payment', '驗收與付款', 'data.show.payment')
    main += para(condition('data.show.units'), text('驗收單元與標準', size=14, bold=True))
    main.append(table([150, 418, 150], ['驗收單元', '驗收標準（須全數通過）', '金額 (NTD)'],
                      ['name', 'criteria', 'amount'],
                      'data.units', 'units', 'data.show.units'))
    main += para(condition('data.show.payments'), text('付款款別', size=14, bold=True))
    main.append(table([150, 268, 100, 200], ['款別', '時點', '比例', '金額 (NTD)'],
                      ['name', 'trigger', 'ratio', 'amount'],
                      'data.payments', 'payments', 'data.show.payments'))
    main += blank()

    # --- 前提與客戶配合事項 -----------------------------------------------------
    main += heading('obligations', '前提與客戶配合事項', 'data.show.obligations')
    main.append(table([160, 558], ['類別', '內容'], ['kind_label', 'text'],
                      'data.obligations', 'obligations', 'data.show.obligations'))
    main += blank()

    # --- 備註與免責 ---------------------------------------------------------
    main += heading('clauses', '備註與免責', 'data.show.clauses')
    main.append(table([50, 668], ['#', '條款'], ['no', 'text'],
                      'data.clauses', 'clauses', 'data.show.clauses'))
    main += blank()

    # --- 效益評估 -----------------------------------------------------------
    main += heading('benefits', '效益評估', 'data.show.benefits')
    main.append(table([180, 150, 150, 238],
                      ['作業項目', '現況人工', '導入後', '年化節省估算（假設）'],
                      ['name', 'current', 'after', 'saving_text'],
                      'data.benefits', 'benefits', 'data.show.benefits'))
    main += para(condition('data.show.benefits'), text('年化節省合計（假設）：', bold=True),
                 pill('合計', 'data.budget.benefit_total'))

    footer = para(pill('公司', 'data.cover.company', size=12, color=GRAY), text('　｜　', size=12, color=GRAY),
                  pill('版號', "data.cover.customer ~ ' ' ~ data.cover.version_no", size=12,
                       color=GRAY),
                  text('　｜　第 ', size=12, color=GRAY),
                  pill('頁碼', source='page', part='number', size=12, color=GRAY),
                  text(' 頁', size=12, color=GRAY), center=True)
    return {'header': [], 'main': separate_tables(main), 'footer': footer}


def build_json():
    return json.dumps(build(), ensure_ascii=False)
