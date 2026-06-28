#!/usr/bin/env python3
"""
Hook 1: PreToolUse on Bash — 命令層紀律守門員

阻擋以下命令：
1. git push（per ENGINEER-RULES §9：autopilot 不 push 遠端）
2. docker exec ... -u construction_*（不該升級 production Odoo 模組）
3. git commit -m 訊息含「stub / Phase D / future / placeholder for next sprint」
   （Sprint 160 v1 stub 事件後的 anti_pattern）
4. rm -rf .claude / .antigravity / .git（防誤刪）

Exit codes:
  0 = 允許
  2 = 阻擋（stderr 給 Claude 看）

設定關閉：環境變數 DOBTOR_HOOKS_DISABLED=1
"""
import json
import os
import re
import shlex
import sys

# 一鍵停用（debug 用）
if os.environ.get("DOBTOR_HOOKS_DISABLED") == "1":
    sys.exit(0)


def block(message: str) -> None:
    print(f"❌ pre_bash_guard 阻擋：{message}", file=sys.stderr)
    print("（要繞過：在 user shell 設 DOBTOR_HOOKS_DISABLED=1）", file=sys.stderr)
    sys.exit(2)


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        # 解析失敗就放過、不卡 Claude
        sys.exit(0)

    cmd = data.get("tool_input", {}).get("command", "")
    if not cmd:
        sys.exit(0)

    # ---- Rule 1: 阻擋 git push ----
    if re.search(r"\bgit\s+push\b", cmd):
        block(
            "git push (ENGINEER-RULES §9: autopilot 只本地 commit、push 由 user 手動)"
        )

    # ---- Rule 2: 阻擋 production Odoo 模組升級 ----
    if re.search(r"docker\s+exec\s+.*-u\s+construction_", cmd):
        block(
            "docker exec -u construction_*（升級 production Odoo 模組屬 user 手動範圍）"
        )

    # ---- Rule 3: commit message 禁用字眼 ----
    if "git commit" in cmd and "-m" in cmd:
        msg = _extract_commit_msg(cmd)
        if msg:
            banned = re.findall(
                r"\b(stub|Phase\s*D|placeholder for next sprint)\b",
                msg,
                re.IGNORECASE,
            )
            if banned:
                block(
                    f"commit message 含禁用字眼 {banned}\n"
                    f"  訊息：{msg[:120]}\n"
                    f"  Sprint 160 v1 stub 事件後的 anti_pattern（見 state.json）"
                )

    # ---- Rule 4: 防誤刪 critical paths ----
    if re.search(r"\brm\s+-[rf]+\b", cmd):
        if re.search(r"(\.claude|\.antigravity|\.git)(\s|/|$)", cmd):
            block(
                "rm -rf 對 .claude/.antigravity/.git 目錄（critical infra、不准刪）"
            )

    sys.exit(0)


def _extract_commit_msg(cmd: str) -> str:
    """從 `git commit -m '...'` 抽出訊息。支援 single/double quote 與 heredoc。"""
    # 嘗試 shlex 解析（handles quoted strings）
    try:
        tokens = shlex.split(cmd, posix=True)
        for i, tok in enumerate(tokens):
            if tok == "-m" and i + 1 < len(tokens):
                return tokens[i + 1]
    except ValueError:
        # heredoc / 複雜 quoting 可能失敗；回退用 regex
        pass

    # 回退：抓 -m 後第一個 quoted 字串
    m = re.search(r"-m\s+['\"]([^'\"]+)['\"]", cmd)
    if m:
        return m.group(1)

    # heredoc 模式：抓 EOF 之間的內容（會抓到整段、夠用於 keyword 搜尋）
    m = re.search(r"-m\s+\"\$\(cat\s+<<['\"]?(\w+)['\"]?\s*\n(.*?)\n\1\)\"", cmd, re.DOTALL)
    if m:
        return m.group(2)

    return ""


if __name__ == "__main__":
    main()
