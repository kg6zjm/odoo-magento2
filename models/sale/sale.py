##############################################################################
#
#    Author: Joel Grand-Guillaume
#    Copyright 2013 Camptocamp SA
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
##############################################################################

import time
import logging
from xmlrpc import client
from odoo.tools.safe_eval import safe_eval
from odoo.exceptions import except_orm
from datetime import datetime, timedelta
import odoo.addons.decimal_precision as dp
from odoo import models, fields, api,exceptions, _,osv
from odoo.addons.odoo_magento2_ept.models.backend.connector import (ConnectorUnit,get_environment)
from odoo.addons.odoo_magento2_ept.models.backend.session import ConnectorSession
from odoo.addons.odoo_magento2_ept.models.backend.exception import (NothingToDoJob,FailedJobError,IDMissingInBackend,OrderImportRuleRetry)
from odoo.addons.odoo_magento2_ept.models.logs.job import job
from odoo.addons.odoo_magento2_ept.models.unit.synchronizer import Exporter
from odoo.addons.odoo_magento2_ept.models.unit.mapper import (mapping,ImportMapper)
from odoo.addons.odoo_magento2_ept.models.unit.sale_order_onchange import (SaleOrderOnChange)
from odoo.addons.odoo_magento2_ept.models.unit.backend_adapter import (GenericAdapter,MAGENTO_DATETIME_FORMAT,)
from odoo.addons.odoo_magento2_ept.models.unit.import_synchronizer import (DelayedBatchImporter,MagentoImporter,)
from odoo.addons.odoo_magento2_ept.models.backend.backend import magento

from odoo.addons.odoo_magento2_ept.models.partner.partner import (PartnerImportMapper,AddressImportMapper)
from odoo.addons.odoo_magento2_ept.python_library.php import Php
from odoo.addons.odoo_magento2_ept.models.api_request import req
from odoo.exceptions import ValidationError
from odoo.addons.odoo_magento2_ept.models.search_criteria import create_search_criteria
from odoo.addons.odoo_magento2_ept.models.stock.stock_picking import StockPickingAdapter
from odoo.addons.odoo_magento2_ept.models.account.invoice import AccountInvoiceAdapter
from odoo.tools import float_is_zero, float_compare, DEFAULT_SERVER_DATETIME_FORMAT
from odoo.addons.odoo_magento2_ept.models.unit.import_synchronizer import IMPORT_DELTA_BUFFER

_logger = logging.getLogger(__name__)

ORDER_STATUS_MAPPING = {  
    'draft': 'pending',
    'sale':'processing',
    'done': 'complete',
    'cancel': 'canceled',
}

class MagentoSaleOrder(models.Model):
    _name = 'magento.sale.order'
    _inherit = 'magento.binding'
    _description = 'Magento Sale Order'
    _inherits = {'sale.order': 'erp_id'}

    erp_id = fields.Many2one(comodel_name='sale.order',string='Sale Order',required=True,ondelete='cascade')
    magento_order_line_ids = fields.One2many(comodel_name='magento.sale.order.line',inverse_name='magento_order_id',string='Magento Order Lines')
    total_amount = fields.Float(string='Total amount',digits=dp.get_precision('Account'))
    total_amount_tax = fields.Float(string='Total amount w. tax',digits=dp.get_precision('Account'))
    magento_order_id = fields.Integer(string='Order ID',help="'order_id' field in Magento")
    # when a sale order is modified, Magento creates a new one, cancels
    # the parent order and link the new one to the canceled parent
    magento_parent_id = fields.Many2one(comodel_name='magento.sale.order',string='Parent Order')
    storeview_id = fields.Many2one(comodel_name='magento.storeview',string='Storeview')
    store_id = fields.Many2one(related='storeview_id.store_id',string='Store',readonly=True,store=True)
    website_id = fields.Many2one(related="store_id.website_id",string='Website',readonly=True,store=True)
    
    """Import sale order from all storeview"""
    @api.multi
    def import_sale_orders(self,backends):
        storeview_obj = self.env['magento.storeview']
        for backend in backends:
            storeviews = storeview_obj.search([('backend_id', 'in', backends.ids)])
            storeviews.import_sale_orders()
            backend.write({'last_order_import_date' : datetime.now()})
        return True
    
    @api.multi
    def import_sale_order_by_number(self,backends,order_ref):
        storeview_obj = self.env['magento.storeview']
        storeviews = storeview_obj.search([('backend_id', 'in', backends.ids)])
        storeviews.import_sale_order_by_number(order_ref)
        return True
    
