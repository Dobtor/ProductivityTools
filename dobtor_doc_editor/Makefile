# dobtor_doc_editor — Sprint 0 Makefile
#
# 用法：在 dobtor_doc_editor/ 目錄下執行 make <target>
# 目標分組：
#   build / dev          — 前端打包與 Odoo 重啟
#   docker / odoo        — Odoo container 操作
#   clean / verify       — 清理與健檢

ODOO_CONTAINER ?= odoo18
ODOO_DB        ?= odoo18_dev
MODULE         ?= dobtor_doc_editor

# 預設執行 help
.DEFAULT_GOAL := help

.PHONY: help upgrade restart logs test-js \
        test-backend test-backend-zip \
        test-local test-local-tour test-local-all \
        ci-python ci-xml ci-all \
        clean verify

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
test-backend: ## 跑 Odoo backend tests（容器內，挑 tag）
	docker exec $(ODOO_CONTAINER) bash /mnt/extra-addons/$(MODULE)/tests/scripts/run_backend_tests.sh

test-backend-zip: ## 只跑 zip_guard test（Sprint 20 W9-10 + Sprint 71）
	docker exec $(ODOO_CONTAINER) bash /mnt/extra-addons/$(MODULE)/tests/scripts/run_backend_tests.sh --tag=zip_guard

# ── 本機兩容器 rig：跑模組的全部測試 ──────────────────────────────────
# 上面三個 test-backend 是在容器內跑、只挑 tag；下面這三個在 host 跑，
# docker exec 進去跑 /dobtor_doc_editor 的全部測試。容器名與連線參數
# 用環境變數覆寫，見 tests/scripts/run_local_rig.sh 的檔頭。

test-local: ## 本機 rig 跑全部 backend 測試（約 480 則）
	bash tests/scripts/run_local_rig.sh test

test-local-tour: ## 本機 rig 跑瀏覽器 tour（另一個容器，前端唯一的驗證）
	bash tests/scripts/run_local_rig.sh tour

test-local-all: ## 本機 rig 跑 backend + tour（後端綠了才跑 tour）
	bash tests/scripts/run_local_rig.sh all

test-js: ## 純函式 JS 單測（node，不需要 Odoo 或瀏覽器，約 1 秒）
	@set -e; for f in tests/js/*.mjs; do echo "── $$f"; node "$$f"; done

# ── 本機靜態檢查（沒有 CI，這幾支就是唯一的關卡）─────────────────────────────

ci-python: ## CI Python job: flake8 + manifest 驗證
	flake8 --max-line-length=120 --extend-ignore=E501,W503 \
	       --select=E9,F63,F7,F82 controllers models wizards
	python3 -c "import ast; ast.literal_eval(open('__manifest__.py').read())"

ci-xml: ## CI XML job: 全 XML well-formed
	@find . -name '*.xml' -not -path './node_modules/*' \
	  -exec xmllint --noout {} \;

ci-all: ci-python ci-xml test-js ## 跑全部本機靜態檢查

# ── 清理 ──────────────────────────────────────────────────────────────────────
clean: ## 刪除 Python 編譯暫存
	find . -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
	find . -name '*.pyc' -delete 2>/dev/null || true
	@echo "✓ cleaned"
