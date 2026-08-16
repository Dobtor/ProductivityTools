# -*- coding: utf-8 -*-
"""富文字編輯器整合：內嵌活動清單、inline 膠囊、工具列時鐘的後端 API。

膠囊在 HTML 裡只存 activityId，其餘一律即時抓 —— 所以合併後不需要改寫散落在
各 html 欄位裡的膠囊，由 get_chip_data 在讀取時解析 merged_into_id 轉向。
"""

from odoo import api, models


class MailActivityEditor(models.Model):
    """富文字編輯器整合（自 mail_activity.py 拆出，同一個 mail.activity 模型）。"""
    _inherit = 'mail.activity'

    @api.model
    def get_editor_default_note_id(self):
        """需求七：已移除「預設筆記本」設計 —— 不再有個人待辦筆記。

        富文字編輯器內嵌清單/時鐘在「無對應記錄」情境下不再退回預設筆記；
        呼叫端（activity_clock_toolbar.js）對 False 有優雅退化（顯示空）。
        """
        return False

    # 膠囊（activity_chip_embedding.js）在 HTML 裡只存 activityId，其餘即時抓。
    # 合併後不改寫那些 HTML（膠囊可能散落在任何啟用 embeddedComponents 的 html
    # 欄位裡，無法窮舉），改成**讀取時解析 merged_into_id 轉向**：涵蓋所有位置、
    # 對既有內容立即生效、且解除合併就自動復原。
    CHIP_FIELDS = [
        'summary', 'state', 'active', 'activity_status', 'user_id',
        'urgency', 'importance', 'date_deadline',
    ]

    @api.model
    def get_chip_data(self, activity_ids):
        """膠囊批次讀取：一次 RPC 取回多顆膠囊所需資料，並自動解析合併轉向。

        :param activity_ids: 膠囊 HTML 內記錄的原始 id 清單
        :return: {原始 id: {..CHIP_FIELDS.., 'id': 實際顯示的待辦 id,
                            'redirected_from': 原始 id 或 False}}
                 找不到的 id 不會出現在回傳中（呼叫端顯示為「已刪除」）。
        """
        ids = [int(i) for i in (activity_ids or []) if i]
        if not ids:
            return {}
        Activity = self.with_context(active_test=False)
        sources = Activity.browse(ids).exists()

        # 先解析每個來源的最終目標，再一次讀取所有目標，避免 N 次 read
        target_by_source = {act.id: act._resolve_merge_target() for act in sources}
        targets = Activity.browse({t.id for t in target_by_source.values()})
        data_by_target = {rec['id']: rec for rec in targets.read(self.CHIP_FIELDS)}

        result = {}
        for source_id, target in target_by_source.items():
            data = data_by_target.get(target.id)
            if not data:
                continue
            result[str(source_id)] = dict(
                data,
                redirected_from=source_id if target.id != source_id else False,
            )
        return result

    @api.model
    def _editor_activity_domain(self, bind, res_model=False, res_id=False, note_id=False):
        """編輯器內嵌清單/時鐘共用的綁定 domain。

        :param bind: 'note' 綁 note_id、'res' 綁 res_model/res_id、其他綁個人筆記
        """
        if bind == 'note' and note_id:
            note_id = int(note_id)
            # note.note 編輯器：除了 res 指向本筆記，也以 note_ids 引用顯示
            # （即使活動 res 指向其他文件，只要引用了本筆記也納入）。
            # note_ids 已涵蓋 note_id（見 create/write 的不變式）。
            return [
                '|',
                '&', ('res_model', '=', 'note.note'), ('res_id', '=', note_id),
                ('note_ids', 'in', note_id),
            ]
        if bind == 'res' and res_model and res_id:
            return [('res_model', '=', res_model), ('res_id', '=', int(res_id))]
        # 需求七：無預設筆記 —— 退回「目前使用者的獨立待辦（無關聯文件）」
        return [('user_id', '=', self.env.uid), ('res_model', '=', False)]

    @api.model
    def get_editor_activities(self, bind, res_model=False, res_id=False, note_id=False, limit=0):
        """供富文字編輯器內嵌清單即時抓取活動（含已封存的完成/取消以便顯示歷史）。

        :param limit: 0 表示不限；>0 時多取 1 筆以判斷是否還有更多
        :return: {'activities': list[dict], 'has_more': bool}
        """
        domain = self._editor_activity_domain(bind, res_model, res_id, note_id)
        fetch = (limit + 1) if limit else None
        activities = self.with_context(active_test=False).search(
            domain, order='active desc, date_deadline asc, id asc', limit=fetch)
        has_more = bool(limit) and len(activities) > limit
        if limit:
            activities = activities[:limit]
        result = []
        for act in activities:
            result.append({
                'id': act.id,
                'summary': act.summary or (act.activity_type_id.name or ''),
                'date_deadline': act.date_deadline and str(act.date_deadline) or False,
                'state': act.state or 'planned',
                'activity_status': act.activity_status,
                'active': act.active,
                'user_id': act.user_id.id,
                'user_name': act.user_id.name or '',
                # 即時「模型 / 記錄名」（取代 stored 快照 res_name，避免傳出 stale 值）
                'res_name': act.res_document_display or '',
                'activity_type_name': act.activity_type_id.name or '',
            })
        return {'activities': result, 'has_more': has_more}

    @api.model
    def get_editor_activity_summary(self, bind, res_model=False, res_id=False, note_id=False):
        """供工具列時鐘輕量查詢：只回進行中活動的 ids 與最嚴重狀態（不組完整 dict）。

        :return: {'ids': list[int], 'worst': 'overdue'|'today'|'planned'|'none'}
        """
        domain = self._editor_activity_domain(bind, res_model, res_id, note_id)
        domain = [('active', '=', True)] + domain
        activities = self.search(domain, order='date_deadline asc, id asc')
        states = set(activities.mapped('state'))
        if 'overdue' in states:
            worst = 'overdue'
        elif 'today' in states:
            worst = 'today'
        elif activities:
            worst = 'planned'
        else:
            worst = 'none'
        return {'ids': activities.ids, 'worst': worst}