class SaleOrder(models.Model):
    _inherit = 'sale.order'
    
    _order = 'date_order desc, name desc'
      
    @api.multi
    @api.depends('magento_bind_ids')
    def set_magento_order_count(self):
        for record in self :
            record.magento_order_count = len(record.magento_bind_ids)   
    
    @api.multi
    @api.depends('magento_bind_ids')
    def _set_magento_info(self):
        for record in self:
            record.website_id = record.magento_bind_ids and record.magento_bind_ids[0].website_id.id or False
            record.store_id = record.magento_bind_ids and record.magento_bind_ids[0].store_id.id or False
            record.storeview_id = record.magento_bind_ids and record.magento_bind_ids[0].storeview_id.id or False        
            
    magento_order_reference = fields.Char("Magento Order Reference")
    company_currency_id = fields.Many2one(related='company_id.currency_id', readonly=True, store=True)
    website_id = fields.Many2one(comodel_name="magento.website",compute="_set_magento_info" ,string="Website",readonly=True,store=True)
    store_id = fields.Many2one(comodel_name="magento.store",compute="_set_magento_info" ,string="Store",readonly=True,store=True)
    storeview_id = fields.Many2one(comodel_name="magento.storeview",compute="_set_magento_info" ,string="Storeview",readonly=True,store=True)
        
    
    magento_bind_ids = fields.One2many(
        comodel_name='magento.sale.order',
        inverse_name='erp_id',
        string="Magento Order",
    )
    magento_order_count = fields.Integer(string="Magento Order count",compute="set_magento_order_count",store=True)
    
    payment_method_id = fields.Many2one(
        comodel_name='magento.payment.method.ept',
        string='Payment Method',
        ondelete='restrict',
    )
    amount_paid = fields.Float(digits=dp.get_precision('Account'), string='Amount Paid')

    magento_workflow_process_id = fields.Many2one(comodel_name='magento.sale.workflow.process',
                                          string='Automatic Workflow',
                                          ondelete='restrict')

    canceled_in_backend = fields.Boolean(string='Canceled in backend',
                                         readonly=True)
    # set to True when the cancellation from the backend is
    # resolved, either because the SO has been canceled or
    # because the user manually chose to keep it open
    cancellation_resolved = fields.Boolean(string='Cancellation from the '
                                                  'backend resolved')
    parent_id = fields.Many2one(comodel_name='sale.order',
                                compute='get_parent_id',
                                string='Parent Order',
                                help='A parent sales order is a sales '
                                     'order replaced by this one.')
    need_cancel = fields.Boolean(compute='_need_cancel',
                                 string='Need to be canceled',
                                 help='Has been canceled on the backend'
                                      ', need to be canceled.')
    parent_need_cancel = fields.Boolean(
        compute='_parent_need_cancel',
        string='A parent sales order needs cancel',
        help='A parent sales order has been canceled on the backend'
             ' and needs to be canceled.',
    )
    
    magento_order_status = fields.Char('Magento Order Status')
    is_paid_in_magento = fields.Boolean(string="Is Paid in Magento?")
    invoice_policy = fields.Selection([('order','Ordered Quantity'),
                                       ('delivery','Delivered Quantity')],
                                      string='Invoice Policy',readonly=True,states={'draft': [('readonly', False)], 'sent': [('readonly', False)]}, copy=False)
    
    _sql_constraints = [
        ('name_uniq', 'unique(name, company_id,website_id)', 'Order Reference must be unique per Company and Website!'),
    ]

    @api.multi
    def view_magento_order(self):
        magento_order_ids = self.mapped('magento_bind_ids')
        xmlid=('odoo_magento2_ept','action_magento_sale_order')
        action = self.env['ir.actions.act_window'].for_xml_id(*xmlid)
        action['domain']= "[('id','in',%s)]" % magento_order_ids.ids
        if not magento_order_ids : 
            return {'type': 'ir.actions.act_window_close'}
        return action
    
    
    @api.one
    @api.depends('magento_bind_ids', 'magento_bind_ids.magento_parent_id')
    def get_parent_id(self):
        """ Return the parent order.

        For Magento sales orders, the magento parent order is stored
        in the binding, get it from there.
        """
        for order in self:
            if not order.magento_bind_ids:
                continue
            # assume we only have 1 SO in odoo for 1 SO in Magento
            magento_order = order.magento_bind_ids[0]
            if magento_order.magento_parent_id:
                self.parent_id = magento_order.magento_parent_id.erp_id
                
    @api.one
    @api.depends('canceled_in_backend', 'cancellation_resolved')
    def _need_cancel(self):
        """ Return True if the sales order need to be canceled
        (has been canceled on the Backend)
        """
        self.need_cancel = (self.canceled_in_backend and
                            not self.cancellation_resolved)

    @api.one
    @api.depends('need_cancel', 'parent_id',
                 'parent_id.need_cancel', 'parent_id.parent_need_cancel')
    def _parent_need_cancel(self):
        """ Return True if at least one parent sales order need to
        be canceled (has been canceled on the backend).
        Follows all the parent sales orders.
        """
        self.parent_need_cancel = False
        order = self.parent_id
        while order:
            if order.need_cancel:
                self.parent_need_cancel = True
            order = order.parent_id

    @api.multi
    def _try_auto_cancel(self):
        """ Try to automatically cancel a sales order canceled
        in a backend.

        If it can't cancel it, does nothing.
        """
        resolution_msg = _("<p>Resolution:<ol>"
                           "<li>Cancel the linked invoices, delivery "
                           "orders, automatic payments.</li>"
                           "<li>Cancel the sales order manually.</li>"
                           "</ol></p>")
        for order in self:
            state = order.state
            if state == 'cancel':
                continue
            elif state == 'done':
                message = _("The sales order cannot be automatically "
                            "canceled because it is already done.")
            else :
                try:
                    order.action_cancel()
                except (osv.osv.except_osv, osv.orm.except_orm,
                        exceptions.Warning):
                    # the 'cancellation_resolved' flag will stay to False
                    message = _("The sales order could not be automatically "
                                "canceled.") + resolution_msg
                else:
                    message = _("The sales order has been automatically "
                                "canceled.")
            order.message_post(body=message)
    
    @api.multi
    def _log_canceled_in_backend(self):
        message = _("The sales order has been canceled on the backend.")
        self.message_post(body=message)
        for order in self:
            message = _("Warning: the origin sales order %s has been canceled "
                        "on the backend.") % order.name
            if order.picking_ids:
                order.picking_ids.message_post(body=message)
            if order.invoice_ids:
                order.invoice_ids.message_post(body=message)

    @api.model
    def create(self, values):
        order = super(SaleOrder, self).create(values)
        if values.get('canceled_in_backend'):
            order._log_canceled_in_backend()
            order._try_auto_cancel()
        return order

    @api.multi
    def cancel_order_on_magento(self):
        if self.state == 'cancel':
            session = ConnectorSession(self.env.cr, self.env.uid,
                                       context=self.env.context)
            for order in self:
                for magento_order in order.magento_bind_ids:
                    magento_order.write({'magento_order_status' : 'canceled'})
                    export_state_change.delay(session,'magento.sale.order',magento_order.id,
                        # so if the state changes afterwards,
                        # it won't be exported
                        allowed_states=['cancel'],
                        description="Cancel sales order %s" %
                                    magento_order.magento_id)
    
    @api.multi
    def write(self, vals):
        result = super(SaleOrder, self).write(vals)
        if vals.get('canceled_in_backend'):
            self._log_canceled_in_backend()
            self._try_auto_cancel()
        return result

    @api.multi
    def action_cancel(self):
        res = super(SaleOrder, self).action_cancel()
        for sale in self:
            # the sales order is canceled => considered as resolved
            if (sale.canceled_in_backend and
                    not sale.cancellation_resolved):
                sale.write({'cancellation_resolved': True})
        return res
    
    @api.multi
    def ignore_cancellation(self, reason):
        """ Manually set the cancellation from the backend as resolved.

        The user can choose to keep the sales order active for some reason,
        it only requires to push a button to keep it alive.
        """
        message = (_("Despite the cancellation of the sales order on the "
                     "backend, it should stay open.<br/><br/>Reason: %s") %
                   reason)
        self.message_post(body=message)
        self.write({'cancellation_resolved': True})
        return True


    @api.multi
    def automatic_payment(self, amount=None):
        """ Create the payment entries to pay a sale order, respecting
        the payment terms.
        If no amount is defined, it will pay the residual amount of the sale
        order.
        """
        self.ensure_one()
        method = self.payment_method_id
        if not method:
            raise exceptions.Warning(
                _("An automatic payment can not be created for the sale "
                  "order %s because it has no payment method.") % self.name
            )

        if not method.journal_id:
            raise exceptions.Warning(
                _("An automatic payment should be created for the sale order"
                  " %s but the payment method '%s' has no journal defined.") %
                (self.name, method.name)
            )

        journal = method.journal_id
        date = self.date_order[:10]
        account_payment_obj = self.env['account.payment']
        if self.amount_total == amount : 
            self.is_paid_in_magento = True
        self.amount_paid = amount
        currency = self.pricelist_id and self.pricelist_id.currency_id and self.pricelist_id.currency_id.id
        vals = {
                'journal_id':method.journal_id.id,
                'communication':self.name,
                'currency_id':currency,
                'payment_type':'inbound',
                'partner_id':self.partner_invoice_id.id,
                'amount':amount,
                'payment_method_id':method.journal_id.inbound_payment_method_ids and method.journal_id.inbound_payment_method_ids[0].id,
                'partner_type':'customer',
                        }
        invoices = self.env['account.invoice'].search([('state','in',['open']),('sale_id','=',self.id)])
        new_rec=account_payment_obj.create(vals)
        if invoices:
            new_rec.write({'invoice_ids' : [(6,0,invoices.ids)]})
            new_rec.post()
        return True

    @api.multi
    def add_payment(self, journal_id, amount, date=None, description=None):
        """ Generate payment move lines of a certain amount linked
        with the sale order.
        """
        self.ensure_one()
        journal_model = self.env['account.journal']
        if date is None:
            date = self.date_order
        journal = journal_model.browse(journal_id)
        self._add_payment(journal, amount, date, description)
        return True

    @api.multi
    def _add_payment(self, journal, amount, date, description=None):
        """ Generate move lines entries to pay the sale order. """
        move_model = self.env['account.move']
        #period_model = self.env['account.period']
        #period = period_model.find(dt=date)
        move_name = description or self._get_payment_move_name(journal, date)
        move_vals = self._prepare_payment_move(move_name, journal,date)
        move_lines = self._prepare_payment_move_lines(move_name, journal, amount, date)

        move_vals['line_ids'] = [(0, 0, line) for line in move_lines]
        move_model.create(move_vals)

    @api.model
    def _get_payment_move_name(self, journal, date):
        sequence = journal.sequence_id
        if not sequence:
            raise exceptions.Warning(_('Please define a sequence on the '
                                       'journal %s.') % journal.name)
        if not sequence.active:
            raise exceptions.Warning(_('Please activate the sequence of the '
                                       'journal %s.') % journal.name)
        name = journal.with_context(ir_sequence_date=date).sequence_id.next_by_id()
        return name

    @api.multi
    def _prepare_payment_move(self, move_name, journal, date):
        return {'name': move_name,
                'journal_id': journal.id,
                'date': date,
                'ref': self.name,
                #'period_id': period.id,
                }
        
    @api.multi
    def _prepare_payment_move_lines(self, move_name, journal, amount, date):
        partner = self.partner_id.commercial_partner_id
        company = journal.company_id

        currency = self.env['res.currency'].browse()
        # if the lines are not in a different currency,
        # the amount_currency stays at 0.0
        amount_currency = 0.0
        if journal.currency_id and journal.currency_id != company.currency_id:
            # when the journal have a currency, we have to convert
            # the amount to the currency of the company and set
            # the journal's currency on the lines
            currency = journal.currency_id
            company_amount = currency.compute(amount, company.currency_id)
            amount_currency, amount = amount, company_amount

        # payment line (bank / cash)
        debit_line = {
            'name': move_name,
            'debit': amount,
            'credit': 0.0,
            'account_id': journal.default_credit_account_id.id,
            'journal_id': journal.id,
            #'period_id': period.id,
            'partner_id': partner.id,
            'date': date,
            'amount_currency': amount_currency,
            'currency_id': currency.id,
        }

        # payment line (receivable)
        credit_line = {
            'name': move_name,
            'debit': 0.0,
            'credit': amount,
            'account_id': partner.property_account_receivable_id.id,
            'journal_id': journal.id,
            #'period_id': period.id,
            'partner_id': partner.id,
            'date': date,
            'amount_currency': -amount_currency,
            'currency_id': currency.id,
            'sale_ids': [(4, self.id)],
        }
        return debit_line, credit_line

    @api.onchange('payment_method_id')
    def onchange_payment_method_id_set_payment_term(self):
        if not self.payment_method_id:
            return
        method = self.payment_method_id
        if method.payment_term_id:
            self.payment_term_id = method.payment_term_id.id

    @api.onchange('payment_method_id')
    def onchange_payment_method_set_workflow(self):
        if not self.payment_method_id:
            return
        method = self.payment_method_id
        workflow = method.magento_workflow_process_id
        if workflow:
            self.magento_workflow_process_id = workflow

    @api.multi
    def _prepare_invoice(self):
        invoice_vals = super(SaleOrder,self)._prepare_invoice()
        workflow = self.magento_workflow_process_id
        invoice_vals['sale_id'] = self.id
        if not workflow:
            return invoice_vals
        invoice_vals['magento_workflow_process_id'] = workflow.id
        if self.payment_method_id :
            invoice_vals['magento_payment_method_id']=self.payment_method_id.id
        if workflow.invoice_date_is_order_date:
            invoice_vals['date_invoice'] = self.date_order
            
        vals = {'journal_id':self.payment_method_id.invoice_journal_id.id}
        if self.payment_method_id.payment_term_id:
            vals.update({'payment_term_id':self.payment_method_id.payment_term_id.id})
        invoice_vals.update(vals)
        if self.magento_bind_ids and self.magento_bind_ids.backend_id:
            invoice_vals.update({
                'backend_id' : self.magento_bind_ids.backend_id.id,
                'is_magento_invoice' : True
                })
            
        return invoice_vals

    @api.onchange('magento_workflow_process_id')
    def onchange_workflow_process_id(self):
        if not self.magento_workflow_process_id:
            return
        workflow = self.magento_workflow_process_id
        if workflow.picking_policy:
            self.picking_policy = workflow.picking_policy
        if workflow.invoice_policy:
            self.invoice_policy = workflow.invoice_policy
        if workflow.team_id:
            self.team_id = workflow.team_id.id
        if workflow.warning:
            warning = {'title': _('Workflow Warning'),
                       'message': workflow.warning}
            return {'warning': warning}

    
    @api.multi
    def action_view_parent(self):
        """ Return an action to display the parent sales order """
        self.ensure_one()

        parent = self.parent_id
        if not parent:
            return

        view_xmlid = 'sale.view_order_form'
        if parent.state in ('draft', 'sent', 'cancel'):
            action_xmlid = 'sale.action_quotations'
        else:
            action_xmlid = 'sale.action_orders'

        action = self.env.ref(action_xmlid).read()[0]

        view = self.env.ref(view_xmlid)
        action['views'] = [(view.id if view else False, 'form')]
        action['res_id'] = parent.id
        return action

    @api.multi
    def action_confirm(self):
        result = super(SaleOrder,self).action_confirm()
        for order in self:
            """ Check is shipping line added in magento order?
            if shipping line is not there then set invoice_shipping_on_delivery field to False 
            because if this field is true then this order's every shipment transfer it will add
            shipping line in sale order.
            """ 
            if order.magento_bind_ids:
                order.picking_ids.write({'backend_id' : order.magento_bind_ids[0].backend_id.id})
            if order.magento_bind_ids:
                no_shipping_line = all([not line.is_delivery for line in order.order_line])
                if no_shipping_line:
                    order.invoice_shipping_on_delivery = False
    
    @api.multi
    def get_magento_order_status(self):
        for order in self:
            for magento_order in order.magento_bind_ids:
                session = ConnectorSession(self.env.cr, self.env.uid,
                                   context=self.env.context)
                backend_id = magento_order.backend_id.id
                env = get_environment(session, magento_order._name, backend_id)
                adapter = env.get_connector_unit(SaleOrderAdapter)
                if magento_order.magento_id :
                    status = adapter.get_status(magento_order.magento_id)
                    if status :
                        order.write({'magento_order_status':status})

