# -*- encoding: utf-8 -*-
###############################################################################
#
#    sale_automatic_workflow for odoo
#    Copyright (C) 2011 Akretion Sébastien BEAU <sebastien.beau@akretion.com>
#    Author: Guewen Baconnier
#    Copyright 2014 Camptocamp SA
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
###############################################################################

from odoo import models, fields,api


class MagentoSaleWorkflowProcess(models.Model):
    """ A workflow process is the setup of the automation of a sales order.

    Each sales order can be linked to a workflow process.
    Then, the options of the workflow will change how the sales order
    behave, and how it is automatized.

    A workflow process may be linked with a Sales payment method, so
    each time a payment method is used, the workflow will be applied.
    """
    _name = "magento.sale.workflow.process"
    _description = "Magento Sale Workflow Process"
    
    @api.multi
    @api.depends('payment_method_ids')
    def set_payment_methods_count(self):
        for record in self :
            record.payment_methods_count = len(record.payment_method_ids)

    name = fields.Char()
    picking_policy = fields.Selection(
        selection=[('direct', 'Deliver each product when available'),
                   ('one', 'Deliver all products at once')],
        string='Shipping Policy',
        default='direct',
    )
    invoice_policy = fields.Selection(selection=[('order','Ordered Quantities'),
                                                 ('delivery','Shipped Quantities')],
                                        string = 'Invoice Policy',
                                        default='order')
                                                
    validate_order = fields.Boolean(string='Validate Order')
    create_invoice = fields.Boolean(string='Create Invoice')
    validate_invoice = fields.Boolean(string='Validate Invoice')
    validate_picking = fields.Boolean(string='Confirm and Close Picking')
    invoice_date_is_order_date = fields.Boolean(
        string='Force Invoice Date',
        help="When checked, the invoice date will be "
             "the same than the order's date"
    )
    warning = fields.Text('Warning Message', translate=True,
                          help='If set, display the message when a '
                               'user selects the process on a sale order')
    team_id = fields.Many2one(comodel_name='crm.team',oldname='section_id',
                                 string='Sales Team')
    
    payment_method_ids = fields.One2many('magento.payment.method.ept','magento_workflow_process_id','Payment Methods')
    payment_methods_count = fields.Integer(string="Payment Methods count",compute="set_payment_methods_count",store=True)
    
    @api.multi
    def view_payment_methods(self):
        payment_method_ids = self.mapped('payment_method_ids')
        xmlid=('odoo_magento2_ept','act_payment_method_form')
        action = self.env['ir.actions.act_window'].for_xml_id(*xmlid)
        action['domain']= "[('id','in',%s)]" % payment_method_ids.ids
        if not payment_method_ids : 
            return {'type': 'ir.actions.act_window_close'}
        if len(payment_method_ids) == 1 :
            ref = self.env.ref('odoo_magento2_ept.payment_method_view_form')
            action['views'] = [(ref.id, 'form')]
            action['res_id'] = payment_method_ids[0].id if payment_method_ids else False
            return action
        return action
