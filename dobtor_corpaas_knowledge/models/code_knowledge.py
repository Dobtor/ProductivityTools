# -*- coding: utf-8 -*-
"""程式知識的結構層（計畫第 51 項）：程式碼版本身分、方法定義、繼承鏈。不花 AI。

判斷順序（AI 讀程式只在最後一步，語意層另做）：
  1. 實例容器的映像摘要（docker inspect）已知 → 官方原碼沿用，結束。
  2. 映像摘要未知 → 讀 Odoo 版號；跟已知版本相同 → 視為同一份。
  3. 版號也不同 → 系統算官方模組的目錄雜湊（找出真正變動的模組）。
  4. 擴充模組：每次比版號＋目錄雜湊（版號不一定有升）。
★ 紀錄掛在程式內容雜湊上，不掛在實例或映像上：映像不同但方法相同照樣共用；
  映像相同但實例多一個覆寫模組，繼承鏈不同就不會誤用。
"""
import hashlib
import json
import logging
import re
import shlex

from odoo import api, fields, models

from ..services import remote, scripts

_logger = logging.getLogger(__name__)
#: 主機上存放抽出原碼的目錄（AI Runner 唯讀掛到 /odoo-core）
CORE_ROOT = '/srv/ai-src/odoo'


class KnowledgeCodeTree(models.Model):
    _name = 'corpaas.knowledge.code_tree'
    _description = '程式碼版本（官方原碼）'
    _order = 'last_seen desc, id desc'

    name = fields.Char(compute='_compute_name')
    image_digest = fields.Char(string='映像摘要', required=True, index=True, readonly=True)
    odoo_version = fields.Char(string='Odoo 版號', readonly=True, index=True)
    match = fields.Selection([('version', '版號相同、沿用'), ('hashed', '算過目錄雜湊')],
                             string='怎麼確認的', readonly=True)
    core_hashes = fields.Text(string='官方模組雜湊', readonly=True, help='{模組: 目錄雜湊}')
    tree_hash = fields.Char(string='整棵雜湊', readonly=True)
    core_path = fields.Char(string='原碼抽取位置', readonly=True,
                            help='主機上抽出的 Odoo 原碼目錄（唯讀掛進 AI Runner 給 AI 讀，計畫第 49 項）')
    first_seen = fields.Datetime(default=fields.Datetime.now, readonly=True)
    last_seen = fields.Datetime(default=fields.Datetime.now, readonly=True)

    _sql_constraints = [('digest_uniq', 'unique(image_digest)', '同一個映像只記一筆')]

    def _compute_name(self):
        for rec in self:
            rec.name = '%s（%s）' % (rec.odoo_version or '?', (rec.image_digest or '')[7:19])


class KnowledgeCodeDef(models.Model):
    _name = 'corpaas.knowledge.code_def'
    _description = '方法定義（一個類別裡一個方法的寫法）'
    _rec_name = 'method'

    def_hash = fields.Char(string='正規化雜湊', required=True, index=True, readonly=True)
    method = fields.Char(required=True, readonly=True)
    module = fields.Char(readonly=True, help='定義所在模組（空白＝Odoo 核心 BaseModel）')
    path = fields.Char(readonly=True)
    line_start = fields.Integer(readonly=True)
    line_end = fields.Integer(readonly=True)
    summary_json = fields.Text(string='AI 摘要', readonly=True,
                               help='語意層：這段程式做什麼（AI 讀過才有；雜湊沒變就沿用）')

    _sql_constraints = [('def_uniq', 'unique(def_hash, method)', '同一段程式只記一筆')]


class KnowledgeCodeFact(models.Model):
    _name = 'corpaas.knowledge.code_fact'
    _description = '方法的繼承鏈（實際執行的那一整條）'
    _rec_name = 'subject'

    subject = fields.Char(string='主體', required=True, index=True, readonly=True,
                          help='model.method')
    chain_hash = fields.Char(string='繼承鏈雜湊', required=True, index=True, readonly=True)
    def_ids = fields.Many2many('corpaas.knowledge.code_def', string='依序的定義', readonly=True)
    fact_json = fields.Text(string='結論', readonly=True,
                            help='語意層：前提、狀態轉換、建立的記錄、開啟的精靈、需要的設定、錯誤訊息')
    verified = fields.Boolean(string='實拍證實', readonly=True)
    state = fields.Selection([('structural', '只有結構'), ('current', '有效'), ('stale', '過期'),
                              ('suspect', '可疑')], default='structural', required=True, readonly=True)

    _sql_constraints = [('chain_uniq', 'unique(subject, chain_hash)', '同一條繼承鏈只記一筆')]