class SpecialOrderLineBuilder(ConnectorUnit):
    """ Base class to build a sales order line for a sales order

    Used when extra order lines have to be added in a sales order
    but we only know some parameters (product, price, ...), for instance,
    a line for the shipping costs or the gift coupons.

    It can be subclassed to customize the way the lines are created.

    Usage::

        builder = self.get_connector_for_unit(ShippingLineBuilder,
                                              model='sale.order.line')
        builder.price_unit = 100
        builder.get_line()

    """
    _model_name = None

    def __init__(self, connector_env):
        super(SpecialOrderLineBuilder, self).__init__(connector_env)
        self.product = None  # id or browse_record
        # when no product_id, fallback to a product_ref
        self.product_ref = None  # tuple (module, xmlid)
        self.price_unit = None
        self.quantity = 1
        self.sign = 1
        self.sequence = 980

    def get_line(self):
        assert self.product_ref or self.product
        assert self.price_unit is not None

        product = self.product
        if product is None:
            product = self.env.ref('.'.join(self.product_ref))

        if not isinstance(product, models.BaseModel):
            product = self.env['product.product'].browse(product)
        return {'product_id': product.id,
                'name': product.name,
                'product_uom': product.uom_id.id,
                'product_uom_qty': self.quantity,
                'price_unit': self.price_unit * self.sign,
                'sequence': self.sequence}


class ShippingLineBuilder(SpecialOrderLineBuilder):
    """ Return values for a Shipping line """
    _model_name = None

    def __init__(self, connector_env):
        super(ShippingLineBuilder, self).__init__(connector_env)
        self.product_ref = ('odoo_magento2_ept', 'product_product_shipping')
        self.sequence = 999


class CashOnDeliveryLineBuilder(SpecialOrderLineBuilder):
    """ Return values for a Cash on Delivery line """
    _model_name = None
    _model_name = None

    def __init__(self, connector_env):
        super(CashOnDeliveryLineBuilder, self).__init__(connector_env)
        self.product_ref = ('odoo_magento2_ept',
                            'product_product_cash_on_delivery')
        self.sequence = 995


class GiftOrderLineBuilder(SpecialOrderLineBuilder):
    """ Return values for a Gift line """
    _model_name = None

    def __init__(self, connector_env):
        super(GiftOrderLineBuilder, self).__init__(connector_env)
        self.product_ref = ('odoo_magento2_ept',
                            'product_product_gift')
        self.sign = -1
        self.gift_code = None
        self.sequence = 990

    def get_line(self):
        line = super(GiftOrderLineBuilder, self).get_line()
        if self.gift_code:
            line['name'] = "%s [%s]" % (line['name'], self.gift_code)
        return line


class SurchargeLineBuilder(SpecialOrderLineBuilder):
    """ Return values for a Paypal surcharge/Credit Card surcharge line """
    _model_name = None

    def __init__(self, connector_env):
        super(SurchargeLineBuilder, self).__init__(connector_env)
        self.product_ref=('odoo_magento2_ept','product_product_surcharge')
        self.sequence = 999
        self.name = None

    def get_line(self):
        assert self.price_unit is not None
        line=super(SurchargeLineBuilder, self).get_line()
        if self.name:
            line['name'] =self.name
        return line

class MagentoSaleOrderLine(models.Model):
    _name = 'magento.sale.order.line'
    _inherit = 'magento.binding'
    _description = 'Magento Sale Order Line'
    _inherits = {'sale.order.line': 'erp_id'}

    magento_order_id = fields.Many2one(comodel_name='magento.sale.order',
                                       string='Magento Sale Order',
                                       required=True,
                                       ondelete='cascade',
                                       index=True)
    erp_id = fields.Many2one(comodel_name='sale.order.line',
                                 string='Sale Order Line',
                                 required=True,
                                 ondelete='cascade')
    backend_id = fields.Many2one(
        related='magento_order_id.backend_id',
        string='Instance',
        readonly=True,
        store=True,
        # override 'magento.binding', can't be INSERTed if True:
        required=False,
    )
    notes = fields.Char()

    @api.model
    def create(self, vals):
        magento_order_id = vals['magento_order_id']
        binding = self.env['magento.sale.order'].browse(magento_order_id)
        vals['order_id'] = binding.erp_id.id
        binding = super(MagentoSaleOrderLine, self).create(vals)
        # FIXME triggers function field
        # The amounts (amount_total, ...) computed fields on 'sale.order' are
        # not triggered when magento.sale.order.line are created.
        # It might be a v8 regression, because they were triggered in
        # v7. Before getting a better correction, force the computation
        # by writing again on the line.
        line = binding.erp_id
        line.write({'price_unit': line.price_unit})
        return binding


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'
    
    @api.depends('state', 'product_uom_qty', 'qty_delivered', 'qty_to_invoice', 'qty_invoiced')
    def _compute_invoice_status(self):
        """
        Compute the invoice status of a SO line. Possible statuses:
        - no: if the SO is not in status 'sale' or 'done', we consider that there is nothing to
          invoice. This is also hte default value if the conditions of no other status is met.
        - to invoice: we refer to the quantity to invoice of the line. Refer to method
          `_get_to_invoice_qty()` for more information on how this quantity is calculated.
        - upselling: this is possible only for a product invoiced on ordered quantities for which
          we delivered more than expected. The could arise if, for example, a project took more
          time than expected but we decided not to invoice the extra cost to the client. This
          occurs onyl in state 'sale', so that when a SO is set to done, the upselling opportunity
          is removed from the list.
        - invoiced: the quantity invoiced is larger or equal to the quantity ordered.
        """
        precision = self.env['decimal.precision'].precision_get('Product Unit of Measure')
        for line in self:
            if not line.order_id.invoice_policy or line.product_id.invoice_policy == 'cost':
                if line.state not in ('sale', 'done'):
                    line.invoice_status = 'no'
                elif not float_is_zero(line.qty_to_invoice, precision_digits=precision):
                    line.invoice_status = 'to invoice'
                elif line.state == 'sale' and line.product_id.invoice_policy == 'order' and\
                        float_compare(line.qty_delivered, line.product_uom_qty, precision_digits=precision) == 1:
                    line.invoice_status = 'upselling'
                elif float_compare(line.qty_invoiced, line.product_uom_qty, precision_digits=precision) >= 0:
                    line.invoice_status = 'invoiced'
                else:
                    line.invoice_status = 'no'
            else:
                if line.state not in ('sale', 'done'):
                    line.invoice_status = 'no'
                elif not float_is_zero(line.qty_to_invoice, precision_digits=precision):
                    line.invoice_status = 'to invoice'
                elif line.state == 'sale' and line.order_id.invoice_policy == 'order' and\
                        float_compare(line.qty_delivered, line.product_uom_qty, precision_digits=precision) == 1:
                    line.invoice_status = 'upselling'
                elif float_compare(line.qty_invoiced, line.product_uom_qty, precision_digits=precision) >= 0:
                    line.invoice_status = 'invoiced'
                else:
                    line.invoice_status = 'no'
    
    @api.depends('product_id.invoice_policy','order_id.invoice_policy', 'order_id.state')
    def _compute_qty_delivered_updateable(self):
        for line in self:
            if not line.order_id.invoice_policy or line.product_id.invoice_policy == 'cost':
                line.qty_delivered_updateable = line.product_id.invoice_policy in ('order', 'delivery') and line.order_id.state == 'sale' and line.product_id.service_type == 'manual'
            else:
                line.qty_delivered_updateable = line.order_id.invoice_policy in ('order', 'delivery') and line.order_id.state == 'sale' and line.product_id.service_type == 'manual'
            

    @api.depends('qty_invoiced', 'qty_delivered', 'product_uom_qty', 'order_id.state')
    def _get_to_invoice_qty(self):
        """
        Compute the quantity to invoice. If the invoice policy is order, the quantity to invoice is
        calculated from the ordered quantity. Otherwise, the quantity delivered is used.
        """
        for line in self:
            if not line.order_id.invoice_policy or line.product_id.invoice_policy == 'cost':
                if line.order_id.state in ['sale', 'done']:
                    if line.product_id.invoice_policy == 'order':
                        line.qty_to_invoice = line.product_uom_qty - line.qty_invoiced
                    else:
                        if line.product_id.type=='service':
                            if line.product_uom_qty-line.qty_invoiced>0.0:
                                line.qty_to_invoice=line.product_uom_qty-line.qty_invoiced
                        else:
                            line.qty_to_invoice = line.qty_delivered - line.qty_invoiced
                else:
                    line.qty_to_invoice = 0
            else:
                if line.order_id.state in ['sale', 'done']:
                    if line.order_id.invoice_policy == 'order':
                        line.qty_to_invoice = line.product_uom_qty - line.qty_invoiced
                    else:
                        if line.product_id.type=='service':
                            if line.product_uom_qty-line.qty_invoiced>0.0:
                                line.qty_to_invoice=line.product_uom_qty-line.qty_invoiced
                        else:
                            line.qty_to_invoice = line.qty_delivered - line.qty_invoiced
                else:
                    line.qty_to_invoice = 0

    
    magento_bind_ids = fields.One2many(
        comodel_name='magento.sale.order.line',
        inverse_name='erp_id',
        string="Magento Bindings",
    )
    
    qty_delivered_updateable = fields.Boolean(compute='_compute_qty_delivered_updateable', string='Can Edit Delivered', readonly=True, default=True)
    
    invoice_status = fields.Selection([
        ('upselling', 'Upselling Opportunity'),
        ('invoiced', 'Fully Invoiced'),
        ('to invoice', 'To Invoice'),
        ('no', 'Nothing to Invoice')
        ], string='Invoice Status', compute='_compute_invoice_status', store=True, readonly=True, default='no')
    
    qty_to_invoice = fields.Float(
        compute='_get_to_invoice_qty', string='To Invoice', store=True, readonly=True,
        digits=dp.get_precision('Product Unit of Measure'), default=0.0)


