# -*- coding: utf-8 -*-
##############################################################################
#
#    Author: Guewen Baconnier
#    Copyright 2013 Camptocamp SA
#    Copyright 2013 Akretion
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

import logging
import ast
from datetime import datetime, timedelta
import time
from odoo import models, fields, api, _
from odoo.addons.odoo_magento2_ept.models.backend.session import ConnectorSession
from odoo.addons.odoo_magento2_ept.models.backend.connector import ConnectorUnit
from odoo.addons.odoo_magento2_ept.models.unit.mapper import mapping, ImportMapper
from odoo.addons.odoo_magento2_ept.models.unit.backend_adapter import GenericAdapter
from odoo.addons.odoo_magento2_ept.models.unit.import_synchronizer import (import_batch,
                                       DirectBatchImporter,
                                       MagentoImporter,
                                       )
from odoo.addons.odoo_magento2_ept.models.sale.sale import SaleOrderBatchImport
from odoo.addons.odoo_magento2_ept.models.sale.sale import SaleOrderImporter
from odoo.addons.odoo_magento2_ept.models.sale.sale import SaleOrderAdapter
from odoo.addons.odoo_magento2_ept.models.partner.partner import partner_import_batch
from odoo.addons.odoo_magento2_ept.models.sale.sale import sale_order_import_batch
from odoo.addons.odoo_magento2_ept.models.backend.backend import magento
from odoo.addons.odoo_magento2_ept.models.api_request import req
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT,ustr
from odoo.addons.odoo_magento2_ept.models.unit.import_synchronizer import IMPORT_DELTA_BUFFER
from odoo.addons.odoo_magento2_ept.models.backend.connector import (ConnectorUnit,
                                                                   get_environment)
from odoo.exceptions import ValidationError,UserError
from odoo.addons.odoo_magento2_ept.models.backend.exception import (
                                                                   NetworkRetryableError,
                                                                   FailedJobError,
                                                                   )
from odoo.addons.odoo_magento2_ept.python_library.requests.exceptions import HTTPError

_logger = logging.getLogger(__name__)

