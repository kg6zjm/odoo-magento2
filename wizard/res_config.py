from odoo import models, fields,api
from odoo.exceptions import Warning
from odoo.addons.odoo_magento2_ept.models.backend.session import ConnectorSession
from odoo.addons.odoo_magento2_ept.models.backend.connector import (ConnectorUnit,
                                                                   get_environment)
from odoo.addons.odoo_magento2_ept.models.backend.magento_model import WebsiteAdapter
from odoo.addons.odoo_magento2_ept.models.backend.exception import (
                                                                   NetworkRetryableError,
                                                                   FailedJobError,
                                                                   )
from pip._vendor.colorama.ansi import Back


class magento_backend_config(models.TransientModel):
    _name = 'res.config.magento.backend'
    
    @api.model
    def select_versions(self):
        return self.env['magento.backend'].select_versions()
    
    name = fields.Char("Name")
    username = fields.Char("User Name")
    password = fields.Char("Password")
    version = fields.Selection(selection=select_versions, required=True,help="Version Of Magento")
    location = fields.Char(string='Location', required=True, help="Url to magento application")
    warehouse_ids = fields.Many2many('stock.warehouse',string = "Warehouse",help='Warehouses used to compute the stock quantities.',)
    token = fields.Char(string="Access Token")
    
    @api.multi
    def test_magento_connection(self):
        backend_obj = self.env['magento.backend']
        location_url = self.location
        location_url = backend_obj._check_location_url(location_url)
        backend_exist = self.env['magento.backend'].search([
                                                            ('location','=', location_url),
                                                            ('token','=',self.token),
                                                        ])
        if backend_exist:
            raise Warning('Instance already exist with given Credential.')
         
        vals = {
                'name':self.name,
                'token':self.token,
                'username' : self.username,
                'password':self.password,
                'version' : self.version,
                'location' : location_url,
                'warehouse_ids' : self.warehouse_ids and [(6,0,self.warehouse_ids.ids)],
                }
        try:
            backend = self.env['magento.backend'].create(vals)
            context=self._context
            session = ConnectorSession(self._cr, self._uid,context=context)
            mage_env = get_environment(session, "magento.website",backend.id)
            adapter = mage_env.get_connector_unit(WebsiteAdapter)
            result = adapter.search()
        except FailedJobError as e:
            raise Warning((str(e)))    
        except Exception as e:
            raise Warning('Exception during backend creation.\n %s'%(str(e)))
        action = self.env.ref('odoo_magento2_ept.action_connector_config_settings', False)
        result = action and action.read()[0] or {}
        ctx = eval(result.get('context',{}))
        ctx.update({'default_backend_id': backend.id,})
        result['context']=ctx
        return result
        
    
