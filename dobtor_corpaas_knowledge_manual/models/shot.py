# -*- coding: utf-8 -*-
"""截圖腳本範本（功能 × 指紋）與情境繫結（範本 × 情境）。

★ 範本不含任何記錄 id，只有佔位符 "{name}"；繫結把佔位符對到情境示範資料的 xmlid，
  拍攝前才在說明庫解析成 id——同一份範本可以在每個情境、每次重建的說明庫重用。
★ elements 由 steps 推導，是指紋「腳本範圍」的定義（核心 `_knowledge_elements_for`）。
★ 範本鍵＝(feature_id, fingerprint)：方案 A 的畫面改版 → 複製一份新指紋的範本
  （derived_from_id），方案 B 還在舊指紋就繼續用舊範本，兩邊的圖互不干擾（B2）。
"""
import json

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from ..services import manual_lib


class KnowledgeShotTemplate(models.Model):
    _name = 'corpaas.knowledge.shot_template'
    _description = '操作說明：截圖腳本範本'
    _inherit = ['mail.thread']
    _order = 'feature_id, id desc'

    name = fields.Char(compute='_compute_name', store=True)
    feature_id = fields.Many2one('corpaas.knowledge.feature', required=True,
                                 ondelete='cascade', index=True)
    fingerprint = fields.Char(string='腳本範圍指紋', index=True,
                              help='範本最後一次驗證成功時的 scope_hash')
    steps_json = fields.Text(string='步驟', required=True, default='[]', tracking=True)
    placeholders = fields.Text(compute='_compute_derived', store=True,
                               help='JSON list：步驟裡的 "{name}" 佔位符')
    elements = fields.Text(compute='_compute_derived', store=True,
                           help='JSON list：highlight/click/fill 碰到的 field/button/page')
    login_role = fields.Char(string='登入角色', help='情境角色 code')
    derived_from_id = fields.Many2one('corpaas.knowledge.shot_template', string='複製自',
                                      ondelete='set null', index=True,
                                      help='畫面指紋變了：以舊範本的步驟為底複製一份（不叫 AI）')
    binding_ids = fields.One2many('corpaas.knowledge.shot_binding', 'template_id',
                                  string='情境繫結')
    repair_count = fields.Integer(string='AI 修補次數', readonly=True)
    source = fields.Selection([('ai', 'AI 探索'), ('rule', '規則產生'), ('manual', '人工')],
                              default='manual')
    note = fields.Char()
    active = fields.Boolean(default=True)

    @api.depends('feature_id.name')
    def _compute_name(self):
        for rec in self:
            rec.name = _('%s 截圖腳本') % (rec.feature_id.name or '')

    @api.depends('steps_json')
    def _compute_derived(self):
        for rec in self:
            steps = rec._steps_or_empty()
            rec.placeholders = json.dumps(manual_lib.placeholders_in(steps))
            rec.elements = json.dumps(manual_lib.elements_from_steps(steps))

    @api.constrains('steps_json')
    def _check_steps(self):
        for rec in self:
            try:
                manual_lib.validate_steps(json.loads(rec.steps_json or '[]'))
            except ValueError as e:
                raise ValidationError(_('截圖腳本不合法：%s') % e) from e

    def _steps_or_empty(self):
        self.ensure_one()
        try:
            steps = json.loads(self.steps_json or '[]')
        except ValueError:
            return []
        return steps if isinstance(steps, list) else []

    def steps(self):
        self.ensure_one()
        return self._steps_or_empty()

    def elements_list(self):
        self.ensure_one()
        return json.loads(self.elements or '[]')

    def placeholder_list(self):
        self.ensure_one()
        return json.loads(self.placeholders or '[]')

    def shot_names(self):
        self.ensure_one()
        return manual_lib.shot_names(self.steps())

    @api.model
    def _for_hashes(self, feature, hashes):
        """該功能在這組指紋（方案目前各角色的 scope_hash）下的範本。

        ★ 範本自己的登入角色對到的那個指紋優先；否則任何一個相符的都行。
        """
        hashes = hashes or {}
        values = [h for h in hashes.values() if h]
        if not values:
            return self.browse()
        found = self.search([('feature_id', '=', feature.id), ('fingerprint', 'in', values)],
                            order='id desc')
        for tmpl in found:
            if hashes.get(tmpl.login_role) == tmpl.fingerprint:
                return tmpl
        return found[:1]

    @api.model
    def _latest_for(self, feature):
        """該功能最新一份範本（分岔／探索的底）。"""
        return self.search([('feature_id', '=', feature.id)], limit=1, order='id desc')

    def binding_for(self, scenario):
        self.ensure_one()
        return self.binding_ids.filtered(lambda b: b.scenario_id == scenario)[:1]


