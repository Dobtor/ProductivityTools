# dobtor_doc_editor — Makefile（`make help` 是權威，CONTRIBUTING 指向這裡）
#
# 用法：在 dobtor_doc_editor/ 目錄下執行 make <target>
#
# ☠️ 2026-10-09：預設值原本還是 2026-05 的開發環境（odoo18 / odoo18_dev /
#    /mnt/extra-addons），在現在的 rig 上全部打不中——`make upgrade` / `restart`
#    / `logs` / `test-backend` 都會對著不存在的容器執行。改成與
#    tests/scripts/run_local_rig.sh 同一組預設，仍可用環境變數覆寫：
#
#      ODOO_CONTAINER=odoo18 ODOO_DB=odoo18_dev MODULE_MOUNT=/mnt/extra-addons/dobtor_doc_editor make upgrade
#
#    MODULE_MOUNT **已含模組名**（與 rig 腳本一致），不要再接 $(MODULE)。

ODOO_CONTAINER ?= qcodoo
ODOO_DB        ?= docedit
MODULE         ?= dobtor_doc_editor
MODULE_MOUNT   ?= /mnt/pt/$(MODULE)
PG_HOST        ?= qcpg
ADDONS_PATH    ?= /usr/lib/python3/dist-packages/odoo/addons,/mnt/pt
# run_backend_tests.sh 預設讀 odoo.conf，但這個 rig 的 Postgres 在另一個容器
# ——不傳這組就會去找容器內的 unix socket 然後 OperationalError。
ODOO_ARGS      ?= --db_host=$(PG_HOST) --db_user=odoo --db_password=odoo --addons-path=$(ADDONS_PATH)

# 預設執行 help
.DEFAULT_GOAL := help

.PHONY: help install build watch dev upgrade restart logs test-js \
        scan-ooxml fixtures-golden fixtures-compare visual-regression \
        test-backend test-backend-zip \
        test-local test-local-tour test-local-all \
        ci-frontend ci-python ci-xml ci-all \
        clean clean-build clean-deps verify

help: ## 列出所有 target
	@echo "dobtor_doc_editor — 開發指令"
	@echo ""
	@echo "Odoo container 操作："
	@grep -E '^(upgrade|restart|logs):.*?##' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Odoo backend tests（容器內、挑 tag）："
	@grep -E '^(test-backend.*):.*?##' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "本機兩容器 rig（host 端、跑全部測試）："
	@grep -E '^(test-local.*):.*?##' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "本機靜態檢查（沒有 CI，這幾支就是唯一的關卡）："
	@grep -E '^(ci-.*):.*?##' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "清理："
	@grep -E '^(clean):.*?##' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ── Odoo container 操作 ──────────────────────────────────────────────────────

upgrade: ## odoo -u dobtor_doc_editor（更新 DB schema、views、ACL）
	docker exec $(ODOO_CONTAINER) odoo -c /etc/odoo/odoo.conf -d $(ODOO_DB) -u $(MODULE) --stop-after-init

restart: ## 重啟 Odoo container（載入 Python controller 變更）
	docker restart $(ODOO_CONTAINER)

logs: ## 跟看 Odoo container 日誌
	docker logs -f --tail 50 $(ODOO_CONTAINER)

# ── Sprint 77：Odoo backend HttpCase / TransactionCase 一鍵觸發 ──────────
test-backend: ## 跑 Odoo backend tests（容器內，挑 tag；TAG=<名稱> 可指定）
	docker exec -e ODOO_DB=$(ODOO_DB) -e ODOO_ARGS="$(ODOO_ARGS)" $(ODOO_CONTAINER) \
		bash $(MODULE_MOUNT)/tests/scripts/run_backend_tests.sh $(if $(TAG),--tag=$(TAG),)

test-backend-zip: ## 只跑 zip_guard tag
	$(MAKE) test-backend TAG=zip_guard

# ── 本機兩容器 rig：跑模組的全部測試 ──────────────────────────────────
# 上面三個 test-backend 是在容器內跑、只挑 tag；下面這三個在 host 跑，
# docker exec 進去跑 /dobtor_doc_editor 的全部測試。容器名與連線參數
# 用環境變數覆寫，見 tests/scripts/run_local_rig.sh 的檔頭。

test-local: ## 本機 rig 跑全部 backend 測試（590 則）
	bash tests/scripts/run_local_rig.sh test

test-local-tour: ## 本機 rig 跑瀏覽器 tour（另一個容器，前端唯一的驗證）
	bash tests/scripts/run_local_rig.sh tour

test-local-all: ## 本機 rig 跑 backend + tour（後端綠了才跑 tour）
	bash tests/scripts/run_local_rig.sh all

test-js: ## 純函式 JS 單測（node，不需要 Odoo 或瀏覽器，約 1 秒）
	@set -e; for f in tests/js/*.mjs; do echo "── $$f"; node "$$f"; done

# ── 本機靜態檢查（沒有 CI，這幾支就是唯一的關卡）─────────────────────────────

ci-python: ## 靜態檢查：flake8（擋載不進去的那幾類）+ manifest 是合法 literal
	# ☠️ host 不一定裝得有 flake8（實測這台就沒有），所以**優先用容器裡的**
	#    ——那也是測試真正跑的環境。host 有就用 host，兩邊都沒有才報錯。
	#    scope 含 tests/：那批測試漏 import 或打錯名稱一樣會讓整批不執行。
	@FLAKE="--max-line-length=120 --extend-ignore=E501,W503 --select=E9,F63,F7,F82 controllers models wizards tests"; \
	if python3 -m flake8 --version >/dev/null 2>&1; then \
		python3 -m flake8 $$FLAKE; \
	elif docker ps --format '{{.Names}}' | grep -qx "$(ODOO_CONTAINER)"; then \
		docker exec $(ODOO_CONTAINER) sh -c "cd $(MODULE_MOUNT) && python3 -m flake8 $$FLAKE"; \
	else \
		echo "✗ 找不到 flake8（host 沒裝、容器 $(ODOO_CONTAINER) 沒在跑）"; exit 1; \
	fi
	@python3 -c "import ast; ast.literal_eval(open('__manifest__.py').read())" && echo "✓ manifest literal"

ci-xml: ## CI XML job: 全 XML well-formed
	@find . -name '*.xml' -not -path './node_modules/*' \
	  -exec xmllint --noout {} \;

ci-all: ci-frontend ci-python ci-xml test-js ## 跑全部本機靜態檢查（不含 visual-regression）

# ── 清理 ──────────────────────────────────────────────────────────────────────

# ── 前端打包 ─────────────────────────────────────────────────────────────────

install: ## 安裝 npm 依賴（含 patch-package 套用）
	npm install --no-audit --no-fund

build: ## rollup 打包 OOXML Parser → canvas-editor-custom.umd.js
	npm run build:frontend

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