class SolutionPackageCode(models.Model):
    _inherit = 'infrastructure.solution.package'

    def _knowledge_code_identity(self, instance, db_name):
        """方案主實例的程式碼身分（版號優先，必要時才算雜湊）。回傳寫進方案檔案的 dict。"""
        self.ensure_one()
        Tree = self.env['corpaas.knowledge.code_tree'].sudo()
        now = fields.Datetime.now()
        res = remote.run(instance.server_id, "docker inspect -f '{{.Image}}' %s"
                         % shlex.quote(instance.odoo_container), dont_raise=True)
        digest = (getattr(res, 'stdout', '') or '').strip()
        if not digest.startswith('sha256:'):
            return {'error': '讀不到映像摘要：%s' % digest[:200]}
        tree = Tree.search([('image_digest', '=', digest)], limit=1)
        how = 'image'
        if not tree:
            version = self._knowledge_odoo_build(instance)
            # ★ 只有帶建置日期的版號（例如 18.0.20260901）才能當「同一份」：純「18.0」每個映像都一樣
            same = Tree.search([('odoo_version', '=', version)], limit=1) \
                if re.search(r'20\d{6}', version or '') else Tree
            if same:
                tree = Tree.create({'image_digest': digest, 'odoo_version': same.odoo_version,
                                    'match': 'version', 'core_hashes': same.core_hashes,
                                    'tree_hash': same.tree_hash})
                how = 'version'
            else:
                core = remote.shell_json(self.env, instance, db_name, scripts.module_hash_script(core=True))
                hashes = {m: d['hash'] for m, d in core.items() if d.get('core')}
                tree = Tree.create({'image_digest': digest, 'odoo_version': version,
                                    'match': 'hashed', 'core_hashes': json.dumps(hashes, sort_keys=True),
                                    'tree_hash': _hash(hashes)})
                how = 'hashed'
        tree.last_seen = now
        if not tree.core_path:
            tree.core_path = self._knowledge_extract_core(instance, digest)
        addons = remote.shell_json(self.env, instance, db_name, scripts.module_hash_script(core=False))
        prev = (self.knowledge_profile().get('code') or {}).get('addons') or {}
        cur = {m: {'version': d.get('version'), 'hash': d.get('hash')} for m, d in addons.items()}
        changed = sorted(m for m in cur if prev.get(m) != cur[m])
        return {'digest': digest, 'odoo_version': tree.odoo_version, 'match': how,
                'addons': cur, 'changed_addons': changed if prev else [],
                'checked': fields.Datetime.to_string(now)}

    def _knowledge_extract_core(self, instance, digest):
        """把映像裡的 Odoo 原碼抽到主機 CORE_ROOT/<摘要前 12 碼>（每個映像一份，已有就不再抽）。

        給 AI Runner 唯讀掛載（一次掛 CORE_ROOT，所有版本都看得到）。失敗回空字串，不擋流程。"""
        server = instance.server_id
        try:
            if hasattr(server, '_assert_disk_room'):
                server._assert_disk_room('抽出 Odoo 原碼', need_gb=2)
            ctr = shlex.quote(instance.odoo_container)
            dest = '%s/%s' % (CORE_ROOT, digest.split(':', 1)[-1][:12])
            cmd = (
                "set -e; D=%(d)s; if [ ! -d \"$D\" ]; then "
                "P=$(docker exec %(c)s python3 -c 'import odoo,os; print(os.path.dirname(odoo.__file__))'); "
                "T=$(docker create %(img)s); mkdir -p \"$D.tmp\"; "
                "docker cp \"$T:$P\" \"$D.tmp/odoo\"; docker rm \"$T\" >/dev/null; "
                "mv \"$D.tmp\" \"$D\"; chmod -R a+rX \"$D\"; fi; echo \"$D\""
            ) % {'d': shlex.quote(dest), 'c': ctr, 'img': shlex.quote(digest)}
            res = remote.run(server, cmd, dont_raise=True)
            out = (getattr(res, 'stdout', '') or '').strip().splitlines()
            return out[-1] if out and out[-1] == dest else ''
        except Exception as e:  # noqa: BLE001
            _logger.warning('[knowledge] 抽出 Odoo 原碼失敗：%s', e)
            return ''

    def _knowledge_odoo_build(self, instance):
        """容器裡 Odoo 的建置版號（官方映像是 deb 套件版號，含建置日期）；讀不到退回 release.version。"""
        cmd = ("docker exec %s sh -c \"dpkg-query -W -f='\\${Version}' odoo 2>/dev/null || "
               "python3 -c 'import odoo.release as r; print(r.version)'\"" % shlex.quote(instance.odoo_container))
        res = remote.run(instance.server_id, cmd, dont_raise=True)
        return (getattr(res, 'stdout', '') or '').strip()[:64]

    def _knowledge_code_chains(self, instance, db_name, targets):
        """方法的繼承鏈：記下每段定義與整條鏈（不讀檔、不花 AI）。回傳 {subject: code_fact}。"""
        self.ensure_one()
        if not targets:
            return {}
        data = remote.shell_json(self.env, instance, db_name,
                                 scripts.code_def_script(sorted({tuple(t) for t in targets})))
        Def = self.env['corpaas.knowledge.code_def'].sudo()
        Fact = self.env['corpaas.knowledge.code_fact'].sudo()
        out = {}
        for subject, chain in (data or {}).items():
            method = subject.rsplit('.', 1)[1]
            defs = Def.browse()
            for d in chain:
                rec = Def.search([('def_hash', '=', d['hash']), ('method', '=', method)], limit=1)
                if not rec:
                    rec = Def.create({'def_hash': d['hash'], 'method': method, 'module': d.get('module'),
                                      'path': d.get('file'), 'line_start': d.get('line'),
                                      'line_end': d.get('end')})
                defs |= rec
            chain_hash = _hash([d['hash'] for d in chain])
            fact = Fact.search([('subject', '=', subject), ('chain_hash', '=', chain_hash)], limit=1)
            if not fact:
                # 同一主體的舊鏈：有結論的標過期（語意層重讀時只讀變動的那段）
                Fact.search([('subject', '=', subject), ('state', '=', 'current')]).write({'state': 'stale'})
                fact = Fact.create({'subject': subject, 'chain_hash': chain_hash,
                                    'def_ids': [(6, 0, defs.ids)]})
            out[subject] = fact
        return out


def _hash(data):
    return hashlib.sha1(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]
