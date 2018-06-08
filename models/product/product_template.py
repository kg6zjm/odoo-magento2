from odoo import models,fields,api
from odoo.addons.odoo_magento2_ept.models.product.product import (ProductProductAdapter,ProductImportMapper,ProductImporter,ProductExporter,ProductProductExportMapper,update_product_to_magento)
from odoo.addons.odoo_magento2_ept.models.unit.import_synchronizer import (DelayedBatchImporter,MagentoImporter,TranslationImporter,ProductPriceImporter,)
from odoo.addons.odoo_magento2_ept.models.unit.mapper import (mapping,ImportMapper,ExportMapper,changed_by)
from odoo.addons.odoo_magento2_ept.models.unit.backend_adapter import (GenericAdapter,MAGENTO_DATETIME_FORMAT)
from odoo.addons.odoo_magento2_ept.models.backend.backend import magento
import urllib.parse
from odoo.addons.odoo_magento2_ept.models.api_request import req
from odoo.addons.odoo_magento2_ept.models.backend.exception import (MappingError,InvalidDataError,IDMissingInBackend,FailedJobError,RetryableJobError,OrderImportRuleRetry,NothingToDoJob)
from lxml import etree
from datetime import datetime, timedelta
from collections import defaultdict
from odoo.addons.odoo_magento2_ept.models.backend.session import ConnectorSession
from odoo.addons.odoo_magento2_ept.models.backend.connector import get_environment
class magento_product_template(models.Model):
    _name = 'magento.product.template'
    _inherit = 'magento.binding'
    _inherits = {'product.template': 'erp_id'}
    _description = 'Magento Product Template'
    
    @api.multi
    def _attr_grp_ids(self):
        for obj in self:
            obj.attribute_group_ids = obj.attribute_set_id.attribute_group_ids.ids
    
    magento_product_name = fields.Char("Name",translate=True)
    erp_id = fields.Many2one('product.template',string="Product",ondelete='restrict')
    magento_product_ids = fields.One2many('magento.product.product','magento_tmpl_id',string="Products")
    website_ids = fields.Many2many("magento.website",string="Websites")
    created_at = fields.Datetime("Created Date")
    updated_at = fields.Datetime("Updated Date")
    magento_sku = fields.Char("Magento SKU")
    exported_in_magento = fields.Boolean('Exported in Magento')
    category_ids = fields.Many2many("magento.product.category",string="Category")
    attribute_set_id=fields.Many2one(comodel_name='magento.attribute.set',string='Attribute Set')
    attribute_group_ids=fields.Many2many('magento.attribute.group',compute="_attr_grp_ids", string='Groups')
    attribute_option_ids = fields.Many2many('magento.attribute.option',string="Magento Attributes")
    product_type = fields.Selection(selection=[('simple', 'Simple Product'),('configurable', 'Configurable Product'),('giftvoucher','Gift Card'),('virtual', 'Virtual Product')],
                                    string='Product Type',default='configurable')
    magento_product_image_ids = fields.One2many('magento.product.image','magento_tmpl_id',string='Images')
    description = fields.Text("Description",translate=True)
    description_sale = fields.Text('Sale Description', translate=True,)
    meta_description = fields.Text('Meta Descritption',translate=True)
    meta_title = fields.Text("Meta Title",translate=True)
    meta_keyword = fields.Text("Meta keyword",translate=True)
    url_key = fields.Char("URL key",translate=True)
    
    @api.model
    def create(self,vals):
        res = super(magento_product_template,self).create(vals)
