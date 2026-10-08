"""doc.render.mixin 的分層實作。

六個純 Python mixin，由 models/doc_render_mixin.py 組合成一個
AbstractModel。拆開的理由是「每一層的不變量要寫在自己的檔頭」，
不是檔案太大：pass 鏈的順序、兩條求值路徑的差別、走訪的前提，
散在三千行裡沒有人會讀到。
"""
from . import tree
from . import sandbox
from . import fields
from . import i18n
from . import snapshot
from . import output
