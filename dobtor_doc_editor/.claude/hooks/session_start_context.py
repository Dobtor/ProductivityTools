#!/usr/bin/env python3
"""
Hook 4: SessionStart — 自動注入 sprint 上下文

每次新 Claude 工作階段開始時、把以下資訊塞進 Claude 的 system context：

- 當前 sprint 編號 / phase / status
- 鎖定決策 1B / 2B / 3B 摘要
- 當前 sprint task spec（id / scope / DoD / anti_patterns）
- 規畫書 §5 Phase 1 還剩幾項真實 wire-up（非 optional）
- 紀律 #18 提醒

效果：你不必每次新 session 都貼啟動咒語、Claude 自動知道在哪個 sprint。

設定關閉：DOBTOR_HOOKS_DISABLED=1
"""
import json
import os
import re
import sys
from pathlib import Path

if os.environ.get("DOBTOR_HOOKS_DISABLED") == "1":
    sys.exit(0)

STATE_PATH = Path(".antigravity/autopilot/state.json")
REGULATION_PATH = Path("dobtor_doc_editor_高保真匯入開發規劃.md")
RULES_PATH = Path(".antigravity/ENGINEER-RULES.md")


def main() -> None:
    # SessionStart 的 stdout = 加進 Claude system context
    lines: list[str] = []

    # ---- 標題 ----
    lines.append("# dobtor_doc_editor Auto-Injected Context")
    lines.append("")
    lines.append("此區塊由 `.claude/hooks/session_start_context.py` 自動產生。")
    lines.append(
        "你在 dobtor_doc_editor 工作、必須遵守 ENGINEER-RULES.md + snappy-nova plan。"
    )
    lines.append("")

    # ---- state.json 摘要 ----
    if STATE_PATH.exists():
        try:
            state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            state = {}

        lines.append("## 當前 Sprint 狀態")
        lines.append("")
        lines.append(f"- **current_sprint**: {state.get('current_sprint', '?')}")
        lines.append(f"- **current_phase**: {state.get('current_phase', '?')}")
        lines.append(f"- **status**: {state.get('status', '?')}")
        lines.append(
            f"- **last_sprint_completed**: {state.get('last_sprint_completed', '?')}"
        )
        if state.get("last_result"):
            lines.append(f"- **last_result**: {state['last_result'][:200]}")
        lines.append("")

        # ---- 鎖定決策 ----
        lock = state.get("lock_decisions", {})
        if lock:
            lines.append("## 鎖定決策（不可違反、user 已批准）")
            lines.append("")
            for k, v in lock.items():
                lines.append(f"- 決策 {k}: {v}")
            lines.append("")

        # ---- 當前 sprint task spec ----
        items = state.get("phase_1_wire_up_batch", {}).get("items", [])
        current = state.get("current_sprint")
        current_item = next((it for it in items if it.get("sprint") == current), None)
        if current_item:
            lines.append(f"## Sprint {current} Task Spec")
            lines.append("")
            lines.append(f"- **id**: {current_item.get('id', '?')}")
            lines.append(f"- **scope**: {current_item.get('scope', '?')}")
            lines.append(
                f"- **regulation_line**: §5 第 {current_item.get('regulation_line', '?')} 行"
            )
            wireup = current_item.get("true_wireup_definition")
            if wireup:
                lines.append(f"- **真實 wire-up 定義**: {wireup}")
            dod = current_item.get("DoD_required", [])
            if dod:
                lines.append("- **DoD（必達）**:")
                for d in dod:
                    lines.append(f"  - {d}")
            anti = current_item.get("anti_patterns", [])
            if anti:
                lines.append("- **Anti-patterns（嚴禁）**:")
                for a in anti:
                    lines.append(f"  - {a}")
            lines.append("")

    # ---- 規畫書 §5 Phase 1 剩餘真實 wire-up ----
    if REGULATION_PATH.exists():
        try:
            content = REGULATION_PATH.read_text(encoding="utf-8")
            # 抓 §5 Phase 1 段
            m = re.search(
                r"### Phase 1[\s\S]*?(?=### Phase 2|\Z)", content
            )
            if m:
                phase1 = m.group(0)
                # 真實 wire-up = `[ ]` 且**不**含「Phase 1 optional」
                todos = []
                for line in phase1.splitlines():
                    stripped = line.strip()
                    if (
                        stripped.startswith("- [ ]") or stripped.startswith("  - [ ]")
                    ) and "Phase 1 optional" not in line:
                        # 抓核心描述（去掉長括號）
                        todos.append(line.strip())
                if todos:
                    lines.append("## Phase 1 真實 wire-up 缺口（非 optional）")
                    lines.append("")
                    for t in todos:
                        lines.append(f"- {t[:150]}")
                    lines.append("")
                    lines.append(
                        f"→ Phase 1 Exit Criteria 要求這 {len(todos)} 項全 `[x]` "
                        f"才能過 Exit。"
                    )
                    lines.append("")
        except Exception:
            pass

    # ---- 紀律 reminder ----
    lines.append("## 紀律快速提醒（完整見 CONTRIBUTING.md §5）")
    lines.append("")
    lines.append("- **紀律 #18**: 不擴張 scope、規畫書沒寫的就不做")
    lines.append("- 規畫書 §5 `[ ]` 只能變 `[x]`、**不加任何敘述/Sprint 註記/百分比/刪除線**")
    lines.append("- 不 `git push`（user 手動）、不 `docker exec -u construction_*`（production）")
    lines.append("- commit message + audit doc 禁用 `stub` / `Phase D` / `placeholder for next sprint`")
    lines.append("- 寫 code 必須有真實下游 consumer（不能只是 `const x = doc.foo` 然後不用）")
    lines.append("")

    # ---- Hooks 提醒 ----
    lines.append("## 本專案 hook 守門員")
    lines.append("")
    lines.append("- `pre_bash_guard`: 阻擋 git push / production 升級 / stub commit message")
    lines.append("- `post_edit_regulation_guard`: 偵測規畫書 §5 違規寫法")
    lines.append("- `stop_audit_check`: sprint 結束須 audit doc ≥ 50 行 / 無禁用字眼 / 有 production code")
    lines.append("- 違規會被擋下、請依 hook stderr 訊息修正")

    print("\n".join(lines))


if __name__ == "__main__":
    main()
