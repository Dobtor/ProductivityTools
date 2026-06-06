from odoo import http
from odoo.http import request


class DobtorBpmnController(http.Controller):

    @http.route('/dobtor_bpmn/node_types', type='json', auth='user')
    def node_types(self):
        """回傳已註冊節點型別（核心標準 + 擴充注入），供前端調色盤/屬性面板動態渲染。"""
        return request.env['bpmn.node.type.registry']._get_node_types()
