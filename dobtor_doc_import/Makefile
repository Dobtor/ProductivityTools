# dobtor_doc_import — Makefile
#
# 用法：在 dobtor_doc_import/ 目錄下執行 make <target>
#
# 這個模組持有整條 TS 工具鏈（rollup / tsconfig / vitest / package.json），
# 核心 dobtor_doc_editor 拆分後**完全沒有** TS。所以：
#   - 任何 .ts 的建置與測試都在這裡
#   - 核心的 make 只剩 Odoo 操作與 Python 靜態檢查
#
# 容器與連線預設與 ../dobtor_doc_editor/tests/scripts/run_local_rig.sh 一致，
# 可用環境變數覆寫。MODULE_MOUNT 已含模組名。

ODOO_CONTAINER ?= qcodoo
ODOO_DB        ?= docedit
MODULE         ?= dobtor_doc_import
MODULE_MOUNT   ?= /mnt/pt/$(MODULE)
PG_HOST        ?= qcpg
ADDONS_PATH    ?= /usr/lib/python3/dist-packages/odoo/addons,/mnt/pt
FIXTURE_DIR    ?= tests/fixtures

.DEFAULT_GOAL := help

.PHONY: help install build build-all watch dev upgrade restart logs \
        scan-ooxml fixtures-golden fixtures-compare visual-regression \
        test test-odoo ci-frontend ci-python ci-all \
        clean clean-build clean-deps verify

help: ## 列出所有 target
	@echo "dobtor_doc_import — 開發指令"
	@echo ""
	@echo "前端打包（三個產物）："
	@grep -E '^(install|build|build-all|watch|verify):.*?##' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "測試："
	@grep -E '^(test|test-odoo):.*?##' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Fixture 回歸與視覺回歸："
	@grep -E '^(scan-ooxml|fixtures-.*|visual-regression):.*?##' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "靜態檢查與清理："
	@grep -E '^(ci-.*|clean.*):.*?##' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ── 測試 ─────────────────────────────────────────────────────────────────────

test: ## vitest（3059 則，TS 管線的主要驗證）
	npm test

test-odoo: ## 本模組的 Odoo 測試（路由／精靈／字型／bundle 載入）
	docker exec $(ODOO_CONTAINER) odoo -d $(ODOO_DB) \
		--db_host=$(PG_HOST) --db_user=odoo --db_password=odoo \
		--addons-path=$(ADDONS_PATH) -u $(MODULE) \
		--test-enable --test-tags '/$(MODULE)' \
		--workers=0 --max-cron-threads=0 --http-port=8069 --stop-after-init

# ── Odoo container 操作 ──────────────────────────────────────────────────────

upgrade: ## odoo -u dobtor_doc_import
	docker exec $(ODOO_CONTAINER) odoo -d $(ODOO_DB) --db_host=$(PG_HOST) \
		--db_user=odoo --db_password=odoo --addons-path=$(ADDONS_PATH) \
		-u $(MODULE) --stop-after-init

restart: ## 重啟 Odoo container
	docker restart $(ODOO_CONTAINER)

logs: ## 跟看 Odoo container 日誌
	docker logs -f --tail 50 $(ODOO_CONTAINER)

# ── 靜態檢查 ─────────────────────────────────────────────────────────────────

ci-python: ## flake8（擋載不進去的那幾類）+ manifest 是合法 literal
	@FLAKE="--max-line-length=120 --extend-ignore=E501,W503 --select=E9,F63,F7,F82 controllers models wizards tests"; \
	if python3 -m flake8 --version >/dev/null 2>&1; then \
		python3 -m flake8 $$FLAKE; \
	elif docker ps --format '{{.Names}}' | grep -qx "$(ODOO_CONTAINER)"; then \
		docker exec $(ODOO_CONTAINER) sh -c "cd $(MODULE_MOUNT) && python3 -m flake8 $$FLAKE"; \
	else \
		echo "✗ 找不到 flake8"; exit 1; \
	fi
	@python3 -c "import ast; ast.literal_eval(open('__manifest__.py').read())" && echo "✓ manifest literal"

ci-all: ci-frontend ci-python ## 跑全部靜態檢查（不含 visual-regression）


# ── 清理 ──────────────────────────────────────────────────────────────────────

# ── 前端打包 ─────────────────────────────────────────────────────────────────

install: ## 安裝 npm 依賴（含 patch-package 套用）
	npm install --no-audit --no-fund

build: ## rollup 打包 OOXML Parser → canvas-editor-custom.umd.js
	npm run build:frontend

build-all: ## 打包三個產物：瀏覽器 bundle + node CLI + VR pipeline
	# ☠️ 2026-10-09：VR pipeline 的 bundle 原本**沒有任何 script 會建它**
	#    （rollup.visual_regression.config.js 存在但沒人叫），所以
	#    visual_regression_v14.mjs 一跑就 exit 2。已補 npm run build:vr。
	npm run build:all

watch: ## rollup --watch（修改 .ts 即時重打包）
	npm run build:watch

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

ci-frontend: ## CI 前端 job: typecheck + vitest + build
	npm run typecheck
	npm test
	npm run build:frontend
	@test -f static/src/lib/canvas_editor/canvas-editor-custom.umd.js \
		&& echo "✓ bundle ok" \
		|| (echo "✗ bundle missing" && exit 1)

clean-build: ## 刪除 rollup 輸出與 .tsbuildinfo
	rm -f static/src/lib/canvas_editor/canvas-editor-custom.umd.js
	rm -f static/src/lib/canvas_editor/canvas-editor-custom.umd.js.map
	rm -rf dist *.tsbuildinfo

clean-deps: ## 刪除 node_modules 與 package-lock.json
	rm -rf node_modules package-lock.json

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
