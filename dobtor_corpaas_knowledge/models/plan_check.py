# -*- coding: utf-8 -*-
"""檢查引擎（新架構規格第 7 節）：同一套檢查清單，在四個時點執行，結果存成檢查紀錄。

T1 起草前（C1～C8，建議書模組另加 P1～P4）、T2 核准前（A1～A6）、T3 前哨批、T4 關卡。
其他模組覆寫 `_knowledge_plan_checks(moment)`，在 super() 的結果後面加上自己的檢查。

每一筆結果：{'code', 'name', 'state': pass|warn|block, 'reason'}。
"""
import json
import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

PASS, WARN, BLOCK = 'pass', 'warn', 'block'


def _r(code, name, state=PASS, reason=''):
    return {'code': code, 'name': name, 'state': state, 'reason': reason}


class KnowledgePlanCheck(models.Model):
    _inherit = 'corpaas.knowledge.plan'

    budget_accepted = fields.Boolean(string='接受超出預算', copy=False,
                                     help='預估成本超出預算時，審閱者確認接受')

    # ------------------------------------------------------------------
    def run_checks(self, moment):
        """執行一個時點的檢查，存成紀錄並回傳。"""
        self.ensure_one()
        results = self._knowledge_plan_checks(moment)
        states = {r['state'] for r in results}
        state = BLOCK if BLOCK in states else (WARN if WARN in states else PASS)
        check = self.env['corpaas.knowledge.check'].sudo().create({
            'plan_id': self.id, 'package_id': self.package_id.id, 'moment': moment,
            'state': state, 'result_json': json.dumps(results, ensure_ascii=False)})
        field = {'t1': 't1_check_id', 't2': 't2_check_id'}.get(moment)
        if field:
            self.with_context(knowledge_plan_system=True).write({field: check.id})
        return check

    def action_run_t1(self):
        for rec in self:
            rec._plan_after_ledger()
        return True

    def _knowledge_plan_checks(self, moment):
        self.ensure_one()
        if moment == 't1':
            return self._checks_t1()
        if moment == 't2':
            return self._checks_t2()
        return []

    # ------------------------------------------------------------------
    # T1 起草前
    # ------------------------------------------------------------------
    def _checks_t1(self):
        pkg = self.package_id
        out = []
        # C1 來源資料完整
        master = pkg._knowledge_master(raise_if_missing=False)
        golden = master._corpaas_golden_db() if master else None
        if self.source_type == 'product':
            if not golden or golden.golden_state != 'verified':
                out.append(_r('C1', _('來源資料完整'), BLOCK, _('母體沒有已驗證的黃金庫')))
            elif not (pkg.knowledge_target_brief or '').strip():
                out.append(_r('C1', _('來源資料完整'), WARN,
                              _('方案沒有填「目標客群說明」：故事會依方案名稱與功能推測，信心較低')))
            else:
                out.append(_r('C1', _('來源資料完整')))
        # C2 關聯模組解析、找得到程式來源
        own = self.module_ids.filtered(lambda m: m.category == 'own')
        nosrc = own.filtered(lambda m: not m.version_ref)
        if not self.module_ids:
            out.append(_r('C2', _('關聯模組解析完成'), BLOCK, _('還沒有關聯模組（底稿沒有建立）')))
        elif nosrc:
            out.append(_r('C2', _('關聯模組解析完成'), BLOCK,
                          _('找不到程式來源：%s') % '、'.join(nosrc.mapped('module'))))
        else:
            out.append(_r('C2', _('關聯模組解析完成')))
        # C3 安裝在分析環境
        missing = self.module_ids.filtered(lambda m: not m.installed and m.category != 'tech')
        out.append(_r('C3', _('關聯模組都安裝在分析環境'), BLOCK if missing else PASS,
                      '、'.join(missing.mapped('module')[:20])))
        # C4／C5 分析完成且是目前版本（依模組目錄雜湊比對）
        need = own.filtered(lambda m: m.feature_count)
        unsummarized = need.filtered(lambda m: not m.summarized)
        strict = self.env['ir.config_parameter'].sudo().get_param(
            'corpaas_knowledge.plan_require_summary', '1') in ('1', 'True', 'true')
        if not self.line_ids:
            out.append(_r('C4', _('模組都以目前版本完成 AI 分析'), BLOCK, _('沒有任何功能點')))
        elif unsummarized:
            out.append(_r('C4', _('模組都以目前版本完成 AI 分析'), BLOCK if strict else WARN,
                          _('沒有目前版本的模組摘要：%s（重建底稿會自動補讀）')
                          % '、'.join(unsummarized.mapped('module'))))
        else:
            out.append(_r('C4', _('模組都以目前版本完成 AI 分析')))
        out.append(_r('C5', _('分析版本等於部署版本'), PASS,
                      _('模組摘要依目錄雜湊比對（C4 已涵蓋）')))
        # C6 流程、資料包、角色群組
        notes = []
        nopack = sorted({l.feature_id.model for l in self.line_ids
                         if l.assignment != 'exclude' and not l.has_pack and l.feature_id.model})
        if nopack:
            notes.append(_('%s 個模型沒有示範資料包（計畫的資料需求要補）') % len(nopack))
        if not self.package_id.env['corpaas.knowledge.flow'].sudo().search_count(
                [('package_ids', 'in', pkg.id)]):
            notes.append(_('沒有推導出任何流程'))
        out.append(_r('C6', _('流程、資料包、角色資訊足夠'), WARN if notes else PASS, '；'.join(notes)))
        # C7 同一來源沒有進行中的其他版本
        busy = self.search([('package_id', '=', pkg.id), ('source_type', '=', self.source_type),
                            ('id', '!=', self.id),
                            ('state', 'in', ('draft', 'review', 'approved', 'expanding', 'canary', 'running'))])
        out.append(_r('C7', _('沒有進行中的其他計畫版本'), BLOCK if busy else PASS,
                      '、'.join(busy.mapped('display_name'))))
        # C9 說明主機容量（#6）：磁碟紅燈擋下、黃燈或沒量過只提醒（建說明庫時另有磁碟閘門）
        server = master.server_id if master else None
        if server and 'disk_state' in server._fields:
            free = '%.1f GB' % (server.disk_free_gb or 0)
            if server.disk_state == 'red':
                out.append(_r('C9', _('說明主機磁碟足夠'), BLOCK, _('%(s)s 磁碟紅燈（剩 %(f)s）', s=server.name, f=free)))
            elif server.disk_state in ('amber', 'unknown', False):
                out.append(_r('C9', _('說明主機磁碟足夠'), WARN,
                              _('%(s)s 磁碟%(st)s（剩 %(f)s）', s=server.name,
                                st=_('黃燈') if server.disk_state == 'amber' else _('沒量過'), f=free)))
            else:
                out.append(_r('C9', _('說明主機磁碟足夠')))
        # C8 預算
        est = self._design_cost_estimate()
        out.append(_r('C8', _('計畫設計預估成本在預算內'), WARN if est > (self.budget or 0) else PASS,
                      '$%.2f' % est))
        return out

    def _design_cost_estimate(self):
        Ai = self.env['corpaas.knowledge.ai']
        batches = max(1, (self.lines_total - self.lines_excluded) // 150 + 1)
        return Ai.unit_cost('plan_design') * (3 + batches)

    # ------------------------------------------------------------------
    # T2 核准前
    # ------------------------------------------------------------------
    def _checks_t2(self):
        out = []
        # A1 底稿 100% 有歸屬
        out.append(_r('A1', _('底稿列都有歸屬'), BLOCK if self.lines_unassigned else PASS,
                      _('%s 列未歸屬') % self.lines_unassigned if self.lines_unassigned else ''))
        # A2 每章有功能點；整份有角色、資料需求
        chapters = self.live_items('chapter')
        empty = chapters.filtered(lambda c: not self.line_ids.filtered(
            lambda l: l.item_id == c and l.assignment == 'chapter'))
        reasons = []
        if not chapters:
            reasons.append(_('沒有章節'))
        if empty:
            # 空章節不影響執行：只提醒（反推的計畫常有能力底下沒有功能點）
            out.append(_r('A2b', _('每章都有功能點'), WARN,
                          _('沒有功能點的章節：%s') % '、'.join(empty.mapped('name'))))
        if not self.live_items('role'):
            reasons.append(_('沒有角色'))
        story_sc = self.live_items('story')[:1].record() if self.live_items('story') else None
        if not self.live_items('data') and not (story_sc and story_sc.published_rev_no):
            # 情境的示範資料已經核准上線（反推或修訂版本）就不需要另列資料需求
            reasons.append(_('沒有資料需求'))
        if not self.live_items('story'):
            reasons.append(_('沒有故事'))
        out.append(_r('A2', _('章節、角色、資料需求、故事齊全'), BLOCK if reasons else PASS, '；'.join(reasons)))
        # A3 引用存在（角色群組要在可用群組裡）
        pack = json.loads(self.design_pack or '{}') if self.design_pack else {}
        allowed = {g.split('｜')[0] for g in pack.get('groups') or []}
        bad = []
        if allowed:
            for role in self.live_items('role'):
                for g in role.content().get('groups') or []:
                    if g not in allowed and g != 'base.group_system':
                        bad.append('%s:%s' % (role.key, g))
        out.append(_r('A3', _('引用的群組、模組都存在'), BLOCK if bad else PASS, '、'.join(bad[:10])))
        # A4 待決事項已回答、低信心已確認
        open_q = self.live_items('question').filtered(lambda q: not (q.answer or '').strip())
        low = self.live_items().filtered(lambda i: i.confidence == 'low' and not i.confirmed and not i.locked
                                         and i.kind not in ('question', 'instruction'))
        reasons = []
        if open_q:
            reasons.append(_('%s 個待決事項未回答') % len(open_q))
        if low:
            reasons.append(_('%s 個低信心項目未確認') % len(low))
        out.append(_r('A4', _('待決事項已回答、低信心已確認'), BLOCK if reasons else PASS, '；'.join(reasons)))
        # A5 預算
        over = self.cost_estimate and self.budget and self.cost_estimate > self.budget
        out.append(_r('A5', _('預估成本在預算內'), BLOCK if over and not self.budget_accepted else PASS,
                      '$%.2f／$%.2f' % (self.cost_estimate or 0, self.budget or 0)))
        # A6 試寫通過（全自動核准的必要條件；人工核准只提醒）
        out.append(_r('A6', _('試寫通過自審'), PASS if self._trial_ok() else WARN,
                      '' if self._trial_ok() else _('試寫沒有通過或還沒產生')))
        return out

    def _trial_ok(self):
        return bool(self.trial_html) and 'data-trial-ok="1"' in (self.trial_html or '')

    # ------------------------------------------------------------------
    def _plan_after_ledger(self):
        """底稿建好 → T1。通過（或只有警告）就起草；擋下就停在「受阻」。"""
        self.ensure_one()
        self.with_context(knowledge_plan_system=True).write({'state': 'readiness'})
        check = self.run_checks('t1')
        if check.state == BLOCK:
            self.with_context(knowledge_plan_system=True).write({'state': 'blocked'})
            self.message_post(body=_('起草前檢查未通過：%s') % check.blocking_text())
            return check
        self.with_context(knowledge_plan_system=True).write({'state': 'draft'})
        self._plan_enqueue_design()
        return check
