"""範本設計的路由：欄位清單、選適用模型、待填欄位與簽約人、範本預覽。
"""
import base64
import io
import json
import logging
import re
import shutil
import subprocess
import tempfile
import os
import zipfile
import html as html_mod
from lxml import etree
from odoo import http
from odoo.exceptions import MissingError, UserError
from odoo.http import request

from ..models.doc_zip_guard import (
    assert_input_size,
    inspect_zip_safe,
    ZipBombError,
)

_logger = logging.getLogger(__name__)

# ─── DOCX XML 命名空間 ────────────────────────────────────────────────────────
_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_XML = "http://www.w3.org/XML/1998/namespace"

# DOCX 段落樣式名稱 → HTML 標籤對應表（大小寫不敏感）
_HEADING_STYLES = {
    'heading1': 'h1', 'heading 1': 'h1',
    'heading2': 'h2', 'heading 2': 'h2',
    'heading3': 'h3', 'heading 3': 'h3',
    'heading4': 'h4', 'heading 4': 'h4',
    'heading5': 'h5', 'heading 5': 'h5',
    'heading6': 'h6', 'heading 6': 'h6',
}
from .doc_controller_base import DocControllerBase
from .doc_convert import (
    _ts_parse_docx_to_elements,
    _docx_to_html_with_format,
    _w_paragraph_to_html,
    _w_runs_to_html,
    _w_run_to_html,
    _w_table_to_html,
    _odt_to_html,
    _lo_convert_to_html,
    _extract_page_margins,
    _lo_postprocess,
    _convert_ins_to_jinja,
)


