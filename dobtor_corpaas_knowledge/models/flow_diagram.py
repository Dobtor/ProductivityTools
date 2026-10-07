# -*- coding: utf-8 -*-
"""任務流程 → dobtor_bpmn 設計圖（直接繼承 bpmn.diagram，不另做橋接模組）。

★ 規則產生、不靠 AI 畫：流程的狀態列步驟、轉換按鈕、「按鈕會打開哪張單」、角色範本，
  同一份事實每次產出同一張圖，跟著改版自動更新（結構雜湊變了才重產）。
★ 人改過（XML 跟系統產生的不同）或已審閱／定版的設計圖不覆蓋：另開新版本，舊版保留，
  記一筆「流程圖」缺口提醒人對照。
★ 系統產生的圖不走人工審核（使用者決定，2026-10-07）：來自程式事實、有結構檢查把關。
"""
import base64
import hashlib
import json
import logging

from odoo import _, api, fields, models

from ..services import bpmn_lib

_logger = logging.getLogger(__name__)

#: 模組 → 角色範本代碼（泳道）。沒對到的放「系統管理員」。
MODULE_ROLE = {
    'sale': 'sales', 'sale_management': 'sales', 'sale_stock': 'sales', 'loyalty': 'sales',
    'purchase': 'purchase', 'purchase_requisition': 'purchase', 'purchase_stock': 'purchase',
    'stock': 'stock', 'stock_landed_costs': 'stock', 'stock_picking_batch': 'stock',
    'stock_dropshipping': 'stock', 'stock_account': 'stock',
    'account': 'account', 'account_payment': 'account', 'payment': 'account',
}
#: 模型 → 角色（跨單據主線裡，被打開的單據落在誰的泳道）
MODEL_ROLE = {
    'sale.order': 'sales', 'purchase.order': 'purchase', 'purchase.requisition': 'purchase',
    'stock.picking': 'stock', 'stock.move': 'stock', 'stock.scrap': 'stock',
    'stock.picking.batch': 'stock', 'stock.landed.cost': 'stock',
    'account.move': 'account', 'account.payment': 'account',
}
#: 智慧按鈕名稱 → 打開的單據（轉換沒記 opens_model 時用）
BUTTON_MODEL = {
    'action_view_delivery': 'stock.picking', 'action_view_picking': 'stock.picking',
    'action_view_receipt': 'stock.picking', 'action_view_invoice': 'account.move',
    'action_create_invoice': 'account.move', 'action_view_purchase_orders': 'purchase.order',
    'action_register_payment': 'account.payment', 'action_view_payment': 'account.payment',
}
#: 主線上下游單據的先後（出貨在開票前、開票在收款前）
DOWNSTREAM_ORDER = ['purchase.order', 'stock.picking', 'account.move', 'account.payment']


class BpmnDiagram(models.Model):
    _inherit = 'bpmn.diagram'

    knowledge_flow_id = fields.Many2one('corpaas.knowledge.flow', string='來源任務流程',
                                        ondelete='set null', index=True, copy=False)
    knowledge_capability_id = fields.Many2one('corpaas.knowledge.capability', string='來源能力',
                                              ondelete='set null', index=True, copy=False)
    knowledge_package_id = fields.Many2one('infrastructure.solution.package', string='來源方案',
                                           ondelete='set null', index=True, copy=False)
    knowledge_scope = fields.Selection([('flow', '單據流程'), ('capability', '能力主線')],
                                       string='產生範圍', copy=False)
    knowledge_struct_hash = fields.Char(string='產生時的流程雜湊', readonly=True, copy=False)
    knowledge_xml_hash = fields.Char(string='產生時的 XML 雜湊', readonly=True, copy=False,
                                     help='跟目前 XML 不同＝人改過，系統不再覆蓋')
    knowledge_attachment_id = fields.Many2one('ir.attachment', string='公開圖片', readonly=True,
                                              copy=False, ondelete='set null')

    def _knowledge_edited(self):
        self.ensure_one()
        return bool(self.knowledge_xml_hash) and _sha(self.xml) != self.knowledge_xml_hash

    def _knowledge_public_image(self):
        """前台文章用的 SVG 圖片（公開附件）；回傳網址。"""
        self.ensure_one()
        if not self.svg:
            return False
        data = base64.b64encode(self.svg.encode('utf-8'))
        att = self.knowledge_attachment_id.sudo().exists()
        if att:
            if att.datas != data:
                att.write({'datas': data})
        else:
            att = self.env['ir.attachment'].sudo().create({
                'name': 'kb_diagram_%s.svg' % self.id, 'datas': data, 'public': True,
                'mimetype': 'image/svg+xml', 'res_model': self._name, 'res_id': self.id})
            self.sudo().knowledge_attachment_id = att
        return '/web/content/%s?unique=%s' % (att.id, att.checksum or '')


