# -*- coding: utf-8 -*-
"""簽核人解析引擎 — DESIGN.md §3.3。

bpmn.role.resolve(instance) 回傳 res.users recordset（可能多人=會簽）。
所有 resolver_type 皆以 Odoo HR 既有關係表達（parent_id / department_id.manager_id /
hr.job / 單據欄位 / safe_eval 運算式），並套用職務代理（_apply_substitutes）。
"""
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)

# safe_eval 允許往上爬的最大層數，避免惡意/錯誤資料造成無窮迴圈
_MAX_MANAGER_LEVEL = 20


class BpmnRole(models.Model):
    _name = 'bpmn.role'
    _description = 'BPMN 簽核角色 / 簽核人解析來源'
    _order = 'sequence, id'

    name = fields.Char(string='角色名稱', required=True)
    sequence = fields.Integer(default=10)
    process_id = fields.Many2one(
        'bpmn.executable.process', string='所屬流程',
        ondelete='cascade', index=True)

    resolver_type = fields.Selection([
        ('direct_manager', '申請人直屬主管 (employee.parent_id)'),
        ('manager_level', '往上第 N 級主管'),
        ('department_manager', '申請人部門經理'),
        ('department_specific', '指定部門之經理'),
        ('job_position', '指定職位'),
        ('specific_user', '指定使用者'),
        ('group', '指定權限群組'),
        ('field_on_record', '取單據上的欄位'),
        ('expression', 'Python 運算式 (safe_eval)'),
        ('authority_matrix', '核決權限表（決策矩陣）'),
        ('dmn_decision', 'DMN 決策'),
    ], string='解析方式', required=True, default='direct_manager')

    level = fields.Integer(string='往上層級', default=1,
                           help='manager_level 用：往上爬幾級主管')
    specific_department_id = fields.Many2one('hr.department', string='指定部門')
    job_id = fields.Many2one('hr.job', string='指定職位')
    user_ids = fields.Many2many('res.users', string='指定使用者')
    group_id = fields.Many2one('res.groups', string='指定權限群組')
    record_field = fields.Char(string='單據欄位名稱',
                               help="field_on_record 用，如 'user_id'")
    expression = fields.Text(
        string='Python 運算式',
        help="可用變數：record（單據）、applicant（申請人 res.users）、"
             "employee（申請人 hr.employee）、env。需回傳 res.users recordset。")
    matrix_id = fields.Many2one(
        'bpmn.authority.matrix', string='核決權限表',
        help='authority_matrix 用：依單據（金額/類別/部門）決定簽核人')
    decision_id = fields.Many2one(
        'dmn.decision', string='DMN 決策',
        help='dmn_decision 用：依 DMN 決策表輸出 approver 鏈決定簽核人')

    apply_substitute = fields.Boolean(string='啟用職務代理人', default=True)

    # ------------------------------------------------------------------
    # 校驗
    # ------------------------------------------------------------------
    @api.constrains('resolver_type', 'level')
    def _check_level(self):
        for role in self:
            if role.resolver_type == 'manager_level':
                if role.level < 1 or role.level > _MAX_MANAGER_LEVEL:
                    raise ValidationError(_(
                        '角色「%(name)s」往上層級必須介於 1 與 %(max)s 之間。',
                        name=role.name, max=_MAX_MANAGER_LEVEL))

    # ------------------------------------------------------------------
    # 解析核心
    # ------------------------------------------------------------------
    def resolve(self, instance):
        """回傳 res.users recordset（去重）。

        :param instance: bpmn.process.instance（提供 applicant_user_id / 單據）
        """
        self.ensure_one()
        Users = self.env['res.users']
        applicant = instance.applicant_user_id
        employee = applicant.employee_id if applicant else self.env['hr.employee']
        rtype = self.resolver_type
        users = Users

        if rtype == 'direct_manager':
            users = employee.parent_id.user_id

        elif rtype == 'manager_level':
            emp = employee
            for _i in range(max(1, self.level)):
                emp = emp.parent_id
                if not emp:
                    break
            users = emp.user_id

        elif rtype == 'department_manager':
            users = employee.department_id.manager_id.user_id

        elif rtype == 'department_specific':
            users = self.specific_department_id.manager_id.user_id

        elif rtype == 'job_position':
            # hr.job 上對應職位的所有在職員工 → 其 user
            emps = self.env['hr.employee'].search([('job_id', '=', self.job_id.id)])
            users = emps.mapped('user_id')

        elif rtype == 'specific_user':
            users = self.user_ids

        elif rtype == 'group':
            users = self.group_id.users

        elif rtype == 'field_on_record':
            users = self._resolve_field_on_record(instance)

        elif rtype == 'expression':
            users = self._resolve_expression(instance)

        elif rtype == 'authority_matrix':
            users = self._resolve_authority_matrix(instance)

        elif rtype == 'dmn_decision':
            users = self._resolve_dmn_decision(instance)

        # 職務代理替換（代簽核）— 僅在能力開啟時生效
        if self.apply_substitute and self.env.company._bpmn_feature_enabled('delegation'):
            users = self._apply_substitutes(users, instance)

        # 去重 + 過濾無效
        return users.filtered(lambda u: u.active) if users else Users

    def _resolve_authority_matrix(self, instance):
        """核決權限表：依單據評估決策表，回傳「命中鏈」簽核人（依規則列序，去重）。

        引擎對 authority_matrix 節點強制走 sequential（見 _enter_user_task），
        故此處的順序＝實際逐關核決順序（直屬→部門經理→財務長…）。
        """
        Users = self.env['res.users']
        if not self.matrix_id:
            return Users
        record = instance._get_res_record() if instance else False
        applicant = instance.applicant_user_id if instance else False
        users = Users
        for _line, line_users in self.matrix_id.resolve_approvers(record, applicant):
            users |= line_users
        return users

    def _resolve_dmn_decision(self, instance):
        """DMN 決策（approver 慣例輸出）：求值決策表得依序鏈，逐項解析簽核人（去重）。

        分階逐關順序由引擎以 phase 控制（見 process_instance._enter_decision_node），
        此處 union 全鏈簽核人即可。
        """
        Users = self.env['res.users']
        if not self.decision_id:
            return Users
        defn = self.decision_id.definitions_id
        record = instance._get_res_record() if instance else False
        applicant = instance.applicant_user_id if instance else False
        users = Users
        for item in defn.resolve_approver_chain(
                self.decision_id.dmn_id, record, applicant, instance):
            users |= self._resolve_chain_item(item, instance)
        return users

    def _resolve_chain_item(self, item, instance):
        """把單一 approver dict 轉成 res.users（以暫時 role 重用既有解析）。"""
        vals = {
            'name': 'dmn-chain',
            'resolver_type': item.get('resolver') or 'direct_manager',
            'level': item.get('level') or 1,
            'apply_substitute': False,
        }
        if vals['resolver_type'] == 'job_position' and item.get('job'):
            job = self.env['hr.job'].search([('name', '=', item['job'])], limit=1)
            vals['job_id'] = job.id
        if vals['resolver_type'] == 'specific_user' and item.get('users'):
            ids = self._coerce_user_ids(item['users'])
            if ids:
                vals['user_ids'] = [(6, 0, ids)]
        role = self.env['bpmn.role'].new(vals)
        return role.resolve(instance)

    def _coerce_user_ids(self, raw):
        """approver 輸出的 users 可能為 id 串列或姓名串列 → res.users ids。"""
        if not isinstance(raw, (list, tuple)):
            raw = [raw]
        ids, names = [], []
        for v in raw:
            if isinstance(v, int):
                ids.append(v)
            elif isinstance(v, str) and v.strip():
                names.append(v.strip())
        if names:
            ids += self.env['res.users'].search([('name', 'in', names)]).ids
        return list(set(ids))

    def resolve_preview(self, applicant_user_id, res_model=False, res_id=False):
        """dry-run 預覽：給定假申請人（與選用單據），算出此角色會解析出的簽核人。
        以 transient 實例重用 resolve()，不建立真實流程實例。"""
        self.ensure_one()
        inst = self.env['bpmn.process.instance'].new({
            'applicant_user_id': applicant_user_id or False,
            'res_model': res_model or False,
            'res_id': res_id or 0,
        })
        try:
            return self.resolve(inst)
        except Exception:  # noqa: BLE001 預覽不可因單一角色設定錯誤而中斷
            _logger.exception('resolve_preview 失敗 (role=%s)', self.id)
            return self.env['res.users']

    def _resolve_field_on_record(self, instance):
        """取單據上的欄位值，轉成 res.users。支援 res.users / hr.employee / partner→user。"""
        Users = self.env['res.users']
        record = instance._get_res_record()
        if not record or not self.record_field:
            return Users
        if self.record_field not in record._fields:
            _logger.warning('bpmn.role: 單據 %s 無欄位 %s', record._name, self.record_field)
            return Users
        value = record[self.record_field]
        if not value:
            return Users
        if value._name == 'res.users':
            return value
        if value._name == 'hr.employee':
            return value.user_id
        if value._name == 'res.partner':
            return self.env['res.users'].search([('partner_id', 'in', value.ids)])
        return Users

    def _resolve_expression(self, instance):
        """safe_eval 白名單運算式，回傳 res.users。"""
        Users = self.env['res.users']
        if not self.expression:
            return Users
        record = instance._get_res_record()
        applicant = instance.applicant_user_id
        ctx = {
            'record': record,
            'applicant': applicant,
            'employee': applicant.employee_id if applicant else False,
            'env': self.env,
            'users': Users,
        }
        try:
            result = safe_eval(self.expression, ctx)
        except Exception as exc:
            raise UserError(_(
                '角色「%(name)s」的運算式執行失敗：%(err)s',
                name=self.name, err=exc))
        if result is None or result is False:
            return Users
        if isinstance(result, models.BaseModel) and result._name == 'res.users':
            return result
        raise UserError(_(
            '角色「%(name)s」運算式必須回傳 res.users recordset。', name=self.name))

    def _apply_substitutes(self, users, instance):
        """套用職務代理：解析出的人若在代理區間 → 加上/改派代理人。

        交由 bpmn.delegation 解析；回傳替換後的 recordset。
        """
        if not users:
            return users
        Delegation = self.env['bpmn.delegation']
        definition = instance.process_id if instance else self.env['bpmn.executable.process']
        return Delegation._substitute_users(users, definition)
