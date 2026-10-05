# -*- coding: utf-8 -*-
"""說明主機需要的主機元件：中文字型、截圖映像（掛在 PAAS 的主機元件目錄上）。

☠️ 兩個實機踩過、而且都不會報錯的坑，就是這一層存在的理由：
  · 主機沒有中文字型 → 截圖流程照跑，中文全是方框；
  · 官方 mcr playwright/python 映像只有瀏覽器、沒有 playwright Python 套件 →
    截圖程式一啟動就 ModuleNotFoundError，控制台只看到「empty file」。
"""
from odoo import _, api, models

#: 截圖映像：官方映像＋同版本的 playwright 套件（版本要與瀏覽器一致）
SHOOTER_DOCKERFILE = (
    'FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy\n'
    'RUN pip install --no-cache-dir playwright==1.48.0\n')


class ServerKnowledgeComponents(models.Model):
    _inherit = 'infrastructure.server'

    @api.model
    def _host_component_catalog(self):
        cat = super()._host_component_catalog()
        cat['kb_shooter'] = {
            'name': _('截圖映像（Playwright＋playwright 套件）'), 'kind': 'docker_build',
            'repo': 'corpaas/kb-shooter', 'version': '1.48.0',
            'dockerfile': SHOOTER_DOCKERFILE, 'size_gb': 2.5,
            'after_install': '_kb_shooter_installed'}
        return cat

    def _knowledge_is_doc_server(self):
        self.ensure_one()
        sid = self.env['ir.config_parameter'].sudo().get_param('corpaas_knowledge.doc_server_id')
        return bool(sid) and str(sid).isdigit() and int(sid) == self.id

    def _host_component_requirements(self):
        req = super()._host_component_requirements()
        if self._knowledge_is_doc_server():
            req['cjk_fonts'] = _('說明主機：沒有中文字型，截圖裡的中文全是方框')
            req['kb_shooter'] = _('說明主機：操作說明的截圖容器')
        return req

    def _kb_shooter_installed(self, tag):
        """說明主機的截圖映像建好後，方案知識改用這個標籤。"""
        if self._knowledge_is_doc_server():
            self.env['ir.config_parameter'].sudo().set_param(
                'corpaas_knowledge.playwright_image', tag)
        return True

    def _knowledge_missing_components(self):
        """說明主機缺的必要元件名稱（自我檢查失敗時提示用；只讀，檢查失敗回空）。"""
        self.ensure_one()
        try:
            self._host_components_check(['cjk_fonts', 'kb_shooter'])
        except Exception:  # noqa: BLE001 — 提示用，不影響自我檢查本身
            return []
        return self.host_component_ids.filtered(
            lambda c: c.key in ('cjk_fonts', 'kb_shooter') and c.state != 'installed'
        ).mapped('name')
