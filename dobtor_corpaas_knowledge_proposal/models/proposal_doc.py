# -*- coding: utf-8 -*-
"""服務建議書的 Word／PDF 輸出：交給 dobtor_doc_editor。

★ 文件是版本資料的**投影**，不是反過來：內容改在版本的資料表，重新輸出就得到新版文件。
★ 已送出的版本 `data.*` 讀**凍結快照**（草稿才讀現場資料）—— 所以送出之後不論能力文案、
  工時範本、牌價怎麼變，同一版重新輸出得到的永遠是送出時的那份文件。
★ 範本綁在提案**既有的列印動作**上（`doc.report`），使用者按的還是原本的「列印」；
  停用那筆綁定就退回原本的 QWeb 報表，兩者共存。
☠️ 填值走藥丸與 `doc_report_values()`，不用 `_doc_render_context()` ——
   doc_editor 的文件已註明那個機制「從來沒生效」並已刪除；ChienYi 的整合先例還在用它，
   不要照抄。
☠️ DOCX 是 doc_editor 的「匯出去編輯」便利功能，不是正式輸出（經 python-docx 轉換，
   無法保證與畫面一致）；正式交給客戶的請用 PDF。
"""
import base64
import json
import logging

from odoo import _, api, models
from odoo.exceptions import UserError

from odoo.addons.dobtor_corpaas_knowledge.models.catalog import COLORS

from ..services import doc_template, docx_polish
from .proposal import PRICING_MODELS
from .effort import ACTIVITIES

_logger = logging.getLogger(__name__)

TEMPLATE_XMLID = 'dobtor_corpaas_knowledge_proposal.doc_template_proposal'
BINDING_XMLID = 'dobtor_corpaas_knowledge_proposal.doc_report_proposal'
REPORT_XMLID = 'dobtor_corpaas_knowledge_proposal.action_report_kb_proposal'

#: 章節出現的順序；編號只給「有資料」的章節。
CHAPTERS = ['changes', 'overview', 'solution', 'matrix', 'migration', 'scope', 'budget',
            'phases', 'payment', 'obligations', 'clauses', 'benefits']
NUMERALS = ['一', '二', '三', '四', '五', '六', '七', '八', '九', '十', '十一', '十二']

SCOPE_KINDS = {'in': '涵蓋範圍', 'out': '不涵蓋（另行估列）', 'excluded': '排除（不建議開發）',
               'optional': '選配（另行報價）'}
OBLIGATION_KINDS = {'client': '客戶須提供／配合', 'assumption': '專案假設',
                    'precondition': '前提條件'}
DRIVER_LABELS = [('companies', '公司數'), ('users', '使用者數'), ('roles', '角色數'),
                 ('integrations', '串接數'), ('sessions', '訓練場次')]


