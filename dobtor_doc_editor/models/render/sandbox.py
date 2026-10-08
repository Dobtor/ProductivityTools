"""RenderSandbox — Jinja 沙箱與求值。

沙箱環境、注入的 helper、底線方法白名單，以及所有「把表達式變成值」
的入口。

兩個不可混淆的求值路徑：
  * from_string() 永遠回**字串**——取值用這條
  * compile_expression() 回**真的 Python 物件**——recordset / list / dict
    來源用這條（_eval_collection / _eval_raw）。用錯會讓 recordset 變成
    "sale.order.line(1, 2)" 這種 repr，然後被當成「不是 recordset」
    靜默回空清單。

失敗策略也在這一層定案：條件失敗當真、取值失敗空字串。理由寫在各自的
docstring 裡，不要在呼叫端再發明一套。
"""
import re

from jinja2.sandbox import SandboxedEnvironment

from odoo.tools.misc import format_amount
from odoo.tools.misc import format_date as odoo_format_date
from odoo.tools.misc import format_datetime as odoo_format_datetime


# 禁止透過屬性存取觸碰的 ORM 提權／IO 向量。
# SandboxedEnvironment 預設只擋「底線開頭」屬性（_cr、__class__、_fields…），
# 但 env/sudo/browse/search/write 等是公開 recordset 介面 → 預設放行，
# 等於任何有 doc write 權限的內部使用者可在範本寫
#   {{ object.env['res.users'].sudo().browse(1).write({...}) }}
# 以 sudo 跑任意 ORM。故額外黑名單封死這些公開向量。
_UNSAFE_ATTRS = frozenset({
    'env', 'sudo', 'with_user', 'with_env', 'with_company', 'with_context',
    'browse', 'search', 'search_read', 'search_count', 'read', 'read_group',
    'create', 'write', 'unlink', 'copy', 'load', 'fields_get', 'get_metadata',
    'pool', 'cr', 'registry',
})

class _DocSandboxedEnvironment(SandboxedEnvironment):
    """收斂版 Jinja sandbox：在預設防護上額外封死 ORM 提權／IO 公開屬性。

    範本只需欄位讀取（object.<field>、.display_name）與注入的 helper，
    因此把 env/sudo/browse/search/write… 一律視為 unsafe，
    阻止 {{ object.env[...].sudo()... }} 這類 SSTI 提權（非理論，低權編輯者即可觸發）。
    """

    def is_safe_attribute(self, obj, attr, value):
        if attr in _UNSAFE_ATTRS:
            return False
        return super().is_safe_attribute(obj, attr, value)


