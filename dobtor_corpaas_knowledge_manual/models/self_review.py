# -*- coding: utf-8 -*-
"""產出自審與單一核准關卡（計畫第 22、23 項）。

流程：文章送審 → 自審（事實檢查＋獨立的 AI 審查）→ 通過就由系統核准上線；不過就留在待審並寫下原因
（＝例外清單，人只處理這些）。自動上線的抽 5% 標「待抽查」，用來校正自審。

★ 審查者與寫作者分開：另一個提示詞、只拿文章與事實（截圖腳本、功能、讀者身分）對照，不看寫作理由。
★ 方案「自動化等級」：保守（不自動核准文章）／標準（預設，自審通過就上線）／全自動（同標準，
  另外 AI 審查失敗時只要事實檢查過也上線）。
☠️ 依據（社群電商方案）：從零到可驗收經過 5 個人工核准關卡；98 篇文章要人逐篇按。
"""
import json
import logging
import re

from odoo import _, api, fields, models

from odoo.addons.dobtor_corpaas_knowledge.services import hub_client

_logger = logging.getLogger(__name__)

#: 自動上線後抽查比例
SAMPLE_EVERY = 20
#: 一次更新最多自審幾篇（控制 AI 花費）
REVIEW_BATCH = 60
_TAG = re.compile(r'<[^>]+>')


class SolutionPackageAutomation(models.Model):
    _inherit = 'infrastructure.solution.package'

    knowledge_automation = fields.Selection(
        [('conservative', '保守：文章都要人核准'),
         ('standard', '標準：自審通過的文章自動上線'),
         ('full', '全自動：事實檢查通過就上線')],
        string='自動化等級', default='standard', required=True,
        help='自審不過的文章留在待審（例外清單），人只處理這些')


class KnowledgeArticleReview(models.Model):
    _inherit = 'corpaas.knowledge.article'

    manual_review_state = fields.Selection([('pass', '自審通過'), ('fail', '自審不過')],
                                           string='自審', readonly=True, copy=False, index=True)
    manual_review_note = fields.Text(string='自審意見', readonly=True, copy=False)
    manual_review_sampled = fields.Boolean(string='待抽查', readonly=True, copy=False,
                                           help='自動上線的文章抽樣，給人事後檢查')

    def _manual_fact_problems(self):
        """不靠 AI 的檢查：截圖就緒、文字檢查、至少一個步驟區塊。"""
        self.ensure_one()
        problems = []
        shot = self._manual_shots_problem()
        if shot:
            problems.append(shot)
        problems += list(self._manual_text_problems() or [])
        if not self.step_block_ids:
            problems.append(_('沒有操作步驟'))
        return problems

    def _manual_review_prompt(self, package):
        hooks = self.env['corpaas.knowledge.hooks']
        feature = hooks._manual_feature_dict(self.feature_id, package) if self.feature_id else {}
        steps = []
        if self.shot_binding_id:
            steps = self.shot_binding_id.template_id.steps()
        # 待審的文章還沒有上線快照：審它現在的內容（預覽＝標題＋情境＋步驟）
        text = _TAG.sub(' ', self.preview_html or '')
        text = re.sub(r'\s+', ' ', text)[:6000]
        # ★ 系統實際的狀態值也給審稿人：沒給時它把文章寫的真實狀態判成「編造」
        #   ☠️ 實機（社群電商方案）：結算單的「準備中／已結算／已撥款／已取消」被判編造
        states = {}
        if feature.get('model'):
            for flow in self.env['corpaas.knowledge.flow'].sudo().search(
                    [('model', '=', feature['model'])]):
                states[flow.state_field] = [st.label or st.value for st in flow.step_ids]
        who = {'visitor': '網站訪客', 'member': '已登入的會員', 'web_editor': '網站管理人員'}.get(
            feature.get('audience'), '後台使用者')
        return (
            "任務：你是說明書審稿人，只審這一篇是否可以上線。依據下面的事實判斷，不要猜。\n"
            "檢查：(1) 步驟說明與截圖腳本對得上（說明提到的按鈕、欄位、頁面，腳本裡要有對應的操作或截圖）；"
            "(2) 讀者身分正確：這篇的讀者是「%(who)s」，用語與入口要符合（前台文章不寫後台選單路徑，"
            "後台文章不叫讀者去網站前台操作）；(3) 沒有編造系統沒有的功能、沒有內部代碼或英文欄位名。\n"
            "只回 JSON：{\"ok\": true|false, \"problems\": [\"…\"]}；有問題才列，最多 3 點、每點一句。\n\n"
            "系統裡這個模型的狀態值（文章提到這些狀態不算編造）：%(states)s\n\n"
            "功能：%(feature)s\n\n截圖腳本：%(steps)s\n\n文章全文：%(text)s"
        ) % {'who': who, 'feature': json.dumps(feature, ensure_ascii=False)[:1500],
             'states': json.dumps(states, ensure_ascii=False)[:800] if states else '（無）',
             'steps': json.dumps(steps, ensure_ascii=False)[:3000], 'text': text}

    def _manual_self_review(self, package, token=None, use_ai=True):
        """回傳 (通過, 問題清單)。AI 呼叫失敗＝沒審到，算不過（留給人）。"""
        self.ensure_one()
        problems = self._manual_fact_problems()
        if problems or not use_ai:
            return not problems, problems
        try:
            data = self.env['corpaas.knowledge.ai'].ask(
                'manual_review', self._manual_review_prompt(package), package=package,
                refresh_token=token, record=self)
        except hub_client.BudgetExceeded:
            raise
        except (hub_client.HubError, ValueError) as e:
            return False, [_('AI 審查沒有完成：%s') % str(e)[:200]]
        ok = bool(isinstance(data, dict) and data.get('ok'))
        found = [str(p)[:200] for p in (data.get('problems') or [])] if isinstance(data, dict) else []
        return ok and not found, found or ([] if ok else [_('AI 審查判定不通過')])


