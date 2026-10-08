# -*- coding: utf-8 -*-
"""每章的「先懂這幾個觀念」：參考說明書在操作前先講清楚單據怎麼串、狀態代表什麼、哪裡容易搞混。

★ 這是 AI 寫的說明（不是規則產生），所以跟能力的其他文字一起送審：存在能力上、列入能力的
  修訂欄位，前台只用能力的上線快照。沒核准前這一頁不出現。
★ 只在章節有流程時起草（沒有流程就沒有「單據怎麼串」可講）；已經有內容的不重寫。
"""
import json
import logging
import re

from odoo import _, api, fields, models

from odoo.addons.dobtor_corpaas_knowledge.services import hub_client

from ..services import manual_lib, prompts

_logger = logging.getLogger(__name__)

#: 一次更新最多起草幾章
CONCEPT_BATCH = 8
_SIMPLIFIED = re.compile('[这为们说时发开关过还进单应个对会来么经现实务样点让认识计记设调导选择]')


def full_width(html):
    """中文之間的半形標點換成全形（實機：AI 回了一整頁「,」「;」）。"""
    return re.sub(r'(?<=[\u4e00-\u9fff」）])\s*([,;:])\s*(?=[\u4e00-\u9fff「（])',
                  lambda m: {',': '，', ';': '；', ':': '：'}[m.group(1)], html or '')


class KnowledgeCapability(models.Model):
    _inherit = 'corpaas.knowledge.capability'

    manual_concept_html = fields.Html(string='本章觀念', help='操作說明每章的「先懂這幾個觀念」（AI 起草、送審）')

    def _knowledge_revision_fields(self):
        return super()._knowledge_revision_fields() + ['manual_concept_html']


class KnowledgeHooks(models.AbstractModel):
    _inherit = 'corpaas.knowledge.hooks'

    @api.model
    def _manual_concept_prompt(self, package, cap, flows):
        outlines = []
        for f in flows:
            o = f.as_outline()
            o['transitions'] = [t for t, raw in zip(o['transitions'], f.transition_ids)
                                if not raw.opens_flow_id or raw.is_handoff()]
            o['meanings'] = {s.label or s.value: s.meaning for s in f.step_ids if s.meaning}
            outlines.append(o)
        glossary = {}
        for sc in package.knowledge_scenario_ids:
            glossary.update(sc.glossary_map() or {})
        return (
            "任務：為操作說明的「%(cap)s」這一章寫一頁「先懂這幾個觀念」，放在本章所有操作說明前面。"
            "讀者是第一次用系統的使用者。\n"
            "1. 第一段：一句話說出這一章的核心觀念（這些單據是為了解決什麼事）。\n"
            "2. 「單據怎麼串」：依下面的流程與交接，寫出 A → B → C 的先後，各由誰負責（用業務說法）。\n"
            "3. 「容易搞混的地方」：2–4 點，只寫從流程的狀態與按鈕推得出來的（例如兩個很像的狀態"
            "差在哪、哪一步做了就不能回頭、取消跟刪除不同）；推不出來就少寫，不要編造系統行為。\n"
            "4. 不寫操作步驟、不放截圖、不寫網址；300–500 字。%(allowed)s\n" + prompts.WRITING_RULES +
            "5. 套用用語對照（左邊系統原詞、右邊這個方案的說法）。\n"
            "回覆格式：{\"html\":\"…\"}\n\n"
            "能力：%(cap)s（痛點：%(pain)s；成果：%(outcome)s）\n\n用語對照：%(glossary)s\n\n"
            "流程（狀態、按鈕、交接、狀態的意思）：%(flows)s"
        ) % {'cap': cap.name, 'pain': cap.pain or '', 'outcome': cap.outcome or '',
             'allowed': prompts.ALLOWED_HTML,
             'glossary': json.dumps(glossary, ensure_ascii=False),
             'flows': json.dumps(outlines, ensure_ascii=False)[:20000]}

    @api.model
    def _manual_draft_concepts(self, package, token, stop):
        """本方案還沒有觀念頁的章節：請 AI 起草、送審。回傳起草幾章。"""
        if stop.get('ai'):
            return 0
        Flow = self.env['corpaas.knowledge.flow'].sudo()
        Ai = self.env['corpaas.knowledge.ai']
        n = 0
        for cap in package.knowledge_capability_ids.sorted(lambda c: (c.sequence, c.id)):
            if n >= CONCEPT_BATCH:
                break
            if cap.manual_concept_html or cap.state == 'review':
                continue
            flows = Flow.search([('capability_id', '=', cap.id), ('package_ids', 'in', package.id)])
            flows = flows.filtered(lambda f: len(f.step_ids.filtered('on_statusbar')) >= 2)
            if not flows:
                continue
            try:
                data = Ai.ask('manual_concept', self._manual_concept_prompt(package, cap, flows),
                              package=package, refresh_token=token, record=cap)
            except hub_client.BudgetExceeded:
                stop['ai'] = True
                break
            except (hub_client.HubError, ValueError) as e:
                _logger.warning('[knowledge.manual] 觀念頁起草失敗 %s：%s', cap.name, e)
                continue
            html = manual_lib.clean_html(data.get('html') if isinstance(data, dict) else '') or ''
            html = full_width(html)
            plain = re.sub(r'<[^>]+>', '', html)
            if len(plain) < 80 or _SIMPLIFIED.search(plain):
                _logger.info('[knowledge.manual] 觀念頁不採用（太短或含簡體字）：%s', cap.name)
                continue
            cap.sudo().manual_concept_html = html
            cap.sudo().knowledge_propose('text', note=_('AI 起草本章觀念'))
            n += 1
        return n


class KnowledgeChannelSection(models.Model):
    _inherit = 'corpaas.knowledge.channel_section'

    def _manual_sync_concept(self, publisher, shown):
        """本章觀念頁：只用能力的上線快照（沒核准過就不出現）。"""
        self.ensure_one()
        cap = self.capability_id
        snap = (cap._last_published_snapshot() or {}) if cap else {}
        html = full_width(manual_lib.clean_html(snap.get('manual_concept_html') or '')).strip()
        if html:
            from ..services import layout_lib as L
            # 長段落切開（AI 的字不改，只重新分段）
            html = L.page('<div class="o_kb_guide o_kb_concept">%s</div>' % L.split_paragraphs(html))
        return self._manual_upsert_guide('concept', html, publisher, shown)
