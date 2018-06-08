# -*- coding: utf-8 -*-
##############################################################################
#
#    Author: Guewen Baconnier, David Beal
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

##############################################################################

import logging
import urllib.parse
import urllib.request as urllib2
import base64
import sys
from datetime import datetime, timedelta
from collections import defaultdict
from odoo import models, fields, api, tools, _
from odoo.exceptions import ValidationError
from odoo.addons.odoo_magento2_ept.models.logs.job import job, related_action,unwrap_binding
from odoo.addons.odoo_magento2_ept.models.backend.event import (on_export_product_to_magento,on_export_magento_product_image)
from odoo.addons.odoo_magento2_ept.models.unit.synchronizer import (Importer,Exporter,)
from odoo.addons.odoo_magento2_ept.models.unit.export_synchronizer import (MagentoExporter , export_record)
from odoo.addons.odoo_magento2_ept.models.unit.delete_synchronizer import MagentoDeleter
from odoo.addons.odoo_magento2_ept.models.backend.exception import (MappingError,InvalidDataError,IDMissingInBackend,FailedJobError,RetryableJobError,OrderImportRuleRetry,NothingToDoJob)
from odoo.addons.odoo_magento2_ept.models.unit.mapper import (mapping,ImportMapper,ExportMapper,changed_by)
from odoo.addons.odoo_magento2_ept.models.unit.backend_adapter import (GenericAdapter,MAGENTO_DATETIME_FORMAT)
from odoo.addons.odoo_magento2_ept.models.unit.import_synchronizer import (DelayedBatchImporter,MagentoImporter,TranslationImporter,ProductPriceImporter,)
from odoo.addons.odoo_magento2_ept.models.backend.connector import get_environment
from odoo.addons.odoo_magento2_ept.models.backend.backend import magento
from odoo.addons.odoo_magento2_ept.models.api_request import req
from odoo.addons.odoo_magento2_ept.models.search_criteria import create_search_criteria
from odoo.addons.odoo_magento2_ept.python_library.php import Php
from odoo.addons.odoo_magento2_ept.models.backend.session import ConnectorSession
import odoo.addons.decimal_precision as dp
from lxml import etree
from odoo.addons.odoo_magento2_ept.models.unit.import_synchronizer import (IMPORT_DELTA_BUFFER,import_batch)
from odoo.addons.odoo_magento2_ept.models.product.product_attribute import field_mapping
from odoo.addons.odoo_magento2_ept.models.product.product_attribute_group import AttributeGroupAdapter
 
_logger = logging.getLogger(__name__)