class MagentoBackend(models.Model):
    _name = 'magento.backend'
    _description = 'Magento Instance'
    _inherit = 'connector.backend'

    _backend_type = 'magento'
    
    
    @api.model
    def select_versions(self):
        """ Available versions in the backend.

        Can be inherited to add custom versions.  Using this method
        to add a version from an ``_inherit`` does not constrain
        to redefine the ``version`` field in the ``_inherit`` model.
        """
        return [('2.0', '2.0+'),('2.1','2.1+'),('2.2','2.2+')]

    @api.model
    def _get_stock_field_id(self):
        field = self.env['ir.model.fields'].search(
            [('model', '=', 'product.product'),
             ('name', '=', 'virtual_available')],
            limit=1)
        return field

    version = fields.Selection(selection='select_versions', required=True)
    location = fields.Char(
        string='Location',
        required=True,
        help="Url to magento application",
    )
    is_only_import_export_basic_info=fields.Boolean(string="Is Import/Export Only Basic Catalog Info")
    warehouse_ids = fields.Many2many(
        'stock.warehouse',
        string='Warehouses',
        required=True,
        help='Warehouses used to compute the '
             'stock quantities.If Warhouses is not selected then it is taken from Website',
    )
 
    website_ids = fields.One2many(
        comodel_name='magento.website',
        inverse_name='backend_id',
        string='Website',
        readonly=True,
    )
    default_lang_id = fields.Many2one(
        comodel_name='res.lang',
        string='Default Language',
        help="If a default language is selected, the records "
             "will be imported in the translation of this language.\n"
             "Note that a similar configuration exists "
             "for each storeview.",
    )
    default_category_id = fields.Many2one(
        comodel_name='magento.product.category',
        string='Default Product Category',
        help='If a default category is selected, products imported '
             'without a category will be linked to it.',
    )

    product_stock_field_id = fields.Many2one(
        comodel_name='ir.model.fields',
        string='Stock Field',
        default=_get_stock_field_id,
        domain="[('model', 'in', ['product.product', 'product.template']),"
               " ('ttype', '=', 'float')]",
        help="Choose the field of the product which will be used for "
             "stock inventory updates.\nIf empty, Quantity Available "
             "is used.",
    )
    product_binding_ids = fields.One2many(
        comodel_name='magento.product.product',
        inverse_name='backend_id',
        string='Magento Products',
        readonly=True,
    )
    
    catalog_price_scope = fields.Selection([('global','Global'),('website','Website')],string="Catalog Price Scope",help="Scope of Price in Magento")
    pricelist_id = fields.Many2one('product.pricelist',string="Pricelist",help="Product Price is set in selected Pricelist")    
    token = fields.Char(string="Access Token")  
    
    attribute_set_tpl_id=fields.Many2one('magento.attribute.set',string='Default Attribute Set',domain="[('backend_id','=',id)]",
                                         help="Attribute Set basing on which the new attribute set "
                                         "will be created.")
    product_import_page_size = fields.Integer('Product Import Page Size',default=500)
    
    allow_import_traslation = fields.Boolean("Import/Export Product data from/to all storeview ?",help="Import product data (e.g Translated value of name,description,etc..) from all storeview if true else import data for only default storeview")
    allow_so_import_on_fly = fields.Boolean("Import Sale Orders on the fly?")
    auto_create_product = fields.Boolean("Auto Create Product")
    customer_import_page_size = fields.Integer("Customer Import Page Size",default=500)
    allow_import_image_of_products = fields.Boolean("Import Images of Products")
    last_attribute_import_date =fields.Datetime(string='Last Attribute import date')
    last_attribute_set_import_date =fields.Datetime(string='Last Attribute Set import date')
    last_product_import_date = fields.Datetime(string='Last Product import date',)
    last_product_category_import_date = fields.Datetime(string='Last Product Category import date',)
    last_order_import_date = fields.Datetime(string="Last Order import date")
    last_order_status_update_date = fields.Datetime(string="Last Shipment Export date")
    last_partner_import_date = fields.Datetime(string="Last Partner import date")
    last_update_stock_time=fields.Datetime("Last Update Stock Time")
    #Import Product Stock
    is_import_product_stock = fields.Boolean('Import Product Stock?',help="Import Product Stock from Magento to Odoo")
    import_stock_warehouse = fields.Many2one('stock.warehouse',string="Stock Warehouse",help="Warehouse for import stock from Magento to Odoo")
    image_delete_on_magento = fields.Boolean("Delete Product Image on Magento?",help="When you delete any Product Image,it will automatic delete it on Magento")
    
    active = fields.Boolean(string="Active",default=True)
    
    @api.multi
    def open_all_websites(self):
        website_ids = self.mapped('website_ids')
        xmlid=('odoo_magento2_ept','action_magento_website')
        action = self.env['ir.actions.act_window'].for_xml_id(*xmlid)
        action['domain']= "[('id','in',%s)]" % website_ids.ids
        if not website_ids : 
            return {'type': 'ir.actions.act_window_close'}
        return action
                 
    @api.multi
    def _check_location_url(self,location_url):
        if location_url : 
            location_url = location_url.strip()
            location_url = location_url.rstrip('/')
            location_vals = location_url.split('/')
            if location_vals[-1] != 'rest':
                if location_url[-1] != '/':
                    location_url = location_url + '/rest'
                else : 
                    location_url = location_url + 'rest'
        return location_url
    
    @api.multi 
    def test_connection(self):
        self.ensure_one()
        try:
            context=self._context
            session = ConnectorSession(self._cr, self._uid,context=context)
            backend_id = self.id
            mage_env = get_environment(session, "magento.website", backend_id)
            adapter = mage_env.get_connector_unit(WebsiteAdapter)
            result = adapter.search()
        except NetworkRetryableError as e :
            raise UserError(
                'A network error caused the failure of the job: '
                '%s' % e)
        except FailedJobError as e :
            raise UserError('Given Credentials is incorrect, please provide correct Credentials.')
        except Exception as e:
            raise UserError("Connection Test Failed! Here is what we got instead:\n \n%s" % ustr(e))
        
        raise UserError("Connection Test Succeeded! Everything seems properly set up!")

    
    @api.model
    def create(self,vals):
        
        backend = super(MagentoBackend,self).create(vals)