@magento
class SaleOrderAdapter(GenericAdapter):
    _model_name = ['magento.sale.order']
    _magento_model = 'sales_order'
    _admin_path = '{model}/view/order_id/{id}'
    _path = '/V1/orders'

    def search(self, filters=None, from_date=None, to_date=None,
               magento_storeview_ids=None):
        """ Search records according to some criteria
        and returns a list of ids

        :rtype: list
        """
        dt_fmt = MAGENTO_DATETIME_FORMAT
        if from_date is not None:
            filters.setdefault('created_at', {})
            filters['created_at']['from'] = from_date.strftime(dt_fmt)
        if to_date is not None:
            filters.setdefault('created_at', {})
            filters['created_at']['to'] = to_date.strftime(dt_fmt)
        if magento_storeview_ids is not None:
            filters['store_id'] = {'in': magento_storeview_ids}
            
        filters = create_search_criteria(filters)
        filters.setdefault('imported',False)

        qs = Php.http_build_query(filters)
        url = "%s?%s"%(self._path,qs)
        
        
        result = []
        content = req(self.backend_record,url)
        for record in content.get('items') :
            result.append(record['entity_id'])
        return result
    
    def read(self, id, attributes=None):
        """ Returns the information of a record

        :rtype: dict
        """
        #content = req(self.backend_record,self._path+"/%s"%(id))
        content = super(SaleOrderAdapter,self).read(id,attributes)
        if content['billing_address'] :
            content['billing_address']['middlename'] = content['billing_address'].get('middlename',False)
        if content.get('extension_attributes',False) and content['extension_attributes'].get('shipping_assignments',False) and content['extension_attributes']['shipping_assignments'][0].get('shipping',False):
            content['shipping_address'] = content['extension_attributes']['shipping_assignments'][0]['shipping'].get('address')
            if content['extension_attributes']['shipping_assignments'][0]['shipping'].get('method',False) :
                content['shipping_method'] = content['extension_attributes']['shipping_assignments'][0]['shipping']['method']
        """
        if not content.get('shipping_address',False) :
            content['shipping_address'] = content['billing_address']
        """
        if content.get('customer_group_id') == 0 :
            content['customer_group_id'] = str(content['customer_group_id'])
        if content.get('relation_parent_id') :
            content['relation_parent_real_id'] = content['relation_parent_id']
        #Added for Import Order which contain bundle product. When Bundle product import is supported need to remove this.
        if content.get('items') :
            items = content.get('items')
            for line in items :
                if line.get('product_type') == 'bundle' :
                    index = items.index(line)
                    del(items[index])
                    continue
            content['items'] = items 
        return content
    
    def get_parent(self, id):
        #content = req(self.backend_record,self._path+"/%s"%(id))
        content = super(SaleOrderAdapter,self).read(id)
        parent_id=False
        if content.get('relation_parent_id') :
            parent_id = content.get('relation_parent_id',False)
        return parent_id
    
    
    def add_comment(self, id, status, comment=None, notify=False):
        data = {
                "statusHistory":{
                                 "parentId":id,
                                 "status":status,
                                 "comment":comment,
                                 "isCustomerNotified":notify
                                 }
                }
        
        url = "%s/%s/comments"%(self._path,id)
        
        result = req(self.backend_record,url,method="POST",data=data)
        
        return result
    
    def get_status(self,id):
        url = "%s/%s/statuses"%(self._path,id)
        result = req(self.backend_record,url)
        if isinstance(result,str):
            return result
        return

    def cancel_order(self,id):
        url = '%s/%s/cancel'%(self._path,id)
        result = req(self.backend_record,url,method="POST")
        if result != True :
            raise FailedJobError(result)
        return result



@magento
class SaleOrderBatchImport(DelayedBatchImporter):
    _model_name = ['magento.sale.order']

    def _import_record(self, record_id, **kwargs):
        """ Import the record directly """
        return super(SaleOrderBatchImport, self)._import_record(
            record_id, max_retries=0, priority=5)

    def run(self, filters=None):
        """ Run the synchronization """
        if filters is None:
            filters = {}
        filters['state'] = {'neq': 'canceled'}
        
        from_date = filters.pop('from_date', None)
        to_date = filters.pop('to_date', None)
        magento_storeview_ids = [filters.pop('magento_storeview_id')]
        record_ids = self.backend_adapter.search(
            filters,
            from_date=from_date,
            to_date=to_date,
            magento_storeview_ids=magento_storeview_ids)
        _logger.info('search for magento saleorders %s returned %s',
                     filters, record_ids)
        increment_id = filters.pop('increment_id', None)
        
        
        if increment_id:
            so_importer = self.unit_for(SaleOrderImporter)
            for record in record_ids:
                try:
                    so_importer.run(record)
                except Exception as error:
                    raise ValidationError(str(error))
                
            #self.env['automatic.workflow.job'].run()
        else:
            import_start_time = to_date or datetime.now()
            next_time = import_start_time - timedelta(seconds=IMPORT_DELTA_BUFFER)
            next_time = fields.Datetime.to_string(next_time)
            storeview_binder = self.binder_for('magento.storeview')
            for magento_storeview_id in magento_storeview_ids:
                storeview = storeview_binder.to_openerp(magento_storeview_id,browse=True)
                if storeview:
                    storeview.write({'import_orders_from_date': next_time})
                else :
                    raise FailedJobError('To update next import date, %s storeview not found'%(storeview.name))
        
            if self.backend_record.allow_so_import_on_fly:
                so_importer = self.unit_for(SaleOrderImporter)
                for record in record_ids:
                    try:
                        so_importer.run(record)
                    except Exception as error:
                        self._import_record(record)
                        continue
                #self.env['automatic.workflow.job'].run()
            else:
                for record_id in record_ids:
                    self._import_record(record_id)


