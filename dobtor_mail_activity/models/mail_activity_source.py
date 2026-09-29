# -*- coding: utf-8 -*-
"""來源推導：由關聯文件自動帶出客戶（專案部分由 dobtor_mail_activity_project 擴充）。

不綁定特定模組 —— 允許的模型與其專案 FK 欄位由 mail.activity.transfer.config
設定驅動（見 _selection_target_model），新增可關聯的模型不需要改這裡的程式碼。

_project_from_res / _partner_from_res 是「唯讀候選查詢」，除了本檔的 onchange
之外，關聯邏輯圖（mail_activity_relation_diagram.py）與建立待辦精靈也重用它們。
"""

import logging
from collections import defaultdict

from odoo import api, models

_logger = logging.getLogger(__name__)


class MailActivitySource(models.Model):
    """自 mail_activity.py 拆出，同一個 mail.activity 模型。"""
    _inherit = 'mail.activity'

    def _derive_partner_from_source(self, force=False):
        """設定驅動派生關聯客戶（需求五，不綁定特定模組）。

        來源優先序（每筆待辦）：
        1. res 記錄的 partner 欄位（transfer.config.partner_field，或自動探測
           res 模型上的 'partner_id'）
        2. _fallback_partner_id()：核心無；dobtor_mail_activity_project 覆寫為
           待辦專案的客戶（需求五「以專案客戶帶入」）
        3. 皆無 → 不動（保留手填/留空）

        預設只在「partner 尚未設定」時填入（force=False），以免覆寫手填值；
        force=True 時（來源明確變更）一律以派生值覆寫。
        """
        relation_map = self.env['mail.activity.transfer.config']._get_relation_map()

        # 依 res 模型分組批次讀取（僅存在的模型）
        model_groups = defaultdict(list)
        for activity in self:
            if activity.res_model and activity.res_id and activity.res_model in self.env:
                model_groups[activity.res_model].append(activity)

        # 先算出每筆的 res-partner 候選
        res_partner = {}
        for model_name, activities in model_groups.items():
            Model = self.env[model_name]
            partner_field = relation_map.get(model_name, {}).get('partner_field')
            if not partner_field and 'partner_id' in Model._fields:
                partner_field = 'partner_id'
            if not partner_field or partner_field not in Model._fields:
                continue
            res_ids = list({a.res_id for a in activities})
            record_map = {r.id: r for r in Model.browse(res_ids).exists()}
            for activity in activities:
                record = record_map.get(activity.res_id)
                if not record:
                    continue
                try:
                    partner = record[partner_field]
                    # partner_field 若被誤設為非關聯欄位（如 Char），partner[:1].id
                    # 會 AttributeError；一併包進 try 防呆（設定驅動功能）。
                    res_partner[activity.id] = partner[:1].id if partner else False
                except Exception as e:
                    _logger.debug('Failed to read partner field %s on %s: %s',
                                  partner_field, model_name, str(e))
                    continue

        # 依 candidate 分組後批次 write（同 partner 一次寫），避免逐筆 N 次 write
        to_write = defaultdict(lambda: self.env['mail.activity'])
        for activity in self:
            candidate = res_partner.get(activity.id) or activity._fallback_partner_id()
            if candidate and (force or not activity.partner_id):
                to_write[candidate] |= activity
        for candidate, activities in to_write.items():
            activities.partner_id = candidate

    def _fallback_partner_id(self):
        """res 推不出客戶時的後備客戶 id（hook）。核心無；專案橋接回傳專案客戶。"""
        self.ensure_one()
        return False

    def _project_from_res(self, res_model, res_id):
        """依 transfer.config.project_field 由 res 記錄反推 project（需求三）。

        res 為 project.project 本身 → 回傳自身；否則讀該模型的 project_field。
        回傳 project.project 記錄集（可能為空）；未安裝專案模組時回傳 False。
        """
        if 'project.project' not in self.env:
            return False
        Project = self.env['project.project']
        if not res_model or not res_id or res_model not in self.env:
            return Project
        if res_model == 'project.project':
            return Project.browse(res_id).exists()
        relation_map = self.env['mail.activity.transfer.config']._get_relation_map()
        project_field = relation_map.get(res_model, {}).get('project_field')
        Model = self.env[res_model]
        if not project_field or project_field not in Model._fields:
            return Project
        record = Model.browse(res_id).exists()
        if not record:
            return Project
        try:
            return record[project_field][:1]
        except Exception:
            return Project

    @api.model
    def _partner_from_res(self, res_model, res_id):
        """由 res 記錄反推 partner id（唯讀，供關聯圖「客戶為根」fallback）。

        依 transfer.config.partner_field，或自動探測 res 模型的 'partner_id'。
        與 _derive_partner_from_source 的 res-partner 候選邏輯一致，但不寫入。
        回傳 partner id 或 False。
        """
        if not res_model or not res_id or res_model not in self.env:
            return False
        relation_map = self.env['mail.activity.transfer.config']._get_relation_map()
        partner_field = relation_map.get(res_model, {}).get('partner_field')
        Model = self.env[res_model]
        if not partner_field and 'partner_id' in Model._fields:
            partner_field = 'partner_id'
        if not partner_field or partner_field not in Model._fields:
            return False
        record = Model.browse(res_id).exists()
        if not record:
            return False
        try:
            partner = record[partner_field]
        except Exception:
            return False
        return partner[:1].id if partner else False

    @api.onchange('res_model_id', 'res_id')
    def _onchange_res_fill_project_partner(self):
        """需求五：選定 res 後派生客戶（res 客戶 > 後備客戶）。
        專案反推由 dobtor_mail_activity_project 覆寫本方法補上（先設專案再呼叫 super）。"""
        for activity in self:
            if activity.res_model and activity.res_id:
                activity._derive_partner_from_source(force=True)