class DocTemplateController(DocControllerBase, http.Controller):

    @http.route('/dobtor_doc/fields', type='json', auth='user', methods=['POST'])
    def get_fields(self, model_name, doc_id=None, **kw):
        """取得指定模型的可用欄位清單。"""
        mixin = request.env['doc.render.mixin']
        try:
            return mixin.get_available_fields(model_name)
        except Exception as e:
            return {'error': str(e)}

    @http.route('/dobtor_doc/models', type='json', auth='user', methods=['POST'])
    def list_models(self, query=None, limit=40, **kw):
        """可當「適用模型」的模型清單（給編輯器裡的選模型用）。

        過濾掉 transient 與 abstract：範本要對著一筆**存得住的**記錄取值，
        精靈與抽象模型沒有記錄可指。
        也過濾掉使用者讀不到的——列出來卻一碰就 AccessError 更糟。
        """
        domain = [('transient', '=', False), ('abstract', '=', False)]
        if query:
            domain += ['|', ('name', 'ilike', query), ('model', 'ilike', query)]
        out = []
        for rec in request.env['ir.model'].search(domain, limit=int(limit) * 3,
                                                  order='name'):
            try:
                request.env[rec.model].check_access('read')
            except Exception:
                continue
            out.append({'id': rec.id, 'model': rec.model, 'name': rec.name})
            if len(out) >= int(limit):
                break
        return out

    @http.route('/dobtor_doc/set_model', type='json', auth='user', methods=['POST'])
    def set_edit_target_model(self, model_id, doc_id=None, template_id=None, **kw):
        """設定範本的「適用模型」／文件的「關聯模型」。

        為什麼要有這支：沒有它，一張新範本就沒有欄位可拖，而編輯器左欄只能
        叫使用者「請先設定適用模型」——也就是進編輯器第一件事是離開編輯器。
        那個缺口讓範本清單的「新增」沒辦法比照文件直接進編輯器。

        要 write 權限（改的是範本的設定，不是內容）。
        """
        record, kind = self._resolve_edit_target(
            doc_id=doc_id, template_id=template_id, access='write')
        if kind == 'output':
            raise UserError('輸出紀錄不可編輯。')
        model = request.env['ir.model'].browse(int(model_id)).exists()
        if not model:
            raise UserError('找不到該模型。')
        if model.transient or model.abstract:
            raise UserError('精靈與抽象模型沒有記錄可指，不能當適用模型。')
        request.env[model.model].check_access('read')
        record.model_id = model.id
        return {'success': True, 'model': model.model, 'name': model.name}

    @http.route('/dobtor_doc/template_fields/load', type='json', auth='user', methods=['POST'])
    def template_fields_load(self, doc_id=None, template_id=None, **kw):
        """載入編輯對象對應 template 的所有 signers + fields。

        雙入口（Phase 1）：文件模式傳 doc_id 由 template_id 推導；
        範本模式直接傳 template_id。

        回傳：
            {
                'has_template': bool,
                'template_id': int | None,
                'signers': [{id, name, color, sequence, field_count}, ...],
                'fields':  [{id, signer_id, field_type, page_no, required,
                             placeholder_text, font_size, odoo_field_name,
                             width, height, pos_x, pos_y}, ...]
            }
        """
        template, err = self._resolve_template(doc_id, template_id, 'read')
        if err or not template:
            return {'has_template': False, 'template_id': None, 'signers': [], 'fields': []}
        signers = template.signer_ids.read([
            'id', 'name', 'color', 'sequence', 'field_count',
        ])
        fields_list = template.field_ids.read([
            'id', 'signer_id', 'field_type', 'page_no', 'required',
            'placeholder_text', 'font_size', 'odoo_field_name',
            'width', 'height', 'pos_x', 'pos_y',
            'layout_mode',  # Sprint D
            # 互動式 control 選項設定
            'option_source', 'selection_field_name', 'input_able', 'is_multi_select',
        ])
        # signer_id 從 Odoo Many2one [id, display_name] tuple 簡化為純 id
        # 並附上自訂選項清單（option_ids → options）供前端組 valueSets
        field_recs = {rec.id: rec for rec in template.field_ids}
        for f in fields_list:
            if f.get('signer_id'):
                f['signer_id'] = f['signer_id'][0]
            rec = field_recs.get(f['id'])
            f['options'] = [
                {'value': o.value, 'code': o.code or o.value}
                for o in rec.option_ids.sorted('sequence')
            ] if rec else []
        return {
            'has_template': True,
            'template_id': template.id,
            'signers': signers,
            'fields': fields_list,
        }

    @http.route('/dobtor_doc/template_fields/options', type='json', auth='user', methods=['POST'])
    def template_field_options(self, doc_id=None, template_id=None, field_id=None, **kw):
        """回傳互動式 control 的選項設定（valueSets + 預設值）。

        給 field_id → 回單一欄位 spec；不給 → 回範本所有欄位的 spec（批次，
        供「開文件自動升級」一次拿齊，免逐個 round-trip）。

        範本模式沒有綁定 record（設計期本來就沒有資料可帶），
        record=None 時 _field_control_spec 不會算 current_code，
        chip 開啟時就是空選、由使用者自行挑——這是正確行為，不是缺陷。
        """
        target, kind = self._resolve_edit_target(doc_id, template_id, access='read')
        if kind == 'template':
            template = target
            record = None
            aliases = template.field_aliases or {}
        else:
            template = target.template_id
            record = target._resolve_bound_record()
            aliases = target._collect_field_aliases() or {}
        if not template:
            # 沒有範本就沒有欄位可查。舊寫法是 `template and field.template_id != template`，
            # template 為空時整個條件恆假 → 任何 field_id 都會被放行、回傳它的 spec。
            return {'success': False, 'error': '此文件未關聯範本'}
        FieldModel = request.env['doc.template.field']
        if field_id:
            field = FieldModel.browse(int(field_id))
            if not field.exists() or field.template_id != template:
                return {'success': False, 'error': '欄位不存在或不屬於此範本'}
            return {'success': True, 'spec': self._field_control_spec(field, record, aliases)}
        specs = [
            self._field_control_spec(field, record, aliases)
            for field in template.field_ids
        ]
        return {'success': True, 'specs': specs}

    @http.route('/dobtor_doc/template_fields/save_field', type='json', auth='user', methods=['POST'])
    def template_fields_save_field(self, doc_id=None, template_id=None, field=None, **kw):
        """新建或更新單個範本欄位。

        field 參數：
            {
                'id':            int | None  # None = create
                'signer_id':     int (required)
                'field_type':    str
                'page_no':       int
                'required':      bool
                'placeholder_text': str
                'font_size':     int
                'odoo_field_name': str
                'width', 'height', 'pos_x', 'pos_y': float
            }

        回傳：{'success': True, 'id': field_id, 'signer_field_counts': {signer_id: count}}
            或 {'success': False, 'error': str}
        """
        if not field:
            return {'success': False, 'error': 'missing field parameter'}
        template, err = self._resolve_template(doc_id, template_id, 'write')
        if err:
            return err
        # 允許的欄位白名單（防止前端塞奇怪 key 進來）
        ALLOWED = {
            'signer_id', 'field_type', 'page_no', 'required',
            'placeholder_text', 'font_size', 'odoo_field_name',
            'width', 'height', 'pos_x', 'pos_y',
            'layout_mode',  # Sprint D
            # 互動式 control 選項設定
            'option_source', 'selection_field_name', 'input_able', 'is_multi_select',
        }
        vals = {k: v for k, v in field.items() if k in ALLOWED}
        FieldModel = request.env['doc.template.field']
        field_id = field.get('id')
        try:
            if field_id:
                rec = FieldModel.browse(int(field_id))
                rec.check_access('write')
                # 確保不能透過 update 把欄位搬到其他範本
                if rec.template_id != template:
                    return {'success': False, 'error': '欄位不屬於此範本'}
                rec.write(vals)
            else:
                vals['template_id'] = template.id
                rec = FieldModel.create(vals)
                field_id = rec.id
        except Exception as e:
            return {'success': False, 'error': str(e)}

        # 回傳每位簽約人最新的欄位計數（前端 chip 計數即時更新）
        signer_counts = {}
        for signer in template.signer_ids:
            signer_counts[signer.id] = len(signer.field_ids)

        return {
            'success': True,
            'id': field_id,
            'signer_field_counts': signer_counts,
            'field_count': len(template.field_ids),
        }

    @http.route('/dobtor_doc/template_fields/delete_field', type='json', auth='user', methods=['POST'])
    def template_fields_delete_field(self, doc_id=None, field_id=None, template_id=None, **kw):
        """刪除單個範本欄位。

        回傳：{'success': True, 'signer_field_counts': {...}, 'field_count': int}
            或 {'success': False, 'error': str}
        """
        if not field_id:
            return {'success': False, 'error': 'missing field_id'}
        template, err = self._resolve_template(doc_id, template_id, 'write')
        if err:
            return err
        field = request.env['doc.template.field'].browse(int(field_id))
        if not field.exists():
            return {'success': False, 'error': 'field not found'}
        if field.template_id != template:
            return {'success': False, 'error': '欄位不屬於此範本'}
        try:
            field.check_access('unlink')
            field.unlink()
        except Exception as e:
            return {'success': False, 'error': str(e)}

        signer_counts = {}
        for signer in template.signer_ids:
            signer_counts[signer.id] = len(signer.field_ids)
        return {
            'success': True,
            'signer_field_counts': signer_counts,
            'field_count': len(template.field_ids),
        }

    @http.route('/dobtor_doc/template_fields/save_signer', type='json', auth='user', methods=['POST'])
    def template_fields_save_signer(self, doc_id=None, template_id=None, signer=None, **kw):
        """新建或更新範本簽約人（讓 Phase 2.1 UI 也能在文件編輯器加 signer）。

        signer 參數：
            {'id': int | None, 'name': str, 'color': int, 'sequence': int}
        """
        if not signer:
            return {'success': False, 'error': 'missing signer parameter'}
        template, err = self._resolve_template(doc_id, template_id, 'write')
        if err:
            return err
        ALLOWED = {'name', 'color', 'sequence'}
        vals = {k: v for k, v in signer.items() if k in ALLOWED}
        SignerModel = request.env['doc.template.signer']
        signer_id = signer.get('id')
        try:
            if signer_id:
                rec = SignerModel.browse(int(signer_id))
                rec.check_access('write')
                if rec.template_id != template:
                    return {'success': False, 'error': '簽約人不屬於此範本'}
                rec.write(vals)
            else:
                vals['template_id'] = template.id
                rec = SignerModel.create(vals)
                signer_id = rec.id
        except Exception as e:
            return {'success': False, 'error': str(e)}
        return {'success': True, 'id': signer_id}

    @http.route('/dobtor_doc/template_preview', type='json', auth='user', methods=['POST'])
    def template_preview(self, doc_id, context=None, **kw):
        """以 user 提供的 context 渲染 doc.content_html，回傳完整 HTML 頁面供新分頁顯示。

        參數：
            doc_id：doc.document id
            context：{變數名稱: 值} dict（對應 content_html 中的 {{ var }}）

        回傳：
            { success: bool, html: str, warnings: list[str], error?: str }
        """
        try:
            doc = self._require_document(doc_id, 'read')
        except Exception as e:
            return {'success': False, 'error': f'文件存取失敗：{e}'}

        content_html = doc.get_content_html() or '<p><em>（文件無內容）</em></p>'
        warnings = []
        ctx = context if isinstance(context, dict) else {}

        # 用 doc.render.mixin 的沙箱建構點渲染。
        # 補遺五：此處原本自己 new 裸 SandboxedEnvironment（註解還宣稱「與
        # _render_template 同樣的 sandbox」，實際上不是），ORM 提權黑名單失效，
        # 而且 render 時把 doc 本身當 object 傳進去，等於直接遞出 recordset。
        rendered_body = content_html
        if ctx:
            try:
                from jinja2 import StrictUndefined, UndefinedError
                env = doc._get_sandbox_env(doc, undefined=StrictUndefined)
                tpl = env.from_string(content_html)
                try:
                    rendered_body = tpl.render(**ctx, object=doc, user=request.env.user)
                except UndefinedError as ue:
                    warnings.append(f'缺少變數：{ue}（已用空白替代）')
                    env_lax = doc._get_sandbox_env(doc)
                    rendered_body = env_lax.from_string(content_html).render(
                        **ctx, object=doc, user=request.env.user
                    )
            except Exception as e:
                warnings.append(f'渲染警告：{e}')
                rendered_body = content_html

        # 包成完整 HTML 頁面（含列印樣式）
        page_format = doc.page_format or 'A4'
        doc_name = html_mod.escape(doc.name or '未命名文件')
        # html_mod.escape on warnings (avoid XSS via warning text)
        warnings_html = ''.join(
            f'<li>{html_mod.escape(w)}</li>' for w in warnings
        )
        warnings_block = (
            f'<aside class="preview-warnings" role="alert">'
            f'<strong>預覽提示</strong><ul>{warnings_html}</ul></aside>'
        ) if warnings else ''

        html = (
            '<!DOCTYPE html>'
            '<html lang="zh-Hant">'
            '<head>'
            '<meta charset="utf-8"/>'
            f'<title>預覽：{doc_name}</title>'
            '<style>'
            'body{font-family:"Microsoft JhengHei","PingFang TC",sans-serif;'
            'margin:0;padding:24px;background:#f3f4f6;color:#111827;}'
            '.preview-page{background:#fff;max-width:794px;margin:0 auto 16px;'
            'padding:48px 56px;box-shadow:0 1px 3px rgba(0,0,0,.1);'
            'border-radius:4px;line-height:1.6;}'
            '.preview-header{max-width:794px;margin:0 auto 16px;'
            'display:flex;justify-content:space-between;align-items:center;'
            'color:#4b5563;font-size:14px;}'
            '.preview-warnings{max-width:794px;margin:0 auto 16px;'
            'padding:12px 16px;background:#fef3c7;border-left:4px solid #f59e0b;'
            'border-radius:4px;color:#92400e;}'
            '.preview-warnings ul{margin:8px 0 0;padding-left:20px;}'
            '@media print{body{background:#fff;padding:0;}'
            '.preview-page{box-shadow:none;border:none;margin:0;}'
            '.preview-header,.preview-warnings{display:none;}}'
            '</style>'
            '</head>'
            '<body>'
            '<div class="preview-header">'
            f'<span>{doc_name}</span><span>{page_format} ｜ 預覽（非正式輸出）</span>'
            '</div>'
            f'{warnings_block}'
            f'<article class="preview-page">{rendered_body}</article>'
            '</body></html>'
        )
        return {'success': True, 'html': html, 'warnings': warnings}

    @http.route('/dobtor_doc/template_requests/list', type='json', auth='user', methods=['POST'])
    def template_requests_list(self, doc_id, **kw):
        """列出此文件範本的填寫請求清單。

        目前 doc.fill.request model 尚未實作；先回傳空陣列作為殼，
        前端 Sprint A 的「請求」分頁能正常顯示「目前沒有填寫請求」空態。
        未來接上 model 後改成 search_read。
        """
        try:
            doc = self._require_document(doc_id, 'read')
        except Exception as e:
            return {'success': False, 'error': f'文件存取失敗：{e}', 'requests': []}

        FillRequest = request.env.get('doc.fill.request')
        if FillRequest is None:
            return {'success': True, 'requests': []}

        # model 已實作時走真實 search_read
        try:
            records = FillRequest.sudo().search_read(
                domain=[('doc_id', '=', doc.id)],
                fields=['id', 'recipient_name', 'state', 'sent_at', 'completed_at'],
                order='sent_at desc',
            )
            STATE_LABELS = {
                'draft': '草稿',
                'sent': '已送出',
                'opened': '已開啟',
                'completed': '已完成',
                'expired': '已過期',
            }
            for r in records:
                r['state_label'] = STATE_LABELS.get(r.get('state'), r.get('state') or '—')
                r['sent_at'] = (r.get('sent_at') and str(r['sent_at'])) or None
                r['completed_at'] = (r.get('completed_at') and str(r['completed_at'])) or None
            return {'success': True, 'requests': records}
        except Exception as e:
            _logger.warning('template_requests_list fallback: %s', e)
            return {'success': True, 'requests': []}