@magento
class SaleImportRule(ConnectorUnit):
    _model_name = ['magento.sale.order']

    def _rule_always(self, record, method):
        """ Always import the order """
        return True

    def _rule_never(self, record, method):
        """ Never import the order """
        raise NothingToDoJob('Orders with payment method %s '
                             'are never imported.' %
                             record['payment']['method'])

    def _rule_authorized(self, record, method):
        """ Import the order only if payment has been authorized. """
        
        if not record.get('payment', {}).get('base_amount_authorized'):
            raise OrderImportRuleRetry('The order has not been authorized.\n'
                                       'The import will be retried later.')

    def _rule_paid(self, record, method):
        """ Import the order only if it has received a payment """
        if not record.get('payment', {}).get('amount_paid'):
            raise OrderImportRuleRetry('The order has not been paid.\n'
                                       'The import will be retried later.')

    _rules = {'always': _rule_always,
              'paid': _rule_paid,
              'authorized': _rule_authorized,
              'never': _rule_never,
              }

    def _rule_global(self, record, method):
        """ Rule always executed, whichever is the selected rule """
        # the order has been canceled since the job has been created
        order_id = record['increment_id']
        if record['state'] == 'canceled':
            raise NothingToDoJob('Order %s canceled' % order_id)
        max_days = method.days_before_cancel
        if max_days:
            fmt = '%Y-%m-%d %H:%M:%S'
            order_date = datetime.strptime(record['created_at'], fmt)
            if order_date + timedelta(days=max_days) < datetime.now():
                raise NothingToDoJob('Import of the order %s canceled '
                                     'because it has not been paid since %d '
                                     'days' % (order_id, max_days))

    def check(self, record):
        """ Check whether the current sale order should be imported
        or not. It will actually use the payment method configuration
        and see if the choosed rule is fullfilled.

        :returns: True if the sale order should be imported
        :rtype: boolean
        """
        website_id = record.get('website_id',False) 
        website_binder = self.binder_for('magento.website')
        oe_website = website_binder.to_openerp(website_id,browse=True)
        payment_method = record['payment']['method']
        magento_payment_method = self.env['magento.payment.method'].search([('payment_method_code','=',payment_method),('backend_id','=',self.backend_record.id)],limit=1)
        if not magento_payment_method:
            self.backend_record.import_payment_method()
            magento_payment_method = self.env['magento.payment.method'].search([('payment_method_code','=',payment_method),('backend_id','=',self.backend_record.id)],limit=1)
        method = False
        if oe_website and magento_payment_method:
            method = self.env['magento.payment.method.ept'].search([('payment_method_code_id', '=', magento_payment_method.id),('website_id','=',oe_website.id)],limit=1)
        if not method:
            raise FailedJobError(
                "The configuration is missing for the Payment Method '%s'.\n\n"
                "Resolution:\n"
                "- Go to "
                "'Magento > Settings >  Payment Methods\n"
                "- Create a new Payment Method with name '%s' and website %s\n"
                "-Eventually  link the Payment Method to an existing Workflow "
                "Process or create a new one." % (payment_method,
                                                  payment_method,
                                                  oe_website.name))
        self._rule_global(record, method)
        self._rules[method.import_rule](self, record, method)


@magento
class SaleOrderMoveComment(ConnectorUnit):
    _model_name = ['magento.sale.order']

    def move(self, binding):
        pass


@magento
class SaleOrderImportMapper(ImportMapper):
    _model_name = ['magento.sale.order']

    direct = [('increment_id', 'magento_id'),
              ('order_id', 'magento_order_id'),
              ('grand_total', 'total_amount'),
              ('tax_amount', 'total_amount_tax'),
              ('store_id', 'storeview_id'),
              ('entity_id','magento_id'),
              ('entity_id','magento_order_id'),
              ('status','magento_order_status'), 
              ('increment_id','magento_order_reference')             
              ]

    children = [('items', 'magento_order_line_ids', 'magento.sale.order.line'),
                ]

    def _get_tax_id(self,website,tax_percentage,tax_include=False):
        tax_id = self.env['account.tax'].get_tax_from_rate(rate=float(tax_percentage),is_tax_included=tax_include)
        if not tax_id :
            if website.create_tax_if_not_found :
                if tax_include :
                    name = '%s %% Included'%(tax_percentage)
                else :
                    name = '%s %% '%(tax_percentage)
                tax_id = self.env['account.tax'].sudo().create({
                                                      'name':name,
                                                      'description':name,
                                                      'amount_type':'percent',
                                                      'price_include':tax_include,
                                                      'amount':float(tax_percentage),
                                                      'type_tax_use':'sale',
                                                      'account_id':website.tax_account_id.id or False,
                                                      'refund_account_id':website.tax_account_refund_id.id or False,
                                                      }
                                                     )
        if not tax_id :
            raise FailedJobError("Tax %s should exist because the import fails "
                            "in SaleOrderImport._before_import when it is "
                            " missing" % tax_percentage)
        return tax_id
    
    def _add_shipping_line(self, map_record, values):
        record = map_record.source
        amount_incl = float(record.get('shipping_incl_tax') or 0.0)
        amount_excl = float(record.get('shipping_amount') or 0.0)
        if not (amount_incl or amount_excl):
            return values
        line_builder = self.unit_for(MagentoShippingLineBuilder)
        website = self.options.storeview.website_id
        tax_include = website.tax_include_in_price
        #tax_percentage = record['extension_attributes'].get('tax_percent',False)
        tax_percentage =  record['items'][0].get('tax_percent')
        if tax_percentage and record['shipping_tax_amount'] :
            tax_id = self._get_tax_id(website, tax_percentage, tax_include)
        else :
            tax_id = False
        amount = tax_include and amount_incl or amount_excl
        discount = float(record.get('shipping_discount_amount') or 0.0)
        line_builder.price_unit = (amount - discount)
        
        if values.get('carrier_id'):
            carrier = self.env['delivery.carrier'].browse(values['carrier_id'])
            line_builder.product = carrier.product_id
        
        line_vals = line_builder.get_line()
        if tax_id :
            line_vals.update({'tax_id': [(6,0,[tax_id.id])]})
        else :
            line_vals.update({'tax_id': False})
        
        line_vals.update({'is_delivery':True})
        line = (0, 0, line_vals)
        values['order_line'].append(line)
        return values
    

    def _add_cash_on_delivery_line(self, map_record, values):
        record = map_record.source
        amount_excl = float(record.get('cod_fee') or 0.0)
        amount_incl = float(record.get('cod_tax_amount') or 0.0)
        if not (amount_excl or amount_incl):
            return values
        line_builder = self.unit_for(MagentoCashOnDeliveryLineBuilder)
        tax_include = self.options.tax_include
        line_builder.price_unit = amount_incl if tax_include else amount_excl
        line = (0, 0, line_builder.get_line())
        values['order_line'].append(line)
        return values

    def _add_gift_certificate_line(self, map_record, values):
        record = map_record.source
        if 'gift_cert_amount' not in record:
            return values
        amount = float(record['gift_cert_amount'])
        line_builder = self.unit_for(MagentoGiftOrderLineBuilder)
        line_builder.price_unit = amount
        if 'gift_cert_code' in record:
            line_builder.code = record['gift_cert_code']
        line = (0, 0, line_builder.get_line())
        values['order_line'].append(line)
        return values

    def finalize(self, map_record, values):
        values.setdefault('order_line', [])
        values = self._add_shipping_line(map_record, values)
        values = self._add_cash_on_delivery_line(map_record, values)
        values = self._add_gift_certificate_line(map_record, values)
        values.update({
            'partner_id': self.options.partner_id,
            'partner_invoice_id': self.options.partner_invoice_id,
            'partner_shipping_id': self.options.partner_shipping_id,
        })
        onchange = self.unit_for(SaleOrderOnChange)
        return onchange.play(values, values['magento_order_line_ids'])
    
    def _add_surcharge_line(self, map_record, values):
        record = map_record.source
        record = record.get('extension_attributes',{})
        if 'paycharge_fee' not in record:
            return values
        line_builder = self.unit_for(MagentoSurchargeLineBuilder)
        if 'paycharge_fee' in record:
            line_builder.name=record.get('paycharge_fee_name')
            line_builder.price_unit=record.get('paycharge_fee',0.0)
        line = (0, 0, line_builder.get_line())
        values['order_line'].append(line)
        return values
    @mapping
    def date_order(self,record):
        created_date = record.get('created_at')
        created_at = datetime.strptime(created_date, "%Y-%m-%d %H:%M:%S")
        return {'date_order' : created_at}
    @mapping
    def name(self, record):
        name = record['increment_id']
        store_id = record.get('store_id')
        store_view = self.env['magento.storeview'].search([('magento_id','=',store_id),('backend_id','=',self.backend_record.id)])
        prefix = store_view and store_view.sale_prefix
        if prefix:
            name = prefix + name
        return {'name': name}

    @mapping
    def customer_id(self, record):
        binder = self.binder_for('res.partner')
        partner_id = self.env['res.partner'].search([('magento_id','=',record.get('customer_id'))])[0]
        assert partner_id is not None, (
            "customer_id %s should have been imported in "
            "SaleOrderImporter._import_dependencies" % record['customer_id'])
        return {'partner_id': partner_id.id}

    @mapping
    def pricelist_id(self,record):
        website_binder = self.binder_for('magento.website')
        website_id = website_binder.to_openerp(record['website_id'])
        website = self.env['magento.website'].browse(website_id)
        pricelist_id = False
        if website.pricelist_id and website.pricelist_id.currency_id.name == record['order_currency_code']:
            pricelist_id = website.pricelist_id.id
        elif website.backend_id.pricelist_id and website.backend_id.pricelist_id.currency_id.name == record['order_currency_code']:
            pricelist_id = website.backend_id.pricelist_id.id
        else :            
            currency_id = self.env['res.currency'].search([('name','like',record['order_currency_code'])],limit=1).id
            pricelist = self.env['product.pricelist'].search([('currency_id','=',currency_id)],limit=1)
            pricelist_id = pricelist and pricelist.id 
        if not pricelist_id :
            raise FailedJobError('Pricelist not found for Currency code %s'%(record['order_currency_code']))
        return {'pricelist_id': pricelist_id}
    
    @mapping
    def payment(self, record):
        payment_method = record['payment']['method']
        website_id = record.get('website_id',False) 
        website_binder = self.binder_for('magento.website')
        website_id = website_binder.to_openerp(website_id)
        #website = self.session.browse('magento.website', oe_website_id)
        magento_payment_method = self.env['magento.payment.method'].search([('payment_method_code','=',payment_method),('backend_id','=',self.backend_record.id)],limit=1)
