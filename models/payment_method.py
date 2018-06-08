# -*- coding: utf-8 -*-
##############################################################################
#
#   sale_quick_payment for odoo
#   Copyright (C) 2011 Akretion Sébastien BEAU <sebastien.beau@akretion.com>
#   Copyright 2013 Camptocamp SA (Guewen Baconnier)
#
#   This program is free software: you can redistribute it and/or modify
#   it under the terms of the GNU Affero General Public License as
#   published by the Free Software Foundation, either version 3 of the
#   License, or (at your option) any later version.
#
#   This program is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU Affero General Public License for more details.
#
#   You should have received a copy of the GNU Affero General Public License
#   along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################
from odoo import models, api, fields

class magento_payment_method(models.Model):
    _name = 'magento.payment.method'
    _rec_name = 'display_name'
    
    def _get_payment_method_name(self):
        for record in self :
            record.display_name = record.payment_method_code + " - " + record.backend_id.name
    
    backend_id = fields.Many2one('magento.backend',string="Magento Instance")
    payment_method_code = fields.Char('Payment Method Code')
    payment_method_name = fields.Char('Payment Method Name')
    display_name = fields.Char("Name",compute="_get_payment_method_name")
    _sql_constraints = [
        ('unique_payment_method_code','unique(backend_id,payment_method_code)',
         'This payment method code is already exist')]

class MagentoPaymentMethod(models.Model):
    _name = "magento.payment.method.ept"
    _description = "Magento Payment Method"
    _inherit = ['mail.thread']
    _rec_name = 'payment_method_code_id'

    @api.model
    @api.returns('res.company')
    def _default_company_id(self):
        return self.env['res.company']._company_default_get('magento.payment.method.ept')
    
    @api.model
    def _get_import_rules(self):
        return [('always', 'Always'),
                ('never', 'Never'),
                ('paid', 'Paid'),
               #('authorized', 'Authorized'),
                ]

    payment_method_code_id = fields.Many2one('magento.payment.method',string="Name")
    journal_id = fields.Many2one(
        comodel_name='account.journal',
        copy=False,
        string='Payment Journal',
        help="If a journal is selected, when a payment is recorded "
             "on a backend, payment entries will be created in this "
             "journal.",
    )
    
    invoice_journal_id = fields.Many2one(
        comodel_name='account.journal',
        copy=False,
        string='Invoice Journal',
        help="If a journal is selected, when a invoice is recorded "
             "on a backend, invoice entries will be created in this "
             "journal.",
    )
    
    payment_term_id = fields.Many2one(
        comodel_name='account.payment.term',
        string='Payment Term',
        help="Default payment term of a sale order using this method.",
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Company',
        default=_default_company_id,
    )

    magento_workflow_process_id = fields.Many2one(comodel_name='magento.sale.workflow.process',
                                          string='Automatic Workflow',help="Workflow for Order")
    create_invoice_on = fields.Selection(
        selection=[('open', 'Validate'),
                   ('paid', 'Paid'),
                   ('na','N/A')],
        string='Create Invoice on action',
        default="na",
        help="Should the invoice be created in Magento "
             "when it is validated or when it is paid in odoo?\n",
    )
    website_id = fields.Many2one(
                                 comodel_name='magento.website',
                                 string='Website',
                                 copy=False,
                                 )
    
    days_before_cancel = fields.Integer(
        string='Import Past Orders Of X Days',
        default=30,
        help="After 'n' days, if the 'Import Rule' is not fulfilled, the "
             "import of the sales order will be canceled.",
    )
    import_rule = fields.Selection(selection='_get_import_rules',
                                   string="Import Rule",
                                   default='always',
                                   required=True,
                                   help="Import Rule for Sale Order.\n \n [Always] : This Payment Method's Order will always import\n \
                                   [Paid]:If Order is Paid On Magento then and then import \n \
                                   [Never] : This Payment Method Order will never imported \n "
                                   )
    
    register_payment = fields.Selection(selection=[('advance_payment','Advance Payment'),
                                                   ('invoice_payment','Payment Against Invoice')],
                                        string="Register Payment As",
                                        default = 'invoice_payment'
                                        )
    
    _sql_constraints = [
                ('unique_website_payment_method', 'unique(payment_method_code_id, website_id)',
                 'There is already record exists for same magento website and payment method.')
            ]
    