odoo.define('flow_calendar.widgets', function(require) {
    "use strict";

    var core = require('web.core');
    var widgets = require('web_calendar.widgets');

    var _t = core._t;
    var QWeb = core.qweb;

    var CalendarView = require('web_calendar.CalendarView');    
    
    // CalendarView.include({
    //     extraSideBar: function() {
    //         var self = this;
    //         var result = this._super();

    //         return result.then(function() {
    //             self.$('.o_calendar_filter').append(QWeb.render('FlowCalendarView.sidebar.filters'));
    //         });
    //     }
    // });

    widgets.QuickCreate.include({
        events: {
            "click .flow-calendar-apps button": 'handle_click'
        },

        init: function(parent, dataset, buttons, options, data_template) {
            this._super.apply(this, arguments);
            this.data_template.flow_calendar_model = false;
            this.btn_edit = this.$footer.find('button.btn-default:first');
        },

        handle_click: function(e) {
            var button = $(e.target)[0];
            
            this.$footer.find('button').prop('disabled', true);
            this.data_template.flow_calendar_model = $(button).next("input[name='flow_calendar_model']")[0].value;
            this.btn_edit.trigger('click');
        }
    });
});
