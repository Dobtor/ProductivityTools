# -*- coding: utf-8 -*-
"""說明庫（D7）：方案母體裡的一個內部資料庫，拍攝的唯一資料來源。

生命週期：pending → cloning → purging（D1）→ seeding → ready → shooting → done
          任一步失敗 → failed。每次 refresh 重建（拋棄式），不原地 -u。

★ 刻意不建 infrastructure.database 記錄：建了就會被服務盤點、授權推送、容量、
  計量、dbfilter 收斂當成客戶庫。代價是平台看它是「無人納管」的實體庫——
  庫名固定用 `docsbx-` 前綴，巡檢時據此辨識（見 README）。
★ 庫名必須是合法的主機名第一段（dbfilter ^%d$ 靠網址第一段選庫）：
  只用小寫英數與連字號，固定為 `docsbx-p<方案id>-s<情境id>`（用 id 不用代碼：
  非英數的代碼會全部變成同一個名字，兩個情境搶同一座庫）。
☠️ 狀態一律在佇列作業的同一個交易裡寫。曾經用第二個游標另外 commit 狀態：
  新建的說明庫在主交易裡還沒 commit，第二個游標的 UPDATE 影響 0 列（看不到那一列），
  state／密碼全部消失，之後「ready 的才拍」永遠是空集合——整條流程什麼都不拍，也不報錯。
  失敗的稽核由佇列步驟（它自己用新游標）記錄；實體庫在回滾後仍存在，下次 overwrite 即可。
"""
import json
import logging
import re
import secrets

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from ..services import remote, scripts

_logger = logging.getLogger(__name__)

_NAME_OK = re.compile(r'^docsbx-[a-z0-9-]+$')


