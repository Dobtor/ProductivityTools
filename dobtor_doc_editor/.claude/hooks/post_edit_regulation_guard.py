#!/usr/bin/env python3
"""
Hook 2: PostToolUse on Edit/Write — 規畫書 §5 違規守門員

當 Edit/Write 動到規畫書（dobtor_doc_editor_高保真匯入開發規劃.md）時、
掃描 §5 Phase 規畫段、偵測以下違規寫法：

1. 行內含 `~~刪除線~~`（snappy-nova §Verification 明令禁止）
2. 行內含「Sprint NNN 完成」/「Sprint NNN 達成」敘述（要寫進 audit doc、不是規畫書）
3. [x] 行後加百分比 / 完成度 描述
4. [ ] 行被加 escape 字眼（stub / Phase D / future）

PostToolUse 不能阻擋（已執行完）、但會 stderr 警告 + 退 exit 2 讓 Claude 看到、
要求 Claude 自行 revert 該違規。

設定關閉：DOBTOR_HOOKS_DISABLED=1
"""
import json
import os
import re
import sys
from pathlib import Path

if os.environ.get("DOBTOR_HOOKS_DISABLED") == "1":
    sys.exit(0)

REGULATION_FILENAME = "dobtor_doc_editor_高保真匯入開發規劃.md"
PHASE_SECTION_HEADER = "## 5. Phase 規劃"
NEXT_SECTION_HEADER = "## 6. 測試與驗證體系"


def warn(message: str) -> None:
    print(f"⚠️  post_edit_regulation_guard：{message}", file=sys.stderr)


def block_warn() -> None:
    """退 exit 2、Claude 會看到 stderr 並可選擇 revert。"""
    sys.exit(2)


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    # 只在規畫書改動時觸發
    if REGULATION_FILENAME not in file_path:
        sys.exit(0)

    # 讀整份規畫書（最新版本、已含本次 edit）
    try:
        content = Path(file_path).read_text(encoding="utf-8")
    except Exception as exc:
        warn(f"無法讀檔 {file_path}: {exc}")
        sys.exit(0)

    # 抓出 §5 段（到 §6 為止）
    sec5_start = content.find(PHASE_SECTION_HEADER)
    sec6_start = content.find(NEXT_SECTION_HEADER)
    if sec5_start == -1:
        sys.exit(0)
    sec5 = content[sec5_start: sec6_start if sec6_start != -1 else len(content)]

    violations = []

    for lineno, line in enumerate(sec5.splitlines(), start=1):
        stripped = line.strip()

        # Rule 1: 刪除線
        if "~~" in line:
            # 雙波浪號表示刪除線
            if line.count("~~") >= 2:
                violations.append((lineno, "刪除線 (~~text~~)", line[:120]))

        # Rule 2: 「Sprint N 完成 / 達成」敘述
        if re.search(r"Sprint\s+\d+\s*(完成|達成)", line):
            violations.append(
                (lineno, "「Sprint N 完成/達成」敘述（要寫 audit doc、不寫規畫書）", line[:120])
            )

        # Rule 3: [x] 後接百分比
        if re.search(r"\[x\].*\b\d{1,3}\s*%", line):
            violations.append(
                (lineno, "[x] 後接百分比（規畫書不追蹤進度數字）", line[:120])
            )

        # Rule 4: [ ] 含禁用 escape 字眼
        if re.match(r"^\s*-\s*\[\s*[ ]\s*\]", line):
            if re.search(
                r"\b(stub|Phase\s*D|placeholder for next sprint)\b", line, re.IGNORECASE
            ):
                violations.append(
                    (lineno, "[ ] 工項含禁用 escape 字眼", line[:120])
                )

    if not violations:
        sys.exit(0)

    # 有違規 → 警告 Claude
    print(
        f"\n⚠️  post_edit_regulation_guard 偵測 §5 Phase 規畫段 {len(violations)} 個違規：\n",
        file=sys.stderr,
    )
    for lineno, rule, snippet in violations:
        print(f"  §5 內第 {lineno} 行 — {rule}", file=sys.stderr)
        print(f"    內容: {snippet}", file=sys.stderr)
    print(
        "\n紀律來源：snappy-nova plan §Verification「Checkbox 規則」+「反例（禁止再做）」\n"
        "處理：請 revert 違規行、把細節寫到對應 docs/sprintN_*.md audit doc",
        file=sys.stderr,
    )
    block_warn()


if __name__ == "__main__":
    main()