def _sha(text):
    return hashlib.sha1((text or '').encode('utf-8')).hexdigest()[:16]


class KnowledgeFlowDiagram(models.Model):
    _inherit = 'corpaas.knowledge.flow'

    diagram_ids = fields.One2many('bpmn.diagram', 'knowledge_flow_id', string='流程圖')

    def _kb_role(self, roles):
        """這個流程落在哪個角色泳道：功能點模組多數決 → 角色範本；沒有就模型對照。"""
        self.ensure_one()
        votes = {}
        for f in self.feature_ids:
            code = MODULE_ROLE.get(f.module)
            if code in roles:
                votes[code] = votes.get(code, 0) + 1
        if votes:
            return max(votes, key=votes.get)
        code = MODEL_ROLE.get(self.model)
        return code if code in roles else next(iter(roles))

    def _kb_main_steps(self):
        self.ensure_one()
        return [s for s in self.step_ids.sorted('sequence') if s.on_statusbar]

    def _kb_struct(self):
        """產生圖用到的流程事實（雜湊用）。"""
        self.ensure_one()
        return [self.name, [(s.value, s.label, s.on_statusbar) for s in self.step_ids.sorted('sequence')],
                sorted((t.from_value or '', t.to_value or '', t.button_name or '',
                        t.button_label or '', t.opens_model or '') for t in self.transition_ids)]

    def _kb_opens(self):
        """[(轉換, 打開的模型)]：這個流程的按鈕會開出哪些下游單據。"""
        self.ensure_one()
        out = []
        for t in self.transition_ids:
            model = t.opens_model or (t.opens_flow_id.model if t.opens_flow_id else False) \
                or BUTTON_MODEL.get(t.button_name or '')
            if model and model != self.model and model in MODEL_ROLE:
                out.append((t, model))
        return out

    def _kb_diagram_model(self, roles):
        """單據流程：開始 → 狀態列步驟 → 完成；取消類步驟在下一列結束。"""
        self.ensure_one()
        lane = self._kb_role(roles)
        main = self._kb_main_steps()
        nodes = [{'id': 'Start_1', 'kind': 'start', 'name': _('開始'), 'lane': lane, 'col': 0}]
        edges = []
        prev = 'Start_1'
        by_value = {}
        for i, s in enumerate(main, start=1):
            nid = 'Task_%s' % i
            by_value[s.value] = (nid, i)
            nodes.append({'id': nid, 'kind': 'task', 'name': s.label or s.value, 'lane': lane,
                          'col': i})
            label = ''
            if i > 1:
                t = self.transition_ids.filtered(
                    lambda t, a=main[i - 2].value, b=s.value: t.from_value == a and t.to_value == b)[:1]
                label = t.button_label or ''
            edges.append({'src': prev, 'dst': nid, 'name': label})
            prev = nid
        end_col = len(main) + 1
        nodes.append({'id': 'End_done', 'kind': 'end', 'name': _('完成'), 'lane': lane,
                      'col': end_col})
        edges.append({'src': prev, 'dst': 'End_done'})
        for j, s in enumerate([s for s in self.step_ids.sorted('sequence') if not s.on_statusbar]):
            src = next((by_value[t.from_value] for t in self.transition_ids
                        if t.to_value == s.value and t.from_value in by_value), None) \
                or (by_value[main[0].value] if main else None)
            if not src:
                continue
            nid = 'End_%s' % (j + 1)
            nodes.append({'id': nid, 'kind': 'end', 'name': s.label or s.value, 'lane': lane,
                          'col': src[1], 'row': 1 + j})
            edges.append({'src': src[0], 'dst': nid})
        lanes = [{'id': lane, 'name': roles[lane]}]
        return {'name': self.name, 'lanes': lanes, 'nodes': nodes, 'edges': edges}


