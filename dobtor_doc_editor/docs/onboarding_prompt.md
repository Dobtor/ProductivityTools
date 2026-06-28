# dobtor_doc_editor — Autopilot Onboarding Prompt

> 用途：開新對話時直接複製「Ready-to-paste」區塊整段貼上，讓 Claude 接續 sprint 開發。
> 維護：每隔幾個 sprint 由 user 要求更新「狀態快照」與「Ready-to-paste」。
> 最後更新：2026-05-21（Sprint 164 結尾、三個 DEFER 決策已拍板）

---

## 狀態快照（2026-05-21 / Sprint 164 結尾）

- 完成到 **Sprint 164**，下一個 Sprint 165
- vitest 1361 passed + 1 skipped、VR mean 0.073191（byte-identical 第 27 連）
- working tree 乾淨（紀律 #14.b enforce 中）
- 階段：wire-up 期（方向 A）。Sprint 157/160v2/161/162/163 連續 wire-up，Strategy C 已驗證安全
- Phase 完成度：P0 100% / P1 80% / P2 部分 / P3 93% / P4 90% / P4.5 100% /
  P5 0% / P6 0% / P7 84% / P8（8.1+8.2.1 已驗證、8.2.2 未啟動）

### 三個 DEFER 決策（user 2026-05-21 拍板，全部 GO）

| 決策 | 來源 | 拍板 |
|---|---|---|
| A textAlignment / framePr wire-up | Sprint 140 | **GO**，做（1-2 sprint） |
| B goldens 重生 | Sprint 141 | **GO 方案 B：OnlyOffice DocumentServer** |
| C Phase 5 進階功能 | Sprint 142 | **GO 全 6 子功能都做** |

⚠️ 決策 C 硬依賴：OMML / SmartArt / Charts 對現有 42 fixture 0% 覆蓋，需真實 .docx
fixture 或經 user 同意的 synthetic fixture，否則 parser 寫完無法驗證。

### 距離終點估算

剩餘約 46-78 sprint（2-4 個月）。純 autonomous 跑得動約 15-20 sprint，
第一個會卡的點 = Phase 5 OMML/SmartArt/Charts 的 fixture。

---

## Ready-to-paste（Sprint 165 + 三決策 GO 版）