class KnowledgeHooksSelfReview(models.AbstractModel):
    _inherit = 'corpaas.knowledge.hooks'

    @api.model
    def _manual_auto_publish(self, package, token, stop):
        """單一核准關卡：方案情境裡待審的文章逐篇自審，通過就由系統核准上線。回傳 (上線, 不過)。"""
        level = package.knowledge_automation or 'standard'
        if level == 'conservative':
            return 0, 0
        Article = self.env['corpaas.knowledge.article'].sudo()
        todo = Article.search([('state', '=', 'review'),
                               ('scenario_id', 'in', package.knowledge_scenario_ids.ids)],
                              limit=REVIEW_BATCH, order='id')
        published = failed = 0
        for art in todo:
            if stop.get('ai'):
                break
            try:
                ok, problems = art._manual_self_review(package, token)
            except hub_client.BudgetExceeded:
                stop['ai'] = True
                break
            if not ok and level == 'full' and not art._manual_fact_problems():
                ok = True   # 全自動：AI 審查有意見但事實都過，照樣上線（問題記在自審意見）
            vals = {'manual_review_state': 'pass' if ok else 'fail',
                    'manual_review_note': '；'.join(problems) or False}
            if ok:
                vals['manual_review_sampled'] = art.id % SAMPLE_EVERY == 0
            art.write(vals)
            if not ok:
                failed += 1
                continue
            try:
                art.with_context(knowledge_system_approve=True).action_approve()
                published += 1
                art.message_post(body=_('自審通過，系統自動核准上線%s') % (
                    _('（列入抽查）') if vals.get('manual_review_sampled') else ''))
            except Exception as e:  # noqa: BLE001 — 核准失敗留在待審
                art.write({'manual_review_state': 'fail',
                           'manual_review_note': _('自動核准失敗：%s') % str(e)[:300]})
                failed += 1
        return published, failed


class KnowledgeRunFunnel(models.Model):
    _inherit = 'corpaas.knowledge.run'

    def _knowledge_dashboard_funnel(self):
        """功能 → 截圖 → 文章 → 上線（計畫第 47 項）：一眼看出卡在哪一段。"""
        self.ensure_one()
        package = self.package_id
        scenarios = package.knowledge_scenario_ids
        n_feat = self.env['corpaas.knowledge.feature'].sudo().search_count(
            [('package_ids', 'in', package.id)])
        shots = self.env['corpaas.knowledge.shot_binding'].sudo().read_group(
            [('scenario_id', 'in', scenarios.ids)], ['state'], ['state'])
        shot = {g['state']: g['state_count'] for g in shots}
        Article = self.env['corpaas.knowledge.article'].sudo()
        dom = [('scenario_id', 'in', scenarios.ids)]
        arts = {g['state']: g['state_count'] for g in Article.read_group(dom, ['state'], ['state'])}
        auto = Article.search_count(dom + [('state', '=', 'published'), ('manual_review_state', '=', 'pass')])
        exc = Article.search_count(dom + [('state', '=', 'review'), ('manual_review_state', '=', 'fail')])
        sampled = Article.search_count(dom + [('manual_review_sampled', '=', True)])
        return [
            (_('功能'), n_feat, _('方案範圍內的功能')),
            (_('截圖'), sum(shot.values()), _('成功 %(ok)s、失敗 %(f)s、待拍 %(p)s', ok=shot.get('ok', 0),
                                              f=shot.get('failed', 0), p=shot.get('pending', 0))),
            (_('文章'), sum(arts.values()), _('草稿 %(d)s、待審 %(r)s', d=arts.get('draft', 0),
                                              r=arts.get('review', 0))),
            (_('上線'), arts.get('published', 0), _('其中自審自動上線 %(a)s、待抽查 %(s)s', a=auto, s=sampled)),
            (_('例外清單'), exc, _('自審不過、等人處理')),
        ]
