/** @odoo-module */

import { Domain } from "@web/core/domain";
import { SearchModel } from "@web/search/search_model";
import { _t } from "@web/core/l10n/translation";
import { reactive } from "@odoo/owl";

/**
 * 週次選擇器的 SearchModel。
 *
 * 為什麼週次要住在 SearchModel 而不是 Controller：
 *   SearchModel.domain --props.domain--> Controller --useModel.onWillUpdateProps--> model.load()
 * 舊版在 Controller 事後呼叫 model.root.load({domain}) 硬塞週次條件，位在資料流下游，
 * 於是「改 facet 會沖掉週次、切週次會沖掉 facet」。改成覆寫 _getDomain() 之後，
 * 週次與所有 facet／searchpanel 自然 AND，且走的是官方重載路徑（一次 RPC）。
 *
 * 一併解決：
 *   - get_week_info 的計數改吃當前 domain（舊版寫死 user_id=uid/active=True，
 *     在「未指派」「全部待辦」兩張清單上顯示的數字與清單內容無關）
 *   - exportState/_importState → 麵包屑返回、重整保留週次
 *   - _getContext() → 排程彈窗／建立 wizard 也拿得到 schedule_current_week，
 *     不再固定 fallback 成本週
 */
export class ActivityWeekSearchModel extends SearchModel {
    setup(services) {
        super.setup(...arguments);

        // 刻意用 reactive() 而非 useState()：SearchModel 是在 WithSearch.setup() 內
        // 建立的，useState 會把這些狀態綁到 WithSearch 的重繪。WithSearch 一重繪就
        // 重新渲染 slot → Controller 的 onWillUpdateProps → model.load()，等於每次
        // 更新週次計數都白打一次 web_search_read。改用 reactive() 後由消費端
        // （Controller）自行 useState() 訂閱，只重繪它自己。
        //
        // currentWeek: -1 | 0 | 1 | ... | 'all'
        this.weekState = reactive({ weeks: [], currentWeek: 0, isLoading: true });
        // 供 kanban 欄位標題透過 env.activityWeekDates 取當週各天日期
        this.weekDatesState = reactive({ dates: {} });
        // 「最後發出的請求才算數」，避免快速切換週次時舊回應覆蓋新結果
        this._weekInfoSeq = 0;
    }

    // ------------------------------------------------------------------
    // 生命週期
    // ------------------------------------------------------------------

    async load(config) {
        // action context 可指定初始週次（例如「未指派」清單預設 'all'）。
        // 必須放在 super.load() 之前：load() 內部第一次計算 searchDomain 就要帶對週次。
        // 若 config.state 存在，super.load() 會走 _importState 覆蓋掉這個預設值。
        const defaultWeek = config?.context?.activity_default_week;
        if (defaultWeek !== undefined && defaultWeek !== null) {
            this.weekState.currentWeek = defaultWeek;
        }
        // 先取週次邊界與 domain（get_week_bounds 不吃 domain，沒有雞生蛋問題），
        // 這樣 super.load() 內第一次算 searchDomain 就已帶對週次條件。
        await this._loadWeekBounds();
        await super.load(config);
        // 再補統計（需要當前 domain）
        await this._loadWeekInfo();
    }

    async reload(config) {
        await super.reload(config);
        // 不 await：action 層 domain 變更後，計數列自行追上即可
        this._loadWeekInfo();
    }

    /**
     * 每次查詢變動（toggle filter、searchpanel、selectWeek…）都會經過這裡。
     * super._notify() 內部已做 blockNotification 判斷並 trigger("update")。
     */
    async _notify() {
        const blocked = this.blockNotification;
        await super._notify();
        if (!blocked) {
            // 不 await：先讓清單重載，計數列稍後自行更新（weekState 為 reactive）
            this._loadWeekInfo();
        }
    }

    // ------------------------------------------------------------------
    // domain / context 注入
    // ------------------------------------------------------------------

    _getDomain(params = {}) {
        const domain = super._getDomain(params);
        // withGlobal:false 只有「加入我的最愛」在取 domain 時會傳
        // （web/search/search_model.js:_getIrFilterDescription）→
        // 不要把當下週次寫死進 favourite。
        if (params.withGlobal === false) {
            return domain;
        }
        const weekDomain = this._getWeekDomain();
        if (!weekDomain) {
            return domain;
        }
        const result = Domain.and([domain, weekDomain]);
        return params.raw ? result : result.toList(this.domainEvalContext);
    }

    _getContext() {
        const context = super._getContext();
        // mail.activity.write() 在「空值卡換天」時會讀這兩個 key
        // （_derive_planned_date_from_context）
        return Object.assign(context, {
            schedule_current_week: this.weekState.currentWeek,
            schedule_week_dates: this.weekDatesState.dates,
        });
    }

    // ------------------------------------------------------------------
    // 狀態保存（麵包屑返回 / 重整）
    // ------------------------------------------------------------------

