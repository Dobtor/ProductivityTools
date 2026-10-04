# -*- coding: utf-8 -*-
"""設定開關與功能分類（基礎／進階 × 標準／專用 ＋ 方案核心）。

定案規則：
  · 只分析黃金庫「已開啟」的開關（module_ 已裝、group_ 已勾、參數不是預設值）——
    沒開的不屬於方案預設提供的範圍，不盤、不記錄。
  · 能被設定關掉的就是「進階」，不論模組是不是 BOM 帶進來的；
    但關掉會連帶移除 BOM 其他模組的安裝模組型開關，實際上關不掉，不算進階。
  · 來源依「提供功能的模組」：官方原生＝標準、其他（自有、OCA…）＝專用。
  · 方案核心：功能所屬模組直接列在該方案的 BOM 裡（各方案各自判斷）。

分類是「每個方案各一筆」（corpaas.knowledge.feature.class）：方案核心本來就因方案而異，
相依模組是否「只因開關才裝」也看該方案其他模組需不需要它。

★ 方案屬性層：功能點、開關是全域一筆（同一個 sale 畫面被兩個方案共用時只有一筆），但
  「依黃金庫而異」的值（使用量、是否被專用模組改過、繼承鏈模組、開關的目前值與連帶移除）
  一律存在每個方案一筆的記錄上；全域欄位只當沒有方案記錄時的退回值與彙總顯示。
  ☠️ 存在全域欄位時，兩個方案輪流更新會互相覆蓋：A 的 AI 排序用到 B 客戶的使用量。
"""
import json

from odoo import api, fields, models

TOGGLE_KINDS = [('module', '安裝模組'), ('group', '開啟群組'), ('param', '參數')]
TIERS = [('base', '基礎'), ('advanced', '進階')]
BASIS = [
    ('base', '直接安裝'),
    ('module', '設定安裝的模組'),
    ('module_dep', '設定安裝模組的相依'),
    ('group', '設定開啟的群組'),
    ('param', '設定參數'),
]
CLASSIFICATIONS = [
    ('own_adv', '專用進階'),
    ('own_base', '專用功能'),
    ('std_adv', '標準進階'),
    ('std_base', '標準功能'),
]
#: AI 歸類／圈選的優先順序（差異化賣點在前）
CLASS_RANK = {'own_adv': 0, 'own_base': 1, 'std_adv': 2, 'std_base': 3}


def classification_of(origin, tier):
    return ('std' if origin == 'odoo' else 'own') + ('_adv' if tier == 'advanced' else '_base')


class KnowledgeToggle(models.Model):
    _name = 'corpaas.knowledge.toggle'
    _description = '設定開關'
    _order = 'app, name'

    name = fields.Char(string='設定欄位', required=True, index=True, readonly=True)
    kind = fields.Selection(TOGGLE_KINDS, string='類型', required=True, readonly=True)
    target = fields.Char(string='目標', readonly=True, help='模組技術名、群組 xmlid 或參數 key')
    module = fields.Char(string='提供模組', readonly=True,
                         help='安裝模組型＝被安裝的模組；其他＝定義這個設定的模組')
    module_origin = fields.Selection([('custom', '專用'), ('odoo', '標準')], string='來源',
                                     readonly=True)
    label = fields.Char(string='名稱', readonly=True)
    help_text = fields.Text(string='說明', readonly=True)
    path = fields.Char(string='開啟路徑', readonly=True, help='設定 › 應用 › 區塊 › 項目')
    app = fields.Char(readonly=True)
    doc_url = fields.Char(string='官方文件', readonly=True)
    value = fields.Char(string='目前值', readonly=True)
    downstream = fields.Char(string='關閉連帶移除', readonly=True,
                             help='取消勾選會一併卸載的已安裝模組（Odoo 本身的 downstream_dependencies）')
    affected_models = fields.Char(string='影響的模型', readonly=True,
                                  help='參數型：原始碼裡讀取這個參數的模型')
    elements_json = fields.Text(string='控制的元素', readonly=True,
                                help='群組型：受這個群組控制的欄位／按鈕（JSON）')
    package_ids = fields.Many2many(
        'infrastructure.solution.package', 'corpaas_knowledge_toggle_package_rel',
        'toggle_id', 'package_id', string='已開啟的方案', readonly=True)
    last_seen = fields.Datetime(readonly=True)

    _sql_constraints = [('toggle_unique', 'unique(name)', '同一個設定欄位只有一筆')]

    def locks_bom(self, package):
        """關掉會拆掉方案的 BOM 模組＝實際上關不掉（它啟用的功能算基礎）。"""
        self.ensure_one()
        return self.kind == 'module' and bool(self.downstream_bom(package))

    state_ids = fields.One2many('corpaas.knowledge.toggle.state', 'toggle_id',
                                string='各方案狀態')

    def state_for(self, package):
        self.ensure_one()
        return self.state_ids.filtered(lambda s: s.package_id == package)[:1]

    def _per_package(self, package, fname):
        """依方案取值：有方案狀態用它，沒有才退回全域（最近一次盤點）的值。"""
        st = self.state_for(package) if package else None
        return st[fname] if st else self[fname]

    def downstream_bom(self, package):
        """關閉會連帶移除的模組裡，屬於這個方案 BOM 的（說明書警示用）。"""
        self.ensure_one()
        bom = set(package._provision_module_names())
        down = self._per_package(package, 'downstream') or ''
        return sorted(set(filter(None, down.split(','))) & bom)


