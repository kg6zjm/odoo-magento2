odoo.define('magento.tour', function(require) {
"use strict";

var core = require('web.core');
var tour = require('web_tour.tour');

var _t = core._t;

tour.register('magento_tour',{
	url: "/web",
},[tour.STEPS.MENU_MORE,{
	trigger:'.o_app[data-menu-xmlid="odoo_magento2_ept_v10.menu_connector_root"], .oe_menu_toggler[data-menu-xmlid="odoo_magento2_ept_v10.menu_connector_root"]',
	content: _t('Organize your Magento 2 activities with the <b>Magento app</b>.'),
    position: 'bottom',
},
{
    trigger: 'li a[data-menu-xmlid="odoo_magento2_ept_v10.menu_connector_config_settings"] .oe_menu_text, div[data-menu-xmlid="odoo_magento2_ept_v10.menu_connector_config_settings"]',
    content: _t("Setup your first <b>Magento Global</b>"),
    position: "right"
},
{
    trigger: '.oe_form_configuration .o_inner_group tbody tr td div div button',
    content: _t("Setup your first <b>Magento Global</b>"),
    position: "right"
}

]);

});