#         if vals.get('attribute_set_id') : 
#             self.set_default_value_for_attribute(res.id, vals.get('attribute_set_id'))
        return res
    
    @api.multi
    def set_default_value_for_attribute(self,product_template_id,attribute_set):
        magento_attribute_option = self.env['magento.attribute.option']
        product = self.browse(product_template_id)
        attribute_set = self.env['magento.attribute.set'].browse(attribute_set)
        for attribute_group in attribute_set.attribute_group_ids:
            for attribute in attribute_group.magento_attribute_ids:
                search_domain  = []
                search_domain.append(('magento_attribute_id','=',attribute.id))
                search_domain.append(('magento_template_ids','=',product.id))
                attribute_option = self.env['magento.attribute.option'].search([('magento_template_ids','=',product.id),('magento_attribute_id','=',attribute.id),('backend_id','=',product.backend_id.id)])
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
                            option.write({'magento_template_ids':[(4,product.id,0)]})
                            
                    elif attribute.type == 'select':
                        attribute_option = magento_attribute_option.search([('magento_attribute_id','=',attribute.id),('magento_id','=',attribute.default_value)])
                        attribute_option.write({'magento_template_ids':[(4,product.id,0)]})
                    else:
                        if not new_attribute_option:
                            new_attribute_option.create({'magento_attribute_id':attribute.id,
                                                     'attribute_id':attribute.erp_id.id,
                                                     'create_variants':create_variants,
                                                     'magento_id':product.magento_id,
                                                     'magento_template_ids':[(6,0,[product.id])],
                                                     'backend_id':product.backend_id.id,
                                                     'name':attribute.default_value
                                                     })
                        else:
                            new_attribute_option.write({'magento_attribute_id':attribute.id,
                                                     'attribute_id':attribute.erp_id.id,
                                                     'create_variants':create_variants,
                                                     'magento_id':product.magento_id,
                                                     'magento_template_ids':[(6,0,[product.id])],
                                                     'backend_id':product.backend_id.id,
                                                     'name':attribute.default_value
                                                     })
    
    @api.multi
    def get_magento_template(self,sku,backend):
        magento_template = self.env['magento.product.template'].search([('magento_sku','=',sku),('backend_id','=',backend)])
        if magento_template:
            return magento_template
        else :
            return False
    
    @api.multi
    def open_variant_list(self):
        return {
            'name' : 'Product Variants',
            'type': 'ir.actions.act_window',
            'res_model': 'magento.product.product',
            'view_type': 'form',
            'view_mode': 'tree,form',
            'domain' : [('magento_tmpl_id', '=', self.id)],
        }
        
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
                    'domain' : [('id','=',self.erp_id.id)],
                }
        return
    
    @api.multi
    def read(self,fields=None,load='_classic_read'):
        result = super(magento_product_template,self).read(fields=fields,load=load)
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
        result = super(magento_product_template, self).fields_view_get(view_id=view_id,view_type=view_type,toolbar=toolbar, submenu=submenu)
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
        ir_model_data_obj = ir_model_data.search([['model', '=', 'ir.ui.view'], ['name', '=', 'product_attributes_extended_template_form_view']])
        res_id =ir_model_data_obj and ir_model_data_obj[0]['res_id'] or False
        attr_grp = self.read(['attribute_group_ids'])
        grp_ids=attr_grp and attr_grp[0] and attr_grp[0]['attribute_group_ids'] or []#[self.ids[0]]
        ctx =  {}
        ctx.update({'magento_template_id':self.id,
                    'active_id':self.id,
                    'active_ids':self.ids,
                    'open_attributes':True,
                    'attribute_group_ids':grp_ids,
                    'active_model':'magento.product.template'
                    })
        return {
            'name': 'Product Attributes',
            'view_type': 'form',
            'view_mode': 'form',
            'view_id': [res_id],
            'res_model': 'magento.product.template',
            'context': ctx,
            'type': 'ir.actions.act_window',
            'nodestroy': True,
            'target': 'new',
            'res_id': self.id,
        }
    @api.model
    def fields_get(self,toupdate_fields=False):
        context=dict(self._context) or {}
        result = super(magento_product_template, self).fields_get()
        if context.get('attribute_group_ids') and toupdate_fields and context.get('open_attributes'):
            magento_product = self.env['magento.product.template'].browse(context.get('magento_template_id'))
            for field in toupdate_fields:
                attribute = self.env['magento.product.attribute'].browse(field)
                list_of_configurable_attrs = []
