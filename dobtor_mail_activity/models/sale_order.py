# -*- coding: utf-8 -*-

import logging

from odoo import models, _

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    """銷售訂單擴展

    覆寫 action_confirm()，在訂單確認（專案已建立）後，
    自動將 SO 關聯的專案回寫到 CRM 商機的 project_id 欄位。

    回寫規則：
    - 商機尚無專案，或專案為公司預設工時表專案 -> 直接覆寫
    - 商機已有非預設專案且與 SO 專案不同 -> 僅發 chatter 通知
    """
    _inherit = 'sale.order'

    def action_confirm(self):
        """確認銷售訂單並將專案回寫至 CRM 商機

        在 super() 之後執行，確保 sale_project 已完成專案/任務建立。
        使用防禦性檢查，在 sale_crm / sale_project 未安裝時安全跳過。
        """
        res = super().action_confirm()

        for order in self:
            # 需要 sale_crm 提供的 opportunity_id
            opportunity = getattr(order, 'opportunity_id', False)
            if not opportunity:
                continue

            # 取得 SO 關聯的專案（sale_project 提供）
            so_project = getattr(order, 'project_id', False)
            if not so_project:
                project_ids = getattr(order, 'project_ids', False)
                so_project = project_ids[:1] if project_ids else False
            if not so_project:
                continue

            lead = opportunity

            # 取得公司預設工時表專案
            default_project = (
                lead.company_id.default_timesheet_project_id
                or self.env.company.default_timesheet_project_id
            )

            if not lead.project_id or lead.project_id == default_project:
                # 商機無專案或仍為預設專案 -> 自動回寫
                lead.write({'project_id': so_project.id})
            elif lead.project_id != so_project:
                # 商機已有不同的非預設專案 -> 發 chatter 通知
                lead.message_post(
                    body=_(
                        'Sales order %(order)s is associated with project "%(so_project)s", '
                        'which differs from current project "%(lead_project)s".',
                        order=order.name,
                        so_project=so_project.display_name,
                        lead_project=lead.project_id.display_name,
                    ),
                    message_type='comment',
                    subtype_xmlid='mail.mt_note',
                )

        return res
