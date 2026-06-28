#!/usr/bin/env python3
"""
Hook 3: Stop hook — sprint 結束品質守門員

當 Claude 嘗試結束（Stop）時、檢查若當前在 sprint-N-* 分支且有新 commit：

1. docs/sprintN_*.md audit doc 必須存在
2. audit doc 行數 >= 50（Sprint 160 v1 audit 只有 17 行、太薄）
3. audit doc 不含禁用 escape 字眼（stub / Phase D / future / placeholder for next sprint）
4. 最近一個 sprint commit 改動含 production code（不能只改 docs）

任何一項失敗 → return {"decision": "block", "reason": "..."} 不准 stop、
告訴 Claude 該補完什麼。

設定關閉：DOBTOR_HOOKS_DISABLED=1
"""
import glob
import json
import os
import re
import subprocess
import sys

if os.environ.get("DOBTOR_HOOKS_DISABLED") == "1":
    sys.exit(0)

AUDIT_MIN_LINES = 50
BANNED_PATTERN = re.compile(
    r"\b(stub|Phase\s*D|placeholder for next sprint)\b", re.IGNORECASE
)


def block(reason: str) -> None:
    print(json.dumps({"decision": "block", "reason": reason}))
    sys.exit(0)


def run(cmd: list[str]) -> str:
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=10
        ).stdout.strip()
    except Exception:
        return ""


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    # 如果 Stop hook 已經 block 過（避免無限迴圈）
    if data.get("stop_hook_active"):
        sys.exit(0)

    # 確認在 sprint 分支
    branch = run(["git", "branch", "--show-current"])
    m = re.match(r"sprint-(\d+)", branch)
    if not m:
        sys.exit(0)  # 不在 sprint 分支、放過

    sprint_num = m.group(1)

    # 確認該分支有新 sprint commit
    # 比對 main branch (18.0) 看有沒有 commit
    log = run(
        ["git", "log", "--oneline", f"18.0..{branch}", "--grep", f"Sprint-{sprint_num}"]
    )
    if not log.strip():
        # 沒新 sprint commit、可能只是讀檔不需要審查
        sys.exit(0)

    # ---- Check 1: audit doc 存在 ----
    audit_files = glob.glob(f"docs/sprint{sprint_num}_*.md")
    if not audit_files:
        block(
            f"Sprint {sprint_num} audit doc 不存在。"
            f"請在 docs/sprint{sprint_num}_<topic>.md 寫一份 audit doc："
            f"含 root cause / 修法 / 三層 SOP / 學習、至少 {AUDIT_MIN_LINES} 行。"
        )

    audit_file = audit_files[0]

    # ---- Check 2: 行數 ----
    try:
        with open(audit_file, encoding="utf-8") as f:
            content = f.read()
    except Exception as exc:
        block(f"audit doc {audit_file} 讀取失敗: {exc}")

    lines = content.splitlines()
    if len(lines) < AUDIT_MIN_LINES:
        block(
            f"Audit doc {audit_file} 只有 {len(lines)} 行、低於 {AUDIT_MIN_LINES} 行門檻。"
            f"請補完內容：root cause（為什麼這個工項要做）/ 修法（具體改了什麼）/"
            f"三層 SOP（vitest + VR + spot check 結果）/ 學習。"
            f"Sprint 157 audit ~270 行、Sprint 158 ~380 行可參考。"
        )

    # ---- Check 3: 禁用字眼 ----
    banned_matches = BANNED_PATTERN.findall(content)
    if banned_matches:
        unique_banned = sorted(set(banned_matches))
        block(
            f"Audit doc {audit_file} 含禁用 escape 字眼: {unique_banned}\n"
            f"Sprint 160 v1 stub 事件後 anti_pattern。請改寫成具體技術描述、不要用這些字眼搪塞。"
        )

    # ---- Check 4: 最近 commit 含 production code ----
    # 取 sprint commit diff 看 file 範圍
    diff = run(["git", "diff", f"18.0..{branch}", "--name-only"])
    files = [f for f in diff.splitlines() if f.strip()]
    if files:
        # 排除純 docs / config 改動
        non_docs = [
            f
            for f in files
            if not (
                f.startswith("docs/")
                or f.endswith(".md")
                or f.startswith(".antigravity/")
                or f.startswith(".claude/")
                or f.endswith(".json")
                or f.endswith(".log")
            )
        ]
        if not non_docs:
            block(
                f"Sprint {sprint_num} 只改了 docs/config（{len(files)} 個檔）、沒 production code 改動。"
                f"Phase 1 wire-up sprint 必須有真實 production code 變更（render/mapper/parser 等）。"
                f"如果這是 docs-only sprint（如 Sprint 156 checkbox audit）、請手動 export "
                f"DOBTOR_HOOKS_DISABLED=1 跳過此檢查。"
            )

    # 全部通過、允許 stop
    sys.exit(0)


if __name__ == "__main__":
    main()