#                 if magento_product:
#                     list_of_configurable_attrs = [attribute_value.attribute_id for attribute_value in magento_product.attribute_value_ids]
#                 if attribute.erp_id in list_of_configurable_attrs:
#                     continue
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
        result = super(magento_product_template, self).default_get(fields)
        product = self.env['magento.product.product']
        self = self.env['magento.attribute.option']
        flag = True
        for field in fields:
            if not result.get(field):
                flag = False
        if flag:
            return result
        if context.get('read_option'):
            magento_product = self.env['magento.product.template'].browse(context.get('magento_template_id'))
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
                            domain.append(('magento_template_ids','in',[magento_product.id]))
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
            #print(result)
        return result

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
            update_product_to_magento.delay(session,'magento.product.template',record.id)
    
    @api.multi
    def import_all_images_products(self,products):
        session = ConnectorSession(self.env.cr, self.env.uid,self.env.context)
        backends = defaultdict(self.browse)
        for product in products:
            backends[product.backend_id] |= product
        for backend,products in backends.items() :
            for product in products:
                env = get_environment(session, 'magento.product.template', product.backend_id.id)
                backend_adapter = env.get_connector_unit(ProductTemplateAdapter)
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
    
class product_template(models.Model):
    _inherit = 'product.template'
    
    magento_bind_ids = fields.One2many('magento.product.template','erp_id',string="Magento Template")
    
@magento    
class ProductTemplateAdapter(ProductProductAdapter):
    _model_name = ['magento.product.template']
    
    def write(self, id, data,storeview_id=None):    
        sku = 'sku' in data and data.pop('sku')
        if not sku :
            sku = self._get_sku(id)
        website_ids = data.pop('website_ids')
        sku = urllib.parse.quote_plus(sku.encode('utf8'))
        url = '/all/V1/products/%s'%(sku)
        binding_record = self.env['magento.product.template'].get_magento_template(sku,self.backend_record.id)
        magento_template = self.env['magento.product.template'].browse(binding_record)
        product_data = {
                'product' : data
            }
        res = req(self.backend_record,url,method="PUT",data=product_data)
        data.update({'sku' : sku})
        #self.export_translation_to_magento(data,website_ids,magento_template)
        if res.get('id') :
            binding_record.write({'exported_in_magento' : True})
        return res
        
    def set_magento_attributes(self,record,storeview_id,binding):
        storeview_obj = self.env['magento.storeview'].search([('magento_id','=',storeview_id),('backend_id','=',self.backend_record.id)])
        record = record.get('custom_attributes',{})
        attribute_option = self.env['magento.attribute.option']
        for attribute_code,attribute_value in record.items():
            attr_record = self.env['magento.product.attribute'].search([('backend_id','=',self.backend_record.id),
                                                          ('attribute_code','=',attribute_code)],limit=1)
            search_domain  = []
            search_domain.append(('magento_attribute_id','=',attr_record.id))
            search_domain.append(('magento_template_ids','=',binding.id))
            
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
                binding = self.env['magento.product.template'].get_magento_template(sku,self.backend_record.id)
                if binding and  not attributes:
                    self.set_magento_attributes(content,storeview_id,binding)
                return content
            else :
                raise RetryableJobError("Product read fail for product id : %s"%(id))
            return
        
        
@magento
class ProductTemplateImporterMapper(ProductImportMapper):
    _model_name = ['magento.product.template']
    
    direct = [('name', 'name'),
              ('name','magento_product_name'),
              ('weight', 'weight'),
              ('sku','magento_sku'),
              ('type_id', 'product_type'),
              ('description', 'description'),
              ('short_description', 'description_sale'),
              ('meta_description','meta_description'),
              ('meta_title','meta_title'),
              ('meta_keyword','meta_keyword'),
              ('url_key','url_key')
              ]
    
