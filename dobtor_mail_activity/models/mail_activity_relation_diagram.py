# -*- coding: utf-8 -*-
"""關聯邏輯圖（需求二/三/五）：供 relation_diagram widget 取得樹狀結構。
"""

import logging
from collections import defaultdict
from datetime import timedelta

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class MailActivityRelationDiagram(models.Model):
    """關聯邏輯圖（自 mail_activity.py 拆出，同一個 mail.activity 模型）。"""
    _inherit = 'mail.activity'

    _RELATION_TREE_LIMIT = 100  # 每模型節點上限，避免樹過大

    @api.model
    def get_relation_tree(self, project_id=False, partner_id=False,
                          res_model=False, res_id=False):
        """回傳向右邏輯圖的 node_tree（需求二/三/五）。

        以「直接外鍵(FK)為軸」（使用者選擇）：
        - 有 project（或由 res 反推得到）→ 以專案為根，依 transfer.config
          的 project_field 展開各模型（CRM/任務/…）中屬於該專案的紀錄。
        - 否則有 partner → 以客戶為根，依 partner_field 展開各模型中屬於
          該客戶的紀錄（需求五：依客戶縮小 res 選擇範圍）。
        - 皆無 → 空樹。

        節點 data 帶 {res_model, res_id}，供前端點擊回填 res。
        """
        Project = self.env['project.project']
        project = Project.browse(project_id).exists() if project_id else Project
        if not project and res_model and res_id:
            project = self._project_from_res(res_model, res_id)

        # 方案 C：無專案且前端未傳 partner 時，由 res(如 crm.lead)反推客戶，
        # 確保「CRM 尚未建專案但有客戶」仍能顯示客戶為根的關聯樹。
        if not project and not partner_id and res_model and res_id:
            partner_id = self._partner_from_res(res_model, res_id)

        if project:
            root = {
                'id': 'project_%s' % project.id,
                'topic': project.display_name,
                'expanded': True,
                'data': {'res_model': 'project.project', 'res_id': project.id},
                'children': self._project_scoped_children(project),
            }
        elif partner_id:
            partner = self.env['res.partner'].browse(partner_id).exists()
            if not partner:
                return self._empty_tree()
            root = {
                'id': 'partner_%s' % partner.id,
                'topic': partner.display_name,
                'expanded': True,
                'data': {'res_model': 'res.partner', 'res_id': partner.id},
                'children': self._partner_scoped_children(partner),
            }
        else:
            return self._empty_tree()

        return {
            'meta': {'name': 'activity_relation', 'version': '1.0'},
            'format': 'node_tree',
            'data': root,
        }

    @api.model
    def _empty_tree(self):
        return {
            'meta': {'name': 'activity_relation', 'version': '1.0'},
            'format': 'node_tree',
            'data': {'id': 'empty', 'topic': _('No related records'),
                     'expanded': True, 'data': {}, 'children': []},
        }

    @api.model
    def _relation_group_node(self, node_id, model_label, leaves, truncated):
        """模型分組節點（不帶 res，不可回填），內含葉節點。"""
        return {
            'id': node_id,
            'topic': '%s (%s%s)' % (model_label, len(leaves), '+' if truncated else ''),
            'expanded': True,
            'data': {},
            'children': leaves,
        }

    @api.model
    def _record_leaf(self, model_name, rec, todos_by_res, extra_children=None):
        """單筆記錄葉節點（帶 {res_model,res_id} 可回填）。
        結構子節點（如子任務）為圖上的子節點（往右）；未完成待辦不再是節點，
        改以 data.todos 掛在本節點，前端在節點內以 level-down/up 鈕垂直下拉呈現。
        """
        children = list(extra_children or [])
        return {
            'id': '%s_%s' % (model_name, rec.id),
            'topic': rec.display_name,
            'expanded': True,
            'data': {
                'res_model': model_name,
                'res_id': rec.id,
                'todos': todos_by_res.get(rec.id, []),
            },
            'children': children,
        }

    @api.model
    def _task_forest_nodes(self, tasks, acts_by_res):
        """把 project.task 記錄依 parent_id 建成森林（需求：子任務放上層任務下）。
        僅在給定集合內巢狀；上層任務不在集合者，該任務視為頂層。
        回傳頂層任務節點清單。
        """
        task_ids = set(tasks.ids)
        by_parent = defaultdict(list)
        tops = []
        for t in tasks:
            parent = t.parent_id
            if parent and parent.id in task_ids:
                by_parent[parent.id].append(t)
            else:
                tops.append(t)

        # 全部互為子代（資料成環，project.task 有祖先約束理論上不會發生）時
        # tops 為空 → 全列為頂層保底，避免整組任務被靜默丟棄
        if not tops and tasks:
            tops = list(tasks)

        def build(task, seen):
            if task.id in seen:
                return None  # 防環：無窮遞迴保護
            seen = seen | {task.id}
            sub_nodes = [n for n in (build(s, seen) for s in by_parent.get(task.id, [])) if n]
            return self._record_leaf('project.task', task, acts_by_res,
                                     extra_children=sub_nodes)

        return [n for n in (build(t, frozenset()) for t in tops) if n]

    @api.model
    def _model_leaves(self, model_name, records, acts_by_res):
        """依模型產生葉節點清單：task 走森林巢狀，其餘為平列。"""
        if model_name == 'project.task':
            return self._task_forest_nodes(records, acts_by_res)
        return [self._record_leaf(model_name, r, acts_by_res) for r in records]

    @api.model
    def _project_scoped_children(self, project):
        """專案為根：各設定模型中 project_field==project 的紀錄。
        任務依 parent_id 巢狀；每模型一個群組節點。
        """
        relation_map = self.env['mail.activity.transfer.config']._get_relation_map()
        children = []
        for model_name, cfg in relation_map.items():
            if model_name not in self.env:
                continue
            fk_field = cfg.get('project_field')
            Model = self.env[model_name]
            if not fk_field or fk_field not in Model._fields:
                continue
            try:
                records = Model.search(
                    [(fk_field, '=', project.id)], limit=self._RELATION_TREE_LIMIT + 1)
            except Exception as e:
                _logger.debug('relation tree search failed on %s.%s: %s',
                              model_name, fk_field, str(e))
                continue
            if not records:
                continue
            truncated = len(records) > self._RELATION_TREE_LIMIT
            records = records[:self._RELATION_TREE_LIMIT]
            acts = self._incomplete_activities_by_res(model_name, records.ids)
            leaves = self._model_leaves(model_name, records, acts)
            model_label = self.env['ir.model']._get(model_name).name or model_name
            children.append(self._relation_group_node(
                'group_project_%s' % model_name, model_label, leaves, truncated))
        return children

    @api.model
    def _partner_scoped_children(self, partner):
        """客戶為根（需求五 + 巢狀）：
        - 有專案 FK 的模型（商機/任務/銷售訂單…）依其 project_id 歸入專案節點下；
          無專案者集中在「未歸專案」的模型群組。
        - 任務再依 parent_id 巢狀。
        - 無專案 FK 的模型（採購單/會計傳票/服務單…）維持平列模型群組。
        - project.project 本身作為巢狀節點，不另列平列群組。
        """
        relation_map = self.env['mail.activity.transfer.config']._get_relation_map()
        # 分類設定模型
        project_fk_models = {}   # model -> project_field
        flat_models = []         # 無 project_field、但可依 partner 過濾的模型
        for model_name, cfg in relation_map.items():
            if model_name not in self.env:
                continue
            if model_name == 'project.project':
                continue  # 專案本身作為節點，稍後處理
            Model = self.env[model_name]
            partner_field = cfg.get('partner_field') or (
                'partner_id' if 'partner_id' in Model._fields else False)
            if not partner_field or partner_field not in Model._fields:
                continue
            proj_field = cfg.get('project_field')
            if proj_field and proj_field in Model._fields:
                project_fk_models[model_name] = (proj_field, partner_field)
            else:
                flat_models.append((model_name, partner_field))

        # 有專案 FK 的模型：查客戶紀錄，依 project_id 分桶
        by_project = {}    # (proj_id, model_name) -> recordset（同模型才 union）
        noproject = {}     # model_name -> recordset
        acts_maps = {}
        referenced_project_ids = set()
        for model_name, (proj_field, partner_field) in project_fk_models.items():
            Model = self.env[model_name]
            try:
                records = Model.search(
                    [(partner_field, '=', partner.id)], limit=self._RELATION_TREE_LIMIT + 1)
            except Exception as e:
                _logger.debug('relation tree search failed on %s: %s', model_name, str(e))
                continue
            if not records:
                continue
            records = records[:self._RELATION_TREE_LIMIT]
            acts_maps[model_name] = self._incomplete_activities_by_res(model_name, records.ids)
            for rec in records:
                proj = rec[proj_field][:1]
                if proj:
                    referenced_project_ids.add(proj.id)
                    key = (proj.id, model_name)
                    by_project[key] = by_project.get(key, Model.browse()) | rec
                else:
                    noproject[model_name] = noproject.get(model_name, Model.browse()) | rec

        children = []

        # 專案節點：客戶自己的專案 ∪ 被紀錄引用到的專案
        Project = self.env['project.project']
        own_projects = Project.search(
            [('partner_id', '=', partner.id)], limit=self._RELATION_TREE_LIMIT + 1)
        project_ids = list(dict.fromkeys(own_projects.ids + list(referenced_project_ids)))
        project_acts = self._incomplete_activities_by_res('project.project', project_ids)
        for proj in Project.browse(project_ids).exists():
            subgroups = []
            for model_name in project_fk_models:
                recs = by_project.get((proj.id, model_name))
                if not recs:
                    continue
                leaves = self._model_leaves(model_name, recs, acts_maps.get(model_name, {}))
                model_label = self.env['ir.model']._get(model_name).name or model_name
                subgroups.append(self._relation_group_node(
                    'group_proj_%s_%s' % (proj.id, model_name), model_label, leaves, False))
            # 專案節點本身也是可回填的 res，且掛自身未完成待辦
            children.append(self._record_leaf(
                'project.project', proj, project_acts, extra_children=subgroups))

        # 無專案的紀錄：集中為「未歸專案」模型群組
        for model_name in project_fk_models:
            recs = noproject.get(model_name)
            if not recs:
                continue
            leaves = self._model_leaves(model_name, recs, acts_maps.get(model_name, {}))
            model_label = self.env['ir.model']._get(model_name).name or model_name
            children.append(self._relation_group_node(
                'group_noproj_%s' % model_name,
                _('%s (no project)') % model_label, leaves, False))

        # 無專案 FK 的模型：平列模型群組
        for model_name, partner_field in flat_models:
            Model = self.env[model_name]
            try:
                records = Model.search(
                    [(partner_field, '=', partner.id)], limit=self._RELATION_TREE_LIMIT + 1)
            except Exception as e:
                _logger.debug('relation tree search failed on %s: %s', model_name, str(e))
                continue
            if not records:
                continue
            truncated = len(records) > self._RELATION_TREE_LIMIT
            records = records[:self._RELATION_TREE_LIMIT]
            acts = self._incomplete_activities_by_res(model_name, records.ids)
            leaves = self._model_leaves(model_name, records, acts)
            model_label = self.env['ir.model']._get(model_name).name or model_name
            children.append(self._relation_group_node(
                'group_partner_%s' % model_name, model_label, leaves, truncated))

        return children

    @api.model
    def _incomplete_activities_by_res(self, model_name, res_ids):
        """批次查某模型多筆記錄底下「尚未完成」的 mail.activity，回傳
        {res_id: [待辦 dict,...]}（供關聯圖記錄節點內的下拉待辦清單）。

        未完成 = active=True 且未完成(done)、未取消(cancel)。單一查詢避免 N+1。
        待辦 dict：{activity_id, label, deadline(字串), severity('over'/'soon'/'ok')}。
        severity 依截止日相對今日（本地時區）：逾期 over、3 日內 soon、其餘 ok。
        """
        if not res_ids:
            return {}
        activities = self.with_context(active_test=False).search([
            ('res_model', '=', model_name),
            ('res_id', 'in', res_ids),
            ('active', '=', True),
            ('done_date', '=', False),
            ('cancel_date', '=', False),
        ], order='date_deadline asc, id asc', limit=self._RELATION_TREE_LIMIT + 1)
        today = fields.Date.context_today(self)
        soon_limit = today + timedelta(days=3)
        result = {}
        for act in activities:
            label = act.summary or act.activity_type_id.display_name or _('To-do')
            dl = act.date_deadline
            severity = 'ok'
            if dl:
                if dl < today:
                    severity = 'over'
                elif dl <= soon_limit:
                    severity = 'soon'
            result.setdefault(act.res_id, []).append({
                'activity_id': act.id,
                'label': label,
                'deadline': fields.Date.to_string(dl) if dl else '',
                'severity': severity,
            })
        return result
