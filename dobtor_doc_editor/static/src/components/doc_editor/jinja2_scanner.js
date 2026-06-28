/** @odoo-module **/

/**
 * jinja2_scanner — Phase 8 Sprint G + H
 *
 * 純函式 util：掃描 canvas-editor 的 IElement[] 結構，找出所有 jinja2 風格的
 * `{{ var }}` / `{{ object.partner_id.name }}` 變數。
 *
 *   - Sprint G: scanJinja2Variables(editorData)
 *     回傳去重後的清單，供批次建 doc.template.field record 用。
 *   - Sprint H: scanJinja2VariablesWithPositions(mainElements)
 *     回傳逐筆匹配 + 元素索引位置，供 in-place 替換用
 *     (setRange + backspace + executeInsertControl)。
 *
 * 設計考量：
 *   - 不依賴 canvas-editor runtime，純 JS、可被 vitest 單測
 *   - Sprint G 遞迴走進 table / list / title 等巢狀結構
 *   - Sprint H **不**遞迴：只處理 main 流，因為跨巢狀的 setRange 簽名複雜
 *     (要 tableId/trIndex/tdIndex)，且 reverse-replace 容易破壞表格結構
 *   - 跳過 control 元素內部的 placeholder/value（已是註冊欄位、不應重複建）
 *   - 允許 `object.partner_id.name` 等帶點路徑，剝除 `object.` 前綴
 *     與 Sprint E `odoo_field_name` 對齊
 *   - 不消耗變數內的空白，允許 `{{name}}` / `{{ name }}` / `{{  name  }}`
 */

/**
 * jinja2 變數正則：
 *   - `{{`  起頭，允許前後任意空白
 *   - 識別字：英文字母或底線開頭，後跟 `\w` 或 `.`（支援 `object.partner_id.name`）
 *   - `}}`  結尾
 *
 * 故意不允許變數內含其他符號（如 `|filter`、`(arg)`），那種已偏離單純
 * 「Odoo 欄位路徑」語意，Sprint E 的 odoo_field_name 也不收這種格式。
 */
const JINJA2_VAR_RE = /\{\{\s*([A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)*)\s*\}\}/g;

/**
 * 把 IElement[] 的所有 text 連接成單一字串。
 * 遞迴 table.trList[].tdList[].value、list/title/block 的 valueList。
 * CONTROL 元素直接跳過（Sprint E 已註冊欄位）。
 *
 * @param {Array} elements - IElement[]
 * @returns {string}
 */
export function flattenElementsToText(elements) {
    if (!Array.isArray(elements)) return "";
    const buf = [];
    for (const el of elements) {
        if (!el || typeof el !== "object") continue;
        const type = el.type;

        if (type === "control") continue;

        if (type === "table" && Array.isArray(el.trList)) {
            for (const tr of el.trList) {
                if (!tr || !Array.isArray(tr.tdList)) continue;
                for (const td of tr.tdList) {
                    if (td && Array.isArray(td.value)) {
                        buf.push(flattenElementsToText(td.value));
                    }
                }
            }
            continue;
        }

        if (Array.isArray(el.valueList)) {
            buf.push(flattenElementsToText(el.valueList));
            continue;
        }

        if (typeof el.value === "string") {
            buf.push(el.value);
        }
    }
    return buf.join("");
}

/**
 * 掃描 canvas-editor 的 IEditorData 主流文字，回傳所有 `{{ var }}` 變數。
 *
 * @param {object} editorData - `editor.command.getValue().data`，含 main/header/footer
 * @returns {Array<{varName: string, occurrences: number}>}
 *   去重後的變數清單，按出現次數降冪、同次數按字母升冪排序。
 */
export function scanJinja2Variables(editorData) {
    if (!editorData || typeof editorData !== "object") return [];

    const buckets = [];
    if (Array.isArray(editorData.main)) buckets.push(editorData.main);
    if (Array.isArray(editorData.header)) buckets.push(editorData.header);
    if (Array.isArray(editorData.footer)) buckets.push(editorData.footer);

    const counts = new Map();
    for (const bucket of buckets) {
        const text = flattenElementsToText(bucket);
        JINJA2_VAR_RE.lastIndex = 0;
        let m;
        while ((m = JINJA2_VAR_RE.exec(text)) !== null) {
            const varName = m[1];
            const cleaned = varName.replace(/^object\./, "");
            if (!cleaned) continue;
            counts.set(cleaned, (counts.get(cleaned) || 0) + 1);
        }
    }

    const items = Array.from(counts.entries()).map(([varName, occurrences]) => ({
        varName,
        occurrences,
    }));
    items.sort((a, b) => {
        if (b.occurrences !== a.occurrences) return b.occurrences - a.occurrences;
        return a.varName.localeCompare(b.varName);
    });
    return items;
}

