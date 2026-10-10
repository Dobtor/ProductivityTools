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

from ..services import hub_client, remote, scripts

_logger = logging.getLogger(__name__)
#: 主機上存放抽出原碼的目錄（AI Runner 唯讀掛到 /odoo-core）
CORE_ROOT = '/srv/ai-src/odoo'
#: 方法定義在 Odoo 核心（BaseModel 等，沒有模組）時記的模組名
CORE_MODULE = '(core)'


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
    server_id = fields.Many2one('infrastructure.server', string='抽在哪台主機', readonly=True,
                                ondelete='set null')
    core_tried = fields.Datetime(string='上次嘗試抽取', readonly=True,
                                 help='抽取失敗後一天內不再試（不要每輪都重來）')
    core_container_path = fields.Char(readonly=True, help='容器裡 Odoo 原碼目錄（對照 Runner 路徑用）')
    changed_core = fields.Text(string='與上一版不同的官方模組', readonly=True,
                               help='算過雜湊時和最近一棵比：只有這些模組裡的方法需要重讀')
    first_seen = fields.Datetime(default=fields.Datetime.now, readonly=True)
    last_seen = fields.Datetime(default=fields.Datetime.now, readonly=True)

    _sql_constraints = [('digest_uniq', 'unique(image_digest)', '同一個映像只記一筆')]

    def _compute_name(self):
        for rec in self:
            rec.name = '%s（%s）' % (rec.odoo_version or '?', (rec.image_digest or '')[7:19])

    @api.model
    def _cron_gc_core(self, days=30):
        """清掉沒人在用的原碼目錄：該映像 days 天沒見過、也沒有最近見過的映像共用同一個目錄。

        ★ 每個映像約 2GB，不清會慢慢吃掉 AI Runner 那台主機的硬碟。只刪 CORE_ROOT 底下的。"""
        old = fields.Datetime.subtract(fields.Datetime.now(), days=days)
        removed = 0
        for tree in self.search([('core_path', '!=', False), ('last_seen', '<', old)]):
            path = tree.core_path
            if self.search_count([('core_path', '=', path), ('last_seen', '>=', old)]):
                continue   # 還有最近的映像（同版號沿用）用著這個目錄
            if not path.startswith(CORE_ROOT + '/') or '..' in path or not tree.server_id:
                continue
            try:
                remote.run(tree.server_id, 'rm -rf %s' % shlex.quote(path))
            except Exception as e:  # noqa: BLE001
                _logger.warning('[knowledge] 清除原碼目錄 %s 失敗：%s', path, e)
                continue
            self.search([('core_path', '=', path)]).write({'core_path': False})
            removed += 1
        return removed


class KnowledgeCodeDef(models.Model):
    _name = 'corpaas.knowledge.code_def'
    _description = '方法定義（一個類別裡一個方法的寫法）'
    _rec_name = 'method'

    def_hash = fields.Char(string='正規化雜湊', required=True, index=True, readonly=True)
    method = fields.Char(required=True, readonly=True)
    module = fields.Char(readonly=True, required=True, help='定義所在模組（(core)＝Odoo 核心 BaseModel）')
    path = fields.Char(readonly=True)
    line_start = fields.Integer(readonly=True)
    line_end = fields.Integer(readonly=True)
    summary_json = fields.Text(string='AI 摘要', readonly=True,
                               help='語意層：這段程式做什麼（AI 讀過才有；雜湊沒變就沿用）')

    _sql_constraints = [('def_uniq', 'unique(def_hash, method, module)', '同一段程式只記一筆')]


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
    fact_text = fields.Text(string='結論（展開）', compute='_compute_fact_text')

    _LABELS = {'preconditions': '前提', 'transitions': '狀態轉換', 'creates': '建立的記錄',
               'opens': '會開的精靈或畫面', 'requires_config': '需要的設定', 'errors': '可能出現的錯誤'}

    @api.depends('fact_json')
    def _compute_fact_text(self):
        for rec in self:
            try:
                data = json.loads(rec.fact_json or '{}')
            except ValueError:
                data = {}
            out = []
            for key, label in self._LABELS.items():
                v = data.get(key)
                if not v:
                    continue
                if key == 'transitions':
                    v = ['%s → %s' % (t.get('from') or '?', t.get('to') or '?') for t in v if isinstance(t, dict)]
                out.append('%s：%s' % (label, '；'.join(map(str, v)) if isinstance(v, list) else v))
            rec.fact_text = '\n'.join(out) or False

    _sql_constraints = [('chain_uniq', 'unique(subject, chain_hash)', '同一條繼承鏈只記一筆')]


