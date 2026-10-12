# -*- coding: utf-8 -*-
"""建議書 → 客戶專屬疊加（知識主從計畫第三期，方案 B）。

客戶專屬情境（建議書來源計畫的故事情境，記著 knowledge_private_partner_id）的說明庫，
疊加該客戶建議書的加購模組與已完成的開發模組；母體與黃金庫不動。
"""
import json
import logging

from odoo import _, api, fields, models

from odoo.addons.dobtor_corpaas_knowledge.services import scripts

_logger = logging.getLogger(__name__)


def _github_url(repo):
    repo = (repo or '').strip()
    if not repo:
        return ''
    if repo.startswith('https://'):
        return repo
    return 'https://github.com/%s' % repo.strip('/')


class KnowledgeProposalOverlay(models.Model):
    _inherit = 'corpaas.knowledge.proposal'

    def _overlay_modules(self, available=None):
        """要疊加的模組：[{module, repo_url, ref, origin, source}]；母體已經有的不疊。
        找不到來源（沒 repo／沒發行標籤）的放在 missing 回傳。"""
        available = set(available or ())
        out, missing = {}, []
        for prop in self:
            for dev in prop.dev_item_ids.filtered(lambda d: d.state == 'done' and d.module_name):
                if dev.module_name in available:
                    continue
                if not (dev.repo and dev.release_tag):
                    missing.append(dev.module_name)
                    continue
                out[dev.module_name] = {'module': dev.module_name, 'repo_url': _github_url(dev.repo),
                                        'ref': dev.release_tag, 'origin': 'dev',
                                        'source': '%s,%s' % (dev._name, dev.id)}
            products = prop._active_mappings().mapped('addon_product_ids')
            if products:
                for m in self.env['infrastructure.repository.module'].sudo().search(
                        [('product_id', 'in', products.ids)]):
                    if m.technical_name in available or m.technical_name in out:
                        continue
                    repo = m.repository_id
                    name = getattr(repo, 'complete_name', '') or ''
                    if not (name and m.branch_id.name):
                        missing.append(m.technical_name)
                        continue
                    out[m.technical_name] = {'module': m.technical_name, 'repo_url': _github_url(name),
                                             'ref': m.branch_id.name, 'origin': 'addon',
                                             'source': '%s,%s' % (m._name, m.id)}
        return sorted(out.values(), key=lambda x: x['module']), sorted(set(missing))


class KnowledgeHooksProposalOverlay(models.AbstractModel):
    _inherit = 'corpaas.knowledge.hooks'

    @api.model
    def _knowledge_sandbox_overlay(self, sandbox):
        res = super()._knowledge_sandbox_overlay(sandbox)
        if res:
            return res
        partner = sandbox.scenario_id.knowledge_private_partner_id
        if not partner:
            return res
        props = self.env['corpaas.knowledge.proposal'].sudo().search([
            ('partner_id', 'child_of', partner.commercial_partner_id.id),
            ('package_id', '=', sandbox.package_id.id)])
        modules, _missing = props._overlay_modules(sandbox.package_id._knowledge_available_modules())
        if not modules:
            return res
        return self.env['corpaas.knowledge.overlay']._ensure_for(
            partner.commercial_partner_id, sandbox.master_instance_id.server_id, modules,
            name=_('%s 的客戶模組') % partner.commercial_partner_id.display_name)