class MagentoProductProduct(models.Model):
    _name = 'magento.product.product'
    _inherit = 'magento.binding'
    _inherits = {'product.product': 'erp_id'}
    _description = 'Magento Product'
    
    @api.multi
    def view_openerp_product(self):
        if self.erp_id:
            if self.product_type == 'configurable':
                return {
                    'name':'Odoo Product',
                    'type': 'ir.actions.act_window',
                    'res_model': 'product.template',
                    'view_type': 'form',
                    'view_mode': 'tree,form',
                    'domain' : [('id','=',self.erp_id.product_tmpl_id.id)],
                }
            return {
                    'name':'Odoo Product',
                    'type': 'ir.actions.act_window',
                    'res_model': 'product.product',
                    'view_type': 'form',
                    'view_mode': 'tree,form',
                    'domain' : [('id','=',self.erp_id.id)],
                }
        return
    
    @api.model
    def product_type_get(self):
        return [
            ('simple', 'Simple Product'),
            ('configurable', 'Configurable Product'),
            ('giftvoucher','Gift Card'),
            ('virtual', 'Virtual Product')
            # XXX activate when supported
            # ('grouped', 'Grouped Product'),
            # ('virtual', 'Virtual Product'),
            # ('bundle', 'Bundle Product'),
            # ('downloadable', 'Downloadable Product'),
        ]
        
        
    @api.multi
    def _attr_grp_ids(self):
        for obj in self:
            obj.attribute_group_ids = obj.attribute_set_id.attribute_group_ids.ids

    magento_product_name = fields.Char("Name",translate=True)   
    attribute_option_ids = fields.Many2many('magento.attribute.option',string="Magento Attributes")
    openerp_tmpl_id = fields.Many2one('product.template',string='Product Template')
    magento_tmpl_id = fields.Many2one('magento.product.template',string="Magento Product template")
    erp_id = fields.Many2one(comodel_name='product.product',
                                 string='Product',
                                 required=True,
                                 ondelete='restrict',copy=False)
    website_ids = fields.Many2many(comodel_name='magento.website',string='Websites',readonly=False, domain="[('backend_id','=',backend_id)]")
    created_at = fields.Date('Created At')
    updated_at = fields.Date('Updated At')
    product_type = fields.Selection(selection='product_type_get',
                                    string='Product Type',
                                    default='simple',)
    no_stock_sync = fields.Boolean(
        string='No Stock Synchronization',
        required=False,
        help="Check this to exclude the product "
             "from stock synchronizations.",
    )
        
    export_stock_type = fields.Selection(selection=[('fixed','Export Fixed Qty'),
                                                    ('actual','Export Actual Stock')],
                                         string="Export Stock Type",
                                         default='actual')
    export_fix_value = fields.Float(string="Fixed Stock Quantity",digits=dp.get_precision("Product UoS"))
    magento_sku = fields.Char("Magento SKU")
    exported_in_magento = fields.Boolean('Exported in Magento')
    category_ids = fields.Many2many("magento.product.category",string="Category")
    attribute_set_id=fields.Many2one(comodel_name='magento.attribute.set',string='Attribute Set')
    attribute_group_ids=fields.Many2many('magento.attribute.group',compute=_attr_grp_ids, string='Groups')
    description = fields.Text("Description",translate=True)
    description_sale = fields.Text('Sale Description', translate=True,)
    meta_description = fields.Text('Meta Descritption',translate=True)
    meta_title = fields.Text("Meta Title",translate=True)
    meta_keyword = fields.Text("Meta keyword",translate=True)
    url_key = fields.Char("URL key",translate=True)
    RECOMPUTE_QTY_STEP = 1000  # products at a time
    
    """Import products from Magento"""
    @api.multi
    def import_products(self,backends):
        session = ConnectorSession(self.env.cr, self.env.uid,self.env.context)
        for backend in backends:
            backend.check_magento_structure()
            from_date = getattr(backend, 'last_product_import_date')
            if from_date:
                from_date = fields.Datetime.from_string(from_date)
            else:
                from_date = None
            import_batch.delay(session, 'magento.product.product',
                               backend.id,
                               filters={'from_date': from_date,
                                        'to_date': datetime.now()})
            #backend.write({'last_product_import_date' : datetime.now()})
        return True
    
    
    @api.multi
    def copy(self,default={}):
        default.update({'erp_id':self.erp_id.id})
        return super(MagentoProductProduct,self).copy(default)

    
    @api.one
    @api.constrains('backend_id','attribute_set_id')
    def _check_magento_product_and_attribute_set(self):
        if self.backend_id and (self.attribute_set_id and not self.attribute_set_id.backend_id.id == self.backend_id.id ):
            raise ValidationError(_('Please select attribute set from proper Magento Global for product'))
    
    @api.multi
    def export_stock_magento(self):
        context = self._context or {}
        active_ids = context.get('active_ids')
        product_ids = self.search([('id','in',active_ids)])       
        if product_ids:
            self.export_multiple_product_stock_to_magento(product_ids)
            
    @api.multi
    def _get_product_stock(self,product,backend):
        if backend.product_stock_field_id :
            stock_field = backend.product_stock_field_id.name
        else :
            stock_field = 'virtual_available'
        warehouse_ids = backend.warehouse_ids
        if not warehouse_ids:
            for website_id in backend.website_ids:
                warehouse_ids.append(website_id.warehouse_id)
        qty_to_update = 0.0
        if product.export_stock_type == 'fixed' :
            qty_to_update = product.export_fix_value
        if product.export_stock_type == 'actual' :
            for warehouse_id in warehouse_ids:
                location_id = warehouse_id and warehouse_id.lot_stock_id and warehouse_id.lot_stock_id.id
                if location_id:
                    odoo_product = self.env['product.product'].with_context(location=location_id).browse(product.erp_id.id)
                    if hasattr(product, stock_field):
                        actual_stock = getattr(odoo_product,stock_field)
                    else:
                        actual_stock = odoo_product.qty_available
                qty_to_update = qty_to_update + actual_stock
            if qty_to_update < 0.0 :
                    qty_to_update = 0.0
        return qty_to_update
        
    @api.multi
    def export_multiple_product_stock_to_magento(self,products):
        session = ConnectorSession(self.env.cr, self.env.uid,self.env.context)
        stock_data = []
        backends = defaultdict(self.browse)
        for product in products:
            backends[product.backend_id] |= product
        for backend,products in backends.items() :
            for product in products:
                product_qty = self._get_product_stock(product,backend)
                if product_qty > 0.0 :
                    product_stock_dict = {
                            'sku' : product.magento_sku,
                            'qty' : product_qty,
                            'is_in_stock' : 1,
                        }
                    stock_data.append(product_stock_dict)
                else :
                    continue   
            
            if stock_data :
                data = {
                        'skuData' : stock_data
                    }
                
                export_product_inventory.delay(session,self._name,backend,data)
    
    @api.multi
    def create_product_inventory(self,products):
        stock_to_import = []
        stock_inventory = self.env['stock.inventory']
        backends = defaultdict(self.browse)
        for product in products:
            backends[product.backend_id] |= product
        for backend,products in backends.items():
            if backend.is_import_product_stock :
                location = backend.import_stock_warehouse and backend.import_stock_warehouse.lot_stock_id
                for product in products:
                    sku = product.magento_sku
                    url = '/V1/stockItems/%s'%(sku)
                    stock_data = req(product.backend_id,url)
                    if stock_data:
                        qty = stock_data.get('qty')
                        if qty > 0.0 :
                            stock_dict = {'product_qty' : qty,'product_id' :product.erp_id}
                            stock_to_import.append(stock_dict)
                stock_inventory.create_stock_inventory(stock_to_import,location,True)
        return True
        
        
            
    @api.multi
    def import_product_stock_from_magento(self):
        context = self._context or {}
        active_ids = context.get('active_ids')
        product_ids = self.search([('id','in',active_ids)])       
        if product_ids:
            self.create_product_inventory(product_ids)
            
    
    @api.multi
    def read(self,fields=None,load='_classic_read'):
        result = super(MagentoProductProduct,self).read(fields=fields,load=load)
        context=dict(self._context) or {}
        flag = True
        for field in fields:
            if not result[0].get(field,False):
                flag = False
        if context.get('open_attributes',False):
            context.update({'read_option':True})
            dict_to_update = self.with_context(context).default_get(fields)
            result[0].update(dict_to_update)
        return result
         
    
    @api.model
    def fields_view_get(self, view_id=None, view_type='form', toolbar=False, submenu=False):
        context=dict(self._context) or {}
        result = super(MagentoProductProduct, self).fields_view_get(view_id=view_id,view_type=view_type,toolbar=toolbar, submenu=submenu)
        if view_type == 'form' and context.get('attribute_group_ids'):
            eview = etree.fromstring(result['arch'])
            attributes_notebook, toupdate_fields = self.env['magento.product.attribute']._build_attributes_notebook(context['attribute_group_ids'])
            result['fields'].update(self.fields_get(toupdate_fields))
            if context.get('open_attributes'):
                placeholder = eview.xpath("//separator[@name='attributes_placeholder']")[0]
                placeholder.getparent().replace(placeholder, attributes_notebook)
            elif context.get('open_product_by_attribute_set'):
                main_page = etree.Element('page', string=_('Custom Attributes'))
                main_page.append(attributes_notebook)
                info_page = eview.xpath("//page[@string='%s']" % (_('Information'),))[0]
                info_page.addnext(main_page)
            result['arch'] = etree.tostring(eview,encoding='unicode')
        return result
    
    @api.multi
    def open_attributes(self):
        self.ensure_one()
        ir_model_data = self.env['ir.model.data']
        ir_model_data_obj = ir_model_data.search([['model', '=', 'ir.ui.view'], ['name', '=', 'product_attributes_extended_form_view']])
        res_id =ir_model_data_obj and ir_model_data_obj[0]['res_id'] or False
        attr_grp = self.read(['attribute_group_ids'])
        grp_ids=attr_grp and attr_grp[0] and attr_grp[0]['attribute_group_ids'] or []#[self.ids[0]]
        ctx =  {}
        ctx.update({'magento_product_id':self.id,
                    'active_id':self.id,
                    'active_ids':self.ids,
                    'open_attributes':True,
                    'attribute_group_ids':grp_ids,
                    'active_model':'magento.product.product'
                    })
        return {
            'name': 'Product Attributes',
            'view_type': 'form',
            'view_mode': 'form',
            'view_id': [res_id],
            'res_model': 'magento.product.product',
            'context': ctx,
            'type': 'ir.actions.act_window',
            'nodestroy': True,
            'target': 'new',
            'res_id': self.id,
        }
        
    @api.model
    def fields_get(self,toupdate_fields=False):
        context=dict(self._context) or {}
        result = super(MagentoProductProduct, self).fields_get()
        if context.get('attribute_group_ids') and toupdate_fields and context.get('open_attributes'):
            magento_product = self.env['magento.product.product'].browse(context.get('magento_product_id'))
            for field in toupdate_fields:
                attribute = self.env['magento.product.attribute'].browse(field)
                list_of_configurable_attrs = []
                if magento_product:
                    list_of_configurable_attrs = [attribute_value.attribute_id for attribute_value in magento_product.attribute_value_ids]
                if attribute.erp_id in list_of_configurable_attrs:
                    continue
                if attribute:
                    update_fields = {}
                    if attribute.type in ['select','multiselect']:
                        update_fields.update({
                            'relation':'magento.attribute.option',
                        })
                    value_dict = {
                          'change_default': False,
                          'string': attribute.name,
                          'searchable': False,
                          'required': attribute.is_required,
                          'manual': False,
                          'readonly': False,
                          'company_dependent': False,
                          'sortable': False,
                          'translate': False,
                          'type': attribute._field_type_mapping.get(attribute.type),
                          'store': False
                    }
                    value_dict_final = value_dict.copy()
                    value_dict_final.update(update_fields)
                    temp_dict = {attribute.attribute_code:value_dict_final}
                 
                result.update(temp_dict)
        return result
         
    @api.model
    def default_get(self, fields):
        context=dict(self._context) or {}
        result = super(MagentoProductProduct, self).default_get(fields)
        product = self.env['magento.product.product']
        self = self.env['magento.attribute.option']
        flag = True
        for field in fields:
            if not result.get(field):
                flag = False
        if flag:
            return result
        if context.get('read_option'):
            magento_product = self.env['magento.product.product'].browse(context.get('magento_product_id'))
            temp_dict = {}
            attribute_group_id = context['attribute_group_ids']
            attribute_group_objects = self.env['magento.attribute.group'].browse(attribute_group_id)
            #Process to set default values of attribute
            for field in fields:
                magento_product_attribute = self.env['magento.product.attribute'].search([('attribute_code','=',field)],limit=1)
                 
                if not magento_product_attribute:
                    continue
                list_of_configurable_attrs = [attribute_value.attribute_id for attribute_value in product.attribute_value_ids]
                if magento_product_attribute.erp_id in list_of_configurable_attrs:
                    continue
                for attribute in magento_product_attribute:
                    multi_select = []
                    for attribute_option in attribute.option_ids:
                        if attribute_option.is_default:
                            if attribute.type == 'select':
                                temp_dict[attribute.attribute_code] = attribute_option.id
                            elif attribute.type == 'multiselect':
                                multi_select.append(attribute_option.id)
                                temp_dict[attribute.attribute_code] = multi_select
                            elif attribute.type == 'boolean':
                                temp_dict[attribute.attribute_code] = True if attribute_option.name == "Yes" else False
                                 
                    if attribute.default_value and not temp_dict.get(attribute.attribute_code,False):
                        if attribute.type == 'select':
                            temp_dict[attribute.attribute_code] = attribute_option.id
                        elif attribute.type == 'multiselect':
                            multi_select.append(attribute_option.id)
                            temp_dict[attribute.attribute_code] = multi_select
                        elif attribute.type == 'boolean':
                            temp_dict[attribute.attribute_code] = True if attribute_option.name == "Yes" else False
                        else:
                            temp_dict[attribute.attribute_code] = attribute.default_value or False
                    
                    skip_multiselect = []
                    if not attribute.default_value and not temp_dict.get(attribute.attribute_code,False):
                        if attribute.type == 'select':
                            temp_dict[attribute.attribute_code] = attribute_option.id
                        elif attribute.type == 'multiselect':
                            multi_select.append(attribute_option.id)
                            temp_dict[attribute.attribute_code] = multi_select
                        elif attribute.type == 'boolean':
                            temp_dict[attribute.attribute_code] = True if attribute_option.name == "Yes" else False
                        else:
                            temp_dict[attribute.attribute_code] = False
                    for tmp_attribute_option in magento_product.attribute_option_ids:
                        if tmp_attribute_option.magento_attribute_id.type == 'select':
                            temp_dict[tmp_attribute_option.magento_attribute_id.attribute_code] =tmp_attribute_option.id
                        elif tmp_attribute_option.magento_attribute_id.type == 'multiselect' and tmp_attribute_option not in skip_multiselect:
                            domain = []
                            domain.append(('magento_attribute_id.type','=','multiselect'))
                            domain.append(('magento_attribute_id','=',tmp_attribute_option.magento_attribute_id.id))
                            domain.append(('magento_product_ids','in',[magento_product.id]))
                            attribute_options = self.search(domain)
                            tmp_list = []
                            for attribute_option in attribute_options:
                                tmp_list.append(attribute_option.id)
                            if tmp_list:
                                temp_dict[tmp_attribute_option.magento_attribute_id.attribute_code] = tmp_list
                            skip_multiselect.append(tmp_attribute_option)
                        elif tmp_attribute_option.magento_attribute_id.type == 'boolean':
                            flag = False
                            if tmp_attribute_option.name == "1":
                                flag = True
                            temp_dict[tmp_attribute_option.magento_attribute_id.attribute_code] = flag
                        elif tmp_attribute_option.magento_attribute_id.type == 'integer':
                            temp_dict[tmp_attribute_option.magento_attribute_id.attribute_code] = int(tmp_attribute_option.name)
                        elif tmp_attribute_option.magento_attribute_id.type == 'float':
                            temp_dict[tmp_attribute_option.magento_attribute_id.attribute_code] = float(tmp_attribute_option.name)
                        elif tmp_attribute_option.magento_attribute_id.type == 'text':
                            temp_dict[tmp_attribute_option.magento_attribute_id.attribute_code] = tmp_attribute_option.name
                        elif tmp_attribute_option.magento_attribute_id.type == 'char':
                            temp_dict[tmp_attribute_option.magento_attribute_id.attribute_code] = tmp_attribute_option.name
                        else:
                            temp_dict[tmp_attribute_option.magento_attribute_id.attribute_code] = tmp_attribute_option.name or False
            result_final = result
            result_final.update(temp_dict) 
            result = result_final
        return result


    def create_or_update_attribute_record(self,record):
        attribute_option = self.env['magento.attribute.option']
        for attribute_code,attribute_value in record.items():
            attr_value = attribute_value
            attr_record = self.env['magento.product.attribute'].search([('backend_id','=',self.backend_id.id),('attribute_code','=',attribute_code)],limit=1)
            #sattr_record = attr_binder.to_openerp(attr_record.magento_id,browse=True)            
            list_of_configurable_attrs = [tmp_attribute_value.attribute_id for tmp_attribute_value in self.attribute_value_ids]
            if attr_record.erp_id in list_of_configurable_attrs:
                continue
            if attr_record.type == 'multiselect' and not attribute_value :
                continue
            elif attr_record.type == 'select' and attribute_value == '0':
                continue
            elif attribute_value == '':
                continue
            create_variants = attr_record.type in ['select']
            if attr_record.type == 'multiselect':
                selected_ids = attribute_value[0][2]
                magento_attribute_option_domain = [('id','in',selected_ids)]
                magento_options = self.env['magento.attribute.option'].search(magento_attribute_option_domain)
                updated_options = []
                for option in magento_options:
                    if self.id not in option.magento_product_ids.ids:
                        self_ids = [(4, self, None) for self in [self.id]]
                        option.write({'magento_product_ids':self_ids})
                    updated_options.append(option.id)   
                magento_options = self.env['magento.attribute.option'].search([('magento_product_ids','=',self.id),('magento_attribute_id','=',attr_record.id),('id','not in',updated_options)])   
                for option in magento_options:
                    self_ids = [(3, self, None) for self in [self.id]]
                    magento_options.write({'magento_product_ids':self_ids})
                    
            elif attr_record.type == 'select':
                ex_attribute_option = attribute_option.search([('magento_product_ids','=',self.id),('magento_attribute_id','=',attr_record.id)])
                if ex_attribute_option:
                    ex_attribute_option.write({'magento_product_ids':[(3,self.id)]})
                attribute_option = attribute_option.search([('id','=',attribute_value)])
                if attribute_option:
                    self_ids = [(4, self, None) for self in [self.id]]
                    attribute_option.write({'magento_product_ids':self_ids})

            elif attr_record.type == 'boolean':
                domain = [('magento_product_ids','=',self.id),('magento_attribute_id','=',attr_record.id)]
                ex_attribute_option = attribute_option.search(domain)
                if ex_attribute_option:
                    self_ids = [(3, self, None) for self in [self.id]]
                    ex_attribute_option.write({'magento_product_ids':self_ids})
                domain.append(('name','=',"1" if attribute_value else "0"))
                attribute_option = attribute_option.search(domain,limit=1)
                if attribute_option:
                    self_ids = [(4, self, None) for self in [self.id]]
                    attribute_option.write({'magento_product_ids':self_ids})
                else:
                    attribute_option.create({'magento_attribute_id':attr_record.id,
                                             'attribute_id':attr_record.erp_id.id,
                                             'create_variants':create_variants,
                                             'magento_id':self.magento_id,
                                             'magento_product_ids':[(6,0,[self.id])],
                                             'backend_id':self.backend_id.id,
                                             'name':"1" if attribute_value else "0"
                                             })
            else:
                search_domain  = []
                search_domain.append(('magento_attribute_id','=',attr_record.id))
                search_domain.append(('magento_product_ids','=',self.id))
                search_domain.append(('name','=',str(attribute_value)))
                new_attribute_option = attribute_option.search(search_domain)
                if not new_attribute_option:
                    new_attribute_option.create({'magento_attribute_id':attr_record.id,
                                             'attribute_id':attr_record.erp_id.id,
                                             'create_variants':create_variants,
                                             'magento_id':self.magento_id,
                                             'magento_product_ids':[(6,0,[self.id])],
                                             'backend_id':self.backend_id.id,
                                             'name':attribute_value
                                             })
                else:
                    new_attribute_option.write({'magento_attribute_id':attr_record.id,
                                             'attribute_id':attr_record.erp_id.id,
                                             'create_variants':create_variants,
                                             'magento_id':self.magento_id,
                                             'magento_product_ids':[(6,0,[self.id])],
                                             'backend_id':self.backend_id.id,
                                             'name':attribute_value
                                             })
                    
        return
    
    @api.multi
    def write(self,vals):
        context=dict(self._context) or {}
        if context.get('open_attributes') and context.get('magento_product_id'):
            self.with_context({'open_attributes':False}).create_or_update_attribute_record(vals)
            return
        else:
            return super(MagentoProductProduct,self).write(vals)
    
    @api.multi
    def set_default_value_for_attribute(self,product_id,attribute_set):
        magento_attribute_option = self.env['magento.attribute.option']
        product = self.browse(product_id)
        attribute_set = self.env['magento.attribute.set'].browse(attribute_set)
        for attribute_group in attribute_set.attribute_group_ids:
            for attribute in attribute_group.magento_attribute_ids:
                search_domain  = []
                search_domain.append(('magento_attribute_id','=',attribute.id))
                search_domain.append(('magento_product_ids','=',product.id))
                attribute_option = self.env['magento.attribute.option'].search([('magento_product_ids','=',product.id),('magento_attribute_id','=',attribute.id),('backend_id','=',product.backend_id.id)])
                if attribute_option:
                    continue
                if attribute.default_value:
                    create_variants = attribute.type in ['select']
                    if create_variants:
                        search_domain.append(('magento_id','=',attribute.default_value))
                    elif attribute.type == 'multiselect':
                        if isinstance(attribute.default_value,str) :
                            attr_value = attribute.default_value.split(',')
                            search_domain.append(('magento_id','in',attr_value))
                    else:
                        search_domain.append(('name','=',attribute.default_value))
                        
                    new_attribute_option = magento_attribute_option.search(search_domain)
                    if attribute.type == 'multiselect':
                        magento_attribute_option_domain = [('magento_attribute_id','=',attribute.id)]
                        if isinstance(attribute.default_value,str) :
                            attr_value = attribute.default_value.split(',')
                        magento_attribute_option_domain.append(('magento_id','in',attr_value))
                        magento_options = self.env['magento.attribute.option'].search(magento_attribute_option_domain)
                        for option in magento_options:
                            option.write({'magento_product_ids':[(4,product.id,0)]})
                            
                    elif attribute.type == 'select':
                        attribute_option = magento_attribute_option.search([('magento_attribute_id','=',attribute.id),('magento_id','=',attribute.default_value)])
                        attribute_option.write({'magento_product_ids':[(4,product.id,0)]})
                    else:
                        if not new_attribute_option:
                            new_attribute_option.create({'magento_attribute_id':attribute.id,
                                                     'attribute_id':attribute.erp_id.id,
                                                     'create_variants':create_variants,
                                                     'magento_id':product.magento_id,
                                                     'magento_product_ids':[(6,0,[product.id])],
                                                     'backend_id':product.backend_id.id,
                                                     'name':attribute.default_value
                                                     })
                        else:
                            new_attribute_option.write({'magento_attribute_id':attribute.id,
                                                     'attribute_id':attribute.erp_id.id,
                                                     'create_variants':create_variants,
                                                     'magento_id':product.magento_id,
                                                     'magento_product_ids':[(6,0,[product.id])],
                                                     'backend_id':product.backend_id.id,
                                                     'name':attribute.default_value
                                                     })
        
    @api.one
    def save_and_close_product_attributes(self):
        context=dict(self._context) or {}
        self.set_default_value_for_attribute(self.id,self.attribute_set_id.id)
        context.update({'open_attributes':False})
        context.update({'read_options':False})   
        return {'type': 'ir.actions.act_window_close','context':context}
    
    @api.multi
    def update_magento_product(self):
        session = ConnectorSession(self.env.cr, self.env.uid,context=self.env.context)
        for record in self:
            update_product_to_magento.delay(session,'magento.product.product',record.id)
    
    @api.multi
    def get_odoo_product(self,sku,backend_id):
        magento_product = self.get_magento_product(sku, backend_id)
        odoo_product = self.env['product.product'].search([('default_code','=',sku)],limit=1)
        if magento_product :
            return magento_product.erp_id
        elif odoo_product:
            return odoo_product
        else :
            return False
    
    @api.multi       
    def get_magento_product(self,sku,backend_id):
        magento_product = self.env['magento.product.product'].search([('magento_sku','=',sku),('backend_id','=',backend_id)],limit=1)
        if magento_product:
            return magento_product
        else :
            return False
   
   
    @api.multi
    def import_all_images_products(self,products):
        session = ConnectorSession(self.env.cr, self.env.uid,self.env.context)
        backends = defaultdict(self.browse)
        for product in products:
            backends[product.backend_id] |= product
        for backend,products in backends.items() :
            for product in products:
                env = get_environment(session, 'magento.product.product', product.backend_id.id)
                backend_adapter = env.get_connector_unit(ProductProductAdapter)
                all_images = backend_adapter.get_images(product.magento_id)
                from odoo.addons.odoo_magento2_ept.models.product.product_image import MagentoImageImporter
                image_importer = backend_adapter.unit_for(MagentoImageImporter,'magento.product.image')
                if all_images:
                    for image in all_images:
                        image_importer.run(image.get('id'),product,image.get('file',''),image_data = image)
        return True
    
    @api.multi
    def import_product_images(self):
        context = self._context or {}
        active_ids = context.get('active_ids')
        product_ids = self.search([('id','in',active_ids)])       
        if product_ids:
            self.import_all_images_products(product_ids)
              
