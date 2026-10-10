# -*- coding: utf-8 -*-
"""AI 呼叫的單一入口：設定、預算、記帳、JSON 解析。

所有出口都經過 `env['corpaas.knowledge.ai'].ask(...)`，預算才算得準。
"""
import hashlib
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..services import hub_client, txn

_logger = logging.getLogger(__name__)

#: 共通的系統指示。Runner 對 content 模式沒有系統提示（SYSTEM_PROMPTS 沒有這個鍵），
#: 所以角色與輸出格式全部寫在這裡，由 Hub 原樣轉交。
BASE_INSTRUCTIONS = """你是 CorPaaS 的產品知識編輯。規則：
1. 一律使用繁體中文（台灣用語）。
2. 只根據提供的資料作答；資料沒有的事實不要編造（功能、欄位、數字、價格）。
3. 回覆只包含一個 ```json 區塊，格式照題目指定；不要多餘說明。
4. 不要輸出任何網址或連結——連結由系統產生。
"""


#: 可快取的用途：輸入相同、結果就該相同的歸類／圈選類工作。
#: ☠️ 起草、修補類不快取——它們的結果會被驗證，驗證失敗後重試同一個 prompt，
#:   快取會讓它永遠拿到同一份壞結果。
CACHEABLE = {'classify_features', 'select', 'help_misses', 'flow_name', 'official_doc',
             'gap_cluster'}


#: 單次呼叫的預設成本（USD）：沒有歷史紀錄時成本規劃器用這些（2026-10 實機平均）
DEFAULT_UNIT_COST = {
    'classify_features': 0.25, 'flow_name': 0.07, 'official_doc': 0.19, 'select': 0.23,
    'manual_explore': 0.12, 'manual_repair': 0.11, 'manual_bind': 0.05,
    'manual_step_block': 0.05, 'manual_scenario': 0.06, 'manual_fork': 0.05,
    'scenario_seed': 0.40, 'seed_repair': 0.40, 'seed_gap_fill': 0.30, 'manual_review': 0.03,
}


#: 預取的 AI 回覆（同一行程內）：{(資料庫, 用途＋提示詞雜湊): text}。ask 用到就取走。
_PREFETCH = {}


def _prefetch_key(dbname, purpose, prompt):
    return dbname, hashlib.sha256(('%s\n%s' % (purpose, prompt)).encode('utf-8')).hexdigest()



#: 要先看「方案檔案」的 AI 工作：圈選情境與角色、起草／補／修示範資料、修截圖腳本、探索畫面
PROFILE_PURPOSES = {'select', 'scenario_seed', 'seed_gap_fill', 'seed_repair', 'manual_repair',
                    'manual_explore'}

