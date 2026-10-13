# -*- coding: utf-8 -*-
"""專案客戶知識（知識主從改版計畫第 24 節，第五期）。

dobtor 做專案、不打包方案：專案客戶的知識基準是**客戶的測試實例**，不是方案母體＋黃金庫。
做法是讓「專案」的基準和「方案」長成同一個形狀，後面的盤點、指紋、讀程式、計畫、說明庫、拍照都不必改：

    方案：基準實例＝母體　　　基準資料庫＝已驗證的黃金庫
    專案：基準實例＝測試實例　基準資料庫＝測試庫（只唯讀盤點；說明庫是複製＋中和＋清除客戶資料後才拍）

★ 絕不對客戶測試庫做寫入：黃金庫專屬的「同步程式碼（-u）」對專案一律不做。
★ PAAS 範本模組的行為不變：知識模組改走自己的入口（_knowledge_base_db 等），不覆寫 _corpaas_golden_db。
"""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class SolutionPackageProject(models.Model):
    _inherit = 'infrastructure.solution.package'

    knowledge_kind = fields.Selection([('package', '方案'), ('project', '專案')], string='知識種類',
                                      default='package', required=True, index=True)
    knowledge_project_partner_id = fields.Many2one('res.partner', string='專案客戶', index=True)
    knowledge_project_instance_id = fields.Many2one(
        'infrastructure.instance', string='基準實例', index=True, ondelete='restrict',
        help='客戶的測試實例：盤點、讀程式都以它為準；說明庫從它的資料庫複製（清除客戶資料後才拍）')
    knowledge_project_database_id = fields.Many2one(
        'infrastructure.database', string='基準資料庫', ondelete='restrict',
        domain="[('instance_id', '=', knowledge_project_instance_id)]")
    knowledge_project_consent = fields.Boolean(string='客戶已同意 AI 讀原始碼', copy=False)
    knowledge_project_consent_note = fields.Char(string='同意說明', copy=False)
    knowledge_project_consent_user_id = fields.Many2one('res.users', string='勾選人', readonly=True, copy=False)
    knowledge_project_consent_at = fields.Datetime(string='勾選時間', readonly=True, copy=False)

    def write(self, vals):
        if not self.env.context.get('_kb_project_system'):
            vals.pop('knowledge_project_consent_user_id', None)
            vals.pop('knowledge_project_consent_at', None)
        res = super().write(vals)
        if vals.get('knowledge_project_consent'):
            self.with_context(_kb_project_system=True).write({
                'knowledge_project_consent_user_id': self.env.user.id,
                'knowledge_project_consent_at': fields.Datetime.now()})
        return res

    # ------------------------------------------------------------------
    def _knowledge_is_project(self):
        self.ensure_one()
        return self.knowledge_kind == 'project'

    def _knowledge_master(self, raise_if_missing=True):
        """專案：基準實例就是「母體」（不要求說明主機、上架版本）。"""
        self.ensure_one()
        if self.knowledge_kind != 'project':
            return super()._knowledge_master(raise_if_missing=raise_if_missing)
        inst = self.knowledge_project_instance_id.sudo()
        if inst and inst.state == 'active':
            return inst
        if raise_if_missing:
            raise UserError(_('專案知識「%s」的基準實例沒有設定或不是啟用中。') % self.display_name)
        return inst.browse()

    def _knowledge_scope_modules(self, golden):
        """專案＝整個客戶系統：測試庫已安裝的全部自訂模組（盤全部種類）＋設定開啟時的官方模組。"""
        if self.knowledge_kind != 'project':
            return super()._knowledge_scope_modules(golden)
        self.ensure_one()
        rows = self.env['infrastructure.database_module'].sudo().search(
            [('database_id', '=', golden.id), ('state', '=', 'installed')])
        installed_official = set(rows.filtered(lambda r: r.module_type == 'odoo').mapped('technical_name')) - {False}
        custom = sorted(set(rows.filtered(lambda r: r.module_type != 'odoo').mapped('technical_name')) - {False})
        official = []
        if self.knowledge_include_official:
            patterns = self._knowledge_official_exclude_patterns()
            official = sorted(n for n in installed_official if not self._knowledge_is_official_excluded(n, patterns))
        return custom, official, installed_official

    def _knowledge_available_modules(self):
        res = super()._knowledge_available_modules()
        if self.knowledge_kind == 'project':
            db = self.knowledge_project_database_id
            if db:
                res |= self._knowledge_golden_installed(db)
        return res

    @api.model
    def _knowledge_projects_for_partner(self, partner):
        """客戶的專案知識（同一家公司在 CRM 有重複聯絡人也對得上）。"""
        if not partner:
            return self.browse()
        cp = partner.commercial_partner_id
        return self.sudo().search([('knowledge_kind', '=', 'project'), ('knowledge_enabled', '=', True),
                                   '|', ('knowledge_project_partner_id', 'child_of', cp.id),
                                   ('knowledge_project_partner_id.name', '=', cp.name)])

    def action_knowledge_project_refresh(self):
        self.ensure_one()
        if self.knowledge_kind != 'project':
            raise UserError(_('這不是專案知識。'))
        self.knowledge_enqueue_refresh(full=True, reason='manual')
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'type': 'info', 'message': _('已排入知識更新。')}}