#         self.create_sequences_and_dashboard_operation(backend)
        return backend
            
    @api.multi
    def check_magento_structure(self):
        """ Used in each data import.

        Verify if a website exists for each backend before starting the import.
        """
        for backend in self:
            websites = backend.website_ids
            if not websites:
                backend.synchronize_metadata()
        return True

    @api.multi
    def synchronize_metadata(self):
        session = ConnectorSession(self.env.cr, self.env.uid,
                                   context=self.env.context)
        for backend in self:
            for model in ('magento.website','magento.store','magento.storeview'): #Import directly without Delay
                import_batch(session, model, backend.id)
            backend.import_attribute_sets()
            backend.import_payment_method()
            backend.import_delivery_method()
        return True

    @api.multi
    def import_payment_method(self):
        payment_method_obj = self.env['magento.payment.method']
        url = '/V1/paymentmethod'
        payment_methods = req(self,url)
        #print(payment_methods)
        for payment_method in payment_methods:
            payment_method_code = payment_method.get('value')
            new_payment_method = payment_method_obj.search([('payment_method_code','=',payment_method_code),('backend_id','=',self.id)])
            if not new_payment_method:
                payment_method_obj.create({
                                            'payment_method_code' : payment_method.get('value'),
                                            'payment_method_name' : payment_method.get('title'),
                                            'backend_id' : self.id
                                            })
    
    @api.multi
    def import_delivery_method(self):
        delivery_method_obj = self.env['magento.delivery.carrier']
        url = '/V1/shippingmethod'
        delivery_methods = req(self,url)
        #print(delivery_methods)
        for delivery_method in delivery_methods:
            for method_value in delivery_method.get('value') : 
                delivery_method_code = method_value.get('value')
                new_delivery_carrier = delivery_method_obj.search([('carrier_code','=',delivery_method_code),('backend_id','=',self.id)])
                if not new_delivery_carrier:
                    delivery_method_obj.create({
                                                'carrier_code' : method_value.get('value'),
                                                'carrier_label' : method_value.get('label'),
                                                'backend_id' : self.id,
                                                'magento_carrier_title' : delivery_method.get('label')
                                                })
    
    @api.multi
    def _import_from_date(self, model, from_date_field):
        session = ConnectorSession(self.env.cr, self.env.uid,
                                   context=self.env.context)
        import_start_time = datetime.now()
        for backend in self:
            backend.check_magento_structure()
            from_date = getattr(backend, from_date_field)
            if from_date:
                from_date = fields.Datetime.from_string(from_date)
            else:
                from_date = None
            import_batch.delay(session, model,
                               backend.id,
                               filters={'from_date': from_date,
                                        'to_date': import_start_time})
        # Records from Magento are imported based on their `created_at`
        # date.  This date is set on Magento at the beginning of a
        # transaction, so if the import is run between the beginning and
        # the end of a transaction, the import of a record may be
        # missed.  That's why we add a small buffer back in time where
        # the eventually missed records will be retrieved.  This also
        # means that we'll have jobs that import twice the same records,
        # but this is not a big deal because they will be skipped when
        # the last `sync_date` is the same.
        
        #Update : 19-12-2016 
        #Added this in BatchImporters of object. 
        #batch job is created and from_date is updated after it but if batch job will failed and 
        #not requeue after that then that batch of records may be missed 
        #that is why it is added in BatchImporter.
        
        #next_time = import_start_time - timedelta(seconds=IMPORT_DELTA_BUFFER)
        #next_time = fields.Datetime.to_string(next_time)
        #self.write({from_date_field: next_time})

    @api.multi
    def import_product_categories(self):
        self._import_from_date('magento.product.category',
                               'last_product_category_import_date')
        return True

    @api.multi
    def import_product_product(self):
        self._import_from_date('magento.product.product',
                               'import_products_from_date')
        return True
    
    @api.multi
    def _domain_for_update_product_stock_qty(self,backend,last_update_stock_time=False):
        product_ids = []
        if last_update_stock_time:
            qry = """
                    select * from magento_product_product mp inner join product_product pp
                    on pp.id = mp.erp_id and pp.id in (select product_id from stock_move where 
                    (create_date >= '%s' or write_date >= '%s') and 'state' != 'cancel');
                  """%(last_update_stock_time,last_update_stock_time)
            
            self._cr.execute(qry)
            results = self._cr.fetchall()
            for result_tuple in results:
                product_ids.append(result_tuple[0])
        backend.write({'last_update_stock_time' : datetime.now()})
        domain = [
            ('backend_id','=',backend.id),
            ('type', '!=', 'service'),
            ('no_stock_sync', '=', False),
        ]
        if product_ids:
            domain.append(('id','in',product_ids))
        return domain


    @api.multi
    def update_product_stock_qty(self):
        mag_product_obj = self.env['magento.product.product']
        domain = self._domain_for_update_product_stock_qty()
        magento_products = mag_product_obj.search(domain)
        magento_products.recompute_magento_qty()
        return True

    @api.model
    def _magento_backend(self, callback, domain=None):
        if domain is None:
            domain = []
        backends = self.search(domain)
        if backends:
            getattr(backends, callback)()

    @api.model
    def _scheduler_import_sale_orders(self, args={}):
        sale_order = self.env['magento.sale.order']
        backend_id = args.get('backend_id')
        if backend_id :
            backend = self.env['magento.backend'].browse(backend_id)
            sale_order.import_sale_orders(backend)

    @api.model
    def _scheduler_import_customer_groups(self, args={}):
        res_partner_category = self.env['magento.res.partner.category']
        backend_id = args.get('backend_id')
        if backend_id :
            backend = self.env['magento.backend'].browse(backend_id)
            res_partner_category.import_customer_group(backend)

    @api.model
    def _scheduler_import_partners(self, args={}):
        res_partner = self.env['res.partner']
        backend_id = args.get('backend_id')
        if backend_id :
            backend = self.env['magento.backend'].browse(backend_id)
            res_partner.import_magento_partners(backend)

    @api.model
    def _scheduler_import_product_categories(self, args={}):
        magento_product_category = self.env['magento.product.category']
        backend_id = args.get('backend_id')
        if backend_id :
            backend = self.env['magento.backend'].browse(backend_id)
            magento_product_category.import_product_category(backend)


    @api.model
    def _scheduler_import_product_product(self, args={}):
        magento_product = self.env['magento.product.product']
        backend_id = args.get('backend_id')
        if backend_id :
            backend = self.env['magento.backend'].browse(backend_id)
            magento_product.import_products(backend)

    @api.model
    def _scheduler_update_product_stock_qty(self,args={}):
        backend_id = args.get('backend_id')
        backend=self.env['magento.backend'].browse(backend_id)
        if backend :
            last_update_stock_time = backend.last_update_stock_time or False
            last_update_stock_time = last_update_stock_time and datetime.strptime(last_update_stock_time, '%Y-%m-%d %H:%M:%S') - timedelta(days=1)
            magento_obj = self.env['magento.product.product']
            domain = self._domain_for_update_product_stock_qty(backend,last_update_stock_time)
            magento_products=magento_obj.search(domain)
            magento_obj.export_multiple_product_stock_to_magento(magento_products)

                
    @api.model
    def _scheduler_update_order_status(self,args={}):
        stock_picking = self.env['stock.picking']
        backend_id = args.get('backend_id')
        if backend_id :
            backend = self.env['magento.backend'].browse(backend_id)
            stock_picking.export_shipment_to_magento(backend)
    
    @api.model
    def _scheduler_export_invoice(self,args={}):
        account_invoice = self.env['account.invoice']
        backend_id = args.get('backend_id')
        if backend_id :
            backend = self.env['magento.backend'].browse(backend_id)
            account_invoice.export_invoice_to_magento(backend)
    @api.multi
    def output_recorder(self):
        """ Utility method to output a file containing all the recorded
        requests / responses with Magento.  Used to generate test data.
        Should be called with ``erppeek`` for instance.
        """
        from odoo.addons.odoo_magento2_ept.models.unit.backend_adapter import output_recorder
        import os
        import tempfile
        fmt = '%Y-%m-%d-%H-%M-%S'
        timestamp = datetime.now().strftime(fmt)
        filename = 'output_%s_%s' % (self.env.cr.dbname, timestamp)
        path = os.path.join(tempfile.gettempdir(), filename)
        output_recorder(path)
        return path
    
    @api.multi
    def import_attribute_sets(self):
        if not hasattr(self.ids, '__iter__'):
            ids = [self.ids]
        self.check_magento_structure()
        session = ConnectorSession(self.env.cr,self.env.uid,self.env.context)
        for backend in self:
            import_batch.delay(session, 'magento.attribute.set', backend.id)
            backend.write({'last_attribute_set_import_date' : datetime.now()})
        return True
  
    #Not in Use
    @api.multi
    def import_attributes(self):
        import_start_time = datetime.now().strftime(DEFAULT_SERVER_DATETIME_FORMAT)
        self.check_magento_structure()
        session = ConnectorSession(self.env.cr, self.env.uid,self.env.context)
        for backend in self:
            from_date = backend.import_attributes_from_date or False
            if from_date:
                from_date = datetime.strptime(from_date,DEFAULT_SERVER_DATETIME_FORMAT)
            else:
                from_date = None            
            import_batch.delay(session, 'magento.product.attribute', backend.id,filters=[ from_date and from_date.strftime(DEFAULT_SERVER_DATETIME_FORMAT) or ''])
            backend.write({'import_attributes_from_date' : import_start_time})
            
        return True  


