/** @odoo-module **/

import { useState } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { rpc } from "@web/core/network/rpc";
import { _t } from "@web/core/l10n/translation";
import { DobtorAiAssistantPanel } from "@dobtor_ai_bridge/panel/panel";

/**
 * 助理面板的「此畫面說明」＋提問後附的說明連結。
 *
 * ★ 連結**不經過 AI**：由主控台依本庫的方案比對產生、本站伺服器轉查、這裡渲染。
 *   面板原本的 `linkHref()` 只收本站相對路徑、markdown 也刻意不渲染連結 ——
 *   那道防外洩設計不變，所以說明連結走自己的一條路、自己的白名單。
 * ★ 只在後台（scope = backend）出現：前台 bundle 不含這支檔案，而前台訪客也
 *   沒有「目前在哪個動作」這種情境。
 */
patch(DobtorAiAssistantPanel.prototype, {
    setup() {
        super.setup(...arguments);
        this.screenHelp = useState({
            open: false,
            loading: false,
            results: [],
            error: null,
        });
        // ★ 允許的網域由伺服器回（設定頁那一份），面板不自己寫一份。
        this.helpHosts = [];
    },

    get helpEnabled() {
        return this.scope === "backend";
    },

    async _helpFetch(params) {
        try {
            const res = (await rpc("/dobtor_ai/help/links", params, { silent: true })) || {};
            if (res.hosts) {
                this.helpHosts = res.hosts;
            }
            return res;
        } catch {
            // ★ 說明只是附帶的：查不到就不顯示，不能讓面板跳錯誤對話框。
            return { ok: false, results: [] };
        }
    },

    /**
     * 這條說明連結能不能點、點去哪。
     *
     * ★ 伺服器已經篩過一次；這裡再擋一次，因為 `t-att-href` 放進去的東西
     *   就是使用者會點的東西 —— `javascript:` 或外站網址在這裡等於釣魚入口。
     */
    helpHref(item) {
        let url;
        try {
            url = new URL(String((item && item.url) || ""));
        } catch {
            return "";
        }
        if (url.protocol !== "https:" || url.username || url.password) {
            return "";
        }
        return this.helpHosts.includes(url.hostname.toLowerCase()) ? url.href : "";
    },

    _helpLinks(res) {
        return (res.results || []).filter((item) => this.helpHref(item));
    },

    async toggleScreenHelp() {
        const help = this.screenHelp;
        if (help.open) {
            help.open = false;
            return;
        }
        help.open = true;
        help.loading = true;
        help.error = null;
        help.results = [];
        // ★ 每次按都重抓情境：面板跨動作一直活著，上一次的 model/action 早就過時。
        const ctx = this.scopeParams();
        const res = await this._helpFetch({
            action: ctx.action_id || false,
            model: ctx.model || "",
            view_type: ctx.view_type || "",
        });
        help.results = this._helpLinks(res);
        help.error = res.ok ? null : _t("暫時查不到說明，請稍後再試。");
        help.loading = false;
    },

    /**
     * 提問時順便用同一句話查說明，結果掛在 AI 回答的下方。
     *
     * ★ 與 AI 並行查：不讓使用者多等；也不把結果交給 AI —— 模型不寫連結。
     * ☠️ 「繼續」送的是我們自己組的句子（fromInput = false），拿它去查只會得到
     *    不相干的說明，所以只查使用者親手打的那一句。
     */
    async sendText(message, fromInput = false) {
        const ask = this.helpEnabled && fromInput && !!message && !this.state.busy;
        const slot = this.state.messages.length + 1;
        const pending = ask
            ? this._helpFetch({ query: message, model: this.scopeParams().model || "" })
            : null;
        const result = await super.sendText(...arguments);
        if (pending) {
            const links = this._helpLinks(await pending);
            // ★ 用位置找那則回答：sendText 在結束時會整個換掉那則訊息物件，
            //   先拿參照會掛到被丟掉的那一個上。失敗時那則會被移除，就不掛。
            const reply = this.state.messages[slot];
            if (links.length && reply && reply.role === "ai" && !reply.streaming) {
                reply.helpLinks = links;
            }
        }
        return result;
    },
});
