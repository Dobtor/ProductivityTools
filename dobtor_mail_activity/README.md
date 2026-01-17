# 生產力工具 (Productivity Tool)

## 概述

`dobtor_mail_activity` 是一個整合待辦管理、筆記本、週報告與效率分析的完整生產力管理系統，專為 Odoo 18 設計。

## 功能特色

### 待辦管理
- **封存機制**：完成/取消待辦時封存而非刪除，保留完整歷史
- **排程系統**：支援週計畫與多週預排功能
- **優先級管理**：時間性（緊急/標準/彈性）與重要性標記
- **工時追蹤**：預估與實際工時記錄，整合 hr_timesheet
- **轉移功能**：支援待辦在不同文件間轉移
- **指派變更追蹤**：完整記錄指派歷史

### 筆記本功能
- **自建 note 模組**：替代 Odoo 18 已移除的 note 模組
- **看板管理**：支援個人化的階段設定
- **標籤分類**：階層式標籤管理
- **待辦整合**：筆記可關聯多個待辦

### 週報告功能
- **週計畫快照**：記錄每週開始時的計畫狀態
- **執行回顧**：週末自動統計執行結果
- **差異分析**：計畫 vs 實際的差異追蹤

### 效率分析
- **個人指標**：完成率、準確度、延期率等
- **團隊分析**：跨用戶效率比較
- **儀表板**：Pivot 與 Graph 視圖

## 技術規格

### 依賴模組
- `mail`
- `hr_timesheet`
- `hr`
- `project`
- `crm`

### 模型清單

| 模型 | 說明 |
|------|------|
| `mail.activity` | 待辦擴展 |
| `mail.activity.type` | 待辦類型擴展 |
| `mail.activity.assignment.history` | 指派歷史 |
| `mail.activity.postpone.history` | 延期歷史 |
| `mail.activity.transfer.config` | 轉移目標配置 |
| `note.note` | 筆記本 |
| `note.stage` | 筆記階段 |
| `note.tag` | 筆記標籤 |
| `weekly.report` | 週報告 |
| `weekly.report.snapshot.line` | 計畫快照明細 |
| `weekly.report.review.line` | 執行回顧明細 |
| `activity.efficiency.metrics` | 效率指標 |
| `weekly.schedule.config` | 週報排程配置 |

## 安裝

1. 將模組放置於 Odoo addons 路徑
2. 更新模組列表
3. 搜尋並安裝「生產力工具」

## 使用說明

### 快捷鍵

| 快捷鍵 | 功能 |
|--------|------|
| `Alt+Shift+A` | 新增待辦 |
| `Alt+Shift+N` | 新增筆記 |

### 週天排程

待辦可排程至特定週天（週一至週日），並支援多週預排：
- 本週
- 下週
- 第三週
- 第四週

### 工時記錄

完成待辦時會自動建立工時表記錄，需設定：
1. 系統設定 > 生產力工具 > 預設工時表專案
2. 或待辦關聯的文件（如 project.task）有對應專案

## 版本資訊

- **版本**：18.0.1.0.0
- **相容性**：Odoo 18
- **授權**：LGPL-3

## 作者

Dobtor SI
https://www.dobtor.com

## 技術支援

如有問題，請聯繫 Dobtor SI 技術團隊。
