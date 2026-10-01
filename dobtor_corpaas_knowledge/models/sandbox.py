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
    ready_at = fields.Datetime(readonly=True)
    purged_at = fields.Datetime(readonly=True,
                                help='D1 清除完成時間：之後建立的記錄都是示範資料或拍攝產生的')
    password = fields.Char(readonly=True, groups='dobtor_corpaas_knowledge.group_knowledge_manager')
    role_logins = fields.Text(readonly=True, help='{role_code: login}')
    purge_report = fields.Text(readonly=True)
    seed_report = fields.Text(readonly=True)
    error = fields.Text(readonly=True)

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

    def rebuild(self):
        """從黃金庫重建：複製 → 清除 → 重播「已核准」的示範資料＋角色帳號。"""
        self.ensure_one()
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
            scenario = self.scenario_id
            # ★ 只重播核准過的示範資料：AI 修補後還在待核的腳本不能拿來拍對外的圖。
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
            purge = self._shell(scripts.purge_script(self._purge_models(seed)))
            self.write({'purge_report': json.dumps(purge, ensure_ascii=False),
                        'purged_at': fields.Datetime.now(), 'state': 'seeding'})
            password = secrets.token_urlsafe(18)
            res = self._shell(scripts.seed_script(
                scenario.xml_module, seed, scenario.all_roles().as_payload(), password))
            self.write({'seed_report': json.dumps(res, ensure_ascii=False),
                        'password': password,
                        'role_logins': json.dumps(res.get('users') or {})})
            if res.get('errors'):
                scenario.sudo().seed_error = json.dumps(res['errors'], ensure_ascii=False)
                raise UserError(_('示範資料重播失敗 %s 筆（見示範資料報告）')
                                % len(res['errors']))
            scenario.sudo().seed_error = False
            self.write({'state': 'ready', 'ready_at': fields.Datetime.now()})
        except Exception as e:
            self.write({'state': 'failed', 'error': str(e)[:4000]})
            raise
        return True

    def _purge_models(self, seed):
        """D1 要清的業務模型：方案功能點用到的模型＋示範資料的模型＋res.partner。"""
        self.ensure_one()
        features = self.env['corpaas.knowledge.feature'].sudo().search(
            [('package_ids', 'in', self.package_id.id), ('model', '!=', False)])
        models = set(features.mapped('model')) | {r['model'] for r in seed} | {'res.partner'}
        for cap in self.package_id.knowledge_capability_ids:
            models |= {m.strip() for m in (cap.master_data_models or '').splitlines() if m.strip()}
        return sorted(models - {'res.config.settings'})

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
        if not pairs and not refs:
            return []
        since = fields.Datetime.to_string(self.purged_at or self.ready_at
                                          or fields.Datetime.now())
        res = self._shell(scripts.gate_script(pairs or {}, since, refs or {}))
        return res.get('bad') or []

    def action_rebuild(self):
        return self._enqueue_op('rebuild')

    def action_drop(self):
        return self._enqueue_op('drop')

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
                               _('重建') if op == 'rebuild' else _('刪除'))}}