/**
 * Sprint T：把 main 流內 value 長度 > 1 的 text 元素拆成 1 字元 / element。
 *
 * 為什麼必要：canvas-editor 載入 content_html 時、會把 `<p>text</p>` 整段
 * 文字塞成單一 IElement（value 多字元）。Sprint H 的 scanner 對 multi-char
 * 元素視為 unsafe sentinel（無法精確 setRange 對齊字元邊界），結果整個段落
 * 的 `{{ var }}` 都被略過 → onScanAndReplaceClick 早退 → 0 record。
 *
 * 解法：handler 在 scan 前先呼叫此函式 normalize、再 executeSetValue
 * 回 canvas-editor。normalize 後每個字元都是獨立元素，scanner 就能找到位置。
 *
 * 設計：
 *   - 只拆 main 流（table 內 td.value 在 scanJinja2VariablesInTables 之前先拆
 *     是另一回事，目前先 cover main；table 由 scanJinja2VariablesInTables 對
 *     每個 td.value 跑 scanJinja2VariablesWithPositions 時連帶處理）
 *   - 保留所有非 value 屬性（font/size/color 等格式靠 spread）
 *   - 非 text 元素 / 複合元素（type === 'control' / 'table' / valueList）原樣回傳
 *
 * @param {Array} elements - main flow IElement[]
 * @returns {Array} 新陣列（multi-char 拆成 single-char）；原陣列不變動
 */
export function normalizeMultiCharElements(elements) {
    if (!Array.isArray(elements)) return [];
    const result = [];
    for (const el of elements) {
        if (!el || typeof el !== "object") {
            result.push(el);
            continue;
        }
        const type = el.type;
        // 複合元素 / control / table 不拆（內部 td.value 由 scanInTables 各自處理）
        if (
            type === "control" ||
            type === "table" ||
            type === "list" ||
            type === "title" ||
            Array.isArray(el.valueList) ||
            Array.isArray(el.trList)
        ) {
            result.push(el);
            continue;
        }
        // text 元素：value 多字元 → 拆成 single-char、保留其他屬性
        if (typeof el.value === "string" && el.value.length > 1) {
            for (const ch of el.value) {
                result.push({ ...el, value: ch });
            }
            continue;
        }
        result.push(el);
    }
    return result;
}

/**
 * Sprint T：對 table 內每個 td.value 也跑同樣的 normalize（多字元 → 單字元）。
 * 回傳新的 main elements，table 結構保留、td.value 內部正規化。
 */
export function normalizeMultiCharElementsInTables(mainElements) {
    if (!Array.isArray(mainElements)) return [];
    return mainElements.map((el) => {
        if (!el || el.type !== "table" || !Array.isArray(el.trList)) return el;
        return {
            ...el,
            trList: el.trList.map((tr) => {
                if (!tr || !Array.isArray(tr.tdList)) return tr;
                return {
                    ...tr,
                    tdList: tr.tdList.map((td) => {
                        if (!td || !Array.isArray(td.value)) return td;
                        return { ...td, value: normalizeMultiCharElements(td.value) };
                    }),
                };
            }),
        };
    });
}

/**
 * Sprint Q：從掃描結果與 cache 算出「待建 / 沿用 / 跳過」分析。
 *
 * 純函式（無 IO、無 side-effect），可在 vitest 直接測試。把 onScanAndReplaceClick
 * 與 onScanVariablesClick 共用的分析邏輯抽出來，handler 變成 orchestration shell。
 *
 * @param {object} params
 * @param {Array<{varName, occurrences}>} params.scannedAll - scanJinja2Variables 結果
 *        （含 header/footer/巢狀，含次數）
 * @param {Array} params.mainPositions - scanJinja2VariablesWithPositions(data.main) 結果
 * @param {Array} params.tablePositions - scanJinja2VariablesInTables(data.main) 結果
 * @param {Array<string>} params.existingOdooFieldNames - cache 中已存在的 odoo_field_name 列表
 *
 * @returns {object} 分析結果：
 *   - positions: main + table 合併的位置陣列
 *   - uniqueVars: 去重 + 字母排序的可替換變數名
 *   - toCreate: uniqueVars 中尚未在 cache 的，需要 save_field
 *   - cacheHitCount: uniqueVars 中已存在於 cache 的數量
 *   - skippedCount: scannedAll 中無法替換的變數數（位於 list/title/multi-char）
 */
