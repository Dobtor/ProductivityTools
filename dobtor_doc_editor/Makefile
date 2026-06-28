# dobtor_doc_editor — Sprint 0 Makefile
#
# 用法：在 dobtor_doc_editor/ 目錄下執行 make <target>
# 目標分組：
#   build / dev          — 前端打包與 Odoo 重啟
#   fixtures / scan      — fixture 回歸 + OOXML 元素統計
#   docker / odoo        — Odoo container 操作
#   clean / verify       — 清理與健檢

ODOO_CONTAINER ?= odoo18
ODOO_DB        ?= odoo18_dev
MODULE         ?= dobtor_doc_editor
FIXTURE_DIR    ?= tests/fixtures

# 預設執行 help
.DEFAULT_GOAL := help

.PHONY: help install build watch dev upgrade restart logs \
        scan-ooxml fixtures-golden fixtures-compare visual-regression \
        test-backend test-backend-font test-backend-zip \
        ci-frontend ci-python ci-xml ci-all \
        clean clean-build clean-deps verify

help: ## 列出所有 target
	@echo "dobtor_doc_editor — Sprint 0 開發指令"
	@echo ""
	@echo "前端打包："
	@grep -E '^(install|build|watch|dev|upgrade|restart|logs):.*?##' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Fixture 回歸："
	@grep -E '^(scan-ooxml|fixtures-.*|visual-regression):.*?##' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Odoo backend tests（Sprint 72/77）："
	@grep -E '^(test-backend.*):.*?##' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "CI 鏡像（與 GitHub Actions 同樣）："
	@grep -E '^(ci-.*):.*?##' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "清理與驗證："
	@grep -E '^(clean.*|verify):.*?##' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ── 前端打包 ─────────────────────────────────────────────────────────────────

install: ## 安裝 npm 依賴（含 patch-package 套用）
	npm install --no-audit --no-fund

build: ## rollup 打包 OOXML Parser → canvas-editor-custom.umd.js
	npm run build:frontend

watch: ## rollup --watch（修改 .ts 即時重打包）
	npm run build:watch

# ── Odoo container 操作 ──────────────────────────────────────────────────────

upgrade: ## odoo -u dobtor_doc_editor（更新 DB schema、views、ACL）
	docker exec $(ODOO_CONTAINER) odoo -c /etc/odoo/odoo.conf -d $(ODOO_DB) -u $(MODULE) --stop-after-init

restart: ## 重啟 Odoo container（載入 Python controller 變更）
	docker restart $(ODOO_CONTAINER)

logs: ## 跟看 Odoo container 日誌
	docker logs -f --tail 50 $(ODOO_CONTAINER)

dev: build upgrade restart ## 完整開發循環：build TS → upgrade module → restart container
	@echo "✓ dev cycle complete: bundle rebuilt, module upgraded, container restarted"

# ── Fixture 回歸與 OOXML 掃描 ────────────────────────────────────────────────

scan-ooxml: ## 掃 tests/fixtures/ 全部 DOCX 統計使用到的 OOXML 元素
	python3 tools/scan_ooxml_elements.py $(FIXTURE_DIR)

fixtures-golden: ## 用 LibreOffice + pdftoppm 為每份 DOCX 產 golden PNG（在 container 內跑）
	docker exec $(ODOO_CONTAINER) bash -c "cd /mnt/extra-addons/$(MODULE) && bash tests/scripts/generate_golden.sh"

fixtures-compare: ## 用 puppeteer + pixelmatch 比對 canvas-editor 渲染與 golden PNG
	@if [ -z "$(FIXTURE)" ]; then \
		node tests/scripts/compare_fixtures.cjs; \
	else \
		node tests/scripts/compare_fixtures.cjs --fixture $(FIXTURE); \
	fi

visual-regression: ## 跑視覺回歸 + threshold 判定（PR block 用）
	bash tests/scripts/run_visual_regression.sh

# ── Sprint 77：Odoo backend HttpCase / TransactionCase 一鍵觸發 ──────────
test-backend: ## 跑 Odoo backend tests（font_serve + zip_guard, Sprint 64b/66/68/69/71）
	docker exec $(ODOO_CONTAINER) bash /mnt/extra-addons/$(MODULE)/tests/scripts/run_backend_tests.sh

test-backend-font: ## 只跑 font_serve test（Sprint 64b/66/68/69）
	docker exec $(ODOO_CONTAINER) bash /mnt/extra-addons/$(MODULE)/tests/scripts/run_backend_tests.sh --tag=font_serve

test-backend-zip: ## 只跑 zip_guard test（Sprint 20 W9-10 + Sprint 71）
	docker exec $(ODOO_CONTAINER) bash /mnt/extra-addons/$(MODULE)/tests/scripts/run_backend_tests.sh --tag=zip_guard

# ── CI 鏡像（在本地跑與 GitHub Actions 同樣的檢查） ──────────────────────────

ci-frontend: ## CI 前端 job: typecheck + vitest + build
	npm run typecheck
	npm test
	npm run build:frontend
	@test -f static/src/lib/canvas_editor/canvas-editor-custom.umd.js \
		&& echo "✓ bundle ok" \
		|| (echo "✗ bundle missing" && exit 1)

ci-python: ## CI Python job: flake8 + manifest 驗證
	flake8 --max-line-length=120 --extend-ignore=E501,W503 \
	       --select=E9,F63,F7,F82 controllers models wizards
	python3 -c "import ast; ast.literal_eval(open('__manifest__.py').read())"

ci-xml: ## CI XML job: 全 XML well-formed
	@find . -name '*.xml' -not -path './node_modules/*' \
	  -exec xmllint --noout {} \;

ci-all: ci-frontend ci-python ci-xml ## 跑全部 CI job（不含 visual-regression）

# ── 清理 ──────────────────────────────────────────────────────────────────────

clean-build: ## 刪除 rollup 輸出與 .tsbuildinfo
	rm -f static/src/lib/canvas_editor/canvas-editor-custom.umd.js
	rm -f static/src/lib/canvas_editor/canvas-editor-custom.umd.js.map
	rm -rf dist *.tsbuildinfo

clean-deps: ## 刪除 node_modules 與 package-lock.json
	rm -rf node_modules package-lock.json

clean: clean-build clean-deps ## 全清（build artifact + node_modules）

# ── 健檢 ──────────────────────────────────────────────────────────────────────

verify: ## 確認 build 鏈通電（type check + rollup build）
	@echo "→ TypeScript type check"
	npx tsc --noEmit
	@echo "→ rollup build"
	npm run build:frontend
	@echo "→ bundle 產出檢查"
	@test -f static/src/lib/canvas_editor/canvas-editor-custom.umd.js && \
		echo "✓ bundle exists ($$(stat -c%s static/src/lib/canvas_editor/canvas-editor-custom.umd.js) bytes)" || \
		(echo "✗ bundle missing" && exit 1)