class KnowledgeCapabilityDiagram(models.Model):
    _inherit = 'corpaas.knowledge.capability'

    diagram_ids = fields.One2many('bpmn.diagram', 'knowledge_capability_id', string='主線圖')

    def _kb_mainline_model(self, package, roles):
        """能力主線：主要流程的步驟展開，接著依序串上它開出的下游單據（每張一個子流程）。

        ★ 下游單據各自落在負責角色的泳道，每個節點一欄，交接線走欄間空隙、不壓字。"""
        self.ensure_one()
        Flow = self.env['corpaas.knowledge.flow'].sudo()
        flows = Flow.search([('capability_id', '=', self.id), ('package_ids', 'in', package.id)])
        if not flows:
            return None
        primary = flows.sorted(lambda f: (-(f.usage_score or 0), -len(f._kb_main_steps()), f.id))[0]
        base = primary._kb_diagram_model(roles)
        nodes = [n for n in base['nodes'] if n['id'] != 'End_done']
        edges = [e for e in base['edges'] if e['dst'] != 'End_done']
        last = [n for n in nodes if n.get('row', 0) == 0
                and n['kind'] in ('task', 'start')][-1]['id']
        col = max(n['col'] for n in nodes if n.get('row', 0) == 0)
        lanes = list(base['lanes'])
        seen, chain = set(), []
        for t, model in primary._kb_opens():
            if model not in seen:
                seen.add(model)
                chain.append((t, model))
        chain.sort(key=lambda x: DOWNSTREAM_ORDER.index(x[1]) if x[1] in DOWNSTREAM_ORDER else 99)
        others = flows - primary
        for f in others.sorted('id'):
            if f.model not in seen:
                seen.add(f.model)
                chain.append((None, f.model))
        for k, (t, model) in enumerate(chain, start=1):
            role = MODEL_ROLE.get(model) or next(iter(roles))
            if role not in roles:
                role = next(iter(roles))
            if role not in [l['id'] for l in lanes]:
                lanes.append({'id': role, 'name': roles[role]})
            col += 1
            target = Flow.search([('model', '=', model)], limit=1)
            nid = 'Sub_%s' % k
            nodes.append({'id': nid, 'kind': 'subprocess', 'lane': role, 'col': col,
                          'name': target.name or self.env['ir.model']._get(model).name or model})
            edges.append({'src': last, 'dst': nid, 'name': (t.button_label or '') if t else ''})
            last = nid
        col += 1
        end_lane = next(n['lane'] for n in nodes if n['id'] == last)
        nodes.append({'id': 'End_done', 'kind': 'end', 'name': _('完成'), 'lane': end_lane,
                      'col': col})
        edges.append({'src': last, 'dst': 'End_done'})
        return {'name': self.name, 'lanes': lanes, 'nodes': nodes, 'edges': edges}

    def _kb_struct(self, package):
        Flow = self.env['corpaas.knowledge.flow'].sudo()
        flows = Flow.search([('capability_id', '=', self.id), ('package_ids', 'in', package.id)])
        return [self.name, [f._kb_struct() for f in flows.sorted('id')]]


