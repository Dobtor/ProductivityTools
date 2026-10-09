from . import test_zip_guard
from . import test_versions
from . import test_doc_linked_mixin
from . import test_security
from . import test_jinja_sandbox
from . import test_controllers
from . import test_optimistic_lock
from . import test_telemetry
from . import test_template_autofill
from . import test_template_field  # Phase 8 ADR-022 — doc.template.signer/field
from . import test_template_edit  # Phase 1（藥丸改版）— 範本可直接編輯
# 藥丸管線：按被測的那一層分（對齊 models/render/ 六層）
from . import test_pill_snapshot
from . import test_pill_sandbox
from . import test_pill_fields
from . import test_pill_i18n
from . import test_pill_output
from . import test_report_engine  # 報表引擎 R1-R3
from . import test_qweb_converter  # QWeb 報表 → 範本轉換器
from . import test_qweb_converter_native  # 原生報表實際轉換＋渲染
from . import test_editor_tour
from . import test_manifest_assets
from . import test_static_checks_wiring  # Makefile 靜態檢查的接線守門員
from . import test_cron_wiring  # ir.cron 的 code 字串接線守門員
from . import test_session_probe_self  # 探針自己的測試（共用基礎設施）
from . import test_done_criteria  # 完工判準不准漂移
from . import test_acl_company_isolation  # 多公司隔離逐 model 量測
from . import test_input_bounds  # 輸入大小上限（稽核尺 2）
from . import test_route_smoke  # 全路由煙霧測試（稽核尺 3）
