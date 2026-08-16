# -*- coding: utf-8 -*-
"""待辦合併：把多筆重複待辦收攏到一筆「主待辦」。

被併入者不刪除，改為 active=False + merged_into_id 指標，讓膠囊可在讀取時
轉向（見 mail_activity_editor.py 的 get_chip_data）並支援解除合併。
"""

import json
import logging

from lxml import etree
from lxml import html as lxml_html
from markupsafe import Markup

from odoo import api, models, Command, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class MailActivityMerge(models.Model):
    """待辦合併（自 mail_activity.py 拆出，同一個 mail.activity 模型）。"""
    _inherit = 'mail.activity'

    # merged_into_id 鏈的最大追蹤深度（防資料異常造成的環或長鏈）
    _MERGE_CHAIN_LIMIT = 20

    def _resolve_merge_target(self):
        """沿 merged_into_id 走到最終主待辦；未合併則回傳自己。

        以 visited 集合擋環（資料異常時），達上限則停在當下那一筆。
        """
        self.ensure_one()
        activity = self
        visited = {activity.id}
        for _i in range(self._MERGE_CHAIN_LIMIT):
            nxt = activity.merged_into_id
            if not nxt or not nxt.exists() or nxt.id in visited:
                break
            visited.add(nxt.id)
            activity = nxt
        return activity

    def _check_merge_access(self):
        """合併／解除合併的權限門檻。

        與 action_cancel 一致：對每一筆被併入者，必須是建立者或被指派者
        （系統管理員與 su 豁免）。合併等同讓別人的待辦消失，門檻不能比取消低。
        """
        if self.env.su or self.env.user.has_group('base.group_system'):
            return
        uid = self.env.uid
        for activity in self:
            is_creator = activity.create_uid.id == uid
            is_assignee = bool(activity.user_id) and activity.user_id.id == uid
            if not (is_creator or is_assignee):
                raise UserError(_(
                    'You can only merge activities you created or are assigned to. '
                    '"%(summary)s" belongs to %(owner)s.',
                    summary=activity.summary or activity.activity_type_id.name,
                    owner=(activity.user_id or activity.create_uid).name,
                ))

    def _merge_field_values(self, master):
        """依合併規則算出要寫回主待辦的值。

        規則（已定案）：
          - estimated_hours：取主待辦（不加總）→ 不在此回傳
          - date_deadline / urgency / importance：取最嚴重
          - note_ids：union
          - note / feedback：附加，不覆蓋
          - actual_hours：不直接寫（stored compute），改搬 timesheet_ids
        """
        urgency_rank = {'urgent': 0, 'standard': 1, 'flexible': 2}
        importance_rank = {'important': 0, 'normal': 1}
        vals = {}

        # 最早的截止日
        deadlines = [a.date_deadline for a in self | master if a.date_deadline]
        if deadlines and min(deadlines) != master.date_deadline:
            vals['date_deadline'] = min(deadlines)

        # 最嚴重的緊急程度／重要性（rank 越小越嚴重）
        worst_urgency = min(
            (a.urgency for a in self | master if a.urgency),
            key=lambda u: urgency_rank.get(u, 99), default=False)
        if worst_urgency and worst_urgency != master.urgency:
            vals['urgency'] = worst_urgency
        worst_importance = min(
            (a.importance for a in self | master if a.importance),
            key=lambda i: importance_rank.get(i, 99), default=False)
        if worst_importance and worst_importance != master.importance:
            vals['importance'] = worst_importance

        # 筆記引用聯集
        note_ids = set(master.note_ids.ids)
        for activity in self:
            note_ids |= set(activity.note_ids.ids)
            if activity.note_id:
                note_ids.add(activity.note_id.id)
        if note_ids != set(master.note_ids.ids):
            vals['note_ids'] = [Command.set(sorted(note_ids))]

        # 待辦註記（HTML）／完成回饋（Text）：附加而非覆蓋
        note_parts = [p for p in (
            Markup(activity.note) for activity in self if activity.note) if p]
        if note_parts:
            header = Markup('<p><br/></p><hr/><p><em>%s</em></p>') % _('Merged from:')
            vals['note'] = (Markup(master.note or '')) + header + Markup('').join(note_parts)
        feedback_parts = [a.feedback for a in self if a.feedback]
        if feedback_parts:
            vals['feedback'] = '\n\n'.join(
                p for p in ([master.feedback] + feedback_parts) if p)

        return vals

    def action_merge(self, master):
        """把 self（被併入者）併進 master。self 不得包含 master。"""
        master.ensure_one()
        sources = self - master
        if not sources:
            raise UserError(_('Select at least one other activity to merge into the master.'))
        if not master.active or master.merged_into_id:
            raise UserError(_('The master activity must be an in-progress activity.'))
        blocked = sources.filtered(lambda a: not a.active)
        if blocked:
            raise UserError(_(
                'Only in-progress activities can be merged. Already done, cancelled '
                'or merged: %(summaries)s',
                summaries=', '.join(
                    b.summary or b.activity_type_id.name or str(b.id) for b in blocked),
            ))
        sources._check_merge_access()

        merge_ctx = sources.with_context(activity_merge=True)
        master_ctx = master.with_context(activity_merge=True)

        # 1) 併值進主待辦
        vals = sources._merge_field_values(master)
        if vals:
            master_ctx.write(vals)

        # 2) 工時表記錄跟著走（actual_hours 是 stored compute，不能直接寫）
        timesheets = sources.mapped('timesheet_ids')
        if timesheets:
            timesheets.sudo().write({'activity_id': master.id})

        # 3) 筆記內的膠囊就地改寫成主待辦（僅處理引用到的筆記；
        #    其餘位置由 get_chip_data 的讀取時轉向兜底）
        self._rewrite_note_chips(sources.ids, master.id,
                                 sources.mapped('note_ids') | sources.mapped('note_id'))

        # 4) 封存來源並留下指標
        merge_ctx.write({'active': False, 'merged_into_id': master.id})

        # 5) 留痕：主待辦與各來源的 chatter，並通知原負責人
        master_link = Markup('<a href="#" data-oe-model="mail.activity" '
                             'data-oe-id="%d">%s</a>') % (
            master.id, master.summary or master.activity_type_id.name or master.id)
        for activity in sources:
            activity.message_post(body=Markup('%s %s') % (
                _('Merged into:'), master_link))
            if activity.user_id and activity.user_id != self.env.user:
                activity.user_id._bus_send('mail.activity/updated',
                                           {'activity_created': False})
        master.message_post(body=Markup('%s %s') % (
            _('Merged in:'),
            Markup(', ').join(
                Markup('%s') % (a.summary or a.activity_type_id.name or a.id)
                for a in sources)))
        return True

    def unlink(self):
        """刪除主待辦前，先把併入它的待辦解除合併。

        merged_into_id 是 ondelete='set null'，直接刪主待辦會讓空殼變成
        active=False 且 merged_into_id=False —— 狀態算成「進行中」卻躺在封存區，
        Unmerge 按鈕也因條件不成立而消失，等於卡死。先解除合併讓它們回到可用狀態。
        """
        merged = self.env['mail.activity'].with_context(active_test=False).search([
            ('merged_into_id', 'in', self.ids),
        ])
        # 排除「主待辦本身也在這次刪除範圍內」的情況：那些空殼一併留給下一輪判斷
        orphans = merged - self
        if orphans:
            orphans.sudo().with_context(activity_merge=True).write({
                'active': True,
                'merged_into_id': False,
            })
            for activity in orphans:
                activity.message_post(body=_(
                    'The master activity was deleted; this activity is active again.'))
        return super().unlink()

    def action_unmerge(self):
        """解除合併：清指標並復原為進行中。膠囊會自動指回原待辦。"""
        merged = self.filtered('merged_into_id')
        if not merged:
            raise UserError(_('These activities are not merged.'))
        merged._check_merge_access()
        merged.with_context(activity_merge=True).write({
            'active': True,
            'merged_into_id': False,
        })
        for activity in merged:
            activity.message_post(body=_('Unmerged; this activity is active again.'))
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    @api.model
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