class MagentoWebsite(models.Model):
    _name = 'magento.website'
    _inherit = 'magento.binding'
    _description = 'Magento Website'

    _order = 'sort_order ASC, id ASC'

    name = fields.Char(required=True, readonly=True)
    code = fields.Char(readonly=True)
    sort_order = fields.Integer(string='Sort Order', readonly=True)
    store_ids = fields.One2many(
        comodel_name='magento.store',
        inverse_name='website_id',
        string='Stores',
        readonly=True,
    )
    import_partners_from_date = fields.Datetime(string='Last partner import date')
    
    product_binding_ids = fields.Many2many(
        comodel_name='magento.product.product',
        string='Magento Products',
        readonly=True,
    )
    pricelist_id = fields.Many2one('product.pricelist',string="Pricelist",help="Product Price is set in selected Pricelist if Catalog Price Scope is Website")    
    payment_method_ids = fields.One2many(comodel_name="magento.payment.method.ept",inverse_name="website_id",
                                         string='Payment method')
    tax_include_in_price = fields.Boolean(string="Tax include in price",help="Product Price is including tax or not")
    create_tax_if_not_found = fields.Boolean(string='Create Tax if not found?')
    tax_account_id = fields.Many2one('account.account', string='Tax Account',
         help="Tax Account that will be set on tax when tax will be create when order import")
    tax_account_refund_id = fields.Many2one('account.account', string='Tax Refund Account',
         help="Tax Refund Account that will be set on tax when tax will be create when order import")
    
    warehouse_id = fields.Many2one(
        comodel_name='stock.warehouse',
        string='Warehouse',
        help='Warehouse to be used to deliver an order from this website.'
    )
    
    company_id = fields.Many2one(
        comodel_name='res.company',
        related='warehouse_id.company_id',
        string='Company',
        readonly=True,
    )
    
    currency_id = fields.Many2one(related='pricelist_id.currency_id',
                                  comodel_name="res.currency",
                                  readonly=True )
    pricelist_id = fields.Many2one(comodel_name="product.pricelist",string="Pricelist",help="If catalog price scope is website, system will get/set price based on this pricelist")
    active = fields.Boolean(string="Active",default=True)
    
    @api.multi
    def open_all_stores(self):
        stores = self.mapped('store_ids')
        xmlid=('odoo_magento2_ept','action_magento_store')
        action = self.env['ir.actions.act_window'].for_xml_id(*xmlid)
        action['domain']= "[('id','in',%s)]" % stores.ids
        if not stores : 
            return {'type': 'ir.actions.act_window_close'}
        return action  
    
    @api.multi
    def open_payment_methods(self):
        payment_method_ids = self.mapped('payment_method_ids')
        xmlid=('odoo_magento2_ept','act_payment_method_form')
        action = self.env['ir.actions.act_window'].for_xml_id(*xmlid)
        action['domain']= "[('id','in',%s)]" % payment_method_ids.ids
        if not payment_method_ids : 
            return {'type': 'ir.actions.act_window_close'}
        return action  
    
    @api.multi
    def count_all(self):
        picking_obj=self.env['stock.picking']
        sale_order_obj=self.env['sale.order']
        invoice_obj=self.env['account.invoice']
        for record in self:
            pickings=picking_obj.search([('is_magento_picking','=',True),('website_id','=',record.id),('state','=','confirmed')])
            record.count_picking_confirmed=len(pickings.ids)
            pickings=picking_obj.search([('is_magento_picking','=',True),('website_id','=',record.id),('state','=','assigned')])
            record.count_picking_assigned=len(pickings.ids)
            pickings=picking_obj.search([('is_magento_picking','=',True),('website_id','=',record.id),('state','=','partially_available')])
            record.count_picking_partial=len(pickings.ids)
            pickings=picking_obj.search([('is_magento_picking','=',True),('website_id','=',record.id),('state','=','done')])
            record.count_picking_done=len(pickings.ids)
              
            orders=sale_order_obj.search([('website_id','=',record.id),('state','in',['draft','sent','cancel'])])
            record.count_quotations=len(orders.ids)
              
            orders=sale_order_obj.search([('website_id','=',record.id),('state','not in',['draft','sent','cancel'])])
            record.count_orders=len(orders.ids)
              
            invoices=invoice_obj.search([('is_magento_invoice','=',True),('website_id','=',record.id),('state','=','open'),('type','=','out_invoice')])
            record.count_open_invoices = len(invoices.ids)
              
            invoices=invoice_obj.search([('sale_id.magento_bind_ids','!=',False),('website_id','=',record.id),('state','=','paid'),('type','=','out_invoice')])
            record.count_paid_invoices = len(invoices.ids)
    
    count_quotations = fields.Integer("Count Sales Quotations",compute="count_all")
    count_orders = fields.Integer("Count Sales Orders",compute="count_all")
    
    color = fields.Integer(string='Color Index')
    count_picking_confirmed = fields.Integer(string="Count Picking Confirmed",compute="count_all")
    count_picking_assigned = fields.Integer(string="Count Picking Assigned",compute="count_all")
    count_picking_partial = fields.Integer(string="Count Picking Partial",compute="count_all")
    count_picking_done = fields.Integer(string="Count Picking Done",compute="count_all")
    
    count_open_invoices = fields.Integer(string="Count Open Invoices",compute="count_all")
    count_paid_invoices = fields.Integer(string="Count Paid Invoices",compute="count_all")
    
    
    @api.multi
    def get_all_operation_wizard(self):
        for record in self:
            context = dict(self._context or {})
            context.update({'default_backend_id' : record.backend_id.id})
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'magento.import.export.ept',
                'view_type': 'form',
                'view_mode': 'form',
                'target': 'new',
                'context' : context
                }
     
    @api.multi
    def get_magento_pending_orders(self):
        return self._get_action('odoo_magento2_ept.magento_action_quotations_ept')
     
    @api.multi
    def get_magento_sales_orders(self):
        return self._get_action('odoo_magento2_ept.magento_action_sale_orders_ept')
     
    @api.multi
    def get_magento_canceled_in_magento_orders(self):
        return self._get_action('odoo_magento2_ept.magento_action_canceled_in_magento_orders_ept')
     
    @api.multi
    def get_magento_waiting_shipments(self):
        return self._get_action('odoo_magento2_ept.magento_action_picking_view_confirm_ept')
     
    @api.multi
    def get_magento_ready_shipments(self):
        return self._get_action('odoo_magento2_ept.magento_action_picking_view_assigned_ept')
     
    @api.multi
    def get_magento_transfered_shipments(self):
        return self._get_action('odoo_magento2_ept.magento_action_picking_view_done_ept')
     
    @api.multi
    def get_magento_open_invoices(self):
        return self._get_action('odoo_magento2_ept.action_open_invoice_tree_magento_invoices')
     
    @api.multi
    def get_magento_paid_invoices(self):
        return self._get_action('odoo_magento2_ept.action_paid_invoice_tree_magento_invoices')
     
    @api.multi
    def get_magento_customers(self):
        return self._get_action('odoo_magento2_ept.action_magento_partner_form')
     
    @api.multi
    def get_magento_products(self):
        return self._get_action('odoo_magento2_ept.magento_product_normal_action_sell_ept')
     
    @api.multi
    def get_magento_websites(self):
        return self._get_action('odoo_magento2_ept.action_magento_website')
     
    @api.multi
    def get_magento_stores(self):
        return self._get_action('odoo_magento2_ept.action_magento_store')
     
    @api.multi
    def get_magento_storeviews(self):
        return self._get_action('odoo_magento2_ept.action_magento_storeview')
    @api.multi
    def get_magento_backend(self):
        return self._get_action('odoo_magento2_ept.action_magento_backend')
     
    @api.multi
    def _get_action(self, action):
        action = self.env.ref(action) or False
        result = action.read()[0] or {}
        domain = result.get('domain') and ast.literal_eval(result.get('domain')) or []
        if action.res_model in ['sale.order'] :
             
            domain.append(('website_id','in',[self.id]))
        if action.res_model in ['res.partner'] :
            domain.append(('backend_id.website_ids.id','in',[self.id]))
        if  action.res_model in ['magento.product.product'] :
            domain.append(('website_ids.id','in',[self.id]))
        if action.res_model in ['account.invoice','stock.picking'] :
            domain.append(('backend_id.website_ids.id','in',[self.id]))
        if action.res_model in ['magento.store']:
                domain.append(('website_id','=',self.id))
        if action.res_model in ['magento.website']:
                domain.append(('id','=',self.id))
        if action.res_model in ['magento.storeview']:
                    domain.append(('website_id','=',self.id))
        if action.res_model in ['magento.backend']:
                    domain.append(('website_ids.id','=',self.id))
        if action.res_model in ['magento.website']:            
            view_xmlid = 'odoo_magento2_ept.view_magento_website_tree'
            view = self.env.ref(view_xmlid)
            result['views'] = [(view.id if view else False, 'tree')]
            result['res_id'] = self.id
        result['domain'] = domain
        return result
    

    
    @api.multi
    def name_get(self):
        result = []
        for record in self:
            name = "%s (%s)"%(record.name,record.backend_id.name or "")
            result.append((record.id, name))
        return result
    
    @api.model
    def name_search(self, name, args=None, operator='ilike', limit=100):
        args = args or []
        recs = self.browse()
        if name:
            recs = self.search([('name', '=', name)] + args, limit=limit)
        if not recs:
            recs = self.search([('name', operator, name)] + args, limit=limit)
        return recs.name_get()

    @api.multi
    def import_partners(self):
        session = ConnectorSession(self.env.cr, self.env.uid,
                                   context=self.env.context)
        import_start_time = datetime.now()
        for website in self:
            backend_id = website.backend_id.id
            if website.import_partners_from_date:
                from_string = fields.Datetime.from_string
                from_date = from_string(website.import_partners_from_date)
            else:
                from_date = None
            partner_import_batch.delay(
                session, 'res.partner', backend_id,
                {'magento_website_id': website.magento_id,
                 'from_date': from_date,
                 'to_date': import_start_time})
        # Records from Magento are imported based on their `created_at`
        # date.  This date is set on Magento at the beginning of a
        # transaction, so if the import is run between the beginning and
        # the end of a transaction, the import of a record may be
        # missed.  That's why we add a small buffer back in time where
        # the eventually missed records will be retrieved.  This also
        # means that we'll have jobs that import twice the same records,
        # but this is not a big deal because they will be skipped when
        # the last `sync_date` is the same.
        next_time = import_start_time - timedelta(seconds=IMPORT_DELTA_BUFFER)
        next_time = fields.Datetime.to_string(next_time)
        self.write({'import_partners_from_date': next_time})
        return True
    
    @api.model
    def create(self,vals):
        if vals.get('code') == 'admin':
            vals.update({'active' : False})
        res = super(MagentoWebsite,self).create(vals)
        return res
    

