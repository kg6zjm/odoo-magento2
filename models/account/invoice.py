import logging
from odoo import models, fields, api, _
from odoo.addons.odoo_magento2_ept.models.logs.job import job, related_action
from odoo.addons.odoo_magento2_ept.models.unit.synchronizer import Exporter
from odoo.addons.odoo_magento2_ept.models.unit.backend_adapter import GenericAdapter
from odoo.addons.odoo_magento2_ept.models.backend.connector import get_environment
from odoo.addons.odoo_magento2_ept.models.backend.backend import magento
from odoo.addons.odoo_magento2_ept.models.backend.related_action import unwrap_binding
from odoo.addons.odoo_magento2_ept.models.backend.session import ConnectorSession
from odoo.addons.odoo_magento2_ept.models.api_request import req
from odoo.addons.odoo_magento2_ept.models.search_criteria import create_search_criteria
import odoo.addons.decimal_precision as dp
from odoo.addons.odoo_magento2_ept.models.backend.exception import (                                                                  
                                                                   FailedJobError,
                                                                   )
from odoo.addons.odoo_magento2_ept.python_library.requests.exceptions import HTTPError
_logger = logging.getLogger(__name__)

class AccountInvoice(models.Model):
    _inherit = 'account.invoice'

    @api.multi
    @api.depends('sale_id')
    def _compute_is_magento_invoice(self):
        for record in self:
            record.is_magento_invoice = False
            if record.sale_id and record.sale_id.magento_bind_ids:
                record.is_magento_invoice = True
    
    @api.multi
    @api.depends("sale_id")
    def _set_magento_info(self):
        for record in self :
            if record.sale_id.magento_bind_ids :
                record.website_id = record.sale_id.website_id
                record.store_id = record.sale_id.store_id
                record.storeview_id = record.sale_id.storeview_id   
        
    magento_workflow_process_id = fields.Many2one(comodel_name='magento.sale.workflow.process',
                                          string='Sale Workflow Process')
    magento_payment_method_id = fields.Many2one(comodel_name='magento.payment.method.ept',string="Magento Payment Method")
    sale_id  = fields.Many2one('sale.order',string="Sale order")
    magento_order_status = fields.Char(related='sale_id.magento_order_status',string="Magento Order Status",readonly=True)
    is_magento_invoice = fields.Boolean(compute='_compute_is_magento_invoice',string="Is Magento Invoice?",store=True)
    is_exported_to_magento = fields.Boolean('Exported to Magento')
    backend_id = fields.Many2one('magento.backend')
    magento_id = fields.Char("Magento Id")
    website_id = fields.Many2one(compute="_set_magento_info",comodel_name="magento.website", store=True,readonly=True,string="Website")
    store_id = fields.Many2one(compute="_set_magento_info", comodel_name="magento.store", store=True,readonly=True,string="Store")
    storeview_id = fields.Many2one(compute="_set_magento_info", comodel_name="magento.storeview", store=True,readonly=True,string="Storeview")
    @api.multi
    def export_invoice_to_magento(self,backends):
        session = ConnectorSession(self.env.cr, self.env.uid,context=self.env.context)
        invoices = self.search([('is_magento_invoice','=',True),('is_exported_to_magento','=',False),('backend_id','in',backends.ids)])
        for invoice in invoices:
            if invoice.magento_payment_method_id.create_invoice_on != 'na':
                export_invoice.delay(session,self._name,invoice.id)
    
    @api.multi
    def get_magento_order_status(self):
        for invoice in self:
            if invoice.sale_id :
                invoice.sale_id.get_magento_order_status()
                