export function analyzeScanResults({
    scannedAll,
    mainPositions,
    tablePositions,
    existingOdooFieldNames,
}) {
    const safeScanned = Array.isArray(scannedAll) ? scannedAll : [];
    const safeMain = Array.isArray(mainPositions) ? mainPositions : [];
    const safeTable = Array.isArray(tablePositions) ? tablePositions : [];
    const safeExisting = Array.isArray(existingOdooFieldNames) ? existingOdooFieldNames : [];

    const positions = [...safeMain, ...safeTable];
    const uniqueVars = Array.from(new Set(positions.map(p => p.varName))).sort();
    const existingSet = new Set(safeExisting);
    const toCreate = uniqueVars.filter(v => !existingSet.has(v));

    return {
        positions,
        uniqueVars,
        toCreate,
        cacheHitCount: uniqueVars.length - toCreate.length,
        // scannedAll 與 uniqueVars 都是去重後的；差值粗略代表「位於不可替換結構內」的變數數
        // （注意：scannedAll 含 header/footer/list/title 內的變數，uniqueVars 只含可替換的）
        skippedCount: Math.max(0, safeScanned.length - uniqueVars.length),
    };
}

/**
 * Sprint Q：對比 cache 與當前文件 control list，算出孤兒 record id 集合。
 *
 * 純函式版本，把 Sprint M `orphanRecordIds` getter 中的 set diff 邏輯抽出來。
 * Getter 仍負責呼叫 canvas-editor `getControlList()` + 解析 conceptId（IO 部分），
 * 把純資料丟給這個函式做 diff。
 *
 * @param {Array<{id}>} cache - _templateFieldsCache（只看 id 欄位）
 * @param {Set<number>|Array<number>} controlIds - 文件內所有 control 的 conceptId 集合
 * @returns {Set<number>} 在 cache、但不在 controlIds 的 id 集合（孤兒）
 */
export function computeOrphanRecordIds(cache, controlIds) {
    const safeCache = Array.isArray(cache) ? cache : [];
    const idSet = controlIds instanceof Set
        ? controlIds
        : new Set(Array.isArray(controlIds) ? controlIds : []);
    const orphans = new Set();
    for (const f of safeCache) {
        if (!f || typeof f.id === "undefined") continue;
        if (!idSet.has(f.id)) orphans.add(f.id);
    }
    return orphans;
}

/**
 * Sprint J：對 table.tr[].td[].value 也掃 `{{ var }}` 並回傳含 table 座標的
 * 位置資訊，供 setRange(s, e, tableId, startTdIdx, endTdIdx, startTrIdx, endTrIdx)
 * 多參數呼叫使用。
 *
 * 與 Sprint H 的 `scanJinja2VariablesWithPositions` 的差異：
 *   - 不掃 main 流（main 流用 Sprint H 的函式）
 *   - 只處理 table 元素（list / title valueList 仍跳過 — 那兩個 setRange 簽名
 *     更複雜、實務罕見）
 *   - 回傳結構含 `tableElementIdx` / `trIdx` / `tdIdx` / `tableId` / `startIdx` / `endIdx`
 *     對應 td.value 內的元素索引
 *
 * @param {Array} mainElements - editor.command.getValue().data.main
 * @returns {Array<{varName, fullMatch, tableElementIdx, trIdx, tdIdx, tableId, startIdx, endIdx}>}
 */
export function scanJinja2VariablesInTables(mainElements) {
    if (!Array.isArray(mainElements)) return [];
    const matches = [];
    for (let ei = 0; ei < mainElements.length; ei++) {
        const el = mainElements[ei];
        if (!el || el.type !== "table" || !Array.isArray(el.trList)) continue;
        const tableId = el.id || el.tableId || null;
        for (let trIdx = 0; trIdx < el.trList.length; trIdx++) {
            const tr = el.trList[trIdx];
            if (!tr || !Array.isArray(tr.tdList)) continue;
            for (let tdIdx = 0; tdIdx < tr.tdList.length; tdIdx++) {
                const td = tr.tdList[tdIdx];
                if (!td || !Array.isArray(td.value)) continue;
                // 對單一 td.value 套同樣的 main-flow 掃描邏輯
                const cellMatches = scanJinja2VariablesWithPositions(td.value);
                for (const cm of cellMatches) {
                    matches.push({
                        ...cm,
                        tableElementIdx: ei,
                        trIdx,
                        tdIdx,
                        tableId,
                    });
                }
            }
        }
    }
    return matches;
}