class MagentoStore(models.Model):
    _name = 'magento.store'
    _inherit = 'magento.binding'
    _description = 'Magento Store'

    name = fields.Char()
    website_id = fields.Many2one(
        comodel_name='magento.website',
        string='Magento Website',
        required=True,
        readonly=True,
        ondelete='cascade',
    )
    backend_id = fields.Many2one(
        comodel_name='magento.backend',
        related='website_id.backend_id',
        string='Instance',
        store=True,
        readonly=True,
        required=False,
    )
    storeview_ids = fields.One2many(
        comodel_name='magento.storeview',
        inverse_name='store_id',
        string="Storeviews",
        readonly=True,
    )
    send_picking_done_mail = fields.Boolean(
        string='Send email for Shipment from Magento',
        help="Does the picking export/creation should send "
             "an email notification on Magento side?",
    )
    send_invoice_paid_mail = fields.Boolean(
        string='Send email for invoice from Magento',
        help="Does the invoice export/creation should send "
             "an email notification on Magento side?",
    )

    active = fields.Boolean(string="Active",default=True)         
    
    
    @api.multi
    def open_magento_storeviews(self):
        storeview_ids = self.mapped('storeview_ids')
        xmlid=('odoo_magento2_ept','action_magento_storeview')
        action = self.env['ir.actions.act_window'].for_xml_id(*xmlid)
        action['domain']= "[('id','in',%s)]" % storeview_ids.ids
        if not storeview_ids : 
            return {'type': 'ir.actions.act_window_close'}
        return action                        
                                     