class ProductProduct(models.Model):
    _inherit = 'product.product'
    
    @api.multi
    def view_magento_products(self):
        magento_product_ids = self.mapped('magento_bind_ids')
        xmlid=('odoo_magento2_ept','action_magento_stock_picking')
        action = self.env['ir.actions.act_window'].for_xml_id(*xmlid)
        action['domain']= "[('id','in',%s)]" % magento_product_ids.ids
        if not magento_product_ids : 
            return {'type': 'ir.actions.act_window_close'}
        return action

#     @api.one
#     @api.constrains('magento_bind_ids')
#     def _check_magento_product_exist(self):
#         #This constaint is for product -----------------------------------------------------will bind with only one magento product
#         if len(self.magento_bind_ids) > 1 :
#             raise ValidationError(_('Product already have Magento product.'))
            
    magento_bind_ids = fields.One2many(comodel_name='magento.product.product',inverse_name='erp_id',string='Magento Product',)
       

@magento
class ProductProductAdapter(GenericAdapter):
    _model_name = ['magento.product.product']
    _magento_model = 'catalog_product'
    _admin_path = '/{model}/edit/id/{id}'
    _path = "/V1/products"
    _sku = {}
    _product_data_type = {}
        
    def search(self, filters=None, from_date=None, to_date=None):
        """ Search records according to some criteria
        and returns a list of ids

        :rtype: list
        """
        dt_fmt = MAGENTO_DATETIME_FORMAT
        if filters is None:
            filters = {}
        #Date : 07-02-2017
        #If pagesize and currenpage is parameter are given in filters then search 
        #products with pagesize and currentPage
        page_size = filters.get('pageSize') and filters.pop('pageSize',None) or 0
        currentPage = filters.get('currentPage') and filters.pop('currentPage',None) or 0
        if from_date is not None:
            filters.setdefault('updated_at', {})
            filters['updated_at']['from'] = from_date.strftime(dt_fmt)
        if to_date is not None:
            filters.setdefault('updated_at', {})
            filters['updated_at']['to'] = to_date.strftime(dt_fmt)
        filters = create_search_criteria(filters)
        if page_size and currentPage and filters.get('searchCriteria'):
            filters['searchCriteria'].update({'currentPage':currentPage,'pageSize':page_size})
        qs = Php.http_build_query(filters)
        url = "%s?%s"%(self._path,qs)
        content = req(self.backend_record,url)
        sku = {}
        for record in content.get('items') :
            sku.setdefault(record['id'],record['sku'])
            self._product_data_type[record['id']] = record['type_id']
            #self._product_data_type.append({record['id'] : record['type_id']})
        backend = self.backend_record.id
        if self._sku.get(backend):
            self._sku[backend].update(sku)
        else :
            self._sku[backend] = sku
        return sku.keys()
    
    def _get_sku(self,id):
        id = int(id)
        backend = self.backend_record.id
        magento_product = self.env['magento.product.product'].search([('magento_id','=',id),('backend_id','=',self.backend_record.id)])
        sku = magento_product and magento_product.magento_sku
        if not sku :
            filters = {'entity_id':id}
            self.search(filters)
            sku = self._sku.get(backend) and self._sku[backend].get(id)
