/** @odoo-module **/

import { AttendeeCalendarCommonPopover } from "@calendar/views/attendee_calendar/common/attendee_calendar_common_popover";
import { patch } from "@web/core/utils/patch";

/**
 * Patch AttendeeCalendarCommonPopover to add meeting note functionality
 *
 * This patch adds a "Create Note" button to the calendar event popover,
 * allowing users to quickly create meeting notes from the calendar view.
 * Note: this.orm and this.actionService are already initialized by the parent setup().
 */
patch(AttendeeCalendarCommonPopover.prototype, {

    /**
     * Create a meeting note for the current event
     */
    async onCreateNote() {
        const record = this.props.record;
        const eventId = record.id;

        // Call the action to create a note linked to this event
        const action = await this.orm.call(
            "calendar.event",
            "action_create_note",
            [[eventId]]
        );

        this.props.close();
        this.actionService.doAction(action);
    },

    /**
     * View notes linked to this event
     */
    async onViewNotes() {
        const record = this.props.record;
        const eventId = record.id;

        const action = await this.orm.call(
            "calendar.event",
            "action_view_notes",
            [[eventId]]
        );

        this.props.close();
        this.actionService.doAction(action);
    },

    /**
     * Check if the event has linked notes
     */
    get hasNotes() {
        const noteCount = this.props.record.rawRecord?.note_count;
        return noteCount && noteCount > 0;
    },

    /**
     * Get the note count for display
     */
    get noteCount() {
        return this.props.record.rawRecord?.note_count || 0;
    },
});
