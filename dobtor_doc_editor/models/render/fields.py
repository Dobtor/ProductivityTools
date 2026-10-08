"""RenderFields — 欄位清單與別名（alias 退場中）。

給編輯器左欄用的欄位清單，以及 L2-v2 的 alias 對映。

alias 機制退場中（視圖已移除「新增對映」入口），這裡保留的是讀取與清除
路徑，給既有資料用。新範本一律用藥丸。
"""
import re


from odoo import api
from odoo.exceptions import UserError, AccessError


# 中文 token 標記符號。前後綴用《》（U+300A / U+300B），降低與正文衝突機率。
# 若 token 內含 》 會被 _ALIAS_PATTERN 提前終止，這是刻意行為（避免巢狀解析歧義）。
_ALIAS_PATTERN = re.compile(r'《([^》]+)》')

# 純變數名 Jinja 表達式（不含 object. 前綴的舊式變數）。
# 例：{{ project_name }} 會被當作可替換 token；{{ object.partner_id.name }} 不會（保留給 Jinja2）。
_VAR_NAME_RE = re.compile(r'^[A-Za-z_][\w]*$')
_JINJA_VARNAME_PATTERN = re.compile(r'\{\{\s*([A-Za-z_][\w]*)\s*\}\}')


class RenderFields:

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