#         if not sku :
#             raise RetryableJobError("SKU not found for product id : %s"%(id))
        return sku
    
    def set_magento_attributes(self,record,storeview_id,binding):
        storeview_obj = self.env['magento.storeview'].search([('magento_id','=',storeview_id),('backend_id','=',self.backend_record.id)])
        record = record.get('custom_attributes',{})
        attribute_option = self.env['magento.attribute.option']
        for attribute_code,attribute_value in record.items():
            attr_record = self.env['magento.product.attribute'].search([('backend_id','=',self.backend_record.id),
                                                          ('attribute_code','=',attribute_code)],limit=1)
            search_domain  = []
            search_domain.append(('magento_attribute_id','=',attr_record.id))
            search_domain.append(('magento_product_ids','=',binding.id))
            
            if attr_record.type == 'multiselect':
                continue
            elif attr_record.type == 'select':
                continue
            elif attribute_value == '':
                continue

            new_attribute_option = attribute_option.search(search_domain)
            
            if new_attribute_option:
                new_attribute_option.with_context(lang=storeview_obj.lang_id.code).write({'name':attribute_value})
            
        return
        
    def read(self, id, storeview_id=None, attributes=None):
        """ Returns the information of a record

        :rtype: dict
        """
        """
        arguments = [int(id)]
        if attributes:
            arguments.append(attributes)
        """
        with self.session.change_context({'storeview_id': storeview_id}):
            sku=self._get_sku(id)
            if sku :
                sku = urllib.parse.quote_plus(sku.encode('utf8'))
                if storeview_id :
                    url = self._path+"/%s?store_id=%s"%(sku,storeview_id)
                else:
                    url = self._path+"/%s?store_id=0"%(sku)
                content = req(self.backend_record,url)
                custom_attributes = {}
                for attribute in content['custom_attributes'] :
                    custom_attributes.update({attribute['attribute_code']:attribute['value']})
                    if attribute['attribute_code'] == 'description':
                        content['description'] = attribute['value']
                        continue
                    if attribute['attribute_code'] == 'short_description':
                        content['short_description'] = attribute['value']
                        continue
                    if attribute['attribute_code'] == 'meta_description':
                        content['meta_description'] = attribute['value']
                        continue
                    if attribute['attribute_code'] == 'meta_title':
                        content['meta_title'] = attribute['value']
                        continue
                    if attribute['attribute_code'] == 'meta_keyword':
                        content['meta_keyword'] = attribute['value']
                        continue
                    if attribute['attribute_code'] == 'url_key':
                        content['url_key'] = attribute['value']
                        continue
                content.update({'custom_attributes':custom_attributes})
                binding = self.env['magento.product.product'].get_magento_product(sku,self.backend_record.id)
                if binding and  not attributes:
                    self.set_magento_attributes(content,storeview_id,binding)
                return content
            else :
                raise RetryableJobError("Product read fail for product id : %s"%(id))
            return
      
    def get_images(self, id, storeview_id=None):
        product_data = self.read(id)
        base_media_url = ''
        if product_data['media_gallery_entries'] :
            if storeview_id :
                binder = self.binder_for(model='magento.storeview')
                storeview = binder.to_openerp(storeview_id, browse=True)
                base_media_url = storeview.base_media_url
            else :
                storeviews = self.env['magento.storeview'].search([('backend_id','=',self.backend_record.id)])
                for storeview in storeviews :
                    if storeview.base_media_url :
                        base_media_url = storeview.base_media_url
                        break
            if base_media_url : 
                    media_entries = product_data['media_gallery_entries']
                    for media in media_entries :
                        url = '%scatalog/product%s'%(base_media_url,media['file'])
                        media.setdefault('url',url)
                    return media_entries
        return 
    
    def read_image(self, id, image_name, storeview_id=None):
        return self._call('product_media.info',
                          [int(id), image_name, storeview_id, 'id'])
    
    def create(self,data,binding_record):
        if data.get('type_id') == 'configurable':
            magento_product_product = self.env['magento.product.product'].search([('erp_id','in',binding_record.erp_id.product_variant_ids.ids),'|',('active','=',False),('active','=',True)])
            configurable_product_options = data.get('extension_attributes',{}).get('configurable_product_options',[])
            data['extension_attributes'] = {
                  "configurable_product_options":configurable_product_options,
                  "configurable_product_links": [ product_product.magento_id  for product_product in magento_product_product  if product_product.magento_id]
            }
        data.pop('website_ids')
        url = "%s?store_id=0"%self._path
        product_data = {
                'product' : data
            }
        #url = "/V1/products"
        content = super(ProductProductAdapter,self).create(product_data)
        
        #self.export_translation_to_magento(data,website_ids,binding_record)
        if content.get('id') :
            binding_record.write({'exported_in_magento' : True})
            return content.get('id')
        else :
            raise FailedJobError("Product not created : error \n %s"%content)            
    def write(self, id, data,storeview_id=None):    
        sku = 'sku' in data and data.pop('sku')
        if not sku :
            sku = self._get_sku(id)
        website_ids = data.pop('website_ids')
        sku = urllib.parse.quote_plus(sku.encode('utf8'))
        url = '/all/V1/products/%s'%(sku)
        binding_record = self.env['magento.product.product'].get_magento_product(sku,self.backend_record.id)
        product_data = {
                'product' : data
            }
        res = req(self.backend_record,url,method="PUT",data=product_data)
        data.update({'sku' : sku})
        #self.export_translation_to_magento(data,website_ids,magento_product)
        if res.get('id') :
            binding_record.write({'exported_in_magento' : True})
        return res
            
    def delete(self,sku):
        sku = urllib.parse.quote_plus(sku.encode('utf8'))
        url = self._path+"/%s"%sku
        res = super(ProductProductAdapter,self).delete(sku)
        return res
    
    def website_link(self,sku,website_id):
        sku = urllib.parse.quote_plus(sku)
        data={
              "productWebsiteLink": {
                "sku":sku,
                "website_id": website_id
                                    }
            }    
        url = "%s/%s/websites"%(self._path,sku)
        res = req(self.backend_record,url,method="POST",data=data)
        result = res
    


