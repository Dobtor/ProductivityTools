# -*- coding: utf-8 -*-
"""18.0.2.0.0 — 將 AI 摘要功能拆出至 bridge 模組 dobtor_ai_chatbot_meeting_minutes。

本 pre-migration 在核心升級「載入資料之前」執行，把所有被搬走的記錄
（seed 資料、模型、欄位、視圖、選單、權限、record rule）在 ir_model_data 中的
歸屬模組由 dobtor_meeting_minutes 改記到 dobtor_ai_chatbot_meeting_minutes。

效果：
- 核心升級結束時的孤兒清理（_process_end）不會再認定這些是「核心的孤兒」而刪除，
  因此不會掉欄位（meeting_summary 內容）、不會 drop note.summary.* 資料表
  （歷史 log 與使用者自建範本得以保留）。
- 之後 bridge 安裝、以「相同 xmlid」載入自己的資料時，Odoo 會就地更新這些
  既有 ir_model_data 列（同一 DB id、同一目標記錄），而非建立重複記錄，
  故 res.company 先前選的 chatbot / 自訂範本 FK 也保持有效。

純 UPDATE，不刪任何記錄；屬移轉模組歸屬的標準 Odoo 作法。
若 bridge 不在 addons path（罕見），這些記錄會暫時掛在未安裝模組名下而保持不動，
仍不會遺失。
"""

OLD_MODULE = 'dobtor_meeting_minutes'
NEW_MODULE = 'dobtor_ai_chatbot_meeting_minutes'

# 被搬到 bridge 的 ir_model_data 名稱（xmlid 去除模組前綴）
MOVED_XMLIDS = [
    # ---- seed 資料（noupdate）----
    'chatbot_meeting_summary',
    'summary_template_formal',
    'summary_template_brainstorm',
    'summary_template_standup',
    'summary_template_project',
    # ---- 模型 ----
    'model_note_summary_template',
    'model_note_summary_log',
    # ---- 欄位（搬到 bridge，避免欄位被刪→掉資料）----
    'field_note_note__meeting_summary',
    'field_note_note__summary_state',
    'field_note_note__summary_worker_pid',
    'field_note_note__summary_worker_started_at',
    'field_res_company__meeting_summary_chatbot_id',
    'field_res_company__summary_prompt_preset',
    'field_res_company__summary_prompt_template_id',
    'field_res_config_settings__meeting_summary_chatbot_id',
    'field_res_config_settings__summary_prompt_preset',
    'field_res_config_settings__summary_prompt_template_id',
    # ---- 視圖 / action ----
    'view_note_summary_template_list',
    'view_note_summary_template_form',
    'view_note_summary_template_search',
    'action_note_summary_template',
    'view_note_summary_log_list',
    'view_note_summary_log_form',
    'view_note_summary_log_search',
    'view_note_summary_log_pivot',
    'action_note_summary_log',
    # ---- 選單 ----
    'menu_meeting_minutes_summary_templates',
    'menu_meeting_minutes_summary_logs',
    # ---- 權限 ----
    'access_note_summary_template_user',
    'access_note_summary_template_manager',
    'access_note_summary_log_user',
    'access_note_summary_log_manager',
    # ---- record rule ----
    'note_summary_log_rule_user',
    'note_summary_log_rule_manager',
]


def migrate(cr, version):
    if not version:
        # 全新安裝不會帶 version；無需 re-home
        return
    cr.execute(
        """
        UPDATE ir_model_data
           SET module = %s
         WHERE module = %s
           AND name IN %s
        """,
        (NEW_MODULE, OLD_MODULE, tuple(MOVED_XMLIDS)),
    )