    exportState() {
        const state = super.exportState();
        state.activityWeek = this.weekState.currentWeek;
        return state;
    }

    _importState(state) {
        super._importState(...arguments);
        if (state.activityWeek !== undefined) {
            this.weekState.currentWeek = state.activityWeek;
        }
    }

    // ------------------------------------------------------------------
    // 對外
    // ------------------------------------------------------------------

    async selectWeek(weekNumber) {
        if (this.weekState.currentWeek === weekNumber) {
            return;
        }
        this.weekState.currentWeek = weekNumber;
        // 先用手上既有的 weeks 資料把日期對應表換好，_getContext() 才會立刻正確
        this._syncWeekDates();
        // domain/context 重算 → props.domain 變 → Controller 重載（並觸發計數重取）
        await this._notify();
    }

    // ------------------------------------------------------------------
    // 內部
    // ------------------------------------------------------------------

    /**
     * @returns {Domain|null} null 代表不加任何週次條件（「全部」或邊界尚未載入）
     *
     * domain 由後端 _week_descriptors() 提供，以 planned_date/scheduled_date 的
     * 日期區間表達，**不碰 stored 的 schedule_week_number** —— 那個欄位相對「今天」
     * 計算，會隨時間腐化，過去只能靠每日 cron 續命，cron 失效就靜默給錯結果。
     * 條件的單一真實來源在 Python（_week_date_domain），前端只負責套用。
     */
    _getWeekDomain() {
        const week = this.weekState.currentWeek;
        if (week === "all") {
            return null;
        }
        const descriptor = this.weekState.weeks.find((w) => w.number === week);
        if (!descriptor || !descriptor.domain || !descriptor.domain.length) {
            // 邊界還沒載入 → 先不過濾（寧可多顯示，不要顯示錯的）
            return null;
        }
        return new Domain(descriptor.domain);
    }

    _syncWeekDates() {
        const info = this.weekState.weeks.find(
            (w) => w.number === this.weekState.currentWeek
        );
        this.weekDatesState.dates = info ? info.dates : {};
        // context getter 有快取（this._context），日期換了要讓它重算，
        // 否則 schedule_week_dates 可能停在上一週
        this._context = null;
    }

    /**
     * 取週次邊界與篩選 domain（不含統計）。刻意與 _loadWeekInfo 分開：
     * 這支不需要 domain，可在 SearchModel 尚未載入 globalDomain 時先呼叫。
     */
    async _loadWeekBounds() {
        try {
            this.weekState.weeks = await this.orm.call("mail.activity", "get_week_bounds", []);
        } catch (e) {
            console.error("Failed to load week bounds:", e);
            this.weekState.weeks = this._fallbackWeeks();
        }
        this._syncWeekDates();
    }

    /** 後端取不到時的降級選單：只有標籤，沒有 domain → 不做週次過濾。 */
    _fallbackWeeks() {
        return [
            { number: -1, name: _t("Previous Week"), display_name: _t("Previous Week"), key: "week_prev", count: 0, total_hours: 0, dates: {}, domain: [] },
            { number: 0, name: _t("This Week"), display_name: _t("This Week"), key: "week0", count: 0, total_hours: 0, dates: {}, domain: [] },
            { number: 1, name: _t("Next Week"), display_name: _t("Next Week"), key: "week1", count: 0, total_hours: 0, dates: {}, domain: [] },
            { number: "all", name: _t("All"), display_name: _t("All"), key: "all", count: 0, total_hours: 0, dates: {}, domain: [] },
        ];
    }

    async _loadWeekInfo() {
        const seq = ++this._weekInfoSeq;
        this.weekState.isLoading = true;
        try {
            // super._getDomain() 繞過本類別的週次注入，取得「除週次以外」的當前條件
            // （action domain + facet + searchpanel），計數才會與畫面一致。
            const baseDomain = super._getDomain();
            const weeks = await this.orm.call("mail.activity", "get_week_info", [], {
                domain: baseDomain,
                // 帶上檢視 context：action 的 active_test 等 key 會影響 read_group 的
                // 結果集，不帶的話計數會與清單對不上（例如「我的待辦」合併歷史後）
                context: this.context,
            });
            if (seq !== this._weekInfoSeq) {
                return;
            }
            this.weekState.weeks = weeks;
        } catch (e) {
            if (seq !== this._weekInfoSeq) {
                return;
            }
            console.error("Failed to load week info:", e);
            // 統計失敗時保留既有 weeks（含 domain），只是數字不更新；
            // 完全沒有 weeks 時才降級成無 domain 的選單。
            if (!this.weekState.weeks.length) {
                this.weekState.weeks = this._fallbackWeeks();
            }
        } finally {
            if (seq === this._weekInfoSeq) {
                this.weekState.isLoading = false;
                this._syncWeekDates();
            }
        }
    }
}
