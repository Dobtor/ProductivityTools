#!/usr/bin/env bash
# generate_golden.sh — 對所有 fixture DOCX 生成 golden PNG（每頁一張）
#
# 執行環境：Docker 容器（需有 soffice + pdftoppm + Noto CJK 字型）
# 執行方式：
#   docker exec system-odoo bash /odoo/addons/dobtor_doc_editor/tests/scripts/generate_golden.sh
#   docker exec system-odoo bash /odoo/addons/dobtor_doc_editor/tests/scripts/generate_golden.sh --force
#
# 轉換流程（兩段式）：
#   DOCX → PDF（LibreOffice，保留所有頁面）→ PNG（pdftoppm，每頁一張）
#
# 為何兩段式：LibreOffice --convert-to png 只輸出第一頁，無法測試跨頁表格。
#
# 輸出：tests/fixtures/<category>/golden/<name>-<page>.png
#       頁碼從 1 開始（pdftoppm 預設）

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FIXTURES_DIR="$(cd "$SCRIPT_DIR/../fixtures" && pwd)"

# 暫存目錄與 LibreOffice profile 在頂層建立一次，EXIT 時統一清理
# $$ 為本次腳本 PID，確保不同腳本執行間隔離，不影響同機其他 soffice 實例
SOFFICE_PROFILE="/tmp/soffice_profile_$$"
TMP_PDF_DIR="$(mktemp -d)"
trap 'rm -rf "$SOFFICE_PROFILE" "$TMP_PDF_DIR"' EXIT

# ── 前置檢查 ──────────────────────────────────────────────────────────────────

if ! command -v soffice &>/dev/null; then
  echo "ERROR: soffice not found."
  echo "  Run: docker exec -u root system-odoo apt-get install -y libreoffice-headless"
  exit 1
fi

if ! command -v pdftoppm &>/dev/null; then
  echo "ERROR: pdftoppm not found."
  echo "  Run: docker exec -u root system-odoo apt-get install -y poppler-utils"
  exit 1
fi

echo "=== generate_golden.sh ==="
echo "Fixtures : $FIXTURES_DIR"
echo "soffice  : $(which soffice)"
echo "pdftoppm : $(which pdftoppm)"
echo ""

FORCE="${1:-}"
total=0
skipped=0

while IFS= read -r -d '' docx; do
  dir="$(dirname "$docx")"
  name="$(basename "${docx%.docx}")"
  golden_dir="$dir/golden"

  # ── Skip 判斷 ──────────────────────────────────────────────────────────────
  if [[ "$FORCE" != "--force" ]] && ls "$golden_dir/${name}"-*.png &>/dev/null; then
    echo "  SKIP  $(basename "$docx")  (use --force to regenerate)"
    ((skipped++)) || true
    continue
  fi

  mkdir -p "$golden_dir"

  # --force 時先清除舊 PNG，避免頁數減少後殘留過時檔案干擾比對
  if [[ "$FORCE" == "--force" ]]; then
    rm -f "$golden_dir/${name}"-*.png
  fi

  echo "  GEN   $(basename "$docx")"

  # ── 第一段：DOCX → PDF ─────────────────────────────────────────────────────
  # LibreOffice headless 無法載入含中文/特殊字元的路徑（source file could not be loaded）
  # 解法：先複製到 TMP_PDF_DIR 並使用純 ASCII 臨時檔名，轉換完再刪除
  tmp_docx="$TMP_PDF_DIR/input_$$.docx"
  cp "$docx" "$tmp_docx"

  # -env:UserInstallation 使用獨立暫存 profile，防止 LibreOffice profile lock 卡死
  soffice \
    "-env:UserInstallation=file://$SOFFICE_PROFILE" \
    --headless \
    --convert-to pdf \
    --outdir "$TMP_PDF_DIR" \
    "$tmp_docx" 2>/dev/null

  rm -f "$tmp_docx"

  pdf_path="$TMP_PDF_DIR/input_$$.pdf"
  if [[ ! -f "$pdf_path" ]]; then
    echo "  ERROR: PDF not generated for $(basename "$docx"), skipping."
    continue
  fi

  # ── 第二段：PDF → PNG（每頁一張，150 DPI）─────────────────────────────────
  # 輸出：golden/<name>-1.png, golden/<name>-2.png ...
  pdftoppm -r 150 -png "$pdf_path" "$golden_dir/$name"

  # 清除本次暫存 PDF
  rm -f "$pdf_path"

  page_count=$(ls "$golden_dir/${name}"-*.png 2>/dev/null | wc -l)
  echo "        → $page_count page(s) → $golden_dir/"

  ((total++)) || true

done < <(find "$FIXTURES_DIR" -name "*.docx" -print0 | sort -z)

echo ""
echo "Done. Generated: $total  Skipped: $skipped"
echo ""
echo "Golden PNG summary:"
find "$FIXTURES_DIR" -name "*.png" -path "*/golden/*" | sort | while read -r png; do
  rel="${png#$FIXTURES_DIR/}"
  size=$(du -h "$png" 2>/dev/null | cut -f1)
  printf "  %-65s %s\n" "$rel" "$size"
done
