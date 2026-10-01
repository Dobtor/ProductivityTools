# -*- coding: utf-8 -*-
"""工時範本（能力 × 工項）與校正歷史。"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from ..services import calc

#: 工項分類沿用 CBMC 已交付報價（設計文件「出口三」）：需求設定／資料移轉／教育訓練／上線部署／專案管理。
ACTIVITIES = [
    ('requirements', '需求設定'),
    ('migration', '資料移轉'),
    ('training', '教育訓練'),
    ('golive', '上線部署'),
    ('pm', '專案管理'),
]

#: 工時回寫比對用的別名（舊版標籤、常見寫法）；比對是整個詞，不是子字串。
ACTIVITY_ALIASES = {
    'requirements': ('需求訪談', '需求', 'req'),
    'migration': ('資料轉檔', '轉檔'),
    'training': ('訓練',),
    'golive': ('上線陪跑', '上線', 'go-live'),
    'pm': ('專管',),
}

DRIVERS = [
    ('none', '固定'),
    ('companies', '公司數'),
    ('users', '使用者數'),
    ('roles', '角色數'),
    ('records_100', '主資料（每百筆）'),
    ('integrations', '串接數'),
    ('sessions', '訓練場次'),
]


class EffortTemplate(models.Model):
    _name = 'corpaas.knowledge.effort_template'
    _description = '工時範本（能力 × 工項）'
    _order = 'capability_id, activity'

    capability_id = fields.Many2one(
        'corpaas.knowledge.capability', string='能力', ondelete='cascade', index=True,
        help='留空＝通用工項：每張建議書算一次（例如專案管理、上線部署）。')
    activity = fields.Selection(ACTIVITIES, string='工項', required=True)
    base_days = fields.Float(string='基礎人天', required=True, default=1.0,
                             help='由工時回寫以移動平均校正。')
    initial_base_days = fields.Float(string='初始基礎人天', readonly=True,
                                     help='建立時的 base_days；移動平均的第一個樣本。')
    driver = fields.Selection(DRIVERS, string='驅動因子', required=True, default='none')
    per_unit_days = fields.Float(string='每單位人天')
    unit_size = fields.Float(string='單位大小', default=1.0,
                             help='驅動量每滿多少算一個單位（例：使用者每 20 人一個單位）。')
    note = fields.Char()
    calibration_ids = fields.One2many('corpaas.knowledge.effort_calibration', 'template_id',
                                      string='校正歷史')
    calibration_count = fields.Integer(compute='_compute_calibration_count', store=True,
                                       string='校正次數')

    _sql_constraints = [
        ('cap_activity_uniq', 'unique(capability_id, activity)',
         '同一能力同一工項只能有一個範本'),
    ]

    @api.constrains('capability_id', 'activity')
    def _check_generic_unique(self):
        # ☠️ unique 約束擋不到 NULL：通用工項（capability 空）要自己擋。
        for rec in self.filtered(lambda r: not r.capability_id):
            if self.search_count([('capability_id', '=', False),
                                  ('activity', '=', rec.activity), ('id', '!=', rec.id)]):
                raise ValidationError(_('通用工項「%s」已經有範本') % dict(ACTIVITIES)[rec.activity])

    @api.depends('calibration_ids')
    def _compute_calibration_count(self):
        for rec in self:
            rec.calibration_count = len(rec.calibration_ids)

    @api.depends('capability_id', 'activity')
    def _compute_display_name(self):
        labels = dict(ACTIVITIES)
        for rec in self:
            rec.display_name = '%s／%s' % (rec.capability_id.name or '通用',
                                          labels.get(rec.activity, rec.activity))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals.setdefault('initial_base_days', vals.get('base_days', 1.0))
        return super().create(vals_list)

    def days_for(self, driver_qty):
        self.ensure_one()
        return calc.effort_days(self.base_days, self.per_unit_days, self.unit_size, driver_qty)

    def calibrate(self, actual_days, driver_qty, proposal=None, window=5):
        """用一筆實際人天校正 base_days（移動平均），並留下歷史。"""
        self.ensure_one()
        obs = calc.observed_base(actual_days, self.per_unit_days, self.unit_size, driver_qty)
        previous = self.calibration_ids.sorted('id').mapped('observed_base')
        new_base = calc.moving_average(self.initial_base_days, previous + [obs], window)
        self.env['corpaas.knowledge.effort_calibration'].create({
            'template_id': self.id,
            'proposal_id': proposal.id if proposal else False,
            'estimated_days': self.days_for(driver_qty),
            'actual_days': actual_days,
            'driver_qty': driver_qty,
            'observed_base': obs,
            'old_base_days': self.base_days,
            'new_base_days': new_base,
        })
        self.base_days = new_base
        return new_base


class EffortCalibration(models.Model):
    _name = 'corpaas.knowledge.effort_calibration'
    _description = '工時範本校正歷史'
    _order = 'id desc'

    template_id = fields.Many2one('corpaas.knowledge.effort_template', required=True,
                                  ondelete='cascade', index=True)
    proposal_id = fields.Many2one('corpaas.knowledge.proposal', ondelete='set null', index=True)
    estimated_days = fields.Float(string='估算人天')
    actual_days = fields.Float(string='實際人天')
    driver_qty = fields.Float(string='驅動量')
    observed_base = fields.Float(string='反推基礎人天')
    old_base_days = fields.Float(string='校正前')
    new_base_days = fields.Float(string='校正後')
    create_date = fields.Datetime(string='校正時間', readonly=True)