class SolutionPackageDiagrams(models.Model):
    _inherit = 'infrastructure.solution.package'

    def _knowledge_diagram_roles(self):
        """泳道用的角色：方案情境的角色；沒有就用角色範本。{code: 名稱}"""
        self.ensure_one()
        Role = self.env['corpaas.knowledge.role'].sudo()
        roles = Role
        for sc in self.knowledge_scenario_ids:
            roles |= sc.all_roles()
        roles = roles or Role.search([])
        return {r.code: r.name for r in roles.sorted('sequence')}

    def _knowledge_diagram_category(self):
        Cat = self.env['bpmn.diagram.category'].sudo()
        root = Cat.search([('name', '=', _('方案知識')), ('parent_id', '=', False)], limit=1) \
            or Cat.create({'name': _('方案知識')})
        name = self.display_name or self.product_tmpl_id.name
        return Cat.search([('name', '=', name), ('parent_id', '=', root.id)], limit=1) \
            or Cat.create({'name': name, 'parent_id': root.id})

    def _knowledge_sync_diagrams(self):
        """把方案的任務流程與能力主線同步進 dobtor_bpmn 設計圖庫。回傳 {'created','updated','versioned','failed'}。"""
        self.ensure_one()
        stats = {'created': 0, 'updated': 0, 'versioned': 0, 'failed': 0, 'same': 0}
        roles = self._knowledge_diagram_roles()
        if not roles:
            return stats
        cat = self._knowledge_diagram_category()
        Flow = self.env['corpaas.knowledge.flow'].sudo()
        for flow in Flow.search([('package_ids', 'in', self.id)]):
            if not flow._kb_main_steps():
                continue
            self._knowledge_upsert_diagram(
                'kb_flow_%s' % flow.id, flow.name, 'flow', flow._kb_struct(),
                lambda f=flow: f._kb_diagram_model(roles), cat, stats,
                flow=flow, capability=flow.capability_id)
        for cap in self.knowledge_capability_ids:
            self._knowledge_upsert_diagram(
                'kb_cap_%s_p%s' % (cap.id, self.id), _('%s：主線') % cap.name, 'capability',
                cap._kb_struct(self), lambda c=cap: c._kb_mainline_model(self, roles), cat, stats,
                capability=cap)
        return stats

    def _knowledge_upsert_diagram(self, code, name, scope, struct, build, cat, stats,
                                  flow=None, capability=None):
        Diagram = self.env['bpmn.diagram'].sudo()
        Gap = self.env['corpaas.knowledge.gap_item'].sudo()
        struct_hash = _sha(json.dumps([struct, sorted(self._knowledge_diagram_roles().items())],
                                      ensure_ascii=False, default=str))
        current = Diagram.search([('code', '=', code)], order='version desc, id desc', limit=1)
        if current and current.knowledge_struct_hash == struct_hash:
            stats['same'] += 1
            return current
        try:
            model = build()
            if not model:
                return current
            xml = bpmn_lib.to_xml(model, process_id=code)
            problems = bpmn_lib.validate(xml)
            svg = bpmn_lib.to_svg(model)
        except Exception as e:  # noqa: BLE001 — 一張產不出來不影響其他
            problems, xml, svg = [str(e)[:500]], None, None
        if problems:
            stats['failed'] += 1
            gap = Gap.note(self, 'diagram', _('「%(n)s」流程圖沒通過結構檢查：%(p)s',
                                              n=name, p='；'.join(problems[:5])),
                           record=flow or capability)
            gap.write({'state': 'human'})
            return current
        vals = {'name': name, 'xml': xml, 'svg': svg, 'purpose': 'documentation',
                'category_id': cat.id, 'knowledge_struct_hash': struct_hash,
                'knowledge_xml_hash': _sha(xml), 'knowledge_scope': scope,
                'knowledge_package_id': self.id,
                'knowledge_flow_id': flow.id if flow else False,
                'knowledge_capability_id': capability.id if capability else False,
                'odoo_module': (flow.feature_ids[:1].module if flow and flow.feature_ids else False)}
        if not current:
            stats['created'] += 1
            return Diagram.create(dict(vals, code=code))
        if current.state == 'draft' and not current._knowledge_edited():
            stats['updated'] += 1
            current.write(vals)
            current._knowledge_public_image() if current.knowledge_attachment_id else None
            return current
        # 人改過或已審閱／定版：另開新版本，舊版保留
        stats['versioned'] += 1
        new = Diagram.create(dict(vals, code=code))
        new.sudo().write({'version': (current.version or 1) + 1})
        gap = Gap.note(self, 'diagram', _('「%(n)s」流程已改版，舊版（v%(v)s）有人工修改或已定版，'
                                          '已另開新版本，請對照', n=name, v=current.version),
                       record=flow or capability)
        gap.write({'state': 'human'})
        return new