class KnowledgeAi(models.AbstractModel):
    _name = 'corpaas.knowledge.ai'
    _description = '知識 AI 呼叫'

    @api.model
    def _conf(self):
        icp = self.env['ir.config_parameter'].sudo()
        return {
            'hub_url': icp.get_param('corpaas_knowledge.hub_url') or '',
            'hub_key': icp.get_param('corpaas_knowledge.hub_key') or '',
            'budget': float(icp.get_param('corpaas_knowledge.budget_usd_per_refresh') or 20.0),
        }

    @api.model
    def spent(self, refresh_token):
        if not refresh_token:
            return 0.0
        # ★ 帳是用獨立游標寫的；佇列作業的主交易是 REPEATABLE READ，看不到之後才
        #   commit 的帳——同一個游標讀會永遠低估，預算形同虛設。
        query = ("SELECT COALESCE(SUM(cost_usd), 0) FROM corpaas_knowledge_ai_call "
                 "WHERE refresh_token = %s")
        if txn.in_tests(self.env):
            self.env.flush_all()
            self.env.cr.execute(query, (refresh_token,))
            return float(self.env.cr.fetchone()[0] or 0.0)
        with self.env.registry.cursor() as cr:
            cr.execute(query, (refresh_token,))
            return float(cr.fetchone()[0] or 0.0)

    @api.model
    def _split_static(self, static):
        """固定內容要不要另外送（吃提示詞快取）。回傳 (system, 併進 prompt 的前綴)。

        ★ 系統參數 corpaas_knowledge.hub_system_prompt 開了才分開送（AI Hub 要先升級）；
          沒開就照舊全部併在 prompt 前面，內容一樣、只是吃不到快取。"""
        on = self.env['ir.config_parameter'].sudo().get_param('corpaas_knowledge.hub_system_prompt')
        if on in ('1', 'True', 'true'):
            return BASE_INSTRUCTIONS + ('\n' + static if static else ''), ''
        return None, BASE_INSTRUCTIONS + '\n' + (static + '\n\n' if static else '')

    def ask(self, purpose, prompt, package=None, refresh_token=None, record=None,
            expect_json=True, context=None, static=None):
        """送出並等待；回傳解析後的 JSON（或純文字）。

        超出本次 refresh 預算時拋 BudgetExceeded——呼叫端應把工作留到下一次，
        而不是當成失敗。
        """
        conf = self._conf()
        prompt = self._with_profile(purpose, prompt, package)
        cacheable = purpose in CACHEABLE
        phash = hashlib.sha256(('%s\n%s\n%s' % (purpose, static or '', prompt)).encode('utf-8')
                               ).hexdigest()[:40] if cacheable else False
        if cacheable:
            hit = self._cache_get(purpose, phash)
            if hit is not None:
                self._log_call({'purpose': purpose, 'refresh_token': refresh_token,
                                'package_id': package.id if package else False,
                                'ok': True, 'cost_usd': 0.0, 'cached': True,
                                'prompt_hash': phash})
                return hub_client.extract_json(hit) if expect_json else hit
        pre = _PREFETCH.pop(_prefetch_key(self.env.cr.dbname, purpose, (static or '') + prompt), None)
        if pre is not None:
            # 已由 prefetch 平行問過（帳也記過了）：直接用
            return hub_client.extract_json(pre) if expect_json else pre
        if refresh_token and self.spent(refresh_token) >= conf['budget']:
            raise hub_client.BudgetExceeded(
                _('本次更新的 AI 預算（%s USD）已用完') % conf['budget'])
        left = self.hub_cost_left()
        if left is not None and left <= 0:
            raise hub_client.BudgetExceeded(_('AI Hub 今日額度已用完，明天再繼續'))
        vals = {'purpose': purpose, 'refresh_token': refresh_token,
                'package_id': package.id if package else False,
                'res_model': record._name if record else False,
                'res_id': record.id if record else 0}
        system, head = self._split_static(static)
        try:
            text, cost, run_id = hub_client.call(
                conf['hub_url'], conf['hub_key'], purpose, head + prompt, context=context,
                **({'system': system} if system else {}))
        except hub_client.HubError as e:
            self._log_call(dict(vals, **self._quota_vals(), ok=False, error=str(e)[:2000]))
            raise
        self._log_call(dict(vals, **self._quota_vals(), ok=True, cost_usd=cost, run_id=run_id,
                            prompt_hash=phash, response_text=text if cacheable else False))
        if not expect_json:
            return text
        return hub_client.extract_json(text)

    # ------------------------------------------------------------------
    # 成本規劃（D3）
    # ------------------------------------------------------------------
    @api.model
    def _today(self):
        """Hub 的「今日」以台北日期計（Hub 與主控台都在 UTC+8 營運）。"""
        from datetime import timedelta
        return (fields.Datetime.now() + timedelta(hours=8)).date().isoformat()

    @api.model
    def _with_profile(self, purpose, prompt, package):
        """方案檔案（計畫第 32 項）：判斷環境的工作都先告訴 AI 方案實際長怎樣。

        ★ ask 與 prefetch 都要經過這裡：否則預先問的鍵（沒加前綴）對不上 ask 的鍵，同一題付兩次錢。"""
        if package and purpose in PROFILE_PURPOSES and hasattr(package, '_knowledge_profile_text'):
            prof = package._knowledge_profile_text()
            if prof:
                return prof + '\n\n' + prompt
        return prompt

    @api.model
    def prefetch(self, items, package=None, refresh_token=None, workers=3):
        """平行送出多個 AI 呼叫（只有 HTTP 在執行緒裡；記帳回主執行緒做）。

        items: [(purpose, prompt)]。結果放進 _PREFETCH，之後同一個 purpose＋prompt 的
        ask() 直接拿走。失敗的不放（ask 時照常再問一次）。回傳成功筆數。
        ★ 起草一篇要兩次 AI 呼叫、每次約 30 秒；94 篇一個接一個要 70 多分鐘。"""
        from concurrent.futures import ThreadPoolExecutor
        if txn.in_tests(self.env) and not self.env.context.get('kb_prefetch_in_tests'):
            return 0
        conf = self._conf()
        items = [(it[0], self._with_profile(it[0], it[1], package), it[2] if len(it) > 2 else None)
                 for it in items]
        todo = [(p, q, st) for p, q, st in items
                if _prefetch_key(self.env.cr.dbname, p, (st or '') + q) not in _PREFETCH]
        if not todo:
            return 0
        if refresh_token and self.spent(refresh_token) >= conf['budget']:
            return 0

        splits = {st: self._split_static(st) for _p, _q, st in todo}   # 讀系統參數要在主執行緒

        def one(item):
            purpose, prompt, static = item
            system, head = splits[static]
            try:
                return item, hub_client.call(conf['hub_url'], conf['hub_key'], purpose, head + prompt,
                                             **({'system': system} if system else {})), None
            except hub_client.HubError as e:
                return item, None, e

        done = 0
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            results = list(pool.map(one, todo))
        for (purpose, prompt, static), res, err in results:
            vals = {'purpose': purpose, 'refresh_token': refresh_token,
                    'package_id': package.id if package else False}
            if err:
                self._log_call(dict(vals, **self._quota_vals(), ok=False, error=str(err)[:2000]))
                continue
            text, cost, run_id = res
            self._log_call(dict(vals, **self._quota_vals(), ok=True, cost_usd=cost,
                                run_id=run_id))
            _PREFETCH[_prefetch_key(self.env.cr.dbname, purpose, (static or '') + prompt)] = text
            done += 1
        return done

    @api.model
    def ask_checked(self, purpose, prompt, check, **kw):
        """結構化契約：AI 回覆先過 check（回傳錯誤清單），不符就帶著錯誤再問一次。

        回傳 (data, errors)：errors 非空＝重問一次仍不符，呼叫端決定是丟掉不符的部分還是交人。
        ★ 只重問一次：AI 連兩次不照規則，多問幾次通常也一樣，只會燒預算。"""
        data = self.ask(purpose, prompt, **kw)
        errors = check(data) or []
        if not errors:
            return data, []
        _logger.info('[knowledge] %s 回覆不符規定，重問一次：%s', purpose, errors[:5])
        retry = prompt + '\n\n你上一次的回覆不符規定，請修正後重新回覆完整 JSON：\n- ' + \
            '\n- '.join(str(e) for e in errors[:20])
        data = self.ask(purpose, retry, **kw)
        return data, check(data) or []

    @api.model
    def _quota_vals(self):
        """這次呼叫 Hub 回報的今日剩餘額度，記在呼叫紀錄上（取走即清，不沿用到下一次）。

        ★ 不存系統參數：ir.config_parameter 每寫一次就清空所有 worker 的快取，
          一次更新幾百次 AI 呼叫會拖慢整個主控台。"""
        q = dict(hub_client.LAST_QUOTA)
        hub_client.LAST_QUOTA.clear()
        if q.get('cost_left') is None:
            return {}
        return {'hub_cost_known': True, 'hub_cost_left': float(q['cost_left'])}

    @api.model
    def hub_cost_left(self):
        """AI Hub 來源今日還剩多少錢（USD）；不知道（今天還沒呼叫過、或 Hub 不限）回 None。"""
        from datetime import datetime, timedelta
        start = datetime.combine(fields.Date.from_string(self._today()),
                                 datetime.min.time()) - timedelta(hours=8)
        call = self.env['corpaas.knowledge.ai.call'].sudo().search(
            [('hub_cost_known', '=', True), ('create_date', '>=', start)],
            order='id desc', limit=1)
        return call.hub_cost_left if call else None

    @api.model
    def unit_cost(self, purpose, days=60):
        """一次呼叫約多少錢：近 days 天實際呼叫（不含快取）的平均，沒紀錄用預設值。"""
        since = fields.Datetime.subtract(fields.Datetime.now(), days=days)
        rows = self.env['corpaas.knowledge.ai.call'].sudo().read_group(
            [('purpose', '=', purpose), ('ok', '=', True), ('cached', '=', False),
             ('create_date', '>=', since)], ['cost_usd:avg'], [])
        avg = rows and rows[0].get('cost_usd')
        return round(float(avg), 4) if avg else DEFAULT_UNIT_COST.get(purpose, 0.1)

    @api.model
    def _cache_get(self, purpose, phash):
        days = int(self.env['ir.config_parameter'].sudo().get_param(
            'corpaas_knowledge.ai_cache_days') or 30)
        if days <= 0:
            return None
        since = fields.Datetime.subtract(fields.Datetime.now(), days=days)
        call = self.env['corpaas.knowledge.ai.call'].sudo().search([
            ('purpose', '=', purpose), ('prompt_hash', '=', phash), ('ok', '=', True),
            ('cached', '=', False), ('response_text', '!=', False),
            ('create_date', '>=', since)], order='id desc', limit=1)
        return call.response_text if call else None

    @api.model
    def _log_call(self, vals):
        """記帳用獨立游標立即 commit：錢已經花了，後面整個作業失敗回滾也不能讓帳消失。"""
        if not txn.in_tests(self.env):
            with self.env.registry.cursor() as cr:
                # ★ 方案本身還沒 commit（同一交易剛建立）時，獨立游標看不到它，
                #   直接 INSERT 會撞外鍵——先確認看得到，看不到就記在目前交易。
                pid = vals.get('package_id')
                visible = True
                if pid:
                    cr.execute('SELECT 1 FROM infrastructure_solution_package WHERE id = %s',
                               (pid,))
                    visible = bool(cr.fetchone())
                if visible:
                    self.env(cr=cr)['corpaas.knowledge.ai.call'].sudo().create(vals)
                    return
        self.env['corpaas.knowledge.ai.call'].sudo().create(vals)

    @api.model
    def enqueue(self, record, method_name, package, note=''):
        """按鈕觸發的 AI 工作一律走佇列。

        ☠️ 不能在 HTTP 請求裡同步等 AI：一次呼叫最多等 15 分鐘，而 worker 的
          limit_time_real 預設 120 秒——請求被殺、交易回滾、帳也跟著消失。
        """
        record.ensure_one()
        if not package:
            raise UserError(_('找不到對應的方案，無法排入 AI 工作。'))
        job = self.env['corpaas.knowledge.ai.job'].sudo().create({
            'res_model': record._name, 'res_id': record.id, 'method': method_name,
            'package_id': package.id, 'user_id': self.env.uid, 'note': note})
        q = self.env['corpaas.queue'].sudo()._enqueue(
            package, 'knowledge_ai_job', {'job_id': job.id})
        q.channel = 'knowledge'
        job.queue_id = q.id
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {'type': 'info', 'sticky': False,
                       'title': _('已排入 AI 工作'),
                       'message': _('%s：完成後結果會出現在紀錄裡。') % (note or method_name)},
        }


