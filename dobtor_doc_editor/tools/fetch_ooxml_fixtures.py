#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LibreOffice OOXML regression 測試語料下載器 — dobtor_doc_editor。

從 LibreOffice/core 的 Writer OOXML import/export 回歸測試語料庫，
抓取一批策展過的真實 .docx 測試檔，做為 dobtor parser 的廣域回歸 fixture。

來源 pin 在固定 commit（見 PINNED_SHA），確保可重現與授權標註。
檔案授權：MPL-2.0（LibreOffice 專案）。下載後保留 PROVENANCE.md 標註。

輸出：
    tests/fixtures/10_ooxml_libreoffice/<category>/<file>.docx
    tests/fixtures/10_ooxml_libreoffice/PROVENANCE.md
    tests/fixtures/10_ooxml_libreoffice/manifest.json

用法：
    python3 tools/fetch_ooxml_fixtures.py --out tests/fixtures [--target 290]
"""
import argparse
import json
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

# ── 來源設定（遵守 CLAUDE.md：禁止 magic string）─────────────────────────
REPO = "LibreOffice/core"
# pin 在固定 commit — 可重現、授權可追溯
PINNED_SHA = "52d51655e3cdfe92893a823545f596f33f1731db"
SOURCE_DIRS = (
    "sw/qa/extras/ooxmlimport/data",   # import 測試（全收：每檔都是 parser 案例）
    "sw/qa/extras/ooxmlexport/data",   # export 測試（策展抽樣）
)
API_BASE = "https://api.github.com/repos"
RAW_BASE = "https://raw.githubusercontent.com"
HTTP_HEADERS = {"User-Agent": "dobtor-fixture-fetcher"}
HTTP_TIMEOUT = 30

# 加密檔無法直接解 zip，對「可解析」型 fixture 是純噪音 → 排除
SKIP_PREFIXES = ("Encrypted_",)

# 分類關鍵字（檔名小寫子字串）；順序即優先序，先命中者勝
CATEGORY_RULES = [
    ("math", ("math", "equation", "formula", "mathtype", "omml")),
    ("chart", ("chart",)),
    ("smartart", ("smartart", "diagram", "dgm")),
    ("note", ("footnote", "endnote", "comment", "annotation")),
    ("track", ("track", "redline", "movefrom", "moveto", "change")),
    ("sdt", ("sdt", "contentcontrol", "content-control")),
    ("table", ("table", "tbl", "cell", "merge")),
    ("image", ("image", "picture", "pict", "graphic", "crop",
               "jpeg", "png", "bitmap", "wmf", "emf")),
    ("shape", ("shape", "textbox", "text-box", "drawing", "group",
               "wps", "wpg", "vml", "anchor", "wrap", "float")),
    ("headerfooter", ("header", "footer", "hdrftr", "hdftr")),
    ("list", ("list", "numbering", "bullet", "numbered")),
    ("field", ("field", "hyperlink", "toc", "bookmark", "index")),
    ("style", ("style", "theme", "font", "color")),
    ("section", ("section", "sect", "margin", "column", "break")),
]
# export 每類最多取的份數（控制總量、確保跨類分散）
EXPORT_CAP_PER_CATEGORY = 16
DEFAULT_TARGET_TOTAL = 290


def http_get(url):
    """GET 回傳 bytes。"""
    req = urllib.request.Request(url, headers=HTTP_HEADERS)
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        return resp.read()


def list_dir(repo_dir):
    """列出 repo 內某目錄的 .docx 檔名（pin 在 PINNED_SHA）。"""
    url = f"{API_BASE}/{REPO}/contents/{repo_dir}?ref={PINNED_SHA}"
    data = json.loads(http_get(url).decode("utf-8"))
    names = []
    for entry in data:
        name = entry.get("name", "")
        if not name.endswith(".docx"):
            continue
        if name.startswith(SKIP_PREFIXES):
            continue
        names.append(name)
    return sorted(names)


def categorise(filename):
    """依檔名關鍵字分類；無命中歸 misc。"""
    low = filename.lower()
    for category, keywords in CATEGORY_RULES:
        if any(kw in low for kw in keywords):
            return category
    return "misc"


def select_fixtures(import_files, export_files, target_total):
    """策展選檔。回傳 [(repo_dir, filename, category), ...]。

    策略：import 目錄全收（每檔都是 parser 案例）；export 目錄做
    跨類 round-robin 抽樣，補到 target_total，每類設上限避免單類灌爆。
    """
    import_dir, export_dir = SOURCE_DIRS
    selected = [(import_dir, n, categorise(n)) for n in import_files]

    # export 依類分桶
    buckets = {}
    for name in export_files:
        buckets.setdefault(categorise(name), []).append(name)
    for names in buckets.values():
        names.sort()

    remaining = max(0, target_total - len(selected))
    taken = {cat: 0 for cat in buckets}
    # round-robin：每輪每類取一個，直到補滿或全類達上限
    progress = True
    while remaining > 0 and progress:
        progress = False
        for category in sorted(buckets):
            if remaining <= 0:
                break
            idx = taken[category]
            if idx >= len(buckets[category]) or idx >= EXPORT_CAP_PER_CATEGORY:
                continue
            selected.append((export_dir, buckets[category][idx], category))
            taken[category] += 1
            remaining -= 1
            progress = True
    return selected


def download(repo_dir, filename, dest_path):
    """下載單檔到 dest_path。回傳錯誤字串或 ''。"""
    url = f"{RAW_BASE}/{REPO}/{PINNED_SHA}/{repo_dir}/{filename}"
    try:
        data = http_get(url)
    except urllib.error.URLError as exc:
        return f"下載失敗：{exc}"
    if not data:
        return "下載內容為空"
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_bytes(data)
    return ""


def zip_ok(path):
    """確認是合法 zip 且含 word/document.xml。回傳 True/False。

    注意：LibreOffice 語料含「故意畸形」的負向測試檔，驗不過屬正常，
    僅標記不刪除。
    """
    try:
        with zipfile.ZipFile(path) as zf:
            return "word/document.xml" in zf.namelist()
    except (zipfile.BadZipFile, OSError):
        return False


PROVENANCE_TEMPLATE = """\
# OOXML 測試 fixture 來源說明

