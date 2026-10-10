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

.PHONY: help upgrade restart logs test-js \
        test-backend test-backend-zip \
        test-local test-local-tour test-local-all \
        ci-python ci-xml ci-all clean

help: ## 列出所有 target
	@echo "dobtor_doc_editor — 開發指令"
	@echo ""
	@echo "稽核與完工："
	@grep -E '^(audit):.*?##' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo "「完成了嗎」的單一判決："
	@grep -E '^(done):.*?##' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
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

test-local: ## 本機 rig 跑全部 backend 測試（則數不寫死——寫死的數字會漂移且沒人守）
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
	#    scope 含 migrations/：migration 腳本語法錯 ＝ 升級當場炸，而且
	#    production 只跑一次、沒有第二次機會。原本漏掉（2026-10-09 補）。
	@FLAKE="--max-line-length=120 --extend-ignore=E501,W503 --select=E9,F63,F7,F82 controllers models wizards tests migrations"; \
	if python3 -m flake8 --version >/dev/null 2>&1; then \
		python3 -m flake8 $$FLAKE; \
	elif docker ps --format '{{.Names}}' | grep -qx "$(ODOO_CONTAINER)"; then \
		docker exec $(ODOO_CONTAINER) sh -c "cd $(MODULE_MOUNT) && python3 -m flake8 $$FLAKE"; \
	else \
		echo "✗ 找不到 flake8（host 沒裝、容器 $(ODOO_CONTAINER) 沒在跑）"; exit 1; \
	fi
	@python3 -c "import ast; ast.literal_eval(open('__manifest__.py').read())" && echo "✓ manifest literal"

ci-xml: ## 全 XML well-formed（壞 XML ＝ 升級 ParseError ＝ 模組裝不起來）
	# ☠️ 原本寫 `find … -exec xmllint --noout {} \;`——**find 的退出碼不受
	#    -exec 的結果影響，恆為 0**。所以壞掉的 XML 會把 parser error 印到
	#    畫面上，然後 make 說過關。2026-10-09 實測：放一支壞 XML 進 views/，
	#    ci-xml 與 ci-all 都回 0。
	#    這是本模組反覆出現的那個失效模式的另一種形狀：檢查**執行了**，
	#    但它的**判決被丟棄**。
	#    改成 pipeline——xargs 的退出碼會傳出來（已實測：壞檔回 1、全好回 0、
	#    空輸入回 0 不會卡）。
	@find . -name '*.xml' -not -path './node_modules/*' -print0 \
	  | xargs -0 xmllint --noout
	# 過關也要出聲。原本全程靜默，正是「沒人發現它不會紅」的助力。
	@echo "✓ XML well-formed（$$(find . -name '*.xml' -not -path './node_modules/*' | wc -l | tr -d ' ') 檔）"

ci-all: ci-python ci-xml test-js ## 跑全部本機靜態檢查

audit: ## 跑稽核的「尺」（不是閘門——它只撈候選，判讀需要人；見 docs/AUDIT_LENSES.md）
	# ☠️ 這些腳本**刻意不用退出碼表示「有候選」**。當成 lint 自動擋會立刻
	#    變噪音，然後被人加例外清單繞過去。退出碼只在「工具自己壞了」時非 0。
	#
	#    路由覆蓋那一把要吃 tour 的日誌才準：先跑
	#        bash tests/scripts/run_local_rig.sh tour
	#    再跑 make audit——沒有日誌時它會**明說自己高估了覆蓋率**。
	@echo "══════ 尺 1：全檔案清查與分類 ══════"
	@python3 tests/scripts/audit_file_inventory.py
	@echo ""
	@echo "══════ 尺 2：路由覆蓋（tour 日誌在 /tmp/dobtor_doc_editor_tour.log 時會併入）══════"
	@TOUR_LOG=/tmp/dobtor_doc_editor_tour.log python3 tests/scripts/audit_route_coverage.py
	@echo ""
	@echo "══════ 尺 3：ACL／record rule 逐 model 對照 ══════"
	@python3 tests/scripts/audit_acl_rules.py
	@echo ""
	@echo "══════ 尺 4：docstring 裡的絕對語句 ══════"
	@python3 tests/scripts/scan_absolute_promises.py

done: ## 「完成了嗎」的單一判決（13 條判準，含匯入模組；見 docs/DONE_CRITERIA.md）
	# 腳本的退出碼 0 全過 / 1 有判準沒過 / **2 環境不具備或有判準被跳過**。
	# ☠️ 但 **make 會把任何失敗都變成自己的 2**（GNU make 的慣例），所以
	#    透過 make 讀 $$? 時 1 與 2 分不出來。要讀真正的判決碼請直接跑：
	#        bash tests/scripts/run_done_check.sh; echo $$?
	#    透過 make 時請讀**最後那一行文字**，它四種結局各有不同措辭。
	# 跳過某幾條：make done DONE_SKIP="tour core-standalone"
	@bash tests/scripts/run_done_check.sh

clean: ## 刪除 Python 編譯暫存
	find . -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
	find . -name '*.pyc' -delete 2>/dev/null || true
	@echo "✓ cleaned"