#         if not magento_payment_method:
#             self.backend_record.import_payment_method()
#             magento_payment_method = self.env['magento.payment.method'].search([('payment_method_code','=',payment_method),('backend_id','=',self.backend_record.id)],limit=1)
        method = False
        if website_id :
            method = self.env['magento.payment.method.ept'].search(
                                                       [('payment_method_code_id', '=', magento_payment_method.id),('website_id','=',website_id)],
                                                       limit=1,
                                                       )
        if not method :
            raise FailedJobError("method %s should exist because the import fails "
                        "in SaleOrderImporter._before_import when it is "
                        " missing" % record['payment']['method'])
        return {'payment_method_id': method.id}
    
    @mapping
    def warehouse_id(self,record):
        website_id = record.get('website_id',False) 
        website_binder = self.binder_for('magento.website')
        oe_website_id = website_binder.to_openerp(website_id)
        website_obj = self.env['magento.website'].browse(int(oe_website_id))
        if website_obj and website_obj.warehouse_id:
            return {'warehouse_id':website_obj.warehouse_id.id}
        return
    
    @mapping
    def website(self,record):
        website_id = record.get('website_id',False) 
        website_binder = self.binder_for('magento.website')
        oe_website_id = website_binder.to_openerp(website_id)
        assert oe_website_id, ("Website is missing!")
        return {'website_id':oe_website_id}
    
    @mapping
    def shipping_method(self, record):
        carrier_code = record.get('shipping_method')
        if not carrier_code:
            raise FailedJobError("Delivery method is not  found in Order %s"%(record.get('increment_id')))
        
        magento_carrier = self.env['magento.delivery.carrier'].search([('carrier_code','=',carrier_code),('backend_id','=',self.backend_record.id)],limit=1)
        if not magento_carrier:
            self.backend_record.import_delivery_method()
            magento_carrier = self.env['magento.delivery.carrier'].search([('carrier_code','=',carrier_code),('backend_id','=',self.backend_record.id)],limit=1)
        delivery_carrier = self.env['delivery.carrier'].search([('magento_carrier','=',magento_carrier.id)],limit=1)
        if delivery_carrier:
            result = {'carrier_id': delivery_carrier.id}
        else:
            product = self.env.ref(
                'odoo_magento2_ept.product_product_shipping')
            title = record.get('shipping_description','')
            title = title.split(' - ')[0] 
            carrier = self.env['delivery.carrier'].create({
                'name' : magento_carrier.carrier_label,
                'product_id': product.id,
                'product_name' : record.get('shipping_description',carrier_code),
                'magento_carrier' : magento_carrier.id
                })
            result = {'carrier_id': carrier.id}
        return result

    @mapping
    def sales_team(self, record):
        team = self.options.storeview.team_id
        if team:
            return {'team_id': team.id}

    @mapping
    def backend_id(self, record):
        return {'backend_id': self.backend_record.id}

    @mapping
    def user_id(self, record):
        """ Do not assign to a Salesperson otherwise sales orders are hidden
        for the salespersons (access rules)"""
        return {'user_id': False}

    @mapping
    def sale_order_comment(self, record):
        comment_mapper = self.unit_for(SaleOrderCommentImportMapper)
        map_record = comment_mapper.map_record(record)
        return map_record.values(**self.options)


@magento
class SaleOrderImporter(MagentoImporter):
    _model_name = ['magento.sale.order']

    _base_mapper = SaleOrderImportMapper

    def _must_skip(self):
        """ Hook called right after we read the data from the backend.

        If the method returns a message giving a reason for the
        skipping, the import will be interrupted and the message
        recorded in the job (if the import is called directly by the
        job, not by dependencies).

        If it returns None, the import will continue normally.

        :returns: None | str | unicode
        """
        if self.binder.to_openerp(self.magento_id):
            return _('Already imported')

    def _clean_magento_items(self, resource):
        """
        Method that clean the sale order line given by magento before
        importing it

        This method has to stay here because it allow to customize the
        behavior of the sale order.

        """
        child_items = {}  # key is the parent item id
        top_items = []

        # Group the childs with their parent
        for item in resource['items']:
            if item.get('parent_item') and item.get('parent_item').get('product_type') == 'bundle':
                continue
            if item.get('parent_item_id'):
                child_items.setdefault(item['parent_item_id'], []).append(item)
            else:
                top_items.append(item)

        all_items = []
        if top_items:
            for top_item in top_items:
                if top_item['item_id'] in child_items:
                    item_modified = self._merge_sub_items(
                        top_item['product_type'], top_item,
                        child_items[top_item['item_id']])
                    if not isinstance(item_modified, list):
                        item_modified = [item_modified]
                    all_items.extend(item_modified)
                else:
                    all_items.append(top_item)
            resource['items'] = all_items
        return resource

    def _merge_sub_items(self, product_type, top_item, child_items):
        """
        Manage the sub items of the magento sale order lines. A top item
        contains one or many child_items. For some product types, we
        want to merge them in the main item, or keep them as order line.

        This method has to stay because it allow to customize the
        behavior of the sale order according to the product type.

        A list may be returned to add many items (ie to keep all
        child_items as items.

        :param top_item: main item (bundle, configurable)
        :param child_items: list of childs of the top item
        :return: item or list of items
        """
        if product_type == 'configurable':
            item = top_item.copy()
            # For configurable product all information regarding the
            # price is in the configurable item. In the child a lot of
            # information is empty, but contains the right sku and
            # product_id. So the real product_id and the sku and the name
            # have to be extracted from the child
            for field in ['sku', 'product_id', 'name']:
                item[field] = child_items[0][field]
            return item
        if product_type == 'bundle':
            item = top_item.copy()
            for field in ['sku', 'product_id', 'name']:
                item[field] = child_items[0][field]
            return item
        return top_item

    def _import_customer_group(self, group_id):
        binder = self.binder_for('magento.res.partner.category')
        if binder.to_openerp(group_id) is None:
            importer = self.unit_for(MagentoImporter,
                                     model='magento.res.partner.category')
            importer.run(group_id)

    def _before_import(self):
        rules = self.unit_for(SaleImportRule)
        rules.check(self.magento_record)

    def _create_payment(self, binding):
        if not binding.payment_method_id.journal_id:
            return
        amount = self.magento_record.get('payment', {}).get('amount_paid')
        invoice_adapter = self.unit_for(AccountInvoiceAdapter,'account.invoice')
        filters = {'order_id':self.magento_id}
        invoices = invoice_adapter.search_read(filters)
        if invoices:
            for invoice in invoices :
                amount = invoice.get('grand_total')
                if amount:
                    amount = float(amount)  # magento gives a str
                    binding.erp_id.automatic_payment(amount)

    def _link_parent_orders(self, binding):
        """ Link the magento.sale.order to its parent orders.

        When a Magento sales order is modified, it:
         - cancel the sales order
         - create a copy and link the canceled one as a parent

        So we create the link to the parent sales orders.
        Note that we have to walk through all the chain of parent sales orders
        in the case of multiple editions / cancellations.
        """
        parent_id = self.magento_record.get('relation_parent_real_id')
        if not parent_id:
            return
        all_parent_ids = []
        while parent_id:
            all_parent_ids.append(parent_id)
            parent_id = self.backend_adapter.get_parent(parent_id)
        current_binding = binding
        for parent_id in all_parent_ids:
            parent_binding = self.binder.to_openerp(parent_id, browse=True)
            if not parent_binding:
                # may happen if several sales orders have been
                # edited / canceled but not all have been imported
                continue
            # link to the nearest parent
            current_binding.write({'magento_parent_id': parent_binding.id})
            parent_canceled = parent_binding.canceled_in_backend
            if not parent_canceled:
                parent_binding.write({'canceled_in_backend': True})
            current_binding = parent_binding

    def _after_import(self, binding):
        self._link_parent_orders(binding)
        self.create_shipment(binding)
        self.env['automatic.workflow.job'].run(binding.magento_workflow_process_id.id,binding.erp_id.ids)
        self._create_payment(binding)
        if binding.magento_parent_id:
            move_comment = self.unit_for(SaleOrderMoveComment)
            move_comment.move(binding)
        
        

    def _get_storeview(self, record):
        """ Return the tax inclusion setting for the appropriate storeview """
        storeview_binder = self.binder_for('magento.storeview')
        return storeview_binder.to_openerp(record['store_id'], browse=True)

    def _get_magento_data(self):
        """ Return the raw Magento data for ``self.magento_id`` """
        record = super(SaleOrderImporter, self)._get_magento_data()
        if not record.get('website_id'):
            storeview = self._get_storeview(record)
            record['website_id'] = storeview.store_id.website_id.magento_id
        record = self._clean_magento_items(record)
        return record

    def _import_addresses(self):
        record = self.magento_record

        # Magento allows to create a sale order not registered as a user
        is_guest_order = bool(int(record.get('customer_is_guest', 0) or 0))

        # For a guest order or when magento does not provide customer_id
        # on a non-guest order (it happens, Magento inconsistencies are
        # common)
        if (is_guest_order or not record.get('customer_id')):
            website_binder = self.binder_for('magento.website')
            oe_website_id = website_binder.to_openerp(record['website_id'])

            # search an existing partner with the same email
            partner = self.env['res.partner'].search(
                [('email', '=', record['customer_email']),
                 ('website_id', '=', oe_website_id)],
                limit=1)

            # if we have found one, we "fix" the record with the magento
            # customer id
            if partner:
                magento = partner.magento_id
                # If there are multiple orders with "customer_id is
                # null" and "customer_is_guest = 0" which share the same
                # customer_email, then we may get a magento_id that is a
                # marker 'guestorder:...' for a guest order (which is
                # set below).  This causes a problem with
                # "importer.run..." below where the id is cast to int.
                if str(magento).startswith('guestorder:'):
                    is_guest_order = True
                else:
                    record['customer_id'] = magento

            # no partner matching, it means that we have to consider it
            # as a guest order
            else:
                is_guest_order = True

        partner_binder = self.binder_for('res.partner')
        if is_guest_order:
            # ensure that the flag is correct in the record
            record['customer_is_guest'] = True
            guest_customer_id = 'guestorder:%s' % record['increment_id']
            # "fix" the record with a on-purpose built ID so we can found it
            # from the mapper
            record['customer_id'] = guest_customer_id

            address = record['billing_address']

            customer_group = record.get('customer_group_id')
            if customer_group:
                self._import_customer_group(customer_group)

            customer_record = {
                'firstname': address['firstname'],
                'middlename': address['middlename'],
                'lastname': address['lastname'],
                'prefix': address.get('prefix'),
                'suffix': address.get('suffix'),
                'email': record.get('customer_email'),
                'taxvat': record.get('customer_taxvat'),
                'group_id': customer_group,
                'gender': record.get('customer_gender'),
                'store_id': record['store_id'],
                'updated_at': False,
                'created_in': False,
                'dob': record.get('customer_dob'),
                'website_id': record.get('website_id'),
                'id' : record.get('customer_id'),
            }
            mapper = self.unit_for(PartnerImportMapper,
                                   model='res.partner')
            map_record = mapper.map_record(customer_record)
            map_record.update(guest_customer=True)
            partner_binding = self.env['res.partner'].create(
                map_record.values(for_create=True))
        else : 
            # We check that customer is exit or not if it's not then it will create new customer
            importer = self.unit_for(MagentoImporter,
                                     model='res.partner')
            importer.run(record['customer_id'])
            partner_binding = self.env['res.partner'].search([('magento_id','=',record['customer_id']),('parent_id','=',False)])
                
        if len(partner_binding) > 1:
            partner_binding = partner_binding[0]
        partner = partner_binding
        billing_address_id = self._check_addresses(record.get('billing_address'))
        shipping_address = self._check_addresses(record.get('shipping_address'))
