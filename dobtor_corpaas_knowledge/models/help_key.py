# -*- coding: utf-8 -*-
"""租戶 → 主控台 help API 的簽章金鑰（每個租戶庫一把）。

★ 金鑰由主控台產生、存在該庫的 infrastructure.database 記錄上，再用平台既有的
  `_shell_set_param` 寫進租戶的 ir.config_parameter——不必另開通道，也不經任何人手。
★ 租戶以 HMAC-SHA256 簽「時間戳.原始 body」，主控台依標頭的庫名找金鑰驗證。
  沒有簽章，任何人都能冒用別的庫名查詢、或灌假的「畫面分歧」回報。
★ 租戶身分（計畫 #12）：庫名在不同主機上會撞名，有 `X-KB-Org`（SSO 已下發給租戶的
  `corpaas.org_uuid`）就以組織 UUID 認庫；沒有才退回庫名（舊版租戶）。
★ 防重放（計畫 #12）：簽章涵蓋 params 裡的 nonce，主控台記住 MAX_SKEW×2 內看過的
  nonce，同一個請求重送一次就擋。`corpaas_knowledge.help_require_nonce`＝True 時
  沒帶 nonce 也擋（預設 False：舊版租戶照常可用）。
"""
import hashlib
import json
import hmac
import logging
import secrets
import time

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from ..services import txn

_logger = logging.getLogger(__name__)

MAX_SKEW = 300


def _grace_hours(env):
    try:
        return max(0, int(env['ir.config_parameter'].sudo().get_param('corpaas_knowledge.key_grace_hours', '24')))
    except ValueError:
        return 24