@magento
class ProductTemplateImporter(ProductImporter): 
    _model_name = ['magento.product.template']
    
    _base_mapper = ProductTemplateImporterMapper
    def _get_binding(self):
        result = False
        session = ConnectorSession(self.env.cr, self.env.uid,context=self.env.context)
        context = dict(self.env.context) 
        magento_template = self.env['magento.product.template']
        sku = self.magento_record.get('sku',False)
        skus=[]
        if sku:
            product_template = magento_template.get_magento_template(sku,self.backend_record.id)
            if product_template:
                result = product_template
        if not result :
            configurable_links  = self.magento_record.get('extension_attributes').get('configurable_product_links')
            for link in configurable_links:
                magento_sku = self.backend_adapter._get_sku(link)
                existing_products = self.env['product.product'].search([('default_code','=',magento_sku)])
                existing_tmpl_id = existing_products and existing_products[0].product_tmpl_id
                if existing_tmpl_id:
                    context.update({'existing_product_tmpl_id' : existing_tmpl_id})
                    #session.change_context({'existing_product_tmpl_id' : existing_tmpl_id}) 
                    self.session = ConnectorSession(self.env.cr, self.env.uid,context=context)
                    return result
        return result
        
    def _validate_date(self,data):
        return
    
    def _create(self, data):
        """ Create the odoo record """
        # special check on data before import
        self._validate_data(data)
        if self.session.context.get('existing_product_tmpl_id') :
            data.update({'erp_id' : self.session.context.get('existing_product_tmpl_id').id})
        #data = self._get_product_vals(data)
        binding = self.env['magento.product.template'].create(data)
        if binding:
            binding.write({'exported_in_magento' : True})
        return binding
    
    def set_configurable_attribte_record(self,record,binding):
        binding.write({'attribute_line_ids':False})
        binding.attribute_line_ids.unlink()
        magento_product_attribute_obj = self.env['magento.product.attribute']
        attribute_line = self.env['product.attribute.line']
        product_template = binding.erp_id
        for magento_attribute in record:
            magento_attibute_id = magento_attribute.get('attribute_id',False)
            if magento_attibute_id:
                magento_attribute_obj = magento_product_attribute_obj.search([('magento_id','=',magento_attibute_id),('backend_id','=',self.backend_record.id)])
                value_ids = []
                if product_template and magento_attribute_obj and magento_attribute_obj.erp_id:
                    magento_attribute_obj.erp_id.write({'create_variant':True})
                    for attribute_option in magento_attribute.get('values',{}):
                        attribute_option = self.env['magento.attribute.option'].search([('magento_attribute_id','=',magento_attribute_obj.id),('magento_id','=',attribute_option.get('value_index',False)),('backend_id','=',self.backend_record.id)],limit=1)
                        if attribute_option :
                            value_ids.append(attribute_option.erp_id.id)
                    attribute_line.create({'product_tmpl_id':product_template.id,
                                'attribute_id': magento_attribute_obj.erp_id.id,
                                'value_ids':[(6,0,value_ids)]})
    
    
    def set_configurable_product_data_after_import(self,binding,record):
        child_ids=[]
        with self.session.change_context({'allowed_type': ['virtual'],'product_tmpl_id' : binding.erp_id}):
            for child_product in record.get('extension_attributes',{}).get('configurable_product_links',[]):
                virtual_product_importer = self.unit_for(ProductImporter,'magento.product.product')
                virtual_product_importer.run(child_product)
                child_ids.append(self.env['magento.product.product'].with_context({'active_test':False}).search([('magento_id','=',child_product),('backend_id','=',binding.backend_id.id)]).erp_id)
            
        self.session.change_context({'allowed_type':[]})
        attribute_ids = []
        for attribute_line in binding.erp_id.attribute_line_ids:
            attribute_ids.append(attribute_line.attribute_id)

        for child in child_ids:
            value_ids = []
            for attribute in attribute_ids:
                # Change for magento_product_id.magento_id --> child.magento_bind_ids[0].magento_id
                #magento_product_id = self.env['magento.product.product'].search([('erp_id','=',child.id)],limit=1)
                attribute_option = self.env['magento.attribute.option'].with_context({'active_test':False}).search([('magento_product_ids','=',child.magento_bind_ids[0].id),('attribute_id','=',attribute.id)])
                if len(attribute_option) > 1 :
                    attribute_option = attribute_option = self.env['magento.attribute.option'].with_context({'active_test':False}).search([('magento_product_ids','=',child.magento_bind_ids[0].id),('attribute_id','=',attribute.id),('is_default','=',False)])
                if attribute_option and attribute_option.erp_id:
                    value_ids.append(attribute_option.erp_id.id)
            
            initial_child_tmpl = child.product_tmpl_id
            child.write({'product_tmpl_id':binding.erp_id.id,
                         'attribute_value_ids':[(6,0,value_ids)]
                         })
            child.magento_bind_ids[0].write({'magento_tmpl_id' : binding.id})
            if initial_child_tmpl != binding.erp_id:
                if not initial_child_tmpl.product_variant_id and initial_child_tmpl.product_variant_id.magento_bind_ids:
                    initial_child_tmpl.write({'active':False})
        
        if binding.erp_id and binding.erp_id.product_variant_id  :
            if not binding.erp_id.product_variant_id.magento_bind_ids :
                binding.erp_id.product_variant_id.write({'active' : False})
        
        if binding.erp_id.product_variant_id.default_code==False or '':
                binding.erp_id.product_variant_id.write({'active':False})
    
    def set_attribute_record(self,record,binding):
        attribute_option = self.env['magento.attribute.option']
        for attribute_code,attribute_value in record.items():
            attr_value = attribute_value
            attr_record = self.env['magento.product.attribute'].search([('backend_id','=',self.backend_record.id),
                                                          ('attribute_code','=',attribute_code)],limit=1)
            search_domain  = []
            search_domain.append(('magento_attribute_id','=',attr_record.id))
            search_domain.append(('magento_template_ids','=',binding.id))
            
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
                        option.write({'magento_template_ids':[(4,binding.id,0)]})
                        
                elif attr_record.type == 'select':
                    attribute_option = attribute_option.search([('magento_attribute_id','=',attr_record.id),('magento_id','=',attribute_value)])
                    attribute_option.write({'magento_template_ids':[(4,binding.id,0)]})
                else:
                    if not new_attribute_option:
                        new_attribute_option.create({'magento_attribute_id':attr_record.id,
                                                 'attribute_id':attr_record.erp_id.id,
                                                 'create_variants':create_variants,
                                                 'magento_id':binding.magento_id,
                                                 'magento_template_ids':[(6,0,[binding.id])],
                                                 'backend_id':self.backend_record.id,
                                                 'name':attribute_value
                                                 })
                    else:
                        new_attribute_option.write({'magento_attribute_id':attr_record.id,
                                                 'attribute_id':attr_record.erp_id.id,
                                                 'create_variants':create_variants,
                                                 'magento_id':binding.magento_id,
                                                 'magento_template_ids':[(6,0,[binding.id])],
                                                 'backend_id':self.backend_record.id,
                                                 'name':attribute_value
                                                 })
                    
        return
    
    def import_product_images(self,binding,magento_id):
        from odoo.addons.odoo_magento2_ept.models.product.product_image import MagentoImageImporter
        image_importer = self.unit_for(MagentoImageImporter,'magento.product.image')
        all_images = self.backend_adapter.get_images(magento_id)
        if all_images:
            for one_image in all_images:
                image_importer.run(one_image.get('id'),binding,one_image.get('file',''),image_data = one_image)
    
    def _after_import(self,binding):
        record = self.magento_record
        backend = self.backend_record
        self.set_attribute_record(record['custom_attributes'],binding)
        if backend.allow_import_image_of_products : 
            self.import_product_images(binding,self.magento_id)
        if backend.allow_import_traslation:
            with self.session.change_context({'translation': True}):
                translation_importer = self.unit_for(TranslationImporter)
                traslated_record = translation_importer.run(self.magento_id, binding.id,
                                         mapper_class=ProductImportMapper)
        self.set_configurable_attribte_record(record.get('extension_attributes',{}).get('configurable_product_options',[]),binding)
        if record.get('type_id','') == 'configurable' :
            self.set_configurable_product_data_after_import(binding,record)


