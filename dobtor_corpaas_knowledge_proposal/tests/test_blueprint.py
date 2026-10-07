# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestBlueprint(TransactionCase):

    def test_blueprint_copies_mainline_for_customer(self):
        tmpl = self.env['product.template'].create({'name': 'BP', 'type': 'service'})
        pkg = self.env['infrastructure.solution.package'].sudo().create({'product_tmpl_id': tmpl.id})
        cap = self.env['corpaas.knowledge.capability'].sudo().create(
            {'name': '銷售', 'code': 'kbbp_sales', 'package_ids': [(4, pkg.id)]})
        partner = self.env['res.partner'].create({'name': '客戶甲'})
        Proposal = self.env['corpaas.knowledge.proposal'].sudo()
        vals = {'partner_id': partner.id, 'package_id': pkg.id}
        if 'product_tmpl_id' in Proposal._fields:
            vals['product_tmpl_id'] = tmpl.id
        if 'tier' in Proposal._fields:
            vals['tier'] = Proposal._fields['tier'].selection[0][0] \
                if isinstance(Proposal._fields['tier'].selection, list) else 'shared'
        prop = Proposal.create(vals)
        with self.assertRaises(UserError):
            prop.action_create_blueprints()
        src = self.env['bpmn.diagram'].sudo().create({
            'name': '銷售：主線', 'code': 'kb_cap_x', 'knowledge_capability_id': cap.id,
            'knowledge_package_id': pkg.id, 'knowledge_scope': 'capability',
            'knowledge_xml_hash': 'abc'})
        prop.action_create_blueprints()
        bp = prop.blueprint_ids
        self.assertEqual(len(bp), 1)
        self.assertEqual((bp.purpose, bp.partner_id), ('blueprint', partner))
        self.assertFalse(bp.knowledge_xml_hash, '藍圖是人的底稿，系統不覆蓋')
        prop.action_create_blueprints()
        self.assertEqual(len(prop.blueprint_ids), 1, '不重複建')
        self.assertNotEqual(bp, src)
