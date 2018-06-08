# -*- coding: utf-8 -*-
###############################################################################
#
#    sale_automatic_workflow for odoo
#    Copyright (C) 2011 Akretion Sébastien BEAU <sebastien.beau@akretion.com>
#    Copyright 2013 Camptocamp SA (Guewen Baconnier)
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

"""
Some comments about the implementation

In order to validate the invoice and the picking, we have to use
scheduled actions, because if we directly jump the various steps in the
workflow of the invoice and the picking, the sale order workflow will be
broken.

The explanation is 'simple'. Example with the invoice workflow: When we
are in the sale order at the workflow router, a transition like a signal
or condition will change the step of the workflow to the step 'invoice';
this step will launch the creation of the invoice.  If the invoice is
directly validated and reconciled with the payment, the subworkflow will
end and send a signal to the sale order workflow.  The problem is that
the sale order workflow has not yet finished to apply the step 'invoice',
so the signal of the subworkflow will be lost because the step 'invoice'
is still not finished. The step invoice should be finished before
receiving the signal. This means that we can not directly validate every
steps of the workflow in the same transaction.

If my explanation is not clear, contact me by email and I will improve
it: sebastien.beau@akretion.com
"""

import logging
from contextlib import contextmanager
from odoo import models, api

_logger = logging.getLogger(__name__)


@contextmanager
def commit(cr):
    """
    Commit the cursor after the ``yield``, or rollback it if an
    exception occurs.

    Warning: using this method, the exceptions are logged then discarded.
    """
    try:
        yield
    except Exception:
        cr.rollback()
        _logger.exception('Error during an automatic workflow action.')
    else:
        cr.commit()


class AutomaticWorkflowJob(models.Model):
    """ Scheduler that will play automatically the validation of
    invoices, pickings...  """

    _name = 'automatic.workflow.job'

    @api.model
    def _get_domain_for_sale_validation(self):
        return [('state', '=', 'draft'),
                ('magento_workflow_process_id.validate_order', '=', True)]

    @api.model
    def _validate_sale_orders(self):
        sale_obj = self.env['sale.order']
        sales = sale_obj.search(self._get_domain_for_sale_validation())
        _logger.debug('Sale Orders to validate: %s', sales)
        for sale in sales:
            with commit(self.env.cr):
                sale.action_confirm()
    
    @api.model
    def _create_invoices(self):
        sale_obj = self.env['sale.order']
        orders = sale_obj.search([('state','=','sale'),
                                  ('magento_workflow_process_id.create_invoice','=',True),
                                  ('invoice_status','!=','invoiced')])
        for order in orders :
            if order.invoice_policy == 'order':
                order.action_invoice_create()
            if order.invoice_policy == 'delivery':
                invoicable_lines = [line for line in order.order_line if not line.is_delivery and line.invoice_status == 'to invoice'] 
                if invoicable_lines :
                    order.action_invoice_create() 
                
            
        
    @api.model
    def _validate_invoices(self):
        invoice_obj = self.env['account.invoice']
        invoices = invoice_obj.search(
            [('state', 'in', ['draft']),
             ('magento_workflow_process_id.validate_invoice', '=', True)],
        )
        _logger.debug('Invoices to validate: %s', invoices)
        for invoice in invoices:
            with commit(self.env.cr):
                invoice.action_invoice_open()
                #invoice.signal_workflow('invoice_open')

    @api.model
    def _validate_pickings(self):
        picking_obj = self.env['stock.picking']
        pickings = picking_obj.search(
            [('state', 'in', ['draft', 'confirmed', 'assigned']),
             ('magento_workflow_process_id.validate_picking', '=', True)],
        )
        _logger.debug('Pickings to validate: %s', pickings)
        if pickings:
            with commit(self.env.cr):
                pickings.validate_picking()

    @api.model
    def run_(self):
        """ Must be called from ir.cron """

        self._validate_sale_orders()
        self._create_invoices()
        self._validate_invoices()
        self._validate_pickings()
        return True    
    
    
    
    
    @api.model
    def run(self,auto_workflow_process_id=False,ids=[]):
        sale_order_obj=self.env['sale.order']
        sale_order_line_obj=self.env['sale.order.line']
        workflow_process_obj=self.env['magento.sale.workflow.process']
        if not auto_workflow_process_id:
            work_flow_process_records=workflow_process_obj.search([])
        else:
            work_flow_process_records=workflow_process_obj.browse(auto_workflow_process_id)
        if not work_flow_process_records:
            return True
        for work_flow_process_record in work_flow_process_records:
            if not ids:
                orders=sale_order_obj.search([('magento_workflow_process_id','=',work_flow_process_record.id),('state','not in',('done','cancel','sale')),('invoice_status','!=','invoiced')])#('invoiced','=',False)
            else:
                orders=sale_order_obj.search([('magento_workflow_process_id','=',work_flow_process_record.id),('id','in',ids)]) 
            if not orders:
                continue
            for order in orders:
                if order.invoice_status and order.invoice_status=='invoiced': 
                    continue
                if work_flow_process_record.validate_order:
                    try:
                        order.action_confirm()
                        order.write({'confirmation_date':order.date_order})
                    except Exception as e:
                        pass
                if work_flow_process_record.invoice_policy=='delivery':
                    continue
                if not work_flow_process_record.invoice_policy and not sale_order_line_obj.search([('product_id.invoice_policy','!=','delivery'),('order_id','in',order.ids)]):
                    continue    
                if not order.invoice_ids:
                    if work_flow_process_record.create_invoice:
                        try:
                            order.action_invoice_create()
                        except Exception as e:
                            pass
                if work_flow_process_record.validate_invoice:
                    for invoice in order.invoice_ids:
                        try:                        
                            invoice.action_invoice_open()
                        except Exception as e:
                            pass
        return True

    
    
    
                    
