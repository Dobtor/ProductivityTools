# 待辦事項 × 專案／工時表（dobtor_mail_activity_project）

`dobtor_mail_activity` 與「專案」「工時表」之間的橋接模組。**裝了工時表（hr_timesheet）
後自動安裝**，不需手動。

## 功能
- 待辦的「專案」欄位（表單、快速彈窗、建立待辦精靈）；選文件可反推專案、專案可帶入客戶
- 關聯圖以專案為根
- 完成待辦時登錄工時到工時表；「登錄後繼續」只登錄不完成
- 找不到專案：照常完成、跳過工時（chatter 留痕）；之後掛上專案，於待辦「工時表」分頁按
  「登錄工時」補登（已完成的待辦也可以）
- 公司「啟用工時記錄」開關、「預設工時專案」
- 隱藏 project_todo 自己的「待辦事項」App（改用 dobtor_mail_activity 的同名 App）

## 相依
`dobtor_mail_activity`、`project`、`project_todo`、`hr_timesheet`