class KnowledgeSandbox(models.Model):
    _name = 'corpaas.knowledge.sandbox'
    _description = '說明庫'
    _order = 'id desc'

    package_id = fields.Many2one('infrastructure.solution.package', required=True,
                                 ondelete='cascade', index=True)
    scenario_id = fields.Many2one('corpaas.knowledge.scenario', required=True,
                                  ondelete='cascade', index=True)
    master_instance_id = fields.Many2one('infrastructure.instance', required=True,
                                         ondelete='cascade')
    golden_id = fields.Many2one('infrastructure.database', string='黃金庫',
                                ondelete='set null')
    db_name = fields.Char(required=True, index=True, readonly=True)
    state = fields.Selection([
        ('pending', '待建'), ('cloning', '複製中'), ('purging', '清除中'),
        ('seeding', '示範資料'), ('ready', '就緒'), ('shooting', '拍攝中'),
        ('done', '完成'), ('failed', '失敗'), ('dropped', '已刪除'),
    ], default='pending', index=True)
    code_manifest = fields.Text(readonly=True)
    inputs_sig = fields.Char(string='輸入簽章', readonly=True,
                             help='黃金庫、程式版本、示範資料上線版號、角色、清除範圍的簽章；'
                                  '全量更新時沒變就沿用這座說明庫，不重建（R1）')
    base_sig = fields.Char(string='基礎簽章', readonly=True,
                           help='不含示範資料的輸入簽章：沒變而示範資料只有新增時，'
                                '直接把新增的記錄寫進這座說明庫（R2）')
    seed_applied = fields.Text(readonly=True,
                               help='{xmlid: 內容雜湊}：目前說明庫裡重播過的示範資料')
    last_prep = fields.Selection([('rebuilt', '重建'), ('reused', '沿用'),
                                  ('overlaid', '疊加新增的示範資料')],
                                 string='最近一次準備', readonly=True)
    is_check = fields.Boolean(string='重播檢查用', readonly=True,
                              help='送審前重播檢查的臨時庫（A3）：檢查完就刪除，不拍照')
    dirty = fields.Boolean(string='資料已被拍攝改動', readonly=True,
                           help='有截圖腳本按了物件按鈕或填了欄位：下次更新一定重建')
    ready_at = fields.Datetime(readonly=True)
    purged_at = fields.Datetime(readonly=True,
                                help='D1 清除完成時間：之後建立的記錄都是示範資料或拍攝產生的')
    password = fields.Char(readonly=True, groups='dobtor_corpaas_knowledge.group_knowledge_manager')
    role_logins = fields.Text(readonly=True, help='{role_code: login}')
    purge_report = fields.Text(readonly=True)
    purge_skipped = fields.Boolean(string='免清除', readonly=True,
                                   help='黃金庫的範本資料來源是空白或純示範（A4）：沒有個資可清，'
                                        '不跑清除、截圖前也不逐筆檢查')
    seed_report = fields.Text(readonly=True)
    error = fields.Text(readonly=True)
    selftest_ok = fields.Boolean(string='自我檢查通過', readonly=True)
    selftest_at = fields.Datetime(string='自我檢查時間', readonly=True)
    selftest_report = fields.Text(string='自我檢查結果', readonly=True)

    _sql_constraints = [('db_unique', 'unique(db_name)', '說明庫名稱重複')]

    @api.model
    def make_name(self, package, scenario):
        return 'docsbx-p%s-s%s' % (package.id, scenario.id)

    def _shell(self, script):
        self.ensure_one()
        return remote.shell_json(self.env, self.master_instance_id, self.db_name, script)

    def _check_manager(self):
        if not self.env.user.has_group('dobtor_corpaas_knowledge.group_knowledge_manager'):
            raise AccessError(_('只有知識管理者可以重建或刪除說明庫。'))

    # ------------------------------------------------------------------
    BUSY = ('cloning', 'purging', 'seeding', 'shooting')

    def _base_parts(self):
        """示範資料以外、重建說明庫要用到的輸入。"""
        self.ensure_one()
        master = self.master_instance_id
        golden = master._corpaas_golden_db()
        scenario = self.scenario_id
        purge = golden._knowledge_needs_purge()
        return [golden.id, golden.name, master._corpaas_code_manifest(),
                scenario.all_roles().as_payload(),
                self._purge_models(scenario.live_seed()) if purge else 'no-purge',
                list(scripts.CONFIG_MODELS) if purge else []]

    @staticmethod
    def _sig(data):
        import hashlib
        return hashlib.sha1(json.dumps(data, sort_keys=True, ensure_ascii=False, default=str)
                            .encode('utf-8')).hexdigest()[:16]

    def _base_signature(self):
        return self._sig(self._base_parts())

    def _inputs_signature(self):
        """重建說明庫要用到的輸入；任何一項變了才需要重建。"""
        self.ensure_one()
        return self._sig(self._base_parts() + [self.scenario_id.seed_revisions()])

    @staticmethod
    def _seed_hashes(seed):
        return {r['xmlid']: KnowledgeSandbox._sig(r) for r in seed}

    def _reusable(self):
        """這座說明庫可以直接沿用：就緒過、沒被拍攝改動、輸入簽章沒變。"""
        self.ensure_one()
        if self.state not in ('ready', 'done') or not self.ready_at or self.dirty \
                or not self.inputs_sig:
            return False
        try:
            return self.inputs_sig == self._inputs_signature()
        except Exception:  # noqa: BLE001 — 算不出來就重建
            return False

    def _overlay_delta(self):
        """R2：示範資料只有「新增」時要補寫的記錄；不能疊加就回傳 None（要重建）。

        條件：說明庫就緒且沒被拍攝改動、示範資料以外的輸入（黃金庫、程式、角色、清除範圍）
        都沒變、原有的每一筆內容一字不差。新增的「呼叫動作」可以（只對新記錄做一次）；
        原有動作不會重做——確認訂單做兩次會失敗，這正是改既有記錄必須重建的原因。
        """
        self.ensure_one()
        if self.state not in ('ready', 'done') or not self.ready_at or self.dirty \
                or not self.seed_applied or not self.base_sig:
            return None
        try:
            if self.base_sig != self._base_signature():
                return None
            seed = self.scenario_id.live_seed()
        except Exception:  # noqa: BLE001 — 算不出來就重建
            return None
        applied = json.loads(self.seed_applied or '{}')
        now = self._seed_hashes(seed)
        if any(now.get(k) != h for k, h in applied.items()):
            return None   # 有刪除或修改
        return [r for r in seed if r['xmlid'] not in applied]

    def overlay(self, delta):
        """把新增的示範資料寫進現有說明庫（R2）；失敗就丟例外，由呼叫端改走重建。"""
        self.ensure_one()
        self._check_name_free()
        scenario = self.scenario_id
        self.write({'state': 'seeding', 'error': False})
        res = self._shell(scripts.seed_script(
            scenario.xml_module, delta, scenario.all_roles().as_payload(),
            self.sudo().password))
        if res.get('errors'):
            raise UserError(_('疊加示範資料失敗 %s 筆') % len(res['errors']))
        applied = json.loads(self.seed_applied or '{}')
        applied.update(self._seed_hashes(delta))
        self.write({'state': 'ready', 'seed_applied': json.dumps(applied, sort_keys=True),
                    'inputs_sig': self._inputs_signature(), 'last_prep': 'overlaid',
                    'seed_report': json.dumps(dict(res, overlay=len(delta)),
                                              ensure_ascii=False)})
        return True

    def _check_name_free(self):
        """名稱合法、而且平台上沒有任何一筆資料庫記錄叫這個名字。

        ★ 重建是 overwrite 複製、刪除是 _drop_full：萬一名字撞到客戶的庫，就是刪客戶資料。
        """
        self.ensure_one()
        if not _NAME_OK.match(self.db_name or ''):
            raise UserError(_('說明庫名稱不合法：%s') % self.db_name)
        if self.env['infrastructure.database'].sudo().with_context(active_test=False).search_count(
                [('name', '=', self.db_name)]):
            raise UserError(_('拒絕操作：%s 是平台上有記錄的資料庫，不是說明庫。') % self.db_name)

    def rebuild(self, seed=None):
        """從黃金庫重建：複製 → 清除 → 重播「已核准」的示範資料＋角色帳號。

        seed：重播檢查（A3）傳入待核版本；此時重播錯誤不丟例外、不寫情境的錯誤欄，
        回傳 seed_script 的結果給檢查報告。"""
        self.ensure_one()
        check = seed is not None
        self._check_name_free()
        if self.state in self.BUSY:
            raise UserError(_('說明庫 %s 正在%s，請等它完成。')
                            % (self.db_name, dict(self._fields['state'].selection)[self.state]))
        try:
            master = self.master_instance_id
            golden = master._corpaas_golden_db()
            if not golden or golden.golden_state != 'verified':
                raise UserError(_('母體「%s」沒有已驗證的黃金庫，不能建立說明庫。')
                                % master.display_name)
            # 複製黃金庫一次吃好幾 GB：主機硬碟紅燈或空間不夠先擋下（PAAS 硬碟閘）
            server = master.server_id
            if hasattr(server, '_assert_disk_room'):
                server._assert_disk_room(_('建立說明庫'), need_gb=2)
            scenario = self.scenario_id
            # ★ 只重播核准過的示範資料：AI 修補後還在待核的腳本不能拿來拍對外的圖。
            if not check:
                seed = scenario.live_seed()
            self.write({'state': 'cloning', 'error': False, 'golden_id': golden.id,
                        'ready_at': False, 'purged_at': False})
            with golden._corpaas_golden_lock():
                golden._corpaas_golden_sync_code()
                golden._duplicate_db_physical(self.db_name, False, overwrite=True,
                                              neutralize=False)
            self.write({'code_manifest': json.dumps(master._corpaas_code_manifest(),
                                                    sort_keys=True),
                        'state': 'purging'})
            # A4：空白／純示範的範本沒有個資可清，清除只會白跑（還曾誤刪設定類資料）
            skip = not golden._knowledge_needs_purge()
            if skip:
                purge = {'skipped': golden.template_version_id.knowledge_data_source}
            else:
                purge = self._shell(scripts.purge_script(self._purge_models(seed)))
            self.write({'purge_report': json.dumps(purge, ensure_ascii=False),
                        'purge_skipped': skip,
                        'purged_at': fields.Datetime.now(), 'state': 'seeding'})
            password = secrets.token_urlsafe(18)
            res = self._shell(scripts.seed_script(
                scenario.xml_module, seed, scenario.all_roles().as_payload(), password))
            self.write({'seed_report': json.dumps(res, ensure_ascii=False),
                        'password': password,
                        'role_logins': json.dumps(res.get('users') or {})})
            if check:
                self.write({'state': 'ready', 'ready_at': fields.Datetime.now()})
                return res
            if res.get('errors'):
                scenario.sudo().seed_error = json.dumps(res['errors'], ensure_ascii=False)
                raise UserError(_('示範資料重播失敗 %s 筆（見示範資料報告）')
                                % len(res['errors']))
            scenario.sudo().seed_error = False
            self.write({'state': 'ready', 'ready_at': fields.Datetime.now(), 'dirty': False,
                        'inputs_sig': self._inputs_signature(),
                        'base_sig': self._base_signature(), 'last_prep': 'rebuilt',
                        'seed_applied': json.dumps(self._seed_hashes(seed), sort_keys=True)})
        except Exception as e:
            self.write({'state': 'failed', 'error': str(e)[:4000]})
            raise
        return True

    # ------------------------------------------------------------------
    # 送審前重播檢查（A3）
    # ------------------------------------------------------------------
    @api.model
    def run_seed_check(self, package, scenario):
        """臨時複製一座說明庫 → 重播情境目前（待核）的示範資料 → 數各畫面筆數 → 刪庫。"""
        master = package._knowledge_master()
        name = self.make_name(package, scenario) + '-chk'
        sb = self.sudo().search([('db_name', '=', name)], limit=1)
        vals = {'package_id': package.id, 'scenario_id': scenario.id,
                'master_instance_id': master.id, 'is_check': True}
        if sb:
            sb.write(dict(vals, state='pending'))
        else:
            sb = self.sudo().create(dict(vals, db_name=name))
        scenario = scenario.sudo()
        scenario.write({'seed_check_state': 'running', 'seed_check_report': False})
        report = {}
        try:
            res = sb.rebuild(seed=scenario.live_seed(draft=True))
            report['errors'] = res.get('errors') or []
            items, labels = package._knowledge_probe_items()
            report['counts'] = self.env['corpaas.knowledge.hooks']._knowledge_check_screens(
                package, sb, items) or {}
            report['labels'] = {k: v for k, v in labels.items() if k in report['counts']}
            empty = [k for k, v in report['counts'].items() if v == 0]
            limit = package._knowledge_profile()['empty_max_pct']
            report['empty_pct'] = round(100.0 * len(empty) / len(report['counts']), 1) \
                if report['counts'] else 0
            report['empty_max_pct'] = limit
            state = 'issues' if report['errors'] or report['empty_pct'] > limit else 'ok'
        except Exception as e:  # noqa: BLE001 — 檢查失敗也要留下結果
            report['error'] = str(e)[:2000]
            state = 'failed'
        finally:
            try:
                sb.drop()
            except Exception as e:  # noqa: BLE001
                _logger.warning('[knowledge] 刪除重播檢查庫 %s 失敗：%s', name, e)
        scenario.write({'seed_check_state': state, 'seed_check_at': fields.Datetime.now(),
                        'seed_check_report': json.dumps(report, ensure_ascii=False)})
        from .catalog import MAX_SEED_REPAIRS
        if state == 'issues' and scenario.seed_auto_repairs < MAX_SEED_REPAIRS:
            try:
                scenario._ai_repair_seed_from_check(report)
            except Exception as e:  # noqa: BLE001 — 修不了就留給人看檢查結果
                _logger.warning('[knowledge] 情境 %s 自動修正示範資料失敗：%s', scenario.code, e)
        elif state == 'issues' and report.get('errors'):
            # 修完仍重播失敗：拿掉出錯的記錄，不讓它們卡住正式說明庫
            try:
                scenario._prune_failed_seed(report)
            except Exception as e:  # noqa: BLE001
                _logger.warning('[knowledge] 情境 %s 移除失敗記錄失敗：%s', scenario.code, e)
        return state

    def _purge_models(self, seed):
        """D1 要清的業務模型：方案功能點用到的模型＋示範資料的模型＋res.partner。"""
        self.ensure_one()
        features = self.env['corpaas.knowledge.feature'].sudo().search(
            [('package_ids', 'in', self.package_id.id), ('model', '!=', False)])
        models = set(features.mapped('model')) | {r['model'] for r in seed} | {'res.partner'}
        for cap in self.package_id.knowledge_capability_ids:
            models |= {m.strip() for m in (cap.master_data_models or '').splitlines() if m.strip()}
        # ★ 設定類模型不清（程式建立、沒有 xmlid 的補貨規則／作業類型被清掉，訂單都確認不了）
        return sorted(models - {'res.config.settings'} - set(scripts.CONFIG_MODELS))

    def drop(self):
        for rec in self.filtered(lambda r: r.state != 'dropped'):
            # ★ 刪除前再驗一次名稱：_drop_full 刪的是 PG 上的庫，名字錯了就是客戶的庫。
            rec._check_name_free()
            if rec.state in rec.BUSY:
                raise UserError(_('說明庫 %s 正在使用中，不能刪除。') % rec.db_name)
            try:
                self.env['infrastructure.database'].sudo().drop_db_on_instance(
                    rec.master_instance_id, rec.db_name)
            except Exception as e:  # noqa: BLE001
                _logger.warning('[knowledge] 刪除說明庫 %s 失敗：%s', rec.db_name, e)
                rec.error = str(e)[:2000]
                continue
            rec.state = 'dropped'
        return True

    def resolve_xmlids(self, xmlids):
        """{xmlid: [model, id]}：截圖前把繫結的示範記錄解析成 id。"""
        self.ensure_one()
        script = scripts._HEAD + (
            "XIDS = json.loads(%r)\n"
            "out = {}\n"
            "for x in XIDS:\n"
            "    r = env.ref(x, raise_if_not_found=False)\n"
            "    if r:\n"
            "        out[x] = [r._name, r.id]\n"
            "env.cr.rollback()\n"
            "print(MARK + json.dumps(out))\n") % json.dumps(sorted(set(xmlids)))
        return self._shell(script)

    def gate_bad_records(self, pairs, refs=None):
        """D1 截圖前檢查：回傳不在允許集合內的 [model, id]。

        pairs = {model: [ids]}；refs = {"model|field": [ids]}（畫面上的關聯值）。
        """
        self.ensure_one()
        if self.purge_skipped or (not pairs and not refs):
            return []
        since = fields.Datetime.to_string(self.purged_at or self.ready_at
                                          or fields.Datetime.now())
        res = self._shell(scripts.gate_script(pairs or {}, since, refs or {}))
        return res.get('bad') or []

    def action_rebuild(self):
        return self._enqueue_op('rebuild')

    def action_drop(self):
        return self._enqueue_op('drop')

    def action_selftest(self):
        """截圖流程端到端自我檢查（優化 7）：在這座說明庫真的跑一次 Playwright。"""
        return self._enqueue_op('selftest')

    def selftest(self):
        """登入 → 打開使用者清單 → 探測 → 截圖 → 打開一筆記錄再探測，檢查：
        容器起得來、登入成功、截圖有內容、探測抓得到元素、狀態列讀值（有的話）、中文字型。
        結果寫在 selftest_report；不改任何資料。"""
        from ..services import shooter
        self.ensure_one()
        logins = json.loads(self.role_logins or '{}')
        checks = []
        if not logins:
            self.write({'selftest_ok': False, 'selftest_at': fields.Datetime.now(),
                        'selftest_report': _('說明庫沒有角色帳號，請先重建。')})
            return False
        uid_xid = 'base.partner_admin'
        ids = self.resolve_xmlids([uid_xid]).get(uid_xid)
        steps = [{'goto': {'action': 'base.action_res_users'}}, {'probe': 'entry'},
                 {'shot': 'selftest_list'}]
        if ids:
            steps += [{'open': {'model': ids[0], 'res_id': ids[1]}}, {'probe': 'record'}]
        shot = {'id': 'selftest', 'login': next(iter(logins.values())),
                'password': self.sudo().password, 'steps': steps}
        try:
            result, files = shooter.run_shots(
                self.env, self, [shot], self.env['res.config.settings'].knowledge_shot_settings())
        except Exception as e:  # noqa: BLE001
            self.write({'selftest_ok': False, 'selftest_at': fields.Datetime.now(),
                        'selftest_report': _('截圖容器執行失敗：%s') % str(e)[:2000]
                        + self._selftest_component_hint()})
            return False
        r = (result.get('shots') or {}).get('selftest') or {}
        checks.append((_('登入與步驟'), bool(r.get('ok')), r.get('error') or ''))
        imgs = r.get('images') or []
        shot_img = next((i for i in imgs if i.get('name') == 'selftest_list'), None)
        size = len(files.get(shot_img['file'], b'')) if shot_img else 0
        checks.append((_('截圖有內容'), size > 10000, _('%s bytes') % size))
        probe = next((i.get('probe') for i in imgs if i.get('is_probe')), None) or {}
        checks.append((_('探測抓得到元素'), bool(probe.get('fields') or probe.get('buttons')),
                       _('%(f)s 欄位／%(b)s 按鈕', f=len(probe.get('fields') or []),
                         b=len(probe.get('buttons') or []))))
        fonts = result.get('cjk_fonts') or []
        checks.append((_('中文字型'), bool(fonts),
                       ', '.join(fonts[:5]) or result.get('cjk_fonts_error') or _('找不到')))
        ok = all(c[1] for c in checks)
        report = '\n'.join('%s %s：%s' % ('✓' if c[1] else '✗', c[0], c[2]) for c in checks)
        if not ok:
            report += self._selftest_component_hint()
        self.write({'selftest_ok': ok, 'selftest_at': fields.Datetime.now(),
                    'selftest_report': report})
        return ok

    def _selftest_component_hint(self):
        """自我檢查失敗時，指出說明主機缺哪些主機元件（PAAS 主機元件頁可一鍵安裝）。"""
        server = self.master_instance_id.server_id
        if not server or not hasattr(server, '_knowledge_missing_components'):
            return ''
        missing = server._knowledge_missing_components()
        if not missing:
            return ''
        return '\n' + _('說明主機缺少元件：%s（到主機的「主機元件」頁按「安裝必要元件」，'
                         '或在設定頁按「準備說明主機」）') % '、'.join(missing)

    def _enqueue_op(self, op):
        """☠️ 不在網頁請求裡跑：複製＋三輪清除＋示範資料要好幾分鐘，worker 被
        limit_time_real 砍掉時交易回滾，狀態與密碼消失，但實體庫已經被覆蓋了。"""
        self._check_manager()
        Queue = self.env['corpaas.queue'].sudo()
        for rec in self:
            if rec.state in rec.BUSY:
                raise UserError(_('說明庫 %s 正在使用中。') % rec.db_name)
            q = Queue._enqueue(rec.package_id, 'knowledge_sandbox',
                               {'sandbox_id': rec.id, 'op': op})
            q.channel = 'knowledge'
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'type': 'info', 'title': _('已排入佇列'),
                           'message': _('說明庫%s會在背景執行。') % (
                               {'rebuild': _('重建'), 'drop': _('刪除'),
                                'selftest': _('截圖自我檢查')}.get(op, op))}}