#         if partner.id != shipping_address.id :
#             shipping_address.write({'parent_id': partner.id})
        if partner.id != billing_address_id.id or partner.id != shipping_address.id:
            if billing_address_id.is_company :
                billing_address_id.write({'parent_id' : False})
                partner.write({'parent_id' : billing_address_id.id})
                if billing_address_id.id != shipping_address.id :
                    shipping_address.write({'parent_id': billing_address_id.id})
            else :
                billing_address_id.write({'parent_id': partner.id})
                shipping_address.write({'parent_id': partner.id})
        self.partner_id = partner.id
        self.partner_invoice_id = billing_address_id.id
        self.partner_shipping_id = shipping_address.id
        
    
    def _check_addresses(self,record):
        address_mapper = self.unit_for(AddressImportMapper,'res.partner')
        address_vals = address_mapper.map_record(record).values()
        name = address_vals.get('name')
        street = address_vals.get('street')
        street2 = address_vals.get('street2')
        country_id = address_vals.get('country_id',False)
        state_id = address_vals.get('state_id',False)
        city = address_vals.get('city',False)
        pin_code = address_vals.get('zip',False)
        phone_number = address_vals.get('phone',False)        
        address = self.env['res.partner'].search([('name','=',name),('street','=',street),('street2','=',street2),('country_id','=',country_id),
                                                  ('state_id','=',state_id),('city','=',city),('zip','=',pin_code),('phone','=',phone_number)],limit=1)
        if record.get('company') :
            address = self.env['res.partner'].search([('name','=',record.get('company')),('street','=',street),('street2','=',street2),('country_id','=',country_id),
                                                  ('state_id','=',state_id),('city','=',city),('zip','=',pin_code),('phone','=',phone_number)],limit=1)

        
        if not address : 
            if address_vals.get('is_company') :
                address_vals.update({'name' : record.get('company')})
            address = self.env['res.partner'].create(address_vals)
        return address
    def _check_special_fields(self):
        if not (self.partner_id or self.partner_invoice_id or self.partner_shipping_id) :
            raise FailedJobError ("Partner is not found for Order %s"%(self.name))

    def _create_data(self, map_record, **kwargs):
        storeview = self._get_storeview(map_record.source)
        self._check_special_fields()
        return super(SaleOrderImporter, self)._create_data(
            map_record,
            tax_include=storeview.website_id.tax_include_in_price,
            partner_id=self.partner_id,
            partner_invoice_id=self.partner_invoice_id,
            partner_shipping_id=self.partner_shipping_id,
            storeview=storeview,
            **kwargs)

    def _update_data(self, map_record, **kwargs):
        storeview = self._get_storeview(map_record.source)
        self._check_special_fields()
        return super(SaleOrderImporter, self)._update_data(
            map_record,
            tax_include=storeview.website_id.tax_include_in_price,
            partner_id=self.partner_id,
            partner_invoice_id=self.partner_invoice_id,
            partner_shipping_id=self.partner_shipping_id,
            storeview=storeview,
            **kwargs)

    def _import_dependencies(self):
        self._import_addresses()
        record = self.magento_record
        items = record.get('items', [])
        for line in items:
            _logger.debug('line: %s', line)
            if 'product_id' in line:
                try :
                    self._import_dependency(line['product_id'],
                                            'magento.product.product')
                except Exception as e:
                    raise FailedJobError(e)
                
    def create_shipment(self,binding):
        picking_adapter = self.unit_for(StockPickingAdapter,'stock.picking')
        move_obj = self.env['stock.move']
        picking_obj = self.env['stock.picking']
        stock_move_line = self.env['stock.move.line']
        filters = {'order_id':self.magento_id}
        magento_product = self.env['magento.product.product']
        shipments = picking_adapter.search(filters)
        if shipments :
            for shipment in shipments :
                pack_op_ids = []
                pick_ids = []
                if not binding.picking_ids :
                    try :
                        binding.erp_id.action_confirm()
                    except :
                        raise FailedJobError("Sale order import job Failed : \n From after_import creating shipment")
                if not binding.picking_ids :
                    raise FailedJobError("Sale order import job Failed at _after_import shipment create \n Please verify configuration.")
                elif len(binding.picking_ids) > 1 :
                    pickings = picking_obj.search([('state','in',['confirmed','assigned','partially_available']),
                                                  ('id','in',binding.picking_ids.ids),
                                                  ])
                    if not pickings :
                        continue
                else :
                    pickings = binding.picking_ids
                pickings.action_confirm()
                for picking in pickings:
                    magento_picking_data = picking_adapter.read(shipment)
                    if magento_picking_data.get('tracks',False) :
                        carrier_tracking_reference = " "
                        number_of_packages = len(magento_picking_data['tracks'])
                        tracking_number = magento_picking_data['tracks']
                        if len(tracking_number) > 1:
                            for track in tracking_number:
                                carrier_tracking_reference = carrier_tracking_reference + track.get('track_number') + ','
                            picking.write({'carrier_tracking_ref':carrier_tracking_reference,'number_of_packages' : number_of_packages})
                        else : 
                            carrier_tracking_reference = magento_picking_data.get('tracks',False) and magento_picking_data.get('tracks')[0].get('track_number') or False
                            picking.write({'carrier_tracking_ref':carrier_tracking_reference,'number_of_packages' : number_of_packages})
                    for item in magento_picking_data.get('items') :
                        order_items = self.magento_record['items']
                        for order_item in order_items :
                            if order_item['product_type'] == 'configurable' and order_item['sku'] == item['sku'] :
                                mag_product_id = order_item['product_id']
                                break
                            else :
                                mag_product_id = item.get('product_id')
                        mag_qty = item.get('qty')
                        #######
                        qty_grouped = {}
                        sku = item['sku']
                        
                        magento_product = magento_product.get_magento_product(sku,self.backend_record.id)
                        product_id = magento_product.erp_id
                        move_lines = move_obj.search([('picking_id','=',picking.id),('product_id','=',product_id.id),('state','in',('confirmed','assigned','partially_available'))])
                        for move in move_lines:
    #                             for quant in move.reserved_availability:
                            key=(move.location_id.id,move.location_dest_id.id,move.product_id.id,move.product_id.uom_id.id, False)
                            if key in qty_grouped:
                                qty_grouped[key]+=move.reserved_availability
                            else:
                                qty_grouped.update({key:move.reserved_availability})
                        qty_left = mag_qty
                        for key, qty in qty_grouped.items():
                            if qty_left>qty:                                        
                                pack_op_qty=qty
                            else:
                                pack_op_qty=qty_left
                            pack_op=stock_move_line.with_context({'no_recompute':True}).create(
                                {       
                                        'product_id': key[2],
                                        'product_uom_id': key[3], 
                                        'picking_id':picking.id,
                                        'date':time.strftime('%Y-%m-%d'),                                        
                                        'qty_done':float(pack_op_qty) or 0,
                                        'result_package_id': False,
                                        'location_id':key[0], 
                                        'location_dest_id': key[1],
                                        'move_id':move.id,
                                 })   
                            pack_op_ids.append(pack_op.id)
                            qty_left=qty_left-pack_op_qty                                 
                            if qty_left<=0.0:
                                break
                        if qty_grouped and qty_left >0.0:
                            pack_op = stock_move_line.with_context({'no_recompute':True}).create(
                                                                {
                                                                'date':time.strftime('%Y-%m-%d'),
                                                                'location_id':move.location_id and move.location_id.id or False, 
                                                                'location_dest_id': move.location_dest_id and move.location_dest_id.id or False,
                                                                'product_id': move.product_id and move.product_id.id or False,
                                                                'product_uom_id': move.product_id and move.product_id.uom_id and move.product_id.uom_id.id or False, 
                                                                'qty_done':qty_left or 0,
                                                                'picking_id':picking.id,
                                                                'move_id':move.id,
                                                                })
                         
                            pack_op_ids.append(pack_op.id)
     
                        elif not qty_grouped:
                            for move in move_lines:
                                delivered_qty = move.product_uom_qty
                                qty_left = qty_left - delivered_qty 
                                if qty_left < 0:
                                    delivered_qty = qty_left + delivered_qty 
                                pack_op = stock_move_line.with_context({'no_recompute':True}).create(
                                                                    {
                                                                    'date':time.strftime('%Y-%m-%d'),
                                                                    'location_id':move.location_id and move.location_id.id or False, 
                                                                    'location_dest_id': move.location_dest_id and move.location_dest_id.id or False,
                                                                    'product_id': move.product_id and move.product_id.id or False,
                                                                    'product_uom_id': move.product_id and move.product_id.uom_id and move.product_id.uom_id.id or False, 
                                                                    'qty_done':delivered_qty or 0,
                                                                    'picking_id':picking.id,
                                                                    'move_id':move.id,
                                                                    })
                             
                                pack_op_ids.append(pack_op.id)
                                if qty_left <= 0:
                                    break     
                        pick_ids.append(picking.id)  
                    if pick_ids and pack_op_ids:   
                        exists_pack_ops = stock_move_line.search([('picking_id','in',pick_ids),('id','not in',pack_op_ids)])
                        exists_pack_ops and exists_pack_ops.unlink()
                        picking = picking_obj.browse(list(set(pick_ids)))
                        try :
                            picking.action_done() 
                        except Exception as e:
                            raise FailedJobError(e)
                        picking.write({'is_magento_picking' : True,
                                       'backend_id' : self.backend_record.id,
                                       'magento_id' : magento_picking_data.get('entity_id',False),
                                       'is_exported_to_magento' : True
                                       })