/**
 * Sprint H：對 main 流（**不含** table / list / title 等巢狀結構）掃描所有
 * `{{ var }}` 並回傳帶元素索引位置的逐筆匹配，供 in-place 替換用
 * (setRange + backspace + executeInsertControl)。
 *
 * **故意不掃 table/list/title**：setRange 對 td 的簽名牽涉 tableId/trIndex/
 * tdIndex/startTdIndex，reverse-replace 容易破壞表格結構。MVP 只處理 main 流
 * 純文字段落，足以覆蓋 user 截圖那 5 個變數場景（都在文件正文）。
 *
 * 防禦：
 *   - 用 NUL ('\0') 作為 unsafe sentinel：regex 的 `[A-Za-z_]` 與 `\w` 都不會
 *     匹配 NUL、`\s` 也不含 NUL，所以跨越 sentinel 的 match 自然不會被產生。
 *     第二道防線會明確檢查 match 範圍內是否含 NUL（保險）。
 *   - 跳過 control / table / list / title / valueList 任何複合元素
 *   - 跳過 value 非 string 或長度 ≠ 1 的元素（multi-char 元素無法用 setRange
 *     精確對齊到字元邊界）
 *
 * @param {Array} mainElements - editor.command.getValue().data.main
 * @returns {Array<{varName, fullMatch, startIdx, endIdx}>}
 *   逐筆匹配按文件順序，未去重。startIdx / endIdx 為 mainElements 內的元素
 *   索引（含），即 setRange(startIdx, endIdx + 1) 會選中整個 match。
 */
/**
 * Sprint W：對 main 流以「flat char-offset」找指定 marker 字串的所有出現位置。
 *
 * 與 `scanJinja2VariablesWithPositions` 的差別：
 *   - 後者要求每個 char 是獨立 IElement（typed content）、回傳的 idx 是 IElement 索引
 *   - 本函式不要求 per-char element、回傳的 idx 是 **flat char-offset**，直接吃進
 *     `setRange(start, end)`。canvas-editor 的 setRange 對 multi-char 元素也以
 *     字元為步長（probe-search-control-insertion.spec.ts 已驗證 setRange(3, 20)
 *     對 single multi-char element 的 char 3..19 範圍正確 backspace）。
 *
 * 用途：Sprint W 兩階段替換的 Stage 2 入口。Stage 1 先用 canvas-editor 的
 *   executeSearch + executeReplace(text) 把 `{{ var }}` 換成 unique marker，
 *   Stage 2 用本函式找 marker 位置 → setRange + executeBackspace + executeInsertControl。
 *
 * 規則：
 *   - text 元素（type 非 control/table/list/title、無 valueList/trList）的 value 字串
 *     原樣計入 flat string
 *   - 非 text / 複合元素一律記成 1 個 NUL 占位（canvas-editor 對 control 也以 1 步計算
 *     游標移動，所以 NUL 占位後續 setRange 仍對齊）
 *
 * @param {Array} mainElements - editor.command.getValue().data.main
 * @param {string} marker - 要尋找的字串（必須非空）
 * @returns {Array<{startIdx: number, endIdx: number}>}
 *   每個 marker 出現位置；endIdx 為 exclusive（setRange(startIdx, endIdx) 即可選中 marker）
 */
export function findMarkerPositionsInMain(mainElements, marker) {
    if (!Array.isArray(mainElements) || typeof marker !== "string" || !marker) return [];
    const NUL = " ";
    const buf = [];
    for (const el of mainElements) {
        if (!el || typeof el !== "object") {
            buf.push(NUL);
            continue;
        }
        const type = el.type;
        const isComplex =
            type === "control" ||
            type === "table" ||
            type === "list" ||
            type === "title" ||
            Array.isArray(el.valueList) ||
            Array.isArray(el.trList);
        if (isComplex) {
            buf.push(NUL);
            continue;
        }
        if (typeof el.value === "string") {
            buf.push(el.value);
            continue;
        }
        buf.push(NUL);
    }
    const concat = buf.join("");
    const positions = [];
    let from = 0;
    while (true) {
        const i = concat.indexOf(marker, from);
        if (i < 0) break;
        positions.push({ startIdx: i, endIdx: i + marker.length });
        from = i + marker.length;
    }
    return positions;
}

