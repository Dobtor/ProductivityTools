/** @odoo-module **/

import { AttendeeCalendarCommonPopover } from "@calendar/views/attendee_calendar/common/attendee_calendar_common_popover";
import { patch } from "@web/core/utils/patch";

/**
 * 在日曆事件 popover 加上「會議記錄」入口。
 *
 * 後端在 models/calendar_event.py：note_count / action_create_note /
 * action_view_notes；關聯欄位是 note.note.calendar_event_id。
 *
 * note_count 必須是 stored 欄位，且要在日曆視圖 arch 內宣告
 * （views/calendar_event_views.xml 的繼承），popover 的 record.rawRecord 才讀得到。
 *
 * this.orm / this.actionService 由父類別 setup() 建立，這裡不需重複取得。
 */
patch(AttendeeCalendarCommonPopover.prototype, {
    /** 建立本會議的會議記錄並開啟 */
    async onCreateNote() {
        const action = await this.orm.call("calendar.event", "action_create_note", [
            [this.props.record.id],
        ]);
        this.props.close();
        this.actionService.doAction(action);
    },

    /** 檢視本會議既有的會議記錄 */
    async onViewNotes() {
        const action = await this.orm.call("calendar.event", "action_view_notes", [
            [this.props.record.id],
        ]);
        this.props.close();
        this.actionService.doAction(action);
    },

    get noteCount() {
        return this.props.record.rawRecord?.note_count || 0;
    },

    get hasNotes() {
        return this.noteCount > 0;
    },
});