@magento
class ProductBatchImporter(DelayedBatchImporter):
    """ Import the Magento Products.

    For every product category in the list, a delayed job is created.
    Import from a date
    """
    _model_name = ['magento.product.product','magento.product.template']

    def run(self, filters=None):
        """ Run the synchronization """
        from_date = filters.pop('from_date', None)
        to_date = filters.pop('to_date', None)
        #Date : 07-feb-2017
        #get CurrentPage from filters and pass it to search
        product_import_page_size = self.backend_record.product_import_page_size
        currentPage = filters.pop('currentPage',1)
        filters.update({'pageSize':product_import_page_size,'currentPage':currentPage})
        record_ids = self.backend_adapter.search(filters,
                                                 from_date=from_date,
                                                 to_date=to_date)
        _logger.info('search for magento products %s returned %s',
                     filters, record_ids)
        #import_from_date will update after the batchImporter will complete at here
        #because as before it was update when BatchImport job create so there may be situation that
        #if batch import job will failed then import_from_date is already updated after 
        #job is created so import of records may be missed
        
        #In this there may be situation that if any old failed or done job will requeued and it will 
        #be done then that job's to_date will become import_from_date (next_date) and that will be set
        #set in import_from_date.
        product_record_ids = self.backend_adapter._product_data_type
        import_start_time = to_date or datetime.now()
        next_time = import_start_time - timedelta(seconds=IMPORT_DELTA_BUFFER)
        next_time = fields.Datetime.to_string(next_time)
        self.backend_record.write({'last_product_import_date': next_time})
        for record_id in product_record_ids : 
            if product_record_ids.get(record_id) == 'configurable':
                import_product_record.delay(self.session,'magento.product.template',self.backend_record.id,record_id,is_configurable=True)
            else : 
                import_product_record.delay(self.session,'magento.product.product',self.backend_record.id,record_id,is_configurable=False)
        #Date : 07-feb-2017
        #if len(record_ids) is equal to import_page_size then it is possible to have another records
        #so it is creating another batch for next page
        #if len(record_ids) not equal to import_page_size then it is less than import_page_size
        #so can guess it is last page.
        if len(record_ids) == product_import_page_size :
            currentPage +=1
            import_batch.delay(self.session, self.model._name,
                               self.backend_record.id,
                               filters={'from_date': from_date,
                                        'to_date': import_start_time,
                                        'currentPage':currentPage})


ProductBatchImport = ProductBatchImporter  # deprecated


#Not in use
@magento
class CatalogImageImporter(Importer):
    """ Import images for a record.

    Usually called from importers, in ``_after_import``.
    For instance from the products importer.
    """

    _model_name = ['magento.product.product',
                   ]
 
    def _get_images(self, storeview_id=None):
        return self.backend_adapter.get_images(self.magento_id, storeview_id)

    def _sort_images(self, images):
        """ Returns a list of images sorted by their priority.
        An image with the 'image' type is the the primary one.
        The other images are sorted by their position.

        The returned list is reversed, the items at the end
        of the list have the higher priority.
        """
        if not images:
            return {}
        # place the images where the type is 'image' first then
        # sort them by the reverse priority (last item of the list has
        # the the higher priority)

        def priority(image):
            primary = 'image' in image['types']
            try:
                position = int(image['position'])
            except ValueError:
                pass
            return (primary, -position)
        return sorted(images, key=priority)

    def _get_binary_image(self, image_data):
        url = image_data['url'].encode('utf8')
        try:
            request = urllib2.Request(url)
            binary = urllib2.urlopen(request)
        except urllib2.HTTPError as err:
            if err.code == 404:
                # the image is just missing, we skip it
                return
            else:
                # we don't know why we couldn't download the image
                # so we propagate the error, the import will fail
                # and we have to check why it couldn't be accessed
                raise
        else:
            return binary.read()

    def run(self, magento_id, binding_id):
        self.magento_id = magento_id
        self.set_attribute_record()
        images = self._get_images()
        images = self._sort_images(images)
        binary = None
        while not binary and images:
            binary = self._get_binary_image(images.pop())
        if not binary:
            return
        model = self.model
        binding = model.browse(binding_id)
        binding.write({'image': base64.b64encode(binary)})


@magento
class BundleImporter(Importer):
    """ Can be inherited to change the way the bundle products are
    imported.

    Called at the end of the import of a product.

    Example of action when importing a bundle product:
        - Create a bill of material
        - Import the structure of the bundle in new objects

    By default, the bundle products are not imported: the jobs
    are set as failed, because there is no known way to import them.
    An additional module that implements the import should be installed.

    If you want to create a custom importer for the bundles, you have to
    declare the ConnectorUnit on your backend::

        @magento_custom
        class XBundleImporter(BundleImporter):
            _model_name = 'magento.product.product'

            # implement import_bundle

    If you want to create a generic module that import bundles, you have
    to replace the current ConnectorUnit::

        @magento(replacing=BundleImporter)
        class XBundleImporter(BundleImporter):
            _model_name = 'magento.product.product'

            # implement import_bundle

    And to add the bundle type in the supported product types::

        class magento_product_product(orm.Model):
            _inherit = 'magento.product.product'

            def product_type_get(self, cr, uid, context=None):
                types = super(magento_product_product, self).product_type_get(
                    cr, uid, context=context)
                if 'bundle' not in [item[0] for item in types]:
                    types.append(('bundle', 'Bundle'))
                return types

    """
    _model_name = ['magento.product.product']

    def run(self, binding_id, magento_record):
        """ Import the bundle information about a product.

        :param magento_record: product information from Magento
        """


@magento
class ProductImportMapper(ImportMapper):
    _model_name = ['magento.product.product']
    # TODO :     categ, special_price => minimal_price
    direct = [('name', 'name'),
              ('name','magento_product_name'),
              ('weight', 'weight'),
              ('sku', 'default_code'),
              ('sku','magento_sku'),
              ('type_id', 'product_type'),
              ('description', 'description'),
              ('short_description', 'description_sale'),
              ('meta_description','meta_description'),
              ('meta_title','meta_title'),
              ('meta_keyword','meta_keyword'),
              ('url_key','url_key')
              ]

    @mapping
    def standard_price(self,record):
        if record['custom_attributes'] :
            return {'standard_price':record['custom_attributes'].get('cost')}
        return 
        
    @mapping
    def magento_id(self, record):
        return {'magento_id': record['id']}
    
#     @mapping
#     def magento_sku(self,record):
#         return {'magento_sku' : record['sku']}
    
    @mapping
    def website_ids(self, record):
        website_ids = []
        binder = self.binder_for('magento.website')
        if not record['extension_attributes'].get('website_ids',[]):
            return
        for mag_website_id in record['extension_attributes'].get('website_ids',[]):
            website_id = binder.to_openerp(mag_website_id)
            website_ids.append(website_id)
        return {'website_ids': [(6,0,website_ids)]}
        
    @mapping
    def is_active(self, record):
        mapper = self.unit_for(IsActiveProductImportMapper)
        return mapper.map_record(record).values(**self.options)

#     @mapping
#     def price(self, record):
#         """ The price is imported at the creation of
#         the product, then it is only modified and exported
#         from odoo """
#         
#         return {'list_price': record.get('price', 0.0),'lst_price': record.get('price', 0.0)}

    @mapping
    def type(self, record):
        if record['type_id'] in ['simple','configurable','virtual']:
            return {'type': 'product','product_type':record['type_id']} # For remove type_id warning
        if record['type_id'] == 'giftvoucher' :
            return {'type':'service','product_type':record['type_id']}
        return

    @mapping
    def categories(self, record):
        mag_categories = record.get('category_ids',[]) 
        binder = self.binder_for('magento.product.category')

        category_ids = []
        main_categ_id = None

        for mag_category_id in mag_categories:
            cat_id = self.env['magento.product.category'].search([('magento_id','=',mag_category_id),('backend_id','=',self.backend_record.id)])
            if not cat_id :
                raise MappingError("The product category with "
                                   "magento id %s is not imported." %
                                   mag_category_id)

            category_ids.append(cat_id.id)

        if not category_ids : 
            default_categ = self.backend_record and self.backend_record.default_category_id
            if default_categ:
                main_categ_id = default_categ.id
        if main_categ_id:
            category_ids.append(main_categ_id)
        result = {'category_ids': [(6, 0, category_ids if category_ids else [] )]}
        return result

    @mapping
    def backend_id(self, record):
        return {'backend_id': self.backend_record.id}

    @mapping
    def bundle_mapping(self, record):
        if record['type_id'] == 'bundle':
            bundle_mapper = self.unit_for(BundleProductImportMapper)
            return bundle_mapper.map_record(record).values(**self.options)

    @mapping
    def attribute_set(self,record):
        result = {}
        binder = self.binder_for('magento.attribute.set')
        set_id = self.env['magento.attribute.set'].search([('magento_id','=',record.get('attribute_set_id')),('backend_id','=',self.backend_record.id)])
        if set_id :
            result.update({'attribute_set_id':set_id.id})
        return result
    
    @mapping
    def created_date(self,record):
        created_date = record.get('created_at')
        created_at = datetime.strptime(created_date, "%Y-%m-%d %H:%M:%S")
        return {'created_at' : created_at}
    
    @mapping
    def updated_date(self,record):
        updated_date = record.get('created_at')
        updated_at = datetime.strptime(updated_date, "%Y-%m-%d %H:%M:%S")
        return {'updated_at' : updated_at}
    
    