export function scanJinja2VariablesWithPositions(mainElements) {
    if (!Array.isArray(mainElements)) return [];

    const SENTINEL = " ";
    const text = [];
    const elementIdxByChar = [];

    for (let ei = 0; ei < mainElements.length; ei++) {
        const el = mainElements[ei];
        if (!el || typeof el !== "object") {
            text.push(SENTINEL);
            elementIdxByChar.push(ei);
            continue;
        }
        const type = el.type;
        const isComplex =
            type === "control" ||
            type === "table" ||
            type === "list" ||
            type === "title" ||
            Array.isArray(el.valueList) ||
            Array.isArray(el.trList);
        if (isComplex) {
            text.push(SENTINEL);
            elementIdxByChar.push(ei);
            continue;
        }
        if (typeof el.value === "string" && el.value.length === 1) {
            text.push(el.value);
            elementIdxByChar.push(ei);
            continue;
        }
        // multi-char value 或非 string → unsafe sentinel
        text.push(SENTINEL);
        elementIdxByChar.push(ei);
    }

    const concat = text.join("");
    const re = /\{\{\s*([A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)*)\s*\}\}/g;
    const matches = [];
    let m;
    while ((m = re.exec(concat)) !== null) {
        const matchStart = m.index;
        const matchEnd = m.index + m[0].length - 1;
        // 第二道防線：明確檢查 match 範圍內無 sentinel
        let hasSentinel = false;
        for (let i = matchStart; i <= matchEnd; i++) {
            if (concat.charCodeAt(i) === 0) {
                hasSentinel = true;
                break;
            }
        }
        if (hasSentinel) continue;
        const startElementIdx = elementIdxByChar[matchStart];
        const endElementIdx = elementIdxByChar[matchEnd];
        const varName = m[1].replace(/^object\./, "");
        if (!varName) continue;
        matches.push({
            varName,
            fullMatch: m[0],
            startIdx: startElementIdx,
            endIdx: endElementIdx,
        });
    }
    return matches;
}

/**
 * Sprint X：對 table cell 內的 td.value 陣列做「marker text element → control element」的純函式
 * 替換、回傳新 td.value。不修改 input（純函式）。
 *
 * 為什麼不用 setRange + executeBackspace + executeInsertControl 路徑（Sprint W main 用的）：
 *   Sprint X probe 證明 executeInsertControl 在 table cell 內第二次以後會丟
 *   "Cannot read properties of undefined (reading 'controlId')"
 *   原因：canvas-editor 內部對 control insertion 的 range tracking 在表格內第一次 insert
 *   完成後落入 stuck state、後續 setRange 無法 reset。
 *   改走直接 IElement 陣列 mutate + executeSetValue 路徑（probe-sprint-x-table 驗證 4/4 OK）。
 *   setValue 對 control element（type:'control'）不會 auto-merge（Sprint T 的 auto-merge 限於
 *   連續同樣式 text），所以這條路徑安全。
 *
 * @param {Array} tdValue - canvas-editor td.value 陣列（IElement[]）
 * @param {Map<string, {fieldId: string|number, varName: string}>} markerToField
 *   marker 字串 → {fieldId, varName} 的對應；用 fieldId 當 conceptId 寫入 control
 * @param {function(string, string|number): object} buildControlElement
 *   給 varName + fieldId 回傳 control IElement（讓呼叫方控制 placeholder/style/etc）
 * @returns {{newValue: Array, replaced: number}} 新陣列 + 替換次數
 */
export function rewriteTdValueWithControls(tdValue, markerToField, buildControlElement) {
    if (!Array.isArray(tdValue)) return { newValue: [], replaced: 0 };
    if (!(markerToField instanceof Map) || markerToField.size === 0) {
        return { newValue: tdValue.slice(), replaced: 0 };
    }
    let replaced = 0;
    const result = [];
    for (const el of tdValue) {
        if (!el || typeof el.value !== "string" || el.value.length === 0) {
            result.push(el);
            continue;
        }
        // 在 el.value 內搜所有 marker；按出現順序處理
        // 找出第一個 hit 位置最小的 marker，然後切；剩下 part 進入下一輪
        let remaining = el.value;
        let madeAnyCut = false;
        while (remaining.length > 0) {
            let bestIdx = -1;
            let bestMarker = null;
            for (const marker of markerToField.keys()) {
                const i = remaining.indexOf(marker);
                if (i < 0) continue;
                if (bestIdx === -1 || i < bestIdx) {
                    bestIdx = i;
                    bestMarker = marker;
                }
            }
            if (bestIdx === -1) {
                // 沒 marker 了；剩下整段保留為 text element（沿用原 el 屬性）
                if (madeAnyCut) {
                    result.push({ ...el, value: remaining });
                } else {
                    result.push(el);
                }
                break;
            }
            // 前段 text
            if (bestIdx > 0) {
                result.push({ ...el, value: remaining.slice(0, bestIdx) });
            }
            // control element
            const info = markerToField.get(bestMarker);
            result.push(buildControlElement(info.varName, info.fieldId));
            replaced++;
            remaining = remaining.slice(bestIdx + bestMarker.length);
            madeAnyCut = true;
        }
    }
    return { newValue: result, replaced };
}
