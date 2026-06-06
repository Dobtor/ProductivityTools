import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """模組升級至 18.0.1.1.0：為缺少預覽 svg 的設計圖（多為匯入檔）由 XML 補產縮圖。"""
    env = api.Environment(cr, SUPERUSER_ID, {})
    Diagram = env['bpmn.diagram']
    diagrams = Diagram.search([
        '|', ('svg', '=', False), ('svg', '=', ''),
        ('xml', '!=', False),
    ])
    if not diagrams:
        return
    n = diagrams._ensure_preview_svg(force=False)
    _logger.info('dobtor_bpmn 升級：為 %s/%s 張設計圖補產預覽縮圖',
                 n, len(diagrams))
