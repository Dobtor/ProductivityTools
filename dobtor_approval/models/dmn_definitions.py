# -*- coding: utf-8 -*-
# Copyright 2026 Dobtor Systems Integration — License LGPL-3
"""DMN 決策集（DESIGN_DMN.md §3.1、§5、§9–10）。

`dmn_xml` 為真相（dmn-js 編輯）；`save_dmn_xml()` → `_parse_dmn()` 重建 shadow 投影。
`evaluate_*` 系列依 binding 注入 ctx、DRD 拓樸排序、逐決策求值；
approver 慣例輸出回傳依序簽核人鏈，接回既有分階引擎。
"""
import logging
from decimal import Decimal

from lxml import etree

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from . import dmn_feel
from .dmn_decision import APPROVER_OUTPUT_NAMES

_logger = logging.getLogger(__name__)

# DMN hitPolicy（XML 屬性，常為大寫/含空白）→ 內部值
_HIT_MAP = {
    'UNIQUE': 'unique', 'ANY': 'any', 'PRIORITY': 'priority', 'FIRST': 'first',
    'COLLECT': 'collect', 'RULE ORDER': 'rule_order', 'OUTPUT ORDER': 'output_order',
}
_AGG_MAP = {'SUM': 'sum', 'MIN': 'min', 'MAX': 'max', 'COUNT': 'count'}

EMPTY_DMN_XML = """<?xml version="1.0" encoding="UTF-8"?>
<definitions xmlns="https://www.omg.org/spec/DMN/20191111/MODEL/"
             id="definitions_new" name="新決策集" namespace="http://dobtor/dmn">
  <decision id="Decision_1" name="決策1">
    <decisionTable id="DecisionTable_1" hitPolicy="UNIQUE">
      <output id="Output_1" name="result" typeRef="string"/>
    </decisionTable>
  </decision>
</definitions>"""


def _ln(tag):
    """取 XML local-name（去命名空間）。"""
    return etree.QName(tag).localname if isinstance(tag, str) else etree.QName(tag.tag).localname


def _children(el, name):
    return [c for c in el if _ln(c) == name]


def _first(el, name):
    for c in el:
        if _ln(c) == name:
            return c
    return None


def _text_of(el):
    t = _first(el, 'text')
    if t is not None and t.text:
        return t.text.strip()
    return ''


def _href_id(el):
    href = el.get('href') or ''
    return href[1:] if href.startswith('#') else href


def _value_list(text):
    """DMN inputValues/outputValues 的 FEEL 清單（如 "高","中","低"）→ 去引號逗號字串。"""
    if not text:
        return ''
    parts = [p.strip().strip('"').strip("'").strip() for p in text.split(',')]
    return ','.join(p for p in parts if p)