class KnowledgeModuleSummary(models.Model):
    _name = 'corpaas.knowledge.module_summary'
    _description = '擴充模組摘要（讀過程式）'
    _rec_name = 'module'
    _order = 'module, id desc'

    module = fields.Char(required=True, index=True, readonly=True)
    dir_hash = fields.Char(string='目錄雜湊', required=True, index=True, readonly=True,
                           help='模組內容沒變（雜湊相同）就沿用，換方案也共用')
    facts_json = fields.Text(string='結構事實', readonly=True,
                             help='系統抽的：說明檔、相依、新增／繼承的模型、狀態值')
    summary_json = fields.Text(string='AI 摘要', readonly=True,
                               help='AI 讀過程式：做什麼、核心規則、跟哪些模組串接、主要模型')
    source = fields.Selection([('ai', 'AI 讀過程式'), ('facts', '只有結構事實')], readonly=True)
    # 畫面用（從 JSON 展開，唯讀）
    title = fields.Char(string='模組名稱', compute='_compute_display_parts')
    purpose = fields.Char(string='用途', compute='_compute_display_parts')
    rules_text = fields.Text(string='核心規則', compute='_compute_display_parts')
    links_text = fields.Text(string='串接', compute='_compute_display_parts')
    setup_text = fields.Text(string='前置設定', compute='_compute_display_parts')
    models_text = fields.Text(string='主要模型', compute='_compute_display_parts')
    depends_text = fields.Char(string='相依模組', compute='_compute_display_parts')

    _sql_constraints = [('module_hash_uniq', 'unique(module, dir_hash)', '同一版模組只記一筆')]

    @api.depends('summary_json', 'facts_json')
    def _compute_display_parts(self):
        def lines(v):
            return '\n'.join('・%s' % x for x in (v or [])) or False
        for rec in self:
            b = rec.brief()
            try:
                facts = json.loads(rec.facts_json or '{}')
            except ValueError:
                facts = {}
            rec.title = facts.get('name') or rec.module
            rec.purpose = b.get('purpose') or False
            rec.rules_text = lines(b.get('rules'))
            rec.links_text = lines(b.get('links'))
            rec.setup_text = lines(b.get('setup'))
            rec.models_text = lines(b.get('key_models') or facts.get('new_models'))
            rec.depends_text = '、'.join(facts.get('depends') or []) or False

    def brief(self):
        """給提示用的精簡版。"""
        self.ensure_one()
        try:
            facts = json.loads(self.facts_json or '{}')
            summary = json.loads(self.summary_json) if self.summary_json else None
        except ValueError:   # 舊資料壞掉：當作沒有摘要，不讓提案整個失敗
            facts, summary = {}, None
        out = {'module': self.module, 'name': facts.get('name')}
        if isinstance(summary, dict):
            out.update(summary)
        else:
            out.update(purpose=facts.get('summary') or facts.get('description', '')[:200],
                       key_models=facts.get('new_models', [])[:8])
        return out


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
                # 同一份原碼：連抽出來的目錄都沿用（不再抽一份）
                tree = Tree.create({'image_digest': digest, 'odoo_version': same.odoo_version,
                                    'match': 'version', 'core_hashes': same.core_hashes,
                                    'tree_hash': same.tree_hash, 'core_path': same.core_path})
                how = 'version'
            else:
                core = remote.shell_json(self.env, instance, db_name, scripts.module_hash_script(core=True))
                hashes = {m: d['hash'] for m, d in core.items() if d.get('core')}
                prev_tree = Tree.search([('core_hashes', '!=', False)], order='last_seen desc', limit=1)
                old = json.loads(prev_tree.core_hashes or '{}') if prev_tree else {}
                tree = Tree.create({'image_digest': digest, 'odoo_version': version,
                                    'match': 'hashed', 'core_hashes': json.dumps(hashes, sort_keys=True),
                                    'tree_hash': _hash(hashes),
                                    'changed_core': json.dumps(sorted(m for m in hashes if old.get(m) != hashes[m]))
                                    if old else False})
                how = 'hashed'
        tree.write({'last_seen': now, 'server_id': getattr(instance.server_id, 'id', False) or tree.server_id.id})
        if not tree.core_path and not (tree.core_tried and tree.core_tried > fields.Datetime.subtract(now, days=1)):
            tree.write({'core_path': self._knowledge_extract_core(instance, digest), 'core_tried': now})
        addons = remote.shell_json(self.env, instance, db_name, scripts.module_hash_script(core=False))
        prev = (self.knowledge_profile().get('code') or {}).get('addons') or {}
        cur = {m: {'version': d.get('version'), 'hash': d.get('hash')} for m, d in addons.items()}
        changed = sorted(m for m in cur if prev.get(m) != cur[m])
        paths = self._knowledge_container_paths(instance)
        if paths.get('core') and not tree.core_container_path:
            tree.core_container_path = paths['core']
        return {'digest': digest, 'odoo_version': tree.odoo_version, 'match': how,
                'container_sources': paths.get('sources') or '',
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
            # ★ 先清掉上次中斷留下的 $D.tmp（不然 docker cp 會變成 odoo/odoo 巢狀）；暫存容器一定刪
            cmd = (
                "set -e; D=%(d)s; if [ ! -d \"$D\" ]; then "
                "P=$(docker exec %(c)s python3 -c 'import odoo,os; print(os.path.dirname(odoo.__file__))'); "
                "rm -rf \"$D.tmp\"; mkdir -p \"$D.tmp\"; T=$(docker create %(img)s); "
                "trap 'docker rm -f \"$T\" >/dev/null 2>&1' EXIT; "
                # ☠️ 不能 docker cp 到目錄：point_of_sale 的字型捷徑指到原碼目錄外，docker 判成
                #    「invalid symlink」整個中止。改成串流 tar 再用系統 tar 解開（捷徑照原樣保留）
                "docker cp \"$T:$P\" - | tar -xf - -C \"$D.tmp\"; "
                "mv \"$D.tmp\" \"$D\"; chmod -R a+rX \"$D\"; fi; echo \"$D\""
            ) % {'d': shlex.quote(dest), 'c': ctr, 'img': shlex.quote(digest)}
            res = remote.run(server, cmd, dont_raise=True)
            out = (getattr(res, 'stdout', '') or '').strip().splitlines()
            return out[-1] if out and out[-1] == dest else ''
        except Exception as e:  # noqa: BLE001
            _logger.warning('[knowledge] 抽出 Odoo 原碼失敗：%s', e)
            return ''

    def _knowledge_container_paths(self, instance):
        """容器裡的 Odoo 原碼目錄、與實例原始碼目錄的掛載點（對照成 Runner 看得到的路徑）。"""
        ctr = shlex.quote(instance.odoo_container)
        try:
            res = remote.run(instance.server_id, "docker exec %s python3 -c 'import odoo,os; "
                             "print(os.path.dirname(odoo.__file__))'; docker inspect -f '{{json .Mounts}}' %s"
                             % (ctr, ctr), dont_raise=True)
            lines = (getattr(res, 'stdout', '') or '').strip().splitlines()
            core = lines[0].strip() if lines else ''
            mounts = json.loads(lines[-1]) if len(lines) > 1 else []
            src = (instance.sources_path or '').rstrip('/')
            addons = [m.get('Destination') for m in mounts
                      if src and (m.get('Source') or '').rstrip('/') == src]
            return {'core': core, 'sources': addons[0] if addons else ''}
        except Exception as e:  # noqa: BLE001
            _logger.warning('[knowledge] 讀取容器路徑失敗：%s', e)
            return {}

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
                module = d.get('module') or CORE_MODULE   # 不存空值：UNIQUE 不管 NULL
                rec = Def.search([('def_hash', '=', d['hash']), ('method', '=', method),
                                  ('module', '=', module)], limit=1)
                if not rec:
                    rec = Def.create({'def_hash': d['hash'], 'method': method, 'module': module,
                                      'path': d.get('file'), 'line_start': d.get('line'),
                                      'line_end': d.get('end')})
                defs |= rec
            chain_hash = _hash([d['hash'] for d in chain])
            fact = Fact.search([('subject', '=', subject), ('chain_hash', '=', chain_hash)], limit=1)
            if not fact:
                # 同一主體的舊鏈：有結論的標過期（語意層重讀時只讀變動的那段；語意層寫入結論時設 current）
                Fact.search([('subject', '=', subject), ('state', '=', 'current')]).write({'state': 'stale'})
                fact = Fact.create({'subject': subject, 'chain_hash': chain_hash,
                                    'def_ids': [(6, 0, defs.ids)]})
            out[subject] = fact
        return out

    # ------------------------------------------------------------------
    # 語意層（計畫第 51 項）：AI 讀程式寫結論，只讀沒有摘要的那幾段
    # ------------------------------------------------------------------
    def _knowledge_runner_path(self, path, instance):
        """容器裡的檔案路徑 → AI Runner 看得到的路徑（讀不到回空字串）。"""
        code = self.knowledge_profile().get('code') or {}
        tree = self.env['corpaas.knowledge.code_tree'].sudo().search(
            [('image_digest', '=', code.get('digest') or '')], limit=1)
        if tree.core_path and tree.core_container_path and path.startswith(tree.core_container_path + '/'):
            return '/odoo-core/%s/odoo%s' % (tree.core_path.rstrip('/').rsplit('/', 1)[-1],
                                             path[len(tree.core_container_path):])
        src = (code.get('container_sources') or '').rstrip('/')
        Runner = self.env.get('infrastructure.ai_runner')
        if src and path.startswith(src + '/') and Runner is not None and hasattr(Runner, '_safe_dir'):
            return '/instances/%s%s' % (Runner._safe_dir(instance.name), path[len(src):])
        return ''

    def _knowledge_code_semantic(self, instance, facts, token=None):
        """讓 AI 讀這些繼承鏈的程式、寫結論。回傳寫好的筆數。

        ★ 已有摘要的定義不再讀（內容雜湊沒變＝同一段程式），只把摘要給 AI 合成結論。"""
        self.ensure_one()
        Ai = self.env['corpaas.knowledge.ai']
        done = 0
        for fact in facts:
            parts, missing = [], []
            for d in fact.def_ids:
                where = self._knowledge_runner_path(d.path or '', instance)
                if d.summary_json:
                    parts.append({'def': d.def_hash, 'module': d.module, 'summary': json.loads(d.summary_json)})
                elif where:
                    missing.append(d)
                    parts.append({'def': d.def_hash, 'module': d.module, 'read': '%s 第 %s–%s 行' % (
                        where, d.line_start, d.line_end)})
            if not missing and not parts:
                continue
            prompt = (
                "任務：說明 Odoo 方法 %s 實際執行時做什麼（官方原碼＋各模組覆寫，依繼承順序由下而上）。\n"
                "讀標了「read」的檔案行數（唯讀；需要時可以順著讀它呼叫的方法），已有 summary 的不必再讀。\n"
                "只回 JSON：{\"defs\": {\"<def>\": \"這一段做什麼（一兩句）\"}, \"fact\": {"
                "\"preconditions\": [\"要先滿足什麼，否則跳什麼錯\"], \"transitions\": [{\"from\": \"\", \"to\": \"\"}], "
                "\"creates\": [\"會建立的記錄模型\"], \"opens\": \"會開的精靈或畫面模型\", "
                "\"requires_config\": [\"需要的設定\"], \"errors\": [\"可能出現的錯誤訊息原文\"]}, "
                "\"also_read\": [\"另外依據的方法 model.method\"]}\n\n繼承鏈：%s"
            ) % (fact.subject, json.dumps(parts, ensure_ascii=False))
            try:
                data = Ai.ask('code_fact', prompt, package=self, refresh_token=token, record=fact,
                              instance_ref=instance.id)
            except hub_client.BudgetExceeded:
                break
            except Exception as e:  # noqa: BLE001 — Hub 不支援指定實例、回覆壞掉：下次再試
                _logger.info('[knowledge] 程式結論 %s 沒有完成：%s', fact.subject, e)
                continue
            if not isinstance(data, dict) or not isinstance(data.get('fact'), dict):
                continue
            summaries = data.get('defs') if isinstance(data.get('defs'), dict) else {}
            for d in missing:
                if summaries.get(d.def_hash):
                    d.summary_json = json.dumps(str(summaries[d.def_hash])[:500], ensure_ascii=False)
            fact.write({'fact_json': json.dumps(data['fact'], ensure_ascii=False)[:4000], 'state': 'current'})
            done += 1
        return done

    def _knowledge_module_summaries(self, token=None, limit=20):
        """方案自訂模組的摘要（計畫第 53 項）：先抽結構事實，再請 AI 讀程式寫摘要。

        ★ 依模組目錄雜湊沿用：模組沒改就不重讀，換方案也共用。AI 讀不到程式（沒掛載、Hub 沒授權）
          就先只存結構事實，下次再補。回傳寫了幾份 AI 摘要。"""
        self.ensure_one()
        golden = self._knowledge_master()._corpaas_golden_db()
        instance, db = golden.instance_id, golden.name
        code = self.knowledge_profile().get('code') or {}
        if not code.get('addons'):
            ident = self._knowledge_code_identity(instance, db)
            if ident.get('error'):
                _logger.warning('[knowledge] 模組摘要：%s', ident['error'])
                return 0
            self._knowledge_update_profile({'code': ident})
            code = ident
        addons = code.get('addons') or {}
        scope = self._knowledge_scope_names()
        mods = sorted(m for m in addons if not scope or m in scope)
        if not mods:
            return 0
        Summary = self.env['corpaas.knowledge.module_summary'].sudo()
        todo = [m for m in mods if not Summary.search_count(
            [('module', '=', m), ('dir_hash', '=', addons[m]['hash']), ('source', '=', 'ai')])]
        if not todo:
            return 0
        facts = remote.shell_json(self.env, instance, db, scripts.module_facts_script(todo)) or {}
        Ai = self.env['corpaas.knowledge.ai']
        done = 0
        for m in todo:
            f = facts.get(m)
            if not f:
                continue
            rec = Summary.search([('module', '=', m), ('dir_hash', '=', addons[m]['hash'])], limit=1) or \
                Summary.create({'module': m, 'dir_hash': addons[m]['hash'], 'source': 'facts',
                                'facts_json': json.dumps(f, ensure_ascii=False)})
            where = self._knowledge_runner_path((f.get('path') or '') + '/__manifest__.py', instance)
            if not where or done >= limit:
                continue
            prompt = (
                "任務：讀 Odoo 擴充模組 %s 的程式（目錄 %s，唯讀；先看 __manifest__.py 與 models/ 下的 .py），"
                "寫給「寫操作說明書的人」看的摘要。不要猜，只寫程式裡看得到的。\n"
                "只回 JSON：{\"purpose\": \"這個模組解決什麼問題（一兩句）\", "
                "\"rules\": [\"核心規則：什麼條件下做什麼、什麼情況會擋下（最多 8 條）\"], "
                "\"links\": [\"跟哪些模組或模型串接、資料怎麼流\"], "
                "\"key_models\": [\"主要模型\"], \"setup\": [\"使用前要先設定的\"]}\n\n系統抽的結構事實：%s"
            ) % (m, where.rsplit('/', 1)[0], json.dumps(f, ensure_ascii=False)[:3000])
            try:
                data = Ai.ask('module_summary', prompt, package=self, refresh_token=token,
                              instance_ref=instance.id)
            except hub_client.BudgetExceeded:
                break
            except Exception as e:  # noqa: BLE001 — 讀不到就先只有結構事實
                _logger.info('[knowledge] 模組 %s 摘要沒有完成：%s', m, e)
                continue
            if isinstance(data, dict) and data.get('purpose'):
                rec.write({'summary_json': json.dumps(_trim_summary(data), ensure_ascii=False), 'source': 'ai'})
                done += 1
                # ★ 寫一份就提交：之後的步驟失敗回滾也不會把付過錢的摘要丟掉
                #   ☠️ 實機：20 份摘要寫完、提案時失敗，整個工作回滾，摘要全沒了
                from ..services import txn
                if not txn.in_tests(self.env):
                    self.env.cr.commit()
        return done

    def action_knowledge_module_summaries(self):
        """方案表單的「模組摘要」：這個方案目前用到的自訂模組（依目前的目錄雜湊）。"""
        self.ensure_one()
        addons = (self.knowledge_profile().get('code') or {}).get('addons') or {}
        scope = self._knowledge_scope_names()
        Summary = self.env['corpaas.knowledge.module_summary'].sudo()
        ids = []
        for m, d in addons.items():
            if scope and m not in scope:
                continue
            ids += Summary.search([('module', '=', m), ('dir_hash', '=', d.get('hash'))]).ids
        return {'type': 'ir.actions.act_window', 'name': '模組摘要：%s' % self.display_name,
                'res_model': 'corpaas.knowledge.module_summary', 'view_mode': 'list,form',
                'domain': [('id', 'in', ids)]}

    def _knowledge_module_brief(self, limit=40):
        """方案自訂模組摘要的精簡清單（給提案、示範資料的提示用）；沒有就空清單。"""
        self.ensure_one()
        code = self.knowledge_profile().get('code') or {}
        addons = code.get('addons') or {}
        scope = self._knowledge_scope_names()
        Summary = self.env['corpaas.knowledge.module_summary'].sudo()
        out = []
        for m in sorted(addons):
            if scope and m not in scope:
                continue
            rec = Summary.search([('module', '=', m), ('dir_hash', '=', addons[m].get('hash'))],
                                 order='source, id desc', limit=1)
            if rec:
                out.append(rec.brief())
        return out[:limit]

    def _knowledge_code_facts_for(self, subjects):
        """有效的程式結論 {model.method: dict}（給寫／修腳本的提示用）。"""
        out = {}
        for f in self.env['corpaas.knowledge.code_fact'].sudo().search(
                [('subject', 'in', list(subjects)), ('state', '=', 'current')]):
            try:
                out[f.subject] = json.loads(f.fact_json or '{}')
            except ValueError:
                continue
        return out


def _trim_summary(data):
    """摘要逐欄截短（不能截 JSON 字串：截斷的 JSON 讀回來就壞了）。"""
    def lst(v, n, w):
        return [str(x)[:w] for x in (v if isinstance(v, list) else [v] if v else [])][:n]
    return {'purpose': str(data.get('purpose') or '')[:500], 'rules': lst(data.get('rules'), 8, 300),
            'links': lst(data.get('links'), 6, 200), 'key_models': lst(data.get('key_models'), 10, 80),
            'setup': lst(data.get('setup'), 6, 200)}


def _hash(data):
    return hashlib.sha1(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]
