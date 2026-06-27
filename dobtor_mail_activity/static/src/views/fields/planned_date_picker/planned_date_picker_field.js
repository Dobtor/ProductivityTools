/** @odoo-module */

/**
 * 共用「計畫日期」欄位 widget（kanban 卡片 + list 欄位共用）。
 *
 * 依狀態自動切換型態：
 *   - 有值：唯讀 badge「週X mm/dd」（改期走拖曳/狀態列/延期）。
 *   - 空值 + 被指派者：可點的「排定日期」pill，開 DateTimePicker（date，minDate=今天）
 *     選定後立即以 ORM 寫入 planned_date，由後端反推 schedule_status 並重載。
 *   - 空值 + 非被指派者：灰字「待排定」。
 *
 * form 不使用此 widget（沿用原生 date 欄位）；此 widget 專供 kanban / list。
 */
import { Component, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { useDateTimePicker } from "@web/core/datetime/datetime_hook";
import { serializeDate, today } from "@web/core/l10n/dates";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

const DAY_LABELS = {
    monday: _t("Mon"),
    tuesday: _t("Tue"),
    wednesday: _t("Wed"),
    thursday: _t("Thu"),
    friday: _t("Fri"),
    saturday: _t("Sat"),
    sunday: _t("Sun"),
};

export class PlannedDatePickerField extends Component {
    static template = "dobtor_mail_activity.PlannedDatePickerField";
    static props = { ...standardFieldProps };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");

        const getPickerProps = () => ({
            value: this.props.record.data[this.props.name] || false,
            type: "date",
            minDate: today(),
        });

        const picker = useDateTimePicker({
            target: "root",
            get pickerProps() {
                return getPickerProps();
            },
            onApply: async () => {
                const value = picker.state.value;
                if (!value) {
                    return;
                }
                await this.orm.write(
                    "mail.activity",
                    [this.props.record.resId],
                    { planned_date: serializeDate(value) }
                );
                // 後端反推 schedule_status / 順延 deadline → 重載以重新分組顯示。
                await this.props.record.model.root.load();
                // 提示：遠期日期會落在目前週次檢視之外，於「全部」檢視可見。
                this.notification.add(
                    _t("Planned date set to %s (visible in the All view).",
                        value.toFormat("MM/dd")),
                    { type: "success" }
                );
            },
        });
        this.pickerState = useState(picker.state);
        this.openPicker = picker.open;
    }

    get hasValue() {
        return !!this.props.record.data[this.props.name];
    }

    get isEditable() {
        return !this.hasValue && !!this.props.record.data.can_edit_as_assignee;
    }

    get displayLabel() {
        const planned = this.props.record.data[this.props.name];
        if (!planned) {
            return "";
        }
        const status = this.props.record.data.schedule_status;
        const dayLabel = (DAY_LABELS[status] || "").toString();
        return `${dayLabel} ${planned.toFormat("MM/dd")}`.trim();
    }

    get setDateLabel() {
        return _t("Set date");
    }

    get unscheduledLabel() {
        return _t("Unscheduled");
    }
}

export const plannedDatePickerField = {
    component: PlannedDatePickerField,
    displayName: _t("Planned Date Picker"),
    supportedTypes: ["date"],
    fieldDependencies: [
        { name: "schedule_status", type: "selection" },
        { name: "can_edit_as_assignee", type: "boolean" },
    ],
};

registry.category("fields").add("planned_date_picker", plannedDatePickerField);