class DmnDefinitions(models.Model):
    _name = 'dmn.definitions'
    _description = 'DMN 決策集'
    _inherit = ['mail.thread']
    _order = 'name'

    name = fields.Char(string='名稱', required=True, tracking=True)
    dmn_xml = fields.Text(string='DMN XML', default=EMPTY_DMN_XML)
    state = fields.Selection([
        ('draft', '草稿'),
        ('published', '已發佈'),
        ('archived', '已封存'),
    ], string='狀態', default='draft', tracking=True, index=True)
    version = fields.Integer(string='版本', default=0, tracking=True)
    company_id = fields.Many2one('res.company', string='公司',
                                 default=lambda self: self.env.company)
    active = fields.Boolean(default=True)

    decision_ids = fields.One2many('dmn.decision', 'definitions_id', string='決策')
    input_data_ids = fields.One2many('dmn.input.data', 'definitions_id', string='輸入資料')
    bkm_ids = fields.One2many('dmn.bkm', 'definitions_id', string='知識模型')
    requirement_ids = fields.One2many('dmn.requirement', 'definitions_id', string='需求邊')
    binding_ids = fields.One2many('dmn.input.binding', 'definitions_id', string='變數綁定')

    decision_count = fields.Integer(compute='_compute_decision_count')

    @api.depends('decision_ids')
    def _compute_decision_count(self):
        for d in self:
            d.decision_count = len(d.decision_ids)

    # ------------------------------------------------------------------
    # 建立 / 存檔 / 解析
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('dmn_xml'):
                vals['dmn_xml'] = EMPTY_DMN_XML
        recs = super().create(vals_list)
        for rec in recs:
            rec._parse_dmn()
        return recs

    def write(self, vals):
        res = super().write(vals)
        # 直接改 XML（後台表單）→ 重建 shadow 投影
        if 'dmn_xml' in vals:
            for rec in self:
                rec._parse_dmn()
        return res

    def save_dmn_xml(self, xml):
        """編輯器存檔入口：寫 XML → 重建 shadow（草稿才可存）。"""
        self.ensure_one()
        if self.state == 'published':
            raise UserError(_('已發佈的決策集不可直接修改，請先轉草稿或升版。'))
        self.dmn_xml = xml   # write() override 會觸發 _parse_dmn 重建 shadow
        return True

    def _parse_dmn(self):
        """DMN XML → shadow models（先刪後建）。XML 為真相。"""
        self.ensure_one()
        # 清舊投影（含決策表本體，避免孤兒累積）
        self.env['dmn.decision.table'].search(
            [('definitions_id', '=', self.id)]).unlink()
        self.decision_ids.unlink()
        self.input_data_ids.unlink()
        self.bkm_ids.unlink()
        self.requirement_ids.unlink()
        if not self.dmn_xml:
            return
        try:
            root = etree.fromstring(self.dmn_xml.encode('utf-8'))
        except Exception as e:
            raise UserError(_('DMN XML 解析失敗：%s', e))

        Dec = self.env['dmn.decision']
        InData = self.env['dmn.input.data']
        Bkm = self.env['dmn.bkm']
        Req = self.env['dmn.requirement']

        # 第一輪：建決策 / 輸入資料 / BKM（dmn_id → record）
        id2dec = {}
        seq = 0
        for el in root:
            tag = _ln(el)
            if tag == 'decision':
                seq += 10
                dec = Dec.create(self._decision_vals(el, seq))
                id2dec[el.get('id')] = dec
            elif tag == 'inputData':
                InData.create({
                    'definitions_id': self.id, 'dmn_id': el.get('id'),
                    'name': el.get('name') or el.get('id'),
                    'type_ref': self._var_type(el)})
            elif tag == 'businessKnowledgeModel':
                Bkm.create(self._bkm_vals(el))

        # 第二輪：需求邊 + decision.requires_ids
        for el in _children(root, 'decision'):
            dec = id2dec.get(el.get('id'))
            for ir in _children(el, 'informationRequirement'):
                rd = _first(ir, 'requiredDecision')
                ri = _first(ir, 'requiredInput')
                if rd is not None:
                    src = _href_id(rd)
                    Req.create({'definitions_id': self.id, 'source_dmn_id': src,
                                'target_dmn_id': el.get('id'), 'req_type': 'information'})
                    if src in id2dec:
                        dec.requires_ids = [(4, id2dec[src].id)]
                elif ri is not None:
                    Req.create({'definitions_id': self.id, 'source_dmn_id': _href_id(ri),
                                'target_dmn_id': el.get('id'), 'req_type': 'information'})
            for kr in _children(el, 'knowledgeRequirement'):
                rk = _first(kr, 'requiredKnowledge')
                if rk is not None:
                    Req.create({'definitions_id': self.id, 'source_dmn_id': _href_id(rk),
                                'target_dmn_id': el.get('id'), 'req_type': 'knowledge'})

    def _var_type(self, el):
        var = _first(el, 'variable')
        if var is not None and var.get('typeRef'):
            return var.get('typeRef')
        return 'string'

    def _decision_vals(self, el, seq):
        vals = {
            'definitions_id': self.id, 'dmn_id': el.get('id'),
            'name': el.get('name') or el.get('id'), 'sequence': seq,
        }
        var = _first(el, 'variable')
        if var is not None and var.get('typeRef'):
            vals['output_type_ref'] = var.get('typeRef') if var.get('typeRef') in [
                t[0] for t in self.env['dmn.decision']._fields['output_type_ref'].selection] else False
        dt = _first(el, 'decisionTable')
        le = _first(el, 'literalExpression')
        if dt is not None:
            vals['logic_type'] = 'decision_table'
            vals['table_id'] = self._build_table(dt).id
        elif le is not None:
            vals['logic_type'] = 'literal_expression'
            vals['literal_expression'] = _text_of(le)
        return vals

    def _bkm_vals(self, el):
        vals = {'definitions_id': self.id, 'dmn_id': el.get('id'),
                'name': el.get('name') or el.get('id'),
                'logic_type': 'literal_expression'}
        enc = _first(el, 'encapsulatedLogic')
        body = enc if enc is not None else el
        dt = _first(body, 'decisionTable')
        le = _first(body, 'literalExpression')
        if dt is not None:
            vals['logic_type'] = 'decision_table'
            vals['table_id'] = self._build_table(dt).id
        elif le is not None:
            vals['literal_expression'] = _text_of(le)
        return vals

    def _build_table(self, dt):
        Tbl = self.env['dmn.decision.table']
        table = Tbl.create({
            'definitions_id': self.id,
            'hit_policy': _HIT_MAP.get((dt.get('hitPolicy') or 'UNIQUE').upper(), 'unique'),
            'aggregation': _AGG_MAP.get((dt.get('aggregation') or '').upper(), 'none'),
        })
        Inp = self.env['dmn.decision.table.input']
        Out = self.env['dmn.decision.table.output']
        Rule = self.env['dmn.decision.table.rule']
        Entry = self.env['dmn.rule.entry']

        inputs = []
        for i, inp in enumerate(_children(dt, 'input')):
            ie = _first(inp, 'inputExpression')
            iv = _first(inp, 'inputValues')
            inputs.append(Inp.create({
                'table_id': table.id, 'sequence': (i + 1) * 10,
                'label': inp.get('label') or '',
                'expression': _text_of(ie) if ie is not None else '',
                'type_ref': (ie.get('typeRef') if ie is not None and ie.get('typeRef') else 'string'),
                'allowed_values': _value_list(_text_of(iv)) if iv is not None else '',
            }))
        outputs = []
        for i, out in enumerate(_children(dt, 'output')):
            ov = _first(out, 'outputValues')
            outputs.append(Out.create({
                'table_id': table.id, 'sequence': (i + 1) * 10,
                'name': out.get('name') or ('output_%d' % (i + 1)),
                'label': out.get('label') or '',
                'type_ref': out.get('typeRef') or 'string',
                'allowed_values': _value_list(_text_of(ov)) if ov is not None else '',
            }))
        for r, rule in enumerate(_children(dt, 'rule')):
            rrec = Rule.create({'table_id': table.id, 'sequence': (r + 1) * 10,
                                'description': (rule.get('id') or '')})
            for j, ie in enumerate(_children(rule, 'inputEntry')):
                Entry.create({
                    'rule_id': rrec.id, 'kind': 'input', 'sequence': (j + 1) * 10,
                    'clause_input_id': inputs[j].id if j < len(inputs) else False,
                    'text': _text_of(ie) or '-'})
            for j, oe in enumerate(_children(rule, 'outputEntry')):
                Entry.create({
                    'rule_id': rrec.id, 'kind': 'output', 'sequence': (j + 1) * 10,
                    'clause_output_id': outputs[j].id if j < len(outputs) else False,
                    'text': _text_of(oe)})
        return table

    # ------------------------------------------------------------------
    # 執行期求值（§5）
    # ------------------------------------------------------------------
    def build_context(self, record=None, applicant=None, instance=None):
        """依 binding 注入 ctx。FEEL 僅能讀白名單欄位（§9）。"""
        self.ensure_one()
        ctx = {}
        for b in self.binding_ids:
            try:
                ctx[b.variable] = self._resolve_binding(b, record, applicant, instance)
            except Exception as e:
                _logger.warning('DMN binding %s 解析失敗：%s', b.variable, e)
                ctx[b.variable] = None
        return ctx

    def _resolve_binding(self, b, record, applicant, instance):
        if b.source_kind == 'constant':
            return b.constant_value
        if b.source_kind == 'applicant':
            return applicant.display_name if applicant else None
        if b.source_kind == 'instance_ctx':
            if instance and hasattr(instance, 'get_ctx_value'):
                return instance.get_ctx_value(b.instance_key)
            return None
        if b.source_kind == 'record_field':
            return self._read_path(record, b.record_field)
        return None

    def _read_path(self, record, path):
        if not record or not path or '__' in path:
            return None
        cur = record
        for part in path.split('.'):
            if cur is False or cur is None:
                return None
            cur = getattr(cur, part, None)
        # 葉值：m2o/recordset → display_name；數值/日期/字串原樣
        if hasattr(cur, '_name') and hasattr(cur, 'ids'):
            return cur.display_name if cur else None
        return cur

    def _topo_decisions(self):
        """依資訊需求拓樸排序（被依賴者在前）。"""
        self.ensure_one()
        decs = list(self.decision_ids)
        done, order = set(), []
        guard = 0
        while len(order) < len(decs):
            guard += 1
            if guard > len(decs) + 5:
                # 偵測到環，剩餘按原序附加
                for d in decs:
                    if d.id not in done:
                        order.append(d)
                        done.add(d.id)
                break
            for d in decs:
                if d.id in done:
                    continue
                deps = [r.id for r in d.requires_ids if r in decs]
                if all(x in done for x in deps):
                    order.append(d)
                    done.add(d.id)
        return order

    def evaluate_all(self, record=None, applicant=None, instance=None, only=None,
                     overrides=None):
        """求值決策與 BKM，回傳 ctx（決策名 → 值）。

        only：限定只求值的決策 recordset（None＝全部）；用於只算目標決策的依賴子樹。
        overrides：覆寫 binding 後的變數值（試算用，直接給輸入）。
        """
        self.ensure_one()
        ctx = self.build_context(record, applicant, instance)
        if overrides:
            ctx.update(overrides)
        ctx['__today__'] = fields.Date.context_today(self)
        # BKM 先求值（簡化：當作具名值，供決策引用）
        for bkm in self.bkm_ids:
            try:
                ctx[bkm.name] = self._eval_logic(
                    bkm.logic_type, bkm.literal_expression, bkm.table_id, ctx)
            except dmn_feel.FeelError as e:
                _logger.warning('BKM %s 求值失敗：%s', bkm.name, e)
        decs = self._topo_decisions()
        if only is not None:
            only_ids = set(only.ids)
            decs = [d for d in decs if d.id in only_ids]
        for dec in decs:
            try:
                ctx[dec.name] = self._eval_logic(
                    dec.logic_type, dec.literal_expression, dec.table_id, ctx)
            except dmn_feel.FeelError as e:
                _logger.warning('決策 %s 求值失敗：%s', dec.name, e)
                ctx[dec.name] = None
        return ctx

    def _decision_closure(self, dec):
        """回傳 dec 及其遞迴資訊需求（決策）的 recordset。"""
        seen, stack = set(), [dec]
        while stack:
            d = stack.pop()
            if d.id in seen:
                continue
            seen.add(d.id)
            stack.extend(d.requires_ids)
        return self.decision_ids.filtered(lambda x: x.id in seen)

    def evaluate_decision(self, dmn_id, record=None, applicant=None, instance=None):
        """求值指定決策（by dmn_id），回傳其值。只算該決策的依賴子樹。"""
        self.ensure_one()
        dec = self.decision_ids.filtered(lambda d: d.dmn_id == dmn_id)[:1]
        if not dec:
            raise UserError(_('找不到決策：%s', dmn_id))
        ctx = self.evaluate_all(record, applicant, instance,
                                only=self._decision_closure(dec))
        return ctx.get(dec.name)

    def _eval_logic(self, logic_type, literal, table, ctx):
        if logic_type == 'literal_expression':
            return dmn_feel.evaluate(literal or 'null', ctx)
        if table:
            return self._eval_table(table, ctx)
        return None

    def _hit_rules(self, table, ctx):
        """回傳命中的 [(rule, {output_name: value})]，依規則序。"""
        hits = []
        for rule in table.rule_ids.sorted('sequence'):
            matched = True
            for ent in rule.entry_ids.filtered(lambda e: e.kind == 'input'):
                clause = ent.clause_input_id
                if not clause:
                    continue
                val = dmn_feel.evaluate(clause.expression or 'null', ctx)
                if not dmn_feel.unary_test(ent.text or '-', val, ctx):
                    matched = False
                    break
            if matched:
                out = {}
                for ent in rule.entry_ids.filtered(lambda e: e.kind == 'output'):
                    if ent.clause_output_id and ent.text:
                        out[ent.clause_output_id.name] = dmn_feel.evaluate(ent.text, ctx)
                hits.append((rule, out))
        return hits

    def _eval_table(self, table, ctx):
        """依 hit policy 套用，回傳 scalar / dict / list（approver 為 list[dict]）。"""
        hits = self._hit_rules(table, ctx)
        outs = [o for _r, o in hits]
        names = table.output_ids.mapped('name')
        is_approver = bool(set(names) & APPROVER_OUTPUT_NAMES)
        policy = table.hit_policy

        def scalarize(d):
            if is_approver or len(names) != 1:
                return d
            return d.get(names[0]) if d else None

        if policy in ('collect', 'rule_order', 'output_order'):
            if is_approver:
                return outs                       # 簽核人鏈：list[dict]（依序）
            if policy == 'collect' and table.aggregation != 'none' and len(names) == 1:
                vals = [o.get(names[0]) for o in outs if o.get(names[0]) is not None]
                return self._aggregate(table.aggregation, vals)
            return [scalarize(o) for o in outs]
        # 單命中策略
        if not outs:
            return [] if is_approver else None
        if policy == 'unique' and len(outs) > 1:
            _logger.warning('決策表 hitPolicy=unique 但命中 %d 列，取第一列。', len(outs))
        if policy == 'priority':
            outs = [self._priority_pick(table, outs)]
        chosen = outs[0]
        return [chosen] if is_approver else scalarize(chosen)

    def _priority_pick(self, table, outs):
        out0 = table.output_ids.sorted('sequence')[:1]
        if out0 and out0.allowed_values:
            order = [v.strip() for v in out0.allowed_values.split(',')]
            name = out0.name

            def rank(o):
                v = dmn_feel._to_str(o.get(name))
                return order.index(v) if v in order else len(order)
            return sorted(outs, key=rank)[0]
        return outs[0]

    def _aggregate(self, agg, vals):
        nums = [Decimal(str(v)) for v in vals if v is not None]
        if agg == 'count':
            return Decimal(len(vals))
        if not nums:
            return None
        if agg == 'sum':
            return sum(nums, Decimal(0))
        if agg == 'min':
            return min(nums)
        if agg == 'max':
            return max(nums)
        return None

    # ------------------------------------------------------------------
    # 簽核人鏈（approver 慣例）→ 接回分階引擎
    # ------------------------------------------------------------------
    def resolve_approver_chain(self, dmn_id, record=None, applicant=None, instance=None):
        """回傳依序 approver dict 串列：[{resolver, level, job, users, phase}, ...]。"""
        self.ensure_one()
        chain = self.evaluate_decision(dmn_id, record, applicant, instance)
        if not isinstance(chain, list):
            chain = [chain] if isinstance(chain, dict) else []
        result = []
        for i, item in enumerate(chain):
            if not isinstance(item, dict):
                continue
            result.append({
                'resolver': dmn_feel._to_str(item.get('resolver')) or 'direct_manager',
                'level': int(item['level']) if item.get('level') is not None else 1,
                'job': dmn_feel._to_str(item.get('job')) if item.get('job') else False,
                'users': item.get('users') or False,
                'phase': int(item['phase']) if item.get('phase') is not None else (i + 1),
            })
        return result

    # ------------------------------------------------------------------
    # 發佈 / 校驗
    # ------------------------------------------------------------------
    def validate_for_publish(self):
        """回傳錯誤 list（空＝通過）。"""
        self.ensure_one()
        errs = []
        if not self.decision_ids:
            errs.append(_('決策集「%s」沒有任何決策。', self.name))
        bound = set(self.binding_ids.mapped('variable'))
        bound |= set(self.input_data_ids.mapped('name'))
        bound |= set(self.decision_ids.mapped('name'))
        bound |= set(self.bkm_ids.mapped('name'))
        for dec in self.decision_ids:
            if dec.logic_type == 'decision_table':
                tbl = dec.table_id
                if not tbl or not tbl.output_ids:
                    errs.append(_('決策「%s」缺輸出欄。', dec.name))
                    continue
                for inp in tbl.input_ids:
                    for nm in dmn_feel.free_names(inp.expression or ''):
                        if nm not in bound:
                            errs.append(_('決策「%(d)s」輸入式引用未綁定變數「%(v)s」。',
                                          d=dec.name, v=nm))
            elif dec.logic_type == 'literal_expression':
                if not dec.literal_expression:
                    errs.append(_('決策「%s」FEEL 運算式為空。', dec.name))
        return errs

    def action_publish(self):
        for rec in self:
            errs = rec.validate_for_publish()
            if errs:
                raise UserError('\n'.join(errs))
            rec.write({'state': 'published', 'version': rec.version + 1})
            rec.message_post(body=_('決策集已發佈（版本 %s）。', rec.version))
        return True

    def action_set_draft(self):
        self.write({'state': 'draft'})
        return True

    # ------------------------------------------------------------------
    # 覆蓋 / 重疊分析（§10）— 單輸入數值階梯
    # ------------------------------------------------------------------
    def coverage_warnings(self, dmn_id):
        self.ensure_one()
        dec = self.decision_ids.filtered(lambda d: d.dmn_id == dmn_id)[:1]
        warns = []
        if not dec or dec.logic_type != 'decision_table':
            return warns
        tbl = dec.table_id
        single_hit = tbl.hit_policy in ('unique', 'first', 'priority')
        # 數值階梯缺口（單一數值輸入）
        num_inputs = tbl.input_ids.filtered(lambda i: i.type_ref == 'number')
        if len(num_inputs) == 1 and single_hit:
            warns += self._numeric_gap(tbl, num_inputs)
        # 列舉缺口：宣告 allowed_values 的輸入欄，哪些值無等值規則覆蓋
        for inp in tbl.input_ids.filtered(lambda i: i.allowed_values):
            warns += self._enum_gap(tbl, inp)
        return warns

    def _enum_gap(self, tbl, inp):
        """allowed_values 中未被任何規則等值/任意涵蓋的值 → 警示。"""
        allowed = [v.strip() for v in (inp.allowed_values or '').split(',') if v.strip()]
        if not allowed:
            return []
        covered, has_any = set(), False
        for rule in tbl.rule_ids:
            ent = rule.entry_ids.filtered(
                lambda e: e.kind == 'input' and e.clause_input_id == inp)[:1]
            txt = (ent.text if ent else '-').strip()
            if txt in ('', '-'):
                has_any = True
                break
            covered |= self._enum_values(txt)
        if has_any:
            return []
        missing = [v for v in allowed if v not in covered]
        if missing:
            return [_('欄位「%(f)s」列舉值未覆蓋：%(v)s',
                      f=inp.label or inp.expression, v='、'.join(missing))]
        return []

    def _enum_values(self, txt):
        """從 unary test 抽出字面字串/數值集合（供列舉覆蓋比對）。"""
        try:
            node = dmn_feel.parse_unary(txt)
        except dmn_feel.FeelError:
            return set()
        out = set()

        def collect(n):
            k = n.__class__
            if k is dmn_feel.EqTest:
                try:
                    out.add(dmn_feel._to_str(dmn_feel.evaluate(n.expr)))
                except Exception:
                    pass
            elif k in (dmn_feel.OrTests, dmn_feel.NotTest):
                for t in n.tests:
                    collect(t)
        collect(node)
        return out

    def _numeric_gap(self, tbl, num_input):
        bounds = []
        for rule in tbl.rule_ids.sorted('sequence'):
            ent = rule.entry_ids.filtered(
                lambda e: e.kind == 'input' and e.clause_input_id == num_input)[:1]
            txt = ent.text if ent else '-'
            iv = self._interval_bounds(txt)
            if iv:
                bounds.append(iv)
        bounds.sort(key=lambda b: b[0])
        warns = []
        cursor = Decimal(0)
        for lo, hi in bounds:
            if lo > cursor:
                warns.append(_('數值 %(a)s–%(b)s 無規則覆蓋。', a=cursor, b=lo))
            if hi is None:
                return warns
            cursor = max(cursor, hi)
        warns.append(_('數值 %s 以上無規則覆蓋。', cursor))
        return warns

    def _interval_bounds(self, txt):
        """粗略解析 unary test 的數值上下界：回傳 (low, high|None) 或 None。"""
        try:
            node = dmn_feel.parse_unary(txt)
        except dmn_feel.FeelError:
            return None
        k = node.__class__
        if k is dmn_feel.IntervalTest:
            iv = node.interval
            try:
                lo = Decimal(str(dmn_feel.evaluate(iv.low)))
                hi = Decimal(str(dmn_feel.evaluate(iv.high)))
                return (lo, hi)
            except Exception:
                return None
        if k is dmn_feel.CmpTest:
            try:
                ep = Decimal(str(dmn_feel.evaluate(node.endpoint)))
            except Exception:
                return None
            if node.op in ('>=', '>'):
                return (ep, None)
            if node.op in ('<=', '<'):
                return (Decimal(0), ep)
        return None

    # ------------------------------------------------------------------
    # 編輯器資料
    # ------------------------------------------------------------------
    def get_dmn_data(self):
        self.ensure_one()
        return {
            'id': self.id,
            'name': self.name,
            'state': self.state,
            'version': self.version,
            'xml': self.dmn_xml or EMPTY_DMN_XML,
            'bindings': [{
                'variable': b.variable, 'source_kind': b.source_kind,
                'record_field': b.record_field or '', 'constant_value': b.constant_value or '',
            } for b in self.binding_ids],
            'decisions': [
                {'id': d.id, 'dmn_id': d.dmn_id, 'name': d.name or d.dmn_id}
                for d in self.decision_ids
            ],
            'users': [
                {'id': u.id, 'name': u.name}
                for u in self.env['res.users'].search(
                    [('share', '=', False)], limit=100)
            ],
        }

    def preview_inline(self, decision_dmn_id, input_json, applicant_id=False):
        """編輯器內嵌試算：對指定決策（by dmn_id，存檔 reparse 後仍穩定）求值，
        回傳結果 HTML 字串（重用 preview 模型）。"""
        self.ensure_one()
        dec = self.decision_ids.filtered(lambda d: d.dmn_id == decision_dmn_id)[:1]
        if not dec:
            return '<p class="text-danger">請選擇決策。</p>'
        pv = self.env['dmn.decision.preview'].create({
            'definitions_id': self.id,
            'decision_id': dec.id,
            'input_json': input_json or '{}',
            'applicant_id': applicant_id or False,
        })
        try:
            pv.action_run()
        except UserError as e:
            return '<p class="text-danger">%s</p>' % e
        return pv.result_html or ''

    def action_open_editor(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'dmn_editor',
            'name': self.name,
            'params': {'definitions_id': self.id},
        }

    def action_open_preview(self):
        """開啟試算精靈（預設帶入本決策集第一個決策）。"""
        self.ensure_one()
        ctx = {'default_definitions_id': self.id}
        if self.decision_ids:
            ctx['default_decision_id'] = self.decision_ids[0].id
        return {
            'type': 'ir.actions.act_window',
            'name': _('DMN 決策試算'),
            'res_model': 'dmn.decision.preview',
            'view_mode': 'form',
            'target': 'new',
            'context': ctx,
        }

    def set_bindings(self, bindings):
        """編輯器存綁定：以傳入清單重建 binding_ids。"""
        self.ensure_one()
        cmds = [(5, 0, 0)]
        for b in bindings or []:
            if not b.get('variable'):
                continue
            cmds.append((0, 0, {
                'variable': b.get('variable'),
                'source_kind': b.get('source_kind') or 'record_field',
                'record_field': b.get('record_field') or False,
                'instance_key': b.get('instance_key') or False,
                'constant_value': b.get('constant_value') or False,
            }))
        self.binding_ids = cmds
        return True
