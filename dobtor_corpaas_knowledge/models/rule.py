# -*- coding: utf-8 -*-
"""環境規則表（計畫第 24、33 項）：不同方案的「環境條件」存成資料，不寫死在程式、不必部署。

★ 程式裡的寫死值保留為內建預設（規則表清空也不失去保護）；規則表的規則疊加在上面。
★ 軟硬兩軌：每條規則標「提示用」（寫進給 AI 的指示）或「驗證用」（系統一定執行，不靠 AI 自律）。
  ☠️ 實機（社群電商方案）：提示詞寫了「公司改名用 base.main_company」，AI 仍建了 company_rename；
    加上重播時的硬性檢查才擋住。能檢查的規則一律要有驗證版。
☠️ 為什麼要有規則表：方案 14 的 23 個修正裡約一半是環境條件（要藏的元素、空白判斷、白名單、清除方法、
  示範資料禁止事項、排序關鍵字、前台頁），每一個都改程式、部署一次，共 20 次部署。
"""
import json
import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

KINDS = [
    ('hide_selector', '截圖時隱藏的元素'),
    ('mask_text', '截圖時遮蔽的文字'),
    ('empty_selector', '空白頁判斷'),
    ('gate_allow_model', '安全檢查白名單（設定類模型）'),
    ('purge_reset_method', '清除客戶資料前的退回方法'),
    ('seed_forbid_model', '示範資料禁止建立'),
    ('seed_prompt', '示範資料提示'),
    ('rank_keyword', '章節排序關鍵字'),
    ('front_route', '前台標準頁'),
]
#: 種類 → 預設軌道（驗證用＝系統執行；提示用＝寫進 AI 指示）
DEFAULT_TRACK = {'seed_prompt': 'prompt'}
#: 值要是 JSON 物件的種類與必填鍵
JSON_KEYS = {
    'mask_text': ('pattern', 'replace'),
    'empty_selector': ('present',),
    'seed_forbid_model': ('model',),
    'rank_keyword': ('keyword', 'like_module'),
    'front_route': ('module', 'url', 'name', 'audiences'),
}


class KnowledgeRule(models.Model):
    _name = 'corpaas.knowledge.rule'
    _description = '方案知識環境規則'
    _order = 'kind, sequence, id'

    name = fields.Char(required=True, help='一句話說明這條規則在處理什麼')
    kind = fields.Selection(KINDS, required=True, index=True)
    track = fields.Selection([('check', '驗證用（系統執行）'), ('prompt', '提示用（寫進 AI 指示）')],
                             required=True, default='check',
                             help='能由系統檢查的一律用驗證用；只有沒辦法檢查的才是提示用')
    value = fields.Text(required=True, help='依種類：CSS 選擇器、模型名、方法名、文字，或 JSON 物件')
    scope_module = fields.Char(string='只套用於模組',
                               help='方案範圍內有這個模組才套用；空白＝全部方案')
    package_id = fields.Many2one('infrastructure.solution.package', string='只套用於方案',
                                 ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    source = fields.Selection([('builtin', '內建'), ('human', '人工'), ('ai', 'AI 提議')],
                              default='human', required=True)
    evidence = fields.Text(string='依據', help='為什麼有這條規則（哪個方案、哪次失敗）')

    @api.constrains('kind', 'value')
    def _check_value(self):
        for rec in self:
            if rec.kind in JSON_KEYS:
                try:
                    data = json.loads(rec.value or '')
                except ValueError:
                    raise ValidationError(_('規則「%s」的值要是 JSON 物件') % rec.name)
                missing = [k for k in JSON_KEYS[rec.kind] if not isinstance(data, dict) or k not in data]
                if missing:
                    raise ValidationError(_('規則「%(n)s」缺少：%(k)s', n=rec.name, k='、'.join(missing)))
                if rec.kind == 'mask_text':
                    re.compile(data['pattern'])
            elif rec.kind == 'purge_reset_method' and not re.fullmatch(
                    r'_?(action|button)_[a-z0-9_]+', (rec.value or '').strip()):
                raise ValidationError(_('清除前的退回方法只能是 action_／button_ 開頭：%s') % rec.value)
            elif rec.kind == 'gate_allow_model' and not re.fullmatch(
                    r'[a-z0-9_]+(\.[a-z0-9_]+)+', (rec.value or '').strip()):
                raise ValidationError(_('白名單要填模型技術名：%s') % rec.value)

    @api.onchange('kind')
    def _onchange_kind(self):
        self.track = DEFAULT_TRACK.get(self.kind, 'check')

    @api.model
    def values(self, kind, package=None, track=None, scope=None):
        """取某種類目前生效的規則值（JSON 種類回傳 dict）：全域＋符合模組範圍＋這個方案的。"""
        dom = [('kind', '=', kind)]
        if track:
            dom.append(('track', '=', track))
        dom += ['|', ('package_id', '=', False), ('package_id', '=', package.id if package else 0)]
        scope = set(scope or (package._knowledge_scope_names() if package else ()))
        out = []
        for r in self.sudo().search(dom):
            if r.scope_module and r.scope_module not in scope:
                continue
            out.append(json.loads(r.value) if kind in JSON_KEYS else r.value.strip())
        return out

    @api.model
    def payload(self, package=None):
        """截圖程式要的規則（放進 job.json）。"""
        return {'hide': self.values('hide_selector', package),
                'mask': self.values('mask_text', package),
                'empty': self.values('empty_selector', package)}


class SolutionPackageRules(models.Model):
    _inherit = 'infrastructure.solution.package'

    def _knowledge_scope_names(self):
        """方案範圍內的模組名（規則的模組範圍用）：最近一次盤點記下的範圍。"""
        self.ensure_one()
        try:
            return set(json.loads(self.knowledge_scope_snapshot or '[]'))
        except (ValueError, AttributeError):
            return set()