@magento
class ProductImporter(MagentoImporter):
    _model_name = ['magento.product.product']

    _base_mapper = ProductImportMapper

    allowed_types = []
    
    #At this moment not being used
    def _import_bundle_dependencies(self):
        """ Import the dependencies for a Bundle """
        bundle = self.magento_record.get('_bundle_data',False)
        if bundle:
            for option in bundle.get('options',[]):
                for selection in option.get('selections',[]):
                    self._import_dependency(selection['product_id'],
                                            'magento.product.product')
    
    def _import_dependencies(self):
        """ Import the dependencies for the record"""
        record = self.magento_record
        #import related attributes 
        backend=self.backend_record
        if not backend.is_only_import_export_basic_info:
            attributes = record['custom_attributes']
            for mag_attribute_code in list(attributes) :
                attribute = self.env['magento.product.attribute'].search([('backend_id','=',self.backend_record.id),
                                                              ('attribute_code','=',str(mag_attribute_code))])
                if not attribute :
                    self._import_dependency(mag_attribute_code,'magento.product.attribute')
        record.update({'category_ids':record.get('custom_attributes').pop('category_ids')})
        #import attribute set
        if not backend.is_only_import_export_basic_info: 
            self._import_dependency(record.get('attribute_set_id'),'magento.attribute.set')       
        # import related categories
        for mag_category_id in record['category_ids']:
            self._import_dependency(mag_category_id,
                                    'magento.product.category')
        if record['type_id'] == 'bundle':
            self._import_bundle_dependencies()
    
    def get_product(self,sku,backend_id):
        magento_product = self.env['magento.product.product'].get_magento_product(sku,self.backend_record.id)
        if not magento_product:
            product = self.env['product.product'].search([('default_code','=',sku)])
            if not product:                
                return False
        else:
            return magento_product.product_id.id
    
    # Added for Product create only and only if we found it in ERP other wise Product is not import
    def _must_skip(self):
        auto_create_product = self.backend_record.auto_create_product
        sku = self.magento_record.get('sku',False)
        if not auto_create_product:
            if sku:
                product = self.env['magento.product.product'].get_odoo_product(sku,self.backend_record.id)
                if not product :
                    raise NothingToDoJob('Product (%s) is Not found in ERP'%sku)
                else : 
                    return False
        else :
            return False
                    
    def _get_binding(self):
        result = super(ProductImporter,self)._get_binding()
        if not result:
            sku = self.magento_record.get('sku',False)
            if sku:
                product = self.env['magento.product.product'].get_magento_product(sku,self.backend_record.id)
                if product:
                    result = product
        return result
    
    def _validate_product_type(self, data):
        """ Check if the product type is in the selection (so we can
        prevent the `except_orm` and display a better error message).
        """
        product_type = data.get('product_type') or data.get('type_id')
        
        product_model = self.env['magento.product.product']
        types = product_model.product_type_get()
        allowed_types = self.allowed_types or []
        types = types + allowed_types
        available_types = [typ[0] for typ in types]
        available_types = available_types + self.session.context.get('allowed_type',[])
        if product_type not in available_types:
            if product_type in ['virtual']:
                #return _('Virtual Product can only be imported with configurable product. This product will be imported with parent product')
                raise NothingToDoJob('Virtual Product can only be imported with configurable product. This product will be imported with parent product')
            raise FailedJobError("The product type '%s' is not "
                                   "yet supported in the connector." %
                                   product_type)

    def _validate_data(self, data):
        """ Check if the values to import are correct

        Pro-actively check before the ``_create`` or
        ``_update`` if some fields are missing or invalid

        Raise `InvalidDataError`
        """
        self._validate_product_type(data)
    
    def _get_product_vals(self,data):
        sku = data.get('magento_sku')
        products = self.env['product.product'].search([('default_code','=',sku)],limit=1)
        vals = {}
        for product in products :
            vals.update({'erp_id':product.id})
            if self.session.context.get('product_tmpl_id'):
                product_tmpl = self.session.context.get('product_tmpl_id')
                product.write({'product_tmpl_id' : product_tmpl.id})  
                vals.update({'product_tmpl_id' :  product_tmpl.id})
            for magento_product in product.magento_bind_ids:
                if magento_product.backend_id.id != data.get('backend_id') :
                    vals = {
                            'magento_id':data.get('magento_id'),
                            'backend_id':data.get('backend_id'),
                            'created_at':data.get('created_at'),
                            'updated_at':data.get('updated_at'),
                            'product_type':data.get('type_id'),
                            'erp_id':product.id,
                            'attribute_set_id':data.get('attribute_set_id'),
                            'magento_sku' : sku,
                            }
                    break
        if vals :
            data.update(vals)
        return data

    
    def set_attribute_record(self,record,binding):
        
        is_only_import_export_basic_info =self.backend_record.is_only_import_export_basic_info
        if not is_only_import_export_basic_info:
            attribute_option = self.env['magento.attribute.option']
            for attribute_code,attribute_value in record.items():
                attr_value = attribute_value
                attr_record = self.env['magento.product.attribute'].search([('backend_id','=',self.backend_record.id),
                                                              ('attribute_code','=',attribute_code)],limit=1)
                search_domain  = []
                search_domain.append(('magento_attribute_id','=',attr_record.id))
                search_domain.append(('magento_product_ids','=',binding.id))
                
                if attr_record.type == 'multiselect' and not attribute_value :
                    continue
                elif attr_record.type == 'select' and attribute_value == '0':
                    continue
                elif attribute_value == '':
                    continue
    
                product = binding.erp_id
                if product:
                    create_variants = attr_record.type in ['select']
                    if create_variants:
                        search_domain.append(('magento_id','=',attribute_value))
                    elif attr_record.type == 'multiselect':
                        if isinstance(attribute_value,str) :
                            attr_value = attribute_value.split(',')
                            search_domain.append(('magento_id','in',attr_value))
                    else:
                        search_domain.append(('name','=',attribute_value))
                        
                    new_attribute_option = attribute_option.search(search_domain)
                    if attr_record.type == 'multiselect':
                        magento_attribute_option_domain = [('magento_attribute_id','=',attr_record.id)]
                        if isinstance(attribute_value,str) :
                            attr_value = attribute_value.split(',')
                        magento_attribute_option_domain.append(('magento_id','in',attr_value))
                        magento_options = self.env['magento.attribute.option'].search(magento_attribute_option_domain)
                        for option in magento_options:
                            option.write({'magento_product_ids':[(4,binding.id,0)]})
                            
                    elif attr_record.type == 'select':
                        attribute_option = attribute_option.search([('magento_attribute_id','=',attr_record.id),('magento_id','=',attribute_value)])
                        attribute_option.write({'magento_product_ids':[(4,binding.id,0)]})
                    else:
                        if not new_attribute_option:
                            new_attribute_option.create({'magento_attribute_id':attr_record.id,
                                                     'attribute_id':attr_record.erp_id.id,
                                                     'create_variants':create_variants,
                                                     'magento_id':binding.magento_id,
                                                     'magento_product_ids':[(6,0,[binding.id])],
                                                     'backend_id':self.backend_record.id,
                                                     'name':attribute_value
                                                     })
                        else:
                            new_attribute_option.write({'magento_attribute_id':attr_record.id,
                                                     'attribute_id':attr_record.erp_id.id,
                                                     'create_variants':create_variants,
                                                     'magento_id':binding.magento_id,
                                                     'magento_product_ids':[(6,0,[binding.id])],
                                                     'backend_id':self.backend_record.id,
                                                     'name':attribute_value
                                                     })
                        
            return
    
    def _create(self, data):
        """ Create the odoo record """
        # special check on data before import
        self._validate_data(data)
        data = self._get_product_vals(data)
        if self.session.context.get('product_tmpl_id'):
            product_tmpl = self.session.context.get('product_tmpl_id')
            data.update({'product_tmpl_id' : product_tmpl.id})
        binding = self.env['magento.product.product'].create(data)
        if self.session.context.get('product_tmpl_id'):
            product_tmpl = self.session.context.get('product_tmpl_id')
            binding.erp_id.write({'product_tmpl_id' : product_tmpl.id})
        if binding:
            binding.write({'exported_in_magento' : True})
        _logger.debug('%d created from magento %s', binding, self.magento_id)
        return binding

    
    def import_product_images(self,binding,magento_id):
        from odoo.addons.odoo_magento2_ept.models.product.product_image import MagentoImageImporter
        image_importer = self.unit_for(MagentoImageImporter,'magento.product.image')
        all_images = self.backend_adapter.get_images(magento_id)
        if all_images:
            for one_image in all_images:
                image_importer.run(one_image.get('id'),binding,one_image.get('file',''),image_data = one_image)
                
    
    def create_pricelist_item(self,website,price,binding):
        pricelist_item_obj = self.env['product.pricelist.item']
        pricelist_item = pricelist_item_obj.search([('pricelist_id','=',website.pricelist_id.id),('product_id','=',binding.erp_id.id)])
        if pricelist_item:
            pricelist_item.write({
                    'fixed_price' : price
                })
        else : 
            pricelist_item_obj.create({
                                    'pricelist_id' : website.pricelist_id.id,
                                    'applied_on' : '0_product_variant',
                                    'product_id' : binding.erp_id.id,
                                    'compute_price'  : 'fixed',
                                    'min_quantity' : 1,
                                    'fixed_price' : price
                                    })
            
    def _after_import(self, binding):
        """ Hook called at the end of the import """
        record = self.magento_record
        if not  self.backend_record.is_only_import_export_basic_info:
            self.set_attribute_record(record['custom_attributes'],binding)
        backend = self.backend_record
        if binding.backend_id.catalog_price_scope == 'global':
            price = record.get('price') or 0.0
            self.create_pricelist_item(binding.backend_id,price,binding)       
        traslated_record = False
        if backend.allow_import_traslation:
            with self.session.change_context({'translation': True}):
                translation_importer = self.unit_for(TranslationImporter)
                traslated_record = translation_importer.run(self.magento_id, binding.id,
                                         mapper_class=ProductImportMapper)
        price_importer = self.unit_for(ProductPriceImporter)
        traslated_record = price_importer.run(self.magento_id, binding.id,present_record=traslated_record)
        website_ids = record['extension_attributes'].get('website_ids',[])
        if traslated_record and binding.backend_id.catalog_price_scope == 'website':
            for storeview,lang_record in traslated_record.items():
                website_id = storeview.website_id
                price = lang_record.get('price',0.0)
                if website_id and website_id.magento_id in website_ids:
                    self.create_pricelist_item(website_id,price,binding)        
        self.session.change_context({'translation': False})
        if backend.allow_import_image_of_products : 
            self.import_product_images(binding,self.magento_id)
           
                
