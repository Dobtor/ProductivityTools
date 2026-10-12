# -*- coding: utf-8 -*-
"""知識主從的基礎（知識主從改版計畫第 6 節、第 20.2 節）。

· 主控台代碼：每個主控台唯一（主體 corpaas、從屬 dobtor），對外識別一律「代碼:鍵」。
· 可交換的紀錄混入 `corpaas.knowledge.federated.mixin`：
    kb_uid          跨主控台唯一（UUID），範本類以它交換；建立時給、既有資料在 init() 回填
    kb_origin       哪個主控台產生的
    kb_content_hash 內容欄位的雜湊（判斷是否需要同步）
    kb_sync_state   本地／鏡像／待送／已送／退回
    kb_visibility   公開／私有（私有永遠不出這個主控台）
    kb_trust        自己算的／從屬提供／主體
· 鏡像紀錄「內容唯讀、關聯可寫」：內容欄位（`_kb_content_fields`）只有交換同步能改；
  關聯（package_ids、feature_ids…）與本地統計照常可寫——從屬的計畫要把方案掛到鏡像的能力上。
"""
import hashlib
import json
import uuid
from urllib.parse import urlparse

from odoo import _, api, fields, models
from odoo.exceptions import UserError

SYNC_STATES = [('local', '本地'), ('mirror', '鏡像（唯讀）'), ('pending', '待送'), ('sent', '已送主體'),
               ('rejected', '主體退回')]
VISIBILITY = [('public', '公開'), ('private', '私有')]
TRUST = [('own', '自己算的'), ('replica', '從屬提供'), ('master', '主體')]
#: 交換同步寫入時帶的 context（RPC 只能傳 JSON，偽造不了這個物件）
EXCHANGE_SYNC = object()


def console_code(env):
    """這個主控台的代碼（系統參數 corpaas_knowledge.console_code；沒設依網域推：admin.corpaas.com → corpaas）。"""
    icp = env['ir.config_parameter'].sudo()
    code = (icp.get_param('corpaas_knowledge.console_code') or '').strip()
    if code:
        return code
    host = urlparse(icp.get_param('web.base.url') or '').hostname or ''
    parts = [p for p in host.split('.') if p and p not in ('admin', 'www')]
    return (parts[0] if parts else 'local').lower()


def is_exchange_sync(env):
    return env.context.get('knowledge_exchange_sync') is EXCHANGE_SYNC


class KnowledgeFederatedMixin(models.AbstractModel):
    _name = 'corpaas.knowledge.federated.mixin'
    _description = '可跨主控台交換的知識紀錄'

    #: 內容欄位：鏡像時唯讀、決定內容雜湊。各模型覆寫。
    _kb_content_fields = ()
    #: 預設公開或私有（程式知識預設私有，由公開判定改成公開）
    _kb_default_visibility = 'public'

    kb_uid = fields.Char(string='全域識別', index=True, copy=False, readonly=True)
    kb_origin = fields.Char(string='來源主控台', index=True, copy=False, readonly=True)
    kb_content_hash = fields.Char(string='內容雜湊', copy=False, readonly=True)
    kb_sync_state = fields.Selection(SYNC_STATES, string='同步狀態', default='local', copy=False,
                                     readonly=True, index=True)
    kb_visibility = fields.Selection(VISIBILITY, string='公開性', copy=False, readonly=True,
                                     default=lambda self: self._kb_default_visibility)
    kb_trust = fields.Selection(TRUST, string='信任', default='own', copy=False, readonly=True)

    _sql_constraints = [('kb_uid_uniq', 'unique(kb_uid)', '全域識別不能重複。')]

    def init(self):
        """既有資料回填全域識別與來源主控台（欄位沒有預設值：預設值會讓所有舊列拿到同一個 UUID）。"""
        res = super().init() if hasattr(super(), 'init') else None
        if self._abstract or not self._auto:
            return res
        table = self._table
        self.env.cr.execute('SELECT 1 FROM information_schema.columns WHERE table_name=%s AND column_name=%s',
                            (table, 'kb_uid'))
        if not self.env.cr.fetchone():
            return res
        self.env.cr.execute('UPDATE "%s" SET kb_uid = md5(random()::text || id::text || clock_timestamp()::text) '
                            'WHERE kb_uid IS NULL' % table)
        self.env.cr.execute('UPDATE "%s" SET kb_origin = %%s WHERE kb_origin IS NULL' % table,
                            (console_code(self.env),))
        return res

    @api.model_create_multi
    def create(self, vals_list):
        origin = console_code(self.env)
        for vals in vals_list:
            vals.setdefault('kb_uid', uuid.uuid4().hex)
            vals.setdefault('kb_origin', origin)
        recs = super().create(vals_list)
        recs._kb_refresh_hash()
        return recs

    def write(self, vals):
        content = set(vals) & set(self._kb_content_fields)
        if content and not is_exchange_sync(self.env):
            mirrors = self.filtered(lambda r: r.kb_sync_state == 'mirror')
            if mirrors:
                raise UserError(_('「%(r)s」是主體的鏡像（唯讀內容）：要修改請到主體，或從這裡送修改意見給主體。'
                                  '（欄位：%(f)s）', r=mirrors[0].display_name, f='、'.join(sorted(content))))
        res = super().write(vals)
        if content:
            self._kb_refresh_hash()
        return res

    def _kb_content_payload(self):
        """內容欄位的可攜表示（關聯欄位轉成全域識別或代碼，不帶本地 id）。"""
        self.ensure_one()
        out = {}
        for name in self._kb_content_fields:
            field = self._fields.get(name)
            if not field:
                continue
            value = self[name]
            if field.type in ('many2one', 'many2many', 'one2many'):
                out[name] = sorted(r.kb_uid if 'kb_uid' in r._fields else (getattr(r, 'code', None) or r.display_name)
                                   for r in value)
            elif field.type in ('date', 'datetime'):
                out[name] = fields.Datetime.to_string(value) if value else False
            else:
                out[name] = value if value is not False else None
        return out

    def _kb_refresh_hash(self):
        for rec in self:
            payload = json.dumps(rec._kb_content_payload(), ensure_ascii=False, sort_keys=True, default=str)
            digest = hashlib.sha1(payload.encode('utf-8')).hexdigest()[:20]
            if rec.kb_content_hash != digest:
                models.Model.write(rec.with_context(knowledge_exchange_sync=EXCHANGE_SYNC),
                                   {'kb_content_hash': digest})
        return True


