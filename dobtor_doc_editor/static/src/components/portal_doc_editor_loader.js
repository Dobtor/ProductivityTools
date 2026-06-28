/** @odoo-module **/

/**
 * Portal Doc Editor Loader（W2-3 P0-1 最後一哩）
 * ================================================
 *
 * 目的：讓 portal user 在 /my/documents/<id> 用 canvas-editor 編輯文件。
 *
 * 做法：把 DocEditor 註冊到 Odoo 18 標準的 `public_components` registry。
 *      Odoo 啟動 frontend 時 `public_component_service` 會掃 DOM 找
 *      `<owl-component name="dobtor_doc_editor.DocEditor" props="...">`
 *      然後自動 mount（同 backend client action 機制，但走 frontend env）。
 *
 *      portal_templates.xml 的 portal_document_view 模板會放對應的
 *      <owl-component> 標籤，props 用 JSON 帶入 docId / readonly。
 *
 * Props（從 <owl-component props="..."> JSON 字串解析）：
 *   - docId (number)   ：要載入的文件 id；DocEditor.setup() 會優先取此值
 *   - readonly (bool)  ：true 時 canvas-editor 走 readonly mode，AutoSave 不啟動
 *
 * 為什麼不另寫 OWL App + mount()：
 *   public_component_service 已處理 template registry / env / app lifecycle，
 *   重造輪子只會踩坑（看 odoo/addons/web/static/src/public/public_component_service.js）。
 */

import { registry } from "@web/core/registry";
import { DocEditor } from "./doc_editor/doc_editor";

registry
    .category("public_components")
    .add("dobtor_doc_editor.DocEditor", DocEditor);