class InstanceKnowledgeBase(models.Model):
    _inherit = 'infrastructure.instance'

    knowledge_project_ids = fields.One2many('infrastructure.solution.package', 'knowledge_project_instance_id',
                                            string='專案知識')

    def _knowledge_base_db(self):
        """知識的基準資料庫：專案的基準實例＝它登記的測試庫；其他＝已驗證的黃金庫。"""
        self.ensure_one()
        proj = self.env['infrastructure.solution.package'].sudo().search(
            [('knowledge_kind', '=', 'project'), ('knowledge_project_instance_id', '=', self.id)], limit=1)
        if proj:
            db = proj.knowledge_project_database_id
            return db if db and db.state == 'active' else db.browse()
        return self._corpaas_golden_db()

    def action_knowledge_create_project(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('建立專案知識'),
            'res_model': 'corpaas.knowledge.project.wizard', 'view_mode': 'form', 'target': 'new',
            'context': {'default_instance_id': self.id},
        }


class DatabaseKnowledgeBase(models.Model):
    _inherit = 'infrastructure.database'

    def _knowledge_is_project_base(self):
        self.ensure_one()
        return bool(self.env['infrastructure.solution.package'].sudo().search_count(
            [('knowledge_kind', '=', 'project'), ('knowledge_project_database_id', '=', self.id)]))

    def _knowledge_base_ok(self):
        """可以當知識基準：黃金庫要已驗證；專案的測試庫要啟用中。"""
        self.ensure_one()
        if self._knowledge_is_project_base():
            return self.state == 'active'
        return self.golden_state == 'verified'

    def _knowledge_base_sync_code(self):
        """複製前同步程式碼：黃金庫才做（-u）；★ 專案的測試庫絕不寫入。"""
        self.ensure_one()
        if self._knowledge_is_project_base():
            return True
        return self._corpaas_golden_sync_code()

    def _on_installed_modules_changed(self, added, removed):
        """專案的穩定點：客戶**正式機**的模組變了＝真的上線了 → 排更新（套等待期與每日上限）。

        ★ 測試機（專案的基準）自己的變動不觸發：開發人員天天在上面試，跟著跑會把半成品一直重拍。
        """
        res = super()._on_installed_modules_changed(added, removed)
        Pkg = self.env['infrastructure.solution.package']
        for rec in self:
            if rec._knowledge_is_project_base() or not rec.partner_id:
                continue
            projects = Pkg._knowledge_projects_for_partner(rec.partner_id)
            if projects:
                _logger.info('[knowledge] 專案客戶正式環境 %s 模組變動：%s', rec.name,
                             ', '.join(sorted(set(added) | set(removed)))[:300])
                projects.knowledge_enqueue_refresh(full=False, reason='customer_release')
        return res

    def _knowledge_needs_purge(self):
        """專案的測試庫是客戶資料：說明庫一律清除。"""
        if self._knowledge_is_project_base():
            return True
        return super()._knowledge_needs_purge()


