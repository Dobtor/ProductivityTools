#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""掃 docstring 裡的絕對語句——稽核尺 5 的工具。

☠️ 為什麼這是一把值得定期拿出來用的尺：
`doc.editor.export.log.record_export()` 的 docstring 曾經承諾
「任何例外都吞掉——log 失敗**絕不**可擋住下載」，而它做不到
（`try/except` 只接得住 Python 例外，PostgreSQL 的交易已經 aborted，
呼叫端接下來的 DB 動作全部會失敗）。那個承諾是**假的**，而且沒有任何東西
會紅——直到有人真的去讀那句話並問「它真的做得到嗎」。

2026-10-09 拿這把尺掃出 21 處絕對語句，逐一判讀後只有一處是真缺陷：
`json_http_route` 的 docstring 標題行寫「保證永遠回 JSON」，而函式體裡
有兩個刻意的例外（HTTPException / SessionExpiredException 原樣往上拋）。
行為是對的、註解也寫得很完整——錯的是**標題行**，而那一行才是別人會讀到的。

其餘 20 處是描述性的（「取不到值一律回空字串」這類），不是對呼叫者的承諾。
**判讀需要人**：這支腳本只負責把候選撈出來，不負責判定。
把它當成 lint 自動擋會立刻變成噪音，然後被人加例外清單繞過去。

用法：
    python3 tests/scripts/scan_absolute_promises.py            # 本模組
    python3 tests/scripts/scan_absolute_promises.py ../dobtor_doc_import
"""
import ast
import pathlib
import sys

# 絕對語句：承諾了就必須做到。中英文都掃（本模組的註解是中文，
# 但第三方程式碼與早期檔案有英文）。
ABSOLUTES = (
    '絕不', '絕對不', '永遠不', '永遠都', '一定會', '必然', '不可能',
    '保證', '不會有', '一律',
    'never ', 'always ', 'guarantee', 'cannot fail', 'impossible',
)

SCAN_DIRS = ('models', 'controllers', 'wizards')


def scan(module_root):
    root = pathlib.Path(module_root)
    hits = []
    for sub in SCAN_DIRS:
        base = root / sub
        if not base.exists():
            continue
        for f in sorted(base.rglob('*.py')):
            tree = ast.parse(f.read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                         ast.ClassDef)):
                    continue
                doc = ast.get_docstring(node) or ''
                if not doc:
                    continue
                headline = doc.strip().split('\n')[0]
                for kw in ABSOLUTES:
                    if kw not in doc:
                        continue
                    for line in doc.split('\n'):
                        if kw in line:
                            hits.append({
                                'file': str(f.relative_to(root)),
                                'name': node.name,
                                'keyword': kw.strip(),
                                'line': line.strip(),
                                # 標題行裡的絕對語句最危險：它是別人唯一會讀的
                                'in_headline': kw in headline,
                            })
                    break
    return hits


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else \
        str(pathlib.Path(__file__).resolve().parents[2])
    hits = scan(root)
    headline = [h for h in hits if h['in_headline']]
    print('掃到 %d 處絕對語句，其中 %d 處在 docstring 的**標題行**。'
          % (len(hits), len(headline)))
    print('標題行那些最危險：它是 IDE 提示與快速瀏覽唯一會顯示的部分。\n')
    for h in sorted(hits, key=lambda x: (not x['in_headline'], x['file'])):
        mark = '★ 標題行' if h['in_headline'] else '  '
        print('%s %-28s %-34s 「%s」' % (mark, h['file'], h['name'], h['keyword']))
        print('       %s' % h['line'][:120])
    print('\n☠️ 判讀需要人。這支只撈候選，不判定——'
          '當成 lint 自動擋會變噪音，然後被例外清單繞過去。')
    # 刻意**不**用退出碼表示「有候選」：它不是閘門，是尺。
    return 0


if __name__ == '__main__':
    sys.exit(main())