SaleOrderImport = SaleOrderImporter  # deprecated


@magento
class SaleOrderCommentImportMapper(ImportMapper):
    """ Mapper for importing comments of sales orders.

    Does nothing in the base addons.
    """
    _model_name = 'magento.sale.order'


@magento
class MagentoSaleOrderOnChange(SaleOrderOnChange):
    _model_name = ['magento.sale.order']


@magento
class SaleOrderLineImportMapper(ImportMapper):
    _model_name = 'magento.sale.order.line'

    direct = [('qty_ordered', 'product_uom_qty'),        
              ('name', 'name'),
              ('item_id', 'magento_id'),
              ]

    @mapping
    def product_options(self, record):
        result={}
        if record.get('product_options') :
            notes=''
            for option in record['product_options']['extension_attributes'].get('custom_options') :
                notes += option['option_id']
                notes += ' : '
                notes += option['option_value']
                notes += '['+ record['sku']+ ']'
                notes += '\n'    
            result = {'notes': notes}
        return result
    
    @mapping
    def price(self, record):
        result = {}        
        row_total = float(record.get('row_total') or 0.)
        qty_ordered = float(record['qty_ordered'])
        if self.options.tax_include:
            row_total_incl_tax = float(record.get('row_total_incl_tax') or 0.)
            result['price_unit'] = row_total_incl_tax / qty_ordered
        else:
            result['price_unit'] = row_total / qty_ordered
        return result
    
    @mapping
    def tax_percentage(self, record):
        tax_percentage = float(record.get('tax_percent') or 0.0)
        if not tax_percentage:
            return {'tax_id' : False}
        
        website = self.options.storeview.website_id
        tax_include = self.options.tax_include
        
        tax_id = self.env['account.tax'].get_tax_from_rate(rate=float(tax_percentage),is_tax_included=tax_include)
        if not tax_id :
            if website.create_tax_if_not_found :
                if tax_include :
                    name = '%s %% Included'%(tax_percentage)
                else :
                    name = '%s %% '%(tax_percentage)
                tax_id = self.env['account.tax'].sudo().create({
                                                      'name':name,
                                                      'description':name,
                                                      'amount_type':'percent',
                                                      'price_include':tax_include,
                                                      'amount':float(tax_percentage),
                                                      'type_tax_use':'sale',
                                                      'account_id':website.tax_account_id.id or False,
                                                      'refund_account_id':website.tax_account_refund_id.id or False,
                                                      }
                                                     )
        if not tax_id :
            raise  FailedJobError("Tax %s should exist because the import fails "
                            "in SaleOrderImport._before_import when it is "
                            " missing" % tax_percentage)
        
        return {'tax_id': [(6,0,[tax_id.id])]}

        
    @mapping
    def discount_amount(self, record):
        discount_value = float(record.get('discount_amount') or 0)
        if self.options.tax_include:
            row_total = float(record.get('row_total_incl_tax') or 0)
        else:
            row_total = float(record.get('row_total') or 0)
        discount = 0
        if discount_value > 0 and row_total > 0:
            discount = 100 * discount_value / row_total
        result = {'discount': discount}
        return result

    @mapping
    def product_id(self, record):
        magento_product = self.env['magento.product.product']
        sku = record.get('sku')
        product_id = magento_product.get_odoo_product(sku,self.backend_record.id)
        if not product_id:
            raise FailedJobError("product_id %s should have been imported in "
            "SaleOrderImporter._import_dependencies" % record.get('sku'))
        return {'product_id': product_id and product_id.id}

@magento
class MagentoShippingLineBuilder(ShippingLineBuilder):
    _model_name = ['magento.sale.order']


@magento
class MagentoCashOnDeliveryLineBuilder(CashOnDeliveryLineBuilder):
    _model_name = ['magento.sale.order']


@magento
class MagentoGiftOrderLineBuilder(GiftOrderLineBuilder):
    _model_name = ['magento.sale.order']

@magento
class MagentoSurchargeLineBuilder(SurchargeLineBuilder):
    _model_name = ['magento.sale.order']


@job(default_channel='root.magento')
def sale_order_import_batch(session, model_name, backend_id, filters=None):
    """ Prepare a batch import of records from Magento """
    if filters is None:
        filters = {}
    assert 'magento_storeview_id' in filters, ('Missing information about '
                                               'Magento Storeview')
    env = get_environment(session, model_name, backend_id)
    importer = env.get_connector_unit(SaleOrderBatchImport)
    importer.run(filters)


@magento
class StateExporter(Exporter):
    _model_name = ['magento.sale.order']

    def run(self, binding_id, state=None, allowed_states=None, comment=None, notify=False):
        """ Change the status of the sales order on Magento.

        It adds a comment on Magento with a status.
        Sales orders on Magento have a state and a status.
        The state is related to the sale workflow, and the status can be
        modified liberaly.  We change only the status because Magento
        handle the state itself.

        When a sales order is modified, if we used the ``sales_order.cancel``
        API method, we would not be able to revert the cancellation.  When
        we send ``cancel`` as a status change with a new comment, we are still
        able to change the status again and to create shipments and invoices
        because the state is still ``new`` or ``processing``.

        :param binding_id: ID of the binding record of the sales order
        :param allowed_states: list of odoo states that are allowed
                               for export. If empty, it will export any
                               state.
        :param comment: Comment to display on Magento for the state change
        :param notify: When True, Magento will send an email with the
                       comment
        """
        binding = self.model.browse(binding_id)
        if state is None :
            state = binding.state
        if allowed_states and state not in allowed_states:
            return _('State %s is not exported.') % state
        magento_id = self.binder.to_backend(binding.id)
        if not magento_id:
            return _('Sale is not linked with a Magento sales order')
        magento_state = self.backend_adapter.get_status(magento_id)
        odoo_state = ORDER_STATUS_MAPPING[state]
        if odoo_state == magento_state:
            return _('Magento sales order is already '
                     'in state %s') % odoo_state
        if odoo_state == 'canceled' :
            self.backend_adapter.cancel_order(magento_id)
        else :
            self.backend_adapter.add_comment(magento_id, odoo_state,
                                         comment=comment,
                                         notify=notify)
        magento_state = self.backend_adapter.get_status(magento_id)
        binding.erp_id.magento_order_status = magento_state
        self.binder.bind(magento_id, binding_id)


@job(default_channel='root.magento')
def export_state_change(session, model_name, binding_id, status=None, allowed_states=None,
                        comment=None, notify=None):
    """ Change state of a sales order on Magento """
    binding = session.env[model_name].browse(binding_id)
    backend_id = binding.backend_id.id
    env = get_environment(session, model_name, backend_id)
    exporter = env.get_connector_unit(StateExporter)
    return exporter.run(binding_id,status, allowed_states=allowed_states,
                        comment=comment, notify=notify)