class KnowledgeProjectWizard(models.TransientModel):
    """實例表單「建立專案知識」：選客戶、確認客戶同意 → 建專案知識、開 AI 讀原始碼、排第一次更新。"""
    _name = 'corpaas.knowledge.project.wizard'
    _description = '建立專案知識'

    instance_id = fields.Many2one('infrastructure.instance', string='基準實例（客戶測試實例）', required=True)
    database_id = fields.Many2one('infrastructure.database', string='基準資料庫', required=True,
                                  domain="[('instance_id', '=', instance_id), ('state', '=', 'active')]")
    partner_id = fields.Many2one('res.partner', string='客戶', required=True)
    consent = fields.Boolean(string='客戶已同意 AI 唯讀讀取自訂模組原始碼')
    consent_note = fields.Char(string='同意說明', help='例如：合約第 9 條、2026-10-13 會議同意')
    is_production_warning = fields.Boolean(compute='_compute_warning')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        inst = self.env['infrastructure.instance'].browse(res.get('instance_id'))
        if inst:
            dbs = self.env['infrastructure.database'].sudo().search(
                [('instance_id', '=', inst.id), ('state', '=', 'active')])
            if len(dbs) == 1:
                res.setdefault('database_id', dbs.id)
            partner = inst.partner_id if 'partner_id' in inst._fields else inst.environment_id.partner_id
            if partner:
                res.setdefault('partner_id', partner.commercial_partner_id.id)
        return res

    @api.depends('instance_id', 'database_id')
    def _compute_warning(self):
        for rec in self:
            name = '%s %s' % (rec.instance_id.name or '', rec.database_id.name or '')
            rec.is_production_warning = 'test' not in name.lower()

    def action_confirm(self):
        self.ensure_one()
        if not self.consent or not (self.consent_note or '').strip():
            raise UserError(_('要先勾「客戶已同意」並填寫同意說明。'))
        Pkg = self.env['infrastructure.solution.package'].sudo()
        if Pkg.search_count([('knowledge_kind', '=', 'project'),
                             ('knowledge_project_instance_id', '=', self.instance_id.id)]):
            raise UserError(_('這座實例已經有專案知識了。'))
        tmpl = self.env['product.template'].sudo().create({
            'name': _('專案知識：%s') % self.partner_id.display_name, 'type': 'service', 'sale_ok': False,
            **({'is_published': False} if 'is_published' in self.env['product.template']._fields else {})})
        pkg = Pkg.create({
            'product_tmpl_id': tmpl.id, 'knowledge_kind': 'project',
            'knowledge_project_partner_id': self.partner_id.id,
            'knowledge_project_instance_id': self.instance_id.id,
            'knowledge_project_database_id': self.database_id.id,
            'knowledge_project_consent_note': self.consent_note.strip()})
        pkg.knowledge_project_consent = True   # 勾選人與時間由 write() 寫入
        notes = []
        inst = self.instance_id.sudo()
        if 'ai_source_mount' in inst._fields and not inst.ai_source_mount:
            inst.ai_source_mount = True
            notes.append(_('已勾「允許 AI 讀原始碼」'))
        Runner = self.env.get('infrastructure.ai_runner')
        runner = Runner.sudo().search([('server_id', '=', inst.server_id.id)], limit=1) if Runner is not None else None
        if runner:
            try:
                runner.action_sync_targets()
                notes.append(_('Runner 已同步來源'))
            except Exception as e:  # noqa: BLE001 — 失敗就請人去按，不擋建立
                _logger.warning('[knowledge] 專案知識同步 Runner 來源失敗：%s', e)
                notes.append(_('Runner 同步來源失敗，請到 AI Runner 按「同步來源」：%s') % str(e)[:200])
        else:
            notes.append(_('這台主機沒有 AI Runner，AI 讀不到程式'))
        pkg.knowledge_enabled = True
        pkg.knowledge_enqueue_refresh(full=True, reason='manual')
        (pkg.message_post if hasattr(pkg, 'message_post') else (lambda **k: None))(body=_('建立專案知識：基準 %(i)s／%(d)s。%(n)s。★ 還要到 AI Hub 的知識來源加「可讀實例」。',
                                i=inst.name, d=self.database_id.name, n='；'.join(notes)))
        return {'type': 'ir.actions.act_window', 'res_model': pkg._name, 'res_id': pkg.id, 'view_mode': 'form'}