ProductImport = ProductImporter  # deprecated


@magento
class IsActiveProductImportMapper(ImportMapper):
    _model_name = ['magento.product.product','magento.product.template']

    @mapping
    def is_active(self, record):
        """Check if the product is active in Magento
        and set active flag in odoo
        status == 1 in Magento means active"""
        return {'active': (record.get('status') == 1)}

@magento
class BundleProductImportMapper(ImportMapper):
    _model_name = ['magento.product.product']


@magento
class ProductInventoryExporter(Exporter):
    _model_name = ['magento.product.product']

    def run(self, backend, data):
        """ Export the product inventory to Magento """
        url = "/V1/product/updatestock"
        try :
            res = req(backend,url,method='PUT',data=data)
        except Exception as e :
            raise FailedJobError(e)
        msg = ""
        if res:
            for message in res : 
                if message.get('code') != '200':
                    msg = msg + message.get("message") +"\n"
        if msg == "" :
            res = "Stock is succesfully exported of All products"
        else : 
            res = msg
        return res

ProductInventoryExport = ProductInventoryExporter  # deprecated

@magento
class ProductProductDeleter(MagentoDeleter):
    """ product deleter for Magento """
    _model_name = ['magento.product.product']

           
@magento
class ProductExporter(MagentoExporter):
    _model_name = ['magento.product.product']
    
    def _export_dependencies(self):
        is_only_import_export_basic_info= self.backend_record.is_only_import_export_basic_info
        if not is_only_import_export_basic_info:
            attribute_set = self.binding_record.attribute_set_id
            vals = {
                   'attribute_set_name':attribute_set.attribute_set_name,
                    }
            self._export_dependency(attribute_set,'magento.attribute.set',binding_extra_vals=vals)
            for group in attribute_set.attribute_group_ids :
                for attribute in group.attribute_ids :
                    self._export_dependency(attribute.attribute_id,'magento.product.attribute')
        product_categs = self.binding_record.category_ids
        for product_categ in product_categs :
            self._export_dependency(product_categ,'magento.product.category')
            #For export create variant type attribute if it is not exported
        if not is_only_import_export_basic_info:    
            for attribute_value in self.binding_record.attribute_value_ids:
                group_adapter = self.unit_for(AttributeGroupAdapter,'magento.attribute.group')
                magento_attribute_obj = self.env['magento.product.attribute']
                magento_group_id = self.env['magento.attribute.group'].search([('attribute_set_id','=',attribute_set.id),('backend_id','=',self.backend_record.id)])[0]
                magento_attribute = self.env['magento.product.attribute'].search([('erp_id','=',attribute_value.attribute_id.id),('backend_id','=',self.backend_record.id)])
                if not magento_attribute:
                    magento_attribute = magento_attribute_obj.create({
                                                                    'erp_id' : attribute_value.attribute_id.id,
                                                                    'attribute_code' : attribute_value.attribute_id.name.lower(),
                                                                    'frontend_label' : attribute_value.attribute_id.name.lower(),
                                                                    'backend_id' : self.binding_record.backend_id.id,
                                                                    'type' : 'select', 
                                                                    })
                    magento_group_id.write({'magento_attribute_ids' : [(4,magento_attribute.id)]})
                    self._export_dependency(magento_attribute,'magento.product.attribute')
                    for attribute_option in attribute_value.attribute_id.option_ids:
                        magento_attribute_option_obj = self.env['magento.attribute.option']
                        magento_attribute_option = self.env['magento.attribute.option'].search([('erp_id','=',attribute_option.id),('backend_id','=',self.backend_record.id)])
                        if not magento_attribute_option:
                            magento_attribute_option = magento_attribute_option_obj.create({
                                                                    'erp_id' : attribute_option.id,
                                                                    'magento_attribute_id' : magento_attribute.id,
                                                                    'backend_id' : magento_attribute.backend_id.id
                                                                })
                        
                            self._export_dependency(magento_attribute_option,'magento.attribute.option')
                    group_adapter.addAttribute(magento_attribute.magento_id,attribute_set.magento_id,magento_group_id.magento_id)
                else :
                    #for export new attribute option of create variant type attribute
                    for attribute_option in attribute_value.attribute_id.option_ids:
                        magento_attribute_option_obj = self.env['magento.attribute.option']
                        magento_attribute_option = self.env['magento.attribute.option'].search([('erp_id','=',attribute_option.id),('backend_id','=',self.backend_record.id)])
                        if not magento_attribute_option:
                            magento_attribute_option = magento_attribute_option_obj.create({
                                                                    'erp_id' : attribute_option.id,
                                                                    'magento_attribute_id' : magento_attribute.id,
                                                                    'backend_id' : magento_attribute.backend_id.id
                                                                })
                        
                            self._export_dependency(magento_attribute_option,'magento.attribute.option')
                    group_adapter.addAttribute(magento_attribute.magento_id,attribute_set.magento_id,magento_group_id.magento_id)
        
    
    def _create(self, data):
        """ Create the Magento record """
        if  not data.get('sku',False):
            raise FailedJobError("SKU not found.")
        filters = {'sku':data.get('sku','')}
        magento_ids = list(self.backend_adapter.search(filters=filters))
        if magento_ids:
            res = self.backend_adapter.write(magento_ids[0],data)
            return magento_ids[0]
        else:
            res = self.backend_adapter.create(data,self.binding_record)
        return res
    
    def _update(self, data):
        assert self.magento_id
        self._validate_update_data(data)
        self.backend_adapter.write(self.magento_id, data,self.binding_record)
    
    def create_blank_template(self,product):
        product_tmpl = product.product_tmpl_id.copy()
        return product_tmpl
    
    def load_traslation(self,field_name,binding_record,lang=None):
        if field_name != 'custom_attributes':
            return binding_record.read([field_name])[0].get(field_name,False)
        else:
            product_exporter = self.unit_for(ProductProductExportMapper)
            return product_exporter.get_product_attribute_option(binding_record,lang).get('custom_attributes')
            
    def export_translation_to_magento(self,website_ids,binding_record):
        from odoo.addons.odoo_magento2_ept.models.product.product_template import ProductTemplateExportMapper
        session = ConnectorSession(self.env.cr, self.env.uid,context=self.env.context)
        sku = binding_record.magento_sku
        sku = urllib.parse.quote_plus(sku.encode('utf8'))
        fields = binding_record.fields_get()
        env = get_environment(session, binding_record._name, binding_record.backend_id.id)
        if binding_record._name == 'magento.product.template' :
            mapper = env.get_connector_unit(ProductTemplateExportMapper)
            data = mapper.map_record(self._get_openerp_data()).values()
        else :
            data = self.mapper.map_record(self._get_openerp_data()).values()
        translatable_fields = [field for field, attrs in list(fields.items())
                               if attrs.get('translate')]
        custom_attributes = []
        translatable_fields = translatable_fields + ['custom_attributes']
        storeviews = self.env['magento.storeview'].search([('website_id','in',website_ids.ids)])
        for storeview in storeviews:
            if storeview.magento_id == '0':
                continue
            lang = storeview and storeview.lang_id and storeview.lang_id.code or False
            if not lang:
                continue
            translated_value = {}
            flag = True
            for field in list(set(translatable_fields) & set(data.keys())):
                flag = False
                translated_value[field] = self.load_traslation(field,binding_record,lang)                    
            pricelist = storeview.website_id.pricelist_id
            if data.get('price') and binding_record.backend_id.catalog_price_scope == 'website':
                price = pricelist and pricelist.with_context(uom=binding_record.erp_id.uom_id.id).price_get(binding_record.erp_id.id,1.0,partner=False)[pricelist.id] or 0.0
                translated_value.update({'price' : price })
            translated_value.update({'name' : binding_record.magento_product_name})
            export_data = {
                'product': translated_value
                }
            export_url = '/%s/V1/products/%s'%(storeview.code,sku)
            res = req(self.backend_record,export_url,method="PUT",data=export_data)
            if flag:
                break
    
    def update_price_website_wise(self,website_ids,binding_record):
        storeviews = self.env['magento.storeview'].search([('website_id','in',website_ids.ids)])
        if binding_record.product_type == 'simple' and binding_record.backend_id.catalog_price_scope == 'website':
            for storeview in storeviews:
                pricelist = storeview.website_id.pricelist_id
                sku = binding_record.magento_sku
                price = pricelist and pricelist.with_context(uom=binding_record.erp_id.uom_id.id).price_get(binding_record.erp_id.id,1.0,partner=False)[pricelist.id] or 0.0
                data = {
                    'name' : binding_record.magento_product_name,
                    'price' : price
                    }
                product_data = {'product' : data}
                url = '/%s/V1/products/%s'%(storeview.code,sku)
                res = req(self.backend_record,url,method="PUT",data=product_data)
    
    def _after_export(self):
        session = ConnectorSession(self.env.cr, self.env.uid,context=self.env.context)
        websites = self.binding_record.website_ids
        sku = self.binding_record and self.binding_record.magento_sku
        if websites :
            for website in websites :
                if website.backend_id.id == self.backend_record.id :
                    self.backend_adapter.website_link(sku,website.magento_id)
            self.update_price_website_wise(websites,self.binding_record)
        for image in self.binding_record.magento_product_image_ids:
            on_export_magento_product_image.fire(session, 'magento.product.image', image.id)
        if self.binding_record.backend_id.allow_import_traslation :
            self.export_translation_to_magento(websites,self.binding_record)
          
            
