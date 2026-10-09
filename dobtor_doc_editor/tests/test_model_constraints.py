# -*- coding: utf-8 -*-
r"""compute 與 constraint 的接線——稽核尺 4（2026-10-09）。

☠️ 為什麼需要機械守衛：查過 Odoo 18 的原始碼（`odoo/models.py`）——

    `_constraint_methods`（905-925 行）對 `@api.constrains('打錯的名字')`
    只印一行 `_logger.warning("… @constrains parameter %r is not a field name")`，
    **然後照樣把方法註冊進去**。

    而 `_validate_fields`（1622 行）只在「這次寫入的欄位名」與
    `check._constrains` **有交集**時才呼叫它：

        if (not field_names.isdisjoint(check._constrains) ...): check(self)

    參數打錯字 → 永遠沒有交集 → **這條業務規則永遠不執行**。
    唯一的訊號是 registry 載入時那行 warning，而沒有人在看那個。

這跟 `ir.cron` 的 `code` 字串是同一個形狀（見 test_cron_wiring.py）：
程式碼存在、甚至「註冊成功」，而它的效果到不了任何地方。

本模組有 3 條 `@api.constrains`（報表的範本模型相符、範本的版面鏈、
範本欄位的簽核人歸屬），全部是「壞資料靜默通過」型的規則。

另一則驗 `@api.depends`：Odoo 對 depends 的無效路徑是在 setup 期就會丟例外，
所以理論上裝得起來就代表沒問題——這一則是**明確記錄那個前提**，
哪天 Odoo 改成只警告（跟 constrains 一樣），它會紅。
"""
from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged

MODULE = 'dobtor_doc_editor'


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestModelConstraintWiring(TransactionCase):
    """本模組每個 model 的 constrains / depends 都要指到真欄位。"""

    def _own_models(self):
        """本模組自己定義的 model（_name 以 doc. 開頭的具體 model）。"""
        out = []
        for name in self.env.registry.models:
            model = self.env[name]
            if not name.startswith('doc.'):
                continue
            if model._abstract:
                continue
            out.append(model)
        return out

    def test_module_defines_some_models(self):
        """先確認真的撈到 model——撈不到的話底下每一則都會空轉過關。"""
        models = self._own_models()
        self.assertGreaterEqual(
            len(models), 8,
            '只撈到 %d 個 doc.* model（%s）。命名規則若改了，'
            '請同步改 _own_models()——不要讓它靜默撈到 0 個然後過關。'
            % (len(models), [m._name for m in models]))

    def test_every_constrains_parameter_is_a_real_writeable_field(self):
        """`@api.constrains('x')` 的 x 必須是真欄位，而且是可寫的。

        不是真欄位 → `_validate_fields` 永遠不會呼叫它（永不執行的規則）。
        不可寫（非 store 且無 inverse）→ Odoo 自己也會警告，同樣永不觸發。
        """
        broken = []
        for model in self._own_models():
            for check in model._constraint_methods:
                for param in check._constrains:
                    field = model._fields.get(param)
                    if field is None:
                        broken.append(
                            '%s.%s：@constrains(%r) 不是欄位 → 這條約束**永遠不會執行**'
                            % (model._name, check.__name__, param))
                    elif not (field.store or field.inverse or field.inherited):
                        broken.append(
                            '%s.%s：@constrains(%r) 不可寫（非 store 且無 inverse）'
                            '→ 寫入時不會觸發'
                            % (model._name, check.__name__, param))
        self.assertFalse(
            broken,
            '下列約束的接線壞了（Odoo 只會印一行 warning，不會失敗）：\n  %s'
            % '\n  '.join(broken))

    def test_every_constrains_is_reachable_from_a_written_field(self):
        """每條約束至少要有一個參數是「使用者／程式會寫到」的欄位。

        ☠️ 這一則跟上一則不同：上一則擋「參數不是欄位」，這一則擋
        「參數是欄位、但它是唯讀 compute，所以沒有人會寫它」
        ——那種約束同樣永遠不觸發，而 Odoo 連 warning 都不會印
        （field.store 為 True 的 compute 欄位會通過上一則的檢查）。
        """
        broken = []
        for model in self._own_models():
            for check in model._constraint_methods:
                writable = [
                    p for p in check._constrains
                    if (f := model._fields.get(p)) is not None
                    and not (f.compute and f.readonly and not f.inverse)
                ]
                if check._constrains and not writable:
                    broken.append(
                        '%s.%s：@constrains%r 的每一個參數都是唯讀 compute'
                        '——沒有人會寫它們，所以這條約束不會觸發'
                        % (model._name, check.__name__, tuple(check._constrains)))
        self.assertFalse(broken, '下列約束觸發不到：\n  %s' % '\n  '.join(broken))

    def test_every_computed_field_depends_resolves(self):
        """`@api.depends` 的每個路徑都解析得到。

        Odoo 目前在 registry setup 期就會對無效的 depends 丟例外，所以「裝得
        起來」本身就是證明。這一則**明確記錄那個前提**：哪天 Odoo 改成只印
        warning（跟 constrains 一樣），它會在這裡紅出來而不是靜默失效。
        """
        bad = []
        for model in self._own_models():
            for fname, field in model._fields.items():
                if not field.compute or not getattr(field, 'depends', None):
                    continue
                for path in field.depends:
                    cur = model
                    for part in path.split('.'):
                        f = cur._fields.get(part)
                        if f is None:
                            bad.append('%s.%s 的 depends %r：%r 不存在於 %s'
                                       % (model._name, fname, path, part, cur._name))
                            break
                        cur = self.env[f.comodel_name] if f.relational else cur
        self.assertFalse(bad, '下列 depends 解析不到：\n  %s' % '\n  '.join(bad))


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestConstraintBehaviour(TransactionCase):
    r"""三條 `@api.constrains` 的**行為**——接線對不代表邏輯對。

    ☠️ 上面那組機械守衛擋的是「約束永遠不執行」。這一組擋的是另一件事：
    約束執行了，但判斷寫反了、或範圍抓錯了。兩者都會讓壞資料通過，而症狀
    一模一樣（存檔成功、後果在別的地方才出現）。

    這三條都是「壞資料靜默通過」型的規則：
      doc.report       範本的適用模型與報表模型不一致 → 變數全部取不到值
                       **而且求值失敗是靜默的（回空字串）**
      doc.template     外框再掛外框 → 追頁首要追好幾層，成環會無限遞迴
      doc.template.field  簽核人屬於別的範本 → 簽核欄位對不到人
    """

    def _template(self, **vals):
        base = {
            'name': '約束測試範本',
            'role': 'content',
            'model_id': self.env['ir.model']._get('res.partner').id,
        }
        base.update(vals)
        return self.env['doc.template'].sudo().create(base)

    # ── doc.template：外框不可再掛外框 ────────────────────────────────

    def test_layout_template_cannot_have_a_layout(self):
        """外框範本自己再指定外框 → 必須被擋。"""
        layout = self._template(name='外框 A', role='layout')
        with self.assertRaises(ValidationError):
            self._template(name='外框 B', role='layout', layout_id=layout.id)

    def test_layout_id_must_point_at_a_layout_template(self):
        """把一般範本當外框用 → 必須被擋。"""
        content = self._template(name='一般範本')
        with self.assertRaises(ValidationError):
            self._template(name='掛錯外框的範本', layout_id=content.id)

    def test_content_template_with_a_real_layout_is_allowed(self):
        """合法組合不可以被誤擋（沒有這一則，上面兩則可能是靠「全部擋掉」過關）。"""
        layout = self._template(name='外框 C', role='layout')
        ok = self._template(name='正常掛外框', layout_id=layout.id)
        self.assertEqual(ok.layout_id, layout)

    # ── doc.template.field：簽核人必須屬於同一個範本 ──────────────────

    def test_signer_from_another_template_is_rejected(self):
        """簽核人屬於別的範本 → 必須被擋。"""
        tpl_a, tpl_b = self._template(name='範本 A'), self._template(name='範本 B')
        signer_b = self.env['doc.template.signer'].sudo().create({
            'template_id': tpl_b.id, 'name': 'B 的簽核人',
        })
        with self.assertRaises(ValidationError):
            self.env['doc.template.field'].sudo().create({
                'template_id': tpl_a.id,
                'signer_id': signer_b.id,
                'field_type': 'text',
                'layout_mode': 'inline',
            })

    def test_signer_from_the_same_template_is_allowed(self):
        """同一個範本的簽核人不可以被誤擋。"""
        tpl = self._template(name='範本 C')
        signer = self.env['doc.template.signer'].sudo().create({
            'template_id': tpl.id, 'name': 'C 的簽核人',
        })
        field = self.env['doc.template.field'].sudo().create({
            'template_id': tpl.id, 'signer_id': signer.id,
            'field_type': 'text', 'layout_mode': 'inline',
        })
        self.assertEqual(field.signer_id, signer)

    # ── doc.report：範本模型與報表模型必須一致 ────────────────────────

    def _report_action(self, model, suffix):
        """建一個印 `model` 的原生報表動作。

        ☠️ doc.report.report_model 是 `related='report_id.model'` 的 stored
        readonly 欄位（註解寫「由報表定義決定，不可自行指定」），所以不能直接
        塞字串——第一版那樣寫，錯誤是 report_id 的 not-null 違反，
        跟想驗的約束完全無關。
        """
        return self.env['ir.actions.report'].sudo().create({
            'name': '約束測試報表 %s' % suffix,
            'model': model,
            'report_type': 'qweb-pdf',
            'report_name': 'dobtor_doc_editor.constraint_probe_%s' % suffix,
        })

    def test_report_rejects_template_with_mismatched_model(self):
        """範本印 res.partner、報表印 res.users → 必須被擋。

        ☠️ 這一條特別重要：不一致時藥丸的欄位路徑對不上來源記錄，
        **求值失敗是靜默的（回空字串）**，所以使用者會拿到一份看起來正常
        但欄位全空的文件。必須在設定階段擋下來。
        """
        tpl = self._template(name='印 partner 的範本')
        with self.assertRaises(UserError):
            self.env['doc.report'].sudo().create({
                'name': '模型不一致的綁定',
                'template_id': tpl.id,
                'report_id': self._report_action('res.users', 'mismatch').id,
            })

    def test_report_accepts_matching_model(self):
        """模型一致時不可以被誤擋。"""
        tpl = self._template(name='印 partner 的範本 2')
        rep = self.env['doc.report'].sudo().create({
            'name': '模型一致的綁定',
            'template_id': tpl.id,
            'report_id': self._report_action('res.partner', 'match').id,
        })
        self.assertEqual(rep.report_model, 'res.partner')