class MagentoStoreview(models.Model):
    _name = 'magento.storeview'
    _inherit = 'magento.binding'
    _description = "Magento Storeview"

    _order = 'sort_order ASC, id ASC'

    name = fields.Char(required=True, readonly=True)
    code = fields.Char(readonly=True)
    sort_order = fields.Integer(string='Sort Order', readonly=True)
    store_id = fields.Many2one(comodel_name='magento.store',
                               string='Store',
                               ondelete='cascade',
                               readonly=True)
    lang_id = fields.Many2one(comodel_name='res.lang', string='Language')
    team_id = fields.Many2one(comodel_name='crm.team',oldname='section_id',
                                 string='Sales Team')
    backend_id = fields.Many2one(
        comodel_name='magento.backend',
        related='store_id.website_id.backend_id',
        string='Instance',
        store=True,
        readonly=True,
        # override 'magento.binding', can't be INSERTed if True:
        required=False,
    )
    import_orders_from_date = fields.Datetime(
        string='Import sale orders from date',
        help='Do not consider non-imported sale orders before this date. '
             'Leave empty to import all sale orders',
    )
    no_sales_order_sync = fields.Boolean(
        string='No Sales Order Synchronization',
        help='Check if the storeview is active in Magento '
             'but its sales orders should not be imported.',
    )
    base_media_url=fields.Char(string='Base Media URL',help="URL for Image store at Magento.")
    website_id = fields.Many2one(string="Website",related="store_id.website_id")
    active = fields.Boolean(string="Active",default=True)
    sale_prefix = fields.Char("Sale Order Prefix",help="A prefix put before the name of imported sales orders.\n"
              "For instance, if the prefix is 'mag-', the sales "
              "order 100000692 in Magento, will be named 'mag-100000692' in ERP.")
    
    
    #CHanges for dashboard
  
    
    _sql_constraints = [
        ('sale_prefix_uniq', 'unique(sale_prefix)',
         "Antoer storeview exist with the same sale prefix already exists")
    ]

    
    @api.model
    def create(self,vals):
        if vals.get('code') == 'admin':
            vals.update({'active' : False})
        return super(MagentoStoreview,self).create(vals)
    
    @api.multi
    def import_sale_order_by_number(self,increment_id):
        session = ConnectorSession(self.env.cr, self.env.uid,
                                   context=self.env.context)
        for storeview in self:
            if storeview.no_sales_order_sync:
                _logger.debug("The storeview '%s' is active in Magento "
                              "but is configured not to import the "
                              "sales orders", storeview.name)
                continue
            try:
                backend_id = storeview.backend_id.id
                self = SaleOrderBatchImport
                filters = {'magento_storeview_id': storeview.magento_id,'increment_id': increment_id}
                env = get_environment(session, 'magento.sale.order', backend_id)
                importer = env.get_connector_unit(SaleOrderBatchImport)
                importer.run(filters)
            except FailedJobError as error: 
                raise ValidationError("Error While importing sale order "+"\n"+str(error))
                
        return True
    
    @api.multi
    def import_sale_orders(self):
        session = ConnectorSession(self.env.cr, self.env.uid,
                                   context=self.env.context)
        import_start_time = datetime.now()
        for storeview in self:
            if storeview.no_sales_order_sync:
                _logger.debug("The storeview '%s' is active in Magento "
                              "but is configured not to import the "
                              "sales orders", storeview.name)
                continue
            backend_id = storeview.backend_id.id
            if storeview.import_orders_from_date:
                from_string = fields.Datetime.from_string
                from_date = from_string(storeview.import_orders_from_date)
            else:
                from_date = None
                
            filters = {'magento_storeview_id': storeview.magento_id,
                 'from_date': from_date,
                 'to_date': import_start_time}
            
            if storeview.backend_id.allow_so_import_on_fly:
                try:
                    env = get_environment(session, 'magento.sale.order', backend_id)
                    importer = env.get_connector_unit(SaleOrderBatchImport)
                    importer.run(filters)
                except Exception as error:
                    raise ValidationError("Error While Preparing batch for sale order"+"\n"+str(error))
            else:
                sale_order_import_batch.delay(
                    session,
                    'magento.sale.order',
                    backend_id,
                    filters,
                    priority=1)
        # Records from Magento are imported based on their `created_at`
        # date.  This date is set on Magento at the beginning of a
        # transaction, so if the import is run between the beginning and
        # the end of a transaction, the import of a record may be
        # missed.  That's why we add a small buffer back in time where
        # the eventually missed records will be retrieved.  This also
        # means that we'll have jobs that import twice the same records,
        # but this is not a big deal because the sales orders will be
        # imported the first time and the jobs will be skipped on the
        # subsequent imports
        return True