@magento
class ProductTemplateExporter(ProductExporter):
    _model_name = ['magento.product.template'] 
    
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
    
    def _export_dependencies(self):
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
        if self.binding_record.product_type == 'configurable' and self.binding_record.erp_id:
            child_ids = self.binding_record.erp_id.product_variant_ids
            all_child = self.binding_record.erp_id.with_context({'active_test':False}).product_variant_ids
            for child in child_ids:
                magento_product=self.env['magento.product.product']
                if not child.magento_bind_ids:
                    magento_obj = magento_product.create({'erp_id':child.id,'backend_id':self.binding_record.backend_id.id,'website_ids':[((6,0,self.binding_record.website_ids.ids))],
                                            'created_at': datetime.now(),'updated_at':datetime.now(),'magento_sku' : child.default_code,'product_type':'simple'})
                    self._export_dependency(magento_obj,'magento.product.product')
                else :
                    magento_obj = magento_product.search([('erp_id','=',child.id),('backend_id','=',self.binding_record.backend_id.id),('magento_sku','=',child.default_code)])
                    self._export_dependency(magento_obj,'magento.product.product')
            products_to_active = all_child - child_ids 
            for product in products_to_active:
                temp_template = product.product_tmpl_id.with_context(create_product_product=False).copy({'name':product.product_tmpl_id.name,'attribute_line_ids':False,'product_variant_ids':False,'product_variant_id':False})
                product.write({'active':True,'product_tmpl_id':temp_template.id})
                temp_template._compute_product_variant_count()
    
