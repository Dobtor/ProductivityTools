# -*- coding: utf-8 -*-
"""核決權限表（Authority Matrix）— 專家能力包「DMN 決策表」的垂直切片。

把「金額/類別/部門 → 簽核角色」這條台灣 ERP 最高頻的決策，做成可編輯、可版本、
可稽核的結構化決策表（而非完整 DMN XML）。接成 `bpmn.role` 的 `authority_matrix`
解析方式：節點的簽核人由決策表依單據動態決定。

hit policy：
- collect：全部命中規則列 → 該節點會簽其全部簽核人（命中鏈亦供未來序簽展開）。
- priority：取序最前一筆命中。
- unique：應恰好命中一筆（多筆時取序最前）。
"""
import logging

from odoo import Command, _, api, fields, models

_logger = logging.getLogger(__name__)

# 規則列輸出（簽核人）可用的解析方式 — basic_approval 的人員挑選子集
_LINE_RESOLVERS = [
    ('direct_manager', '申請人直屬主管'),
    ('department_manager', '申請人部門經理'),
    ('manager_level', '往上第 N 級主管'),
    ('job_position', '指定職位'),
    ('specific_user', '指定使用者'),
]


class BpmnAuthorityMatrix(models.Model):
    _name = 'bpmn.authority.matrix'
    _description = '核決權限表（決策矩陣）'
    _inherit = ['mail.thread']
    _order = 'name'

    name = fields.Char(string='名稱', required=True, tracking=True)
    active = fields.Boolean(default=True)
    model_id = fields.Many2one(
        'ir.model', string='適用單據模型', ondelete='cascade',
        help='此決策表評估的目標單據（如 purchase.order）')
    model_name = fields.Char(related='model_id.model', store=True, index=True)

    # 輸入欄位設定（取單據上的欄位作為決策輸入）
    amount_field = fields.Char(string='金額欄位', help="如 amount_total；未設則金額一律 0")
    category_field = fields.Char(string='類別欄位', help="取其字串值比對；未設則類別不限")
    use_applicant_department = fields.Boolean(
        string='以申請人部門比對', default=True,
        help='勾選＝用申請人 employee 的部門；取消＝改用下方單據部門欄位')
    department_field = fields.Char(string='單據部門欄位', help="如 department_id（hr.department）")

    hit_policy = fields.Selection([
        ('collect', '疊加 Collect（全部命中 → 會簽/鏈）'),
        ('priority', '優先 Priority（取序最前一筆）'),
        ('unique', '唯一 Unique（應恰好命中一筆）'),
    ], string='命中策略', default='collect', required=True)

    line_ids = fields.One2many('bpmn.authority.matrix.line', 'matrix_id', string='規則列')
    line_count = fields.Integer(compute='_compute_line_count', string='規則數')
    note = fields.Text(string='備註')

    # 版本 / 凍結（核決權限變更稽核）
    state = fields.Selection([
        ('draft', '草稿'), ('frozen', '定版')],
        string='狀態', default='draft', tracking=True)
    version = fields.Integer(string='版本', default=1, readonly=True, copy=False)

    @api.depends('line_ids')
    def _compute_line_count(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)

    def action_freeze(self):
        """定版：凍結此權限表（變更前須先設為草稿）。"""
        for rec in self:
            if rec.state != 'frozen':
                rec.write({'state': 'frozen'})
        return True

    def action_set_draft(self):
        """轉回草稿並升版（保留稽核軌跡）。"""
        for rec in self:
            rec.write({'state': 'draft', 'version': rec.version + 1})
        return True

    # ------------------------------------------------------------------
    # 求值引擎
    # ------------------------------------------------------------------
    def _category_values(self, record):
        """回傳可接受的類別比對字串集合，容忍 m2o(id/標籤) / selection(key/標籤) / char。"""
        if not (record and self.category_field and self.category_field in record._fields):
            return set()
        val = record[self.category_field]
        if not val:
            return set()
        if hasattr(val, '_name'):  # Many2one recordset
            return {str(val.id), val.display_name or ''}
        out = {str(val)}
        field = record._fields.get(self.category_field)
        if field and field.type == 'selection':
            try:
                label = dict(field._description_selection(record.env)).get(val)
                if label:
                    out.add(label)
            except Exception:  # noqa: BLE001
                pass
        return out

    def _extract_inputs(self, record, applicant_user):
        """從單據/申請人取出 (amount, cat_values:set, department)。"""
        self.ensure_one()
        amount = 0.0
        if record and self.amount_field and self.amount_field in record._fields:
            amount = record[self.amount_field] or 0.0
        cat_values = self._category_values(record)
        dept = self.env['hr.department']
        if self.use_applicant_department and applicant_user:
            dept = applicant_user.employee_id.department_id
        elif record and self.department_field and self.department_field in record._fields:
            dept = record[self.department_field]
        return amount, cat_values, dept

    def _line_matches(self, line, amount, cat_values, dept):
        # 金額：amount_min ≤ amount <（amount_max 或 無上限）
        if line.amount_max:
            if not (line.amount_min <= amount < line.amount_max):
                return False
        elif amount < line.amount_min:
            return False
        # 類別：留空＝不限；否則須命中可接受字串之一
        if line.category_value and line.category_value not in cat_values:
            return False
        # 部門：留空＝不限
        if line.department_id and (not dept or dept.id != line.department_id.id):
            return False
        return True

    def evaluate(self, record, applicant_user):
        """回傳命中的規則列 recordset（依 hit policy 與 sequence）。"""
        self.ensure_one()
        amount, cat_values, dept = self._extract_inputs(record, applicant_user)
        matched = self.line_ids.filtered(
            lambda l: self._line_matches(l, amount, cat_values, dept)).sorted('sequence')
        if self.hit_policy in ('priority', 'unique'):
            if self.hit_policy == 'unique' and len(matched) > 1:
                _logger.warning(
                    '核決權限表「%s」hit_policy=unique 但命中 %d 筆，取序最前。',
                    self.name, len(matched))
            return matched[:1]
        return matched

    def resolve_approvers(self, record, applicant_user):
        """回傳命中鏈 [(line, users)]：每一命中列解析出其簽核人。"""
        self.ensure_one()
        Role = self.env['bpmn.role']
        inst_vals = {'applicant_user_id': applicant_user.id if applicant_user else False}
        if record:
            inst_vals.update(res_model=record._name, res_id=record.id)
        instance = self.env['bpmn.process.instance'].new(inst_vals)
        chain = []
        for line in self.evaluate(record, applicant_user):
            role = Role.new(line._role_vals())
            chain.append((line, role.resolve(instance)))
        return chain

    def validate_for_publish(self):
        """發佈期完整性校驗：回傳 list[str] 錯誤（空＝通過）。"""
        self.ensure_one()
        errs = []
        if not self.line_ids:
            errs.append(_('核決權限表「%s」沒有任何規則列。', self.name))
        model = None
        if self.model_name and self.model_name in self.env:
            model = self.env[self.model_name]
        if model is not None:
            for fld in ('amount_field', 'category_field', 'department_field'):
                fname = self[fld]
                if fname and fname not in model._fields:
                    errs.append(_(
                        '核決權限表「%(m)s」的欄位「%(f)s」不存在於模型 %(mod)s。',
                        m=self.name, f=fname, mod=self.model_name))
        for line in self.line_ids:
            if line.resolver_type == 'job_position' and not line.job_id:
                errs.append(_('核決權限表「%s」有規則列未指定職位。', self.name))
            if line.resolver_type == 'specific_user' and not line.user_ids:
                errs.append(_('核決權限表「%s」有規則列未指定使用者。', self.name))
        return errs

    def _coverage_warnings(self):
        """基礎金額階梯（無類別/部門限制列）是否覆蓋 [0, ∞) 無缺口。回傳警示 list。"""
        self.ensure_one()
        base = self.line_ids.filtered(
            lambda l: not l.category_value and not l.department_id).sorted('amount_min')
        warns = []
        cursor = 0.0
        for line in base:
            if line.amount_min > cursor:
                warns.append(_('金額 %(a)s–%(b)s 無基礎規則對應（可能解析不到簽核人）。',
                               a=cursor, b=line.amount_min))
            if not line.amount_max:
                return warns  # 已覆蓋至無上限
            cursor = max(cursor, line.amount_max)
        warns.append(_('金額 %s 以上無基礎規則對應。', cursor))
        return warns

    def preview_manual(self, amount, category, department, applicant_user):
        """設計期試算：直接給輸入（不需真實單據），回傳命中鏈 [(line, users)]。"""
        self.ensure_one()
        cat_values = {category} if category else set()
        matched = self.line_ids.filtered(
            lambda l: self._line_matches(l, amount or 0.0, cat_values, department)
        ).sorted('sequence')
        if self.hit_policy in ('priority', 'unique'):
            matched = matched[:1]
        Role = self.env['bpmn.role']
        instance = self.env['bpmn.process.instance'].new({
            'applicant_user_id': applicant_user.id if applicant_user else False})
        return [(line, Role.new(line._role_vals()).resolve(instance)) for line in matched]

    def action_open_preview(self):
        """開啟試算精靈。"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('核決權限表試算'),
            'res_model': 'bpmn.authority.matrix.preview',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_matrix_id': self.id},
        }

    # ------------------------------------------------------------------
    # 轉 DMN（Layer G）：核決權限表 → 等價 dmn.definitions（決策表 + 綁定）
    # ------------------------------------------------------------------
    def action_to_dmn(self):
        """產生等價的 DMN 決策集並開啟其編輯器。

        對映：金額/類別/部門 → 決策表輸入欄；規則列 → rule；
        簽核解析 → approver 慣例輸出（resolver/level/job/users）。
        綁定：amount←amount_field、category←category_field、department←department_field。
        """
        self.ensure_one()
        xml = self._build_dmn_xml()
        defn = self.env['dmn.definitions'].create({
            'name': _('%s（轉自核決權限表）', self.name),
            'dmn_xml': xml,
            'company_id': self.env.company.id,
        })
        bindings = []
        if self.amount_field:
            bindings.append({'variable': 'amount', 'source_kind': 'record_field',
                             'record_field': self.amount_field})
        if self.category_field:
            bindings.append({'variable': 'category', 'source_kind': 'record_field',
                             'record_field': self.category_field})
        if self.department_field and not self.use_applicant_department:
            bindings.append({'variable': 'department', 'source_kind': 'record_field',
                             'record_field': self.department_field})
        if bindings:
            defn.set_bindings(bindings)
        self.message_post(body=_('已轉為 DMN 決策集「%s」。', defn.name))
        return defn.action_open_editor()

    def _build_dmn_xml(self):
        """以 lxml 產生 DMN 1.3 XML。輸入欄依設定動態決定；輸出採 approver 慣例。"""
        from lxml.builder import ElementMaker
        from lxml import etree as _ET

        ns = 'https://www.omg.org/spec/DMN/20191111/MODEL/'
        E = ElementMaker(namespace=ns, nsmap={None: ns})

        # 動態輸入欄
        inputs = []
        if self.amount_field:
            inputs.append(('amount', 'number', '金額'))
        if self.category_field:
            inputs.append(('category', 'string', '類別'))
        if self.department_field and not self.use_applicant_department:
            inputs.append(('department', 'string', '部門'))

        # 輸出欄（approver 慣例）
        has_job = any(l.resolver_type == 'job_position' for l in self.line_ids)
        has_users = any(l.resolver_type == 'specific_user' for l in self.line_ids)
        outputs = [('resolver', 'string'), ('level', 'number')]
        if has_job:
            outputs.append(('job', 'string'))
        if has_users:
            outputs.append(('users', 'string'))

        hit = {'collect': 'COLLECT', 'priority': 'PRIORITY',
               'unique': 'UNIQUE'}.get(self.hit_policy, 'COLLECT')

        dt_children = []
        for i, (var, tref, label) in enumerate(inputs, start=1):
            dt_children.append(E.input(
                E.inputExpression(E.text(var), {'id': 'IE_%d' % i, 'typeRef': tref}),
                {'id': 'In_%d' % i, 'label': label}))
        for j, (name, tref) in enumerate(outputs, start=1):
            dt_children.append(E.output({'id': 'Out_%d' % j, 'name': name, 'typeRef': tref}))

        for r, line in enumerate(self.line_ids.sorted('sequence'), start=1):
            rule = E.rule({'id': 'rule_%d' % r})
            for (var, _t, _l) in inputs:
                rule.append(E.inputEntry(E.text(self._dmn_input_entry(var, line)),
                                         {'id': 'rin_%d_%s' % (r, var)}))
            for (name, _t) in outputs:
                rule.append(E.outputEntry(E.text(self._dmn_output_entry(name, line)),
                                          {'id': 'rout_%d_%s' % (r, name)}))
            dt_children.append(rule)

        table = E.decisionTable(*dt_children, {'id': 'DT_chain', 'hitPolicy': hit})
        decision = E.decision(table, {'id': 'Decision_chain', 'name': '核決層級鏈'})
        extra = [E.inputData({'id': 'InputData_%s' % v, 'name': v})
                 for (v, _t, _l) in inputs]
        root = E.definitions(decision, *extra, {
            'id': 'defn_from_matrix_%d' % self.id,
            'name': self.name or 'matrix',
            'namespace': 'http://dobtor/dmn'})
        return _ET.tostring(root, pretty_print=True, xml_declaration=True,
                            encoding='UTF-8').decode('utf-8')

    def _dmn_input_entry(self, var, line):
        if var == 'amount':
            lo = line.amount_min or 0.0
            hi = line.amount_max or 0.0
            if hi and hi > 0:
                return '[%s..%s]' % (_numfmt(lo), _numfmt(hi))
            if lo and lo > 0:
                return '>= %s' % _numfmt(lo)
            return '-'
        if var == 'category':
            return '"%s"' % line.category_value if line.category_value else '-'
        if var == 'department':
            return '"%s"' % line.department_id.display_name if line.department_id else '-'
        return '-'

    def _dmn_output_entry(self, name, line):
        if name == 'resolver':
            return '"%s"' % line.resolver_type
        if name == 'level':
            return str(line.level or 1)
        if name == 'job':
            return '"%s"' % line.job_id.name if line.job_id else ''
        if name == 'users':
            names = line.user_ids.mapped('name')
            return '[%s]' % ', '.join('"%s"' % n for n in names) if names else ''
        return ''


def _numfmt(v):
    f = float(v)
    return str(int(f)) if f == int(f) else repr(f)


class BpmnAuthorityMatrixLine(models.Model):
    _name = 'bpmn.authority.matrix.line'
    _description = '核決權限表規則列'
    _order = 'sequence, id'

    matrix_id = fields.Many2one('bpmn.authority.matrix', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    name = fields.Char(string='關卡/說明', help='此規則列代表的簽核關，如「部門經理關」')

    # 條件（輸入）
    amount_min = fields.Float(string='金額 ≥', default=0.0)
    amount_max = fields.Float(string='金額 <', help='0＝無上限')
    category_value = fields.Char(string='類別 =', help='留空＝不限')
    department_id = fields.Many2one('hr.department', string='部門 =', help='留空＝不限')

    # 輸出（簽核人解析，鏡射 bpmn.role 子集）
    resolver_type = fields.Selection(
        _LINE_RESOLVERS, string='簽核人', required=True, default='department_manager')
    level = fields.Integer(string='往上層級', default=1, help='manager_level 用')
    job_id = fields.Many2one('hr.job', string='指定職位')
    user_ids = fields.Many2many('res.users', string='指定使用者')

    def _role_vals(self):
        """轉成 bpmn.role 可用的 vals（供 NewId 暫存解析）。"""
        self.ensure_one()
        vals = {
            'name': self.name or 'matrix_line',
            'resolver_type': self.resolver_type,
            'apply_substitute': False,
        }
        if self.resolver_type == 'manager_level':
            vals['level'] = max(1, self.level)
        elif self.resolver_type == 'job_position':
            vals['job_id'] = self.job_id.id
        elif self.resolver_type == 'specific_user':
            vals['user_ids'] = [Command.set(self.user_ids.ids)]
        return vals


class BpmnAuthorityMatrixPreview(models.TransientModel):
    _name = 'bpmn.authority.matrix.preview'
    _description = '核決權限表試算'

    matrix_id = fields.Many2one('bpmn.authority.matrix', required=True, ondelete='cascade')
    amount = fields.Float(string='測試金額')
    category = fields.Char(string='測試類別', help='與規則列「類別 =」相同的字串')
    department_id = fields.Many2one('hr.department', string='測試部門')
    applicant_id = fields.Many2one('res.users', string='測試申請人')
    result_html = fields.Html(string='試算結果', readonly=True, sanitize=False)

    def action_run(self):
        self.ensure_one()
        chain = self.matrix_id.preview_manual(
            self.amount, self.category, self.department_id, self.applicant_id)
        if chain:
            items = []
            for idx, (line, users) in enumerate(chain, start=1):
                names = ', '.join(users.mapped('name')) or '（解析不到簽核人）'
                items.append('<li>第 %d 關 %s：<b>%s</b></li>' % (
                    idx, line.name or '', names))
            body = '<p>依序核決鏈：</p><ol>%s</ol>' % ''.join(items)
        else:
            body = '<p class="text-danger">無命中規則 → 此單據將解析不到簽核人。</p>'
        warns = self.matrix_id._coverage_warnings()
        if warns:
            body += ('<div class="alert alert-warning mt-2">覆蓋提醒：<br/>%s</div>'
                     % '<br/>'.join(warns))
        self.result_html = body
        return {
            'type': 'ir.actions.act_window',
            'name': _('核決權限表試算'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
