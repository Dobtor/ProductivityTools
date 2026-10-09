#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""尺：全檔案清查與分類（`make audit` 的一部分）。

把兩個模組的每一個追蹤檔案歸入一類，並**驗證分類總數等於 git 的檔案數**
——分類漏了比沒分類更糟，因為它給人「都看過了」的錯覺。

☠️ 2026-10-09 第一版用 `subprocess.run(..., text=True)` 配 `git ls-files`，
**掉了 181 個檔案**（算出 959 而非 1140）。改用 `-z` ＋ 顯式 bytes 解碼才對。
最後那一行「合計 vs git ls-files」的對帳就是為了讓這種錯誤無法通過。

用法：python3 tests/scripts/audit_file_inventory.py [模組…]
"""
import collections
import os
import subprocess
import sys

#: ☠️ 從 repo 根跑 git ls-files。第一版沒有這一段，從模組目錄裡執行時
#:    `git ls-files dobtor_doc_editor …` 什麼都找不到，而腳本回報
#:    「合計 0（git ls-files = 0）✓ 相符」——**0 等於 0 所以過關**。
#:    那正是本模組一整天在修的「沒量到東西卻說通過」，發生在量測工具自己身上。
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

DEFAULT_MODULES = ('dobtor_doc_editor', 'dobtor_doc_import')


def tracked_files(modules):
    """☠️ 一定要用 `-z`：換行分隔 ＋ text=True 會掉檔案。"""
    out = subprocess.run(['git', 'ls-files', '-z', *modules],
                         capture_output=True, cwd=REPO_ROOT)
    return [f.decode('utf8', 'replace') for f in out.stdout.split(b'\x00') if f]


def classify(path):
    rest = '/'.join(path.split('/')[1:])
    if rest.startswith(('tests/fixtures/', 'tests/goldens/')):
        return '測試資料'
    if rest.startswith('tests/'):
        return '測試'
    if rest.startswith('docs/') or rest.endswith('.md'):
        return '文件'
    if rest.startswith('tools/dist/') or 'canvas-editor-custom.umd' in rest:
        return '建置產物'
    if rest.startswith(('tools/', 'scripts/', 'spikes/')):
        return '工具／量測'
    if rest.startswith('static/src/'):
        return '前端源碼'
    if rest.startswith('static/'):
        return '前端其他'
    if rest.startswith(('models/', 'controllers/', 'wizards/', 'views/',
                        'security/', 'data/', 'report/', 'migrations/',
                        'i18n/', 'LICENSES/')):
        return '出貨'
    if rest in ('__manifest__.py', '__init__.py', 'Makefile', 'LICENSE',
                '.gitignore', 'package.json', 'package-lock.json'):
        return '出貨'
    if rest.startswith(('rollup.', 'tsconfig', 'vitest.config', '.eslintrc',
                        'babel.')):
        return '建置設定'
    return '未歸類'


def main():
    modules = sys.argv[1:] or list(DEFAULT_MODULES)
    files = tracked_files(modules)
    tab = collections.defaultdict(collections.Counter)
    unclassified = collections.defaultdict(list)
    for f in files:
        mod = f.split('/')[0]
        c = classify(f)
        tab[mod][c] += 1
        if c == '未歸類':
            unclassified[mod].append(f)
    total = 0
    for mod in modules:
        n = sum(tab[mod].values())
        total += n
        print('\n════ %s  %d 檔 ════' % (mod, n))
        for k, v in sorted(tab[mod].items(), key=lambda x: -x[1]):
            print('  %-10s %5d' % (k, v))
        # ☠️ 用 .get() 不要用 unclassified[mod]——後者在 defaultdict 上
        #    **會生出空 key**，於是底下 `if unclassified:` 恆為真，
        #    印出假的「有未歸類的檔案」警告。假警告比沒警告更糟：
        #    它會訓練人無視警告。
        for f in unclassified.get(mod, ()):
            print('       未歸類：%s' % f)
    # ☠️ 先擋「一個檔案都沒撈到」。沒有這一段，total=0 == len(files)=0
    #    會印出「✓ 相符」——量測工具自己的空洞通過。
    if not files:
        print('\n✗ 一個追蹤檔案都沒撈到（模組名打錯？不在 git repo 裡？）')
        print('  這**不是**通過——「0 等於 0」不算相符。')
        return 2
    counted = total == len(files)
    ok = counted and not any(unclassified.values())
    print('\n合計 %d（git ls-files = %d）  %s'
          % (total, len(files), '✓ 相符' if counted else '✗ 不符'))
    if any(unclassified.values()):
        print('☠️ 有未歸類的檔案——分類漏了比沒分類更糟（它給人「都看過了」的錯覺）')
    # 刻意回 0：這是尺，不是閘門。工具自己壞了（總數不符／有未歸類）才回 1。
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
