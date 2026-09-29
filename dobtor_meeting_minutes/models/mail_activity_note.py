# -*- coding: utf-8 -*-
"""待辦 ↔ 筆記整合（自 dobtor_mail_activity 搬入）。

- note_id  來源參考：待辦「從哪張筆記長出來」
- note_ids 引用筆記：合併時把被併入者的筆記併進主待辦（不變式：note_id ∈ note_ids）
- 合併時改寫筆記裡指向被併入者的膠囊
- 編輯器內嵌清單 bind='note'：除了 res 指向本筆記，也列出引用本筆記的待辦
- chatter「相關筆記」側欄的資料 API（get_related_notes）
"""

import json
import logging
from collections import defaultdict

from lxml import etree
from lxml import html as lxml_html

from odoo import api, fields, models, Command, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class MailActivity(models.Model):
    _inherit = 'mail.activity'

    # ===== 來源參考（需求四：note_id 顯示為「來源參考 / Source Reference」）=====
    # note_id  = 這張待辦「從哪張筆記長出來」—— 語意單一，轉移精靈記的就是它。
    # note_ids = 「有哪些筆記引用這張待辦」—— 合併時把被併入者的筆記併進主待辦，
    #            所以必須是多筆。不變式：note_id 若有值，必定是 note_ids 的成員
    #            （由 create/write 維護，見 _link_source_note）。
    note_id = fields.Many2one(
        'note.note',
        string='Source Reference',
        index=True,
        ondelete='set null',
        help='Source note this activity originated from',
    )
    note_ids = fields.Many2many(
        'note.note',
        'mail_activity_note_rel', 'activity_id', 'note_id',
        string='Referenced Notes',
        help='All notes referencing this activity (always includes the source '
             'reference). Merging an activity moves its notes here.',
    )

    # 視圖條件用：py.js 沒有 len() builtin，不能在 invisible 裡寫 len(note_ids)
    # （伺服端 ast.parse 會過，瀏覽器才炸）
    note_count = fields.Integer(
        string='Referenced Note Count',
        compute='_compute_note_count',
    )

    @api.depends('note_ids')
    def _compute_note_count(self):
        for activity in self:
            activity.note_count = len(activity.note_ids)

    @api.constrains('note_id', 'note_ids')
    def _check_note_id_in_note_ids(self):
        """守住「來源筆記必為引用集合成員」的不變式。

        create/write 會自動維護，但 API 匯入、批次 UPDATE 或未來新增的寫入路徑
        可能繞過。不變式一破，note.note 端只看 note_ids 的計數與清單就會漏掉
        那筆待辦（筆記上明明有來源關聯，統計卻是 0）。
        """
        for activity in self:
            if activity.note_id and activity.note_id not in activity.note_ids:
                raise ValidationError(_(
                    'The source reference note must also be one of the referenced '
                    'notes. Activity "%(summary)s" points at note "%(note)s" which '
                    'is missing from its referenced notes.',
                    summary=activity.summary or activity.activity_type_id.name or activity.id,
                    note=activity.note_id.display_name,
                ))

    # ===== 不變式：來源筆記（note_id）必定也在引用集合（note_ids）內 =====
    # 讓筆記端的計數/清單只需要看 note_ids 一個欄位。

    @api.model
    def _link_source_note(self, vals):
        if vals.get('note_id'):
            vals = dict(vals)
            vals['note_ids'] = list(vals.get('note_ids') or []) + [Command.link(vals['note_id'])]
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        # note_id 未明寫時，ORM 會取 context 的 default_note_id —— 也要併入 note_ids，
        # 否則不變式約束會擋下（例：建立精靈帶 default_note_id、使用者清空關聯筆記）。
        default_note = self.env.context.get('default_note_id')
        vals_list = [
            dict(vals, note_id=default_note) if default_note and 'note_id' not in vals else vals
            for vals in vals_list
        ]
        return super().create([self._link_source_note(vals) for vals in vals_list])

    def write(self, vals):
        return super().write(self._link_source_note(vals))

    def _guarded_related_fields(self):
        return super()._guarded_related_fields() | {'note_id', 'note_ids'}

    def _continue_todo_action(self):
        action = super()._continue_todo_action()
        if self.note_id:
            action['context']['default_note_id'] = self.note_id.id
        elif self.note_ids:
            action['context']['default_note_id'] = self.note_ids[0].id
        return action

    # ===== 合併 =====

    def _merge_field_values(self, master):
        """筆記引用取聯集。"""
        vals = super()._merge_field_values(master)
        note_ids = set(master.note_ids.ids)
        for activity in self:
            note_ids |= set(activity.note_ids.ids)
            if activity.note_id:
                note_ids.add(activity.note_id.id)
        if note_ids != set(master.note_ids.ids):
            vals['note_ids'] = [Command.set(sorted(note_ids))]
        return vals

    def _merge_extra(self, master):
        """筆記內的膠囊就地改寫成主待辦（僅處理引用到的筆記；
        其餘位置由 get_chip_data 的讀取時轉向兜底）。"""
        res = super()._merge_extra(master)
        self._rewrite_note_chips(self.ids, master.id,
                                 self.mapped('note_ids') | self.mapped('note_id'))
        return res

    def _rewrite_note_chips(self, old_ids, new_id, notes):
        """把 note.memo 內指向 old_ids 的膠囊，就地改寫成 new_id。

        僅為資料整潔（讓 HTML 與實際狀態一致）；正確性不依賴它 ——
        沒改到的膠囊由 get_chip_data 在讀取時轉向。
        以 lxml 解析 data-embedded-props 的 JSON，不用正則碰 HTML。
        """
        if not notes or not old_ids:
            return
        old_ids = set(old_ids)
        for note in notes:
            if not note.memo:
                continue
            try:
                tree = lxml_html.fragment_fromstring(note.memo, create_parent='div')
            except (etree.ParserError, ValueError):
                _logger.warning('Cannot parse note %s memo, chips left untouched.', note.id)
                continue
            changed = False
            for el in tree.xpath('//*[@data-embedded="activityChip"]'):
                try:
                    props = json.loads(el.get('data-embedded-props') or '{}')
                except ValueError:
                    continue
                if props.get('activityId') in old_ids:
                    props['activityId'] = new_id
                    el.set('data-embedded-props', json.dumps(props))
                    changed = True
            if changed:
                inner = ''.join(
                    [tree.text or ''] +
                    [lxml_html.tostring(child, encoding='unicode') for child in tree]
                )
                note.sudo().write({'memo': inner})

    # ===== 富文字編輯器：bind='note' =====

    @api.model
    def _editor_activity_domain(self, bind, res_model=False, res_id=False, note_id=False):
        """note.note 編輯器：除了 res 指向本筆記，也以 note_ids 引用顯示
        （即使活動 res 指向其他文件，只要引用了本筆記也納入）。
        note_ids 已涵蓋 note_id（見不變式）。"""
        if bind == 'note' and note_id:
            note_id = int(note_id)
            return [
                '|',
                '&', ('res_model', '=', 'note.note'), ('res_id', '=', note_id),
                ('note_ids', 'in', note_id),
            ]
        return super()._editor_activity_domain(bind, res_model, res_id, note_id)

    # ===== chatter「相關筆記」 =====

    @api.model
    def get_related_notes(self, res_model, res_id):
        """取得指定文件的待辦所關聯的 Notes

        注意：一張待辦可引用多張筆記（note_ids），因此同一張待辦會同時出現在
        多個筆記分組底下 —— 各分組 total_count 的**加總會大於實際待辦數**，
        呼叫端（related_notes.js）不應把它們相加當作總數。
        """
        activities = self.with_context(active_test=False).search([
            ('res_model', '=', res_model),
            ('res_id', '=', res_id),
            ('note_ids', '!=', False),
        ])

        notes_activities = defaultdict(list)
        for activity in activities:
            if activity.merged_into_id:
                activity_state = 'merged'
            elif activity.active:
                activity_state = 'active'
            elif activity.done_date:
                activity_state = 'done'
            elif activity.cancel_date:
                activity_state = 'cancelled'
            else:
                activity_state = 'archived'

            for note in activity.note_ids:
                notes_activities[note.id].append({
                    'id': activity.id,
                    'summary': activity.summary or '',
                    'state': activity_state,
                    'note': note,
                })

        notes_data = []
        for note_id, activity_list in notes_activities.items():
            note = activity_list[0]['note']
            note_name = note.name
            if not note_name and note.memo:
                note_name = self._html_to_text(note.memo, max_length=50)

            active_count = sum(1 for a in activity_list if a['state'] == 'active')
            done_count = sum(1 for a in activity_list if a['state'] in ('done', 'cancelled'))
            # 已合併者仍列出（顯示但標示），但它與主待辦是同一件事 —— 單獨算出來，
            # 讓前端能說明分母為何比實際件數大。
            merged_count = sum(1 for a in activity_list if a['state'] == 'merged')
            total_count = len(activity_list)

            activities_info = [{
                'id': a['id'],
                'summary': a['summary'],
                'state': a['state'],
            } for a in activity_list]

            notes_data.append({
                'id': note_id,
                'name': note_name or _('Unnamed Note'),
                'activities': activities_info,
                'total_count': total_count,
                'active_count': active_count,
                'done_count': done_count,
                'merged_count': merged_count,
                # 只有「已合併空殼」的筆記不算全部完成（實際內容在別處的主待辦上）
                'is_all_done': active_count == 0 and (total_count - merged_count) > 0,
            })

        return notes_data
