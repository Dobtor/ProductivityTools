# -*- coding: utf-8 -*-
"""週次排程：週次選擇器的 domain / 統計、排入週次的動作、週相關排程任務。

篩選與統計一律走 _week_date_domain 的日期區間，**不讀** stored 的
schedule_week_number —— 那個欄位相對「今天」計算會腐化。stored 欄位只保留給
searchpanel 計數與 By Week 分組（Odoo 18 兩者都要求 stored），由 cron 增量刷新。
"""

import logging
from collections import defaultdict
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.osv import expression

_logger = logging.getLogger(__name__)


class MailActivityWeek(models.Model):
    """週次排程（自 mail_activity.py 拆出，同一個 mail.activity 模型）。"""
    _inherit = 'mail.activity'

    @api.model
    def _cron_weekly_transition(self):
        """每週一凌晨執行的排程任務"""
        today = fields.Date.today()
        if today.weekday() != 0:  # 只在週一執行
            return

        # 找出下週預排的待辦（已有 scheduled_date 但無 planned_date）
        activities = self.search([
            ('scheduled_date', '!=', False),
            ('planned_date', '=', False),
            ('active', '=', True),
        ])

        # 依星期幾分組，批次 write
        weekday_map = {
            0: 'monday', 1: 'tuesday', 2: 'wednesday',
            3: 'thursday', 4: 'friday', 5: 'saturday', 6: 'sunday'
        }
        groups = defaultdict(lambda: self.env['mail.activity'])
        for activity in activities:
            weekday = activity.scheduled_date.weekday()
            groups[weekday] |= activity

        ctx = {'skip_schedule_check': True}
        for weekday, group_activities in groups.items():
            # 同星期的待辦 planned_date 各不同，需逐日處理
            date_groups = defaultdict(lambda: self.env['mail.activity'])
            for act in group_activities:
                date_groups[act.scheduled_date] |= act

            for scheduled_date, acts in date_groups.items():
                acts.with_context(**ctx).write({
                    'planned_date': scheduled_date,
                    'schedule_status': weekday_map.get(weekday, 'waiting'),
                    'scheduled_date': False,
                })

        _logger.info('Weekly transition completed. Processed %d activities.', len(activities))

    @api.model
    def _cron_refresh_schedule_week(self, batch_limit=20000):
        """每日重算 schedule_week / schedule_week_number（修正 stored compute 腐化）。

        這兩個欄位為 stored compute，計算依賴「今天」所在週次，ORM 只在
        planned_date / scheduled_date 變更時才重算 → 時間流逝會讓 stored 值腐化。

        **本 cron 已降級為「只影響顯示」**：週次篩選與計數改走 _week_date_domain
        的日期區間，不再讀這兩個欄位，所以 cron 失效不會造成錯誤的篩選結果，
        只會讓 By Week 分組標籤與 searchpanel 計數落後（那兩處 Odoo 18 要求 stored）。

        增量化：只挑「stored 值與應有值不符」的列，而非全表。
          - 無日期的列固定 -999，永遠不會變 → 直接排除（通常佔大宗）。
          - -1..3 各以日期區間比對 stored 值抓出不符者。
          - >3（遠期）的 stored 值每過一週就少 1，一律重算；數量通常很少。
        """
        Activity = self.with_context(active_test=False)
        stale = Activity.browse()

        for week_number in (-1, 0, 1, 2, 3):
            stale |= Activity.search(
                expression.AND([
                    self._week_date_domain(week_number),
                    [('schedule_week_number', '!=', week_number)],
                ]),
                limit=batch_limit,
            )

        # 遠期：stored 值是實際偏移量，每週遞減，無法用單一區間比對 → 全數重算
        stale |= Activity.search(
            [('schedule_week_number', '>', 3)], limit=batch_limit)

        if not stale:
            _logger.debug('Cron: schedule_week already up to date, nothing to refresh.')
            return

        # 強制標記 stored computed 欄位需重算（依賴 today，ORM 不會自動觸發）
        for field_name in ('schedule_week', 'schedule_week_number'):
            self.env.add_to_compute(self._fields[field_name], stale)
        stale.flush_recordset(['schedule_week', 'schedule_week_number'])

        _logger.info('Cron: refreshed schedule_week for %d stale activities.', len(stale))

    # 入口（兩處，行為一致）：
    #   - 清單／看板：views/mail_activity_schedule_views.xml 的三個
    #     ir.actions.server（binding_view_types="list,kanban"）→ ⚙️ 動作選單，
    #     多選時自動成為批次操作（本方法以 for 迴圈實作，本就支援多筆）。
    #   - 表單：static/src/views/activity_form/activity_form_controller.js
    #     自行 push 進 actionMenuItems（該表單覆寫了選單、binding 進不來）。
    def action_schedule_to_week(self, week_number):
        """將待辦排程至指定週次（保持原星期幾，移動到目標週）。

        Args:
            week_number: 相對週次偏移（-1=上週, 0=本週, 1=下週；正數為未來週，
                走 scheduled_date 預排）。
        Returns:
            重新載入視圖的 action
        """
        today = fields.Date.today()
        current_week_start = today - timedelta(days=today.weekday())
        target_week_start = current_week_start + timedelta(days=7 * week_number)

        weekday_map = {
            0: 'monday', 1: 'tuesday', 2: 'wednesday',
            3: 'thursday', 4: 'friday', 5: 'saturday', 6: 'sunday',
        }

        for activity in self:
            # 保持原有的星期幾，或預設為週一
            if activity.planned_date:
                original_weekday = activity.planned_date.weekday()
            elif activity.scheduled_date:
                original_weekday = activity.scheduled_date.weekday()
            else:
                original_weekday = 0  # 預設週一

            target_date = target_week_start + timedelta(days=original_weekday)

            # 根據週次設定不同欄位
            if week_number <= 0:
                # 上週或本週：設定 planned_date + schedule_status
                activity.with_context(skip_schedule_check=True).write({
                    'planned_date': target_date,
                    'schedule_status': weekday_map.get(original_weekday, 'monday'),
                    'scheduled_date': False,
                })
            else:
                # 未來週次：設定 scheduled_date
                activity.with_context(skip_schedule_check=True).write({
                    'scheduled_date': target_date,
                    'planned_date': False,
                })

        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

    def action_schedule_to_week_prev(self):
        """排程至上週"""
        return self.action_schedule_to_week(-1)

    def action_schedule_to_week0(self):
        """排程至本週"""
        return self.action_schedule_to_week(0)

    def action_schedule_to_week1(self):
        """排程至下週"""
        return self.action_schedule_to_week(1)

    @api.model
    def _week_date_domain(self, week_number):
        """「排程於第 N 週」的日期區間 domain。

        必須與 _compute_schedule_week 等價：
          - 判斷依據是 ``planned_date or scheduled_date``（COALESCE），故拆兩支。
          - week_number <= -1 代表「本週之前的全部」—— compute 端把更早的週次
            一律夾鉗成 -1，這裡對應成「只有上界、沒有下界」。
        """
        today = fields.Date.today()
        current_week_start = today - timedelta(days=today.weekday())
        week_start = current_week_start + timedelta(days=7 * week_number)
        week_end = week_start + timedelta(days=6)

        def _range(fname):
            cond = [(fname, '<=', fields.Date.to_string(week_end))]
            if week_number > -1:
                cond.append((fname, '>=', fields.Date.to_string(week_start)))
            return cond

        by_planned = expression.AND([
            [('planned_date', '!=', False)],
            _range('planned_date'),
        ])
        by_scheduled = expression.AND([
            [('planned_date', '=', False), ('scheduled_date', '!=', False)],
            _range('scheduled_date'),
        ])
        return expression.OR([by_planned, by_scheduled])

    @api.model
    def _week_descriptors(self):
        """週次選單的靜態描述：邊界、每日日期、篩選 domain（不含統計）。

        與 get_week_info 共用，確保「選單上的 domain」與「計數用的 domain」同源。
        """
        today = fields.Date.today()
        current_week_start = today - timedelta(days=today.weekday())
        weekday_keys = ['monday', 'tuesday', 'wednesday', 'thursday',
                        'friday', 'saturday', 'sunday']
        selection_labels = dict(
            self._fields['schedule_week']._description_selection(self.env))
        configs = [
            (-1, selection_labels.get('week_prev', 'Previous Week'), 'week_prev'),
            (0, selection_labels.get('week0', 'This Week'), 'week0'),
            (1, selection_labels.get('week1', 'Next Week'), 'week1'),
        ]

        descriptors = []
        for week_number, week_name, week_key in configs:
            week_start = current_week_start + timedelta(days=7 * week_number)
            week_end = week_start + timedelta(days=6)
            descriptors.append({
                'number': week_number,
                'name': week_name,
                'key': week_key,
                'start_date': fields.Date.to_string(week_start),
                'end_date': fields.Date.to_string(week_end),
                'dates': {
                    day_key: fields.Date.to_string(week_start + timedelta(days=i))
                    for i, day_key in enumerate(weekday_keys)
                },
                # 選擇器實際套用的條件：待排程（waiting）在每一週都看得到
                'domain': expression.OR([
                    [('schedule_status', '=', 'waiting')],
                    self._week_date_domain(week_number),
                ]),
            })

        all_name = _('All')
        descriptors.append({
            'number': 'all',
            'name': all_name,
            'key': 'all',
            'start_date': False,
            'end_date': False,
            'dates': {},
            'domain': [],
        })
        return descriptors

    @api.model
    def get_week_bounds(self):
        """供前端 SearchModel 在 load() 之前取得週次邊界與 domain。

        刻意不吃 domain 參數 —— 它必須能在 SearchModel 尚未載入 globalDomain 時
        呼叫（第一次計算 searchDomain 就要帶對週次條件）。統計另由 get_week_info 提供。
        """
        return self._week_descriptors()

    @api.model
    def get_week_info(self, domain=None):
        """取得週次選單資訊（供前端使用）：上週、本週、下週、全部。

        以單次 read_group 統計上/本/下週的數量與工時，另對「全部」做一次無
        週次過濾的彙總（含 waiting / 遠期 / 無日期）。

        :param domain: 呼叫端目前的檢視條件（action domain + facet + searchpanel，
            但**不含**週次本身）。由 ActivityWeekSearchModel._loadWeekInfo 傳入，
            確保選單上的數字與清單實際內容一致。舊版寫死
            ``user_id = env.uid`` / ``active = True``，導致「未指派」「全部待辦」
            兩張清單的週次計數與畫面無關。

        注意：每週的 count/total_hours 刻意排除 ``schedule_status = 'waiting'``
        ——它是「已排進該週的工作量」（供週工時規劃用），與週次篩選 domain
        （waiting 卡在每一週都看得到）語意不同，維持原行為。
        """
        base_domain = list(domain or [])
        descriptors = self._week_descriptors()

        weeks = []
        for descriptor in descriptors:
            week_number = descriptor['number']
            if week_number == 'all':
                # 「全部」：無週次過濾的整體彙總（含 waiting / 遠期 / 無日期）
                count_domain = base_domain
            else:
                # 與選擇器同源的日期區間，再排除 waiting（見上方 docstring）
                count_domain = expression.AND([
                    base_domain,
                    self._week_date_domain(week_number),
                    [('schedule_status', '!=', 'waiting')],
                ])
            groups = self._read_group(count_domain, aggregates=['__count', 'estimated_hours:sum'])
            count, total_hours = groups[0] if groups else (0, 0)

            week = dict(descriptor, count=count, total_hours=total_hours or 0)
            if week_number == 'all':
                week['display_name'] = '%s[%d]' % (descriptor['name'], count)
            else:
                week['display_name'] = '%s[%d]%s-%s' % (
                    descriptor['name'], count,
                    descriptor['start_date'].replace('-', '/'),
                    descriptor['end_date'].replace('-', '/'),
                )
            weeks.append(week)

        return weeks