class MagentoConfigSettings(models.TransientModel):
    _name = 'connector.config.settings'
    _description = 'Connector Configuration'
    _inherit = 'res.config.settings'
    
    @api.model
    def _default_bakend(self):
        instances = self.env['magento.backend'].search([])
        if len(instances) == 1 :
            return instances and instances[0].id or False
        else : 
            return False
    
    @api.model
    def select_versions(self):
        return self.env['magento.backend'].select_versions()
        
    @api.model
    def _get_stock_field_id(self):
        field = self.env['ir.model.fields'].search(
            [('model', '=', 'product.product'),
             ('name', '=', 'virtual_available')],
            limit=1)
        return field
        
    backend_id = fields.Many2one('magento.backend', 'Instance', default=_default_bakend)
    warehouse_ids = fields.Many2many('stock.warehouse',string = "Warehouses",help='Warehouses used to compute stock to update on Magento.',)
    
    version = fields.Selection(selection=select_versions)
    location = fields.Char(string='Location', help="URL of Magento")
    company_id = fields.Many2one('res.company',string='Company')
    currency_id = fields.Many2one('res.currency',related='company_id.currency_id')
    default_lang_id = fields.Many2one('res.lang',string='Default Language',
        help="If a default language is selected, the records "
             "will be imported in the translation of this language.\n"
             "Note that a similar configuration exists "
             "for each storeview. First preference will be given to Storeview by system")
    default_category_id = fields.Many2one('magento.product.category',string='Default Product Category',help='If a default category is selected, System will set this category as a default if not found from Magento side.',)
    
    ###
    catalog_price_scope = fields.Selection([('global','Global'),('website','Website')],string="Catalog Price Scope",help="Scope of Price in Magento")
    pricelist_id = fields.Many2one('product.pricelist',string="Pricelist",help="Product price will be taken/set from this pricelist if Catalog Price Scrope is global")
    product_import_page_size = fields.Integer('Product Import Page Size',default=500,help="While import products from Magento, if there are large no of products on Magento side, you can split product list in multiple partitions of x number of records to process in Odoo.")
    allow_import_traslation = fields.Boolean("Import/Export Product data from/to all storeview ?",help="Import product data (e.g Translated value of name,description,etc..) from all storeview if true else import data for only default storeview")
    allow_so_import_on_fly = fields.Boolean("Import Sale Orders on the fly?",help="It Import all Sale Order directly without create Jobs, in this case system will create job in case of any failed transansactions")
    customer_import_page_size = fields.Integer("Customer Import Page Size",default=500,help="While import customers from Magento, you can split customer list in multiple partitions of x number records to process in Odoo.")
    allow_import_image_of_products = fields.Boolean("Import Images of Products",help="Import product images along with product from Magento while import product?")
    
    #Import Product Stock
    is_import_product_stock = fields.Boolean('Is Import Product Stock?',help="Import Product Stock from Magento to Odoo")
    import_stock_warehouse = fields.Many2one('stock.warehouse',string="Stock Warehouse",help="Warehouse for import stock from Magento to Odoo")
    
    product_stock_field_id = fields.Many2one('ir.model.fields',string='Stock Field',default=_get_stock_field_id,domain="[('model', 'in', ['product.product', 'product.template']),('ttype', '=', 'float')]",
                help="Choose the field of the product which will be used for stock inventory updates.\nIf empty, Quantity Available is used.")
    token = fields.Char(string="Access Token")
    is_only_import_export_basic_info=fields.Boolean(string="Is Import/Export Only Basic Catalog Info")

    import_customer_groups = fields.Boolean('Auto import customer groups?',help="Automatic import Customer group")
    import_customer_group_interval_number = fields.Integer('Import customer group Interval Number',help="Repeat every x.",default=1)
    import_customer_group_interval_type = fields.Selection( [('minutes', 'Minutes'),
            ('hours','Hours'), ('work_days','Work Days'), ('days', 'Days'),('weeks', 'Weeks'), ('months', 'Months')], 'Import Customer groups')
    import_customer_group_next_execution = fields.Datetime('Next Execution', help='Next execution time')
    import_customer_group_user_id = fields.Many2one('res.users',string='User',help="Responsible User")
    
    import_customers = fields.Boolean('Auto import customers?',help="Automatic Import Customers")
    import_customers_interval_number = fields.Integer('Import customers Interval Number',help="Repeat every x.",default=1)
    import_customers_interval_type = fields.Selection( [('minutes', 'Minutes'),
            ('hours','Hours'), ('work_days','Work Days'), ('days', 'Days'),('weeks', 'Weeks'), ('months', 'Months')], 'Import Customer groups')
    import_customers_next_execution = fields.Datetime('Next Execution', help='Next execution time')
    import_customer_user_id = fields.Many2one('res.users',string='User',help="Responsible User")
    
    import_product_categories = fields.Boolean('Auto import product categories?',help="Automatic Import Product Category")
    import_product_categories_interval_number = fields.Integer('Import product categories Interval Number',help="Repeat every x.",default=1)
    import_product_categories_interval_type = fields.Selection( [('minutes', 'Minutes'),
            ('hours','Hours'), ('work_days','Work Days'), ('days', 'Days'),('weeks', 'Weeks'), ('months', 'Months')], 'Import Customer groups')
    import_product_categories_next_execution = fields.Datetime('Next Execution', help='Next execution time')
    import_product_category_user_id = fields.Many2one('res.users',string='User',help="Responsible User")
    
    import_products = fields.Boolean('Auto import products?',help="Automatic Import Products")
    import_products_interval_number = fields.Integer('Import products Interval Number',help="Repeat every x.",default=1)
    import_products_interval_type = fields.Selection( [('minutes', 'Minutes'),
            ('hours','Hours'), ('work_days','Work Days'), ('days', 'Days'),('weeks', 'Weeks'), ('months', 'Months')], 'Import Customer groups')
    import_products_next_execution = fields.Datetime('Next Execution', help='Next execution time')
    import_product_user_id = fields.Many2one('res.users',string='User',help="Responsible User")
    
    auto_create_product = fields.Boolean(string="Auto Create Product",help="Checked True, if you want to create new product in Odoo if not found. \nIf not checked, Job will be failed while import order or product..")
    import_sale_orders = fields.Boolean('Auto import sale orders?',help="Automatic Import Sale Orders")
    import_sale_orders_interval_number = fields.Integer('Import sale orders Interval Number',help="Repeat every x.",default=1)
    import_sale_orders_interval_type = fields.Selection( [('minutes', 'Minutes'),
            ('hours','Hours'), ('work_days','Work Days'), ('days', 'Days'),('weeks', 'Weeks'), ('months', 'Months')], 'Import Customer groups')
    import_sale_orders_next_execution = fields.Datetime('Next Execution', help='Next execution time')
    import_sale_order_user_id = fields.Many2one('res.users',string='User',help="Responsible User")
    
    export_product_stock = fields.Boolean('Auto Export Product Stock?',help="Automatic Export Product Stock")
    export_product_stock_interval_number = fields.Integer('Export Product Stock Interval Number',help="Repeat every x.",default=1)
    export_product_stock_interval_type = fields.Selection( [('minutes', 'Minutes'),
            ('hours','Hours'), ('work_days','Work Days'), ('days', 'Days'),('weeks', 'Weeks'), ('months', 'Months')], 'Import Customer groups')
    export_product_stock_next_execution = fields.Datetime('Next Execution', help='Next execution time')
    export_product_stock_user_id = fields.Many2one('res.users',string='User',help="Responsible User")
    
    update_order_status = fields.Boolean('Auto Export Shipment Information?',help="Automatic Export Shipment Information")
    update_order_status_interval_number = fields.Integer('Update Order Status Interval Number',help="Repeat every x.",default=1)
    update_order_status_interval_type = fields.Selection( [('minutes', 'Minutes'),
            ('hours','Hours'), ('work_days','Work Days'), ('days', 'Days'),('weeks', 'Weeks'), ('months', 'Months')], 'Import Customer groups')
    update_order_status_next_execution = fields.Datetime('Next Execution', help='Next execution time')
    update_order_status_user_id = fields.Many2one('res.users',string='User',help="Responsible User")
    
    export_invoice = fields.Boolean('Auto Export Invoice?',help="Automatic Export Invoice")
    export_invoice_interval_number = fields.Integer('Export Invoice Interval Number',help="Repeat every x.",default=1)
    export_invoice_interval_type = fields.Selection( [('minutes', 'Minutes'),
            ('hours','Hours'), ('work_days','Work Days'), ('days', 'Days'),('weeks', 'Weeks'), ('months', 'Months')], 'Import Customer groups')
    export_invoice_next_execution = fields.Datetime('Next Execution', help='Next execution time')
    export_invoice_user_id = fields.Many2one('res.users',string='User',help="Responsible User")
    
    show_tutorial=fields.Boolean(help="How to generate API username and password in magento instance")
    
   

    
    @api.onchange('backend_id')
    def onchange_backend_id(self):
        backend = self.backend_id
        if backend :
            self.warehouse_ids = backend.warehouse_ids and [(6,0,backend.warehouse_ids.ids)] or False
            self.default_lang_id = backend.default_lang_id and backend.default_lang_id.id or False 
            self.default_category_id = backend.default_category_id and backend.default_category_id.id or False
            self.product_stock_field_id = backend.product_stock_field_id and backend.product_stock_field_id.id or False
            self.version = backend.version  or False
            self.location = backend.location  or False
            self.token=backend.token or False
            self.auto_create_product = backend.auto_create_product or False
            self.is_only_import_export_basic_info=backend.is_only_import_export_basic_info or False
            self.allow_import_image_of_products = backend.allow_import_image_of_products or False
            self.catalog_price_scope = backend.catalog_price_scope or False
            self.allow_so_import_on_fly = backend.allow_so_import_on_fly or False
            self.allow_import_traslation = backend.allow_import_traslation or False
            self.pricelist_id = backend.pricelist_id and backend.pricelist_id.id or False
            self.product_import_page_size = backend.product_import_page_size or False
            self.customer_import_page_size = backend.customer_import_page_size or False
            self.is_import_product_stock = backend.is_import_product_stock or False
            self.import_stock_warehouse = backend.import_stock_warehouse and backend.import_stock_warehouse.id or False
            
            import_customer_groups_cron_exist = self.env.ref('odoo_magento2_ept.ir_cron_import_customer_groups_backend_%d'%(backend.id),raise_if_not_found=False)
            if import_customer_groups_cron_exist and import_customer_groups_cron_exist.active:
                self.import_customer_groups = True
                self.import_customer_group_interval_number = import_customer_groups_cron_exist.interval_number or False
                self.import_customer_group_interval_type = import_customer_groups_cron_exist.interval_type or False
                self.import_customer_group_next_execution = import_customer_groups_cron_exist.nextcall or False
            else :
                self.import_customer_groups = False
            
            import_customers_cron_exist = self.env.ref('odoo_magento2_ept.ir_cron_import_customers_backend_%d'%(backend.id),raise_if_not_found=False)
            if import_customers_cron_exist and import_customers_cron_exist.active:
                self.import_customers = True
                self.import_customers_interval_number = import_customers_cron_exist.interval_number or False
                self.import_customers_interval_type = import_customers_cron_exist.interval_type or False
                self.import_customers_next_execution = import_customers_cron_exist.nextcall or False
            else :
                self.import_customers = False
            
            import_product_categories_cron_exist = self.env.ref('odoo_magento2_ept.ir_cron_import_product_categories_backend_%d'%(backend.id),raise_if_not_found=False)
            if import_product_categories_cron_exist and import_product_categories_cron_exist.active:
                self.import_product_categories = True
                self.import_product_categories_interval_number = import_product_categories_cron_exist.interval_number or False
                self.import_product_categories_interval_type = import_product_categories_cron_exist.interval_type or False
                self.import_product_categories_next_execution = import_product_categories_cron_exist.nextcall or False
            else :
                self.import_product_categories = False
            
            import_products_cron_exist = self.env.ref('odoo_magento2_ept.ir_cron_import_products_backend_%d'%(backend.id),raise_if_not_found=False)
            if import_products_cron_exist and import_products_cron_exist.active:
                self.import_products = True
                self.import_products_interval_number = import_products_cron_exist.interval_number or False
                self.import_products_interval_type = import_products_cron_exist.interval_type or False
                self.import_products_next_execution = import_products_cron_exist.nextcall or False
            else :
                self.import_products = False
                
            import_sale_orders_cron_exist = self.env.ref('odoo_magento2_ept.ir_cron_import_sale_orders_backend_%d'%(backend.id),raise_if_not_found=False)
            if import_sale_orders_cron_exist and import_sale_orders_cron_exist.active:
                self.import_sale_orders = True
                self.import_sale_orders_interval_number = import_sale_orders_cron_exist.interval_number or False
                self.import_sale_orders_interval_type = import_sale_orders_cron_exist.interval_type or False
                self.import_sale_orders_next_execution = import_sale_orders_cron_exist.nextcall or False
            else :
                self.import_sale_orders = False         
                
            export_product_stock_cron_exist = self.env.ref('odoo_magento2_ept.ir_cron_update_product_stock_qty_backend_%d'%(backend.id),raise_if_not_found=False)
            if export_product_stock_cron_exist and export_product_stock_cron_exist.active:
                self.export_product_stock = True
                self.export_product_stock_interval_number = export_product_stock_cron_exist.interval_number or False
                self.export_product_stock_interval_type = export_product_stock_cron_exist.interval_type or False
                self.export_product_stock_next_execution = export_product_stock_cron_exist.nextcall or False
            else :
                self.export_product_stock = False
                
            update_order_status_cron_exist = self.env.ref('odoo_magento2_ept.ir_cron_update_order_status_%d'%(backend.id),raise_if_not_found=False)
            if update_order_status_cron_exist and update_order_status_cron_exist.active :
                self.update_order_status = True
                self.update_order_status_interval_number = update_order_status_cron_exist.interval_number or False
                self.update_order_status_interval_type = update_order_status_cron_exist.interval_type or False
                self.update_order_status_next_execution = update_order_status_cron_exist.nextcall or False
                
            export_invoice_cron_exist = self.env.ref('odoo_magento2_ept.ir_cron_export_invoice_%d'%(backend.id),raise_if_not_found=False)
            if export_invoice_cron_exist and export_invoice_cron_exist.active :
                self.export_invoice = True
                self.export_invoice_interval_number = export_invoice_cron_exist.interval_number or False
                self.export_invoice_interval_type = export_invoice_cron_exist.interval_type or False
                self.export_invoice_next_execution = export_invoice_cron_exist.nextcall or False
                
    @api.multi
    def execute(self):
        backend = self.backend_id
        values = {}
        res = super(MagentoConfigSettings,self).execute()
        if backend:
            values['warehouse_ids'] = self.warehouse_ids and [(6,0,self.warehouse_ids.ids)] or False
            values['default_lang_id'] = self.default_lang_id and self.default_lang_id.id or False
            values['default_category_id'] = self.default_category_id and self.default_category_id.id or False
            values['product_stock_field_id'] = self.product_stock_field_id and self.product_stock_field_id.id or False
            values['version'] = self.version or False
            values['location'] = self.location or False
            values['import_customer_groups'] = self.import_customer_groups or False
            values['import_customers']=self.import_customers or False
            values['import_product_categories']=self.import_product_categories or False            
            values['import_products']=self.import_products or False
            values['import_sale_orders']=self.import_sale_orders or False
            values['export_product_stock']=self.export_product_stock or False     
            values['auto_create_product'] = self.auto_create_product or False  
            values['catalog_price_scope'] = self.catalog_price_scope or False
            values['is_only_import_export_basic_info']=self.is_only_import_export_basic_info or False
            values['allow_import_image_of_products'] = self.allow_import_image_of_products
            values['allow_import_traslation'] = self.allow_import_traslation
            values['allow_so_import_on_fly'] = self.allow_so_import_on_fly
            values['pricelist_id'] = self.pricelist_id and self.pricelist_id.id or False
            values['product_import_page_size'] = self.product_import_page_size
            values['customer_import_page_size'] = self.customer_import_page_size
            values['is_import_product_stock'] = self.is_import_product_stock or False
            values['import_stock_warehouse'] = self.import_stock_warehouse and self.import_stock_warehouse.id or False 
            
            self.setup_import_customer_groups(backend)
            self.setup_import_customers(backend)
            self.setup_import_product_categories(backend)
            self.setup_import_products(backend)
            self.setup_import_sale_orders(backend)
            self.setup_export_product_stock_qty(backend)
            self.setup_update_order_status_cron(backend)
            self.setup_export_invoice_cron(backend)
            backend.write(values)
        return res    
    
    @api.multi   
    def setup_import_customer_groups(self,backend):
        if self.import_customer_groups:
            cron_exist = self.env.ref('odoo_magento2_ept.ir_cron_import_customer_groups_backend_%d'%(backend.id),raise_if_not_found=False)
            vals = {
                    "active" : True,
                    "interval_number":self.import_customer_group_interval_number,
                    "interval_type":self.import_customer_group_interval_type,
                    "nextcall":self.import_customer_group_next_execution,
                    "code" : "model._scheduler_import_customer_groups({'backend_id' : %d})"%(backend.id),
                    "user_id" : self.import_customer_group_user_id and self.import_customer_group_user_id.id or False
                    }
                    
            if cron_exist:
                cron_exist.write(vals)
            else:
                import_customer_groups_cron = self.env.ref('odoo_magento2_ept.ir_cron_import_customer_groups',raise_if_not_found=False)
                if not import_customer_groups_cron:
                    raise Warning('Core settings of Magento are deleted, please upgrade Magento module to back this settings.')
                
                name = 'Magento - '+backend.name + ' : Import Customer Groups'
                vals.update({'name' : name})
                new_cron = import_customer_groups_cron.copy(default=vals)
                self.env['ir.model.data'].create({'module':'odoo_magento2_ept',
                                                  'name':'ir_cron_import_customer_groups_backend_%d'%(backend.id),
                                                  'model': 'ir.cron',
                                                  'res_id' : new_cron.id,
                                                  'noupdate' : True
                                                  })
        else:
            cron_exist = self.env.ref('odoo_magento2_ept.ir_cron_import_customer_groups_backend_%d'%(backend.id),raise_if_not_found=False)
            if cron_exist:
                cron_exist.write({'active':False})
        return True
    
    @api.multi   
    def setup_import_customers(self,backend):
        if self.import_customers:
            cron_exist = self.env.ref('odoo_magento2_ept.ir_cron_import_customers_backend_%d'%(backend.id),raise_if_not_found=False)
            vals = {
                    "active" : True,
                    "interval_number":self.import_customers_interval_number,
                    "interval_type":self.import_customers_interval_type,
                    "nextcall":self.import_customers_next_execution,
                    "code" : "model._scheduler_import_partners({'backend_id' : %d})"%(backend.id),
                    "user_id" : self.import_customer_user_id and self.import_customer_user_id.id
                    }
                    
            if cron_exist:
                cron_exist.write(vals)
            else:
                import_customers_cron = self.env.ref('odoo_magento2_ept.ir_cron_import_partners',raise_if_not_found=False)
                if not import_customers_cron:
                    raise Warning('Core settings of Magento are deleted, please upgrade Magento module to back this settings.')
                
                name = 'Magento - '+backend.name + ' : Import Customers'
                vals.update({'name' : name})
                new_cron = import_customers_cron.copy(default=vals)
                self.env['ir.model.data'].create({'module':'odoo_magento2_ept',
                                                  'name':'ir_cron_import_customers_backend_%d'%(backend.id),
                                                  'model': 'ir.cron',
                                                  'res_id' : new_cron.id,
                                                  'noupdate' : True
                                                  })
        else:
            cron_exist = self.env.ref('odoo_magento2_ept.ir_cron_import_customers_backend_%d'%(backend.id),raise_if_not_found=False)
            if cron_exist:
                cron_exist.write({'active':False})
        return True
    
    @api.multi   
    def setup_import_product_categories(self,backend):
        if self.import_product_categories:
            cron_exist = self.env.ref('odoo_magento2_ept.ir_cron_import_product_categories_backend_%d'%(backend.id),raise_if_not_found=False)
            vals = {
                    "active" : True,
                    "interval_number":self.import_product_categories_interval_number,
                    "interval_type":self.import_product_categories_interval_type,
                    "nextcall":self.import_product_categories_next_execution,
                    "code" : "model._scheduler_import_product_categories({'backend_id' : %d})"%(backend.id),
                    "user_id" : self.import_product_category_user_id and self.import_product_category_user_id.id
                    }
                    
            if cron_exist:
                cron_exist.write(vals)
            else:
                import_product_categories_cron = self.env.ref('odoo_magento2_ept.ir_cron_import_product_categories',raise_if_not_found=False)
                if not import_product_categories_cron:
                    raise Warning('Core settings of Magento are deleted, please upgrade Magento module to back this settings.')
                
                name = 'Magento - '+backend.name + ' : Import Product Categories'
                vals.update({'name' : name})
                new_cron = import_product_categories_cron.copy(default=vals)
                self.env['ir.model.data'].create({'module':'odoo_magento2_ept',
                                                  'name':'ir_cron_import_product_categories_backend_%d'%(backend.id),
                                                  'model': 'ir.cron',
                                                  'res_id' : new_cron.id,
                                                  'noupdate' : True
                                                  })
        else:
            cron_exist = self.env.ref('odoo_magento2_ept.ir_cron_import_product_categories_backend_%d'%(backend.id),raise_if_not_found=False)
            if cron_exist:
                cron_exist.write({'active':False})
        return True
    
    @api.multi   
    def setup_import_products(self,backend):
        if self.import_products:
            cron_exist = self.env.ref('odoo_magento2_ept.ir_cron_import_products_backend_%d'%(backend.id),raise_if_not_found=False)
            vals = {
                    "active" : True,
                    "interval_number":self.import_products_interval_number,
                    "interval_type":self.import_products_interval_type,
                    "nextcall":self.import_products_next_execution,
                    "code" : "model._scheduler_import_product_product({'backend_id' : %d})"%(backend.id),
                    "user_id" : self.import_product_user_id and self.import_product_user_id.id
                    }
                    
            if cron_exist:
                cron_exist.write(vals)
            else:
                import_products_cron = self.env.ref('odoo_magento2_ept.ir_cron_import_product_product',raise_if_not_found=False)
                if not import_products_cron:
                    raise Warning('Core settings of Magento are deleted, please upgrade Magento module to back this settings.')
                
                name = 'Magento - '+backend.name + ' : Import Products'
                vals.update({'name' : name})
                new_cron = import_products_cron.copy(default=vals)
                self.env['ir.model.data'].create({'module':'odoo_magento2_ept',
                                                  'name':'ir_cron_import_products_backend_%d'%(backend.id),
                                                  'model': 'ir.cron',
                                                  'res_id' : new_cron.id,
                                                  'noupdate' : True
                                                  })
        else:
            cron_exist = self.env.ref('odoo_magento2_ept.ir_cron_import_products_backend_%d'%(backend.id),raise_if_not_found=False)
            if cron_exist:
                cron_exist.write({'active':False})
        return True
    
    @api.multi   
    def setup_import_sale_orders(self,backend):
        if self.import_sale_orders:
            cron_exist = self.env.ref('odoo_magento2_ept.ir_cron_import_sale_orders_backend_%d'%(backend.id),raise_if_not_found=False)
            vals = {
                    "active" : True,
                    "interval_number":self.import_sale_orders_interval_number,
                    "interval_type":self.import_sale_orders_interval_type,
                    "nextcall":self.import_sale_orders_next_execution,
                    "code" : "model._scheduler_import_sale_orders({'backend_id' : %d})"%(backend.id),
                    "user_id" : self.import_sale_order_user_id and self.import_sale_order_user_id.id
                    }
                    
            if cron_exist:
                cron_exist.write(vals)
            else:
                import_sale_orders_cron = self.env.ref('odoo_magento2_ept.ir_cron_import_sale_orders',raise_if_not_found=False)
                if not import_sale_orders_cron:
                    raise Warning('Core settings of Magento are deleted, please upgrade Magento module to back this settings.')
                
                name = 'Magento - '+backend.name + ' : Import Sale Orders'
                vals.update({'name' : name})
                new_cron = import_sale_orders_cron.copy(default=vals)
                self.env['ir.model.data'].create({'module':'odoo_magento2_ept',
                                                  'name':'ir_cron_import_sale_orders_backend_%d'%(backend.id),
                                                  'model': 'ir.cron',
                                                  'res_id' : new_cron.id,
                                                  'noupdate' : True
                                                  })
        else:
            cron_exist = self.env.ref('odoo_magento2_ept.ir_cron_import_sale_orders_backend_%d'%(backend.id),raise_if_not_found=False)
            if cron_exist:
                cron_exist.write({'active':False})
        return True
    
    @api.multi   
    def setup_export_product_stock_qty(self,backend):
        if self.export_product_stock:
            cron_exist = self.env.ref('odoo_magento2_ept.ir_cron_update_product_stock_qty_backend_%d'%(backend.id),raise_if_not_found=False)
            vals = {
                    "active" : True,
                    "interval_number":self.export_product_stock_interval_number,
                    "interval_type":self.export_product_stock_interval_type,
                    "nextcall":self.export_product_stock_next_execution,
                    "code" : "model._scheduler_update_product_stock_qty({'backend_id' : %d})"%(backend.id),
                    "user_id" : self.export_product_stock_user_id and self.export_product_stock_user_id.id
                    }
                    
            if cron_exist:
                cron_exist.write(vals)
            else:
                export_product_stock_cron = self.env.ref('odoo_magento2_ept.ir_cron_update_product_stock_qty',raise_if_not_found=False)
                if not export_product_stock_cron:
                    raise Warning('Core settings of Magento are deleted, please upgrade Magento module to back this settings.')
                
                name = 'Magento - '+backend.name + ' : Update Stock Quantities'
                vals.update({'name' : name})
                new_cron = export_product_stock_cron.copy(default=vals)
                self.env['ir.model.data'].create({'module':'odoo_magento2_ept',
                                                  'name':'ir_cron_update_product_stock_qty_backend_%d'%(backend.id),
                                                  'model': 'ir.cron',
                                                  'res_id' : new_cron.id,
                                                  'noupdate' : True
                                                  })
        else:
            cron_exist = self.env.ref('odoo_magento2_ept.ir_cron_update_product_stock_qty_backend_%d'%(backend.id),raise_if_not_found=False)
            if cron_exist:
                cron_exist.write({'active':False})
        return True
    
    @api.multi   
    def setup_update_order_status_cron(self,backend):
        if self.update_order_status:
            cron_exist = self.env.ref('odoo_magento2_ept.ir_cron_update_order_status_%d'%(backend.id),raise_if_not_found=False)
            vals = {
                    "active" : True,
                    "interval_number":self.update_order_status_interval_number,
                    "interval_type":self.update_order_status_interval_type,
                    "nextcall":self.update_order_status_next_execution,
                    "code" : "model._scheduler_update_order_status({'backend_id' : %d})"%(backend.id),
                    "user_id" : self.update_order_status_user_id and self.update_order_status_user_id.id
                    }
                    
            if cron_exist:
                cron_exist.write(vals)
            else:
                update_order_status_cron = self.env.ref('odoo_magento2_ept.ir_cron_update_order_status',raise_if_not_found=False)
                if not update_order_status_cron:
                    raise Warning('Core settings of Magento are deleted, please upgrade Magento module to back this settings.')
                
                name = 'Magento - '+backend.name + ' : Export Shipment Information'
                vals.update({'name' : name})
                new_cron = update_order_status_cron.copy(default=vals)
                self.env['ir.model.data'].create({'module':'odoo_magento2_ept',
                                                  'name':'ir_cron_update_order_status_%d'%(backend.id),
                                                  'model': 'ir.cron',
                                                  'res_id' : new_cron.id,
                                                  'noupdate' : True
                                                  })
        else:
            cron_exist = self.env.ref('odoo_magento2_ept.ir_cron_update_order_status_%d'%(backend.id),raise_if_not_found=False)
            if cron_exist:
                cron_exist.write({'active':False})
        return True
    
    @api.multi   
    def setup_export_invoice_cron(self,backend):
        if self.export_invoice:
            cron_exist = self.env.ref('odoo_magento2_ept.ir_cron_export_invoice_%d'%(backend.id),raise_if_not_found=False)
            vals = {
                    "active" : True,
                    "interval_number":self.export_invoice_interval_number,
                    "interval_type":self.export_invoice_interval_type,
                    "nextcall":self.export_invoice_next_execution,
                    "code" : "model._scheduler_export_invoice({'backend_id' : %d})"%(backend.id)
                    }
                    
            if cron_exist:
                cron_exist.write(vals)
            else:
                export_inovice_cron = self.env.ref('odoo_magento2_ept.ir_cron_export_invoice',raise_if_not_found=False)
                if not export_inovice_cron:
                    raise Warning('Core settings of Magento are deleted, please upgrade Magento module to back this settings.')
                
                name = 'Magento - '+backend.name + ' : Export Invoice'
                vals.update({'name' : name})
                new_cron = export_inovice_cron.copy(default=vals)
                self.env['ir.model.data'].create({'module':'odoo_magento2_ept',
                                                  'name':'ir_cron_export_invoice_%d'%(backend.id),
                                                  'model': 'ir.cron',
                                                  'res_id' : new_cron.id,
                                                  'noupdate' : True
                                                  })
        else:
            cron_exist = self.env.ref('odoo_magento2_ept.ir_cron_export_invoice_%d'%(backend.id),raise_if_not_found=False)
            if cron_exist:
                cron_exist.write({'active':False})
        return True
    