@magento
class WebsiteAdapter(GenericAdapter):
    _model_name = ['magento.website']
    _magento_model = 'ol_websites'
    _admin_path = 'system_store/editWebsite/website_id/{id}'
    _path = "/V1/store/websites"
    
    def search(self, filters=None):
        """ Search records according to some criterias
        and returns a list of ids

        :rtype: list
        """
        result = super(WebsiteAdapter,self).search(filters)
        return result
    
    def read(self, id, attributes=None):
        """ Returns the information of a record

        :rtype: dict
        """
        result = {}
        content = req(self.backend_record,self._path)
        for record in content :
            if record['id'] == int(id) :
                return record
        return result


@magento
class StoreAdapter(GenericAdapter):
    _model_name = ['magento.store']
    _magento_model = 'ol_groups'
    _admin_path = 'system_store/editGroup/group_id/{id}'
    _path = "/V1/store/storeGroups"
    
    def search(self, filters=None):
        """ Search records according to some criterias
        and returns a list of ids

        :rtype: list
        """
        result = super(StoreAdapter,self).search(filters)
        return result
    
    def read(self, id, attributes=None):
        """ Returns the information of a record

        :rtype: dict
        """
        
        result = {}
        content = req(self.backend_record,self._path)
        for record in content :
            if record['id'] == int(id) :
                return record
        
        return result



