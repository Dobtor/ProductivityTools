"""doc.qweb.converter 的分層實作。

五個純 Python mixin，由 models/doc_qweb_converter.py 組合成一個
AbstractModel。拆開的理由與 models/render/ 相同（見 ADR-026）：
每一層的不變量要寫在自己的檔頭。
"""
from . import entry
from . import locate
from . import expr
from . import structure
from . import blocks