class KnowledgeCapabilityFederated(models.Model):
    _name = 'corpaas.knowledge.capability'
    _inherit = ['corpaas.knowledge.capability', 'corpaas.knowledge.federated.mixin']
    _kb_content_fields = ('name', 'pain', 'outcome', 'differentiator', 'color')


class KnowledgeScenarioFederated(models.Model):
    _name = 'corpaas.knowledge.scenario'
    _inherit = ['corpaas.knowledge.scenario', 'corpaas.knowledge.federated.mixin']
    _kb_content_fields = ('name', 'narrative', 'glossary', 'seed_json', 'required_module_names')


class KnowledgeSeedPackFederated(models.Model):
    _name = 'corpaas.knowledge.seed_pack'
    _inherit = ['corpaas.knowledge.seed_pack', 'corpaas.knowledge.federated.mixin']
    _kb_content_fields = ('name', 'description', 'seed_json', 'required_module_names')


class KnowledgeRoleFederated(models.Model):
    _name = 'corpaas.knowledge.role'
    _inherit = ['corpaas.knowledge.role', 'corpaas.knowledge.federated.mixin']
    _kb_content_fields = ('name', 'group_xmlids')


class KnowledgeRuleFederated(models.Model):
    _name = 'corpaas.knowledge.rule'
    _inherit = ['corpaas.knowledge.rule', 'corpaas.knowledge.federated.mixin']
    _kb_content_fields = ('name', 'kind', 'track', 'value', 'scope_module')


class KnowledgeCodeDefFederated(models.Model):
    _name = 'corpaas.knowledge.code_def'
    _inherit = ['corpaas.knowledge.code_def', 'corpaas.knowledge.federated.mixin']
    _kb_content_fields = ('summary_json',)
    _kb_default_visibility = 'private'


class KnowledgeCodeFactFederated(models.Model):
    _name = 'corpaas.knowledge.code_fact'
    _inherit = ['corpaas.knowledge.code_fact', 'corpaas.knowledge.federated.mixin']
    _kb_content_fields = ('fact_json',)
    _kb_default_visibility = 'private'


class KnowledgeModuleSummaryFederated(models.Model):
    _name = 'corpaas.knowledge.module_summary'
    _inherit = ['corpaas.knowledge.module_summary', 'corpaas.knowledge.federated.mixin']
    _kb_content_fields = ('summary_json', 'facts_json')
    _kb_default_visibility = 'private'

    git_revision = fields.Char(string='git 版本', readonly=True,
                               help='讀摘要時該模組的 git 版本（主控台的版本識別），與目錄雜湊一起存（計畫 #1）')


class KnowledgeCodeTreeFederated(models.Model):
    _inherit = 'corpaas.knowledge.code_tree'

    python_version = fields.Char(string='Python 版本', readonly=True,
                                 help='段落雜湊用 ast.dump，Python 小版本不同結果就不同（計畫 #2）')


class SolutionPackageFederated(models.Model):
    _inherit = 'infrastructure.solution.package'

    knowledge_global_key = fields.Char(
        string='方案全域識別', copy=False, index=True,
        help='跨主控台認方案用：「主控台代碼:方案代碼」。主體的方案知識鏡像到從屬時，以這個鍵對應。')
    knowledge_upstream_key = fields.Char(
        string='對應主體方案', copy=False, index=True,
        help='從屬：這個方案對應主體的哪個方案（填主體方案的全域識別）；鏡像的方案知識掛到這個方案')

    _sql_constraints = [('knowledge_global_key_uniq', 'unique(knowledge_global_key)',
                         '方案全域識別不能重複。')]

    def init(self):
        res = super().init() if hasattr(super(), 'init') else None
        self.env.cr.execute("SELECT 1 FROM information_schema.columns WHERE table_name=%s AND column_name=%s",
                            (self._table, 'knowledge_global_key'))
        if self.env.cr.fetchone():
            self.env.cr.execute('UPDATE "%s" SET knowledge_global_key = %%s || \':pkg\' || id '
                                'WHERE knowledge_global_key IS NULL' % self._table, (console_code(self.env),))
        return res

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        code = console_code(self.env)
        for rec in recs.filtered(lambda r: not r.knowledge_global_key):
            rec.knowledge_global_key = '%s:pkg%s' % (code, rec.id)
        return recs

    @api.model
    def _knowledge_seed_public_base_url(self):
        """安裝時種公開網址：只有主體預設 www.corpaas.com（從屬裝上去不能指到主體網域）。"""
        icp = self.env['ir.config_parameter'].sudo()
        if not icp.get_param('corpaas_knowledge.public_base_url') and console_code(self.env) == 'corpaas':
            icp.set_param('corpaas_knowledge.public_base_url', 'https://www.corpaas.com')
        return True

    def knowledge_match_key(self):
        """認方案的鍵：從屬有填對應主體方案就用它，否則用自己的全域識別。"""
        self.ensure_one()
        return self.knowledge_upstream_key or self.knowledge_global_key