@magento
class StoreviewAdapter(GenericAdapter):
    _model_name = ['magento.storeview']
    _magento_model = 'ol_storeviews'
    _admin_path = 'system_store/editStore/store_id/{id}'
    _path = '/V1/store/storeViews'

    def search(self, filters=None):
        """ Search records according to some criterias
        and returns a list of ids

        :rtype: list
        """
        result = super(StoreviewAdapter,self).search(filters)
        return result
    
    def read(self, id, attributes=None):
        """ Returns the information of a record

        :rtype: dict
        """
        result = {}
        content = req(self.backend_record,self._path)
            
        for record in content :
            if record['id'] == int(id) :
                path = '/V1/store/storeConfigs'
                configs = req(self.backend_record,path)
                for config in configs :
                    if config['id'] == int(id):
                        record['base_media_url']=config['base_media_url']
                return record
        
        return result

@magento
class MetadataBatchImporter(DirectBatchImporter):
    """ Import the records directly, without delaying the jobs.

    Import the Magento Websites, Stores, Storeviews

    They are imported directly because this is a rare and fast operation,
    and we don't really bother if it blocks the UI during this time.
    (that's also a mean to rapidly check the connectivity with Magento).
    """
    _model_name = [
        'magento.website',
        'magento.store',
        'magento.storeview',
    ]


MetadataBatchImport = MetadataBatchImporter  # deprecated


@magento
class WebsiteImportMapper(ImportMapper):
    _model_name = ['magento.website']

    direct = [('code', 'code'),
              ('sort_order', 'sort_order')]

    @mapping
    def name(self, record):
        name = record['name']
        if name is None:
            name = _('Undefined')
        return {'name': name}

    @mapping
    def backend_id(self, record):
        return {'backend_id': self.backend_record.id}


@magento
class StoreImportMapper(ImportMapper):
    _model_name = ['magento.store']

    direct = [('name', 'name')]

    @mapping
    def website_id(self, record):
        binder = self.binder_for(model='magento.website')
        binding_id = binder.to_openerp(record['website_id'])
        return {'website_id': binding_id}


@magento
class StoreviewImportMapper(ImportMapper):
    _model_name = ['magento.storeview']

    direct = [
        ('name', 'name'),
        ('code', 'code'),
        ('sort_order', 'sort_order'),
        ('base_media_url','base_media_url'),
    ]

    @mapping
    def store_id(self, record):
        binder = self.binder_for(model='magento.store')
        binding_id = binder.to_openerp(record['store_group_id'])
        return {'store_id': binding_id}
    
    @mapping
    def lang(self,record):
        path = "/V1/storeview"
        try:
            lang_data = req(self.backend_record,path)
        except :
            raise UserError("""
                        It seems Magento plugin not installed on Magento side.
                                            
                        Resolution : 
                        You have to install magento plugin named "Emipro_Apichange"
                        Please Install Magento plugin 'Emipro_Apichange' on Magento.
                        """)
        for data in lang_data:
            if int(data['store_id']) == record.get('id') :
                lang_code = data.get('language')
                language = self.env['res.lang'].search([('code','=',lang_code)])
                if not language:
                    language = self.env['res.lang'].search([('code','=',lang_code),'|',('active','=',False),('active','=',True)])
                    language_install = self.env['base.language.install'].create({
                                                                                'lang' : language.code
                                                                                }) 
                    language_install.lang_install()
                break
                return {'lang_id' : language.id}
                