class KnowledgePlanOverlayScan(models.Model):
    """建議書計畫：客戶疊加模組的功能點與畫面指紋（掃描用說明庫：複製黃金庫＋裝疊加模組，用完就刪）。

    ★ 盤到的功能點只掛在這份計畫的底稿上，不掛到方案（不出現在其他客戶或方案的說明書）。
    ★ 疊加內容（模組＋版本 SHA）沒變就不重掃。
    """
    _inherit = 'corpaas.knowledge.plan'

    overlay_feature_ids = fields.Many2many(
        'corpaas.knowledge.feature', 'corpaas_knowledge_plan_overlay_feature_rel', 'plan_id', 'feature_id',
        string='客戶模組功能點', readonly=True)
    overlay_scan_sig = fields.Char(readonly=True, copy=False)
    overlay_scan_at = fields.Datetime(string='客戶模組掃描時間', readonly=True, copy=False)
    overlay_scan_error = fields.Text(string='客戶模組掃描錯誤', readonly=True, copy=False)

    def _ledger_extra_features(self):
        res = super()._ledger_extra_features()
        if self.source_type == 'proposal' and self.proposal_id:
            try:
                self._overlay_scan()
            except Exception as e:  # noqa: BLE001 — 掃不到就記錯（P3／C4 會反映），底稿照建
                _logger.warning('[knowledge] 計畫 %s 掃描客戶模組失敗：%s', self.id, e)
                self.overlay_scan_error = str(e)[:2000]
            res |= self.overlay_feature_ids.filtered(lambda f: not f.missing)
        return res

    def _overlay_scan(self):
        self.ensure_one()
        pkg, prop = self.package_id, self.proposal_id
        master = pkg._knowledge_master(raise_if_missing=False)
        if not master:
            return False
        mods, _missing = prop._overlay_modules(pkg._knowledge_available_modules())
        if not mods:
            self.write({'overlay_feature_ids': [(5,)], 'overlay_scan_sig': False})
            return False
        partner = prop.partner_id.commercial_partner_id
        ovl = self.env['corpaas.knowledge.overlay']._ensure_for(
            partner, master.server_id, mods, name=_('%s 的客戶模組') % partner.display_name)
        if ovl.state != 'ready':
            ovl.action_prepare()
        if ovl.state != 'ready':
            self.overlay_scan_error = ovl.error
            return False
        sig = json.dumps(ovl.signature())
        if sig == self.overlay_scan_sig:
            return False
        names = ovl.module_names()
        # 說明庫一定要掛情境；掃描不重播示範資料，用一個不掛任何方案的系統情境（草稿，不上線、不交換）
        Sc = self.env['corpaas.knowledge.scenario'].sudo()
        scenario = Sc.search([('code', '=', 'kb_system_overlay_scan')], limit=1) or Sc.create(
            {'name': _('（系統）客戶模組掃描'), 'code': 'kb_system_overlay_scan'})
        Sandbox = self.env['corpaas.knowledge.sandbox'].sudo()
        db_name = 'docsbx-p%s-scan%s' % (pkg.id, self.id)
        sb = Sandbox.search([('db_name', '=', db_name)], limit=1) or Sandbox.create({
            'package_id': pkg.id, 'scenario_id': scenario.id, 'master_instance_id': master.id,
            'db_name': db_name, 'is_check': True, 'overlay_id': ovl.id})
        sb.overlay_id = ovl
        try:
            sb.rebuild_scan()
            res = sb._shell(scripts.analysis_script(names, official=[])) or {}
            feats = self._overlay_upsert_features(res.get('features') or [], names)
            items = [{'key': f.feature_key, 'model': f.model, 'views': f.views_for_fingerprint(),
                      'elements': [], 'menu_path': f.menu_path or '', 'view_mode': f.view_mode or ''}
                     for f in feats if f.model and f.views_for_fingerprint()]
            if items:
                fp = sb._shell(scripts.fingerprint_script(items, pkg._knowledge_roles())) or {}
                self._overlay_store_fingerprints(feats, fp)
            self.write({'overlay_feature_ids': [(6, 0, feats.ids)], 'overlay_scan_sig': sig,
                        'overlay_scan_at': fields.Datetime.now(), 'overlay_scan_error': False})
        finally:
            try:
                sb.drop()
            except Exception as e:  # noqa: BLE001
                _logger.warning('[knowledge] 刪除掃描用說明庫 %s 失敗：%s', db_name, e)
        return True

    def _overlay_upsert_features(self, items, names):
        """只收疊加模組的功能點；不掛方案（package_ids 不動）。"""
        Feature = self.env['corpaas.knowledge.feature'].sudo().with_context(active_test=False)
        now = fields.Datetime.now()
        out = Feature
        for item in items:
            if item.get('module') not in names:
                continue
            key = Feature.make_key(item['module'], item['kind'], item['anchor'])
            vals = {'name': item.get('name') or item['anchor'], 'model': item.get('model') or False,
                    'view_mode': item.get('view_mode') or False, 'view_xmlid': item.get('view_xmlid') or False,
                    'action_xmlid': item.get('action_xmlid') or False,
                    'button_name': item.get('button_name') or False,
                    'menu_path': item.get('menu_path') or False,
                    'group_xmlids': ','.join(item.get('groups') or []) or False,
                    'module_origin': 'custom', 'last_seen': now, 'active': True}
            rec = Feature.search([('feature_key', '=', key)], limit=1)
            if rec:
                rec.write(vals)
            else:
                rec = Feature.create(dict(vals, feature_key=key, module=item['module'], kind=item['kind'],
                                          anchor=item['anchor']))
            out |= rec
        return out

    def _overlay_store_fingerprints(self, feats, res):
        FP = self.env['corpaas.knowledge.fingerprint'].sudo()
        by_key = {f.feature_key: f for f in feats}
        now = fields.Datetime.now()
        for key, per in (res.get('items') or {}).items():
            feature = by_key.get(key)
            if not feature:
                continue
            for role_code, data in per.items():
                if data.get('error'):
                    continue
                FP.search([('feature_id', '=', feature.id), ('package_id', '=', self.package_id.id),
                           ('role_code', '=', role_code), ('current', '=', True)]).write({'current': False})
                FP.create({'feature_id': feature.id, 'package_id': self.package_id.id, 'role_code': role_code,
                           'computed_at': now, 'fp_version': res.get('version'), 'lang': res.get('lang'),
                           'form_hash': data['form'], 'scope_hash': data['scope'],
                           'found_json': json.dumps(data.get('found') or []),
                           'signature_json': json.dumps(data.get('sig') or []), 'elements_json': '[]'})