class RenderSandbox:

    def _render_template(self, html, record, with_chip=False):
        """使用 Jinja2 SandboxedEnvironment 渲染 {{ field }} 變數，防止 SSTI。

        渲染流程：
          1. 套用 field_aliases 把 《中文 token》 轉成 {{ expression }}
          2. Jinja2 SandboxedEnvironment 渲染（globals 帶 helper）

        參數 with_chip：
          True 時，把 alias 替換結果包進 <span class="doc-field-token">…</span>，
          讓預覽頁面可直觀辨識「這格是動態欄位」。匯出 PDF/DOCX 預設 False，
          避免 span 樣式干擾排版（doc-field-token 樣式在預覽 wrapper 內定義）。
        """
        if not html or not record:
            return html or ''
        try:
            html = self._apply_field_aliases(html, with_chip=with_chip)
            env = self._get_sandbox_env(record)
            template = env.from_string(html)
            return template.render(object=record, user=self.env.user)
        except Exception as e:
            return html  # 渲染失敗時回傳原始 HTML

    def _get_render_helpers(self, record):
        """回傳要注入 Jinja2 globals 的 helper 對映。

        子類別可覆寫加入更多 helper（例如格式化、權限相關 lookup）。
        helper 內避免直接暴露 _fields 等 sandboxed attribute，由本層代為呼叫。
        """
        def selection_label(fieldname):
            """回傳 Selection 欄位的人類可讀標籤；非 Selection 或空值回空字串。"""
            if not record or not fieldname:
                return ''
            field = record._fields.get(fieldname)
            if not field or field.type != 'selection':
                return ''
            selection = field._description_selection(record.env)
            value = record[fieldname]
            return dict(selection).get(value, value or '')

        def format_date(value, fmt='%Y-%m-%d'):
            """安全地格式化 date / datetime；None 與字串原樣回傳。

            fmt 兩個特殊值走 Odoo 自己的語言格式（原生報表印的就是這個，
            `2026-10-08` 與 `10/08/2026` 在單據上是看得出來的差別）：
                'lang'           → odoo.tools.misc.format_date（只有日期）
                'lang_datetime'  → odoo.tools.misc.format_datetime（含時間）
            預設值刻意不動：既有範本（含使用者手工做的）的輸出不該因為這個
            改動而位移，要語言格式的是轉換器產生的表達式，它會明寫 'lang'。
            """
            if value is None or value is False:
                return ''
            if fmt in ('lang', 'lang_datetime'):
                try:
                    if fmt == 'lang_datetime':
                        out = odoo_format_datetime(self.env, value)
                    else:
                        out = odoo_format_date(self.env, value)
                except Exception:
                    out = ''
                # Odoo 的 format_date 對不是日期的值回空字串（不是拋例外）。
                # 原樣回傳字串是這個 helper 既有的約定——回空的話，
                # 把 format_date 套在非日期欄位上會靜默吃掉內容。
                return out or str(value)
            if hasattr(value, 'strftime'):
                return value.strftime(fmt)
            return str(value)

        def format_address(partner, without_company=False, with_name=False,
                           with_phone=False):
            """依國別格式排版的地址（對應原生的 t-options widget="contact"）。

            委派給 res.partner._display_address()——那支就是 Odoo 自己用的，
            會依國家的地址格式排列欄位、自動吃掉空欄位。自己拼
            street / city / zip 的話，換個國家就排錯。

            回傳含換行的字串；_inline_element_html 會把值內部的換行轉成
            <br/>，所以在文件上就是正常的多行地址。

            with_name=True 時第一行是對象名稱。_display_address 不含名稱，
            而原生的 contact widget 預設會印（它的 fields 預設含 "name"）
            ——收件人區塊少了名字就只是一串地址，所以轉換器會依原範本的
            fields 設定決定要不要帶。預設維持不帶，既有範本的版面不變。
            """
            if not partner:
                return ''
            try:
                target = partner[:1] if hasattr(partner, 'ids') else partner
                if not target:
                    return ''
                body = target._display_address(without_company=without_company)
                if with_name:
                    name = str(target.display_name or '').strip()
                    body = ('%s\n%s' % (name, body)) if name else body
                if with_phone:
                    # 原生 contact widget 的 fields 常含 phone（採購單、出貨單
                    # 都有）。不帶的話單據上少一行電話。
                    phone = str(target.phone or target.mobile or '').strip()
                    if phone:
                        body = '%s\n%s' % (body, phone)
                return body
            except Exception:
                # 不是 partner（或沒有這支方法）→ 退回 display_name，
                # 至少印得出東西而不是讓整份文件產不出來
                try:
                    return str(partner.display_name or '')
                except Exception:
                    return ''

        def format_money(value, currency=None):
            """金額格式化：幣別符號、符號位置、小數位都依 res.currency 設定。

            對應原生報表的 t-options='{"widget": "monetary",
            "display_currency": doc.currency_id}'。format_number 不能取代它
            ——單據上少了幣別符號、或小數位跟幣別設定不一致，會被當成錯誤。

            currency 省略時依序找 record.currency_id → record.company_id
            .currency_id → env.company.currency_id。在明細列上求值時 record
            就是該筆明細，所以 format_money(line.price_subtotal) 直接就對。
            """
            if value is None or value is False or value == '':
                return ''
            cur = self._resolve_currency(record, currency)
            try:
                amount = float(value)
            except (TypeError, ValueError):
                return str(value)
            if not cur:
                # 找不到幣別時退回純數字，不要印出沒有符號的半成品也不要炸
                return format(amount, ',.2f')
            return format_amount(self.env, amount, cur)

        def format_number(value, spec=',.2f'):
            """安全地格式化數字；非數字原樣回傳、空值回空字串。

            分組小計與聚合表達式直接求值出來是 500.0 這種樣子，印在單據上很醜。
            與 format_date 同一個設計：格式化放在表達式裡，不是另開一個 meta 欄位
            ——使用者在同一個輸入框裡看到完整的取值邏輯。
            """
            if value is None or value is False or value == '':
                return ''
            try:
                return format(float(value), spec)
            except (TypeError, ValueError):
                return str(value)

        def is_html_empty(value):
            """同原生報表的 is_html_empty()：沒有可見文字也沒有圖就算空。

            原生報表到處用它判斷「條款／備註有沒有內容」。沒有這個 helper，
            轉換過來的條件會以 UndefinedError 收場——而條件求值失敗是「當真」，
            於是空條款也會印出一個孤零零的標題。
            """
            return not self._html_has_content(
                value if isinstance(value, str) else (value or ''),
            )

        def has_group(xmlid):
            """使用者在不在這個群組（對應 QWeb 節點的 groups 屬性）。

            原生報表用 groups="uom.group_uom" 這種屬性做「只有某個群組看得到
            的欄位」。沙箱不開放 env，所以這件事只能由 helper 代為查。
            唯讀、只吃一個 xmlid 字串；查不到群組回 False（與 Odoo 的
            has_group 一致）。
            """
            try:
                return self.env.user.has_group(str(xmlid))
            except Exception:
                return False

        def _safe_len(value):
            try:
                return len(value)
            except TypeError:
                return 0

        def report_helper(target, name, *args, **kwargs):
            """呼叫白名單內的模型輔助方法。取不到值一律回空字串。

            沙箱擋掉所有底線開頭的方法——那是提權的主要入口，不該放寬。
            但原生報表確實會呼叫幾個純計算的輔助方法（提前付款折扣金額、
            折扣截止日），擋掉的後果是單據上那一段印成空白，而且沒有訊息。
            這裡用一份逐一讀過實作的白名單（_SAFE_REPORT_METHODS）開一道
            窄門：方法名與模型都要對得上，不在名單上就回空字串。
            """
            try:
                model = getattr(target, '_name', None)
                if not model or (model, name) not in self._SAFE_REPORT_METHODS:
                    return ''
                one = target[:1] if hasattr(target, 'ids') else target
                if not one:
                    return ''
                value = getattr(one, name)(*args, **kwargs)
            except Exception:
                # 參數不合、資料不全 → 空字串。一個輔助方法不該讓整份文件
                # 產不出來（與其他 helper 的失敗策略一致）。
                return ''
            # 不可寫成 value in (None, False)：0.0 == False，金額剛好是 0
            # 的時候會被當成「沒有值」印成空白。
            if value is None or value is False:
                return ''
            return value

        return {
            'selection_label': selection_label,
            'format_date': format_date,
            'is_html_empty': is_html_empty,
            'format_number': format_number,
            'format_money': format_money,
            'format_address': format_address,
            'report_helper': report_helper,
            'has_group': has_group,
            # Jinja 沒有 len()（它只有 |length），而 QWeb 條件到處寫
            # len(x) > 1。沒有這個 helper，那種條件會以 UndefinedError 收場
            # ——而條件求值失敗是「當真」，於是該藏起來的區塊照印。
            'len': _safe_len,
        }

    # 白名單：(模型, 方法名)。只收「讀完實作確認不寫資料」的純計算方法。
    # 想加自己的：繼承 doc.render.mixin 覆寫這個集合——但請先考慮改用
    # compute / related 欄位，那條路不需要任何白名單，也不必信任誰。
    #
    # 刻意不收 account.move._generate_qr_code：它在回傳前會
    # `self.qr_code_method = qr_code_method`（account_move.py:6032），
    # 也就是渲染一張 PDF 會改資料。轉換器改走公開的
    # res.partner.bank.build_qr_code_base64()，那支只讀。
    _SAFE_REPORT_METHODS = frozenset({
        # 提前付款折扣後的應付金額。只算百分比與四捨五入
        ('account.payment.term', '_get_amount_due_after_discount'),
        # 折扣截止日（已格式化的字串）
        ('account.payment.term', '_get_last_discount_date_formatted'),
        # 報表要印的訂單明細：濾掉「未入帳的預付款列」。只有 filtered
        ('sale.order', '_get_order_lines_to_report'),
        # 這張單合不合提前付款折扣的條件。只有比較與 filtered
        ('account.move', '_is_eligible_for_early_payment_discount'),
        # 出貨單上的品項說明（去掉重複的品名前綴）。只有字串處理
        ('stock.move', '_get_report_description_picking'),
        # 出貨單的彙總明細（同品項跨列合併）。只組一個 dict 回傳
        ('stock.move.line', '_get_aggregated_product_quantities'),
        # 發票上要印的批號／序號明細（sale_stock 加的）。只讀 stock move
        ('account.move', '_get_invoiced_lot_values'),
    })

    _CURRENCY_PATHS = ('currency_id', 'company_currency_id')

    def _coerce_currency(self, value):
        """把使用者給的值轉成 res.currency；轉不出來回 None（交給記錄推斷）。

        整段包 try 的理由：Jinja 的 Undefined 在屬性存取時就會 raise，所以
        format_money(x, currrency) 這種打錯字會炸掉整份文件。打錯字應該退回
        用記錄身上的幣別——印出一個帶符號的合理數字，而不是一張產不出來的單。

        bool 要排除：True 是 int 的子類別，會被 browse(1) 當成某個幣別的 id。
        """
        if value is None or value is False:
            return None
        try:
            if getattr(value, '_name', None) == 'res.currency':
                return value[:1] or None
            if isinstance(value, int) and not isinstance(value, bool):
                return self.env['res.currency'].browse(value).exists() or None
        except Exception:
            return None
        return None

    def _resolve_currency(self, record, currency=None):
        """把使用者給的 currency（recordset / id / None）解析成 res.currency。

        沒給時從記錄身上找。helper 內不暴露 env——由本層代為 browse，
        沙箱的 env/browse 黑名單因此不必開洞。
        """
        explicit = self._coerce_currency(currency)
        if explicit is not None:
            return explicit
        if record is not None and hasattr(record, '_fields'):
            for path in self._CURRENCY_PATHS:
                if path in record._fields:
                    try:
                        value = record[path]
                    except Exception:
                        continue
                    if value:
                        return value[:1]
            if 'company_id' in record._fields:
                try:
                    company = record.company_id
                except Exception:
                    company = None
                if company and company.currency_id:
                    return company.currency_id[:1]
        return self.env.company.currency_id[:1]

    # ══════════════════════════════════════════════════════════════════
    # Phase 3（藥丸改版）：content_json 為權威的快照 / 攤平管線
    #
    # 兩個動作，時間上徹底分離：
    #   _snapshot_content_json()  建立文件時求值一次，把值寫進藥丸，藥丸結構保留
    #   _flatten_content_json()   匯出時把藥丸攤平成純文字，不再求值
    #
    # 綁定定義存在元素的 extension.dobtorField（canvas-editor 的官方擴充點，
    # 且在其序列化白名單內），不存在可見文字裡，也不需要後端欄位記錄——
    # 見 security/ir.model.access.csv:25，一般編輯者對 doc.template.field 唯讀。
    # ══════════════════════════════════════════════════════════════════

    def _get_sandbox_env(self, record, undefined=None):
        """唯一的 Jinja 沙箱建構點。

        存在的理由：改版前 doc_controller.preview_content_json 自己 new 了一個
        裸 SandboxedEnvironment，繞過 _DocSandboxedEnvironment 的 ORM 提權黑名單
        （env / sudo / browse / write）。快照管線會執行來自舊 alias 遷移的任意
        Jinja 字串，絕不能重蹈覆轍。所有需要沙箱的地方一律呼叫這裡。
        """
        kwargs = {'undefined': undefined} if undefined is not None else {}
        env_j = _DocSandboxedEnvironment(**kwargs)
        for name, fn in self._get_render_helpers(record).items():
            env_j.globals[name] = fn
        return env_j

    def _field_meta_expression(self, meta):
        """把綁定 meta 轉成一段 Jinja 表達式；靜態值與空定義回 None。"""
        source = (meta.get('source') or 'record').strip()
        if source == 'static':
            return None
        expression = (meta.get('expression') or '').strip()
        if expression:
            return expression
        path = (meta.get('path') or '').strip()
        if not path:
            return None
        expression = f'object.{path}'
        fmt = (meta.get('format') or '').strip()
        if fmt:
            # 目前只支援 strftime 形態；非日期欄位給了格式也不會炸（helper 會原樣回傳）
            expression = "format_date(%s, '%s')" % (expression, fmt.replace("'", ''))
        return expression

    def _eval_collection(self, expression, record):
        """求值一段表達式並回傳 Python 清單（不是字串）。

        用 compile_expression 而不是 from_string：後者永遠回字串，recordset
        會變成 "sale.order.line(1, 2)" 這種 repr，然後被當成「不是 recordset」
        靜默回空清單——明細整個不印而且沒有任何訊息。

        沙箱的黑名單在 compile_expression 下仍然生效（已實測：env / sudo /
        底線開頭方法 / write 全部 SecurityError，__class__ 回 None）。
        """
        try:
            fn = self._get_sandbox_env(record).compile_expression(expression)
            value = fn(object=record, user=self.env.user)
        except Exception:
            return []
        if value is None or value is False:
            return []
        if hasattr(value, 'ids') and hasattr(value, '_name'):
            return list(value)
        if isinstance(value, (list, tuple)):
            return list(value)
        if isinstance(value, dict):
            # 取值而不是取鍵：QWeb 對 dict 跑 t-foreach 是走鍵，但範本內
            # 一律寫 aggregated_lines[key][...] 取值（出貨單的彙總明細就是
            # 這個形狀），所以真正要重複的是「值」。
            return list(value.values())
        return []

    def _eval_raw(self, expression, record, extra=None):
        """求值一段表達式並回傳**真的 Python 值**（失敗回 None）。

        與 _eval_collection 同一個理由用 compile_expression：from_string
        永遠回字串，bytes 會變成 "b'iVBOR...'" 這種 repr，印出來是一串
        看不懂的文字而且不報錯。
        """
        try:
            fn = self._get_sandbox_env(record).compile_expression(expression)
            return fn(object=record, user=self.env.user, **(extra or {}))
        except Exception:
            return None

    # ─── 展開 ────────────────────────────────────────────────────────

    # Jinja 把 recordset 字串化成 "res.partner(7,)" 這種 repr
    _RECORDSET_REPR_RE = re.compile(r'^[a-z][\w.]*\((?:\d+(?:,\s*)?)*\)$')

    def _fix_recordset_repr(self, rendered, expression, record, extra=None):
        """輸出是 recordset 的 repr 時改用 display_name 重算一次。

        t-field="o.partner_id" 想要的是名稱，而 Jinja 的字串化會給
        "res.partner(7,)"——單據上印出一個 Python repr 一定是錯的，而且
        不會報錯（實測：出貨單的收件人欄位就是這樣）。
        只在「輸出剛好長得像 repr」時才多算一次，所以不影響其他取值。
        """
        text = (rendered or '').strip()
        if not text or not self._RECORDSET_REPR_RE.match(text):
            return rendered
        raw = self._eval_raw(expression, record, extra)
        if hasattr(raw, 'ids') and hasattr(raw, '_name'):
            names = [n for n in (raw.mapped('display_name') or []) if n]
            return ', '.join(names)
        return rendered

    def _eval_for(self, record, extra=None):
        """回傳一個綁定到 record 的求值函式（含同表達式快取）。

        每筆明細各自建一個 sandbox env——helper（selection_label 等）是綁在
        record 上的閉包，共用一個 env 會讓 helper 指到錯的記錄。
        表達式編譯本身是微秒級，數百筆明細的成本可忽略。
        """
        env_j = self._get_sandbox_env(record)
        cache = {}
        extra = extra or {}

        def _eval(expression):
            if expression in cache:
                return cache[expression]
            try:
                rendered = env_j.from_string('{{ %s }}' % expression).render(
                    object=record, user=self.env.user, **extra,
                )
            except Exception:
                rendered = ''
            rendered = self._fix_recordset_repr(
                rendered, expression, record, extra)
            value = '' if rendered in (None, 'False', 'None') else str(rendered)
            cache[expression] = value
            return value

        return _eval

    def _eval_condition(self, expression, record, extra=None):
        """求值一個條件表達式。

        壞掉時回 True——寧可多印也不要靜默少印。條件寫錯而內容消失的話，
        使用者會以為是資料問題，幾乎追不到渲染層。
        """
        result = self._try_eval_condition(expression, record, extra)
        return True if result is None else result

    def _try_eval_condition(self, expression, record, extra=None):
        """同 _eval_condition，但求值失敗回 None 讓呼叫端自己決定語意。

        分組的分隔判斷式需要這個：失敗時當成「不是分隔點」才能退化成不分組；
        若沿用 _eval_condition 的「失敗當真」，一個壞掉的判斷式會讓每一筆明細
        都變成分組標題，印出 N 個空組——比不分組難看得多。
        """
        expression = (expression or '').strip()
        if not expression:
            return True
        try:
            env_j = self._get_sandbox_env(record)
            out = env_j.from_string(
                '{%% if %s %%}1{%% endif %%}' % expression
            ).render(object=record, user=self.env.user, **(extra or {}))
            return (out or '').strip() == '1'
        except Exception:
            return None