@magento
class AccountInvoiceAdapter(GenericAdapter):
    """ Backend Adapter for the Magento Invoice """
    _model_name = ['account.invoice']
    _path = "/V1/invoices"
    
    def create(self, order_id, items, comment, email,
               include_comment):
        """ Create a record on the external system """
        order_item = []
        if items :
            for item_id,qty in items.items():
                item={}
                item.setdefault("order_item_id",item_id)
                item.setdefault("qty",qty)
                order_item.append(item)
        else :
            order_item.append(items)         
        data = {
                "entity":{
                          "orderId":order_id,
                          "items":order_item,
                          "notify":email
                          },
                'url':'/V1/order/%s/invoice'%order_id
                }
        
        if include_comment and comment:
            data.update({
                
                "appendComment": True,
                "comment": {
                    "extension_attributes": {},
                    "comment": comment,
                    "is_visible_on_front": 0
                }
                         
            })
      
        content = super(AccountInvoiceAdapter,self).create(data)
        return content
    
    
    def search_read(self, filters=None, order_id=None):
        """ Search records according to some criterias
        and returns their information
        
        """
        if filters is None:
            filters = {}
        if order_id is not None:
            filters['order_id'] = {'eq': order_id}
        items = super(AccountInvoiceAdapter,self).search_read(filters)
        try :
            for item in items :
                item['increment_id']=item['entity_id'] 
            return items 
        except : 
            _logger.error("Error at invoice search_read :",items)
    

@magento
class MagentoInvoiceExporter(Exporter):
    """ Export invoices to Magento """
    _model_name = ['account.invoice']

    def _export_invoice(self, sale_magento_id, lines_info, mail_notification):
        if not lines_info:  # invoice without any line for the sale order
            return
        return self.backend_adapter.create(sale_magento_id,
                                           lines_info,
                                           _("Invoice Created"),
                                           mail_notification,
                                           False)

    def _get_lines_info(self, invoice):
        """
        Get the line to export to Magento. In case some lines doesn't have a
        matching on Magento, we ignore them. This allow to add lines manually.

        :param invoice: invoice is an magento.account.invoice record
        :type invoice: browse_record
        :return: dict of {magento_product_id: quantity}
        :rtype: dict
        """
        item_qty = {}
        # get product and quantities to invoice
        # if no magento id found, do not export it
        order = invoice.sale_id.magento_bind_ids and invoice.sale_id.magento_bind_ids[0]
        for line in invoice.invoice_line_ids:
            product = line.product_id
            # find the order line with the same product
            # and get the magento item_id (id of the line)
            # to invoice
            order_line = next((line for line in order.magento_order_line_ids
                               if line.product_id.id == product.id),
                              None)
            if order_line is None:
                continue

            item_id = order_line.magento_id
            item_qty.setdefault(item_id, 0)
            item_qty[item_id] += line.quantity
        return item_qty

    def run(self, binding_id):
        """ Run the job to export the validated/paid invoice """
        invoice = self.model.browse(binding_id)

        magento_order = invoice.sale_id.magento_bind_ids and invoice.sale_id.magento_bind_ids[0]
        magento_store = magento_order.store_id
        mail_notification = magento_store.send_invoice_paid_mail

        lines_info = self._get_lines_info(invoice)
        magento_id = None
        try:
            magento_id = self._export_invoice(magento_order.magento_id,
                                              lines_info,
                                              mail_notification)
        except FailedJobError as err:
            # When the invoice is already created on Magento, it returns:
            magento_id = self._get_existing_invoice(magento_order)
            if magento_id is None:
                raise FailedJobError('Invoice Export job failed')
        if not magento_id:
            # If Magento returned no ID, try to find the Magento
            # invoice, but if we don't find it, let consider the job
            # as done, because Magento did not raised an error
            magento_id = self._get_existing_invoice(magento_order)
        invoice.write({'is_exported_to_magento' : True , 'magento_id' : magento_id})
        return "Invoice is successfully exported on Magento with ID %s"%(magento_id)

    def _get_existing_invoice(self, magento_order):
        invoices = self.backend_adapter.search_read(order_id=magento_order.magento_order_id)
        if not invoices:
            return
        return invoices[0]['increment_id']


MagentoInvoiceSynchronizer = MagentoInvoiceExporter  # deprecated


@job(default_channel='root.magento')
@related_action(action=unwrap_binding)
def export_invoice(session, model_name, record_id):
    """ Export a validated or paid invoice. """
    invoice = session.env[model_name].browse(record_id)
    backend_id = invoice.backend_id.id
    env = get_environment(session, model_name, backend_id)
    invoice_exporter = env.get_connector_unit(MagentoInvoiceExporter)
    result = invoice_exporter.run(record_id)
    return result
