"""藥丸管線測試的共用 helper。

原本在 test_pill_pipeline.py 的檔頭。拆成五支之後每一支都要用，
所以抽出來——複製五份的話改一個欄位要改五個地方。

☠️ _cell 原本在**原檔的中段**（第 532 行附近），而它前後的類別都在用它。
第一次拆的時候它跟著所在位置被分到 output.py，於是 snapshot 與 sandbox
那兩批變成 undefined name——pyflakes 抓到的。它是真正共用的，放這裡。
（另外三個類別各自還有一支 self._cell method，簽名不同，那些留在原處。）
"""


def _text(value, **kw):
    return dict({'value': value}, **kw)


def _pill(label_text, **meta):
    payload = {'labelText': label_text}
    payload.update(meta)
    return {
        'type': 'label',
        'value': label_text,
        'label': {'backgroundColor': '#e3f2fd', 'color': '#1976d2'},
        'extension': {'dobtorField': payload},
    }


def _cell(*elements, **kw):
    return dict({'colspan': 1, 'rowspan': 1,
                 'value': list(elements) + [_text('\n')]}, **kw)