本目錄 `10_ooxml_libreoffice/` 下的 `.docx` 檔**並非本專案產出**，
而是從 LibreOffice 專案的 Writer OOXML 回歸測試語料庫下載，
做為 dobtor_doc_editor parser 的廣域回歸測試 fixture。

## 來源

- 專案：LibreOffice / core
- Repo：https://github.com/{repo}
- Commit（pinned）：`{sha}`
- 目錄：
{dirs}

## 授權

LibreOffice 專案以 **MPL-2.0** 授權（部分歷史檔 LGPLv3+）。
這些測試檔隨專案散布，沿用同一授權。本目錄檔案**請勿修改**，
維持與上游一致；如需更新請重跑 `tools/fetch_ooxml_fixtures.py`。

## 注意

- 部分檔案為**故意畸形 / 加密 / 邊界**的負向測試案例，
  parser 對它們應「優雅失敗」而非崩潰——這正是測試目的。
- 檔案依檔名關鍵字粗分到各 category 子目錄，分類僅供瀏覽方便，
  不代表上游的權威分類。
- 完整檔案清單與分類見同目錄 `manifest.json`。

## 重新產生

```
python3 tools/fetch_ooxml_fixtures.py --out tests/fixtures
```
"""


def main():
    parser = argparse.ArgumentParser(description="OOXML 測試 fixture 下載器")
    parser.add_argument("--out", required=True,
                        help="fixture 輸出根目錄（通常是 tests/fixtures）")
    parser.add_argument("--target", type=int, default=DEFAULT_TARGET_TOTAL,
                        help=f"目標下載總數（預設 {DEFAULT_TARGET_TOTAL}）")
    args = parser.parse_args()

    out_dir = Path(args.out) / "10_ooxml_libreoffice"

    print(f"[1/3] 列出來源目錄（pin @ {PINNED_SHA[:10]}）...")
    try:
        import_files = list_dir(SOURCE_DIRS[0])
        export_files = list_dir(SOURCE_DIRS[1])
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        print(f"列目錄失敗：{exc}", file=sys.stderr)
        return 1
    print(f"    import {len(import_files)} 檔 / export {len(export_files)} 檔")

    selected = select_fixtures(import_files, export_files, args.target)
    print(f"[2/3] 策展選出 {len(selected)} 檔，開始下載 ...")

    manifest = {
        "source_repo": REPO,
        "pinned_sha": PINNED_SHA,
        "source_dirs": list(SOURCE_DIRS),
        "license": "MPL-2.0 (LibreOffice project)",
        "files": [],
    }
    cat_count = {}
    ok = malformed = failed = 0
    seen = {}
    for repo_dir, filename, category in selected:
        # 同類內檔名碰撞 → 加序號
        stem, suffix = filename.rsplit(".", 1)
        key = (category, filename)
        if key in seen:
            seen[key] += 1
            local_name = f"{stem}_{seen[key]}.{suffix}"
        else:
            seen[key] = 1
            local_name = filename
        dest = out_dir / category / local_name
        err = download(repo_dir, filename, dest)
        if err:
            failed += 1
            print(f"    ✗ {category}/{local_name}：{err}")
            continue
        valid = zip_ok(dest)
        ok += 1
        if not valid:
            malformed += 1
        cat_count[category] = cat_count.get(category, 0) + 1
        manifest["files"].append({
            "category": category,
            "local_path": str(dest.relative_to(out_dir)),
            "source": f"{repo_dir}/{filename}",
            "valid_zip": valid,
        })
    print(f"[3/3] 寫入 PROVENANCE.md / manifest.json ...")
    out_dir.mkdir(parents=True, exist_ok=True)
    dirs_block = "\n".join(f"  - `{d}`" for d in SOURCE_DIRS)
    (out_dir / "PROVENANCE.md").write_text(
        PROVENANCE_TEMPLATE.format(repo=REPO, sha=PINNED_SHA,
                                   dirs=dirs_block),
        encoding="utf-8",
    )
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("─" * 60)
    print(f"下載成功：{ok} 檔（其中 {malformed} 檔為故意畸形/負向案例）")
    print(f"下載失敗：{failed} 檔")
    print("分類分佈：")
    for category in sorted(cat_count):
        print(f"    {category:14s} {cat_count[category]}")
    print(f"輸出：{out_dir}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
