# -*- coding: utf-8 -*-
"""任務流程 → dobtor_bpmn 設計圖：規則產生、結構檢查、版本與人工修改保護、能力主線。"""
from odoo.tests import TransactionCase, tagged

from ..services import bpmn_lib


def _model():
    return {'name': '測試', 'lanes': [{'id': 'sales', 'name': '業務'}, {'id': 'stock', 'name': '倉管'}],
            'nodes': [{'id': 'Start_1', 'kind': 'start', 'name': '開始', 'lane': 'sales', 'col': 0},
                      {'id': 'Task_1', 'kind': 'task', 'name': '報價', 'lane': 'sales', 'col': 1},
                      {'id': 'End_1', 'kind': 'end', 'name': '已取消', 'lane': 'sales', 'col': 1, 'row': 1},
                      {'id': 'Sub_1', 'kind': 'subprocess', 'name': '出貨', 'lane': 'stock', 'col': 2},
                      {'id': 'End_done', 'kind': 'end', 'name': '完成', 'lane': 'stock', 'col': 3}],
            'edges': [{'src': 'Start_1', 'dst': 'Task_1'}, {'src': 'Task_1', 'dst': 'End_1'},
                      {'src': 'Task_1', 'dst': 'Sub_1', 'name': '確認'},
                      {'src': 'Sub_1', 'dst': 'End_done'}]}


@tagged('post_install', '-at_install')
class TestBpmnLib(TransactionCase):

    def test_xml_valid_and_svg(self):
        xml = bpmn_lib.to_xml(_model(), 'kb_t')
        self.assertEqual(bpmn_lib.validate(xml), [])
        svg = bpmn_lib.to_svg(_model())
        self.assertIn('業務', svg)
        self.assertIn('倉管', svg)
        self.assertNotIn('width="', svg.split('>')[0], '不寫死大小，文章裡會縮放')

    def test_validate_catches_overlap_and_lane(self):
        m = _model()
        m['nodes'][3]['lane'], m['nodes'][3]['col'] = 'sales', 1   # 跟「報價」同一格
        problems = bpmn_lib.validate(bpmn_lib.to_xml(m, 'kb_t'))
        self.assertTrue(any('重疊' in p for p in problems))
        self.assertTrue(bpmn_lib.validate('<x')[0].startswith('XML 解析失敗'))


@tagged('post_install', '-at_install')
class TestFlowDiagrams(TransactionCase):

    def setUp(self):
        super().setUp()
        tmpl = self.env['product.template'].create({'name': 'DIA', 'type': 'service'})
        self.pkg = self.env['infrastructure.solution.package'].sudo().create(
            {'product_tmpl_id': tmpl.id})
        Feature = self.env['corpaas.knowledge.feature'].sudo()
        self.f = Feature.create({'feature_key': 'sale.action:kbd', 'module': 'sale', 'kind': 'action',
                                 'anchor': 'kbd', 'name': '報價單', 'model': 'sale.order',
                                 'package_ids': [(4, self.pkg.id)]})
        self.cap = self.env['corpaas.knowledge.capability'].sudo().create(
            {'name': '銷售', 'code': 'kbd_sales', 'package_ids': [(4, self.pkg.id)]})
        Flow = self.env['corpaas.knowledge.flow'].sudo()
        self.flow = Flow.create({'model': 'sale.order', 'state_field': 'kbd_state',
                                 'model_name': '銷售訂單流程', 'field_type': 'selection',
                                 'package_ids': [(4, self.pkg.id)], 'capability_id': self.cap.id,
                                 'feature_ids': [(4, self.f.id)]})
        Step = self.env['corpaas.knowledge.flow.step'].sudo()
        for i, (v, label, bar) in enumerate([('draft', '報價', True), ('sale', '銷售訂單', True),
                                             ('cancel', '已取消', False)]):
            Step.create({'flow_id': self.flow.id, 'sequence': i, 'value': v, 'label': label,
                         'on_statusbar': bar})
        Tr = self.env['corpaas.knowledge.flow.transition'].sudo()
        Tr.create({'flow_id': self.flow.id, 'from_value': 'draft', 'to_value': 'sale',
                   'button_name': 'action_confirm', 'button_label': '確認'})
        Tr.create({'flow_id': self.flow.id, 'from_value': 'draft', 'to_value': 'cancel',
                   'button_name': 'action_cancel', 'button_label': '取消'})
        Tr.create({'flow_id': self.flow.id, 'from_value': 'sale', 'to_value': '',
                   'button_name': 'action_view_invoice', 'button_label': '發票'})

    def _diagrams(self, code):
        return self.env['bpmn.diagram'].search([('code', '=', code)], order='version')

    def test_sync_creates_flow_and_mainline(self):
        stats = self.pkg._knowledge_sync_diagrams()
        self.assertEqual(stats['created'], 2)
        flow_d = self._diagrams('kb_flow_%s' % self.flow.id)
        self.assertEqual((flow_d.purpose, flow_d.state, flow_d.knowledge_scope),
                         ('documentation', 'draft', 'flow'))
        self.assertIn('業務', flow_d.svg, '泳道依模組對到角色範本')
        self.assertEqual(bpmn_lib.validate(flow_d.xml), [])
        main = self._diagrams('kb_cap_%s_p%s' % (self.cap.id, self.pkg.id))
        self.assertIn('會計', main.svg, '主線串上「發票」開出的單據，落在會計泳道')
        self.assertEqual(main.category_id.parent_id.name, '方案知識')
        self.assertEqual(self.pkg._knowledge_sync_diagrams()['same'], 2, '流程沒變不重產')

    def test_struct_change_updates_draft_but_versions_edited(self):
        self.pkg._knowledge_sync_diagrams()
        d = self._diagrams('kb_flow_%s' % self.flow.id)
        self.flow.step_ids.filtered(lambda s: s.value == 'sale').label = '已確認訂單'
        stats = self.pkg._knowledge_sync_diagrams()
        self.assertEqual(stats['updated'], 2, '沒人改過的草稿直接更新')
        self.assertIn('已確認訂單', d.svg)
        d.xml = d.xml.replace('報價', '詢價')   # 人在編輯器裡改過
        self.flow.step_ids.filtered(lambda s: s.value == 'sale').label = '訂單'
        stats = self.pkg._knowledge_sync_diagrams()
        self.assertEqual(stats['versioned'], 1)
        versions = self._diagrams('kb_flow_%s' % self.flow.id)
        self.assertEqual(versions.mapped('version'), [1, 2], '人改過的保留，另開新版')
        self.assertIn('詢價', versions[0].xml)
        gap = self.env['corpaas.knowledge.gap_item'].search(
            [('package_id', '=', self.pkg.id), ('kind', '=', 'diagram')])
        self.assertEqual(gap.state, 'human')

    def test_public_image(self):
        self.pkg._knowledge_sync_diagrams()
        d = self._diagrams('kb_flow_%s' % self.flow.id)
        url = d._knowledge_public_image()
        self.assertTrue(url.startswith('/web/content/'))
        self.assertTrue(d.knowledge_attachment_id.public)
