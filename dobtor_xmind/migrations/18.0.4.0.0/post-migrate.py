# -*- coding: utf-8 -*-
"""18.0.4.0.0：專案鎖的資料回填。

全程只用 SQL 改 xmind_workbook —— **不碰任何 project.task / project.project**。

1. 重算 project_locked：同步過（xmind_last_sync）或有主題連到任務。
2. project_created_from_map：只在「看起來確實是由這張圖建立的專案」時為 True ——
   專案建立時間在工作簿第一次同步的 10 分鐘內、工作簿比專案早建立（排除由專案
   反向建立的心智圖）、且專案名稱等於第一張分頁的中心主題。其餘一律 False（＝同步不再改專案
   名稱，較保守）。
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    # 1. 專案鎖
    cr.execute("""
        UPDATE xmind_workbook w
           SET project_locked = (
                w.xmind_last_sync IS NOT NULL
                OR EXISTS (
                    SELECT 1 FROM xmind_topic t
                      JOIN xmind_sheet s ON s.id = t.sheet_id
                     WHERE s.workbook_id = w.id AND t.task_id IS NOT NULL))
    """)

    # 2. 專案是否由這張圖建立
    cr.execute("UPDATE xmind_workbook SET project_created_from_map = FALSE")
    cr.execute("""
        WITH first_sync AS (
            SELECT w.id AS workbook_id,
                   COALESCE(
                       (SELECT MIN(tk.create_date)
                          FROM project_task tk
                          JOIN xmind_topic t ON t.task_id = tk.id
                          JOIN xmind_sheet s ON s.id = t.sheet_id
                         WHERE s.workbook_id = w.id AND tk.project_id = w.project_id),
                       w.xmind_last_sync) AS ts
              FROM xmind_workbook w
             WHERE w.project_id IS NOT NULL
        ),
        central AS (
            SELECT DISTINCT ON (s.workbook_id) s.workbook_id, t.title
              FROM xmind_sheet s
              JOIN xmind_topic t ON t.sheet_id = s.id AND t.parent_id IS NULL
             ORDER BY s.workbook_id, s.sequence NULLS LAST, s.id, t.sequence, t.id
        )
        UPDATE xmind_workbook w
           SET project_created_from_map = TRUE
          FROM first_sync f, central c, project_project p
         WHERE f.workbook_id = w.id AND c.workbook_id = w.id AND p.id = w.project_id
           AND f.ts IS NOT NULL
           AND p.create_date BETWEEN f.ts - INTERVAL '10 minutes' AND f.ts + INTERVAL '10 minutes'
           -- 圖先存在、專案後建立（由專案反向建立的心智圖則相反）
           AND w.create_date < p.create_date
           AND (p.name->>'en_US' = c.title
                OR EXISTS (SELECT 1 FROM jsonb_each_text(p.name) n WHERE n.value = c.title))
    """)
    cr.execute("SELECT count(*) FILTER (WHERE project_locked), "
               "count(*) FILTER (WHERE project_created_from_map), count(*) FROM xmind_workbook")
    locked, from_map, total = cr.fetchone()
    _logger.info("dobtor_xmind 18.0.4.0.0: %s workbooks, %s locked, %s with map-created project",
                 total, locked, from_map)