class KnowledgeProposalDoc(models.Model):
    _inherit = 'corpaas.knowledge.proposal'

    # ------------------------------------------------------------------
    # 範本與綁定的安裝
    # ------------------------------------------------------------------
    @api.model
    def _ensure_doc_template(self, force=False):
        """建立（或重建）文件範本與它在列印動作上的綁定。回範本。

        ★ 冪等：已經有就不動（客戶在編輯器裡調過版面，升級不能蓋掉）；
          `force=True` 才用出貨版面重建。
        ★ 由 post_init_hook（新裝）與 2.0 的 migration（升級）呼叫，不放在 XML 資料檔：
          content_json 是程式產生的，不是人手寫的 JSON。
        """
        env = self.env
        Template = env['doc.template'].sudo()
        tmpl = env.ref(TEMPLATE_XMLID, raise_if_not_found=False)
        vals = {
            'name': '服務建議書（規格書）',
            'model_id': env['ir.model']._get_id(self._name),
            'role': 'content',
            'content_json': doc_template.build_json(),
            # 邊距取自既有規格書（約 0.87 吋）；紙張用 A4（台灣慣用，既有檔案是 Letter 的預設值）
            'page_format': 'A4',
            'margin_left': 83, 'margin_right': 83, 'margin_top': 76, 'margin_bottom': 76,
        }
        if tmpl and force:
            tmpl.sudo().write(vals)
        elif not tmpl:
            tmpl = Template.create(vals)
            env['ir.model.data']._update_xmlids([{
                'xml_id': TEMPLATE_XMLID, 'record': tmpl, 'noupdate': True}])
        report = env.ref(REPORT_XMLID, raise_if_not_found=False)
        binding = env.ref(BINDING_XMLID, raise_if_not_found=False)
        if report and not binding:
            binding = env['doc.report'].sudo().create({
                'name': '服務建議書（規格書）',
                'template_id': tmpl.id, 'report_id': report.id,
                # 這是要寄給客戶的文件：每次輸出都留紀錄，事後查得到當時給了什麼
                'persist_output': True,
                'filename_pattern': "{{ object.partner_id.name }}_服務建議書_{{ object.version_no }}",
            })
            env['ir.model.data']._update_xmlids([{
                'xml_id': BINDING_XMLID, 'record': binding, 'noupdate': True}])
        return tmpl

    # ------------------------------------------------------------------
    # 下載 Word
    # ------------------------------------------------------------------
    def action_download_word(self):
        """輸出這個版本的 Word 檔。

        ☠️ DOCX 是 doc_editor 的「匯出去編輯」便利功能，不是正式輸出（轉換無法保證與畫面一致）；
           正式交給客戶請用 PDF（列印按鈕）。這裡額外補上表頭與交錯底色（見 docx_polish），
           讓版面接近既有的報價規格書。
        ★ 每次下載都留一筆輸出紀錄（doc.output），事後查得到當時給了什麼。
        """
        self.ensure_one()
        binding = self.env.ref(BINDING_XMLID, raise_if_not_found=False)
        if not binding:
            raise UserError(_('服務建議書的文件範本還沒安裝；請聯絡管理者。'))
        _html, trees = binding._build_report_html(self)
        output = self.env['doc.output']._record_output(
            binding, self, trees[self.id], output_format='docx')
        action = output.action_download_docx()
        attachment = self.env['ir.attachment'].sudo().search(
            [('res_model', '=', 'doc.output'), ('res_id', '=', output.id)],
            order='id desc', limit=1)
        if attachment:
            vals = {}
            name = self.env['doc.render.mixin']._render_filename(binding.filename_pattern, self)
            if name:
                vals['name'] = '%s.docx' % name       # 預設檔名含「/」（PRO/2026/0001）
            try:
                vals['datas'] = base64.b64encode(
                    docx_polish.polish(base64.b64decode(attachment.datas)))
            except Exception:  # noqa: BLE001 — 後處理失敗就交出未處理的檔案，不擋下載
                _logger.warning('建議書 %s 的 Word 後處理失敗，改交未處理的檔案', self.name,
                                exc_info=True)
            if vals:
                attachment.write(vals)
        return action

    # ------------------------------------------------------------------
    # 範本讀的 data.*
    # ------------------------------------------------------------------
    def _doc_snapshot(self):
        """已送出的版本讀凍結快照；草稿讀現場資料。"""
        self.ensure_one()
        if self.state != 'draft' and self.snapshot_json:
            try:
                return json.loads(self.snapshot_json)
            except ValueError:
                _logger.warning('建議書 %s 的快照壞了，改讀現場資料', self.name)
        return self._snapshot()

    def doc_report_values(self):
        """範本裡用 `data.<鍵>`。見 services/doc_template.py 的欄位對照。"""
        self.ensure_one()
        snap = self._doc_snapshot()
        money = self._money
        color_labels = dict(COLORS)
        prices = snap.get('prices') or {}
        pricing = snap.get('pricing') or {}
        time_budget = pricing.get('model') == 'time_budget'
        version = snap.get('version') or {}
        hpd = self._settings()['hours_per_day'] or 8.0

        changes = [{'ref_no': c.get('ref_no') or str(i), 'demand': c.get('demand') or '',
                    'handling': c.get('handling') or '', 'chapter': c.get('chapter') or ''}
                   for i, c in enumerate(snap.get('changes') or [], start=1)]

        drivers = snap.get('drivers') or {}
        driver_rows = [{'name': label, 'value': drivers.get(key)}
                       for key, label in DRIVER_LABELS if drivers.get(key)]
        narrative = '\n'.join(snap.get('narrative') or [])

        caps = [{'name': c.get('name') or '', 'pain': c.get('pain') or '',
                 'outcome': c.get('outcome') or '',
                 'color_label': color_labels.get(c.get('color'), c.get('color') or '')}
                for c in snap.get('capabilities') or []]

        matrix = []
        for pain in snap.get('pains') or []:
            maps = [m for m in pain.get('mappings') or [] if m.get('confirmed')] \
                or (pain.get('mappings') or [])
            how_default = ''
            if not maps:
                matrix.append({'description': pain.get('description') or '', 'how': how_default,
                               'color_label': ''})
            for m in maps:
                how = m.get('note') or ''
                if m.get('capability'):
                    how = ('%s：%s' % (m['capability'], how)) if how else m['capability']
                matrix.append({'description': pain.get('description') or '', 'how': how,
                               'color_label': color_labels.get(m.get('color'),
                                                               m.get('color') or '')})
        for i, row in enumerate(matrix, start=1):
            row['no'] = i

        Model = self.env['ir.model']
        masters = [{'label': Model._get(m['model']).name or m['model'], 'model': m['model'],
                    'records': m.get('records') or '',
                    'provided': _('是') if m.get('provided') else ''}
                   for m in snap.get('master_data') or [] if m.get('model')]

        scope = [{'kind_label': SCOPE_KINDS.get(s.get('kind'), s.get('kind') or ''),
                  'name': s.get('name') or '', 'detail': s.get('detail') or ''}
                 for s in snap.get('scope') or []]

        # --- 預算 ---------------------------------------------------------
        units_raw = snap.get('units') or []
        budget_units = [{
            'name': u.get('name') or '',
            'scope_text': '、'.join(u.get('capabilities') or []) or (
                _('客製開發項目') if u.get('is_custom') else ''),
            'hours': '%g' % round(u.get('hours') or 0.0, 2),
            'ratio': '%.1f%%' % (u.get('ratio') or 0.0),
            'amount': money(u.get('amount'))} for u in units_raw]
        activity_labels = dict(ACTIVITIES)
        budget_lines = []
        if not time_budget:
            if prices.get('subscription_amount'):
                budget_lines.append({
                    'item': _('訂閱方案'),
                    'content': _('%(p)s・%(t)s・%(c)s CCU・月費 %(m)s',
                                 p=snap.get('product') or '', t=snap.get('tier') or '',
                                 c=snap.get('ccu') or '', m=money(prices.get('subscription_monthly'))),
                    'amount': money(prices.get('subscription_amount'))})
            if prices.get('addon_amount'):
                budget_lines.append({'item': _('加購模組'), 'content': _('依能力對應之加購模組'),
                                     'amount': money(prices.get('addon_amount'))})
            for line in snap.get('lines') or []:
                kind = _('客製開發') if line.get('is_custom') else _('導入服務')
                label = line.get('note') if line.get('is_custom') else '%s／%s' % (
                    line.get('capability') or _('通用'),
                    activity_labels.get(line.get('activity'), line.get('activity') or ''))
                budget_lines.append({
                    'item': kind, 'content': _('%(n)s：%(d)s 人天', n=label or '',
                                              d=line.get('days')),
                    'amount': money(line.get('amount'))})
        total = prices.get('total') or 0.0
        total_hours = pricing.get('total_hours') or sum(
            (l.get('days') or 0.0) for l in snap.get('lines') or []) * hpd
        budget = {'total': money(total), 'benefit_total': money(sum(
            (b.get('saving') or 0.0) for b in snap.get('benefits') or []))}
        if time_budget:
            rate = pricing.get('hourly_rate') or (
                (snap.get('lines') or [{}])[0].get('day_rate', 0.0) / hpd)
            weeks = pricing.get('weeks_total') or 0
            budget['summary'] = _('預算 %(t)s（未稅）／ 約 %(h)s 小時 ／ 單位工時 %(r)s%(w)s',
                                  t=money(total), h=round(total_hours, 2), r=money(rate),
                                  w=_(' ／ 約 %s 週') % weeks if weeks else '')
        cap = pricing.get('budget_cap')
        budget['cap'] = money(cap) if cap else ''
        budget['gap'] = (_('（超出預算 %s）') % money(total - cap) if total > cap
                         else _('（尚餘 %s）') % money(cap - total)) if cap else ''

        phases = [{'code': p.get('code') or '', 'name': p.get('name') or '',
                   'content': p.get('content') or '',
                   'period': (_('第 %(a)s–%(b)s 週', a=p['week_from'], b=p['week_to'])
                              if p.get('week_from') and p.get('week_to') else ''),
                   'hours': '%g' % round(p.get('hours') or 0.0, 2),
                   'milestone': p.get('milestone') or ''} for p in snap.get('phases') or []]
        units = [{'name': u.get('name') or '',
                  'criteria': '；'.join(filter(None, (u.get('criteria') or '').splitlines())),
                  'amount': money(u.get('amount'))} for u in units_raw]
        payments = [{'name': t.get('name') or '', 'trigger': t.get('trigger') or '',
                     'ratio': '%g%%' % (t.get('ratio') or 0.0), 'amount': money(t.get('amount'))}
                    for t in snap.get('payments') or []]
        obligations = [{'kind_label': OBLIGATION_KINDS.get(o.get('kind'), o.get('kind') or ''),
                        'text': o.get('text') or ''} for o in snap.get('obligations') or []]
        clauses = [{'no': i, 'text': c.get('text') or ''}
                   for i, c in enumerate(snap.get('clauses') or [], start=1)]
        benefits = [{'name': b.get('name') or '', 'current': b.get('current') or '',
                     'after': b.get('after') or '', 'saving_text': money(b.get('saving'))}
                    for b in snap.get('benefits') or []]

        show = {
            'changes': bool(changes), 'drivers': bool(driver_rows),
            'overview': bool(narrative or driver_rows), 'solution': bool(caps),
            'matrix': bool(matrix), 'migration': bool(masters), 'scope': bool(scope),
            'budget_time': time_budget and bool(budget_units),
            'budget_sub': (not time_budget) and bool(budget_lines),
            'phases': bool(phases), 'units': bool(units), 'payments': bool(payments),
            'obligations': bool(obligations), 'clauses': bool(clauses), 'benefits': bool(benefits),
        }
        show['budget'] = show['budget_time'] or show['budget_sub'] or bool(total)
        show['payment'] = show['units'] or show['payments']
        numbers = iter(NUMERALS)
        chap = {key: next(numbers) for key in CHAPTERS if show.get(key)}

        basis = '；'.join(
            ('%s %s' % (b.get('date') or '', b.get('title') or '')).strip()
            for b in snap.get('basis') or [])
        model_label = dict(PRICING_MODELS).get(pricing.get('model'), '')
        return {
            'cover': {
                'customer': (snap.get('partner') or self.partner_id.display_name or ''),
                'title': _('服務建議書'),
                'subtitle': (_('導入規劃與報價（%s）') % model_label) if time_budget
                else _('功能規格與報價範圍說明'),
                'version_no': version.get('no') or self.version_no,
                'date': version.get('date') or '',
                'purpose': version.get('purpose') or '',
                'basis': basis,
                'company': snap.get('company') or self.company_id.name or '',
            },
            'show': show, 'chap': chap,
            'changes': changes, 'overview': {'narrative': narrative}, 'drivers': driver_rows,
            'caps': caps, 'matrix': matrix, 'masters': masters, 'scope': scope,
            'budget': budget, 'budget_units': budget_units, 'budget_lines': budget_lines,
            'phases': phases, 'units': units, 'payments': payments,
            'obligations': obligations, 'clauses': clauses, 'benefits': benefits,
        }