class InfrastructureDatabase(models.Model):
    _inherit = 'infrastructure.database'

    knowledge_help_key = fields.Char(
        string='說明查詢金鑰', copy=False, readonly=True,
        groups='dobtor_corpaas_knowledge.group_knowledge_manager')
    knowledge_help_key_pushed = fields.Datetime(string='說明金鑰下發時間', copy=False,
                                                readonly=True)
    # ★ 輪替期雙金鑰（計畫 #13）：換新金鑰後舊的在寬限期內仍然有效——
    #   租戶的 worker 可能還拿著舊值（ICP 快取、正在進行的請求），不該一換就斷。
    knowledge_help_key_prev = fields.Char(copy=False, readonly=True,
                                          groups='dobtor_corpaas_knowledge.group_knowledge_manager')
    knowledge_help_key_prev_until = fields.Datetime(copy=False, readonly=True)

    def action_knowledge_push_help_key(self):
        if not self.env.user.has_group('dobtor_corpaas_knowledge.group_knowledge_manager'):
            raise AccessError(_('只有知識管理者可以下發說明查詢金鑰。'))
        return self._knowledge_push_help_key()

    def _knowledge_push_help_key(self):
        """逐庫下發；每一庫各自成敗、各自落帳。

        ★ 先寫進租戶、成功才存在主控台：反過來的話，下發失敗就會讓主控台拒絕
          租戶一直在用的舊金鑰。
        ☠️ 不用平台的 `_shell_set_param`：它把值放在指令列上 `echo`，失敗時錯誤訊息
          （連同指令）會帶著金鑰進 log。改走 remote.shell_exec（腳本以檔案上傳）。
        ☠️ 每庫各自 commit：多庫一起下發時後面一庫失敗整批回滾，前面的租戶已經換了
          新金鑰、主控台卻還是舊的——而排程只補「沒有金鑰」的庫，永遠修不回來。
        """
        base = self.env['ir.config_parameter'].sudo().get_param('web.base.url') or ''
        failed = []
        for rec in self.sudo():
            key = secrets.token_urlsafe(32)
            try:
                rec._knowledge_set_tenant_params({'dobtor_ai_help.console_key': key,
                                                  **({'dobtor_ai_help.console_url': base}
                                                     if base else {})})
            except Exception as e:  # noqa: BLE001
                failed.append(rec.name)
                _logger.warning('[knowledge] 下發說明金鑰到 %s 失敗：%s', rec.name,
                                type(e).__name__)
                continue
            vals = {'knowledge_help_key': key, 'knowledge_help_key_pushed': fields.Datetime.now()}
            if rec.knowledge_help_key:
                vals.update({'knowledge_help_key_prev': rec.knowledge_help_key,
                             'knowledge_help_key_prev_until': fields.Datetime.add(
                                 fields.Datetime.now(), hours=_grace_hours(self.env))})
            if txn.in_tests(self.env):
                rec.write(vals)
            else:
                with self.env.registry.cursor() as cr:
                    # ★ 環境留在變數裡並明確 flush（transaction 以 WeakSet 記環境，臨時環境
                    #   被回收後 commit 不會 flush）：否則金鑰已下發到租戶，主控台這邊卻沒存，
                    #   之後的簽章驗證一律失敗。
                    env = self.env(cr=cr)
                    env[self._name].sudo().browse(rec.id).write(vals)
                    env.flush_all()
        if failed and len(self) == 1:
            raise UserError(_('下發失敗：%s（詳見伺服器紀錄）') % ', '.join(failed))
        return True

    def _knowledge_set_tenant_params(self, params):
        """寫租戶的 ir.config_parameter（腳本檔上傳，值不上指令列）。"""
        self.ensure_one()
        from ..services import remote
        script = (
            "import json\n"
            "for k, v in json.loads(%r).items():\n"
            "    env['ir.config_parameter'].sudo().set_param(k, v)\n"
            "env.cr.commit()\n"
            "env.registry.signal_changes()\n"
            "print('__CORPAAS_SHELL__:' + json.dumps({'ok': True}))\n"
        ) % json.dumps(params)
        res = remote.shell_json(self.env, self.instance_id, self.name, script)
        if not res.get('ok'):
            raise UserError(_('租戶沒有回應'))

    @api.model
    def _cron_knowledge_push_help_keys(self, batch=20):
        """知識已啟用的方案底下、還沒有金鑰的正式庫：逐一下發（失敗留到下一次）。"""
        pkgs = self.env['infrastructure.solution.package'].sudo().search(
            [('knowledge_enabled', '=', True)])
        if not pkgs:
            return
        dbs = self.sudo().search([
            ('knowledge_help_key', '=', False), ('state', '=', 'active'),
            ('is_golden_template', '=', False),
            '|', ('born_from_version_id.package_id', 'in', pkgs.ids),
            ('instance_id.template_package_id', 'in', pkgs.ids)], limit=batch)
        for db in dbs:
            try:
                db._knowledge_push_help_key()
            except Exception as e:  # noqa: BLE001 - 一台連不上不擋其他
                _logger.warning('[knowledge] 下發說明金鑰到 %s 失敗：%s', db.name, type(e).__name__)

    @api.model
    def _knowledge_help_db(self, database, org=None):
        """租戶庫記錄。有組織 UUID：庫自己的 UUID，或實例的 UUID（共享租戶）＋庫名；
        組織 UUID 對不到就是查無此庫（不退回庫名：那正是撞名要避開的情況）。"""
        Db = self.sudo()
        if org:
            rec = Db.search([('corpaas_org_uuid', '=', org), ('name', '=', database)], limit=1)
            if not rec:
                rec = Db.search([('instance_id.corpaas_org_uuid', '=', org),
                                 ('name', '=', database)], limit=1)
            return rec
        return Db.search([('name', '=', database)], limit=1)

    @api.model
    def _knowledge_help_key_for(self, database, org=None):
        rec = self._knowledge_help_db(database, org)
        return rec.knowledge_help_key if rec else False

    @api.model
    def _knowledge_help_keys_for(self, database, org=None):
        """目前有效的金鑰：新金鑰，加上寬限期內的舊金鑰。"""
        rec = self._knowledge_help_db(database, org)
        if not rec:
            return []
        keys = [rec.knowledge_help_key] if rec.knowledge_help_key else []
        if rec.knowledge_help_key_prev and rec.knowledge_help_key_prev_until \
                and rec.knowledge_help_key_prev_until > fields.Datetime.now():
            keys.append(rec.knowledge_help_key_prev)
        return keys

    @api.model
    def _knowledge_verify_help_request(self, database, headers, body, nonce=None):
        """回傳 None＝通過；否則回錯誤代碼。"""
        icp = self.env['ir.config_parameter'].sudo()
        require = icp.get_param('corpaas_knowledge.help_require_signature', 'True') == 'True'
        sig = headers.get('X-KB-Signature') or ''
        ts = headers.get('X-KB-Timestamp') or ''
        db_hdr = headers.get('X-KB-Database') or ''
        org = (headers.get('X-KB-Org') or '').strip()[:64] or None
        if not sig:
            return 'unsigned' if require else None
        if db_hdr != database:
            return 'bad_signature'
        try:
            skew = abs(time.time() - int(ts))
        except (TypeError, ValueError):
            return 'bad_signature'
        if skew > MAX_SKEW:
            return 'bad_signature'
        keys = [self._knowledge_help_key_for(database, org)]
        keys += [k for k in self._knowledge_help_keys_for(database, org) if k not in keys]
        keys = [k for k in keys if k]
        if not keys:
            return 'bad_signature'
        if not any(hmac.compare_digest(hmac.new(k.encode(), ts.encode() + b'.' + (body or b''),
                                                hashlib.sha256).hexdigest(), sig) for k in keys):
            return 'bad_signature'
        # ★ nonce 在簽章驗過之後才記：沒簽好的請求不能拿來把別人的 nonce 先占掉。
        if nonce:
            if not self.env['corpaas.knowledge.help.nonce']._knowledge_claim(
                    '%s|%s' % (org or database, nonce)):
                return 'replayed'
        elif icp.get_param('corpaas_knowledge.help_require_nonce', 'False') == 'True':
            return 'replayed'
        return None


class KnowledgeHelpNonce(models.Model):
    """說明 API 看過的 nonce（只留 MAX_SKEW×2 秒；更舊的請求本來就會因時間戳過期被擋）。"""
    _name = 'corpaas.knowledge.help.nonce'
    _description = '說明查詢防重放'
    _log_access = False

    nonce = fields.Char(required=True, index=True)
    ts = fields.Integer(required=True, index=True)

    _sql_constraints = [('nonce_uniq', 'unique(nonce)', 'nonce 重複')]

    @api.model
    def _knowledge_claim(self, nonce):
        """第一次看到回 True；看過回 False。

        ★ 用 ON CONFLICT 而不是先查再寫：兩個 worker 同時收到同一個重送請求時，
          先查再寫兩邊都會查不到。
        """
        now = int(time.time())
        cr = self.env.cr
        cr.execute('DELETE FROM corpaas_knowledge_help_nonce WHERE ts < %s', (now - 2 * MAX_SKEW,))
        cr.execute('INSERT INTO corpaas_knowledge_help_nonce (nonce, ts) VALUES (%s, %s) '
                   'ON CONFLICT (nonce) DO NOTHING RETURNING id', (nonce[:200], now))
        return bool(cr.fetchone())