@magento
class ProductTemplateExportMapper(ProductProductExportMapper):
    _model_name = ['magento.product.template']
    
    @mapping
    def extension_attribute(self, record,lang=None):
        if record.product_type == 'configurable':
            configurable_product_options = []
            product_attribute_value_ids = []
            magento_attribute = self.env['magento.product.attribute']
            magento_attribute_option = self.env['magento.attribute.option']
            if not record.attribute_line_ids:
                return
            for line in record.attribute_line_ids:
                product_attribute_value_ids = product_attribute_value_ids + line.value_ids.ids
            magento_attribute_values = magento_attribute_option.search([('erp_id','in',product_attribute_value_ids),('backend_id','=',self.backend_record.id)])
            attribute_ids = [attribute.attribute_id for attribute in magento_attribute_values]
            attribute_ids = dict.fromkeys(attribute_ids).keys()
            for attribute_id in attribute_ids:
                if attribute_id.create_variant:
                    attr = magento_attribute.search([('erp_id','=',attribute_id.id),('backend_id','=',self.backend_record.id)])
                    if attr:
                        temp_dict = {
                            "attribute_id" : str(attr.magento_id),
                            "label":attr.frontend_label,
                            "values" : [ { 'value_index':attribute_value.magento_id} for attribute_value in magento_attribute_values if attribute_value.attribute_id == attribute_id]
                        }
                        configurable_product_options.append(temp_dict)
   
            magento_product_product = self.env['magento.product.product'].search([('erp_id','in',record.erp_id.product_variant_ids.ids),'|',('active','=',False),('active','=',True)])
            return {'extension_attributes':{
                        "configurable_product_options": configurable_product_options,
                        "configurable_product_links": [ product_product.magento_id  for product_product in magento_product_product  if product_product.magento_id]
                    }
                }
        return
    
    
    def finalize(self, map_record, values):
        # Here Needs to map all fields which will not take data from attribute struture. like mapped sku with default_code etc..
        #fields = self.options.get('fields',[])
        for_create = self.options.get('for_create',False)
        if for_create :
            record=map_record.source
            pricelist = record.backend_id.pricelist_id
            values['name']= values.get('name') or  record.name
            values['sku'] = values.get('sku') or  record.magento_sku
            values.update({                
                    'type_id': record.product_type,                
                    })
        return values