class KnowledgeShotBinding(models.Model):
    _name = 'corpaas.knowledge.shot_binding'
    _description = '操作說明：情境繫結'
    _order = 'template_id, scenario_id'

    template_id = fields.Many2one('corpaas.knowledge.shot_template', required=True,
                                  ondelete='cascade', index=True)
    feature_id = fields.Many2one(related='template_id.feature_id', store=True, index=True)
    scenario_id = fields.Many2one('corpaas.knowledge.scenario', required=True,
                                  ondelete='cascade', index=True)
    bindings_json = fields.Text(string='佔位符對應', default='{}',
                                help='{"佔位符": "示範資料 xmlid"}')
    roles_json = fields.Text(string='角色覆寫', default='{}',
                             help='{"login_role": "<code>"}：這個情境改用別的角色登入')
    state = fields.Selection([('pending', '待拍'), ('ok', '成功'), ('failed', '失敗')],
                             default='pending', index=True)
    last_result = fields.Text(readonly=True, help='最近一次 shooter 回傳（本繫結的部分）')
    last_error = fields.Text(readonly=True)
    last_token = fields.Char(readonly=True, help='最近一次拍攝的 refresh token')
    last_shot_at = fields.Datetime(readonly=True)
    shot_scope_hash = fields.Char(readonly=True, help='最近一次成功拍攝時的指紋')
    transient_fp = fields.Char(readonly=True, copy=False,
                               help='暫時性錯誤原樣重拍過的指紋（同一個只重拍一次）')
    repair_bonus_used = fields.Boolean(readonly=True, copy=False,
                                       help='已用過「錯誤附畫面資訊」的額外一次修補')
    repair_checking = fields.Boolean(readonly=True, copy=False,
                                     help='AI 剛修過、等重拍結果（算修補成功率用，拍完就清掉）')
    shot_inputs = fields.Char(readonly=True,
                              help='最近一次成功拍攝的輸入簽章（腳本、繫結、指紋、示範資料版號、截圖程式）；'
                                   '全量更新時簽章沒變就沿用現有截圖，不重拍（R4）')
    needs_repair = fields.Boolean(readonly=True, index=True,
                                  help='失敗、等 AI 修（下一次 refresh 的分派階段修，不必重建說明庫）')
    repair_attempts = fields.Integer(readonly=True, help='連續 AI 修補次數；成功拍攝後歸零')
    repair_fp = fields.Char(readonly=True,
                            help='上次送 AI 修時的錯誤指紋：修完再拍又是同一個指紋＝這招沒用，不再修')
    asset_ids = fields.Many2many('corpaas.knowledge.asset', compute='_compute_asset_ids',
                                string='素材')
    asset_count = fields.Integer(compute='_compute_asset_ids')

    _sql_constraints = [
        ('template_scenario_unique', 'unique(template_id, scenario_id)',
         '同一範本在同一情境只能有一個繫結'),
    ]

    def _compute_asset_ids(self):
        Asset = self.env['corpaas.knowledge.asset'].sudo()
        for rec in self:
            assets = Asset.search([('owner_model', '=', self._name), ('owner_id', '=', rec.id),
                                   ('state', '=', 'current')]) if rec.id else Asset
            rec.asset_ids = assets
            rec.asset_count = len(assets)

    def bindings(self):
        """佔位符 → 示範資料 xmlid。鍵一律不含大括號（腳本裡寫 {rec}，對照鍵是 rec）。

        ☠️ 實機（社群電商方案）：AI 修腳本回的鍵是 "{agent_partner}"，永遠對不到，
          4 張報「說明庫找不到示範資料」，AI 又照樣修了 3 次。"""
        self.ensure_one()
        try:
            data = json.loads(self.bindings_json or '{}') or {}
        except ValueError:
            return {}
        if not isinstance(data, dict):
            return {}
        return {str(k).strip().strip('{}').strip(): v for k, v in data.items()}

    def login_role(self):
        self.ensure_one()
        try:
            override = (json.loads(self.roles_json or '{}') or {}).get('login_role')
        except ValueError:
            override = None
        return override or self.template_id.login_role

    def current_assets(self):
        self.ensure_one()
        return self.env['corpaas.knowledge.asset'].sudo().search(
            [('owner_model', '=', self._name), ('owner_id', '=', self.id),
             ('state', '=', 'current')])

    def action_open_assets(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('素材'),
            'res_model': 'corpaas.knowledge.asset', 'view_mode': 'list,form',
            'domain': [('owner_model', '=', self._name), ('owner_id', '=', self.id)],
        }

    def action_reset(self):
        self.write({'state': 'pending', 'last_error': False, 'needs_repair': False, 'repair_fp': False,
                    'repair_attempts': 0, 'transient_fp': False, 'repair_bonus_used': False,
                    'repair_checking': False})
        return True
