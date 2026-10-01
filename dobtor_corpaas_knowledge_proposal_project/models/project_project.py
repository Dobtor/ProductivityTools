# -*- coding: utf-8 -*-
"""專案結案 → 自動工時回寫（校正工時範本）。

★ Odoo 18 的「結案」＝ `project.project.stage_id` 進到 `fold=True` 的階段
  （project.project.stage 的 fold 說明：Projects in a folded stage are considered as closed）。
  在 write() 比對前後：原本不是摺疊 → 現在摺疊，才觸發；每個專案只跑一次
  （`knowledge_feedback_done`），重新打開（移到非摺疊階段）就重設，下次結案再跑。
★ 找建議書：專案 → 報價單（`sale_line_id.order_id`，即 sale_project 的 related `sale_order_id`；
  另含 `reinvoiced_sale_order_id`，以及把這個專案指定為 `project_id` 的報價單）→ 以該報價單為 `sale_order_id` 的建議書。
  回寫本身直接呼叫建議書的 `action_feedback_actuals()`，不重寫校正邏輯；
  它讀 `sale_order_id.project_ids`（sale_project 以 `sale_order_id` 搜尋專案）＋ `so_line`
  的工時，這個結案中的專案一定在裡面，不需要另外轉接。
☠️ 回寫失敗（建議書未送出、資料有誤、任何例外）絕不能擋住結案：包在 savepoint 裡，
  失敗就回滾回寫、在專案留言，專案照樣結案；旗標不設，下次重新結案會再試。
☠️ stage_id 有 groups="project.group_project_stages"，讀舊值一律 sudo()。
"""
import logging

from markupsafe import Markup, escape

from odoo import _, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ProjectProject(models.Model):
    _inherit = 'project.project'

    knowledge_feedback_done = fields.Boolean(
        string='已自動工時回寫', copy=False, readonly=True,
        help='專案結案時已自動把工時回寫到服務建議書；重新打開專案會重設。')

    # ------------------------------------------------------------------
    def _knowledge_is_closed(self):
        self.ensure_one()
        return bool(self.sudo().stage_id.fold)

    def _knowledge_proposals(self):
        """這個專案對應的服務建議書（已送出與否由回寫方法自己判斷）。"""
        self.ensure_one()
        project = self.sudo()
        orders = project.sale_line_id.order_id
        if 'reinvoiced_sale_order_id' in project._fields:
            orders |= project.reinvoiced_sale_order_id
        # ★ 報價單直接指定既有專案（sale.order.project_id）時專案沒有 sale_line_id
        orders |= self.env['sale.order'].sudo().search([('project_id', '=', project.id)])
        if not orders:
            return self.env['corpaas.knowledge.proposal']
        # ★ 以建議書的 sale_order_id 為準：回寫方法只讀自己那張報價單的專案工時。
        return self.env['corpaas.knowledge.proposal'].sudo().search(
            [('sale_order_id', 'in', orders.ids)])

    def write(self, vals):
        # company_id 變更時 project.write 會自己換 stage_id，也要比對
        watch = 'stage_id' in vals or 'company_id' in vals
        was_closed = {p.id: p._knowledge_is_closed() for p in self} if watch else {}
        res = super().write(vals)
        if watch:
            closed = self.filtered(lambda p: not was_closed.get(p.id) and p._knowledge_is_closed())
            reopened = self.filtered(lambda p: p.knowledge_feedback_done
                                     and not p._knowledge_is_closed())
            if reopened:
                reopened.write({'knowledge_feedback_done': False})
            closed.filtered(lambda p: not p.knowledge_feedback_done)._knowledge_feedback_on_close()
        return res

    def _knowledge_feedback_on_close(self):
        for project in self:
            proposals = project._knowledge_proposals()
            if not proposals:
                continue
            ok = True
            for proposal in proposals:
                try:
                    with self.env.cr.savepoint():
                        # ★ 系統觸發：結案的人不一定有建議書權限（範本校正本身也是 sudo）
                        proposal.action_feedback_actuals()
                except Exception as e:  # noqa: BLE001 — 任何失敗都不擋結案
                    ok = False
                    if isinstance(e, UserError):
                        reason = e.args[0] if e.args else str(e)
                    else:
                        _logger.exception('專案 %s 結案自動工時回寫失敗（建議書 %s）',
                                          project.id, proposal.id)
                        reason = _('系統錯誤：%s') % e
                    project.message_post(body=Markup(_(
                        '結案自動工時回寫失敗（建議書 %(p)s）：%(r)s<br/>'
                        '專案仍已結案；可到建議書手動按「工時回寫」，或重新打開再結案重試。'))
                        % {'p': escape(proposal.display_name), 'r': escape(reason)})
                else:
                    project.message_post(body=_('結案自動工時回寫：已回寫到建議書 %s。')
                                         % proposal.display_name)
            if ok:
                project.knowledge_feedback_done = True
