# Portal 整合設計（W2-3 P0-1）

**狀態**：W2-3 補強衝刺實作  
**對應漏項**：P0-1 — Portal user 完全無法使用編輯器  
**完成日期**：2026-05-06

---

## 1. 為什麼需要

`controllers/doc_controller.py` 既有 12 條路由全為 `auth='user'`，無 portal 支援。但 ChienYi 主要客群（承包商、現場人員、業主代表）多為 portal user，無法存取編輯器 = 模組失去最大價值。

## 2. 兩層權限模型

| 角色 | Odoo 群組 | 可做 |
|---|---|---|
| **內部編輯者** | `group_doc_editor`（implies `base.group_user`） | 建立、編輯、刪除自己的文件；讀範本 |
| **內部管理者** | `group_doc_manager`（implies `group_doc_editor`） | 全局存取所有文件與範本 |
| **Portal 協作者** | `group_doc_portal`（implies `base.group_portal`） | 只能讀寫**自己被加為 collaborator 的文件**；不能建立、不能刪除 |

關鍵差異：
- portal user 由 internal user 主動「邀請」（加入 `collaborator_ids`）後才能存取
- portal user 看不到任何文件列表上沒列出的東西（ir.rule 強制過濾）
- portal user 不能 escalate 為 internal user

## 3. 變更檔案清單

| 檔案 | 變更 |
|---|---|
| `security/doc_groups.xml` | 新增 `group_doc_portal` |
| `security/ir.model.access.csv` | 新增 3 條 portal ACL（doc.document/template/render_mixin 各一） |
| `security/doc_security.xml` | 新增 `rule_doc_document_portal`：domain `[('collaborator_ids', 'in', [user.id])]` |
| `controllers/__init__.py` | import portal module |
| `controllers/portal.py`（**新增**） | `DobtorDocPortal(CustomerPortal)`：`/my/documents` 列表、`/my/documents/<id>` 編輯 |
| `views/portal_templates.xml`（**新增**） | 4 個模板：home_documents（/my 入口）、breadcrumbs、my_documents（列表）、document_view（編輯） |
| `__manifest__.py` | depends 加 `portal`；data 加 `views/portal_templates.xml` |

## 4. 路由清單

| 路由 | 方法 | auth | 用途 |
|---|---|---|---|
| `/my/documents` | GET | user | 文件列表（portal + internal user 共用） |
| `/my/documents/page/<int:page>` | GET | user | 列表分頁 |
| `/my/documents/<int:doc_id>` | GET | user | 單份文件檢視 / 編輯 |

既有的 12 條 `/dobtor_doc/*` JSON 路由**不動**：
- portal user 已可呼叫（auth='user' 涵蓋 internal + portal）
- 實際讀寫由 `doc.check_access_rule('write')` 二次驗證
- ir.rule 確保 portal user 寫入時也只能寫自己被加為協作者的文件

## 5. 與 ChienYi 的關係

本 W2-3 的 portal 整合**不依賴 construction_portal 的 cy_pc_layout**，沿用標準 Odoo `portal.portal_layout`，確保模組通用性。

ChienYi 的特化整合（讓承包商透過 cy_pc_layout 風格的介面進入 dobtor 文件）將在 **W5-6 P1-2** 透過 `doc.linked.mixin` 處理，跨模組建立關聯後再決定是否覆蓋 portal 模板。

## 6. 邀請流程（手動，由 internal user 操作）

1. Internal user 在後台 `doc.document` 列表選一份文件
2. 編輯 → 「協作者」欄位 → 加入想授權的 portal user
3. portal user 下次登入即可在 `/my/documents` 看到這份文件
4. （未來 W5-6 整合 ChienYi 後可自動化：建立監造會議記錄時自動加會議出席者為協作者）

## 7. 安全考量

- **CSRF**：所有 portal HTTP 路由都有 `website=True`，標準 Odoo CSRF 機制；既有 12 條 JSON-RPC 路由本身有 session 驗證
- **公司隔離**：`rule_doc_document_company` 對 portal user **不**生效（portal user 通常隸屬一家公司，但 record 的 company_id 可能跨公司）。可改用 `partner.commercial_partner_id` 隔離 → 留待 W5-6 與 ChienYi 整合時統一設計
- **access_token 公開分享**：本次未實作；如未來要支援「不登入也能看文件」需在 `doc.document` 加 `access_token` 欄位 + `_compute_access_url()` + 模板加 token 校驗
- **IDOR 攻擊**：portal user 嘗試直接訪問 `/my/documents/999`（其他人的文件）會被 ir.rule + `check_access_rule` 雙重攔截，回 404

## 8. 後續整合點

| Sprint | 工作 | 關係 |
|---|---|---|
| W4 | OWL 升級 doc_editor.js | 升級後 `portal_document_view` template 內的 mount point 才能掛實際編輯器 |
| W5-6 | doc.linked.mixin | ChienYi 模型可自動建立文件 + 自動加協作者 |
| W7-8 | 版本管理 UI | portal user 也能看版本歷史（受 ir.rule 限制） |
| W9-10 | Python 測試 `tests/test_security.py` | 驗證 portal user 無法 IDOR、無法 escalate、無法 unlink |

## 9. 驗收條件

- [ ] portal user 登入後 `/my` 首頁能看到「文件」入口卡與計數
- [ ] 點入後看到列表，**只**列出自己被加為 collaborator 的文件
- [ ] 點任一文件可進編輯頁
- [ ] 直接訪問 `/my/documents/<別人的 id>` → 404 / 重導向 `/my`
- [ ] portal user 沒有任何 UI 入口去建立新文件（ACL 鎖死）
- [ ] internal user 走 `/my/documents` 也能看到自己的文件（向下相容）

---

**附註**：此設計檔對應規劃文件 `dobtor_doc_editor_高保真匯入開發規劃.md` 的 §5.5b Phase 4.5 P0-1，與 plan `d-work-doc-editor-pure-duckling.md` 的 W2-3 段。