@magento
class ProductProductExportMapper(ExportMapper):
    _model_name = ['magento.product.product']

    #TODO FIXME
    direct = [('magento_product_name', 'name'),
              ('magento_sku', 'sku'),
              ]
    @mapping
    def sku(self, record):
        sku = record.magento_sku
        if not sku:
            raise MappingError("The product attribute Magento SKU cannot be empty.")
        return {'sku': sku}
    
    @changed_by('attribute_set_id')    
    @mapping
    def attribute_set(self, record):
        return {'attribute_set_id': record.attribute_set_id.magento_id}
    
    @mapping
    def price(self,record):
        pricelist = record.backend_id.pricelist_id
        price = 0.0
        if record.product_type == 'simple':
            price = pricelist and pricelist.with_context(uom=record.erp_id.uom_id.id).price_get(record.erp_id.id,1.0,partner=False)[pricelist.id] or 0.0
        return {'price' : price}
        
    @mapping
    def get_product_attribute_option(self, record,lang=None):
        result = {}
        custom_attributes = []
        skip_multiselect = []
        magento_attribute_option = self.env['magento.attribute.option']
        for attribute_option in record.attribute_option_ids:
            if attribute_option.magento_attribute_id.type == 'select':
                custom_attributes.append({'attribute_code':attribute_option.magento_attribute_id.attribute_code,
                                          'value':attribute_option.magento_id})
            elif attribute_option.magento_attribute_id.type == 'multiselect':
                if attribute_option.magento_attribute_id not in skip_multiselect:
                    value = []
                    for option in attribute_option.search([('magento_attribute_id','=',attribute_option.magento_attribute_id.id),('id','in',record.attribute_option_ids.ids)]):
                        value.append(option.magento_id)
                    custom_attributes.append({'attribute_code':attribute_option.magento_attribute_id.attribute_code,
                                              'value':value})
                    skip_multiselect.append(attribute_option.magento_attribute_id)
            else:
                custom_attributes.append({'attribute_code':attribute_option.magento_attribute_id.attribute_code,
                                          'value':attribute_option.name})
        category_id=[]
        if lang:
            record = record.with_context(lang=lang)
        if record.category_ids:
            for categ_id in record.category_ids:
                category_id.append(categ_id.magento_id)
            temp_dict = {
                "attribute_code" : 'category_ids',
                "value" : category_id
                }
            custom_attributes.append(temp_dict)
        if record.description : 
            temp_dict = {
                    "attribute_code" : "description",
                    "value" : record.description
                }
            custom_attributes.append(temp_dict)
        if record.description_sale :
            temp_dict = {
                    "attribute_code" : "short_description",
                    "value" : record.description_sale
                }
            custom_attributes.append(temp_dict)
        if record.meta_description :
            temp_dict = {
                    "attribute_code" : "meta_description",
                    "value" : record.meta_description
                }
            custom_attributes.append(temp_dict)
        if record.meta_title :
            temp_dict = {
                    "attribute_code" : "meta_title",
                    "value" : record.meta_title
                }
            custom_attributes.append(temp_dict)
        if record.meta_keyword :
            temp_dict = {
                    "attribute_code" : "meta_keyword",
                    "value" : record.meta_keyword
                }
            custom_attributes.append(temp_dict)
        #attribute values which can create Variants       
        if record.product_type != 'configurable' :       
            for attribute_value in record.attribute_value_ids:
                attr_option = magento_attribute_option.search([('erp_id','=',attribute_value.id),('backend_id','=',self.backend_record.id)])
                magento_attribute_code = attr_option.magento_attribute_id.attribute_code
                value = attr_option.magento_id
                if magento_attribute_code and value:
                    temp_dict = {
                        "attribute_code" : magento_attribute_code,
                        "value":value
                    }
                    custom_attributes.append(temp_dict)
        result.update({'custom_attributes':custom_attributes})
        return result
    
    
    @mapping
    def website_ids(self,record):
        website_ids = []
        websites = record.website_ids
        for website in websites:
            website_ids.append(website.id)
        return {'website_ids' : website_ids}
    
    def finalize(self, map_record, values):
        # Here Needs to map all fields which will not take data from attribute struture. like mapped sku with default_code etc..
        #fields = self.options.get('fields',[])
        for_create = self.options.get('for_create',False)
        if for_create :
            record=map_record.source
            pricelist = record.backend_id.pricelist_id
            values['name']= values.get('name') or  record.name
            values['sku'] = values.get('sku') or  record.magento_sku
            values['weight'] = values.get('weight',0.0) or  record.weight or 0.0
            values.update({                
                    'price': pricelist and pricelist.with_context(uom=record.erp_id.uom_id.id).price_get(record.erp_id.id,1.0,partner=False)[pricelist.id] or 0.0,
                    'type_id': record.product_type,                
                    })
        return values


@job(default_channel='root.magento')
@related_action(action=unwrap_binding)
def export_product_inventory(session, model_name, backend,data, fields=None):
    """ Export the inventory configuration """
    backend = session.env['magento.backend'].browse(backend.id)
    env = get_environment(session, model_name, backend.id)
    inventory_exporter = env.get_connector_unit(ProductInventoryExporter)
    return inventory_exporter.run(backend,data)

@on_export_product_to_magento
def on_export_product_to_magento(session, model_name, record_id, fields=None):
    """ Export the inventory configuration and quantity of a product. """
    export_product_to_magento.delay(session, model_name,
                                       record_id, fields=None,
                                       priority=20)
    
@on_export_magento_product_image
def on_export_product_image(session, model_name, record_id, fields=None):
    """Export Product Image to Magento """
    export_record.delay(session, model_name,
                                       record_id, fields=None,
                                       priority=20)

@job(default_channel='root.magento')
@related_action(action=unwrap_binding)
def export_product_to_magento(session, model_name, record_id, fields=None):
    """ Export a Product to Magento. """
    from odoo.addons.odoo_magento2_ept.models.product.product_template import ProductTemplateExporter
    product = session.env[model_name].browse(record_id)
    backend_id = product.backend_id.id
    env = get_environment(session, model_name, backend_id)
    if model_name == 'magento.product.template' :
        product_exporter = env.get_connector_unit(ProductTemplateExporter)
    else :
        product_exporter = env.get_connector_unit(ProductExporter)
    return product_exporter.run(record_id, fields)


@job(default_channel='root.magento')
@related_action(action=unwrap_binding)
def update_product_to_magento(session, model_name, record_id, fields=None):
    """ Update a Product to Magento. """
    from odoo.addons.odoo_magento2_ept.models.product.product_template import ProductTemplateExporter
    product = session.env[model_name].browse(record_id)
    backend_id = product.backend_id.id
    env = get_environment(session, model_name, backend_id)
    if model_name == 'magento.product.template' :
        product_exporter = env.get_connector_unit(ProductTemplateExporter)
    else :
        product_exporter = env.get_connector_unit(ProductExporter)
    return product_exporter.run(record_id, fields)



@job(default_channel='root.magento')
@related_action(action=unwrap_binding)
def import_product_record(session, model_name, backend_id, magento_id,is_configurable=False ,force=None):
    """ Import a record from Magento """
    from odoo.addons.odoo_magento2_ept.models.product.product_template import ProductTemplateImporter
    env = get_environment(session, model_name, backend_id)
    if is_configurable :
        importer = env.get_connector_unit(ProductTemplateImporter)
    else :
        importer = env.get_connector_unit(MagentoImporter)
    importer.run(magento_id, force=force)
