# -*- coding: utf-8 -*-
"""方案的知識更新流程（knowledge_refresh）與觸發點。

    kb_check → kb_golden_sync → kb_inventory → kb_fingerprint → kb_ai_catalog
             → kb_sandbox → kb_shoot → kb_outlets → kb_cleanup

★ 只在「說明主機」上的母體做：方案沒有在說明主機上架就擋下（使用者定案），
  不在其他主機部署截圖容器。
★ 黃金庫全程唯讀：盤點與指紋腳本結尾 rollback；拍攝一律在說明庫。
"""
import fnmatch
import hashlib
import json
import logging
import time
import uuid

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from ..services import fingerprint_lib, hub_client, remote, scripts, search_lib, txn
from .toggle import CLASS_RANK, classification_of

#: 方案能力少於這個數、而且一次待歸類的功能點不少於 CLUSTER_MIN_FEATURES：先分群再歸類
CLUSTER_MAX_CAPS = 3
CLUSTER_MIN_FEATURES = 15

_logger = logging.getLogger(__name__)

#: 指紋一次 odoo shell 處理的功能點數。每次 shell 都要重載整個 registry，分太細＝多次載入；
#: 同一個程序裡逐筆算 get_views，記憶體不隨批量成長，所以取大值、一般方案一趟跑完。
FP_CHUNK = 1000
RENAME_THRESHOLD_DEFAULT = 0.6
# 官方模組預設不盤的：框架、技術、在地化、整合與佈景——它們沒有使用者會「學怎麼用」
# 的畫面，盤進來只會稀釋 AI 歸類與說明。可在設定頁（全域）與方案（追加）調整。
OFFICIAL_EXCLUDE_DEFAULT = (
    'base, base_*, web, web_*, bus, auth_*, iap, iap_*, l10n_*, theme_*, test_*, '
    '*_test, *_tests, http_routing, mail_bot*, google_*, microsoft_*, payment_*, '
    'snailmail*, onboarding, digest, utm, resource, uom, phone_validation, '
    'partner_autocomplete, social_media')


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
                                            domain=[('is_check', '=', False)],
                                            string='說明庫')
    knowledge_event_ids = fields.One2many('corpaas.knowledge.event', 'package_id')
    knowledge_last_refresh = fields.Datetime(readonly=True, copy=False)
    knowledge_last_token = fields.Char(readonly=True, copy=False)
    knowledge_image_digest = fields.Char(readonly=True, copy=False)
    knowledge_pending_full = fields.Boolean(readonly=True, copy=False,
                                            help='待執行的更新要做全量（多個觸發合併成一張）')
    knowledge_include_official = fields.Boolean(
        string='納入 Odoo 官方模組', default=True,
        help='盤點範圍除了方案模組，再加上黃金庫實際安裝的 Odoo 官方模組（扣除排除清單）；'
             '官方模組只盤選單與選單動作。')
    knowledge_pending_reason = fields.Char(copy=False, readonly=True,
                                           help='最近一次排入知識更新的原因（執行紀錄用）')
    knowledge_document_native = fields.Boolean(
        string='原生畫面也製作操作說明',
        help='預設（不勾）：沒被客製過的 Odoo 原生畫面不寫操作說明，說明查詢改連 Odoo 官方文件'
             '（不重寫一份官方已有的內容）。\n'
             '勾選：原生畫面也截圖並起草操作說明——適合「帶客戶認識原生功能」的方案'
             '（例如原生進銷存導覽）。')
    knowledge_official_exclude = fields.Char(
        string='追加排除的官方模組',
        help='逗號分隔，可用萬用字元（例如 website_*）；與設定頁的全域排除清單合併。')
    knowledge_fp_manifest = fields.Text(
        readonly=True, copy=False,
        help='上一次算指紋時黃金庫的程式碼與模組版本（JSON），增量重算的比較基準')
    knowledge_fp_image = fields.Char(readonly=True, copy=False,
                                     help='上一次算指紋時的母體映像 digest')
    knowledge_scope_snapshot = fields.Text(
        readonly=True, copy=False,
        help='上一次盤點的模組範圍（JSON），用來偵測範圍變動')
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
            # 觸發原因記在方案上（params 只放 package_id 才能去重），執行時寫進執行紀錄
            rec._knowledge_bookkeep({'knowledge_pending_reason': reason})
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
        """佇列派工目標：知識更新的第一階段（盤點→指紋→流程→AI 歸類→說明庫）。

        ★ A1：更新拆成三張接力的佇列單（盤點與說明庫 → 拍攝 → 出口與收尾），每段各自提交，
          進度即時可見、失敗只重跑那一段，也不會被佇列看門狗判逾時。
          ☠️ 原本十個步驟在同一個 REPEATABLE READ 交易裡跑 2–4 小時：期間查不到任何結果、
          中途失敗全部回滾、超過 120 分鐘沒心跳就被判逾時（實機 2026-10-05）。
        ★ 測試裡（或 context knowledge_inline_stages）三段直接接著跑，不排佇列。
        """
        self.ensure_one()
        # 這個作業跑很久而且不寫方案這一列：簿記改走獨立游標（見 _knowledge_bookkeep）
        self = self.with_context(knowledge_fresh_cursor=True)
        Run = self.env['corpaas.knowledge.run'].sudo()
        busy = Run.search([('package_id', '=', self.id), ('state', '=', 'running'),
                           ('create_date', '>', fields.Datetime.subtract(
                               fields.Datetime.now(), hours=6))], limit=1)
        if busy and not txn.in_tests(self.env):
            # ★ 上一次更新的拍攝／出口階段還在排隊或執行：別在中間插進來重建說明庫，
            #   10 分鐘後再排（超過 6 小時沒結束的紀錄視為已中斷）
            _logger.info('[knowledge] %s 上一次更新（%s）尚未結束，延後', self.display_name, busy.id)
            self.knowledge_enqueue_refresh(full=full, reason=reason, delay_minutes=10)
            return True
        full = full or self._knowledge_take_pending_full()
        reason = reason or self.knowledge_pending_reason or ''
        if self.knowledge_pending_reason:
            self._knowledge_bookkeep({'knowledge_pending_reason': False})
        token = uuid.uuid4().hex
        run = Run.create({
            'package_id': self.id, 'token': token, 'full': bool(full), 'reason': reason or ''})
        self._knowledge_commit()
        try:
            run.begin_stage('prepare')
            self._knowledge_commit()   # 執行紀錄立刻看得到「目前階段」
            sandboxes = self._knowledge_stage_prepare(run)
            run.sandbox_ids = [(6, 0, sandboxes.ids)]
            run.end_stage()
            self._knowledge_commit()
        except Exception as e:
            self._knowledge_stage_failed(run, e)
            raise
        self._knowledge_next_stage(run, 'shoot')
        return True

    def solution_package_knowledge_stage(self, run_id=None, stage=None):
        """佇列派工目標：知識更新的拍攝／出口階段（由前一階段排入）。"""
        self.ensure_one()
        self = self.with_context(knowledge_fresh_cursor=True)
        run = self.env['corpaas.knowledge.run'].sudo().browse(run_id).exists()
        if not run or run.state != 'running':
            return True
        try:
            run.begin_stage(stage)
            self._knowledge_commit()
            if stage == 'shoot':
                self._knowledge_stage_shoot(run)
            elif stage == 'outlets':
                self._knowledge_stage_outlets(run)
            run.end_stage()
            self._knowledge_commit()
        except Exception as e:
            self._knowledge_stage_failed(run, e)
            raise
        if stage == 'shoot':
            self._knowledge_next_stage(run, 'outlets')
        elif stage == 'outlets':
            try:
                self._knowledge_carry_over(run)
            except Exception as e:  # noqa: BLE001 — 排不了隔天只少一次接續，不算更新失敗
                _logger.warning('[knowledge] %s 隔天接續排程失敗：%s', self.display_name, e)
            run.mark_done()
        return True

    def _knowledge_commit(self):
        """階段作業裡的中途提交（測試裡不提交）。"""
        if not txn.in_tests(self.env):
            self.env.cr.commit()

    def _knowledge_stage_failed(self, run, error):
        """記下失敗：先回滾這一段做到一半的寫入，再在乾淨的交易裡寫執行紀錄。"""
        if txn.in_tests(self.env):
            run.mark_failed(error)
            return
        self.env.cr.rollback()
        run.mark_failed(error)
        self.env.cr.commit()

    def _knowledge_next_stage(self, run, stage):
        if txn.in_tests(self.env) or self.env.context.get('knowledge_inline_stages'):
            return self.solution_package_knowledge_stage(run_id=run.id, stage=stage)
        return self._knowledge_enqueue_stage(run, stage)

    def _knowledge_enqueue_stage(self, run, stage):
        q = self.env['corpaas.queue'].sudo()._enqueue(
            self, 'knowledge_stage', {'run_id': run.id, 'stage': stage})
        if q.channel != 'knowledge':
            q.channel = 'knowledge'
        return q

    def _knowledge_stage_prepare(self, run):
        """盤點、指紋、流程、AI 歸類、說明庫。回傳要拍攝的說明庫。"""
        token, full = run.token, run.full
        Event = self.env['corpaas.knowledge.event'].sudo()
        with self._op_step('kb_check'):
            master = self._knowledge_master()
            golden = master._corpaas_golden_db()
            if not golden or golden.golden_state != 'verified':
                raise UserError(_('母體「%s」沒有已驗證的黃金庫。') % master.display_name)
        with self._op_step('kb_golden_sync'):
            with golden._corpaas_golden_lock():
                # 同步會重讀黃金庫模組狀態；本次盤點就會涵蓋變動，不要再排一張更新。
                # golden_refresh_state：知識更新要最新的模組狀態（開通前則只讀快取）
                changed = golden.with_context(
                    knowledge_skip_modules_trigger=True,
                    golden_refresh_state=True)._corpaas_golden_sync_code()
            if changed:
                Event.create({'type': 'code_changed', 'package_id': self.id,
                              'refresh_token': token,
                              'payload': json.dumps({'modules': changed})})
        with self._op_step('kb_inventory'):
            # 盤點＋設定開關＋流程合成一次 odoo shell（只載入一次 registry）
            analysis = self._knowledge_analyze(golden)
            added, removed = self._knowledge_inventory(golden, token, analysis)
        with self._op_step('kb_fingerprint'):
            self._knowledge_fingerprint(golden, token, full=full)
            self._knowledge_detect_renames(added, removed, token)
        with self._op_step('kb_flows'):
            try:
                self._knowledge_flows(golden, token, analysis.get('flows'))
            except Exception as e:  # noqa: BLE001 - 流程是輔助資料，失敗不擋說明更新
                _logger.warning('[knowledge] %s 流程推導失敗：%s', self.display_name, e)
        with self._op_step('kb_ai_catalog'):
            self._knowledge_ai_catalog(added, token)
            self._knowledge_official_docs(token)
            self._knowledge_flow_names(token)
        events = run.events()
        hooks = self.env['corpaas.knowledge.hooks']
        sandboxes = self.env['corpaas.knowledge.sandbox']
        with self._op_step('kb_sandbox'):
            scenarios = self.knowledge_scenario_ids if full else \
                hooks._knowledge_scenarios_needing_shots(self, events)
            for sc in scenarios:
                sb = self._knowledge_prepare_sandbox(master, sc, token)
                sandboxes |= sb
                run.add_stats(**{{'reused': 'sandboxes_reused', 'overlaid': 'sandboxes_overlaid'}
                                 .get(sb.last_prep, 'sandboxes_rebuilt'): 1})
        return sandboxes

    def _knowledge_stage_shoot(self, run):
        events, ctx = run.events(), dict(run.ctx(), run_id=run.id)
        hooks = self.env['corpaas.knowledge.hooks']
        with self._op_step('kb_shoot'):
            for sb in run.sandbox_ids.filtered(lambda s: s.state == 'ready'):
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
        run.add_stats(**ctx.get('stats', {}))

    def _knowledge_stage_outlets(self, run):
        events, ctx = run.events(), dict(run.ctx(), run_id=run.id)
        hooks = self.env['corpaas.knowledge.hooks']
        with self._op_step('kb_outlets'):
            hooks._knowledge_dispatch_events(self, events, ctx)
            events.write({'processed': True})
        with self._op_step('kb_cleanup'):
            try:
                self._knowledge_rebuild_coverage()
            except Exception as e:  # noqa: BLE001 - 報表失敗不影響這次更新
                _logger.warning('[knowledge] %s 覆蓋率重算失敗：%s', self.display_name, e)
            self._knowledge_bookkeep({'knowledge_last_refresh': fields.Datetime.now(),
                                      'knowledge_last_token': run.token})
        run.add_stats(**ctx.get('stats', {}))

    # ------------------------------------------------------------------
    # 方案列的簿記：一律用獨立游標
    # ------------------------------------------------------------------
    def _knowledge_bookkeep(self, vals):
        """☠️ 知識更新一跑幾十分鐘，主交易若寫了方案這一列，整段時間都鎖著它：
        「立即全量更新」按鈕、映像監看排程、上架流程寫同一列都會卡住或撞序列化衝突。
        簿記欄位用獨立游標寫、立即 commit。"""
        for rec in self:
            # ★ 只有在「知識更新作業」裡才用獨立游標：那個作業刻意不寫方案這一列，獨立游標
            #   才不會和它相撞。按鈕、上架、排程這些短交易自己就寫了方案這一列（啟用旗標、
            #   上架版本），若再用獨立游標寫同一列，主交易 commit 時撞 40001（或互等卡死）
            #   ——寫在自己的交易裡即可。
            if txn.in_tests(self.env) or not self.env.context.get('knowledge_fresh_cursor'):
                rec.sudo().write(vals)
                continue
            with self.env.registry.cursor() as cr:
                # ★ 環境要留在變數裡並明確 flush：transaction 用 WeakSet 記環境，一行寫完
                #   臨時環境就被回收，commit 時找不到要 flush 的環境，寫入靜默消失。
                env = self.env(cr=cr)
                env[self._name].sudo().browse(rec.id).write(vals)
                env.flush_all()

    def _knowledge_probe_items(self):
        """重播檢查要數筆數的畫面：要寫說明的功能裡，有選單動作的。

        回傳 ([[功能鍵, 動作 xmlid]], {功能鍵: 顯示名稱})。"""
        self.ensure_one()
        hooks = self.env['corpaas.knowledge.hooks']
        if hasattr(hooks, '_manual_candidates'):
            features = list(hooks._manual_candidates(self))
        else:
            features = self.knowledge_capability_ids.mapped('feature_ids')
        items, labels = [], {}
        for f in features:
            if f.action_xmlid and f.feature_key not in labels:
                items.append([f.feature_key, f.action_xmlid])
                labels[f.feature_key] = f.name
        return items, labels

    def _knowledge_documents_feature(self, feature):
        """這個方案要不要替這個功能製作操作說明（K21＋原生開關）。

        沒被客製過的官方畫面預設不寫（連 Odoo 官方文件）；方案勾了「原生畫面也製作
        操作說明」就照寫。"""
        self.ensure_one()
        if feature.module_origin != 'odoo' or feature.attr_for(self, 'customized'):
            return True
        return bool(self.knowledge_document_native)

    _HEARTBEAT_AT = {}

    def _knowledge_heartbeat(self, step, message=None):
        """長步驟裡定期送佇列心跳（每分鐘最多一次）。

        ☠️ 佇列 watchdog 以 last_step_at 判斷作業死活，預設 120 分鐘沒心跳就判逾時；
          截圖步驟逐一探索 100 多個畫面要兩個多小時，中間沒有心跳就被標成錯誤
          （背景執行緒其實還在跑）。"""
        qid = self.env.context.get('corpaas_queue_id')
        if not qid or txn.in_tests(self.env):
            return
        now = time.monotonic()
        if now - self._HEARTBEAT_AT.get(qid, 0) < 60:
            return
        self._HEARTBEAT_AT[qid] = now
        try:
            self.env['corpaas.queue'].sudo().browse(qid)._notify(step, 'running', message)
        except Exception as e:  # noqa: BLE001 — 心跳失敗不影響作業
            _logger.warning('[knowledge] 佇列心跳失敗：%s', e)

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
    # 盤點範圍
    # ------------------------------------------------------------------
    def _knowledge_official_exclude_patterns(self):
        self.ensure_one()
        raw = self.env['ir.config_parameter'].sudo().get_param(
            'corpaas_knowledge.official_exclude', OFFICIAL_EXCLUDE_DEFAULT)
        raw = '%s,%s' % (raw or '', self.knowledge_official_exclude or '')
        return [p.strip() for p in raw.replace('\n', ',').split(',') if p.strip()]

    def _knowledge_is_official_excluded(self, name, patterns=None):
        patterns = self._knowledge_official_exclude_patterns() if patterns is None \
            else patterns
        return any(fnmatch.fnmatchcase(name, p) for p in patterns)

    def _knowledge_scope_modules(self, golden):
        """(BOM 模組, 範圍內的官方模組, 黃金庫全部已安裝的官方模組)。

        官方模組＝黃金庫追蹤列上 module_type='odoo' 且已安裝的（碼池裡的官方列＋
        相依／手動裝進來的 extra 列，見 infrastructure.database_module）。
        BOM 裡的官方模組算 BOM（全種類盤點），不重複列在官方範圍。
        """
        self.ensure_one()
        bom = self._provision_module_names()
        installed_official = self._knowledge_golden_installed(golden, official_only=True)
        official = []
        if self.knowledge_include_official:
            patterns = self._knowledge_official_exclude_patterns()
            official = sorted(n for n in installed_official - set(bom)
                              if not self._knowledge_is_official_excluded(n, patterns))
        return bom, official, installed_official

    @api.model
    def _knowledge_golden_installed(self, golden, official_only=False):
        """黃金庫上已安裝模組的技術名集合（讀 infrastructure.database_module 追蹤列）。"""
        domain = [('database_id', '=', golden.id), ('state', '=', 'installed')]
        if official_only:
            domain.append(('module_type', '=', 'odoo'))
        rows = self.env['infrastructure.database_module'].sudo().search(domain)
        return set(n for n in rows.mapped('technical_name') if n)

    def _knowledge_available_modules(self):
        """方案客戶實際拿得到的模組：BOM ∪ 說明主機母體黃金庫上已安裝的模組。

        ★ 不能只看 BOM：sale、account 這類官方模組多半是被方案模組相依裝進來的，
          不在 BOM 裡。能力的功能點納入官方模組之後，只看 BOM 會把「方案本來就有」
          的能力誤判成加購或缺少。
        """
        self.ensure_one()
        have = set(self._provision_module_names())
        master = self._knowledge_master(raise_if_missing=False)
        golden = master._corpaas_golden_db() if master else None
        if golden:
            have |= self._knowledge_golden_installed(golden)
        return have

    def _knowledge_record_scope(self, scope, token):
        """範圍和上一次盤點不同 → 發一筆 modules_changed（第一次只記錄）。"""
        self.ensure_one()
        try:
            prev = json.loads(self.knowledge_scope_snapshot or 'null')
        except ValueError:
            prev = None
        if prev == scope:
            return
        if prev is not None:
            old, new = set(prev), set(scope)
            self.env['corpaas.knowledge.event'].sudo().create({
                'type': 'modules_changed', 'package_id': self.id,
                'refresh_token': token,
                'payload': json.dumps({'added': sorted(new - old),
                                       'removed': sorted(old - new)})})
        self._knowledge_bookkeep({'knowledge_scope_snapshot': json.dumps(scope)})

    # ------------------------------------------------------------------
    # 盤點
    # ------------------------------------------------------------------
    def _knowledge_analyze(self, golden):
        """在黃金庫一次跑完盤點＋設定開關＋流程（scripts.analysis_script）。"""
        self.ensure_one()
        modules, official, installed_official = self._knowledge_scope_modules(golden)
        res = remote.shell_json(self.env, golden.instance_id, golden.name,
                                scripts.analysis_script(modules, official=official),
                                isolated=True) or {}
        res['_scope'] = (modules, official, installed_official)
        return res

    def _knowledge_inventory(self, golden, token, analysis=None):
        """回傳 (新增的 feature, 消失的 feature)。"""
        self.ensure_one()
        res = analysis if analysis is not None else self._knowledge_analyze(golden)
        modules, official, installed_official = res.get('_scope') or \
            self._knowledge_scope_modules(golden)
        scope = sorted(set(modules) | set(official))
        self._knowledge_record_scope(scope, token)
        # 設定開關：只有已開啟的才在方案範圍內（沒勾的群組開關所控制的畫面要排除）
        tg = res
        items = self._knowledge_filter_off_groups(res.get('features') or [],
                                                  set(tg.get('off_groups') or []))
        items += self._knowledge_setting_items(tg.get('toggles') or [])
        Feature = self.env['corpaas.knowledge.feature'].sudo().with_context(
            active_test=False)
        Event = self.env['corpaas.knowledge.event'].sudo()
        Selection = self.env['corpaas.knowledge.selection'].sudo()
        now = fields.Datetime.now()
        seen = Feature
        added = Feature
        dirty = set()
        for item in items:
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
                'module_origin': 'odoo' if item['module'] in installed_official
                else 'custom',
                'last_seen': now, 'active': True,
            }
            rec = Feature.search([('feature_key', '=', key)], limit=1)
            if rec:
                # 指紋範圍會看選單路徑與視圖設定：這些變了，增量重算也一定要算它。
                if any((rec[f] or False) != vals[f]
                       for f in ('menu_path', 'view_mode', 'view_xmlid')):
                    dirty.add(rec.id)
                rec.write(vals)
            else:
                rec = Feature.create(dict(vals, feature_key=key, module=item['module'],
                                          kind=item['kind'], anchor=item['anchor']))
            # ★ 「新增」以方案為單位：已存在於別的方案的功能點，對這個方案仍是新的。
            if self not in rec.package_ids:
                # ★ 已在別的方案歸類過：同義詞是全域的、不再請 AI；能力歸類沿用（K11）。
                reuse = rec.ai_classified
                rec.write({'package_ids': [(4, self.id)],
                           'missing_package_ids': [(3, self.id)],
                           'classify_pending': not reuse})
                if reuse:
                    for cap in rec.capability_ids:
                        Selection._knowledge_upsert({
                            'package_id': self.id, 'kind': 'feature', 'feature_id': rec.id,
                            'capability_id': cap.id, 'source': 'reuse',
                            'reason': _('沿用其他方案已核准的歸類')})
                added |= rec
                Event.create({'type': 'feature_added', 'package_id': self.id,
                              'feature_id': rec.id, 'refresh_token': token})
            self._knowledge_sync_entries(rec, item.get('entries') or [],
                                         set(modules) | set(official), now)
            seen |= rec
        # ★ 消失＝這次沒盤到（不再限定 BOM 模組）：模組被移出範圍（拿出 BOM、官方
        #   模組被卸載或加進排除清單）時它的功能點也要下架，限定模組就永遠不會。
        #   一筆都沒盤到多半是腳本那端出了事，不能據此把整個方案的功能點下架。
        if not res.get('features'):
            # ★ 看盤點腳本本身的結果，不看 seen：已設定的參數型開關會讓 seen 非空
            _logger.warning('[knowledge] %s 盤點結果是空的，略過消失判定',
                            self.display_name)
            stale = Feature
        else:
            stale = Feature.search([('package_ids', 'in', self.id),
                                    ('id', 'not in', seen.ids)])
        for rec in stale:
            rec.write({'package_ids': [(3, self.id)], 'missing_package_ids': [(4, self.id)]})
            Event.create({'type': 'feature_removed', 'package_id': self.id,
                          'feature_id': rec.id, 'refresh_token': token})
        Selection.search([('package_id', '=', self.id), ('source', '=', 'reuse'),
                          ('state', '=', 'proposed')])._knowledge_auto_approve()
        toggles = self._knowledge_sync_toggles(tg.get('toggles') or [], installed_official,
                                               now, token)
        self._knowledge_classify(seen, toggles, tg.get('graph') or {}, modules,
                                 installed_official, token)
        if dirty:
            self.env['corpaas.knowledge.feature.class'].sudo().search([
                ('package_id', '=', self.id), ('feature_id', 'in', list(dirty))
            ]).write({'fp_dirty': True})
        self._knowledge_update_usage(seen)
        return added, stale

    # ------------------------------------------------------------------
    # 設定開關與功能分類
    # ------------------------------------------------------------------
    @api.model
    def _knowledge_filter_off_groups(self, items, off):
        """沒勾的群組開關所控制的畫面不屬於方案預設範圍：畫面群組、或它所有入口的群組
        都落在這些群組裡的，不收。"""
        if not off:
            return list(items)

        def hidden(groups):
            return bool(groups) and set(groups) <= off

        out = []
        for it in items:
            entries = it.get('entries') or []
            if hidden(it.get('groups')):
                continue
            if entries and all(hidden(e.get('groups')) for e in entries):
                continue
            if entries:
                it = dict(it, entries=[e for e in entries if not hidden(e.get('groups'))])
            out.append(it)
        return out

    @api.model
    def _knowledge_setting_items(self, toggles):
        """已設定的參數型開關本身成為功能點（kind=setting，進階）。"""
        return [{'kind': 'setting', 'module': t['module'], 'anchor': t['name'],
                 'name': t.get('label') or t['name'], 'model': 'res.config.settings',
                 'menu_path': ' › '.join(t.get('path') or []), 'entries': []}
                for t in toggles if t.get('kind') == 'param' and t.get('module')]

    def _knowledge_sync_toggles(self, data, installed_official, now, token):
        """寫入設定開關（全域記錄，方案關聯記「在哪些方案已開啟」）。"""
        self.ensure_one()
        Toggle = self.env['corpaas.knowledge.toggle'].sudo()
        State = self.env['corpaas.knowledge.toggle.state'].sudo()
        doc_base = self.env['corpaas.knowledge.official_doc']._base().rstrip('/')
        before = set(Toggle.search([('package_ids', 'in', self.id)]).mapped('name'))
        seen = Toggle
        for t in data:
            doc = t.get('doc') or ''
            vals = {
                'kind': t['kind'], 'target': t.get('target') or False,
                'module': t.get('module') or False,
                'module_origin': 'odoo' if t.get('module') in installed_official else 'custom',
                'label': t.get('label') or t['name'], 'help_text': t.get('help') or False,
                'path': ' › '.join(['設定'] + list(t.get('path') or [])),
                'app': t.get('app') or False,
                'doc_url': (doc if doc.startswith('http') else doc_base + doc) if doc else False,
                'value': t.get('value') or False,
                'downstream': ','.join(t.get('downstream') or []) or False,
                'affected_models': ','.join(t.get('models') or []) or False,
                'elements_json': json.dumps(t.get('elements') or []) if t.get('elements') else False,
                'last_seen': now, 'package_ids': [(4, self.id)],
            }
            rec = Toggle.search([('name', '=', t['name'])], limit=1)
            if rec:
                rec.write(vals)
            else:
                rec = Toggle.create(dict(vals, name=t['name']))
            # 依黃金庫而異的值另存一份在「這個方案」的狀態上（全域欄位只是最近一次的值）
            st_vals = {k: vals[k] for k in ('value', 'downstream', 'affected_models',
                                            'elements_json')}
            st_vals['last_seen'] = now
            st = rec.state_for(self)
            if st:
                st.write(st_vals)
            else:
                State.create(dict(st_vals, toggle_id=rec.id, package_id=self.id))
            seen |= rec
        for rec in Toggle.search([('package_ids', 'in', self.id), ('id', 'not in', seen.ids)]):
            rec.package_ids = [(3, self.id)]
            rec.state_for(self).unlink()
        after = set(seen.mapped('name'))
        if before and before != after:
            self.env['corpaas.knowledge.event'].sudo().create({
                'type': 'toggle_changed', 'package_id': self.id, 'refresh_token': token,
                'payload': json.dumps({'on': sorted(after - before),
                                       'off': sorted(before - after)})})
        return seen

    @staticmethod
    def _closure(graph, roots):
        out, todo = set(), list(roots)
        while todo:
            m = todo.pop()
            if m in out:
                continue
            out.add(m)
            todo.extend(graph.get(m) or [])
        return out

    def _knowledge_classify(self, features, toggles, graph, bom, installed_official, token):
        """每個功能點在這個方案的分類（定案規則，依序判斷）：

        1. 模組是已開啟 module_ 開關的目標（不論是否 BOM／相依）→ 進階
           ★ 例外：關掉會連帶移除 BOM 其他模組的開關＝關了方案就壞，實際上關不掉 → 不算
             （例：網站設定的「開票」對應 account，關掉會卸載 sale 與整個方案）
        2. 只因第 1 項模組才裝進來的相依（其他已安裝模組都不需要它）→ 進階
        3. 畫面本身、或它所有入口的群組，都是已勾選 group_ 開關的群組 → 進階
        4. 已設定的參數型開關本身（kind=setting）→ 進階
        5. 其他 → 基礎
        另記：基礎畫面上受群組開關控制的元素（進階元素）、讀取參數的模型（進階行為）、
        方案核心（模組直接列在 BOM）。
        """
        self.ensure_one()
        Class = self.env['corpaas.knowledge.feature.class'].sudo()
        Event = self.env['corpaas.knowledge.event'].sudo()
        bom = set(bom)
        mod_toggles = {t.target: t for t in toggles if t.kind == 'module' and t.target
                       and not (set(filter(None, (t._per_package(self, 'downstream') or '')
                                            .split(','))) & bom)}
        grp_toggles = {t.target: t for t in toggles if t.kind == 'group' and t.target}
        param_toggles = {t.name: t for t in toggles if t.kind == 'param'}
        targets = set(mod_toggles)
        ct = self._closure(graph, targets)
        others = set(graph) - ct
        exclusive = ct - targets - self._closure(graph, others)
        dep_owner = {d: [mod_toggles[t] for t in targets if d in self._closure(graph, [t])]
                     for d in exclusive}
        on_groups = set(grp_toggles)
        elements_by_model = {}
        for t in grp_toggles.values():
            try:
                els = json.loads(t._per_package(self, 'elements_json') or '[]')
            except ValueError:
                els = []
            for e in els:
                elements_by_model.setdefault(e.get('model') or '', []).append((t, e))
        behavior_by_model = {}
        for t in param_toggles.values():
            for m in filter(None, (t._per_package(self, 'affected_models') or '').split(',')):
                behavior_by_model.setdefault(m, set()).add(t.id)
        existing = {c.feature_id.id: c for c in Class.search([('package_id', '=', self.id)])}
        changed = []
        for f in features:
            tier, basis, tgl = 'base', 'base', []
            if f.module in mod_toggles:
                tier, basis, tgl = 'advanced', 'module', [mod_toggles[f.module]]
            elif f.module in exclusive:
                tier, basis, tgl = 'advanced', 'module_dep', dep_owner.get(f.module) or []
            elif f.kind == 'setting' and f.anchor in param_toggles:
                tier, basis, tgl = 'advanced', 'param', [param_toggles[f.anchor]]
            else:
                own = set(filter(None, (f.group_xmlids or '').split(',')))
                entry_groups = [set(filter(None, (e.group_xmlids or '').split(',')))
                                for e in f.entry_ids]
                hit = set()
                if own and own <= on_groups:
                    hit = own
                elif entry_groups and all(g and g <= on_groups for g in entry_groups):
                    hit = set().union(*entry_groups)
                if hit:
                    tier, basis, tgl = 'advanced', 'group', [grp_toggles[g] for g in sorted(hit)]
            elements = []
            if tier == 'base' and f.model:
                for t, e in elements_by_model.get(f.model, []):
                    if f.kind == 'button' and e.get('view') != f.view_xmlid:
                        continue
                    if f.kind not in ('action', 'menu', 'client', 'button'):
                        continue
                    elements.append({'element': e.get('element'), 'toggle': t.name,
                                     'path': t.path,
                                     'origin': 'odoo' if e.get('module') in installed_official
                                     else 'custom',
                                     'core': e.get('module') in bom})
            vals = {
                'tier': tier, 'basis': basis, 'toggle_ids': [(6, 0, [t.id for t in tgl])],
                'behavior_toggle_ids': [(6, 0, sorted(behavior_by_model.get(f.model or '', ())))],
                'advanced_elements': json.dumps(elements, ensure_ascii=False) if elements else False,
                'core': f.module in bom,
                'classification': classification_of(f.module_origin, tier),
            }
            rec = existing.pop(f.id, None)
            if rec:
                if rec.classification != vals['classification']:
                    changed.append({'feature': f.feature_key, 'old': rec.classification,
                                    'new': vals['classification']})
                rec.write(vals)
            else:
                Class.create(dict(vals, feature_id=f.id, package_id=self.id))
        if existing:
            Class.browse([c.id for c in existing.values()]).unlink()
        if changed:
            Event.create({'type': 'class_changed', 'package_id': self.id,
                          'refresh_token': token,
                          'payload': json.dumps(changed[:500], ensure_ascii=False)})

    @api.model
    def _knowledge_sync_entries(self, feature, entries, scope, now):
        """同步一個畫面的入口。只刪「本方案範圍內模組」的入口：別的方案的模組帶來的
        入口（同一個畫面被兩個方案共用）不歸這次盤點管。"""
        Entry = self.env['corpaas.knowledge.feature.entry'].sudo()
        existing = {(e.kind, e.anchor): e for e in feature.entry_ids}
        seen = set()
        for e in entries:
            k = (e['kind'], e['anchor'])
            if k in seen:
                continue
            seen.add(k)
            vals = {'name': e.get('name') or False, 'path': e.get('path') or False,
                    'module': e['module'],
                    'group_xmlids': ','.join(e.get('groups') or []) or False,
                    'last_seen': now}
            if k in existing:
                existing[k].write(vals)
            else:
                Entry.create(dict(vals, feature_id=feature.id, kind=e['kind'],
                                  anchor=e['anchor']))
        gone = [e for k, e in existing.items() if k not in seen and e.module in scope]
        if gone:
            Entry.browse([e.id for e in gone]).unlink()

    def _knowledge_tenant_databases(self):
        """這個方案的租戶庫：從範本誕生的庫，加上共享母體上的租戶。"""
        self.ensure_one()
        return self.env['infrastructure.database'].sudo().search([
            '|', ('born_from_version_id.package_id', '=', self.id),
            ('instance_id.template_package_id', '=', self.id)])

    def _knowledge_update_usage(self, features):
        """租戶使用量（K18）：

        · 有租戶端計數（dobtor_database_tools → activity_stats 的 database.activity.usage）：
          畫面＝動作 xmlid 的開啟次數、按鈕＝(模型, 方法) 的呼叫次數，來源記「實測」；
        · 沒有：退回模型層級的異動數（同模型的功能點分數相同），來源記「模型層級」。
        取近 30 天。
        """
        if 'database.activity.stats' not in self.env:
            return
        dbs = self._knowledge_tenant_databases()
        Stats = self.env['database.activity.stats'].sudo()
        by_model = {}
        for s in Stats.search([('database_id', 'in', dbs.ids)]):
            by_model[s.model_name] = by_model.get(s.model_name, 0) + (s.month_count or 0)
        actions, buttons = {}, {}
        if 'database.activity.usage' in self.env and dbs:
            since = fields.Date.subtract(fields.Date.today(), days=30)
            for u in self.env['database.activity.usage'].sudo().search([
                    ('database_id', 'in', dbs.ids), ('day', '>=', since)]):
                if u.kind == 'action':
                    actions[u.name] = actions.get(u.name, 0) + u.count
                else:
                    k = (u.model or '', u.name)
                    buttons[k] = buttons.get(k, 0) + u.count
        for f in features:
            measured = None
            if f.kind in ('action', 'menu', 'client') and f.action_xmlid in actions:
                measured = actions[f.action_xmlid]
            elif f.kind == 'button' and (f.model or '', f.button_name) in buttons:
                measured = buttons[(f.model or '', f.button_name)]
            if measured is not None:
                vals = {'usage_score': measured, 'usage_source': 'measured'}
            else:
                vals = {'usage_score': by_model.get(f.model or '', 0), 'usage_source': 'model'}
            row = f.class_for(self)
            (row or f).write(vals)
        features._sync_global_aggregates()

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
        code_manifest = golden.instance_id._corpaas_code_manifest()
        manifest = json.dumps(code_manifest, sort_keys=True)
        state = self._knowledge_fp_state(golden, code_manifest)
        changed = None if full else self._knowledge_fp_changed(state)
        prev_elements = {}
        for fp in FP.search([('package_id', '=', self.id), ('current', '=', True),
                             ('feature_id', 'in', features.ids)]):
            prev_elements.setdefault(fp.feature_id.id, fp.elements_json or '[]')
        items = []
        for f in features:
            views = f.views_for_fingerprint()
            if not views:
                continue
            elements = hooks._knowledge_elements_for(f, self) or []
            if changed is not None and not self._knowledge_fp_needed(
                    f.class_for(self) or f, changed, prev_elements.get(f.id),
                    json.dumps(elements)):
                continue
            items.append({'key': f.feature_key, 'model': f.model, 'views': views,
                          'elements': elements,
                          'menu_path': f.menu_path or '', 'view_mode': f.view_mode or ''})
        _logger.info('[knowledge] %s 指紋：%s／%s 個功能點需要計算（%s）',
                     self.display_name, len(items), len(features),
                     '全量' if changed is None else '增量，變動模組 %s' % (
                         ', '.join(sorted(changed)) or '無'))
        by_key = {f.feature_key: f for f in features}
        now = fields.Datetime.now()
        official = self._knowledge_golden_installed(golden, official_only=True) \
            if golden.id else set()
        for start in range(0, len(items), FP_CHUNK):
            chunk = items[start:start + FP_CHUNK]
            res = remote.shell_json(self.env, golden.instance_id, golden.name,
                                    scripts.fingerprint_script(chunk, roles), isolated=True)
            mods_of = res.get('modules') or {}
            for it in chunk:
                feature = by_key.get(it['key'])
                if feature:
                    # get_views 失敗（各角色都沒權限等）拿不到繼承鏈：退回功能點自己的模組，
                    # 否則它每次增量都被當成「未知」而重算。
                    mods = mods_of.get(it['key']) or [feature.module]
                    vals = {'view_modules': ','.join(mods), 'fp_dirty': False}
                    if feature.module_origin == 'odoo':
                        parts = (res.get('parts') or {}).get(it['key']) or {}
                        mine = {m: e for m, e in parts.items() if m not in official}
                        vals.update(
                            customized=bool(mine),
                            custom_modules=','.join(sorted(mine)) or False,
                            custom_elements=json.dumps(sorted(
                                {x for e in mine.values() for x in e})) if mine else False)
                    # 繼承鏈與「是否被改過」依這個方案的黃金庫而定：寫在方案記錄上
                    row = feature.class_for(self)
                    (row or feature).write(vals)
                    if row and 'customized' in vals:
                        feature._sync_global_aggregates()
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
        # 全部算完才記基準：中途失敗下次就全算，不會漏。
        self._knowledge_bookkeep({
            'knowledge_fp_manifest': json.dumps(state, sort_keys=True),
            'knowledge_fp_image': self.knowledge_image_digest or False})

    # ------------------------------------------------------------------
    # 任務流程（K14）
    # ------------------------------------------------------------------
    def _knowledge_flows(self, golden, token, data=None):
        """從黃金庫推導本方案畫面所屬模型的狀態流程，更新流程／步驟／轉換。

        data：合併分析已經算好的 flows（就不再另開一次 shell）。"""
        self.ensure_one()
        Feature = self.env['corpaas.knowledge.feature'].sudo()
        Flow = self.env['corpaas.knowledge.flow'].sudo()
        feats = Feature.search([('package_ids', 'in', self.id), ('missing', '=', False)])
        models_ = sorted({f.model for f in feats if f.kind in ('action', 'menu') and f.model})
        if data is None:
            res = remote.shell_json(self.env, golden.instance_id, golden.name,
                                    scripts.flow_script(models_), isolated=True) if models_ else {}
            data = res.get('flows') or {}
        now = fields.Datetime.now()
        seen = Flow
        for model, d in data.items():
            if model not in models_:
                continue  # 合併分析涵蓋全部盤點到的畫面；只處理本方案範圍內的
            flow = Flow.search([('model', '=', model), ('state_field', '=', d['field'])],
                               limit=1) or Flow.create({'model': model,
                                                        'state_field': d['field']})
            flow.write({'model_name': d.get('model_name') or model,
                        'field_type': d.get('field_type'), 'last_seen': now,
                        'package_ids': [(4, self.id)]})
            self._knowledge_flow_steps(flow, d)
            self._knowledge_flow_transitions(flow, d, feats)
            self._knowledge_flow_tenant(flow)
            seen |= flow
        for flow in seen:
            for t in flow.transition_ids.filtered('opens_model'):
                target = Flow.search([('model', '=', t.opens_model)], limit=1)
                if t.opens_flow_id != target:
                    t.opens_flow_id = target
        for flow in Flow.search([('package_ids', 'in', self.id), ('id', 'not in', seen.ids)]):
            flow.package_ids = [(3, self.id)]
        self._knowledge_flow_usage(seen, feats)
        return seen

    @api.model
    def _knowledge_flow_steps(self, flow, d):
        Step = self.env['corpaas.knowledge.flow.step'].sudo()
        bar = set(d.get('statusbar_visible') or [])
        existing = {s.value: s for s in flow.step_ids}
        keep = set()
        for seq, st in enumerate(d.get('steps') or []):
            vals = {'sequence': seq, 'label': st.get('label') or st['value'],
                    'on_statusbar': not bar or st['value'] in bar}
            keep.add(st['value'])
            if st['value'] in existing:
                existing[st['value']].write(vals)
            else:
                Step.create(dict(vals, flow_id=flow.id, value=st['value']))
        Step.browse([s.id for v, s in existing.items() if v not in keep]).unlink()

    def _knowledge_flow_transitions(self, flow, d, feats):
        """靜態轉換：按鈕在哪些狀態看得到 × 方法寫入的終點狀態。

        ★ 起點空白＝每個狀態都看得到；終點空白＝推不出來或不改狀態。
        ★ 方案屬性層：轉換記「在哪些方案的黃金庫推得出來」。這次沒推出來只拿掉本方案，
          別的方案仍推得出來就保留；沒有任何方案、也沒有租戶／截圖證據才刪。
          ☠️ 直接刪會讓兩個程式版本不同的黃金庫輪流刪掉對方的轉換，流程結構雜湊來回跳，
            每次都重新請 AI 命名。
        """
        Trans = self.env['corpaas.knowledge.flow.transition'].sudo()
        no_feature = self.env['corpaas.knowledge.feature']
        buttons = feats.filtered(lambda f: f.kind == 'button' and f.model == flow.model)
        by_name = {}
        for f in buttons.sorted(lambda f: f.view_mode != 'form'):
            by_name.setdefault(f.button_name, f)
        static = {}
        for b in d.get('buttons') or []:
            froms = b['visible'] if b.get('visible') is not None else ['']
            for fr in froms or ['']:
                for to in b.get('targets') or ['']:
                    if to and fr == to:
                        continue
                    static[(fr, to, b['name'])] = b
        existing = {(t.from_value or '', t.to_value or '', t.button_name or ''): t
                    for t in flow.transition_ids}
        for key, b in static.items():
            vals = {'ev_static': True, 'button_label': b.get('label'),
                    'conditional': bool(b.get('conditional')),
                    'opens_model': (b.get('opens') or [False])[0],
                    'button_feature_id': by_name.get(b['name'], no_feature).id,
                    'package_ids': [(4, self.id)]}
            if key in existing:
                existing[key].write(vals)
            else:
                Trans.create(dict(vals, flow_id=flow.id, from_value=key[0], to_value=key[1],
                                  button_name=key[2]))
        for key, t in existing.items():
            if key in static or self not in t.package_ids:
                continue
            t.package_ids = [(3, self.id)]
            if not t.package_ids:
                if t.ev_tenant or t.ev_shot:
                    t.ev_static = False
                else:
                    t.unlink()
        # 流程上的功能點：入口畫面、按鈕、按鈕打開的精靈／畫面、報表
        opens = set(flow.transition_ids.mapped('opens_model')) - {False}
        reports = set(d.get('reports') or [])
        mine = feats.filtered(lambda f: (
            (f.kind in ('action', 'menu') and f.model == flow.model)
            or f in flow.transition_ids.mapped('button_feature_id')
            or (f.kind in ('wizard', 'action') and f.model in opens)
            or (f.kind == 'report' and f.anchor in reports)))
        # 別的方案帶進來的功能點不歸這次管
        others = flow.feature_ids.filtered(lambda f: self not in f.package_ids)
        flow.feature_ids = [(6, 0, (mine | others).ids)]
        # 結構雜湊取「所有方案」的靜態轉換聯集：任一方案的程式改了才會變
        union = sorted((t.from_value or '', t.to_value or '', t.button_name or '')
                       for t in flow.transition_ids if t.ev_static)
        flow.structure_hash = hashlib.sha256(json.dumps(
            [[s.value for s in flow.step_ids.sorted('sequence')], union],
            sort_keys=True).encode()).hexdigest()[:32]

    def _knowledge_flow_tenant(self, flow):
        """租戶證據（K15）：近 30 天實際發生的「舊狀態→新狀態」次數（本方案的租戶）。

        · 對得上靜態轉換的：標「租戶」、記本方案的次數（多顆按鈕觸發同一條時平均分攤）；
        · 靜態推不出來的：新增一條只有租戶證據的轉換（按鈕不明）；
        · 按鈕沒有實測呼叫次數時，用分攤到的轉換次數當本方案的推估使用量。
        ★ 次數按方案分開記（usage_json），總數是各方案相加——只重設本方案的部分。
        """
        if 'database.activity.transition' not in self.env:
            return
        dbs = self._knowledge_tenant_databases()
        if not dbs:
            return
        since = fields.Date.subtract(fields.Date.today(), days=30)
        counts = {}
        for t in self.env['database.activity.transition'].sudo().search([
                ('database_id', 'in', dbs.ids), ('model', '=', flow.model),
                ('field', '=', flow.state_field), ('day', '>=', since)]):
            k = (t.from_value or '', t.to_value or '')
            counts[k] = counts.get(k, 0) + t.count
        Trans = self.env['corpaas.knowledge.flow.transition'].sudo()
        for t in flow.transition_ids:
            if (t.from_value or '', t.to_value or '') not in counts:
                t._set_package_usage(self, 0)
        for (fr, to), n in counts.items():
            if not to or fr == to:
                continue
            matches = flow.transition_ids.filtered(
                lambda t: (t.to_value or '') == to and (t.from_value or '') in (fr, ''))
            matches = matches.filtered(lambda t: t.ev_static) or matches
            if not matches:
                t = Trans.create({'flow_id': flow.id, 'from_value': fr, 'to_value': to,
                                  'button_name': '', 'package_ids': [(4, self.id)]})
                t._set_package_usage(self, n)
                continue
            share = n // len(matches)
            for t in matches:
                t._set_package_usage(self, share)
                f = t.button_feature_id
                row = f.class_for(self) if f else None
                target = row or f
                if target and target.usage_source != 'measured':
                    target.write({'usage_score': share, 'usage_source': 'estimated'})

    @api.model
    def _knowledge_flow_usage(self, flows, feats):
        for flow in flows:
            tenant = sum(t._package_usage(self) for t in flow.transition_ids)
            entry = max([f.attr_for(self, 'usage_score') or 0 for f in flow.feature_ids
                         if f.kind in ('action', 'menu')] or [0])
            flow._set_package_usage(self, tenant or entry)

    def _knowledge_fp_state(self, golden, code_manifest):
        """指紋比較基準：程式碼 revision ＋ 黃金庫已安裝模組的 DB 版本（官方模組沒有
        revision，映像更新只反映在版本上）。"""
        state = {k: v or '' for k, v in (code_manifest or {}).items()}
        # 設定開關：群組開關不改已安裝模組，但會改畫面（誰看得到什麼）
        for t in self.env['corpaas.knowledge.toggle'].sudo().search(
                [('package_ids', 'in', self.id)]):
            state['t:' + t.name] = t._per_package(self, 'value') or 'on'
        if golden.id:
            rows = self.env['infrastructure.database_module'].sudo().search([
                ('database_id', '=', golden.id), ('state', '=', 'installed')])
            for r in rows:
                if r.technical_name:
                    state['v:' + r.technical_name] = r.db_version or ''
        return state

    def _knowledge_fp_changed(self, state):
        """與上一次算指紋時相比變動的模組；回 None＝要全算（沒有基準或映像換了）。"""
        self.ensure_one()
        try:
            prev = json.loads(self.knowledge_fp_manifest or 'null')
        except ValueError:
            prev = None
        if not isinstance(prev, dict):
            return None
        if (self.knowledge_fp_image or '') != (self.knowledge_image_digest or ''):
            return None
        keys = set(prev) | set(state)
        diff = {k for k in keys if prev.get(k) != state.get(k)}
        if any(k.startswith('t:') for k in diff):
            return None  # 開關變了：影響範圍難以靜態界定，全算（開關很少變）
        return {k[2:] if k.startswith('v:') else k for k in diff}

    @api.model
    def _knowledge_fp_needed(self, feature, changed, prev_elements, elements):
        """增量時這個功能點要不要重算。"""
        if prev_elements is None or feature.fp_dirty or not feature.view_modules:
            return True
        if prev_elements != elements:
            return True  # 截圖範本換了元素清單：要換基準
        return bool(set(feature.view_modules.split(',')) & changed)

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
        for old in removed.filtered(lambda f: f.kind in ('menu', 'action', 'client', 'button')):
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
        ★ 能力清單給「方案能力＋全域能力」（都帶 code）：AI 只能用 code 指名既有能力，
          只給方案能力時，別的方案已有的能力會被當成新能力再提一次。
        ★ 同一批提出的新能力先依名稱相似度合併成一筆「新能力」提案（帶功能點清單），
          核准者看到的是一個候選能力，而不是十個名稱略有不同的提案。
        """
        self.ensure_one()
        pending = self.env['corpaas.knowledge.feature'].sudo().search(
            [('package_ids', 'in', self.id), ('classify_pending', '=', True)])
        if not pending:
            return
        Ai = self.env['corpaas.knowledge.ai']
        Cap = self.env['corpaas.knowledge.capability'].sudo()
        mine = self.knowledge_capability_ids
        caps = Cap.search([('code', '!=', False)])
        # 專用進階 → 專用功能 → 標準進階 → 標準功能（差異化賣點在前），同類再依租戶使用量。
        rank = {c.feature_id.id: CLASS_RANK.get(c.classification, 9)
                for c in self.env['corpaas.knowledge.feature.class'].sudo().search(
                    [('package_id', '=', self.id), ('feature_id', 'in', pending.ids)])}
        todo = pending.sorted(lambda f: (rank.get(f.id, 1 if f.module_origin == 'custom' else 3),
                                         -(f.attr_for(self, 'usage_score') or 0)))
        batch = todo[:80]
        payload = [{'key': f.feature_key, 'kind': f.kind, 'name': f.name,
                    'menu_path': f.menu_path, 'model': f.model} for f in batch]
        # ★ 從零開始（方案還幾乎沒有能力、一次來一大批）：先分群再歸類。
        #   逐一歸類時 AI 找不到可用的能力，幾乎每個功能點各提一個新能力（實機 108 個功能點
        #   提了 71 個），核准者得逐一排除。改成先分出 6–10 個能力，新能力名稱只能從中挑。
        cluster = len(mine) < CLUSTER_MAX_CAPS and len(batch) >= CLUSTER_MIN_FEATURES
        group_rule = (
            "本方案目前幾乎沒有能力：請先把這批功能點分成 6–10 個業務能力（依使用者要完成的"
            "工作分，例如聯絡人、產品、銷售、採購、庫存、應收付；設定頁與報表歸到它服務的那個能力，"
            "不要單獨成一個能力），每個能力至少涵蓋 3 個功能點，放在 capabilities；"
            "new_capability 只能填 capabilities 裡的名稱。\n") if cluster else ''
        prompt = (
            "以下是方案「%s」改版後新增的功能點，以及既有的能力（in_package 表示已在本方案）。\n"
            "%s"
            "請為每個功能點：(1) 建議歸入哪個能力（用能力 code；優先用本方案的，其次全域既有的；"
            "都不適合才給 new_capability 名稱）；(2) 產生 3–6 個使用者可能的問法或同義詞。\n"
            "回覆格式：{%s\"items\":[{\"key\":…,\"capability\":…|null,"
            "\"new_capability\":…|null,\"reason\":…,\"intents\":[…]}]}\n\n"
            "能力：%s\n\n功能點：%s"
        ) % (self.display_name, group_rule,
             '\"capabilities\":[{\"name\":…,\"outcome\":…,\"pain\":…}],' if cluster else '',
             json.dumps([{'code': c.code, 'name': c.name, 'outcome': c.outcome,
                          'in_package': c in mine} for c in caps], ensure_ascii=False),
             json.dumps(payload, ensure_ascii=False))
        try:
            data = Ai.ask('classify_features', prompt, package=self, refresh_token=token)
        except hub_client.BudgetExceeded as e:
            self._knowledge_budget_notice(e)
            return
        except hub_client.HubError as e:
            _logger.warning('[knowledge] 功能點分類略過：%s', e)
            return
        batch.write({'classify_pending': False, 'ai_classified': True})
        Selection = self.env['corpaas.knowledge.selection'].sudo()
        by_key = {f.feature_key: f for f in batch}
        by_code = {c.code: c for c in caps}
        groups = []  # [(代表名稱, [items])]
        planned = {}  # 分群模式：AI 分出的能力 {名稱: {outcome, pain}}
        if cluster:
            for c in (data or {}).get('capabilities') or []:
                if isinstance(c, dict) and isinstance(c.get('name'), str) and c['name'].strip():
                    planned[c['name'].strip()] = {'outcome': c.get('outcome'), 'pain': c.get('pain')}
            for name in planned:
                groups.append((name, []))
        for item in (data or {}).get('items') or []:
            feature = by_key.get(item.get('key'))
            if not feature:
                continue
            intents = [i for i in item.get('intents') or [] if isinstance(i, str)]
            if intents:
                # 同義詞只影響檢索，自動生效（第 3 項閘門）。
                feature._knowledge_add_intents(intents)
            cap = by_code.get(item.get('capability'))
            new_name = item.get('new_capability') if not cap else None
            if planned and isinstance(new_name, str) and new_name not in planned:
                # 分群模式：清單外的名稱靠到最像的一群；都不像就先不歸（共通操作）
                best = max(planned, key=lambda n: search_lib.similarity(n, new_name))
                new_name = best if search_lib.similarity(best, new_name) >= 0.3 else None
            if new_name and isinstance(new_name, str):
                existing = Cap._knowledge_find_by_name(new_name)
                if existing:
                    cap, new_name = existing, None
            if cap or not new_name:
                Selection._knowledge_upsert({
                    'package_id': self.id, 'kind': 'feature', 'feature_id': feature.id,
                    'capability_id': cap.id if cap else False,
                    'reason': item.get('reason'),
                    'score': feature.attr_for(self, 'usage_score') or 0})
                continue
            exact = [g for g in groups if g[0] == new_name]
            similar = exact or ([] if planned else [
                g for g in groups if search_lib.similarity(g[0], new_name) >= 0.5])
            if similar:
                similar[0][1].append((feature, item))
            else:
                groups.append((new_name, [(feature, item)]))
        for name, members in groups:
            if not members:
                continue
            Selection._knowledge_upsert({
                'package_id': self.id, 'kind': 'capability',
                'proposal_json': json.dumps(dict({
                    'new_capability': name,
                    'features': [f.feature_key for f, _i in members],
                    'aliases': sorted({i.get('new_capability') for _f, i in members} - {name}),
                }, **{k: v for k, v in planned.get(name, {}).items() if v}),
                    ensure_ascii=False),
                'reason': '\n'.join(filter(None, (i.get('reason') for _f, i in members)))[:2000],
                'score': sum(f.attr_for(self, 'usage_score') or 0 for f, _i in members)})

    def _knowledge_flow_names(self, token, batch=10):
        """流程結構變了（或從沒命名過）→ 請 AI 用業務語言命名、寫摘要、建議能力（K25）。

        結果是「流程」提案，核准後才生效；同一個流程已有待審提案就先不問。
        以流程為單位歸類能力：一次掛一整組功能點，比逐個按鈕歸類少很多呼叫、也少很多重複能力。
        """
        self.ensure_one()
        Sel = self.env['corpaas.knowledge.selection'].sudo()
        flows = self.env['corpaas.knowledge.flow'].sudo().search([
            ('package_ids', 'in', self.id), ('structure_hash', '!=', False)])
        waiting = set(Sel.search([('package_id', '=', self.id), ('kind', '=', 'flow'),
                                  ('state', '=', 'proposed')]).mapped('flow_id').ids)
        todo = flows.filtered(lambda f: f.structure_hash != f.named_hash
                              and f.id not in waiting)[:batch]
        if not todo:
            return Sel
        Cap = self.env['corpaas.knowledge.capability'].sudo()
        caps = Cap.search([('code', '!=', False)])
        mine = self.knowledge_capability_ids
        prompt = (
            "以下是方案「%s」裡的任務流程（狀態步驟與觸發按鈕）。請為每個流程：(1) 取一個使用者"
            "看得懂的業務名稱（4–12 字）；(2) 用 1–2 句寫出這個流程在做什麼；(3) 建議歸入哪個能力"
            "（用能力 code；優先本方案的；都不適合才給 new_capability 名稱）。\n"
            "格式：{\"items\":[{\"model\":…,\"name\":…,\"summary\":…,"
            "\"capability\":…|null,\"new_capability\":…|null,\"reason\":…}]}\n\n"
            "能力：%s\n\n流程：%s"
        ) % (self.display_name,
             json.dumps([{'code': c.code, 'name': c.name, 'in_package': c in mine}
                         for c in caps], ensure_ascii=False),
             json.dumps([f.as_outline() for f in todo], ensure_ascii=False))
        try:
            data = self.env['corpaas.knowledge.ai'].ask('flow_name', prompt, package=self,
                                                        refresh_token=token)
        except hub_client.BudgetExceeded as e:
            self._knowledge_budget_notice(e)
            return Sel
        except hub_client.HubError as e:
            _logger.warning('[knowledge] 流程命名略過：%s', e)
            return Sel
        by_model = {f.model: f for f in todo}
        by_code = {c.code: c for c in caps}
        out = Sel
        for item in (data or {}).get('items') or []:
            flow = by_model.get(item.get('model'))
            if not flow:
                continue
            cap = by_code.get(item.get('capability'))
            new_cap = item.get('new_capability') if not cap else None
            if new_cap:
                existing = Cap._knowledge_find_by_name(new_cap)
                if existing:
                    cap, new_cap = existing, None
            out |= Sel._knowledge_upsert({
                'package_id': self.id, 'kind': 'flow', 'flow_id': flow.id,
                'capability_id': cap.id if cap else False,
                'proposal_json': json.dumps({
                    'name': item.get('name'), 'summary': item.get('summary'),
                    'new_capability': new_cap}, ensure_ascii=False),
                'reason': item.get('reason'), 'score': flow.usage_score})
        return out

    def _knowledge_official_docs(self, token, batch=40):
        """沒被改過的官方畫面 → 請 AI 提議 Odoo 官方文件網址，系統驗證後自動核准（K20）。

        已經有對照（含被否決的）就不再問：被否決代表人工判斷過，不該每次又冒出來。
        """
        self.ensure_one()
        Doc = self.env['corpaas.knowledge.official_doc'].sudo()
        todo = self.env['corpaas.knowledge.feature'].sudo().search([
            ('package_ids', 'in', self.id), ('missing', '=', False),
            ('module_origin', '=', 'odoo'),
            ('kind', 'in', ('action', 'client', 'setting'))])
        # 「改過」與使用量都依這個方案（方案屬性層）
        todo = todo.filtered(lambda f: not f.attr_for(self, 'customized')).sorted(
            lambda f: -(f.attr_for(self, 'usage_score') or 0))
        done = set(Doc.search([('feature_id', 'in', todo.ids)]).mapped('feature_id').ids)
        todo = todo.filtered(lambda f: f.id not in done)
        # 設定頁 <setting documentation=…> 是官方自己給的章節：先用它，不必請 AI 猜
        out = Doc
        for f in todo:
            cls = f.class_for(self)
            url = next((t.doc_url for t in cls.toggle_ids if t.doc_url), None) if cls else None
            if url:
                ok = Doc._verify_url(url)
                out |= Doc.create({'feature_id': f.id, 'url': url,
                                   'title': cls.toggle_ids[:1].label or False,
                                   'verified': ok, 'auto_approved': ok,
                                   'state': 'approved' if ok else 'proposed',
                                   'note': '設定頁官方文件'})
        todo = todo.filtered(lambda f: f not in out.mapped('feature_id'))[:batch]
        if not todo:
            return out
        base = Doc._base()
        prompt = (
            "以下是 Odoo 18 官方模組的畫面（沒有被客製）。請為每個畫面找出 Odoo 18 官方使用說明"
            "最對應的章節網址。★ 本題例外：請輸出網址，系統會逐一連線驗證；"
            "網址必須以 %s 開頭，找不到把握的就回 null，不要猜。\n"
            "格式：{\"items\":[{\"key\":…,\"url\":…|null,\"title\":…}]}\n\n畫面：%s"
        ) % (base, json.dumps([{'key': f.feature_key, 'module': f.module, 'name': f.name,
                                'menu_path': f.menu_path, 'model': f.model} for f in todo],
                              ensure_ascii=False))
        try:
            data = self.env['corpaas.knowledge.ai'].ask('official_doc', prompt, package=self,
                                                        refresh_token=token)
        except hub_client.BudgetExceeded as e:
            self._knowledge_budget_notice(e)
            return Doc
        except hub_client.HubError as e:
            _logger.warning('[knowledge] 官方文件對照略過：%s', e)
            return Doc
        by_key = {f.feature_key: f for f in todo}
        for item in (data or {}).get('items') or []:
            f = by_key.get(item.get('key'))
            url = item.get('url')
            if not f or not isinstance(url, str) or not url.strip():
                continue
            url = url.strip()
            ok = Doc._verify_url(url)
            out |= Doc.create({'feature_id': f.id, 'url': url,
                               'title': (item.get('title') or '')[:200] or False,
                               'verified': ok, 'auto_approved': ok,
                               'state': 'approved' if ok else 'proposed'})
        return out

    # ------------------------------------------------------------------
    # 說明庫
    # ------------------------------------------------------------------
    def _knowledge_prepare_sandbox(self, master, scenario, token=None):
        self.ensure_one()
        Sandbox = self.env['corpaas.knowledge.sandbox'].sudo()
        name = Sandbox.make_name(self, scenario)
        sb = Sandbox.search([('db_name', '=', name)], limit=1)
        if sb and sb.master_instance_id == master and sb.scenario_id == scenario \
                and sb._reusable():
            # ★ R1：輸入沒變、沒被拍攝改動 → 沿用，不重新複製黃金庫
            sb.write({'state': 'ready', 'last_prep': 'reused'})
            _logger.info('[knowledge] 說明庫 %s 輸入未變，沿用', name)
            return sb
        delta = sb._overlay_delta() if sb and sb.master_instance_id == master \
            and sb.scenario_id == scenario else None
        if delta is not None:
            # ★ R2：示範資料只有新增 → 寫進現有說明庫，不重新複製
            try:
                sb.overlay(delta)
                _logger.info('[knowledge] 說明庫 %s 疊加新增示範資料 %s 筆', name, len(delta))
                return sb
            except Exception as e:  # noqa: BLE001 — 疊加失敗就照常重建
                _logger.warning('[knowledge] 說明庫 %s 疊加失敗，改重建：%s', name, e)
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

    def solution_package_knowledge_sandbox(self, sandbox_id=None, op='rebuild', package_id=None,
                                           scenario_id=None):
        """佇列派工目標：手動重建／刪除說明庫、送審前重播檢查（複製＋清除＋示範資料
        動輒數分鐘，不能在網頁請求裡跑）。"""
        self.ensure_one()
        if op == 'check':
            scenario = self.env['corpaas.knowledge.scenario'].sudo().browse(scenario_id).exists()
            if scenario:
                self.env['corpaas.knowledge.sandbox'].run_seed_check(self, scenario)
            return True
        sb = self.env['corpaas.knowledge.sandbox'].sudo().browse(sandbox_id).exists()
        if not sb:
            return True
        if op == 'selftest':
            return sb.selftest()
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
        base = [('package_ids', 'in', self.id), ('missing', '=', False)]
        # 自有模組優先，官方模組保留配額（最多 30）：納入官方畫面後，只依使用量排序會把
        # 方案自己的功能擠出名單。
        def top(origin):
            recs = Feature.search(base + [('module_origin', '=', origin)])
            return recs.sorted(lambda f: -(f.attr_for(self, 'usage_score') or 0))[:150]
        own = top('custom')
        off = top('odoo')
        quota = min(30, len(off))
        own = own[:150 - quota]
        features = own | off[:150 - len(own)]
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
            Selection._knowledge_upsert({
                'package_id': self.id, 'kind': 'scenario',
                'scenario_id': sc_by_code.get(item.get('code')).id
                if sc_by_code.get(item.get('code')) else False,
                'proposal_json': json.dumps(item.get('new'), ensure_ascii=False)
                if item.get('new') else False,
                'reason': item.get('reason'), 'score': item.get('score') or 0})
        for item in (data or {}).get('capabilities') or []:
            Selection._knowledge_upsert({
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
                # 增量即可：指紋會找出真的變了的畫面，只重拍那些；全量重拍留給每月保底。
                pkg.knowledge_enqueue_refresh(full=False, reason='image')
            # ★ 只有真的變了才寫：每天無條件寫會更新 write_date、跟正在跑的更新搶這一列。
            pkg._knowledge_bookkeep({'knowledge_image_digest': digest})


class Database(models.Model):
    _inherit = 'infrastructure.database'

    def _on_installed_modules_changed(self, added, removed):
        """說明主機母體的黃金庫安裝集合變了，而且變動落在盤點範圍內 → 排增量更新。"""
        res = super()._on_installed_modules_changed(added, removed)
        if self.env.context.get('knowledge_skip_modules_trigger'):
            return res
        for rec in self.filtered('is_golden_template'):
            master = rec.instance_id
            pkg = master.template_package_id
            if not (pkg and pkg.knowledge_enabled and master._knowledge_is_doc_master()):
                continue
            bom = set(pkg._provision_module_names())
            patterns = pkg._knowledge_official_exclude_patterns()
            relevant = [n for n in list(added) + list(removed)
                        if n in bom or (pkg.knowledge_include_official
                                        and not pkg._knowledge_is_official_excluded(
                                            n, patterns))]
            if relevant:
                _logger.info('[knowledge] %s 黃金庫模組變動：%s', pkg.display_name,
                             ', '.join(relevant))
                pkg.knowledge_enqueue_refresh(full=False, reason='modules')
        return res


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
