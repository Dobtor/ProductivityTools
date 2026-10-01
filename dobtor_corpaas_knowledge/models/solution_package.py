# -*- coding: utf-8 -*-
"""方案的知識更新流程（knowledge_refresh）與觸發點。

    kb_check → kb_golden_sync → kb_inventory → kb_fingerprint → kb_ai_catalog
             → kb_sandbox → kb_shoot → kb_outlets → kb_cleanup

★ 只在「說明主機」上的母體做：方案沒有在說明主機上架就擋下（使用者定案），
  不在其他主機部署截圖容器。
★ 黃金庫全程唯讀：盤點與指紋腳本結尾 rollback；拍攝一律在說明庫。
"""
import json
import logging
import uuid

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from ..services import fingerprint_lib, hub_client, remote, scripts, txn

_logger = logging.getLogger(__name__)

FP_CHUNK = 120
RENAME_THRESHOLD_DEFAULT = 0.6


class SolutionPackage(models.Model):
    _inherit = 'infrastructure.solution.package'

    knowledge_enabled = fields.Boolean(string='啟用知識自動更新', copy=False)
    knowledge_scenario_ids = fields.Many2many(
        'corpaas.knowledge.scenario', 'corpaas_knowledge_scenario_package_rel',
        'package_id', 'scenario_id', string='情境')
    knowledge_capability_ids = fields.Many2many(
        'corpaas.knowledge.capability', 'corpaas_knowledge_capability_package_rel',
        'package_id', 'capability_id', string='能力')
    knowledge_sandbox_ids = fields.One2many('corpaas.knowledge.sandbox', 'package_id',
                                            string='說明庫')
    knowledge_event_ids = fields.One2many('corpaas.knowledge.event', 'package_id')
    knowledge_last_refresh = fields.Datetime(readonly=True, copy=False)
    knowledge_last_token = fields.Char(readonly=True, copy=False)
    knowledge_image_digest = fields.Char(readonly=True, copy=False)
    knowledge_pending_full = fields.Boolean(readonly=True, copy=False,
                                            help='待執行的更新要做全量（多個觸發合併成一張）')
    knowledge_blocker = fields.Char(compute='_compute_knowledge_blocker',
                                    string='無法更新的原因')
    knowledge_feature_count = fields.Integer(compute='_compute_knowledge_counts')
    knowledge_event_count = fields.Integer(compute='_compute_knowledge_counts')

    # ------------------------------------------------------------------
    @api.model
    def _knowledge_doc_server(self):
        sid = self.env['ir.config_parameter'].sudo().get_param(
            'corpaas_knowledge.doc_server_id')
        return self.env['infrastructure.server'].sudo().browse(int(sid)).exists() \
            if sid and sid.isdigit() else self.env['infrastructure.server']

    def _knowledge_master(self, raise_if_missing=True):
        self.ensure_one()
        server = self._knowledge_doc_server()
        masters = self.sudo().master_instance_ids.filtered(
            lambda m: m.server_id == server and m.state == 'active'
            and (not self.published_version_id
                 or m.template_version_id == self.published_version_id))
        if not masters and raise_if_missing:
            raise UserError(self._knowledge_blocker_text(server))
        return masters[:1]

    def _knowledge_blocker_text(self, server):
        if not server:
            return _('尚未在設定頁指定「說明主機」。')
        if not self.published_version_id:
            return _('方案「%s」尚未上架。') % self.display_name
        return _('方案「%(p)s」沒有在說明主機「%(s)s」上架（該主機沒有這個方案的母體）。'
                 '請把說明主機加進服務層級的可用主機後重新上架。',
                 p=self.display_name, s=server.display_name)

    def _compute_knowledge_blocker(self):
        server = self._knowledge_doc_server()
        for rec in self:
            rec.knowledge_blocker = False if rec._knowledge_master(
                raise_if_missing=False) else rec._knowledge_blocker_text(server)

    def _compute_knowledge_counts(self):
        Feature = self.env['corpaas.knowledge.feature']
        Event = self.env['corpaas.knowledge.event']
        for rec in self:
            rec.knowledge_feature_count = Feature.search_count(
                [('package_ids', 'in', rec.id), ('missing', '=', False)]) if rec.id else 0
            rec.knowledge_event_count = Event.search_count(
                [('package_id', '=', rec.id), ('processed', '=', False)]) if rec.id else 0

    def _knowledge_roles(self):
        self.ensure_one()
        roles = self.env['corpaas.knowledge.role']
        for sc in self.knowledge_scenario_ids:
            roles |= sc.all_roles()
        if not roles:
            return [{'code': 'admin', 'name': 'admin', 'groups': ['base.group_system']}]
        return roles.as_payload()

    # ------------------------------------------------------------------
    # 排入佇列
    # ------------------------------------------------------------------
    def knowledge_enqueue_refresh(self, full=False, reason='manual', delay_minutes=0):
        """排入知識更新。

        ★ 同一個方案只會有一張待執行的更新：params 只放 package_id（佇列以
          type+reference+operate+params 去重），「要不要全量」記在方案上、執行時讀取。
          ☠️ 把 full／reason 放進 params 會讓上架、改版、每月三種觸發各一張，
            平行對同一座說明庫 overwrite 複製，另一張正在拍攝。
        ★ channel 固定 `knowledge`、上限 1：方案記錄沒有 server_id，預設 channel
          是不限流的 default——多個方案同時開 Chromium 會把說明主機壓垮。
        """
        Queue = self.env['corpaas.queue'].sudo()
        icp = self.env['ir.config_parameter'].sudo()
        if not icp.get_param('corpaas.queue_channel_cap_knowledge'):
            icp.set_param('corpaas.queue_channel_cap_knowledge', '1')
        queues = Queue
        for rec in self.filtered('knowledge_enabled'):
            if not rec._knowledge_master(raise_if_missing=False):
                _logger.info('[knowledge] %s 略過：%s', rec.display_name,
                             rec.knowledge_blocker)
                continue
            if full:
                rec._knowledge_bookkeep({'knowledge_pending_full': True})
            when = fields.Datetime.add(fields.Datetime.now(), minutes=delay_minutes) \
                if delay_minutes else False
            # ★ 正在跑的那張也算「重複」（佇列去重包含 processing）：更新進行中又來了
            #   改版觸發，直接去重就被吃掉了。改排一張「接在它後面」的（params 不同＝不同鍵；
            #   channel 上限 1，自然等前一張跑完）。之後的觸發再去重到這張待執行的。
            running = Queue.search([('type', '=', 'solution.package'),
                                    ('operate', '=', 'knowledge_refresh'),
                                    ('reference_id', '=', rec.id),
                                    ('state', '=', 'processing')], limit=1)
            params = {'package_id': rec.id}
            if running:
                params['after'] = running.id
            q = Queue._enqueue(rec, 'knowledge_refresh', params, q_datetime=when)
            if q.channel != 'knowledge':
                q.channel = 'knowledge'
            _logger.info('[knowledge] %s 排入更新（%s%s）', rec.display_name, reason,
                         '，全量' if full else '')
            queues |= q
        return queues

    def action_knowledge_refresh(self):
        if not self.env.user.has_group('dobtor_corpaas_knowledge.group_knowledge_manager'):
            raise AccessError(_('只有知識管理者可以啟動知識更新。'))
        self._knowledge_master()
        # ★ 方案記錄的寫入權在基礎建設／銷售管理者；知識管理者只需要打開這個開關。
        self.sudo().write({'knowledge_enabled': True})
        q = self.knowledge_enqueue_refresh(full=True, reason='manual')
        return q[:1]._open_form_action() if q else True

    # ------------------------------------------------------------------
    # 佇列派工目標
    # ------------------------------------------------------------------
    def solution_package_knowledge_refresh(self, package_id=None, full=False, reason='',
                                           after=None):
        self.ensure_one()
        full = full or self._knowledge_take_pending_full()
        token = uuid.uuid4().hex
        Event = self.env['corpaas.knowledge.event'].sudo()
        ctx = {'token': token, 'full': full, 'reason': reason}
        with self._op_step('kb_check'):
            master = self._knowledge_master()
            golden = master._corpaas_golden_db()
            if not golden or golden.golden_state != 'verified':
                raise UserError(_('母體「%s」沒有已驗證的黃金庫。') % master.display_name)
        with self._op_step('kb_golden_sync'):
            with golden._corpaas_golden_lock():
                changed = golden._corpaas_golden_sync_code()
            if changed:
                Event.create({'type': 'code_changed', 'package_id': self.id,
                              'refresh_token': token,
                              'payload': json.dumps({'modules': changed})})
        with self._op_step('kb_inventory'):
            added, removed = self._knowledge_inventory(golden, token)
        with self._op_step('kb_fingerprint'):
            self._knowledge_fingerprint(golden, token, full=full)
            self._knowledge_detect_renames(added, removed, token)
        with self._op_step('kb_ai_catalog'):
            self._knowledge_ai_catalog(added, token)
        events = Event.search([('refresh_token', '=', token)])
        hooks = self.env['corpaas.knowledge.hooks']
        with self._op_step('kb_sandbox'):
            scenarios = self.knowledge_scenario_ids if full else \
                hooks._knowledge_scenarios_needing_shots(self, events)
            sandboxes = self.env['corpaas.knowledge.sandbox']
            for sc in scenarios:
                sandboxes |= self._knowledge_prepare_sandbox(master, sc, token)
        with self._op_step('kb_shoot'):
            for sb in sandboxes.filtered(lambda s: s.state == 'ready'):
                sb.state = 'shooting'
                try:
                    hooks._knowledge_shoot(self, sb, events, ctx)
                    sb.state = 'done'
                except hub_client.BudgetExceeded as e:
                    _logger.info('[knowledge] %s：%s，剩下的留到下一次', sb.db_name, e)
                    sb.write({'state': 'done', 'error': str(e)})
                    self._knowledge_budget_notice(e)
                except Exception as e:
                    sb.write({'state': 'failed', 'error': str(e)[:4000]})
                    _logger.exception('[knowledge] 拍攝失敗 %s', sb.db_name)
        with self._op_step('kb_outlets'):
            hooks._knowledge_dispatch_events(self, events, ctx)
            events.write({'processed': True})
        with self._op_step('kb_cleanup'):
            self._knowledge_bookkeep({'knowledge_last_refresh': fields.Datetime.now(),
                                      'knowledge_last_token': token})
        return True

    # ------------------------------------------------------------------
    # 方案列的簿記：一律用獨立游標
    # ------------------------------------------------------------------
    def _knowledge_bookkeep(self, vals):
        """☠️ 知識更新一跑幾十分鐘，主交易若寫了方案這一列，整段時間都鎖著它：
        「立即全量更新」按鈕、映像監看排程、上架流程寫同一列都會卡住或撞序列化衝突。
        簿記欄位用獨立游標寫、立即 commit。"""
        for rec in self:
            if txn.in_tests(self.env):
                rec.sudo().write(vals)
                continue
            with self.env.registry.cursor() as cr:
                self.env(cr=cr)[self._name].sudo().browse(rec.id).write(vals)

    def _knowledge_take_pending_full(self):
        self.ensure_one()
        if txn.in_tests(self.env):
            full, self.sudo().knowledge_pending_full = self.knowledge_pending_full, False
            return full
        with self.env.registry.cursor() as cr:
            cr.execute('UPDATE infrastructure_solution_package SET knowledge_pending_full = false '
                       'WHERE id = %s AND knowledge_pending_full RETURNING id', (self.id,))
            return bool(cr.fetchone())

    # ------------------------------------------------------------------
    # 盤點
    # ------------------------------------------------------------------
    def _knowledge_inventory(self, golden, token):
        """回傳 (新增的 feature, 消失的 feature)。"""
        self.ensure_one()
        modules = self._provision_module_names()
        res = remote.shell_json(self.env, golden.instance_id, golden.name,
                                scripts.inventory_script(modules))
        Feature = self.env['corpaas.knowledge.feature'].sudo().with_context(
            active_test=False)
        Event = self.env['corpaas.knowledge.event'].sudo()
        now = fields.Datetime.now()
        seen = Feature
        added = Feature
        for item in res.get('features') or []:
            key = Feature.make_key(item['module'], item['kind'], item['anchor'])
            vals = {
                'name': item.get('name') or item['anchor'],
                'model': item.get('model') or False,
                'view_mode': item.get('view_mode') or False,
                'view_xmlid': item.get('view_xmlid') or False,
                'action_xmlid': item.get('action_xmlid') or False,
                'button_name': item.get('button_name') or False,
                'menu_path': item.get('menu_path') or False,
                'group_xmlids': ','.join(item.get('groups') or []) or False,
                'last_seen': now, 'active': True,
            }
            rec = Feature.search([('feature_key', '=', key)], limit=1)
            if rec:
                rec.write(vals)
            else:
                rec = Feature.create(dict(vals, feature_key=key, module=item['module'],
                                          kind=item['kind'], anchor=item['anchor']))
            # ★ 「新增」以方案為單位：已存在於別的方案的功能點，對這個方案仍是新的。
            if self not in rec.package_ids:
                rec.write({'package_ids': [(4, self.id)],
                           'missing_package_ids': [(3, self.id)],
                           'classify_pending': True})
                added |= rec
                Event.create({'type': 'feature_added', 'package_id': self.id,
                              'feature_id': rec.id, 'refresh_token': token})
            seen |= rec
        stale = Feature.search([('package_ids', 'in', self.id),
                                ('module', 'in', modules), ('id', 'not in', seen.ids)])
        for rec in stale:
            rec.write({'package_ids': [(3, self.id)], 'missing_package_ids': [(4, self.id)]})
            Event.create({'type': 'feature_removed', 'package_id': self.id,
                          'feature_id': rec.id, 'refresh_token': token})
        self._knowledge_update_usage(seen)
        return added, stale

    def _knowledge_update_usage(self, features):
        """租戶使用量（依 dobtor_database_activity_stats，未安裝就略過）。"""
        if 'database.activity.stats' not in self.env:
            return
        Stats = self.env['database.activity.stats'].sudo()
        stats = Stats.search(['|',
                              ('database_id.born_from_version_id.package_id', '=', self.id),
                              ('database_id.instance_id.template_package_id', '=', self.id)])
        by_model = {}
        for s in stats:
            by_model[s.model_name] = by_model.get(s.model_name, 0) + (s.month_count or 0)
        for f in features:
            f.usage_score = by_model.get(f.model or '', 0)

    # ------------------------------------------------------------------
    # 指紋
    # ------------------------------------------------------------------
    def _knowledge_fingerprint(self, golden, token, full=False):
        self.ensure_one()
        Feature = self.env['corpaas.knowledge.feature'].sudo()
        FP = self.env['corpaas.knowledge.fingerprint'].sudo()
        Event = self.env['corpaas.knowledge.event'].sudo()
        hooks = self.env['corpaas.knowledge.hooks']
        features = Feature.search([('package_ids', 'in', self.id),
                                   ('missing', '=', False), ('model', '!=', False)])
        roles = self._knowledge_roles()
        manifest = json.dumps(golden.instance_id._corpaas_code_manifest(), sort_keys=True)
        items = []
        for f in features:
            views = f.views_for_fingerprint()
            if not views:
                continue
            items.append({'key': f.feature_key, 'model': f.model, 'views': views,
                          'elements': hooks._knowledge_elements_for(f, self) or [],
                          'menu_path': f.menu_path or '', 'view_mode': f.view_mode or ''})
        by_key = {f.feature_key: f for f in features}
        now = fields.Datetime.now()
        for start in range(0, len(items), FP_CHUNK):
            chunk = items[start:start + FP_CHUNK]
            res = remote.shell_json(self.env, golden.instance_id, golden.name,
                                    scripts.fingerprint_script(chunk, roles))
            for key, per in (res.get('items') or {}).items():
                feature = by_key.get(key)
                if not feature:
                    continue
                for role_code, data in per.items():
                    prev = FP.search([('feature_id', '=', feature.id),
                                      ('package_id', '=', self.id),
                                      ('role_code', '=', role_code),
                                      ('current', '=', True)], limit=1)
                    element_json = json.dumps(next((i['elements'] for i in chunk
                                                    if i['key'] == key), []))
                    vals = {'feature_id': feature.id, 'package_id': self.id,
                            'role_code': role_code, 'computed_at': now,
                            'fp_version': res.get('version'), 'lang': res.get('lang'),
                            'code_manifest': manifest, 'elements_json': element_json}
                    if data.get('error'):
                        vals.update(error=data['error'])
                    else:
                        vals.update(form_hash=data['form'], scope_hash=data['scope'],
                                    found_json=json.dumps(data.get('found') or []),
                                    signature_json=json.dumps(data.get('sig') or []))
                    if prev and not data.get('error') \
                            and (prev.elements_json or '[]') != element_json:
                        # ★ 元素清單換了（第一次建立截圖範本、AI 修過範本）＝指紋的定義變了，
                        #   不是畫面變了：靜默換基準，不發事件、不分岔、不重拍。
                        prev.current = False
                        FP.create(vals)
                        hooks._knowledge_fingerprint_rebaselined(
                            feature, self, role_code, prev.scope_hash, data['scope'])
                        continue
                    if prev and not data.get('error'):
                        same_scope = prev.scope_hash == data['scope'] \
                            and prev.fp_version == res.get('version')
                        same_form = prev.form_hash == data['form']
                        if same_scope and same_form and not full:
                            prev.computed_at = now
                            continue
                        if not same_scope:
                            Event.create({'type': 'scope_changed', 'package_id': self.id,
                                          'feature_id': feature.id, 'role_code': role_code,
                                          'refresh_token': token,
                                          'payload': json.dumps({'old': prev.scope_hash,
                                                                 'new': data['scope']})})
                        elif not same_form:
                            Event.create({'type': 'form_changed', 'package_id': self.id,
                                          'feature_id': feature.id, 'role_code': role_code,
                                          'refresh_token': token})
                    if prev:
                        prev.current = False
                    FP.create(vals)

    def _knowledge_detect_renames(self, added, removed, token):
        """D3：舊鍵消失、同模組同種類出現新鍵、元素簽章相似 → 改名候選。"""
        if not added or not removed:
            return
        threshold = float(self.env['ir.config_parameter'].sudo().get_param(
            'corpaas_knowledge.rename_threshold') or RENAME_THRESHOLD_DEFAULT)
        FP = self.env['corpaas.knowledge.fingerprint'].sudo()
        Rename = self.env['corpaas.knowledge.rename'].sudo()
        Event = self.env['corpaas.knowledge.event'].sudo()

        def sig(feature):
            fp = FP.search([('feature_id', '=', feature.id), ('package_id', '=', self.id)],
                           order='computed_at desc', limit=1)
            return json.loads(fp.signature_json or '[]') if fp else []

        # ★ 只對有自己畫面的種類提候選：設定、精靈、報表共用同一張表單，簽章相同；
        #   簽章為空（沒有指紋）時 similarity([], []) = 1.0，任何一對都會變成候選。
        for old in removed.filtered(lambda f: f.kind in ('menu', 'action', 'button')):
            best, best_score = None, 0.0
            old_sig = sig(old)
            if not old_sig:
                continue
            for new in added.filtered(lambda f: f.module == old.module and f.kind == old.kind):
                new_sig = sig(new)
                if not new_sig:
                    continue
                s = fingerprint_lib.similarity(old_sig, new_sig)
                if s > best_score:
                    best, best_score = new, s
            if best and best_score >= threshold:
                Rename.create({'old_feature_id': old.id, 'new_feature_id': best.id,
                               'similarity': best_score})
                Event.create({'type': 'rename_candidate', 'package_id': self.id,
                              'feature_id': old.id, 'refresh_token': token,
                              'payload': json.dumps({'new': best.feature_key,
                                                     'similarity': best_score})})

    # ------------------------------------------------------------------
    # AI：新功能點歸入能力＋同義詞（第 2、3 項）
    # ------------------------------------------------------------------
    def _knowledge_ai_catalog(self, added, token):
        """新功能點歸類＋同義詞。

        ★ 待歸類的是「classify_pending」的功能點，不只本次新增的：超出單次上限（80）
          或預算用完的，下一次更新接著做；只看本次事件會讓它們永遠不被歸類。
        """
        self.ensure_one()
        pending = self.env['corpaas.knowledge.feature'].sudo().search(
            [('package_ids', 'in', self.id), ('classify_pending', '=', True)])
        if not pending:
            return
        Ai = self.env['corpaas.knowledge.ai']
        caps = self.knowledge_capability_ids
        todo = pending.sorted(lambda f: -f.usage_score)
        payload = [{'key': f.feature_key, 'kind': f.kind, 'name': f.name,
                    'menu_path': f.menu_path, 'model': f.model} for f in todo[:80]]
        prompt = (
            "以下是方案「%s」改版後新增的功能點，以及方案既有的能力。\n"
            "請為每個功能點：(1) 建議歸入哪個能力（用能力 code；都不適合就給 new_capability "
            "名稱）；(2) 產生 3–6 個使用者可能的問法或同義詞。\n"
            "回覆格式：{\"items\":[{\"key\":…,\"capability\":…|null,"
            "\"new_capability\":…|null,\"reason\":…,\"intents\":[…]}]}\n\n"
            "能力：%s\n\n功能點：%s"
        ) % (self.display_name,
             json.dumps([{'code': c.code, 'name': c.name, 'outcome': c.outcome}
                         for c in caps], ensure_ascii=False),
             json.dumps(payload, ensure_ascii=False))
        try:
            data = Ai.ask('classify_features', prompt, package=self, refresh_token=token)
        except hub_client.BudgetExceeded as e:
            self._knowledge_budget_notice(e)
            return
        except hub_client.HubError as e:
            _logger.warning('[knowledge] 功能點分類略過：%s', e)
            return
        todo[:80].write({'classify_pending': False})
        Selection = self.env['corpaas.knowledge.selection'].sudo()
        by_key = {f.feature_key: f for f in todo}
        by_code = {c.code: c for c in caps if c.code}
        for item in (data or {}).get('items') or []:
            feature = by_key.get(item.get('key'))
            if not feature:
                continue
            intents = [i for i in item.get('intents') or [] if isinstance(i, str)]
            if intents:
                # 同義詞只影響檢索，自動生效（第 3 項閘門）。
                feature.intents = '\n'.join(filter(None, [feature.intents] + intents))
            cap = by_code.get(item.get('capability'))
            Selection.create({
                'package_id': self.id, 'kind': 'feature', 'feature_id': feature.id,
                'capability_id': cap.id if cap else False,
                'proposal_json': json.dumps({'new_capability': item.get('new_capability')},
                                            ensure_ascii=False)
                if not cap and item.get('new_capability') else False,
                'reason': item.get('reason'), 'score': feature.usage_score,
            })

    # ------------------------------------------------------------------
    # 說明庫
    # ------------------------------------------------------------------
    def _knowledge_prepare_sandbox(self, master, scenario, token=None):
        self.ensure_one()
        Sandbox = self.env['corpaas.knowledge.sandbox'].sudo()
        name = Sandbox.make_name(self, scenario)
        sb = Sandbox.search([('db_name', '=', name)], limit=1)
        if sb:
            sb.write({'master_instance_id': master.id, 'state': 'pending',
                      'scenario_id': scenario.id})
        else:
            sb = Sandbox.create({'package_id': self.id, 'scenario_id': scenario.id,
                                 'master_instance_id': master.id, 'db_name': name})
        try:
            sb.rebuild()
        except Exception as e:  # noqa: BLE001 - 一個情境失敗不擋其他情境
            _logger.warning('[knowledge] 說明庫 %s 重建失敗：%s', name, e)
            self._knowledge_try_seed_repair(sb, token)
        return sb

    def _knowledge_try_seed_repair(self, sandbox, token=None):
        """D6：示範資料重播失敗 → AI 修腳本 → 走情境的核准閘門。"""
        scenario = sandbox.scenario_id
        if not scenario.seed_error:
            return
        prompt = (
            "情境「%s」的示範資料腳本在新版程式碼上重播失敗。請修正腳本，讓它能成功建立記錄；"
            "只改出錯的記錄，其他照舊。\n格式：{\"seed\":[{\"xmlid\",\"model\",\"values\"}]}，"
            "參照其他記錄用 \"__ref__:<xmlid>\"。\n\n錯誤：%s\n\n目前腳本：%s"
        ) % (scenario.name, scenario.seed_error, scenario.seed_json or '[]')
        try:
            data = self.env['corpaas.knowledge.ai'].ask(
                'seed_repair', prompt, package=self, record=scenario, refresh_token=token)
        except hub_client.HubError as e:
            _logger.warning('[knowledge] 示範資料修補失敗：%s', e)
            return
        seed = (data or {}).get('seed')
        if isinstance(seed, list) and seed:
            scenario.sudo().seed_json = json.dumps(seed, ensure_ascii=False, indent=1)
            scenario.sudo().knowledge_propose('text', note=_('AI 修補示範資料腳本（D6）'))

    def _knowledge_budget_notice(self, err):
        """預算用完：留紀錄給管理者（營運規格：超過的排到下一次並通知）。"""
        self.ensure_one()
        try:
            self.message_post(body=_('知識更新的 AI 預算已用完：%s。未完成的工作會在下一次更新接續。')
                              % err)
        except Exception:  # noqa: BLE001 - 沒有 chatter 也不影響流程
            _logger.info('[knowledge] %s 預算用完：%s', self.display_name, err)

    def solution_package_knowledge_sandbox(self, sandbox_id=None, op='rebuild', package_id=None):
        """佇列派工目標：手動重建／刪除說明庫（複製＋清除＋示範資料動輒數分鐘，
        不能在網頁請求裡跑）。"""
        self.ensure_one()
        sb = self.env['corpaas.knowledge.sandbox'].sudo().browse(sandbox_id).exists()
        if not sb:
            return True
        return sb.drop() if op == 'drop' else sb.rebuild()

    def solution_package_knowledge_ai_job(self, job_id=None, package_id=None):
        """佇列派工目標：按鈕觸發的 AI 工作（見 corpaas.knowledge.ai.enqueue）。"""
        self.ensure_one()
        job = self.env['corpaas.knowledge.ai.job'].sudo().browse(job_id).exists()
        if job:
            job._run()
        return True

    @api.constrains('knowledge_scenario_ids')
    def _check_knowledge_scenarios(self):
        for rec in self:
            rec.knowledge_scenario_ids._check_modules()

    # ------------------------------------------------------------------
    # AI 圈選（第 4 項）
    # ------------------------------------------------------------------
    def action_knowledge_ai_select(self):
        """提議這個方案要說明的情境與能力（排入佇列，完成後在提案清單查看）。"""
        self.ensure_one()
        self._knowledge_master()
        return self.env['corpaas.knowledge.ai'].enqueue(
            self, '_knowledge_ai_select_run', self, note=_('AI 圈選情境與能力'))

    def _knowledge_ai_select_run(self):
        self.ensure_one()
        Feature = self.env['corpaas.knowledge.feature']
        features = Feature.search([('package_ids', 'in', self.id), ('missing', '=', False)],
                                  order='usage_score desc', limit=150)
        scenarios = self.env['corpaas.knowledge.scenario'].search([])
        caps = self.env['corpaas.knowledge.capability'].search([])
        tmpl = self.product_tmpl_id
        prompt = (
            "方案：%s\n定位描述：%s\n\n既有情境：%s\n\n既有能力：%s\n\n功能點（依使用量排序）：%s\n\n"
            "請提議：(1) 此方案該引用哪些既有情境，或需要新增什麼專屬情境（說明要延伸哪個基底）；"
            "(2) 此方案的能力清單（沿用既有能力用 code，新能力給名稱、痛點、成果、包含的功能點 key）。\n"
            "格式：{\"scenarios\":[{\"code\"|\"new\":{…},\"reason\",\"score\"}],"
            "\"capabilities\":[{\"code\"|\"new\":{\"name\",\"pain\",\"outcome\",\"features\":[key]},"
            "\"reason\",\"score\"}]}"
        ) % (tmpl.display_name, (tmpl.description_sale or tmpl.description or '')[:3000],
             json.dumps([{'code': s.code, 'name': s.name, 'base': s.is_base,
                          'narrative': (s.narrative or '')[:300]} for s in scenarios],
                        ensure_ascii=False),
             json.dumps([{'code': c.code, 'name': c.name} for c in caps], ensure_ascii=False),
             json.dumps([{'key': f.feature_key, 'name': f.name, 'menu': f.menu_path}
                         for f in features], ensure_ascii=False))
        data = self.env['corpaas.knowledge.ai'].ask('select', prompt, package=self)
        Selection = self.env['corpaas.knowledge.selection'].sudo()
        sc_by_code = {s.code: s for s in scenarios}
        cap_by_code = {c.code: c for c in caps if c.code}
        for item in (data or {}).get('scenarios') or []:
            Selection.create({
                'package_id': self.id, 'kind': 'scenario',
                'scenario_id': sc_by_code.get(item.get('code')).id
                if sc_by_code.get(item.get('code')) else False,
                'proposal_json': json.dumps(item.get('new'), ensure_ascii=False)
                if item.get('new') else False,
                'reason': item.get('reason'), 'score': item.get('score') or 0})
        for item in (data or {}).get('capabilities') or []:
            Selection.create({
                'package_id': self.id, 'kind': 'capability',
                'capability_id': cap_by_code.get(item.get('code')).id
                if cap_by_code.get(item.get('code')) else False,
                'proposal_json': json.dumps(item.get('new'), ensure_ascii=False)
                if item.get('new') else False,
                'reason': item.get('reason'), 'score': item.get('score') or 0})
        return {
            'type': 'ir.actions.act_window', 'name': _('AI 圈選提案'),
            'res_model': 'corpaas.knowledge.selection', 'view_mode': 'list,form',
            'domain': [('package_id', '=', self.id), ('state', '=', 'proposed')],
        }

    # ------------------------------------------------------------------
    # 觸發點
    # ------------------------------------------------------------------
    def _corpaas_bind_masters(self, version, masters, publish_website=False):
        res = super()._corpaas_bind_masters(version, masters,
                                            publish_website=publish_website)
        self.filtered('knowledge_enabled').knowledge_enqueue_refresh(
            full=True, reason='publish')
        return res

    @api.model
    def _cron_knowledge_monthly(self):
        """每月保底：全量重拍。"""
        self.search([('knowledge_enabled', '=', True)]).knowledge_enqueue_refresh(
            full=True, reason='monthly')

    @api.model
    def _cron_knowledge_image_watch(self):
        """Odoo 映像或核心改版：manifest 看不到，改看母體容器的映像 digest。"""
        for pkg in self.search([('knowledge_enabled', '=', True)]):
            master = pkg._knowledge_master(raise_if_missing=False)
            if not master:
                continue
            try:
                res = remote.run(master.server_id,
                                 "docker inspect --format '{{.Image}}' %s"
                                 % master.odoo_container, dont_raise=True)
                digest = (getattr(res, 'stdout', '') or '').strip()[:128]
            except Exception as e:  # noqa: BLE001
                _logger.warning('[knowledge] 取映像 digest 失敗 %s：%s', pkg.display_name, e)
                continue
            if not digest or digest == pkg.knowledge_image_digest:
                continue
            if pkg.knowledge_image_digest:
                pkg.knowledge_enqueue_refresh(full=True, reason='image')
            # ★ 只有真的變了才寫：每天無條件寫會更新 write_date、跟正在跑的更新搶這一列。
            pkg._knowledge_bookkeep({'knowledge_image_digest': digest})


class Instance(models.Model):
    _inherit = 'infrastructure.instance'

    def _knowledge_is_doc_master(self):
        self.ensure_one()
        server = self.env['infrastructure.solution.package']._knowledge_doc_server()
        return bool(self.template_package_id and server and self.server_id == server)


class InstanceModule(models.Model):
    _inherit = 'infrastructure.instance_module'

    def module_pull_clone_and_checkout(self, update=True, revision=""):
        """母體「下載新版」完成、而且程式碼真的變了 → 排入知識更新。"""
        masters = self.mapped('instance_id').filtered(
            lambda i: i.template_package_id and i._knowledge_is_doc_master())
        before = {m.id: m._corpaas_code_manifest() for m in masters}
        res = super().module_pull_clone_and_checkout(update=update, revision=revision)
        for m in masters:
            if m._corpaas_code_manifest() != before.get(m.id):
                # ★ 下載新版之後母體會重啟；立刻 docker exec 進去會撞在重啟中途。
                m.template_package_id.knowledge_enqueue_refresh(
                    full=False, reason='code', delay_minutes=5)
        return res