```
讀以下檔案了解 dobtor_doc_editor 高保真匯入專案狀態，然後接續開發。

【狀態檔（先讀，最準）】
docs/progress_snapshot.md       → 當前指標 / Phase 完成度 / VR mean
docs/autonomous_roadmap.md      → Sprint 排程 + 進度追蹤表
（路徑前綴 /mnt/d/work/odoo18-docker/addons/dobtor_doc_editor/）

【主規畫書（純規畫）】
dobtor_doc_editor_高保真匯入開發規劃.md
  → §5 Phase 計畫、§6 紀律（22 條 + 6 子 + 1 候選 + 1 潛在子 #21.a + #14.b enforce）

【最近必讀 sprint doc】
- docs/sprint162_defaulttabstop_production_wireup.md（Strategy C 完整範例 + VR opt-in 量測）
- docs/sprint164_bookmark_render_defer.md（honest DEFER 範式）

【★ user 已拍板三個 DEFER 決策（2026-05-21）★】

之前 Sprint 140/141/142 三個 DEFER user GO，user 現已決定全部 GO：
- 決策 A（Sprint 140）：textAlignment / framePr wire-up → GO，做（1-2 sprint）
- 決策 B（Sprint 141）：goldens 重生 → GO 方案 B：OnlyOffice DocumentServer
    （docker pull onlyoffice/documentserver、compose 起服務、conversion API、
     bulk 重轉 252 PNG goldens、re-baseline；CJK 字型需手動裝；
     注意 community 版頁數限制，若撞限制先回報 user）
- 決策 C（Sprint 142）：Phase 5 進階功能 → GO 全 6 子功能都做
    5.1 OMML / 5.2 SmartArt / 5.3 Charts / 5.4 追蹤修訂 / 5.5 註解 / 5.6 浮水印
    ⚠️ 6 子功能對現有 42 fixture 全 0% 覆蓋。開工前必須先解決 fixture：
       - 5.4 / 5.5 / 5.6：可先做（scope 可控），用 synthetic fixture 驗 parser
       - 5.1 / 5.2 / 5.3：需真實 .docx fixture。若 tests/fixtures/ 沒有含
         OMML/SmartArt/Charts 的樣本 → 停下來明確請 user 提供，或經 user 同意
         後用 docx-builder 生 synthetic fixture，不可無 fixture 硬寫 parser

【建議工作順序】

1. 先收尾 Phase 1-4 剩餘 wire-up（主軸、Strategy C、不卡 user）
2. 決策 A：textAlignment / framePr wire-up
3. 決策 C 的可控部分：5.6 浮水印 → 5.4 追蹤修訂 → 5.5 註解（synthetic fixture 即可）
4. 決策 B：OnlyOffice goldens 重生（env setup 較重、可獨立一個 cluster）
5. 決策 C 的大塊：5.1 OMML → 5.2 SmartArt → 5.3 Charts（需 fixture，撞牆就停等 user）
6. Phase 6 docx export 對稱性 / Phase 7 效能殘項 / Phase 8.2.2

【第 0 步 — 開工前檢查（紀律 #14.b）】

cd /mnt/d/work/odoo18-docker/addons/dobtor_doc_editor && git status -s .
有殘留 → 先補完 commit 或 audit 後 revert，working tree 清零才開新 sprint。
roadmap 進度追蹤表落後 → 先補登缺列（紀律 #14）。

【這個 session 要做的事】

1. 第 0 步檢查
2. 從下一個未完成 sprint 開始，照上面工作順序做，盡量多做幾個
3. 每個 sprint 走完整三層 SOP：
   - 寫程式 / wire-up / 補測試（Phase 5 parser → 先確認 fixture 存在）
   - vitest + flake8 +（影響 layout 時）VR opt-in 重跑量測 delta
   - probe 後若無真實 consumer / 無 fixture → honest DEFER 或停下請 user，不硬塞 stub
   - docs/sprintNN_*.md（Hypothesis / Method / Verification / Discipline / Result / 後續）
   - 更新 autonomous_roadmap.md 進度表 + progress_snapshot.md 指標
   - commit 前 git status -s 必須乾淨（紀律 #14.b），commit「Sprint NN: <一句話>」
4. 自然停：卡住 / 需 user 提供 fixture / context 重 → 停下留進度總結 + 列出等 user 的事項
   不要 touch .flag、不要排定下次自己醒來、不要寫 hook 或 wrapper script

【硬性紀律】

- 規畫書 §6 全部適用，特別注意：
  - #1.a / #1.b：wire-up 改 layout 後跑 VR、Strategy C（caller 不傳 → byte-identical）
  - #14 / #14.a / #14.b：docs 即時同步 + commit 前 working tree 清零
  - #18 / #18.a：PR-size、「依規畫書繼續」是 scope 限制詞、不發明新紀律
  - #21 / #21.a：optional 空集合不掛 key；key 即 binary signal 為例外
  - #22：mental model 不確定先 probe sprint；probe 結論可以是 honest DEFER
- Odoo Python 改完走升級 SOP：
  docker exec odoo18 odoo -c /etc/odoo/odoo.conf -d odoo18_dev -u dobtor_doc_editor --stop-after-init && docker restart odoo18
- Portal 模板用 --wb-*、禁用 --cy-*
- 不確定的東西明確標 "hypothesis"
- tsc --noEmit 有 2 個 pre-existing error（FontMetrics opentype.js 宣告 / SettingsParser position）、非新 bug

開工。
```

---

## 更新此檔的方式

每隔幾個 sprint，請 Claude：
1. 跑 `git log --oneline` + 讀 `docs/progress_snapshot.md` 抓最新狀態
2. 更新「狀態快照」區塊（sprint 編號、vitest、Phase 完成度）
3. 更新 Ready-to-paste 區塊的起點 sprint 與必讀 doc 清單
4. 「最後更新」日期改掉
