# -*- coding: utf-8 -*-
"""子心智圖的伺服器端操作：建立（延伸／拆出）、合併回上層、發想頁掛到主題、
跨分頁搬移主題。

共同原則（也是測試的重點）：
- **只動主題的 sheet_id / parent_id / sequence 與分頁本身**，絕不讀寫
  project.task —— 任務連結（topic.task_id）跟著主題走，專案端完全不受影響；
  任務階層要等下一次「同步到專案」才會依新的圖重算。
- 關聯線／外框／總結：整組都在搬移範圍內 → 跟著搬；跨越邊界 → 刪除並回報筆數
  （它們不能跨分頁）。標註、標記、備註、附件掛在主題上，自然跟著走。
- 子圖規則（同一本、非中心主題、不成環、最多三層）由 xmind.sheet 的約束兜底；
  這裡先做一次預檢，給看得懂的訊息。
"""
import logging

from odoo import models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class XMindWorkbookSubSheets(models.Model):
    _inherit = 'xmind.workbook'

    # ------------------------------------------------------------------
    # 共用
    # ------------------------------------------------------------------
    def _resolve_topic_keys(self, keys, sheet_id=None):
        """[(key, topic)]：key 可以是主題 id（int）或 component_id（str）。

        component_id 只在同一張分頁內保證唯一，所以有 sheet_id 時只在該分頁找。
        找不到（或不屬於這本工作簿）的 topic 為空 recordset。
        """
        self.ensure_one()
        Topic = self.env['xmind.topic']
        keys = list(keys or [])
        ids = [k for k in keys if isinstance(k, int)]
        cids = [k for k in keys if isinstance(k, str) and k]
        by_id = {t.id: t for t in Topic.browse(ids).exists()
                 if t.sheet_id.workbook_id == self}
        by_cid = {}
        if cids:
            domain = [('component_id', 'in', cids), ('sheet_id.workbook_id', '=', self.id)]
            if sheet_id:
                domain.append(('sheet_id', '=', int(sheet_id)))
            for t in Topic.search(domain, order='id'):
                by_cid.setdefault(t.component_id, t)
        result = []
        for k in keys:
            topic = by_id.get(k) if isinstance(k, int) else by_cid.get(k)
            result.append((k, topic or Topic))
        return result

    def _check_sheet_in_book(self, sheet_id):
        sheet = self.env['xmind.sheet'].browse(int(sheet_id or 0)).exists()
        if not sheet or sheet.workbook_id != self:
            raise UserError(_('Sheet %s does not belong to this mind map.', sheet_id))
        return sheet

    @staticmethod
    def _topic_label(topic):
        return topic.title or _('(untitled)')

    def _floating_cids(self, sheet):
        return set(sheet.floating_topic_ids.mapped('component_id'))

    def _anchor_refusal(self, topic, extra_height=0):
        """這顆主題不能當子圖錨點的原因；可以的話回 False。

        :param extra_height: 新子圖底下還會掛幾層子圖（拆出時，被搬走的子樹裡
            若有錨點，它們的子圖會跟著往下沉一層）。
        """
        sheet = topic.sheet_id
        if not topic.parent_id:
            return _('a central topic cannot be expanded into a sub sheet')
        if sheet.sheet_role not in ('main', 'sub'):
            return _('topics of an idea sheet cannot be expanded; attach the idea sheet first')
        if topic.is_summary_node:
            return _('a summary topic cannot be expanded')
        if topic.component_id and topic.component_id in self._floating_cids(sheet):
            return _('a floating topic cannot be expanded')
        max_depth = self.env['xmind.sheet']._MAX_SUB_DEPTH
        if sheet._sub_depth() + 1 + extra_height > max_depth:
            return _('sub sheets can be nested at most %s levels', max_depth)
        return False

    def _subtree_sub_height(self, topics):
        """子樹裡的錨點，它們的子圖（含更深層）最多有幾層。"""
        subs = self.env['xmind.sheet'].search([
            ('sheet_role', '=', 'sub'), ('anchor_topic_id', 'in', topics.ids)])
        return max([1 + s._sub_height() for s in subs] or [0])

    def _move_subtrees(self, tops, target_sheet, target_parent):
        """把 tops（各自連同子孫）搬到 target_sheet 的 target_parent 底下，排在既有
        子主題之後。回傳被刪掉的跨界特徵筆數 {'relationships', 'boundaries', 'summaries'}。

        只寫 xmind.* —— 任務連結跟著主題。
        """
        Topic = self.env['xmind.topic']
        dropped = {'relationships': 0, 'boundaries': 0, 'summaries': 0}
        if not tops:
            return dropped
        moved = Topic.search([('id', 'child_of', tops.ids)])
        moved_ids = set(moved.ids)
        source_sheets = moved.mapped('sheet_id')

        # 浮動主題：只有掛在目標分頁中心主題底下時才維持浮動，其他情況轉成一般主題
        floating = self.env['xmind.floating.topic'].search([
            ('sheet_id', 'in', source_sheets.ids),
            ('component_id', 'in', [c for c in moved.mapped('component_id') if c])])
        target_root = target_sheet._get_root_topic()
        keep_floating = floating.filtered(
            lambda f: target_parent == target_root
            and tops.filtered(lambda t: t.component_id == f.component_id))
        (floating - keep_floating).unlink()

        # 1) 主題
        last = max(target_parent.child_ids.filtered(
            lambda c: c.id not in moved_ids).mapped('sequence') or [-1])
        others = moved.filtered(lambda t: t.sheet_id != target_sheet)
        if others:
            others.write({'sheet_id': target_sheet.id})
        for offset, top in enumerate(tops.sorted(lambda t: (t.sequence, t.id))):
            top.write({'parent_id': target_parent.id, 'sequence': last + 1 + offset})
        if keep_floating:
            keep_floating.write({'sheet_id': target_sheet.id})

        # 2) 特徵層（主題已就位，約束檢查才會通過）
        Rel = self.env['xmind.relationship']
        for rel in Rel.search(['|', ('source_topic_id', 'in', moved.ids),
                               ('target_topic_id', 'in', moved.ids)]):
            inside = (rel.source_topic_id.id in moved_ids and rel.target_topic_id.id in moved_ids)
            if inside:
                if rel.sheet_id != target_sheet:
                    rel.sheet_id = target_sheet.id
            elif rel.source_topic_id.sheet_id == rel.target_topic_id.sheet_id == rel.sheet_id:
                continue   # 同一張分頁內搬移：關聯線仍然有效
            else:
                rel.unlink()
                dropped['relationships'] += 1
        for model, key in (('xmind.boundary', 'boundaries'), ('xmind.summary', 'summaries')):
            domain = [('topic_ids', 'in', moved.ids)]
            if model == 'xmind.summary':
                domain = ['|', ('topic_ids', 'in', moved.ids), ('summary_topic_id', 'in', moved.ids)]
            for rec in self.env[model].search(domain):
                members = rec.topic_ids | (rec.summary_topic_id if model == 'xmind.summary'
                                           else self.env['xmind.topic'])
                if all(m.id in moved_ids for m in members):
                    if rec.sheet_id != target_sheet:
                        rec.sheet_id = target_sheet.id
                else:
                    rec.unlink()
                    dropped[key] += 1
        return dropped

    def _sheet_payload(self, sheet):
        return {'id': sheet.id, 'name': sheet.name}

    # ------------------------------------------------------------------
    # 建立子心智圖
    # ------------------------------------------------------------------
    def action_create_sub_sheets(self, topic_ids, mode='extend', names=None, layout=None,
                                 sheet_id=None):
        """每顆選取的主題各建一張子心智圖。

        :param topic_ids: 主題 id 或 component_id 的清單
        :param mode: 'extend'（空白子圖，只有代理中心主題）或 'split'（把主題現有的
            子主題整棵搬進子圖）。沒有子主題的主題在 split 下等同 extend。
        :param names: {key: 分頁名稱} 或與 topic_ids 對齊的清單；預設為主題標題
        :param layout: 新分頁的版面（預設 logic_right）
        :param sheet_id: component_id 所在的分頁（同一個 component_id 可能出現在
            不同分頁，帶上它才不會找錯）
        :returns: {'created': [sheet ids], 'existing': [...], 'skipped': [...],
                   'dropped': {...}}
        """
        self.ensure_one()
        self.check_access('write')
        if mode not in ('extend', 'split'):
            raise UserError(_('Unknown mode: %s', mode))
        Sheet = self.env['xmind.sheet']
        Topic = self.env['xmind.topic']
        layout = layout or 'logic_right'
        if layout not in dict(Sheet._fields['layout_type'].selection):
            layout = 'logic_right'
        pairs = self._resolve_topic_keys(topic_ids, sheet_id=sheet_id)
        if isinstance(names, (list, tuple)):
            names = {str(k): n for (k, _topic), n in zip(pairs, names)}
        names = {str(k): v for k, v in (names or {}).items()}

        result = {'created': [], 'existing': [], 'skipped': [],
                  'dropped': {'relationships': 0, 'boundaries': 0, 'summaries': 0}}
        done = set()
        max_seq = max(self.sheet_ids.mapped('sequence') or [0])
        for key, topic in pairs:
            if not topic:
                result['skipped'].append({'key': key, 'title': str(key),
                                          'reason': _('topic not found (save the mind map first)')})
                continue
            if topic.id in done:
                continue
            done.add(topic.id)
            existing = topic.sub_sheet_id
            if existing:
                result['existing'].append({'key': key, 'topic_id': topic.id,
                                           'title': topic.title, 'sheet_id': existing.id,
                                           'sheet_name': existing.name})
                continue
            children = topic.child_ids
            split = mode == 'split' and bool(children)
            reason = self._anchor_refusal(
                topic, extra_height=self._subtree_sub_height(
                    Topic.search([('id', 'child_of', children.ids)])) if split else 0)
            if reason:
                result['skipped'].append({'key': key, 'title': topic.title, 'reason': reason})
                continue
            max_seq += 10
            name = (names.get(str(key)) or '').strip() or topic.title or _('Sub Sheet')
            parent_sheet = topic.sheet_id
            sub = Sheet.create({
                'workbook_id': self.id,
                'name': name,
                'sequence': max_seq,
                'sheet_role': 'sub',
                'anchor_topic_id': topic.id,
                'layout_type': layout,
                'theme': parent_sheet.theme or 'primary',
            })
            proxy = Topic.with_context(_syncing_name=True).create({
                'sheet_id': sub.id,
                'title': topic.title,
                'font_size': 18,
                'font_weight': 'bold',
            })
            if split:
                dropped = self._move_subtrees(children, sub, proxy)
                for k, v in dropped.items():
                    result['dropped'][k] += v
            result['created'].append(sub.id)
        if not result['created'] and not result['existing']:
            reasons = '\n'.join('• %s: %s' % (s['title'], s['reason']) for s in result['skipped'])
            raise UserError(_('No sub sheet could be created:\n%s', reasons))
        return result

    # ------------------------------------------------------------------
    # 合併回上層
    # ------------------------------------------------------------------
    def action_merge_sub_sheet(self, sheet_id):
        """子圖的主題搬回錨點底下（在上層分頁），然後刪掉這張子圖。

        代理中心主題本身不搬（它就是錨點）；指向它的關聯線改指錨點。
        子圖裡的浮動主題改掛上層分頁的中心主題、維持浮動。
        """
        self.ensure_one()
        self.check_access('write')
        sheet = self._check_sheet_in_book(sheet_id)
        if sheet.sheet_role != 'sub' or not sheet.anchor_topic_id:
            raise UserError(_('Only a sub sheet can be merged into its parent sheet.'))
        anchor = sheet.anchor_topic_id
        target = anchor.sheet_id
        Topic = self.env['xmind.topic']
        proxy = sheet._get_root_topic()
        if proxy and proxy.task_id:
            raise UserError(_(
                'The central topic of sub sheet "%s" is linked to a task; unlink it first.',
                sheet.name))
        dropped = {'relationships': 0, 'boundaries': 0, 'summaries': 0}
        floating_cids = self._floating_cids(sheet)
        tops = proxy.child_ids if proxy else Topic.search(
            [('sheet_id', '=', sheet.id), ('parent_id', '=', False)])
        float_tops = tops.filtered(lambda t: t.component_id in floating_cids)
        tree_tops = tops - float_tops
        # 其他沒有父主題的殘留（理論上不會有）一併當成一般主題搬
        strays = Topic.search([('sheet_id', '=', sheet.id), ('parent_id', '=', False),
                               ('id', '!=', proxy.id)]) if proxy else Topic
        tree_tops |= strays

        # 關聯線：指向代理中心主題的改指錨點（另一端也是代理／錨點就刪掉）
        rels = sheet.relationship_ids
        for rel in rels:
            src = anchor if rel.source_topic_id == proxy else rel.source_topic_id
            dst = anchor if rel.target_topic_id == proxy else rel.target_topic_id
            if src == dst:
                rel.unlink()
                dropped['relationships'] += 1
        # 外框／總結含代理中心主題：無法對應，刪掉
        for rec in sheet.boundary_ids.filtered(lambda b: proxy in b.topic_ids):
            rec.unlink()
            dropped['boundaries'] += 1
        for rec in sheet.summary_ids.filtered(
                lambda s: proxy in s.topic_ids or s.summary_topic_id == proxy):
            rec.unlink()
            dropped['summaries'] += 1

        moved = Topic.search([('id', 'child_of', (tops | strays).ids)]) if (tops or strays) else Topic
        if moved:
            moved.write({'sheet_id': target.id})
        last = max(anchor.child_ids.filtered(lambda c: c.sheet_id == target and c not in moved)
                   .mapped('sequence') or [-1])
        for offset, top in enumerate(tree_tops.sorted(lambda t: (t.sequence, t.id))):
            top.write({'parent_id': anchor.id, 'sequence': last + 1 + offset})
        target_root = target._get_root_topic()
        if float_tops and target_root:
            float_tops.write({'parent_id': target_root.id})
            sheet.floating_topic_ids.write({'sheet_id': target.id})
        else:
            sheet.floating_topic_ids.unlink()
        for rel in sheet.relationship_ids:
            vals = {'sheet_id': target.id}
            if rel.source_topic_id == proxy:
                vals['source_topic_id'] = anchor.id
            if rel.target_topic_id == proxy:
                vals['target_topic_id'] = anchor.id
            rel.write(vals)
        sheet.boundary_ids.write({'sheet_id': target.id})
        sheet.summary_ids.write({'sheet_id': target.id})
        name = sheet.name
        sheet.unlink()
        return {'merged': name, 'target_sheet_id': target.id,
                'anchor_component_id': anchor.component_id, 'dropped': dropped}

    # ------------------------------------------------------------------
    # 發想頁 → 掛到主題成為子圖
    # ------------------------------------------------------------------
    def action_attach_idea_sheet(self, sheet_id, anchor_topic_id):
        """發想頁掛到一顆主題底下，變成它的子心智圖。

        發想頁的中心主題保留（成為錨點的代理），它原本的標題捨棄、改顯示錨點標題；
        底下的主題原封不動。
        """
        self.ensure_one()
        self.check_access('write')
        sheet = self._check_sheet_in_book(sheet_id)
        if sheet.sheet_role != 'idea':
            raise UserError(_('Only an idea sheet can be attached to a topic.'))
        (_key, anchor), = self._resolve_topic_keys([anchor_topic_id])
        if not anchor:
            raise UserError(_('Topic not found in this mind map.'))
        if anchor.sheet_id == sheet:
            raise UserError(_('An idea sheet cannot be attached to one of its own topics.'))
        if anchor.sub_sheet_id:
            raise UserError(_('Topic "%(topic)s" already has the sub sheet "%(sheet)s".',
                              topic=anchor.title, sheet=anchor.sub_sheet_id.name))
        reason = self._anchor_refusal(anchor, extra_height=sheet._sub_height())
        if reason:
            raise UserError(_('Cannot attach to "%(topic)s": %(reason)s',
                              topic=self._topic_label(anchor), reason=reason))
        root = sheet._get_root_topic()
        if not root:
            root = self.env['xmind.topic'].create({'sheet_id': sheet.id, 'title': anchor.title})
        sheet.write({'sheet_role': 'sub', 'anchor_topic_id': anchor.id})
        if root.title != anchor.title:
            root.with_context(_syncing_name=True).write({'title': anchor.title})
        return {'sheet_id': sheet.id, 'anchor_component_id': anchor.component_id}

    # ------------------------------------------------------------------
    # 跨分頁搬移主題
    # ------------------------------------------------------------------
    def move_topics_to_sheet(self, topic_ids, target_sheet_id, target_parent_topic_id=None,
                             sheet_id=None):
        """把主題（連同子孫）搬到另一張分頁的某顆主題底下（預設：目標分頁的中心主題）。

        :returns: {'moved': n, 'target_sheet_id': id, 'dropped': {...}}
        """
        self.ensure_one()
        self.check_access('write')
        target_sheet = self._check_sheet_in_book(target_sheet_id)
        Topic = self.env['xmind.topic']
        if target_parent_topic_id:
            (_key, parent), = self._resolve_topic_keys(
                [target_parent_topic_id],
                sheet_id=target_sheet.id if isinstance(target_parent_topic_id, str) else None)
            if not parent or parent.sheet_id != target_sheet:
                raise UserError(_('The target topic is not on sheet "%s".', target_sheet.name))
        else:
            parent = target_sheet._get_root_topic()
            if not parent:
                raise UserError(_('Sheet "%s" has no central topic.', target_sheet.name))
        tops = Topic
        for key, topic in self._resolve_topic_keys(topic_ids, sheet_id=sheet_id):
            if not topic:
                raise UserError(_('Topic %s not found (save the mind map first).', key))
            if not topic.parent_id:
                raise UserError(_('The central topic "%s" cannot be moved.',
                                  self._topic_label(topic)))
            tops |= topic
        # 只搬最上層：選了父又選子，子會跟著父走
        tops = tops.filtered(lambda t: not (t.parent_id and Topic.search_count(
            [('id', 'in', tops.ids), ('id', '!=', t.id), ('id', 'parent_of', t.id)])))
        if not tops:
            return {'moved': 0, 'target_sheet_id': target_sheet.id, 'dropped': {}}
        subtree = Topic.search([('id', 'child_of', tops.ids)])
        if parent in subtree:
            raise UserError(_('A topic cannot be moved under itself.'))
        # 成環：要搬的子樹裡有錨點，目標分頁卻是那張子圖（或它更下層的子圖）
        current = target_sheet
        seen = set()
        while current and current.id not in seen:
            seen.add(current.id)
            if current.sheet_role == 'sub' and current.anchor_topic_id in subtree:
                raise UserError(_(
                    'Topic "%(topic)s" is expanded into sheet "%(sheet)s"; it cannot be moved '
                    'into that sheet.', topic=current.anchor_topic_id.title, sheet=current.name))
            current = current.anchor_topic_id.sheet_id if current.sheet_role == 'sub' else False
        height = self._subtree_sub_height(subtree)
        max_depth = self.env['xmind.sheet']._MAX_SUB_DEPTH
        if height and (target_sheet.sheet_role == 'idea'
                       or target_sheet._sub_depth() + height > max_depth):
            raise UserError(_(
                'The moved topics contain sub sheet anchors; the target sheet must be the main '
                'sheet or a sub sheet, and sub sheets can be nested at most %s levels.', max_depth))
        dropped = self._move_subtrees(tops, target_sheet, parent)
        return {'moved': len(subtree), 'target_sheet_id': target_sheet.id, 'dropped': dropped}

    # ------------------------------------------------------------------
    # .xmind 匯出／匯入：分頁角色與子圖連結
    # ------------------------------------------------------------------
    #: 分頁上的自訂鍵（XMind 會忽略）：main / sub / idea
    _XMIND_ROLE_KEY = 'dobtor:sheetRole'
    #: 錨點主題原本的超連結（href 被子圖連結佔用時另存）
    _XMIND_HREF_KEY = 'dobtor:hyperlink'
    _XMIND_SHEET_LINK = 'xmind:#'

    def _export_sheet_id(self, sheet):
        """分頁在 .xmind 裡的 id（子圖連結 xmind:#<id> 指向它，所以要穩定）。"""
        return sheet.component_id or 'sheet-%d' % sheet.id

    def _restore_sheet_roles(self, imported):
        """匯入後依「主題 href = xmind:#<分頁 id>」把分頁還原成子圖。

        :param imported: [(sheet_data, xmind.sheet)]，依檔案順序
        規則：
        - 主圖：自訂鍵標成 main 的那張，沒有就是第一張（建立時已自動成為主圖）；
        - 子圖：被某顆（主圖或子圖上的）主題以分頁連結指到的分頁，由主圖往下逐層
          還原；違反子圖規則（中心主題、超過三層、成環）就留作發想頁；
        - 其他（沒被連到的）一律是發想頁。
        錨點主題的超連結還原成匯出前的值（自訂鍵），沒有就清空。
        """
        if not imported:
            return
        Topic = self.env['xmind.topic']
        by_cid = {}
        for data, sheet in imported:
            if data.get('id'):
                by_cid.setdefault(data['id'], sheet)

        links = []   # (source sheet, topic component_id, target sheet, original href)
        for data, sheet in imported:
            stack = [data.get('rootTopic') or {}]
            while stack:
                node = stack.pop()
                href = node.get('href') or ''
                if href.startswith(self._XMIND_SHEET_LINK):
                    target = by_cid.get(href[len(self._XMIND_SHEET_LINK):])
                    if target and target != sheet and node.get('id'):
                        links.append((sheet, node['id'], target, node.get(self._XMIND_HREF_KEY) or ''))
                children = node.get('children') or {}
                for key in ('attached', 'detached'):
                    stack.extend(children.get(key) or [])

        declared_main = next((sheet for data, sheet in imported
                              if data.get(self._XMIND_ROLE_KEY) == 'main'), None)
        if declared_main and declared_main.sheet_role != 'main':
            try:
                with self.env.cr.savepoint():
                    declared_main._set_as_main()
            except (UserError, ValidationError):
                _logger.info('xmind import: could not restore main sheet %s', declared_main.id)

        anchors = {}   # target sheet id -> (anchor topic, original href)
        for source, cid, target, original in links:
            topic = Topic.search([('sheet_id', '=', source.id), ('component_id', '=', cid)], limit=1)
            if topic:
                anchors.setdefault(target.id, (topic, target, original))

        progress = True
        while progress and anchors:
            progress = False
            for target_id, (topic, target, original) in list(anchors.items()):
                if topic.sheet_id.sheet_role not in ('main', 'sub') or target.sheet_role != 'idea':
                    continue
                del anchors[target_id]
                progress = True
                try:
                    with self.env.cr.savepoint():
                        target.write({'sheet_role': 'sub', 'anchor_topic_id': topic.id})
                        topic.hyperlink = original or False
                except (UserError, ValidationError) as e:
                    _logger.info('xmind import: sheet %s kept as idea sheet: %s', target.name, e)