class KnowledgeToggleState(models.Model):
    """開關在某個方案黃金庫上的狀態（依黃金庫而異的值都在這裡）。"""
    _name = 'corpaas.knowledge.toggle.state'
    _description = '設定開關（各方案狀態）'

    toggle_id = fields.Many2one('corpaas.knowledge.toggle', required=True, ondelete='cascade',
                                index=True)
    package_id = fields.Many2one('infrastructure.solution.package', required=True,
                                 ondelete='cascade', index=True)
    value = fields.Char(string='目前值')
    downstream = fields.Char(string='關閉連帶移除')
    affected_models = fields.Char(string='影響的模型')
    elements_json = fields.Text(string='控制的元素')
    last_seen = fields.Datetime()

    _sql_constraints = [('state_unique', 'unique(toggle_id, package_id)', '一個方案一筆')]


class KnowledgeFeatureClass(models.Model):
    _name = 'corpaas.knowledge.feature.class'
    _description = '功能分類（每個方案一筆）'
    _order = 'package_id, classification'

    feature_id = fields.Many2one('corpaas.knowledge.feature', required=True,
                                 ondelete='cascade', index=True)
    package_id = fields.Many2one('infrastructure.solution.package', required=True,
                                 ondelete='cascade', index=True)
    tier = fields.Selection(TIERS, string='層級', required=True, default='base')
    basis = fields.Selection(BASIS, string='判定依據', required=True, default='base')
    toggle_ids = fields.Many2many('corpaas.knowledge.toggle',
                                  'corpaas_knowledge_feature_class_toggle_rel',
                                  'class_id', 'toggle_id', string='啟用開關')
    behavior_toggle_ids = fields.Many2many('corpaas.knowledge.toggle',
                                           'corpaas_knowledge_feature_class_behavior_rel',
                                           'class_id', 'toggle_id', string='進階行為',
                                           help='行為受這些參數型設定影響（層級不變）')
    advanced_elements = fields.Text(
        string='進階元素', help='JSON：基礎畫面上受群組開關控制的欄位／按鈕 '
                             '[{element, toggle, origin, core}]')
    core = fields.Boolean(string='方案核心', index=True,
                          help='功能所屬模組直接列在這個方案的 BOM 裡')
    classification = fields.Selection(CLASSIFICATIONS, string='功能分類', index=True)
    # —— 方案屬性層：依這個方案的黃金庫／租戶而異的值 ——
    usage_score = fields.Float(string='租戶使用量')
    usage_source = fields.Selection(
        [('model', '模型層級'), ('measured', '實測'), ('estimated', '推估')], string='使用量來源')
    customized = fields.Boolean(string='專用模組改過')
    custom_modules = fields.Char(string='改動的專用模組')
    custom_elements = fields.Text(string='專用模組加的元素')
    view_modules = fields.Char(string='繼承鏈模組')
    fp_dirty = fields.Boolean(string='指紋待重算')

    _sql_constraints = [('class_unique', 'unique(feature_id, package_id)', '一個方案一筆')]

    def toggle_paths(self):
        self.ensure_one()
        return [t.path for t in self.toggle_ids if t.path]

    def elements(self):
        self.ensure_one()
        try:
            return json.loads(self.advanced_elements or '[]')
        except ValueError:
            return []

    def as_payload(self):
        """給出口（說明書 prompt、help API、行銷）的精簡資訊。"""
        self.ensure_one()
        return {
            'classification': self.classification,
            'classification_label': dict(CLASSIFICATIONS).get(self.classification),
            'tier': self.tier, 'core': self.core,
            'toggle_paths': self.toggle_paths(),
            'downstream_bom': sorted({m for t in self.toggle_ids
                                      for m in t.downstream_bom(self.package_id)}),
            'usage_score': self.usage_score, 'customized': self.customized,
            'advanced_elements': self.elements(),
            'behavior': [{'label': t.label, 'path': t.path, 'value': t.value}
                         for t in self.behavior_toggle_ids],
        }


class KnowledgeFeature(models.Model):
    _inherit = 'corpaas.knowledge.feature'

    class_ids = fields.One2many('corpaas.knowledge.feature.class', 'feature_id',
                                string='功能分類（各方案）')

    def class_for(self, package):
        self.ensure_one()
        return self.class_ids.filtered(lambda c: c.package_id == package)[:1]

    def attr_for(self, package, fname):
        """依方案取屬性（usage_score、customized、custom_elements…）：有方案記錄用它，
        沒有才退回全域欄位（測試資料、尚未盤點過的舊資料）。"""
        self.ensure_one()
        row = self.class_for(package) if package else None
        return row[fname] if row else self[fname]

    def _sync_global_aggregates(self):
        """全域欄位只當彙總顯示：使用量取各方案最大、改過＝任一方案改過。"""
        for rec in self:
            rows = rec.class_ids
            if not rows:
                continue
            best = max(rows, key=lambda r: r.usage_score or 0)
            rec.write({'usage_score': best.usage_score or 0,
                       'usage_source': best.usage_source or False,
                       'customized': any(rows.mapped('customized'))})
