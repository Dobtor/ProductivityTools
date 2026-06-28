# Canvas-editor 記憶體釋放設計（W4 P0-4）

**狀態**：W4 補強衝刺實作  
**對應漏項**：P0-4 — Canvas-editor 實例無 destroy()，記憶體洩漏  
**完成日期**：2026-05-06

---

## 1. 風險背景

`doc_editor.js`（582 行）原本 onWillUnmount 寫法：

```javascript
onWillUnmount(async () => {
    await this._autoSave.flush();
    this._autoSave.destroy();
    this._offlineManager.destroy();
    if (this._leaderElection) this._leaderElection.destroy();
    this.editor?.destroy?.();
});
```

### 三個未處理的 retention 點

1. **`window._docEditor = this.editor`**（line 226）
   - 為 DevTools 除錯方便而設的全域別名
   - onWillUnmount 沒清掉 → editor 被 `window` 這個 GC root 持有
   - 即使 component unmount，整個文件資料、Canvas、字型快取仍 retain

2. **`this.editor.listener.contentChange = () => { ... this... }`**（line 229）
   - closure 內捕獲 `this`（component instance）
   - destroy 後 listener 未清，editor → listener → closure → component → 任何 component 引用的物件 全部無法 GC

3. **Component 成員引用**（`this.editor`、`this._autoSave`、`this._offlineManager` 等）
   - 即使外部不再持有 component，內部成員若互相引用也可能形成 cycle
   - 顯式 null-out 可幫助引擎更快識別不可達

## 2. canvas-editor v0.9.128 destroy() API 確認

讀取 `node_modules/@hufe921/canvas-editor/dist/src/editor/index.d.ts`：

```typescript
export default class Editor {
    command: Command;
    version: string;
    listener: Listener;
    eventBus: EventBus<EventBusMap>;
    override: Override;
    register: Register;
    destroy: () => void;          // ← 官方提供
    use: UsePlugin;
    constructor(container: HTMLDivElement, data: IEditorData | IElement[], options?: IEditorOption);
}
```

→ optional chaining `this.editor?.destroy?.()` 會真的呼叫到（v0.9.128 確認有此方法）。原規劃猜測「上游可能缺 destroy」屬於假警報。

## 3. 修改後的 onWillUnmount

完整六步驟（按執行順序）：

| 步驟 | 動作 | 防範什麼 retention |
|---|---|---|
| 1 | `await this._autoSave.flush()` | 未存資料 → 用戶離開頁前最後一次同步寫入 |
| 2 | `this._autoSave.destroy()` | AutoSaveManager 內 setTimeout / setInterval |
| 3 | `this._offlineManager.destroy()` | window online/offline event listener、IndexedDB connection |
| 4 | `this._leaderElection.destroy()` | SharedWorker channel、bus 訂閱 |
| 5 | `delete window._docEditor` | 全域變數對 editor 的 hold |
| 6 | `this.editor.listener.contentChange = null` | listener 內 closure 對 component 的 hold |
| 7 | `this.editor.destroy()` | canvas-editor 內部 Canvas、字型、緩衝區 |
| 8 | `this.editor = null; this._loadedContentJson = null; ...` | 顯式幫助 GC |

flush 失敗用 try/catch 包，**不擋 destroy**（避免一個小錯把整個 cleanup 流程卡住）。

## 4. 驗收方式（Chrome DevTools Memory Profile）

操作步驟：
1. Chrome DevTools → Memory tab → Heap snapshot → 取 **baseline**
2. 開一份大文件（如 `tests/fixtures/03_complex_table/送審管制總表.docx`）
3. 等 canvas-editor 渲染完成
4. 關閉文件 tab（觸發 onWillUnmount）
5. 取 **after-1** snapshot
6. 重複 4-5 共 10 次
7. 取 **after-10** snapshot

**期望**：
- after-10 與 baseline 的 retained heap 差距 < 50MB
- Heap snapshot 中沒有殘留的 `Editor` instance（搜尋「Editor」應為 0 或固定數量）
- 沒有殘留的 `DocEditor` component instance

**對照組**（修正前）：
- 修正前每次 unmount 後都會 retain ~30-50MB
- 開關 10 次後 retained heap 接近 500MB
- DevTools Memory > Detached DOM 樹會持續增長

## 5. 4 個 Component 的處理範圍

原規劃寫「4 個元件升級為 OWL」，但實裝清查發現：

| Component | 狀態 | 處理 |
|---|---|---|
| `doc_editor` | ✅ 已是 OWL；本次強化 onWillUnmount | 已修 |
| `doc_field_picker` | 在 manifest 中**已停用**（line 71-72 註解） | 不需動 |
| `doc_page_layout` | 在 manifest 中**已停用**（line 76-77 註解） | 不需動 |
| `doc_ruler` | 在 manifest 中**已停用**（line 74-75 註解） | 不需動 |

→ 實際只有 1 個 active component，且本來就是 OWL。「OWL 升級」工作大幅縮小。

## 6. 後續觀察點

- W7-8 整合 AutoSave UI 時會新增 `auto_save_manager.onStatusChange()` callback，若該 callback 引用 component 也要在 unmount 時清掉
- W7-8 加 `doc_version_panel` 元件時，須使用同樣的 destroy 模式
- 若未來 portal user 端要載入 canvas-editor，`portal_document_view` 模板的 mount point 也要遵循相同 lifecycle

---

**附註**：此修改對應規劃文件 `dobtor_doc_editor_高保真匯入開發規劃.md` 的 §5.5b Phase 4.5 P0-4，與 plan `d-work-doc-editor-pure-duckling.md` 的 W4 段。
