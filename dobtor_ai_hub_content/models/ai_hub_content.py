# -*- coding: utf-8 -*-
"""content 模式：主控台（dobtor_corpaas_knowledge）請 AI 產生知識內容。

★ 這個模式不需要改檔案、不需要 bridge：它只讀 prompt、回一段文字。
  所以能力需求只有 `has_agent_loop`（與 website／backend 同一級），不要求
  `can_edit_files` —— 要求了反而會把可以勝任的模型排除掉。
"""
from odoo import fields, models
from odoo.addons.dobtor_ai_hub.models import ai_hub_route

# ★ 在模組載入時改 dict，而不是覆寫 `capable()`：路由器每次都讀這個全域表，
#   改表就生效，也不必跟著上游方法的簽名走。
# ☠️ 不加這一條的話 `MODE_REQUIREMENTS.get('content', ())` 是空的，等於「任何
#    模型都勝任」—— 路由會把工作派給連多回合都不會的模型，症狀是回一段
#    不完整的文字，而不是錯誤訊息。
ai_hub_route.MODE_REQUIREMENTS.setdefault('content', ('has_agent_loop',))

CONTENT = [('content', '知識內容')]

#: 預設的 prompt 上限。主控台一次送進一整個方案的功能點與情境，
#: 比面板提問（4000 字）大得多；Runner 超過 argv 上限會自動改寫成檔案。
DEFAULT_MAX_CHARS = 200000


class AiHubSession(models.Model):
    _inherit = 'ai.hub.session'

    # ★ 解除安裝時改回預設而不是刪掉：Session／Run 上記著花掉的錢，
    #   上行配額與成本上限是用它們算的，刪了等於把帳抹掉。
    mode = fields.Selection(selection_add=CONTENT,
                            ondelete={'content': 'set default'})


class AiHubRun(models.Model):
    _inherit = 'ai.hub.run'

    mode = fields.Selection(selection_add=CONTENT,
                            ondelete={'content': 'set default'})


class AiHubArtifact(models.Model):
    _inherit = 'ai.hub.artifact'

    # ☠️ 產物的型別預設取 Run 的 mode（`art.get('type') or self.mode`）。
    #    不加這個值，content 模式的 Run 只要留下任何一個檔案，登錄產物時就會
    #    當場 ValueError —— 而那發生在 Runner 回報的交易裡，Run 會停在執行中。
    type = fields.Selection(selection_add=CONTENT,
                            ondelete={'content': 'set default'})


class AiHubRouteRule(models.Model):
    _inherit = 'ai.hub.route.rule'

    # ★ 規則刪掉而不是清空：mode 空白的意思是「所有模式」，清空會讓一條只為
    #   content 寫的規則突然管到網站編輯與後台助理。
    mode = fields.Selection(selection_add=CONTENT,
                            ondelete={'content': 'cascade'})


class AiHubSource(models.Model):
    _inherit = 'ai.hub.source'

    content_enabled = fields.Boolean(
        string='允許知識內容', default=False,
        help='開啟後，持有本來源上行金鑰的主控台可以送 content 模式的工作進來。'
             '與網站編輯分開授權：知識內容不寫對方的系統，所以不需要 L2。')
    content_max_chars = fields.Integer(
        string='知識內容 prompt 上限（字元）', default=DEFAULT_MAX_CHARS,
        help='0 = 使用預設值 %s。' % DEFAULT_MAX_CHARS)

    def content_limit(self):
        self.ensure_one()
        return self.content_max_chars if self.content_max_chars > 0 else DEFAULT_MAX_CHARS
