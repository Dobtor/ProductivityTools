#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""尺：路由到底有沒有被任何東西驗過（`make audit` 的一部分）。

☠️ 這把尺最重要的一步**不是靜態分析**，是「**跑一次 tour，從 werkzeug 的
存取日誌看它實際打到哪些路由**」。

2026-10-09 量到的事實推翻了一個很合理的假設：tour 有 66 個 trigger、616 行，
看起來「前端都走過了」——實際只打到 **5 條**路由。核心 36 條裡 **22 條完全
沒有任何驗證**（沒有 Python 測試、tour 也沒走到），包含 /dobtor_doc/export、
4 條版本路由、5 條 i18n 路由全部。

「有出貨 JS 在呼叫它」不等於「有東西驗過它」。

用法：
    python3 tests/scripts/audit_route_coverage.py              # 靜態部分
    TOUR_LOG=/tmp/dobtor_doc_editor_tour.log \
        python3 tests/scripts/audit_route_coverage.py          # 併入 tour 實測

拿 tour 日誌的方式：先 `bash tests/scripts/run_local_rig.sh tour`，
日誌在 /tmp/dobtor_doc_editor_tour.log。
"""
import ast
import os
import re
import sys

# ☠️ 這支檔案在 <模組>/tests/scripts/ 底下，所以 dirname 三次剛好是**模組根**。
#    第一版又在後面 join 了一次模組名，變成 dobtor_doc_editor/dobtor_doc_editor
#    ——於是 declared_routes() 回空陣列、語料庫長度 0，而腳本印出
#    「完全沒有驗證的路由：0 條」。**什麼都沒量到卻看起來像好消息。**
#    底下 main() 的「0 條路由」守衛就是為了讓這種錯誤無法通過。
CORE = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))


def declared_routes(module_root):
    out = []
    ctrl = os.path.join(module_root, 'controllers')
    if not os.path.isdir(ctrl):
        return out
    for name in sorted(os.listdir(ctrl)):
        if not name.endswith('.py') or name == '__init__.py':
            continue
        with open(os.path.join(ctrl, name), encoding='utf-8') as fh:
            tree = ast.parse(fh.read())
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if not isinstance(dec, ast.Call):
                    continue
                if (getattr(dec.func, 'attr', None)
                        or getattr(dec.func, 'id', None)) != 'route':
                    continue
                paths = []
                for arg in dec.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        paths.append(arg.value)
                    elif isinstance(arg, (ast.List, ast.Tuple)):
                        paths += [e.value for e in arg.elts
                                  if isinstance(e, ast.Constant)]
                for p in paths:
                    out.append((p, node.name, name))
    return out


#: ☠️ `test_route_smoke.py` 要從「有沒有測試」的語料庫裡排除。
#:    它的 `_UNVERIFIED` 清單把 22 條零驗證路由的路徑**寫成字串**，
#:    所以把它算進去的話每條路由都「在測試裡出現過」→ 量出「零驗證 0 條」。
#:    這跟 legacy 例外清單養活 legacy 檔案是同一個形狀：**宣告某物沒被驗的
#:    那份清單，本身讓它看起來被驗了。** 第一版就是這樣量錯的。
#: ☠️ 不能整個排除 `test_route_smoke.py`——它同時裝著 `_UNVERIFIED`（清單，
#:    會造成誤判）與 `TestListModelsBehaviour`（真的行為測試）。整個排掉會把
#:    `/dobtor_doc/models` 誤報成零驗證。只剔掉 `_UNVERIFIED = {…}` 那個區塊。
STRIP_BLOCKS = {'test_route_smoke.py': '_UNVERIFIED = {'}

#: ☠️ `tests/scripts/` 整個目錄也要排除——那裡放的是**工具**，不是測試。
#:    這一條是實測踩出來的：本腳本自己的 docstring 寫了
#:    「包含 /dobtor_doc/export、4 條版本路由…」，而腳本就在 tests/scripts/
#:    底下，於是**描述缺口的文字讓那個缺口看起來補好了**。
#:    今天同一個形狀出現三次：
#:      1. legacy 例外清單養活 legacy 檔案
#:      2. _UNVERIFIED 清單讓 22 條路由看起來被驗過
#:      3. 這一條
#:    共同點：**宣告某物有問題的那份文字，本身成了它沒問題的證據。**
EXCLUDE_DIRS = ('scripts',)


def _corpus(root, subdirs, exts):
    text = []
    for sub in subdirs:
        base = os.path.join(root, sub)
        for dirpath, _d, files in os.walk(base):
            if 'node_modules' in dirpath:
                continue
            if any(os.sep + d in dirpath + os.sep for d in EXCLUDE_DIRS):
                continue
            for f in files:
                if f.endswith(exts):
                    with open(os.path.join(dirpath, f), encoding='utf-8',
                              errors='ignore') as fh:
                        body = fh.read()
                    marker = STRIP_BLOCKS.get(f)
                    if marker and marker in body:
                        head, rest = body.split(marker, 1)
                        body = head + rest.split('}', 1)[-1]
                    text.append(body)
    return '\n'.join(text)


def tour_hits(log_path):
    """從 werkzeug 存取日誌抽出被打到的路由。"""
    if not log_path or not os.path.exists(log_path):
        return None
    with open(log_path, 'rb') as fh:
        blob = fh.read().decode('utf8', 'replace')
    return set(re.findall(r'"(?:POST|GET) (/dobtor[a-zA-Z0-9_/]*)', blob))


def main():
    routes = declared_routes(CORE)
    tests = _corpus(CORE, ('tests',), ('.py',))
    js = _corpus(CORE, ('static',), ('.js',))
    hits = tour_hits(os.environ.get('TOUR_LOG'))

    # ☠️ 一條路由都沒撈到 → 工具壞了，不是「全部都驗過了」
    if not routes:
        print('✗ 一條路由都沒撈到（%s/controllers 不存在？）' % CORE)
        print('  這**不是**通過——什麼都沒量到就不能說覆蓋率好。')
        return 2
    print('核心宣告的路由：%d 條' % len(routes))
    if hits is None:
        print('⚠️  沒有 tour 日誌（設 TOUR_LOG=…），這一輪只有靜態部分')
        print('    ——**那會高估覆蓋率**：出貨 JS 引用 ≠ 有東西驗過它')
    else:
        print('tour 實際打到：%d 條  %s' % (len(hits), sorted(hits)))
    print()
    zero = []
    for path, meth, fn in sorted(routes):
        pre = path.split('<')[0]
        # ☠️ 只認「**路徑**在測試裡出現過」，不認方法名。
        #    方法名可能只出現在 AST 註冊檢查（`hasattr(Controller, 'x')`）
        #    或 docstring 裡——那不代表行為被驗過。本模組的
        #    `/dobtor_doc/models` 就是血淋淋的例子：它有一則「測試」只斷言
        #    `hasattr(DocTemplateController, 'list_models')`，而那條路由
        #    **一直是壞的**（ir.model 沒有 abstract 欄位）。
        #    判準要與 tests/test_route_smoke.py 的 `_UNVERIFIED` 一致，
        #    否則兩邊會給出不同的數字（第一版就差了一條）。
        in_py = pre in tests
        in_js = pre in js
        in_tour = hits is not None and any(h.startswith(pre) for h in hits)
        verified = in_py or in_tour
        mark = '✓' if verified else '✗'
        if not verified:
            zero.append(path)
        print('  %s %-44s py=%s js=%s tour=%s'
              % (mark, path, 'Y' if in_py else '-',
                 'Y' if in_js else '-',
                 ('Y' if in_tour else '-') if hits is not None else '?'))
    print('\n完全沒有驗證的路由：%d 條' % len(zero))
    for p in zero:
        print('    %s' % p)
    print('\n☠️ 這是尺，不是閘門——分母在 tests/test_route_smoke.py 的 '
          '_UNVERIFIED，那裡有守衛確保「補了測試就要從清單拿掉」。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