class KnowledgeAiJob(models.Model):
    _name = 'corpaas.knowledge.ai.job'
    _description = '按鈕觸發的 AI 工作'
    _order = 'id desc'

    res_model = fields.Char(required=True)
    res_id = fields.Integer(required=True)
    method = fields.Char(required=True)
    package_id = fields.Many2one('infrastructure.solution.package', ondelete='cascade')
    user_id = fields.Many2one('res.users')
    queue_id = fields.Many2one('corpaas.queue', ondelete='set null')
    note = fields.Char()
    state = fields.Selection([('pending', '排隊中'), ('done', '完成'), ('failed', '失敗')],
                             default='pending', index=True)
    error = fields.Text()

    _ALLOWED_PREFIX = '_'

    def _run(self):
        self.ensure_one()
        if not (self.method.startswith(self._ALLOWED_PREFIX) and self.method.endswith('_run')):
            raise UserError(_('不允許的 AI 工作方法：%s') % self.method)
        user = self.user_id or self.env.user
        record = self.env[self.res_model].with_user(user).browse(self.res_id).exists()
        if not record:
            self.write({'state': 'failed', 'error': _('記錄已不存在')})
            return
        method = getattr(record, self.method)
        try:
            if getattr(method, 'knowledge_commits', False):
                # ★ 長時間、逐筆提交的工作（例如重寫待審說明）：不包 savepoint——中途 commit 會讓
                #   savepoint 失效；失敗時已提交的部分保留，只有當下那一筆作廢
                method()
            else:
                with self.env.cr.savepoint():
                    method()
            self.state = 'done'
            self._post(record, _('AI 工作完成：%s') % (self.note or self.method))
        except Exception as e:  # noqa: BLE001 - 失敗記在工作上，不讓佇列重試燒預算
            _logger.warning('[knowledge] AI 工作 %s 失敗：%s', self.id, e)
            self.write({'state': 'failed', 'error': str(e)[:4000]})
            self._post(record, _('AI 工作失敗：%s') % e)

    @staticmethod
    def _post(record, body):
        if hasattr(record, 'message_post'):
            try:
                record.sudo().message_post(body=body)
            except Exception:  # noqa: BLE001
                pass
