# 轉換函式與共用守衛要先載（路由檔案 import 它們）
from . import doc_convert
from . import doc_controller_base
from . import doc_controller            # 文件（17 條）
from . import doc_controller_template   # 範本設計（10 條）
from . import doc_controller_i18n       # 多語（5 條）
from . import doc_controller_devtools   # 遙測與測試夾具（4 條）
from . import portal
from . import report_download  # 下載檔名（filename_pattern）
