import base64
import csv
import html as html_mod
import io
import json
import re

from jinja2.sandbox import SandboxedEnvironment

from odoo import models, api, fields
from odoo.exceptions import UserError, AccessError
from odoo.tools.misc import format_amount
from odoo.tools.image import FILETYPE_BASE64_MAGICWORD, image_data_uri
from odoo.tools.mail import html_sanitize


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


# 中文 token 標記符號。前後綴用《》（U+300A / U+300B），降低與正文衝突機率。
# 若 token 內含 》 會被 _ALIAS_PATTERN 提前終止，這是刻意行為（避免巢狀解析歧義）。
_ALIAS_PATTERN = re.compile(r'《([^》]+)》')

# 純變數名 Jinja 表達式（不含 object. 前綴的舊式變數）。
# 例：{{ project_name }} 會被當作可替換 token；{{ object.partner_id.name }} 不會（保留給 Jinja2）。
_VAR_NAME_RE = re.compile(r'^[A-Za-z_][\w]*$')
_JINJA_VARNAME_PATTERN = re.compile(r'\{\{\s*([A-Za-z_][\w]*)\s*\}\}')


class DocRenderMixin(models.AbstractModel):
    _name = 'doc.render.mixin'
    _description = '文件渲染 Mixin'

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
            """安全地格式化 date / datetime；None 與字串原樣回傳。"""
            if value is None or value is False:
                return ''
            if hasattr(value, 'strftime'):
                return value.strftime(fmt)
            return str(value)

        def format_address(partner, without_company=False, with_name=False):
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
                if not with_name:
                    return body
                name = str(target.display_name or '').strip()
                return ('%s\n%s' % (name, body)) if name else body
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

    def _apply_field_aliases(self, html, with_chip=False):
        """掃 html 把 alias 鍵替換成 Jinja2 expression。

        支援兩種 key 形式（同 dict）：
          1) 中文 token（含非 ASCII 字元）：對應文件內 《token》 替換。
          2) 純變數名（[A-Za-z_][\\w]*）：對應文件內 {{ varname }} 替換，
             方便沿用既有「{{ project_name }}」這類舊式範本而不需重寫。

        合併順序（後者覆寫前者）：template.field_aliases ← doc.field_aliases
        with_chip 為 True 時把替換結果包進 doc-field-token span。
        """
        aliases = self._collect_field_aliases()
        if not aliases or not html:
            return html

        # 拆成兩組（token / varname）以分別走兩條替換
        token_map = {}
        var_map = {}
        for key, expr in aliases.items():
            if not key or not expr:
                continue
            if _VAR_NAME_RE.match(key):
                var_map[key] = expr
            else:
                token_map[key] = expr

        def _wrap(expr, token):
            jinja = '{{ ' + expr + ' }}'
            if with_chip:
                return (
                    '<span class="doc-field-token" data-token="'
                    + (token or '').replace('"', '&quot;') + '">'
                    + jinja + '</span>'
                )
            return jinja

        if token_map:
            def _replace_token(m):
                tk = m.group(1).strip()
                expr = token_map.get(tk)
                if not expr:
                    return m.group(0)
                return _wrap(expr, tk)
            html = _ALIAS_PATTERN.sub(_replace_token, html)

        if var_map:
            def _replace_var(m):
                v = m.group(1).strip()
                expr = var_map.get(v)
                if not expr:
                    return m.group(0)
                return _wrap(expr, v)
            html = _JINJA_VARNAME_PATTERN.sub(_replace_var, html)

        return html

    def _collect_field_aliases(self):
        """合併 template 與自身的 alias map（自身覆寫 template）。

        Mixin 端用 _fields 防呆——非 doc.document/doc.template 呼叫時回空 dict。
        """
        merged = {}
        # 範本層級（doc.document 才有 template_id）
        if self._fields.get('template_id') and getattr(self, 'template_id', False):
            tmpl_aliases = getattr(self.template_id, 'field_aliases', None) or {}
            merged.update(tmpl_aliases)
        # 自身（doc.document.field_aliases 或 doc.template.field_aliases）
        if self._fields.get('field_aliases'):
            merged.update(getattr(self, 'field_aliases', None) or {})
        return merged

    def init_aliases_from_model_for(self, model_name, overwrite=False):
        """從給定 model_name 的欄位自動生成 alias，寫入 self.field_aliases。

        生成兩種 key（同個 dict）：
          1) 中文 token（field.field_description）→ 完整 expression
          2) 純變數名（field.name）→ 完整 expression — 沿用既有 {{ varname }} 也能渲染

        參數 overwrite：False=保留既有 token；True=整批以模型欄位重建。
        """
        self.ensure_one()
        if not self._fields.get('field_aliases'):
            return {'success': False, 'error': '此 model 沒有 field_aliases 欄位'}
        if not model_name or model_name not in self.env:
            return {'success': False, 'error': f"模型 '{model_name}' 不存在"}

        existing = dict(self.field_aliases or {})
        added = []
        skipped = []
        IrModelFields = self.env['ir.model.fields']
        ttypes = ('char', 'text', 'integer', 'float', 'monetary',
                  'date', 'datetime', 'boolean', 'selection', 'many2one')
        records = IrModelFields.search([
            ('model', '=', model_name),
            ('store', '=', True),
            ('ttype', 'in', list(ttypes)),
        ], order='field_description asc')

        def _expr_for(f):
            if f.ttype in ('date', 'datetime'):
                return f'format_date(object.{f.name})'
            if f.ttype == 'selection':
                return f"selection_label('{f.name}')"
            if f.ttype == 'many2one':
                return f'object.{f.name}.display_name'
            return f'object.{f.name}'

        for f in records:
            expr = _expr_for(f)
            label = (f.field_description or '').strip()
            # 中文 token alias
            if label:
                if label in existing and not overwrite:
                    skipped.append(label)
                else:
                    existing[label] = expr
                    added.append(label)
            # 純變數名 alias（同 expression）
            varname = f.name
            if varname in existing and not overwrite:
                skipped.append(varname)
            else:
                existing[varname] = expr
                added.append(varname)

        self.write({'field_aliases': existing})
        return {
            'success': True,
            'aliases': existing,
            'added': added,
            'skipped': skipped,
        }

    @api.model
    def get_available_fields(self, model_name, max_depth=2):
        """回傳指定 model 的可用欄位清單（含 Many2one 子欄位，深度限制 2）。"""
        if model_name not in self.env:
            raise UserError(f"模型 '{model_name}' 不存在")

        try:
            self.env[model_name].check_access('read')
        except AccessError:
            raise AccessError(f"您沒有讀取 '{model_name}' 的權限")

        return self._get_fields_for_model(model_name, max_depth=max_depth, current_depth=0)

    # 可放進文件的欄位型別。
    #
    # one2many / many2many 一定要在清單裡——左欄「明細（一對多）」那一組是靠
    # 它們產生的，漏掉的話整個重複列功能在 UI 上沒有入口（後端跑得動、使用者
    # 點不到）。binary 則是圖片藥丸（客戶簽名、公司 logo）的來源。
    # 前端負責把這三種分流到各自的面板，不要混進「主記錄欄位」的純量清單。
    _FIELD_TTYPES = (
        'char', 'text', 'integer', 'float', 'monetary',
        'date', 'datetime', 'boolean', 'selection', 'many2one',
        'one2many', 'many2many', 'binary', 'html',
    )
    # 純量（可直接當變數印出來）的型別——其餘要走專屬面板
    _SCALAR_TTYPES = (
        'char', 'text', 'html', 'integer', 'float', 'monetary',
        'date', 'datetime', 'boolean', 'selection', 'many2one',
    )

    def _get_fields_for_model(self, model_name, max_depth=2, current_depth=0):
        """遞迴取得模型欄位，限制深度以防止無限遞迴。"""
        IrModelFields = self.env['ir.model.fields']
        fields = IrModelFields.search([
            ('model', '=', model_name),
            ('store', '=', True),
            ('ttype', 'in', self._FIELD_TTYPES),
        ], order='field_description asc')

        result = []
        for f in fields:
            field_info = {
                'name': f.name,
                'label': f.field_description,
                'type': f.ttype,
                'expression': '{{{{ object.{} }}}}'.format(f.name),
            }
            if f.relation:
                field_info['relation'] = f.relation
            # Many2one：若未達深度限制，遞迴取子欄位。
            # 刻意不遞迴 x2many——一對多的子欄位由「明細欄位」面板在設好
            # 重複列之後另外載入，在這裡展開只會讓 payload 爆掉。
            if f.ttype == 'many2one' and f.relation and current_depth < max_depth:
                if f.relation in self.env:
                    try:
                        self.env[f.relation].check_access('read')
                        field_info['sub_fields'] = self._get_fields_for_model(
                            f.relation, max_depth, current_depth + 1
                        )
                    except AccessError:
                        field_info['sub_fields'] = []
            result.append(field_info)
        return result

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

    # ─── 元素樹走訪 ──────────────────────────────────────────────────
    #
    # content_json 是 canvas-editor getValue().data，形狀為
    #   {header: [...], main: [...], footer: [...]}
    # 只走 main 會漏掉頁首頁尾的變數；不遞迴 trList/tdList 會漏掉表格內的變數。
    # 快照、攤平、遷移三支共用這裡，不各寫一份。

    _ELEMENT_ZONES = ('header', 'main', 'footer')

    def _iter_element_lists(self, tree):
        """yield 樹中每一個「元素串列」（含頁首/頁尾/表格儲存格/超連結子串）。

        yield 的是 list 物件本身，呼叫端可就地改寫（攤平需要換掉元素）。
        """
        if isinstance(tree, dict):
            roots = [tree[z] for z in self._ELEMENT_ZONES
                     if isinstance(tree.get(z), list)]
            if not roots and not any(z in tree for z in self._ELEMENT_ZONES):
                # 少數舊資料直接存成單一 list 包在 dict 裡的情況，盡量容錯
                roots = [v for v in tree.values() if isinstance(v, list)]
        elif isinstance(tree, list):
            roots = [tree]
        else:
            return

        stack = list(roots)
        while stack:
            elements = stack.pop()
            yield elements
            for el in elements:
                if not isinstance(el, dict):
                    continue
                # 超連結 / 日期等群組元素的子串
                if isinstance(el.get('valueList'), list):
                    stack.append(el['valueList'])
                # 表格：trList → tdList → value（value 在儲存格內是元素串列）
                for row in (el.get('trList') or []):
                    if not isinstance(row, dict):
                        continue
                    for cell in (row.get('tdList') or []):
                        if isinstance(cell, dict) and isinstance(cell.get('value'), list):
                            stack.append(cell['value'])

    def _iter_elements(self, tree):
        """yield 樹中每一個元素 dict。"""
        for elements in self._iter_element_lists(tree):
            for el in elements:
                if isinstance(el, dict):
                    yield el

    # ─── 藥丸綁定 meta ───────────────────────────────────────────────

    DOBTOR_FIELD_KEY = 'dobtorField'

    # ─── 圖片與頁碼 ─────────────────────────────────────────────────
    #
    # 這兩種藥丸的共同點：**值不是文字**，所以攤平時不能變成文字元素。
    # 圖片要變成 image 元素（否則 data URI 會被當字串印出來，實測確認過），
    # 頁碼要變成 wkhtmltopdf 認得的 span。
    #
    # 圖片對應原生報表的 image_data_uri(doc.signature)——客戶簽名每張單據都
    # 不同，所以不能像公司 logo 那樣貼死一張圖。
    _IMAGE_SOURCE = 'image'
    _PAGE_SOURCE = 'page'
    # Html 欄位（條款、公司資訊、頁尾文字）。純量藥丸會把值逸出成可見的
    # <p>、<strong> 標籤——實測確認過，而且完全不報錯。
    # external_layout 的外框幾乎全是 Html 欄位，所以這個來源是外框轉換的前提。
    _HTML_SOURCE = 'html'
    # i18n：使用者自己打進範本的靜態文字。欄位「值」的語言由 ORM 依
    # with_context(lang=) 負責，不需要這個。
    _I18N_SOURCE = 'i18n'

    def _element_field_meta(self, element):
        """取出元素的綁定定義；不是模型變數藥丸就回 None。"""
        if not isinstance(element, dict) or element.get('type') != 'label':
            return None
        meta = (element.get('extension') or {}).get(self.DOBTOR_FIELD_KEY)
        return meta if isinstance(meta, dict) else None

    # ─── 區塊容器 ────────────────────────────────────────────────────
    #
    # 「條件區塊」「稅額彙總」這類需要包住多段內容的構件，容器一律用
    # 單格表格。理由：元素串列是扁平的，只有 value=='\n' 與表格列是可靠邊界；
    # 跨段落的起訖標記在使用者編輯時極易被拆散，而拆散後的結果無從察覺。
    # 表格則是原子結構——使用者刪就整個刪，不可能只刪掉一半。
    #
    # 副作用：容器本身是表格，輸出時必須不印框線（見 _table_to_html 的
    # doc-block class 與四條輸出路徑的 CSS）。

    _BLOCK_KEY = 'dobtorBlock'

    def _element_block_kind(self, element):
        """表格元素的區塊種類（'condition' / 'taxTotals'）；不是區塊容器回 ''。"""
        if not isinstance(element, dict) or element.get('type') != 'table':
            return ''
        kind = (element.get('extension') or {}).get(self._BLOCK_KEY)
        return kind if isinstance(kind, str) else ''

    def _drop_empty_tables(self, tree):
        """移除 trList 已空的表格，連同其後的孤兒換行。

        會變成空表格的兩種情況：條件區塊整塊被移除、重複列零筆明細。
        不一起吃掉後面那個換行的話，版面會留下一個空段落——使用者看到的是
        「條件為假時多了一行空白」，而且完全看不出來那行空白是怎麼來的。

        只吃「緊跟其後」的那一個換行：使用者自己在表格後面多按的 Enter
        是他要的空行，不該被當成殘渣清掉。
        """
        removed = 0
        for elements in self._iter_element_lists(tree):
            # 由後往前刪，避免索引位移
            for idx in range(len(elements) - 1, -1, -1):
                el = elements[idx]
                if not isinstance(el, dict) or el.get('type') != 'table':
                    continue
                rows = el.get('trList') or []
                # 欄條件可能把每一列的格子都刪掉——列還在但一格不剩，
                # _table_to_html 會輸出空字串，留著只會變成一個空段落
                if rows and any((r.get('tdList') or []) for r in rows
                                if isinstance(r, dict)):
                    continue
                stop = idx + 1
                nxt = elements[stop] if stop < len(elements) else None
                if isinstance(nxt, dict) and (nxt.get('value') or '') == '\n':
                    stop += 1
                del elements[idx:stop]
                removed += 1
        return removed

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

    def _image_data_uri(self, record, meta):
        """binary 欄位 → data: URI。取不到一律回空字串。

        用 path 走欄位而不是求 expression：binary 欄位的值是 base64 bytes，
        經過 Jinja 會變成 "b'iVBOR...'" 這種 repr——印出來是一串看不懂的文字，
        而且不會報錯。路徑直接取值才拿得到原始 bytes。

        刻意只接受 binary 欄位與既成的 data URI，不抓外部 URL：匯出不該在
        使用者按下載時去連外，那會讓匯出時間取決於第三方網站，在無外網的
        容器還會直接卡住（與 doc_document._emit_image 同一個決定）。
        """
        if record is None:
            return ''
        if (meta.get('barcodeType') or '').strip():
            return self._barcode_data_uri(record, meta)
        path = (meta.get('path') or '').strip()
        expression = (meta.get('expression') or '').strip()
        if path:
            value = self._traverse_path(record, path)
        elif expression:
            # 表達式來源：發票的付款 QR 是
            # partner_bank_id.build_qr_code_base64(...) 算出來的 data URI，
            # 不是某個 binary 欄位。一樣用 compile_expression 取真值——
            # from_string 會把 bytes 變成 "b'iVBOR...'" 的 repr。
            value = self._eval_raw(expression, record)
        else:
            return ''
        if not value:
            return ''
        if isinstance(value, str):
            if value.startswith('data:'):
                return value
            value = value.encode()
        if not isinstance(value, bytes):
            return ''
        # image_data_uri() 不驗證內容——認不出型別就一律當 png。所以把一個
        # 文字欄位誤設成圖片來源時，它會回 'data:image/png;base64,壞圖'，
        # 印出一張破圖而且不報錯。這裡先確認首位元組落在 Odoo 自己的
        # magic word 表裡（jpg/gif/png/svg/webp），認不出來就當沒有圖。
        if value[:1] not in FILETYPE_BASE64_MAGICWORD:
            return ''
        try:
            return image_data_uri(value)
        except Exception:
            # base64 壞了 → 空字串。單一壞圖不該讓整份文件產不出來
            return ''

    # ─── i18n 工具 ──────────────────────────────────────────────────
    #
    # 沒有這兩個工具，i18n 藥丸不會被用起來：沒人會回頭把一張做好的中文範本
    # 裡幾十段文字一個一個改成藥丸，也沒人會為了翻譯讓譯者登入 Odoo。

    def _iter_text_runs(self, tree):
        """yield (元素串列, 起, 迄, 文字)。

        連續的純文字元素合成一個「run」。換行、藥丸、表格都是 run 的邊界——
        跨越這些邊界合併會把兩段不相干的文字黏成一個翻譯字串。
        """
        for elements in self._iter_element_lists(tree):
            start = None
            for idx, el in enumerate(elements + [None]):
                is_text = (
                    isinstance(el, dict)
                    and (el.get('type') or 'text') == 'text'
                    and (el.get('value') or '') != '\n'
                    and el.get('value')
                )
                if is_text:
                    if start is None:
                        start = idx
                    continue
                if start is not None:
                    text = ''.join(
                        elements[i].get('value') or ''
                        for i in range(start, idx)
                    )
                    if text.strip():
                        yield elements, start, idx, text
                    start = None

    def extract_static_texts(self):
        """列出範本裡的靜態文字（給「抽出靜態文字」面板用）。

        回傳 [{'text', 'count'}]，依出現次數遞減。同一段文字出現多次時只列
        一筆——使用者勾一次就全部轉換，不必一段一段找。
        """
        self.ensure_one()
        tree = self._parse_content_json(self.content_json)
        if tree is None:
            return []
        counts = {}
        for _els, _s, _e, text in self._iter_text_runs(tree):
            key = text.strip()
            counts[key] = counts.get(key, 0) + 1
        return [
            {'text': t, 'count': c}
            for t, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        ]

    def convert_texts_to_i18n(self, texts, lang=None):
        """把指定的靜態文字轉成 i18n 藥丸（就地改寫 content_json）。

        轉換時把當前語言填進 texts，其他語言留空——留空的語言在渲染時會
        fallback 到有值的那個，所以半成品狀態下單據仍然印得出字。
        """
        self.ensure_one()
        if not texts:
            return {'converted': 0}
        wanted = {t.strip() for t in texts if (t or '').strip()}
        lang = lang or self.env.context.get('lang') or 'en_US'
        tree = self._parse_content_json(self.content_json)
        if tree is None:
            return {'converted': 0}

        converted = 0
        # 由後往前改寫：run 的索引會因替換而位移
        for elements, start, end, text in reversed(list(
                self._iter_text_runs(tree))):
            key = text.strip()
            if key not in wanted:
                continue
            # 保留第一個元素的字型樣式——轉成藥丸不該順手改掉字級與顏色
            base = {
                k: v for k, v in elements[start].items()
                if k in ('font', 'size', 'bold', 'italic', 'color',
                         'underline', 'strikeout', 'rowFlex')
            }
            pill = dict(base)
            pill.update({
                'type': 'label',
                'value': key,
                'label': {'backgroundColor': '#fff3e0', 'color': '#e65100'},
                'extension': {self.DOBTOR_FIELD_KEY: {
                    'source': self._I18N_SOURCE,
                    'labelText': key,
                    'texts': {lang: key},
                }},
            })
            elements[start:end] = [pill]
            converted += 1

        if converted:
            self.content_json = json.dumps(tree, ensure_ascii=False)
        return {'converted': converted}

    def i18n_entries(self):
        """範本裡所有 i18n 藥丸的翻譯表：[{'key', 'texts'}]。"""
        self.ensure_one()
        tree = self._parse_content_json(self.content_json)
        if tree is None:
            return []
        out = []
        seen = set()
        for element in self._iter_elements(tree):
            meta = self._element_field_meta(element)
            if not meta or (meta.get('source') or '') != self._I18N_SOURCE:
                continue
            texts = meta.get('texts') if isinstance(meta.get('texts'), dict) else {}
            key = (meta.get('key') or '').strip() or (meta.get('labelText') or '')
            if key in seen:
                continue
            seen.add(key)
            out.append({'key': key, 'texts': texts})
        return out

    def export_i18n_csv(self, langs=None):
        """翻譯表 → CSV 字串（第一欄是 key，其餘每欄一個語言）。"""
        self.ensure_one()
        entries = self.i18n_entries()
        langs = list(langs or [])
        if not langs:
            # 已安裝語言優先（維持 Odoo 的排序），再補上範本裡出現過但尚未
            # 安裝的語言——不補的話那些既有翻譯會在一次匯出匯入後消失
            found = set()
            for entry in entries:
                found |= set(entry['texts'].keys())
            installed = self.env['res.lang'].search([]).mapped('code')
            langs = installed + sorted(found - set(installed))
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(['key'] + langs)
        for entry in entries:
            writer.writerow(
                [entry['key']] + [entry['texts'].get(c, '') for c in langs]
            )
        return buf.getvalue()

    def import_i18n_csv(self, content):
        """CSV → 回填各 i18n 藥丸的 texts。

        以 key 比對，找不到的 key 列在 unknown 回傳——靜默忽略的話，譯者改錯
        一個 key，使用者只會看到「翻譯沒進去」而查不出原因。
        """
        self.ensure_one()
        if not content:
            return {'updated': 0, 'pills': 0, 'unknown': []}
        reader = csv.reader(io.StringIO(content))
        try:
            header = next(reader)
        except StopIteration:
            return {'updated': 0, 'pills': 0, 'unknown': []}
        langs = [c.strip() for c in header[1:]]
        table = {}
        for row in reader:
            if not row or not (row[0] or '').strip():
                continue
            table[row[0].strip()] = {
                langs[i]: (row[i + 1] or '').strip()
                for i in range(min(len(langs), len(row) - 1))
                if langs[i]
            }

        tree = self._parse_content_json(self.content_json)
        if tree is None:
            return {'updated': 0, 'unknown': sorted(table)}

        pills = 0
        hit = set()
        for element in self._iter_elements(tree):
            meta = self._element_field_meta(element)
            if not meta or (meta.get('source') or '') != self._I18N_SOURCE:
                continue
            key = (meta.get('key') or '').strip() or (meta.get('labelText') or '')
            incoming = table.get(key)
            if not incoming:
                continue
            texts = dict(meta.get('texts') or {})
            texts.update({k: v for k, v in incoming.items() if v})
            meta['texts'] = texts
            hit.add(key)
            pills += 1

        if pills:
            self.content_json = json.dumps(tree, ensure_ascii=False)
        # updated 計 key 數而不是藥丸數：同一段文字在範本裡出現兩次就有兩個
        # 藥丸，回報「2」會跟譯者手上 CSV 的 1 列對不上，看起來像多塞了東西。
        # 藥丸數另外回報給需要的人。
        return {
            'updated': len(hit),
            'pills': pills,
            'unknown': sorted(set(table) - hit),
        }

    def _html_field_value(self, record, meta):
        """Html 欄位 → 可直接嵌入的 HTML 片段（已消毒）。

        一定要過 html_sanitize：這些值最後會進 PDF（wkhtmltopdf 會執行 JS）
        與 doc.output.content_json（後台編輯器裡瀏覽），而 Odoo 並非所有
        Html 欄位在寫入時都有 sanitize。

        內容沒有可見文字也沒有圖時回空字串——Odoo 的 Html 編輯器留下的
        '<p><br></p>' 這類空殼若原樣輸出，自動收合空段落會判斷成「有值」，
        於是單據上多出一段看不見的空白。
        """
        expression = self._field_meta_expression(meta)
        if not expression or record is None:
            return ''
        env_j = self._get_sandbox_env(record)
        try:
            raw = env_j.from_string('{{ %s }}' % expression).render(
                object=record, user=self.env.user,
            )
        except Exception:
            return ''
        if not raw or raw in ('False', 'None'):
            return ''
        clean = html_sanitize(raw)
        if not self._html_has_content(clean):
            return ''
        return clean

    def _html_has_content(self, html):
        """等同原生報表的 is_html_empty()：沒有可見文字也沒有圖就算空。"""
        if not html:
            return False
        if '<img' in html or '<table' in html:
            return True
        try:
            from lxml import html as lhtml
            text = lhtml.fromstring('<div>%s</div>' % html).text_content()
        except Exception:
            text = re.sub(r'<[^>]+>', '', html)
        return bool((text or '').replace('\u00a0', ' ').strip())

    def _render_lang(self, record):
        """這份文件該用哪個語言渲染。

        順序：呼叫端明確指定（doc.report.lang）→ 記錄的客戶語言 → session。
        綁定上特地設了語言就該聽它（「印給英國客戶的英文版」），沒設則跟隨
        客戶——與原生報表一致（sale 的範本第 5 行就是
        doc.with_context(lang=doc.partner_id.lang)）。
        """
        explicit = self.env.context.get('doc_render_lang')
        if explicit:
            return explicit
        if record is not None and hasattr(record, '_fields'):
            for path in ('partner_id', 'partner_shipping_id'):
                if path in record._fields:
                    try:
                        partner = record[path]
                    except Exception:
                        continue
                    if partner and partner[:1].lang:
                        return partner[:1].lang
        return self.env.context.get('lang')

    def _record_in_lang(self, record, lang=None):
        """把記錄換到渲染語言的 context。

        少了這一步的後果是靜默的：綁定上設了 zh_TW，data-oe-lang 會寫 zh_TW，
        但商品名稱、selection 標籤、付款條件全部印成操作者的語言。
        """
        if record is None:
            return record
        lang = lang or self._render_lang(record)
        if not lang or self.env.context.get('lang') == lang:
            return record
        try:
            return record.with_context(lang=lang)
        except Exception:
            return record

    def _i18n_text(self, record, meta):
        """i18n 藥丸的文字。

        Fallback 刻意不回空字串：空白在單據上看起來像資料掉了，而一個未翻譯
        的英文字串至少讀得懂。順序為 當前語言 → en_US → 第一個有值的 → 標籤文字。
        """
        texts = meta.get('texts')
        if not isinstance(texts, dict):
            texts = {}
        lang = (record.env.context.get('lang')
                if record is not None else None) or self.env.context.get('lang')
        for candidate in (lang, (lang or '').split('_')[0], 'en_US'):
            if candidate and texts.get(candidate):
                return texts[candidate]
        for value in texts.values():
            if value:
                return value
        return meta.get('labelText') or ''

    # Odoo 自己的條碼 API 支援的型別（ir_actions_report.barcode()）。
    # 揀貨單用了 16 處條碼、發票有付款 QR——所以這不是發票專屬的需求。
    _BARCODE_TYPES = ('QR', 'Code128', 'Code39', 'EAN13', 'EAN8', 'UPCA')

    def _barcode_data_uri(self, record, meta):
        """條碼／QR → data: URI。委派 ir.actions.report.barcode()。

        原生報表用 o._generate_qr_code()，但底線開頭的方法被沙箱擋死（刻意的）。
        barcode() 是公開 API，而且同時支援 QR / Code128 / EAN13，涵蓋範圍比
        單一個 QR helper 大得多。

        掛在「圖片藥丸」上而不是做成沙箱 helper：藥丸的值是文字，helper 回
        data URI 的話會在單據上印出一長串 base64——實測過的那個失敗模式。
        """
        barcode_type = (meta.get('barcodeType') or 'QR').strip()
        expression = (meta.get('expression') or '').strip()
        if not expression:
            path = (meta.get('path') or '').strip()
            expression = 'object.%s' % path if path else ''
        if not expression:
            return ''
        env_j = self._get_sandbox_env(record)
        try:
            value = env_j.from_string('{{ %s }}' % expression).render(
                object=record, user=self.env.user,
            )
        except Exception:
            return ''
        value = (value or '').strip()
        if not value or value in ('False', 'None'):
            return ''
        try:
            raw = self.env['ir.actions.report'].barcode(
                barcode_type, value,
                width=int(meta.get('barcodeWidth') or 300),
                height=int(meta.get('barcodeHeight') or 100),
                humanreadable=1 if meta.get('barcodeText') else 0,
            )
        except Exception:
            # 條碼型別與值不相容（EAN13 要 12-13 位數字之類）→ 不印。
            # 這裡刻意不 raise：一個打錯的料號不該讓整張揀貨單印不出來。
            return ''
        return 'data:image/png;base64,%s' % base64.b64encode(raw).decode()

    def _snapshot_content_json(self, tree, record, only_pending=False):
        """把模型變數藥丸求值後寫進 label 的 value（就地改寫並回傳 tree）。

        決策一（建立時快照）：值在此凍結一次，之後改記錄不會動到文件。
        決策三（空值印空白）：求值為 falsy 一律寫空字串，不印底線也不擋。

        藥丸結構刻意保留——凍結後仍看得出哪些字是帶進來的、右側面板仍能顯示
        來源欄位、也仍然可以按「重新帶值」重跑。快照時就攤平的話這三件事全失去。

        only_pending=True 時只處理「還沒凍結過」的藥丸（meta 無 frozenAt）。
        這是匯出路徑用的：文件級的 snapshot_date 當開關會漏掉「快照之後才新增
        的藥丸」——它們會以標籤文字原樣印進 PDF，而且沒有任何錯誤訊息。
        改以逐元素標記，既有凍結值不動（決策一保住），新加的會補上值。
        """
        if not tree or record is None:
            return tree

        # 先展開重複列（表格明細）。必須在純量藥丸求值之前——展開會產生新的列，
        # 那些列裡的 source='line' 藥丸要以「各自的明細記錄」求值，不是主記錄。
        # Pass 順序有意義，不可對調：
        #   1. 展開重複列——要在純量求值前，展開產生的列裡 source='line' 藥丸
        #      必須以各自的明細記錄求值，不是主記錄
        #      （重複列內「沒有 groupId」的條件標記也在這一步就地解決：
        #       那種條件要逐筆判斷，第 2 關只有 object 可用，見
        #       _resolve_line_row_conditions）
        #   1.5. 展開稅額彙總——同樣會產生新的列（每個稅別一列），
        #      要在條件之前，產生出來的列才能被條件處理到
        #   2-3. 條件（列→欄→段落）——條件自成一體、不依賴藥丸的值，放在求值前
        #      可以少算被移除那部分。欄一定排在列之後：列條件的標記可能就放在
        #      某一欄裡，先刪欄會讓那個列條件無聲消失
        #   3.5. 清掉空表格——1 與 2 都可能把表格的列全部移除（零筆明細、
        #      條件區塊為假），留著空表格會在版面上印出一個空段落
        #   4. 純量藥丸求值（下方既有迴圈）
        #   5. 自動收合空段落——必須在求值後，要有值才知道是不是空的
        if not only_pending:
            self._expand_repeat_rows(tree, record)
            self._expand_tax_totals_rows(tree, record)
            # if/else 群組先一次求完值再傳下去：兩個 pass 共用同一份結果，
            # 否則列條件移走 if 標記後，段落裡的 else 就找不到配對了。
            groups = self._condition_group_results(tree, record)
            self._apply_row_conditions(tree, record, groups)
            self._apply_column_conditions(tree, record, groups)
            self._apply_paragraph_conditions(tree, record, groups)
            self._drop_empty_tables(tree)

        env_j = self._get_sandbox_env(record)
        cache = {}

        def _eval(expression):
            if expression in cache:
                return cache[expression]
            try:
                rendered = env_j.from_string('{{ %s }}' % expression).render(
                    object=record, user=self.env.user,
                )
            except Exception:
                # 求值失敗（欄位被刪、表達式壞掉）→ 空字串。
                # 這裡刻意不 raise：一個壞欄位不該讓整份文件產不出來。
                rendered = ''
            value = '' if rendered in (None, 'False', 'None') else str(rendered)
            cache[expression] = value
            return value

        stamp = fields.Datetime.to_string(fields.Datetime.now())
        for element in self._iter_elements(tree):
            meta = self._element_field_meta(element)
            if not meta:
                continue
            if only_pending and meta.get('frozenAt'):
                continue  # 已凍結過：維持原值，不重新求值
            src = meta.get('source') or 'record'
            if src in self._EXPANSION_SOURCES:
                # 由 _expand_repeat_rows 負責。走到這裡只有兩種情況：
                #   1. 展開已處理過（那時已蓋 frozenAt，上一個 continue 就擋掉了）
                #   2. 使用者把 line / running / 分組藥丸放在重複列之外——設定錯誤
                # 第 2 種刻意保留標籤文字不動，讓錯誤在文件上看得見而不是變空白。
                continue
            if src == 'static':
                element['value'] = meta.get('static') or ''
            elif src == self._IMAGE_SOURCE:
                element['value'] = self._image_data_uri(record, meta)
            elif src == self._HTML_SOURCE:
                element['value'] = self._html_field_value(record, meta)
            elif src == self._I18N_SOURCE:
                element['value'] = self._i18n_text(record, meta)
            else:
                expression = self._field_meta_expression(meta)
                element['value'] = _eval(expression) if expression else ''
            meta['frozenAt'] = stamp

        # 5. 自動收合空段落（規則 A）。只在完整快照時做——only_pending 是匯出時
        #    補值用的，那時版面早已定案，不該再動結構。
        if not only_pending:
            self._collapse_empty_paragraphs(tree)
        return tree

    # ─── 重複列（表格明細）─────────────────────────────────────────
    #
    # 業務單據的核心需求：訂單明細、發票行、出貨品項。純量藥丸只能帶一個值，
    # 多筆必須有「列複製」機制。
    #
    # 兩種新來源：
    #   source='repeat'  放在某一列的任一格，宣告「這一列對 path 重複」
    #                    path 指向主記錄的 one2many / many2many 欄位
    #   source='line'    該列內的欄位，path 相對於「當前明細」而非主記錄
    #
    # 為什麼標記放在「列內的藥丸」而不是列物件（trList[i]）的自訂屬性：
    #   canvas-editor 對 tr 只做 delete n.id、看起來會保留其他 key，但那無法在
    #   沒有瀏覽器的環境實測；而 element.extension 已實測確認會存活序列化。
    #   不確定時選已驗證的機制。副作用是列首多一個可見標記——這其實是優點，
    #   使用者看得到哪一列會重複，刪掉標記就是取消重複。
    #
    # 範圍：只做「表格列重複」，不做任意區塊重複。canvas-editor 的元素串列是
    #   扁平的，任意區塊的起訖標記在使用者編輯時極易被拆散；表格列有天然邊界。

    _REPEAT_SOURCE = 'repeat'
    _LINE_SOURCE = 'line'
    # 分組：標題列每組開頭印一次、小計列每組結尾印一次。
    # 為什麼做「分組」而不做 QWeb 那種累加器（current_subtotal = current_subtotal + ...）：
    #   累加器是 QWeb 因為只能單次順序掃描而被迫採用的實作手法，不是使用者的需求。
    #   使用者心裡想的是「依章節分組，每組印小計」。我們手上有完整 recordset，
    #   可以先分組再聚合——小計變成 group.lines|sum(attribute='...')，實測可用。
    #   在 WYSIWYG 編輯器裡暴露「宣告變數／每列更新／歸零」等於要使用者寫程式，
    #   而且寫錯了只會印出錯誤的數字，沒有任何訊息。
    # 標記（宣告這一列的角色）與取值藥丸分開：
    #   groupHeader / groupFooter  列角色標記
    #   group                      取值藥丸（組名、小計…），放哪一種列都一樣
    # 合成一種的話，「在標題列放一顆小計藥丸」會讓該列被誤判成小計列。
    _GROUP_HEADER_SOURCE = 'groupHeader'
    _GROUP_FOOTER_SOURCE = 'groupFooter'
    _GROUP_VALUE_SOURCE = 'group'
    # 流水藥丸：項次（1,2,3…）與逐列累計。這兩個是真的需要跨列狀態的少數情況，
    # 範圍極小（一個整數／一個浮點數），就放在展開的順序迴圈裡。
    _RUNNING_SOURCE = 'running'
    # 結構期（展開／條件）就處理完的來源：純量求值那一輪一律跳過。
    # 不跳過的後果各不相同但都是靜默的：
    #   line / running / group 會以主記錄重新求值，把每列各自的值蓋成同一個
    #   column 會把條件表達式當成值印出 True / False
    # 放錯位置的藥丸因此會原樣保留標籤文字——讓錯誤在文件上看得見。
    _EXPANSION_SOURCES = (
        _REPEAT_SOURCE, _LINE_SOURCE,
        _GROUP_HEADER_SOURCE, _GROUP_FOOTER_SOURCE, _GROUP_VALUE_SOURCE,
        _RUNNING_SOURCE, 'taxTotals', 'column', 'page',
    )

    def _iter_tables(self, tree):
        """yield 樹中所有表格元素（含表格內巢狀表格）。"""
        tables = []
        for elements in self._iter_element_lists(tree):
            for el in elements:
                if (isinstance(el, dict) and el.get('type') == 'table'
                        and isinstance(el.get('trList'), list)):
                    tables.append(el)
        return tables

    def _row_source_meta(self, row, sources):
        """列內第一個 source 落在 sources 的標記藥丸 → (元素, meta, source)。"""
        if not isinstance(row, dict):
            return None, None, ''
        for cell in (row.get('tdList') or []):
            if not isinstance(cell, dict):
                continue
            for el in (cell.get('value') or []):
                meta = self._element_field_meta(el)
                if not meta:
                    continue
                src = (meta.get('source') or '').strip()
                if src in sources:
                    return el, meta, src
        return None, None, ''

    def _row_repeat_meta(self, row):
        """這一列是否為重複列；是則回 (標記藥丸, meta)，否則 (None, None)。"""
        el, meta, _src = self._row_source_meta(row, (self._REPEAT_SOURCE,))
        return el, meta

    def _row_group_meta(self, row):
        """這一列是分組標題／小計列嗎 → (標記藥丸, meta, 'header'|'footer'|'')。"""
        el, meta, src = self._row_source_meta(
            row, (self._GROUP_HEADER_SOURCE, self._GROUP_FOOTER_SOURCE),
        )
        role = ''
        if src == self._GROUP_HEADER_SOURCE:
            role = 'header'
        elif src == self._GROUP_FOOTER_SOURCE:
            role = 'footer'
        return el, meta, role

    def _traverse_path(self, record, path):
        """沿 a.b.c 走值；中途取不到或遇到空值回 False。"""
        target = record
        for part in (path or '').split('.'):
            if not part:
                return False
            try:
                target = target[part]
            except Exception:
                return False
            if target is False or target is None:
                return False
        return target

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
        # dict 本身不是清單（使用者大概漏了取某個鍵），回空比印出一堆鍵名好
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

    def _line_key(self, item, key):
        """取明細的排序鍵。recordset 與 dict 都用 item[key]。"""
        try:
            return item[key]
        except Exception:
            return None

    def _sort_lines(self, lines, sort_by, desc=False):
        """依指定欄位排序明細。

        對應原生報表的 sorted(key=lambda …)——那在 Jinja 裡語法上就不存在
        （實測 TemplateSyntaxError），所以改成設定欄位名。多鍵排序請用
        「來源表達式」鏈接 |sort（Jinja 的 sort 是穩定排序，由低位往高位鏈即可）。

        排序失敗（型別混雜）時回原順序：排序壞掉不該讓整份文件產不出來，
        而順序不對至少看得出來。
        """
        key = (sort_by or '').strip()
        if not key or not lines:
            return lines

        def _k(item):
            value = self._line_key(item, key)
            if value is False or value is None or value == '':
                # 空值一律排最後，不管升降——空白夾在中間最難看
                return (1, '')
            if isinstance(value, bool):
                return (0, str(value))
            if isinstance(value, (int, float)):
                return (0, value)
            if hasattr(value, '_name'):
                try:
                    return (0, value.display_name or '')
                except Exception:
                    return (0, '')
            return (0, str(value))

        try:
            return sorted(lines, key=_k, reverse=bool(desc))
        except Exception:
            return lines

    def _resolve_repeat_records(self, record, meta, apply_filter=True):
        """求出重複的來源 recordset，並套用明細篩選。取不到回空清單。

        filter 對應原生報表的 lines_to_report（那個 t-set 做的就是這件事）：
        section / note / 預付款這類行不該印成空白列。
        表達式裡 line 與 object 都指向當前明細，兩種寫法都接受。

        apply_filter=False 是分隔列分組用的：分隔列（line_section）一定會被
        「not line.display_type」這類篩選排除掉，先篩就再也找不到分隔點了。
        分組必須先看到完整的明細序列，篩選改在分組後對組內明細做。
        """
        if record is None:
            return []
        source_expr = (meta.get('sourceExpression') or '').strip()
        if source_expr:
            # 進階來源：排序（|sort）與非 recordset 的來源（發票的付款紀錄、
            # 分期明細、稅別都是 list of dict）都靠這條
            lines = self._eval_collection(source_expr, record)
        else:
            path = (meta.get('path') or '').strip()
            if not path:
                return []
            target = self._traverse_path(record, path)
            if hasattr(target, '_name') and hasattr(target, 'ids'):
                lines = list(target)
            elif isinstance(target, (list, tuple)):
                # 計算欄位回傳 list of dict 的情形：發票的 payment_term_details
                # （分期明細）就是這樣。原本只收 recordset，結果明細整個不印
                # 而且沒有任何訊息——那是最難追的一種壞法。
                # 字串／位元組刻意不收：Char 欄位設成重複來源會逐字展開成
                # 一列一個字，比直接不印更難懂。
                lines = list(target)
            else:
                # 純量欄位設成重複來源是設定錯誤
                return []
        lines = self._sort_lines(
            lines, meta.get('sortBy'), meta.get('sortDesc'),
        )
        expr = (meta.get('filter') or '').strip()
        if apply_filter and expr:
            lines = self._filter_lines(lines, expr)
        return lines

    def _filter_lines(self, lines, expression):
        return [
            ln for ln in lines
            if self._eval_condition(expression, ln, extra={'line': ln})
        ]

    # ─── 分組 ────────────────────────────────────────────────────────

    def _group_key_label(self, value):
        """分組鍵要可雜湊、標籤要可讀。recordset 用 (model, ids) 當鍵。"""
        if value is False or value is None:
            return False, ''
        if hasattr(value, '_name') and hasattr(value, 'ids'):
            try:
                names = value.mapped('display_name')
            except Exception:
                names = []
            return (value._name, tuple(value.ids)), ', '.join(n for n in names if n)
        return value, str(value)

    def _marker_group_label(self, line):
        """分隔列模式下該組的標籤。

        取 name 再退回 display_name：sale 的 line_section 把章節文字放在 name，
        display_name 會變成「訂單編號 - 章節」這種對單據沒意義的字串。
        真正可靠的做法是在標題列放一顆 source='line' 藥丸明確指定欄位，
        group.label 只是個不必設定的方便值。
        """
        for attr in ('name', 'display_name'):
            try:
                value = line[attr]
            except Exception:
                continue
            if value:
                return str(value)
        return ''

    def _repeat_group_mode(self, meta):
        """有效的分組模式（設了模式但沒設依據＝等於不分組）。"""
        mode = (meta.get('groupMode') or '').strip()
        if mode == 'field' and not (meta.get('groupBy') or '').strip():
            return ''
        if mode == 'marker' and not (meta.get('groupSplitOn') or '').strip():
            return ''
        return mode if mode in ('field', 'marker') else ''

    def _resolve_repeat_groups(self, record, meta):
        """取明細並切成組：[{'key','label','header','lines','index','count'}]。

        沒設定分組時回「單一組包全部明細」，展開邏輯因此只有一條路徑；
        副作用是未分組時的小計列會變成總計列——那正是使用者會期待的行為。
        """
        mode = self._repeat_group_mode(meta)
        group_by = (meta.get('groupBy') or '').strip()
        split_on = (meta.get('groupSplitOn') or '').strip()
        flt = (meta.get('filter') or '').strip()
        # 分隔列模式要看到完整序列才找得到分隔點，篩選延後到分組之後
        lines = self._resolve_repeat_records(
            record, meta, apply_filter=(mode != 'marker'),
        )

        if not mode:
            groups = [{'key': False, 'label': '', 'header': None, 'lines': lines}]
        elif mode == 'field':
            groups = []
            seen = {}
            for line in lines:
                key, label = self._group_key_label(
                    self._traverse_path(line, group_by),
                )
                if key not in seen:
                    seen[key] = {
                        'key': key, 'label': label, 'header': None, 'lines': [],
                    }
                    groups.append(seen[key])
                seen[key]['lines'].append(line)
        else:
            groups = []
            current = None
            include_header = bool(meta.get('groupIncludeHeader'))
            for line in lines:
                is_split = self._try_eval_condition(
                    split_on, line, extra={'line': line},
                )
                if is_split:
                    current = {
                        'key': line.id, 'label': self._marker_group_label(line),
                        'header': line, 'lines': [],
                    }
                    groups.append(current)
                    if include_header:
                        current['lines'].append(line)
                    continue
                if current is None:
                    # 第一個分隔列之前就有明細：給一個無標題的組，不要丟掉資料
                    current = {
                        'key': False, 'label': '', 'header': None, 'lines': [],
                    }
                    groups.append(current)
                current['lines'].append(line)

        if mode == 'marker' and flt:
            for group in groups:
                group['lines'] = self._filter_lines(group['lines'], flt)
        # 空組不印：原生報表的 _get_order_lines_to_report 也會丟掉空章節，
        # 印一個標題配 0 元小計只會讓人以為資料掉了。
        groups = [g for g in groups if g['lines']]
        total = len(groups)
        for idx, group in enumerate(groups, start=1):
            group['index'] = idx
            group['count'] = total
        return groups

    # ─── 展開 ────────────────────────────────────────────────────────

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
            value = '' if rendered in (None, 'False', 'None') else str(rendered)
            cache[expression] = value
            return value

        return _eval

    def _running_value(self, meta, line, state_bank, key, eval_line):
        """流水藥丸的值。state_bank 是 {'never': {}, 'group': {}} 兩本帳。"""
        op = (meta.get('op') or 'index').strip()
        bucket = state_bank['group' if (meta.get('resetOn') or '') == 'group'
                            else 'never']
        if op == 'index':
            bucket[key] = int(bucket.get(key) or 0) + 1
            return str(bucket[key])
        if op == 'sum':
            expression = (meta.get('expression') or '').strip()
            raw = eval_line(expression) if expression else ''
            try:
                delta = float(raw)
            except (TypeError, ValueError):
                delta = 0.0
            bucket[key] = float(bucket.get(key) or 0.0) + delta
            if meta.get('asMoney'):
                # 累計金額欄跟其他金額欄必須用同一套格式，否則同一張單上
                # 「金額」有幣別符號、「累計」沒有，看起來像兩個系統拼起來的
                cur = self._resolve_currency(line)
                if cur:
                    return format_amount(self.env, bucket[key], cur)
            spec = (meta.get('numberFormat') or ',.2f').strip()
            try:
                return format(bucket[key], spec)
            except (TypeError, ValueError):
                return str(bucket[key])
        return ''

    def _fill_line_row(self, row, line, marker_el, stamp, state_bank=None,
                       variant=0):
        """對複製出來的一列求值：source='line' 的藥丸以該明細為 object。

        流水藥丸（source='running'）的累加器以「列型索引 + 該藥丸在範本列中的
        位置」當鍵——每個複製出來的列都源自同一個範本列，位置因此是穩定且不必
        前端配 id 的識別方式。位置要在過濾標記藥丸「之前」算，否則索引會跟
        範本列對不上。
        列型索引也要進鍵裡：商品列的項次不該被備註列的流水藥丸影響，而兩者
        在各自版面裡的位置很可能剛好相同。
        """
        eval_line = self._eval_for(line, extra={'line': line})
        for td_idx, cell in enumerate(row.get('tdList') or []):
            if not isinstance(cell, dict):
                continue
            values = cell.get('value')
            if not isinstance(values, list):
                continue
            keep = []
            for pos, el in enumerate(values):
                meta = self._element_field_meta(el)
                src = (meta.get('source') or '').strip() if meta else ''
                if src == self._REPEAT_SOURCE:
                    # 標記藥丸不進成品——它是設計期的宣告，不是內容
                    continue
                if src == self._LINE_SOURCE:
                    expression = self._field_meta_expression(meta)
                    el['value'] = eval_line(expression) if expression else ''
                    meta['frozenAt'] = stamp
                elif src == self._RUNNING_SOURCE and state_bank is not None:
                    el['value'] = self._running_value(
                        meta, line, state_bank, (variant, td_idx, pos),
                        eval_line,
                    )
                    meta['frozenAt'] = stamp
                keep.append(el)
            cell['value'] = keep

    def _fill_group_row(self, row, group, record, stamp):
        """對分組標題／小計列求值。

        群組上下文 group 是個 dict（Jinja 的屬性查找會退回 item 查找，所以
        group.lines 寫得通）。另外允許列內放 source='line' 藥丸指向分隔列本身
        ——章節標題文字要用 line.name 這種明確欄位才可靠，group.label 只是方便值。
        """
        eval_group = self._eval_for(record, extra={'group': group})
        header = group.get('header')
        eval_header = self._eval_for(header, extra={'line': header}) if header else None
        for cell in (row.get('tdList') or []):
            if not isinstance(cell, dict):
                continue
            values = cell.get('value')
            if not isinstance(values, list):
                continue
            keep = []
            for el in values:
                meta = self._element_field_meta(el)
                src = (meta.get('source') or '').strip() if meta else ''
                if src in (self._GROUP_HEADER_SOURCE,
                           self._GROUP_FOOTER_SOURCE,
                           self._GROUP_VALUE_SOURCE):
                    if meta.get('isMarker'):
                        # 宣告用的標記藥丸（「分組標題列」字樣）不進成品
                        continue
                    expression = (meta.get('expression') or '').strip()
                    el['value'] = eval_group(expression) if expression else ''
                    meta['frozenAt'] = stamp
                elif src == self._LINE_SOURCE:
                    expression = self._field_meta_expression(meta)
                    el['value'] = (
                        eval_header(expression)
                        if (eval_header and expression) else ''
                    )
                    meta['frozenAt'] = stamp
                keep.append(el)
            cell['value'] = keep

    def _pick_row_variant(self, variants, line):
        """依列型條件挑出這筆明細該用哪一個列模板。

        對應原生報表在迴圈裡的 t-if / t-elif / t-else（sale 的
        ir_actions_report_templates.xml:130,137 —— 商品列／章節列／備註列
        各自不同版面，而且必須保持原本的交錯順序）。

        規則：
          1. 依文件順序，第一個「列型條件成立」的列型勝出
          2. 都不成立 → 第一個「沒有列型條件」的列型（相當於 t-else）
          3. 連那個都沒有 → 第一個列型（寧可多印，不要靜默漏印）

        刻意不用單純的「第一個符合就勝出」（留空＝一律符合）：那會迫使使用者
        把新加的列型搬到主要列上面去，否則永遠不會生效——而「加了設定卻沒反應」
        是最難自己看出來的一種錯。有條件的優先、無條件的當 else，加列型就不必
        搬動任何東西。

        用 _try_eval_condition 而不是 _eval_condition：壞掉的列型條件應該
        「不要攔截」這筆明細，讓它落到 else；若沿用「失敗當真」，一個寫壞的
        條件會把所有明細都吃進那個列型。
        """
        fallback = None
        for item in variants:
            expr = (item[1].get('rowFilter') or '').strip()
            if not expr:
                if fallback is None:
                    fallback = item
                continue
            if self._try_eval_condition(expr, line, extra={'line': line}) is True:
                return item
        return fallback if fallback is not None else variants[0]

    def _expand_repeat_rows(self, tree, record):
        """把重複列展開成每筆明細一列（就地改寫 tree）。回傳展開的列數。

        零筆明細時整列移除——留一列空白會在單據上印出一條空的表格列，
        看起來像資料掉了。整個表格只剩空的 trList 時由 _drop_empty_tables 收尾。

        輸出順序固定為 分組標題 → 明細 → 分組小計，不管使用者把模板列放在
        表格的哪裡。理由：那是唯一說得通的語意，而要求使用者把三列排對順序
        只會製造一種「看起來沒錯但印出來順序不對」的錯誤。

        同一個 repeatId 可以有多個重複列（列型）：來源／篩選／分組一律取
        **第一個**的設定，其餘只貢獻自己的 rowFilter 與版面。否則兩個列型
        各設一個不同的 path，結果會是哪個生效取決於列的先後——那種不確定性
        在範本裡完全看不出來。
        """
        import copy as _copy
        if not tree or record is None:
            return 0
        stamp = fields.Datetime.to_string(fields.Datetime.now())
        total = 0

        for table in self._iter_tables(tree):
            rows = table.get('trList') or []
            # 先把分組標題／小計列抽出來當模板（依 repeatId 歸戶）
            templates = {'header': {}, 'footer': {}}
            body_rows = []
            for row in rows:
                _el, g_meta, role = self._row_group_meta(row)
                if role:
                    rid = (g_meta.get('repeatId') or '').strip()
                    templates[role].setdefault(rid, row)
                    continue
                body_rows.append(row)
            changed = bool(templates['header'] or templates['footer'])

            # 重複列依 repeatId 歸戶成「列型」清單，保留文件順序。
            # 沒帶 repeatId 的各自成一組（以列物件的 id() 當鍵），維持舊行為。
            variants = {}
            order = []
            for row in body_rows:
                marker_el, meta = self._row_repeat_meta(row)
                if not marker_el:
                    continue
                rid = (meta.get('repeatId') or '').strip() or 'anon-%d' % id(row)
                if rid not in variants:
                    variants[rid] = []
                    order.append(rid)
                variants[rid].append((row, meta, len(variants[rid])))

            expanded = set()
            new_rows = []
            for row in body_rows:
                marker_el, meta = self._row_repeat_meta(row)
                if not marker_el:
                    new_rows.append(row)
                    continue
                rid = (meta.get('repeatId') or '').strip() or 'anon-%d' % id(row)
                if rid in expanded:
                    # 同一組的其他列型只是模板，不在原位輸出
                    continue
                expanded.add(rid)
                changed = True
                group_of = variants[rid]
                primary_meta = group_of[0][1]

                hdr_tmpl = templates['header'].get(rid)
                ftr_tmpl = templates['footer'].get(rid)
                if rid:
                    # 分組列沒帶 repeatId（單一重複列時前端可省）也要能配對
                    hdr_tmpl = hdr_tmpl or templates['header'].get('')
                    ftr_tmpl = ftr_tmpl or templates['footer'].get('')

                groups = self._resolve_repeat_groups(record, primary_meta)
                state_bank = {'never': {}, 'group': {}}
                for group in groups:
                    state_bank['group'] = {}
                    if hdr_tmpl is not None:
                        clone = _copy.deepcopy(hdr_tmpl)
                        clone.pop('id', None)
                        self._fill_group_row(clone, group, record, stamp)
                        new_rows.append(clone)
                    for line in group['lines']:
                        tmpl, _m, v_idx = self._pick_row_variant(group_of, line)
                        clone = _copy.deepcopy(tmpl)
                        clone.pop('id', None)
                        self._fill_line_row(
                            clone, line, marker_el, stamp, state_bank,
                            variant=v_idx,
                        )
                        if not self._resolve_line_row_conditions(
                                clone, record, line):
                            continue
                        new_rows.append(clone)
                        total += 1
                    if ftr_tmpl is not None:
                        clone = _copy.deepcopy(ftr_tmpl)
                        clone.pop('id', None)
                        self._fill_group_row(clone, group, record, stamp)
                        new_rows.append(clone)
            if changed:
                table['trList'] = new_rows
        return total

    def _resolve_line_row_conditions(self, row, record, line):
        """重複列內的條件標記：以該筆明細求值，不成立就整列不輸出。

        為什麼要在展開階段處理，而不是交給後面的 _apply_row_conditions：
        那一關只有 object 可用（_condition_marker_result 不帶 line），
        所以同一個條件在每一列都得到同一個答案——要嘛全留要嘛全刪。
        而原生報表裡「逐列條件」很常見（發票的付款列
        <tr t-if="payment_vals['is_exchange'] == 0">），那種一定得逐筆判斷。

        若／否則配對（groupId）不在這裡處理：它的另一半在別的列上，
        展開階段看不到，留給 _apply_row_conditions。
        """
        def _plain_markers(cell):
            out = []
            for el in (cell.get('value') or []):
                meta = self._element_condition_meta(el)
                if meta and not (meta.get('groupId') or '').strip():
                    out.append((el, meta))
            return out

        cells = [c for c in (row.get('tdList') or []) if isinstance(c, dict)]
        found = [(el, meta) for cell in cells for el, meta in _plain_markers(cell)]
        if not found:
            return True
        extra = {'line': line}
        for _el, meta in found:
            expr = meta.get('expression') or meta.get('path') or ''
            # _eval_condition 求值失敗回 True（寧可多印），所以只在明確為
            # False 時才丟掉這一列。
            if self._eval_condition(expr, record, extra=extra) is False:
                return False
        # 條件成立 → 把標記清掉。不清的話後面那一關會用「只有 object」的
        # 環境再判一次，帶 line 的條件在那裡求值失敗 → 當成真 → 看起來沒事，
        # 但條件其實從此沒有作用。
        ids = {id(el) for el, _m in found}
        for cell in cells:
            if isinstance(cell.get('value'), list):
                cell['value'] = [el for el in cell['value']
                                 if id(el) not in ids]
        return True

    def _count_repeat_rows(self, tree):
        """統計樹中的重複列數（給 UI 顯示「此範本有 N 個重複列」用）。"""
        if not tree:
            return 0
        count = 0
        for table in self._iter_tables(tree):
            for row in (table.get('trList') or []):
                if self._row_repeat_meta(row)[0]:
                    count += 1
        return count

    # ─── 稅額彙總（內建區塊）────────────────────────────────────────
    #
    # 對應原生報表的 t-call="sale.document_tax_totals"——那支子範本自己有迴圈，
    # 單純內聯進範本做不到。
    #
    # 為什麼做成「內建區塊」而不是讓使用者用 repeat 對 tax_totals 這個 dict 重複：
    #   稅額彙總的版型在各國法規下變化不大，但 tax_totals 這個資料結構每個 Odoo
    #   版本都在改（amount_by_group 在 18 就已經消失）。做成內建區塊，升版時改
    #   模組一處；走通用重複則是每個客戶的範本裡都埋著一串
    #   object.tax_totals['subtotals']，升版時要一張一張改，而且錯了只會印出空白。
    #
    # 結構沿用重複列的作法：三列各放一個標記，part 決定它是哪一列。
    # 稅別列會依稅別數複製，其餘兩列原地填值。使用者因此可以各自調整樣式
    # （把總計那列加粗之類），而不是面對一個不能動的黑盒子。
    _TAX_TOTALS_SOURCE = 'taxTotals'
    # Odoo 18 的鍵名（已實測）：
    #   頂層    has_tax_groups / base_amount_currency / tax_amount_currency /
    #           total_amount_currency
    #   小計    name / base_amount_currency / tax_amount_currency / tax_groups
    #   稅別    group_name / group_label / tax_amount_currency /
    #           display_base_amount_currency
    _TAX_PARTS = ('untaxed', 'groups', 'total')

    def _row_tax_totals_meta(self, row):
        el, meta, _src = self._row_source_meta(row, (self._TAX_TOTALS_SOURCE,))
        return el, meta

    def _tax_totals_data(self, record, meta):
        path = (meta.get('path') or 'tax_totals').strip()
        data = self._traverse_path(record, path)
        return data if isinstance(data, dict) else {}

    def _fill_tax_row(self, row, values, stamp, currencies=None):
        """填一列稅額彙總。

        values 的形狀是 {'document': {...}, 'company': {...}}，每個藥丸依自己的
        currencyMode 取——對應原生發票的 document_tax_totals_company_currency_template
        （外幣發票同時印公司幣別）。兩種幣別的數字都在 tax_totals 裡，差別只是
        鍵名有沒有 _currency 後綴。

        金額預設走 format_amount（幣別符號 + 幣別小數位）而不是 ',.2f'：
        稅額彙總一定是金額，預設值應該直接可用。使用者給了 numberFormat
        才改用純數字格式。
        """
        currencies = currencies or {}
        for cell in (row.get('tdList') or []):
            if not isinstance(cell, dict):
                continue
            items = cell.get('value')
            if not isinstance(items, list):
                continue
            keep = []
            for el in items:
                meta = self._element_field_meta(el)
                src = (meta.get('source') or '').strip() if meta else ''
                if src == self._TAX_TOTALS_SOURCE:
                    if meta.get('isMarker'):
                        continue
                    mode = (meta.get('currencyMode') or 'document').strip()
                    if mode not in values:
                        mode = 'document'
                    bucket = values.get(mode) or {}
                    currency = currencies.get(mode)
                    field = (meta.get('field') or 'amount').strip()
                    raw = bucket.get(field)
                    if raw is None or raw is False:
                        el['value'] = ''
                    elif field == 'label':
                        el['value'] = str(raw)
                    else:
                        spec = (meta.get('numberFormat') or '').strip()
                        try:
                            amount = float(raw)
                        except (TypeError, ValueError):
                            el['value'] = str(raw)
                            meta['frozenAt'] = stamp
                            keep.append(el)
                            continue
                        if not spec and currency:
                            el['value'] = format_amount(
                                self.env, amount, currency,
                            )
                        else:
                            try:
                                el['value'] = format(amount, spec or ',.2f')
                            except (TypeError, ValueError):
                                el['value'] = str(raw)
                    meta['frozenAt'] = stamp
                keep.append(el)
            cell['value'] = keep

    def _expand_tax_totals_rows(self, tree, record):
        """展開稅額彙總區塊：稅別列依稅別數複製，稅前小計／總計列原地填值。

        刻意不要求表格帶 dobtorBlock='taxTotals'——標記藥丸在哪裡就在哪裡展開。
        區塊標記只負責「輸出時不印框線」，兩件事分開，使用者把標記貼到別的
        表格裡時也還是會動，而不是靜默不生效。
        """
        import copy as _copy
        if not tree or record is None:
            return 0
        stamp = fields.Datetime.to_string(fields.Datetime.now())
        count = 0

        for table in self._iter_tables(tree):
            rows = table.get('trList') or []
            if not any(self._row_tax_totals_meta(r)[1] for r in rows):
                continue
            new_rows = []
            for row in rows:
                _el, meta = self._row_tax_totals_meta(row)
                if not meta:
                    new_rows.append(row)
                    continue
                data = self._tax_totals_data(record, meta)
                # tax_totals 帶的是 currency_id / company_currency_id
                # （整數 id，不是 recordset）
                currencies = {
                    'document': self._resolve_currency(
                        record, data.get('currency_id'),
                    ),
                    'company': self._resolve_currency(
                        record, data.get('company_currency_id'),
                    ),
                }
                part = (meta.get('part') or 'total').strip()
                if part not in self._TAX_PARTS:
                    part = 'total'
                if part == 'untaxed':
                    subs = data.get('subtotals') or []
                    sub = subs[0] if subs else {}
                    self._fill_tax_row(row, {
                        'document': {
                            'label': sub.get('name') or '',
                            'amount': sub.get('base_amount_currency'),
                            'base': sub.get('base_amount_currency'),
                        },
                        'company': {
                            'label': sub.get('name') or '',
                            'amount': sub.get('base_amount'),
                            'base': sub.get('base_amount'),
                        },
                    }, stamp, currencies)
                    new_rows.append(row)
                    count += 1
                elif part == 'groups':
                    # 零稅別時整列消失——印一列 0 元的稅額比不印更容易被誤讀
                    for sub in (data.get('subtotals') or []):
                        for grp in (sub.get('tax_groups') or []):
                            clone = _copy.deepcopy(row)
                            clone.pop('id', None)
                            label = (grp.get('group_label')
                                     or grp.get('group_name') or '')
                            self._fill_tax_row(clone, {
                                'document': {
                                    'label': label,
                                    'amount': grp.get('tax_amount_currency'),
                                    'base': grp.get(
                                        'display_base_amount_currency',
                                        grp.get('base_amount_currency'),
                                    ),
                                },
                                'company': {
                                    'label': label,
                                    'amount': grp.get('tax_amount'),
                                    'base': grp.get(
                                        'display_base_amount',
                                        grp.get('base_amount'),
                                    ),
                                },
                            }, stamp, currencies)
                            new_rows.append(clone)
                            count += 1
                else:
                    self._fill_tax_row(row, {
                        'document': {
                            'label': '',
                            'amount': data.get('total_amount_currency'),
                            'base': data.get('base_amount_currency'),
                        },
                        'company': {
                            'label': '',
                            'amount': data.get('total_amount'),
                            'base': data.get('base_amount'),
                        },
                    }, stamp, currencies)
                    new_rows.append(row)
                    count += 1
            table['trList'] = new_rows
        return count

    # ─── 條件式列印 ───────────────────────────────────────────────────
    #
    # 真實 Odoo 報表的條件分佈（銷售訂單 20 個 t-if 實測）：
    #   單純「欄位有值」10、「欄位沒值」2、值比較 5、複合邏輯 2、呼叫 1
    # 一半是「有值才印」——那類不該要使用者設定條件，用自動收合處理。
    #
    # 三種機制，各有對應的 t-if 類型：
    #   ① 自動收合空段落        涵蓋「欄位有值才印」（規則 A：連靜態標籤一起消失）
    #   ② source='condition'   涵蓋值比較與複合邏輯（段落或表格列）
    #   ③ repeat 的 filter     涵蓋逐明細判斷（not line.display_type 之類）
    #
    # 刻意不做「任意區塊條件」與 t-else：元素串列是扁平的，跨段落的起訖標記在
    # 使用者編輯時極易被拆散，而且拆散後的結果無從察覺。要二擇一就放兩段互補
    # 條件，或做兩張範本由 doc.report 挑。

    _CONDITION_SOURCE = 'condition'

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

    def _element_condition_meta(self, element):
        meta = self._element_field_meta(element)
        if meta and (meta.get('source') or '') == self._CONDITION_SOURCE:
            return meta
        return None

    # ─── if / else 配對 ──────────────────────────────────────────────
    #
    # 兩個標記共用一個 groupId；else 那個不帶自己的表達式，求值時取同群 if
    # 的反值。這樣只有一處表達式要維護。
    #
    # 為什麼不讓使用者自己放兩段互補條件（這是改版前的建議作法）：
    #   改一個忘了改另一個時，結果是兩段都印或兩段都不印，而且不會報錯。
    #   二擇一的語意本來就該由程式保證互斥，不該靠使用者維護兩份真值表。
    #
    # 刻意不做 elif 鏈：三擇一以上在單據上極少見，而鏈結的中斷（使用者刪掉
    # 中間那段）會讓剩下的分支語意靜默改變。需要多擇一就用多張範本由
    # doc.report 依 lang / company 挑。

    def _condition_group_results(self, tree, record):
        """先求出每個條件群組的 if 結果：{groupId: bool}。

        同群有多個 if 標記時只採第一個——群組的定義是「一個條件、兩個分支」，
        第二個 if 是使用者複製貼上造成的，採第一個比較接近他的意圖。
        """
        results = {}
        for element in self._iter_elements(tree):
            meta = self._element_condition_meta(element)
            if not meta:
                continue
            gid = (meta.get('groupId') or '').strip()
            if not gid or (meta.get('role') or 'if') == 'else':
                continue
            if gid in results:
                continue
            results[gid] = self._eval_condition(
                meta.get('expression') or meta.get('path') or '', record,
            )
        return results

    def _condition_marker_result(self, meta, record, group_results):
        """單一條件標記要不要保留。"""
        gid = (meta.get('groupId') or '').strip()
        if gid and (meta.get('role') or 'if') == 'else':
            if gid not in group_results:
                # 配對的 if 被刪掉了 → 當成恆真。與 _eval_condition 的失敗
                # 策略一致：寧可多印也不要靜默少印。
                return True
            return not group_results[gid]
        if gid and gid in group_results:
            return group_results[gid]
        return self._eval_condition(
            meta.get('expression') or meta.get('path') or '', record,
        )

    # ─── 段落切分 ────────────────────────────────────────────────────
    #
    # 段落在扁平元素串列裡有可靠邊界：value == '\n' 的元素。
    # 這不是推測——_elements_to_html() 本身就是用它切段落的，所以「整段移除」
    # 與渲染結果一定一致。這也是為什麼條件與重複都只做到段落／列的粒度。

    def _iter_paragraph_spans(self, elements):
        """回傳 [(start, end_exclusive, nl_index or None), ...]。

        nl_index 是該段落結尾的換行元素位置；最後一段可能沒有換行。
        """
        spans = []
        start = 0
        for idx, el in enumerate(elements):
            if isinstance(el, dict) and (el.get('value') or '') == '\n':
                spans.append((start, idx, idx))
                start = idx + 1
        if start < len(elements):
            spans.append((start, len(elements), None))
        return spans

    def _drop_span(self, elements, span):
        """移除一個段落（含其結尾換行，否則會留下一條空行）。"""
        start, end, nl = span
        stop = (nl + 1) if nl is not None else end
        del elements[start:stop]

    # ─── ② 明確條件 ──────────────────────────────────────────────────

    def _apply_paragraph_conditions(self, tree, record, group_results=None):
        """處理段落層級的 condition 標記：條件為假整段移除，為真則移除標記本身。"""
        removed = 0
        if group_results is None:
            group_results = self._condition_group_results(tree, record)
        for elements in self._iter_element_lists(tree):
            # 由後往前刪，避免索引位移
            for span in reversed(self._iter_paragraph_spans(elements)):
                start, end, _nl = span
                markers = [
                    (i, self._element_condition_meta(elements[i]))
                    for i in range(start, end)
                ]
                markers = [(i, m) for i, m in markers if m]
                if not markers:
                    continue
                keep = all(
                    self._condition_marker_result(m, record, group_results)
                    for _i, m in markers
                )
                if not keep:
                    self._drop_span(elements, span)
                    removed += 1
                else:
                    # 條件成立：標記藥丸是宣告不是內容，不留在成品裡
                    for i, _m in reversed(markers):
                        del elements[i]
        return removed

    def _apply_row_conditions(self, tree, record, group_results=None):
        """處理表格列層級的 condition 標記。"""
        removed = 0
        if group_results is None:
            group_results = self._condition_group_results(tree, record)
        for table in self._iter_tables(tree):
            rows = table.get('trList') or []
            kept = []
            for row in rows:
                markers = []
                for cell in (row.get('tdList') or []):
                    if not isinstance(cell, dict):
                        continue
                    for el in (cell.get('value') or []):
                        m = self._element_condition_meta(el)
                        if m:
                            markers.append(m)
                if not markers:
                    kept.append(row)
                    continue
                keep = all(
                    self._condition_marker_result(m, record, group_results)
                    for m in markers
                )
                if not keep:
                    removed += 1
                    continue
                # 條件成立：清掉標記藥丸
                for cell in (row.get('tdList') or []):
                    if isinstance(cell, dict) and isinstance(cell.get('value'), list):
                        cell['value'] = [
                            el for el in cell['value']
                            if not self._element_condition_meta(el)
                        ]
                kept.append(row)
            if removed:
                table['trList'] = kept
        return removed

    # ─── ②b 欄條件 ───────────────────────────────────────────────────
    #
    # 對應原生報表的「折扣欄」那種寫法：一個 t-if 同時掛在 <th> 與每一列的
    # <td> 上（sale 的 display_discount，ir_actions_report_templates.xml:82,119）。
    #
    # 列條件與欄條件是對稱的兩件事：表格有 colgroup，欄邊界跟列一樣可靠。
    # 標記放在該欄的任一格（通常是表頭），後端依該格的起始欄索引把所有列的
    # 同一欄刪掉，colgroup 也一起處理——不然 canvas-editor 的欄寬會跟實際
    # 格數對不上，表格整個歪掉。
    #
    # 跑在列條件之後：列條件的標記可能就放在某一欄裡，先刪欄會讓那個列條件
    # 無聲消失。反過來（列先刪掉、連帶失去欄標記）則是「欄留著」——
    # 與條件求值失敗一致的「寧可多印」方向。

    _COLUMN_SOURCE = 'column'

    def _column_condition_markers(self, table):
        """回傳 [(欄索引, meta)]。欄索引以 colspan 累加算出。"""
        found = []
        for row in (table.get('trList') or []):
            if not isinstance(row, dict):
                continue
            col = 0
            for cell in (row.get('tdList') or []):
                if not isinstance(cell, dict):
                    continue
                span = max(1, int(cell.get('colspan') or 1))
                for el in (cell.get('value') or []):
                    meta = self._element_field_meta(el)
                    if meta and (meta.get('source') or '') == self._COLUMN_SOURCE:
                        found.append((col, meta))
                col += span
        return found

    def _strip_column_markers(self, table):
        """清掉表格內所有欄條件標記（宣告不是內容）。"""
        for row in (table.get('trList') or []):
            for cell in (row.get('tdList') or []):
                if not isinstance(cell, dict):
                    continue
                items = cell.get('value')
                if not isinstance(items, list):
                    continue
                cell['value'] = [
                    el for el in items
                    if ((self._element_field_meta(el) or {}).get('source') or '')
                    != self._COLUMN_SOURCE
                ]

    def _drop_column(self, table, target):
        """移除第 target 欄（含 colgroup）。

        跨欄的格子不刪，改成 colspan 減一——那一格橫跨多欄（例如小計列的
        「小計」標題），整格刪掉會讓該列少一欄，表格對不齊。
        """
        for row in (table.get('trList') or []):
            if not isinstance(row, dict):
                continue
            col = 0
            keep = []
            for cell in (row.get('tdList') or []):
                if not isinstance(cell, dict):
                    keep.append(cell)
                    continue
                span = max(1, int(cell.get('colspan') or 1))
                if col <= target < col + span:
                    if span > 1:
                        cell['colspan'] = span - 1
                        keep.append(cell)
                else:
                    keep.append(cell)
                col += span
            row['tdList'] = keep
        cg = table.get('colgroup')
        if isinstance(cg, list) and 0 <= target < len(cg):
            removed = cg.pop(target)
            # 被移除的寬度補給最後一欄，表格總寬維持不變——否則刪一欄
            # 整張表就縮一截，使用者會以為版面壞了
            if cg and isinstance(removed, dict) and removed.get('width'):
                last = cg[-1]
                if isinstance(last, dict) and last.get('width'):
                    last['width'] = last['width'] + removed['width']

    def _apply_column_conditions(self, tree, record, group_results=None):
        """處理欄層級的 condition 標記。"""
        removed = 0
        if group_results is None:
            group_results = self._condition_group_results(tree, record)
        for table in self._iter_tables(tree):
            markers = self._column_condition_markers(table)
            if not markers:
                continue
            drops = {
                col for col, meta in markers
                if not self._condition_marker_result(meta, record, group_results)
            }
            # 由右往左刪，避免索引位移
            for col in sorted(drops, reverse=True):
                self._drop_column(table, col)
                removed += 1
            self._strip_column_markers(table)
        return removed

    # ─── ① 自動收合空段落（規則 A）─────────────────────────────────────

    def _collapse_empty_paragraphs(self, tree):
        """段落內含藥丸且所有藥丸求值皆為空 → 整段移除（含靜態標籤）。

        規則 A（已定案）：「客戶統編：」這類標籤會連著一起消失，否則沒統編的
        單據上會留一個孤零零的標籤，那是最常見的難看問題。

        退出方式：任一藥丸的 meta 帶 keepEmpty=True 時該段不收合——
        給「重要靜態文字配一個可選藥丸」那種少數情況用。

        必須在純量求值之後跑：要有值才知道是不是空的。
        """
        removed = 0
        for elements in self._iter_element_lists(tree):
            for span in reversed(self._iter_paragraph_spans(elements)):
                start, end, _nl = span
                pills = []
                for i in range(start, end):
                    meta = self._element_field_meta(elements[i])
                    if meta:
                        pills.append((elements[i], meta))
                if not pills:
                    continue
                if any(m.get('keepEmpty') for _el, m in pills):
                    continue
                # 段落裡有表格就不收合。表格是獨立的區塊容器（條件區塊、
                # 巢狀的重複清單），它的內容跟同段落那幾顆藥丸沒有關係。
                # 段落邊界只認 value == '\n'，而表格元素的 value 是空字串，
                # 所以它會被算進同一段——實測到的後果是發票的分期清單被旁邊
                # 求值為空的「提前付款折扣」藥丸連帶整段刪掉。
                if any((elements[i].get('type') or '') == 'table'
                       for i in range(start, end)):
                    continue
                if all(not (el.get('value') or '').strip() for el, _m in pills):
                    self._drop_span(elements, span)
                    removed += 1
        return removed

    def _count_pending_pills(self, tree):
        """統計尚未凍結過的模型變數藥丸數。

        給 UI 用：匯出前要讓使用者知道「有 N 個變數還沒帶值」，
        而不是等他看到 PDF 上印著「客戶名稱」四個字才發現。
        """
        if not tree:
            return 0
        count = 0
        for element in self._iter_elements(tree):
            meta = self._element_field_meta(element)
            if meta and not meta.get('frozenAt'):
                count += 1
        return count

    def _flatten_content_json(self, tree):
        """把藥丸攤平成純文字元素（就地改寫並回傳 tree）。

        決策四（只輸出值）：丟掉 label 樣式與 extension，網底屬編輯輔助，
        不進正式文件。**不求值**——值應已由快照凍結在 value 裡。
        """
        if not tree:
            return tree
        for elements in self._iter_element_lists(tree):
            for idx, el in enumerate(elements):
                if not isinstance(el, dict) or el.get('type') != 'label':
                    continue
                # meta 要在丟掉 extension 之前讀——圖片與頁碼的攤平結果
                # 取決於它們的 source
                meta = self._element_field_meta(el) or {}
                src = (meta.get('source') or '').strip()
                plain = {k: v for k, v in el.items()
                         if k not in ('type', 'label', 'extension', 'labelId')}
                plain['value'] = el.get('value') or ''
                if src == self._IMAGE_SOURCE:
                    if (plain['value'] or '').startswith('data:'):
                        plain['type'] = 'image'
                        for key in ('width', 'height'):
                            if meta.get(key):
                                plain[key] = meta[key]
                    else:
                        # 沒有圖（欄位空的）→ 什麼都不印，不要留下 data URI 殘骸
                        plain['value'] = ''
                elif src == self._HTML_SOURCE:
                    # 區塊級：不能當行內塞進 <p> 裡，否則變成
                    # <p><p>…</p></p> 的非法嵌套
                    plain['type'] = 'htmlBlock'
                elif src == self._PAGE_SOURCE:
                    plain['type'] = 'pageField'
                    plain['pageKind'] = (
                        'count' if (meta.get('part') or '') == 'count'
                        else 'number'
                    )
                    plain['value'] = ''
                elements[idx] = plain
        return tree

    # ─── 元素樹 → HTML（伺服器端匯出鏈用）────────────────────────────
    #
    # 前端有 canvas-editor 的 getHTML()，伺服器端沒有。匯出改以 content_json
    # 為權威之後，這支轉換是必要的。涵蓋本模組實際會產生的元素類型；
    # 未知類型退回「輸出其 value 的逸出文字」——最壞情況是掉格式，不是掉內容。

    _ROW_FLEX_ALIGN = {
        'left': 'left', 'center': 'center', 'right': 'right',
        'alignment': 'justify', 'justify': 'justify',
    }

    def _element_style(self, el):
        parts = []
        if el.get('bold'):
            parts.append('font-weight:bold')
        if el.get('italic'):
            parts.append('font-style:italic')
        decos = []
        if el.get('underline'):
            decos.append('underline')
        if el.get('strikeout'):
            decos.append('line-through')
        if decos:
            parts.append('text-decoration:%s' % ' '.join(decos))
        if el.get('color'):
            parts.append('color:%s' % el['color'])
        if el.get('highlight'):
            parts.append('background-color:%s' % el['highlight'])
        if el.get('size'):
            # canvas-editor 的 element.size 單位是 px——它組 canvas font 字串時是
            # `${size}px`（見 lib 的 getElementFont）。這裡若寫 pt，匯出的每段文字
            # 都會比畫面上大 33%（16px → 16pt = 21.3px），而且不會有任何錯誤訊息。
            parts.append('font-size:%spx' % el['size'])
        if el.get('font'):
            parts.append("font-family:'%s'" % str(el['font']).replace("'", ''))
        return ';'.join(parts)

    def _inline_element_html(self, el):
        """單一行內元素 → HTML 片段。"""
        etype = el.get('type') or 'text'
        if etype == 'htmlBlock':
            # 正常會在 _elements_to_html 被攔成區塊級；走到這裡表示它被放進了
            # 超連結之類的子串列，原樣輸出總比印出逸出標籤好
            return el.get('value') or ''
        if etype == 'pageField':
            # 頁碼不必自己算也不必寫 JS：Odoo 的 wkhtmltopdf 管線會把抽出來的
            # div.footer 包進 web.minimal_layout（subst=True，見
            # ir_actions_report.py:441），那支範本內的 subst() JS 會填滿所有
            # class="page" / "topage" 的元素。輸出這個 span 就夠了。
            kind = el.get('pageKind') or 'number'
            return '<span class="%s"></span>' % (
                'topage' if kind == 'count' else 'page'
            )
        if etype == 'image':
            src = el.get('value') or ''
            if not src:
                return ''
            w = el.get('width')
            h = el.get('height')
            dims = ''
            if w:
                dims += ' width="%d"' % int(w)
            if h:
                dims += ' height="%d"' % int(h)
            return '<img src="%s"%s/>' % (html_mod.escape(src, quote=True), dims)
        if etype == 'separator':
            return '<hr/>'
        if etype == 'tab':
            return '&emsp;'
        if etype == 'checkbox':
            checked = ((el.get('checkbox') or {}).get('value'))
            return '☑' if checked else '☐'
        if etype == 'radio':
            checked = ((el.get('radio') or {}).get('value'))
            return '◉' if checked else '○'
        if etype == 'hyperlink':
            inner = ''.join(
                self._inline_element_html(c)
                for c in (el.get('valueList') or []) if isinstance(c, dict)
            ) or html_mod.escape(el.get('value') or '')
            url = html_mod.escape(el.get('url') or '', quote=True)
            return '<a href="%s">%s</a>' % (url, inner)

        text = html_mod.escape(el.get('value') or '')
        if '\n' in text:
            # 伺服器端求值會產生多行值（format_address、多行文字欄位）。
            # canvas-editor 本身不把換行放進元素的 value 裡（它用獨立的 '\n'
            # 元素），而「值剛好等於 '\n'」的段落標記在 _elements_to_html 就先
            # 攔掉了——所以走到這裡的換行一定是值內部的，轉成 <br/> 沒有歧義。
            # 不轉的話多行地址會塌成一行，而 HTML 裡看起來只是少了換行。
            text = text.replace('\n', '<br/>')
        if not text:
            return ''
        style = self._element_style(el)
        if etype == 'label':
            # 理論上匯出前已攤平；萬一漏了也只輸出文字，不帶網底（決策四）
            return text
        return '<span style="%s">%s</span>' % (style, text) if style else text

    def _table_to_html(self, el):
        rows = []
        for row in (el.get('trList') or []):
            if not isinstance(row, dict):
                continue
            cells = []
            for cell in (row.get('tdList') or []):
                if not isinstance(cell, dict):
                    continue
                attrs = ''
                if (cell.get('colspan') or 1) > 1:
                    attrs += ' colspan="%d"' % int(cell['colspan'])
                if (cell.get('rowspan') or 1) > 1:
                    attrs += ' rowspan="%d"' % int(cell['rowspan'])
                cells.append('<td%s>%s</td>' % (
                    attrs, self._elements_to_html(cell.get('value') or []),
                ))
            if cells:
                rows.append('<tr>%s</tr>' % ''.join(cells))
        if not rows:
            return ''
        # 區塊容器不是真的表格，不可印框線。class 讓四條輸出路徑各自關掉邊框，
        # 而不是在這裡寫 inline style——inline style 進不了 python-docx 的表格樣式。
        cls = ' class="doc-block"' if self._element_block_kind(el) else ''
        return '<table%s>%s</table>' % (cls, ''.join(rows))

    def _elements_to_html(self, elements):
        """元素串列 → HTML。

        canvas-editor 的元素串列是扁平的，用 value == '\\n' 標示換行；
        換行元素身上的 rowFlex 決定該段落的對齊。
        """
        out = []
        buf = []

        def _flush(row_el=None):
            if not buf:
                # 空段落也要保留，否則多個空行會被吃掉、版面走樣
                out.append('<p><br/></p>')
                return
            align = self._ROW_FLEX_ALIGN.get((row_el or {}).get('rowFlex') or '')
            style = ' style="text-align:%s"' % align if align else ''
            out.append('<p%s>%s</p>' % (style, ''.join(buf)))
            buf.clear()

        for el in (elements or []):
            if not isinstance(el, dict):
                continue
            etype = el.get('type') or 'text'
            if etype == 'table':
                if buf:
                    _flush()
                out.append(self._table_to_html(el))
                continue
            if etype == 'htmlBlock':
                # 已在求值時消毒過（_html_field_value）。這裡原樣輸出，
                # 與表格同樣是區塊級：先把行內緩衝沖掉再放。
                if buf:
                    _flush()
                out.append(el.get('value') or '')
                continue
            if etype == 'pageBreak':
                if buf:
                    _flush()
                out.append('<div class="doc-page-break"></div>')
                continue
            if (el.get('value') or '') == '\n':
                _flush(el)
                continue
            buf.append(self._inline_element_html(el))
        if buf:
            _flush()
        return ''.join(out)

    def _content_json_to_html(self, tree, zone='main'):
        """content_json 的指定區域 → HTML。"""
        if isinstance(tree, dict):
            elements = tree.get(zone)
        elif isinstance(tree, list) and zone == 'main':
            elements = tree
        else:
            elements = None
        return self._elements_to_html(elements or [])

    def _parse_content_json(self, raw):
        """content_json 欄位（字串或已解析物件）→ dict/list；失敗回 None。"""
        if not raw:
            return None
        if isinstance(raw, (dict, list)):
            return raw
        try:
            return json.loads(raw)
        except Exception:
            return None

    # ─── HTML → DOCX（doc.document 與 doc.output 共用）────────────────
    #
    # 原本只存在 doc.document._generate_docx_via_python 裡，綁在它的欄位上。
    # 報表引擎的輸出紀錄也要能匯出 DOCX（定案決策四：定位為「匯出去編輯」
    # 的便利功能），所以抽到 mixin、參數化。
    # doc.document 那支保留為對外介面，內部委派到這裡。

    _DOCX_PAGE_SIZES_MM = {
        'A4': (210, 297), 'A3': (297, 420), 'A5': (148, 210),
        'letter': (216, 279), 'legal': (216, 356),
    }

    def _docx_fill_zone(self, zone, content, lhtml, add_runs, apply_align):
        """把頁首／頁尾的 HTML（或純文字）填進 DOCX 的 header/footer。"""
        if not content or not content.strip():
            return
        text = content.strip()
        if '<' not in text:
            zone.paragraphs[0].text = text
            return
        try:
            node = lhtml.fromstring('<div>%s</div>' % text)
        except Exception:
            zone.paragraphs[0].text = text
            return
        blocks = node.xpath('./p | ./div') or [node]
        for idx, blk in enumerate(blocks):
            para = zone.paragraphs[0] if idx == 0 else zone.add_paragraph()
            apply_align(para, blk)
            add_runs(para, blk)

    def _docx_bytes_from_html(self, body_html, page_format='A4', margins=None,
                              header_text='', footer_text=''):
        """body HTML → DOCX bytes。

        margins：{'top','bottom','left','right'} 單位 px（與編輯器一致）。
        缺 python-docx 時 raise UserError 並指名該裝的 pip 套件——
        它是選用相依（見 __manifest__.py），核心功能不需要。
        """
        try:
            from docx import Document
            from docx.shared import Mm
            from lxml import html as lhtml
        except ImportError as e:
            raise UserError(
                f'無法匯出 DOCX：{e}\n'
                '請安裝 python-docx：pip install python-docx'
            )
        from .doc_document import (
            _add_runs_from_node, _apply_paragraph_align, _html_node_to_docx,
        )

        margins = margins or {}
        px_to_mm = 0.264583  # 96dpi：1px = 0.264583mm
        w_mm, h_mm = self._DOCX_PAGE_SIZES_MM.get(page_format, (210, 297))

        docx_doc = Document()
        section = docx_doc.sections[0]
        section.page_width = Mm(w_mm)
        section.page_height = Mm(h_mm)
        section.top_margin = Mm(margins.get('top', 96) * px_to_mm)
        section.bottom_margin = Mm(margins.get('bottom', 96) * px_to_mm)
        section.left_margin = Mm(margins.get('left', 96) * px_to_mm)
        section.right_margin = Mm(margins.get('right', 96) * px_to_mm)

        try:
            tree = lhtml.fromstring('<div>%s</div>' % (body_html or ''))
            _html_node_to_docx(docx_doc, tree)
        except Exception:
            # 解析失敗時退回純文字——掉格式比整份匯不出來好
            try:
                text = lhtml.fromstring(
                    '<div>%s</div>' % (body_html or '')
                ).text_content()
            except Exception:
                text = ''
            docx_doc.add_paragraph(text)

        # 頁首頁尾收 HTML 而不是純文字：頁碼在 DOCX 裡是 field code
        # （<span class="page"> → PAGE），用 paragraphs[0].text 設值會把它
        # 變成字面文字「頁碼」，而且不會有任何錯誤訊息。
        self._docx_fill_zone(section.header, header_text, lhtml,
                             _add_runs_from_node, _apply_paragraph_align)
        self._docx_fill_zone(section.footer, footer_text, lhtml,
                             _add_runs_from_node, _apply_paragraph_align)

        buf = io.BytesIO()
        docx_doc.save(buf)
        return buf.getvalue()
