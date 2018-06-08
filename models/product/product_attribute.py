
from odoo.addons.odoo_magento2_ept.python_library.unidecode import unidecode
import re
from odoo import models, api, fields
from lxml import etree
import ast
from odoo.osv import orm
from odoo.addons.odoo_magento2_ept.models.unit.mapper import (ExportMapper,
                                                             ImportMapper,
                                                             mapping)
from odoo.addons.odoo_magento2_ept.models.backend.backend import magento
from odoo.addons.odoo_magento2_ept.models.unit.binder import MagentoModelBinder
from odoo.addons.odoo_magento2_ept.models.unit.backend_adapter import GenericAdapter
from odoo.addons.odoo_magento2_ept.models.unit.delete_synchronizer import MagentoDeleter
from odoo.addons.odoo_magento2_ept.models.unit.export_synchronizer import (MagentoExporter,export_record)
from odoo.addons.odoo_magento2_ept.models.unit.import_synchronizer import (DelayedBatchImporter,
                                                                          MagentoImporter , import_batch)
from odoo.addons.odoo_magento2_ept.models.backend.exception import (FailedJobError,
                                                                )
from odoo.addons.odoo_magento2_ept.models.api_request import req
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
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT,ustr
from datetime import datetime
#import odoo.addons.odoo_magento2_ept.models.product.product.ProductImportMapper
#from odoo.addons.odoo_magento2_ept.models.product.product import ProductProductAdapter
#from odoo.addons.odoo_magento2_ept.models.product.product import ProductImportMapper
import logging
_logger = logging.getLogger(__name__)




def safe_column_name(string):
    """This function prevent portability problem in database column name
    with other DBMS system
    Use case : if you synchronise attributes with other applications """
    string = unidecode(string.replace(' ', '_').lower())
    return re.sub(r'[^0-9a-z_]','', string)

field_mapping = {
                 #attribute_code:field name
                'category_ids':'category_ids',
                'sku':'magento_sku',
                'name':'name',
                'weight':'weight',
                'description':'description',
                'short_description':'description_sale',
                'price':'list_price',
                'cost':'standard_price',
                'url_key' : 'url_key',
                'meta_description' : 'meta_description',
                'meta_title' : 'meta_title',
                'meta_keywords' : 'meta_keywords'
            }

@magento(replacing=MagentoModelBinder)
class MagentoAttributeBinder(MagentoModelBinder):
    _model_name = [
        'magento.product.attribute',
        'magento.attribute.option',
        'magento.attribute.set',
        'magento.attribute.group'
        ]

class attribute_attribute(models.Model):
    
    _inherit = "product.attribute"
    _description = "Attribute"


    @api.multi
    def _get_model_product(self):
        model, res_id = self.env['ir.model.data'].get_object_reference('product', 'model_product_product')
        return res_id

    magento_bind_ids=fields.One2many('magento.product.attribute','erp_id',string='Magento Bindings')
                                    #default=_get_model_product)

    option_ids=fields.One2many(comodel_name='product.attribute.value',inverse_name='attribute_id',string='Attribute Options')
    '''attribute_type=fields.Selection([
            ('char', 'Char'),
            ('text', 'Text'),
            ('select', 'Select'),
            ('multiselect', 'Multiselect'),
            ('boolean', 'Boolean'),
            ('integer', 'Integer'),
            ('date', 'Date'),
            ('datetime', 'Datetime'),
            ('binary', 'Binary'),
            ('float', 'Float')],string='Type', required=True)
    serialized=fields.Boolean(string='Field serialized',
            help="If serialized, the field will be stocked in the serialized "
                 "field: attribute_custom_tmpl or attribute_custom_variant "
                 "depending on the field based_on")
    
    create_date=fields.Datetime(string='Created date', readonly=True)
    relation_model_id=fields.Many2one(comodel_name='ir.model',string='Model')
    required_on_views=fields.Boolean(string='Required (on views)',
            help="If activated, the attribute will be mandatory on the views, "
                 "but not in the database")
    '''
        
    @api.model
    def create(self, vals):
        '''if vals.get('field_id') and vals.get('name') in field_mapping.keys():
            create_data = {'field_id':vals.get('field_id'),
                           'required_on_views':vals.get('required_on_views'),
                           'attribute_type':vals.get('attribute_type')}
            return super(attribute_attribute, self).create(create_data)
        if vals.get('relation_model_id'):
            relation = self.env['ir.model'].search([vals.get('relation_model_id')])
            relation=relation[0]['model']
        else:
            relation = 'product.attribute.value'
        if vals['attribute_type'] == 'select':
            vals['ttype'] = 'many2one'
            vals['relation'] = relation
        elif vals['attribute_type'] == 'multiselect':
            vals['ttype'] = 'many2many'
            vals['relation'] = relation
            vals['relation_table'] = '%s_product_rel'%(vals['name'])
            vals['serialized'] = True
        else:
            vals['ttype'] = vals['attribute_type']
        
      
        if vals.get('serialized'):
            field_obj = self.env['ir.model.fields']
            serialized_objs = field_obj.search([
                ('ttype', '=', 'serialized'),
                ('model_id', '=', vals['model_id']),
                ('name', '=', 'x_custom_json_attrs')]
                )
            serialized_ids=[x.id for x in serialized_objs]
            if serialized_ids:
                vals['serialization_field_id'] = serialized_ids[0]
            else:
                f_vals = {
                    'name': u'x_custom_json_attrs',
                    'field_description': u'Serialized JSON Attributes',
                    'ttype': 'serialized',
                    'model_id': vals['model_id'],
                }
                vals['serialization_field_id'] = field_obj.with_context({'manual': True}).create(f_vals).id
        vals['state'] = 'manual'
        '''
        return super(attribute_attribute, self).create(vals)
    
    @api.multi
    def unlink(self):
        for record in self:
            if record.option_ids :
                record.option_ids.unlink()
            attribute_location_ids = self.env['attribute.location'].search([('attribute_id','=',record.id)])
            attribute_location_ids.unlink()
        return super(attribute_attribute, self).unlink()

    @api.multi    
    def onchange_name(self, name):
        res = {}
        if not name.startswith('x_'):
            name = u'x_%s' % name
        else:
            name = u'%s' % name
        res = {'value': {'name': unidecode(name)}}

        #FILTER ON MODEL
        context=self._context
        model_name = context.get('force_model')
        if not model_name:
            model_id = context.get('default_model_id')
            if model_id:
                model = self.env['ir.model'].browse(model_id)
                model_name = model.model
        if model_name:
            model_obj = self.env[model_name]
            allowed_model = [x for x in model_obj._inherits] + [model_name]
            res['domain'] = {'model_id': [['model', 'in', allowed_model]]}

        return res
  

class MagentoProductAttribute(models.Model):
    _name = 'magento.product.attribute'
    _description = "Magento Product Attribute"
    _inherit = 'magento.binding'
    _rec_name = 'attribute_code'
    MAGENTO_HELP = "This field is a technical / configuration field for " \
                   "the attribute on Magento. \nPlease refer to the Magento " \
                   "documentation for details. "


    _inherits = {'product.attribute':'erp_id'}
    
    _field_type_mapping = {
        'binary':'binary',
        'boolean':'boolean',
        'char':'char',
        'text':'text',
        'select':'many2one',
        'multiselect':'many2many',
        'integer':'integer',
        'date':'date',
        'datetime':'datetime',
        'float':'float'
    }
    @api.multi
    def copy(self, default=None):
        if default is None:
            default = {}
        default['attribute_code'] = default.get('attribute_code', '') + 'Copy '
        return super(MagentoProductAttribute, self).copy(default)
    
    @api.multi
    def _frontend_input(self):
        res={}
      
        return res

    erp_id=fields.Many2one('product.attribute',required=True,string='Attribute',ondelete='cascade')
    attribute_code=fields.Char(string='Code',required=True,size=200)
    scope=fields.Selection([('store', 'store'), ('website', 'website'), ('global', 'global')],
                           string='Scope',default='global',required=True,help=MAGENTO_HELP)
    apply_to=fields.Selection([('simple', 'simple')],string='Apply to',required=True,default='simple',help=MAGENTO_HELP)
    frontend_input=fields.Char(compute=_frontend_input,method=True,string='Frontend input',store=False,
                               help="This field depends on odoo attribute 'type' field "
                               "but used on Magento")
    frontend_label=fields.Char(string='Label', required=True, size=100, help=MAGENTO_HELP)
    position=fields.Integer(string='Position', help=MAGENTO_HELP)
    group_id= fields.Integer(string='Group', help=MAGENTO_HELP) 
    default_value=fields.Char(string='Default Value',size=10,help=MAGENTO_HELP)
    note=fields.Char(string='Note', size=200, help=MAGENTO_HELP)
    entity_type_id=fields.Integer(string='Entity Type', help=MAGENTO_HELP)
        # boolean fields
    is_visible_in_advanced_search=fields.Boolean(string='Visible in advanced search?', help=MAGENTO_HELP,default=True)
    is_visible=fields.Boolean(string='Visible?', help=MAGENTO_HELP,default=True)
    is_visible_on_front=fields.Boolean(string='Visible (front)?', help=MAGENTO_HELP,default=True)
    is_html_allowed_on_front=fields.Boolean(string='Html (front)?', help=MAGENTO_HELP)
    is_wysiwyg_enabled=fields.Boolean(string='Wysiwyg enabled?', help=MAGENTO_HELP)
    is_global=fields.Boolean('Global?', help=MAGENTO_HELP)
    is_unique=fields.Boolean('Unique?', help=MAGENTO_HELP)
    is_required=fields.Boolean('Required?', help=MAGENTO_HELP)
    is_filterable=fields.Boolean('Filterable?', help=MAGENTO_HELP,default=True)
    is_comparable=fields.Boolean('Comparable?', help=MAGENTO_HELP,default=True)
    is_searchable=fields.Boolean('Searchable ?', help=MAGENTO_HELP,default=True)
    is_configurable=fields.Boolean('Configurable?', help=MAGENTO_HELP)
    is_user_defined=fields.Boolean('User defined?', help=MAGENTO_HELP)
    used_for_sort_by=fields.Boolean('Use for sort?', help=MAGENTO_HELP)
    is_used_for_price_rules=fields.Boolean('Used for pricing rules?', help=MAGENTO_HELP)
    is_used_for_promo_rules=fields.Boolean('Use for promo?', help=MAGENTO_HELP)
    used_in_product_listing=fields.Boolean('In product listing?', help=MAGENTO_HELP)
    #added by krishna
    options=fields.Text(string="Attribute Options")
    option_ids=fields.One2many('magento.attribute.option', 'magento_attribute_id',string='Options')
    create_state=fields.Selection([('new', 'New'),('created', 'Done')], string='State')
    additional_check=fields.Boolean(string='is it additional?')
    type=fields.Selection([('char', 'Char'),
                                         ('text', 'Text'),
                                         ('select', 'Select'),
                                         ('multiselect', 'Multiselect'),
                                         ('boolean', 'Boolean'),
                                         ('integer', 'Integer'),
                                         ('date', 'Date'),
                                         ('datetime', 'Datetime'),
                                         ('binary', 'Binary'),
                                         ('float', 'Float')],
                                         string='Type',required=True)
    
                                 
    _sql_constraints = [
        ('attribute_code_unique', 'unique(attribute_code,backend_id)',
         "Attribute with the same code already exists with this magento instance : must be unique"),
        ('openerp_uniq', 'unique(backend_id, erp_id)',
         'An attribute can not be bound to several records on the same backend.'),
    ]
    
    @api.multi
    def import_attribute(self,backends):
        session = ConnectorSession(self.env.cr, self.env.uid,self.env.context)
        for backend in backends:
            backend.check_magento_structure()
            for backend in backends:
                from_date = backend.last_attribute_import_date or False
                if from_date:
                    from_date = datetime.strptime(from_date,DEFAULT_SERVER_DATETIME_FORMAT)
                else:
                    from_date = None            
                import_batch.delay(session, 'magento.product.attribute', backend.id,filters=[ from_date and from_date.strftime(DEFAULT_SERVER_DATETIME_FORMAT) or ''])
                backend.write({'last_attribute_import_date' : datetime.now()})
        return True  
    
    @api.multi
    def export_product_attribute(self):
        session = ConnectorSession(self.env.cr, self.env.uid,self.env.context)
        for record in self:
            export_record.delay(session,'magento.product.attribute',record.id)
            
    @api.multi
    def update_product_attribute(self):
        session = ConnectorSession(self.env.cr, self.env.uid,self.env.context)
        for record in self:
            export_record.delay(session,'magento.product.attribute',record.id)
    @api.multi
    def open_attribute_value(self):
        return {
                'name':'Attribute Value',
                'type': 'ir.actions.act_window',
                'res_model': 'magento.attribute.option',
                'view_type': 'form',
                'view_mode': 'tree,form',
                'domain' : [('magento_attribute_id','=',self.id),('erp_id','!=',False)],
            }

    @api.model
    def create(self,vals):
        if not vals.get('name',False):
            vals['name'] = vals.get('frontend_label',False) or 'No Label'
        if not vals.get('create_variant',False):
            vals['create_variant'] = vals.get('is_configurable',False)
        res = super(MagentoProductAttribute,self).create(vals)
        return res

    @api.multi
    def _build_attribute_field(self, page, attribute):
        parent = etree.SubElement(page, 'group')
        kwargs = {'String': "%s" % attribute.name,
                  'name':"%s"%attribute.attribute_code.lower().replace(" ", "_")}
        if attribute.type in ['multiselect', 'text']:
            parent = etree.SubElement(parent, 'group')
            etree.SubElement(parent,
                                   'separator',
                                    string="%s" % attribute.frontend_label,
                                    name="name",
                                    colspan="4")
            kwargs['nolabel'] = "1"
        if attribute.type in ['multiselect', 'select']:
#             if attribute.relation_model_id:
#                 # attribute.domain is a string, it may be an empty list
#                 try:
#                     domain = ast.literal_eval(attribute.domain)
#                 except ValueError:
#                     domain = None
#                 if domain:
#                     kwargs['domain'] = attribute.domain
#                 else:
#                     ids = [op.value_ref.id for op in attribute.option_ids]
#                     kwargs['domain'] = "[('id', 'in', %s)]" % ids
#             else:
            if attribute.name == 'categ_ids':
                backend_ids = [backend.backend_id.id for backend in attribute.attribute_id.magento_bind_ids]
                domain =  "[('magento_bind_ids.backend_id','in',%s)]"%backend_ids
                kwargs['domain']= domain
            else :
                kwargs['domain'] = "[('magento_attribute_id', '=', %s)]" % attribute.id
                if attribute.type == 'multiselect':
                    kwargs['widget'] = 'many2many_tags'
                    kwargs['options']="{'no_create':True}"            
            kwargs['context'] = "{'default_magento_attribute_id': %s}" % attribute.id
        if attribute.type == 'boolean':
            kwargs['required'] = str(False)
        else :
            kwargs['required'] = str(attribute.is_required)
            # or
            #                     attribute.required_on_views)
        field = etree.SubElement(parent, 'field', **kwargs)
        orm.setup_modifiers(field, self.fields_get(attribute.attribute_code))
        return parent


    @api.multi
    def _build_attributes_notebook(self, attribute_group_ids):
        notebook = etree.Element('notebook', name="attributes_notebook", colspan="4")
        toupdate_fields = []
        attribute_group_objects = self.env['magento.attribute.group'].browse(attribute_group_ids)
        for group in attribute_group_objects:#grp_obj.browse(attribute_group_ids):
            if group.name == 'Images':
                continue
            page = etree.SubElement(notebook, 'page', string=group.name.capitalize())
            for attribute in group.magento_attribute_ids:
                if attribute.name not in toupdate_fields:
                    if attribute.attribute_code in field_mapping.keys():
                        continue
                    list_of_configurable_attrs = []
                    magento_product = self.env[self._context.get('active_model')].browse(self._context.get('magento_product_id'))
                    if magento_product:
                        list_of_configurable_attrs = [attribute_value.attribute_id for attribute_value in magento_product.attribute_value_ids]
                    if attribute.erp_id in list_of_configurable_attrs:
                        continue
                    toupdate_fields.append(attribute.id)
                    self._build_attribute_field(page, attribute)
        return notebook, toupdate_fields

@magento
class ProductAttributeAdapter(GenericAdapter):
    _model_name = ['magento.product.attribute']
    _magento_model = 'ol_catalog_product_attribute'
    _magento_default_model = 'product_attribute'
    _path = "/V1/products/attributes"
    
    def search(self, filters=None):
        """ Search records according and returns a list of ids
        :rtype: list
        """
        filters = {'main_table.attribute_id':{'gt':-1}}
        result = []
        content = super(ProductAttributeAdapter,self).search(filters)
        for record in content.get('items') :
            result.append(record['attribute_code'])
        return result
    
    def search_attribute(self, filters=None):
        """ Search records according and returns a list of ids
            :rtype: list
        """
        id=filters.get('attribute_set_id')
#         return [int(row['attribute_id']) for row
#                 in self._call('%s.list' % self._magento_model,[id])]
        return self._call('%s.list' % self._magento_model, [id])
    
    def create(self, data):
        """ Create a record on the external system """
        data = {
                    "attribute":data
                }
        content = super(ProductAttributeAdapter,self).create(data)
        result = content.get('attribute_id')
        if not result :
            raise FailedJobError("Result from Magento : %s"%content)
        return result

    def write(self,attribute_id,data):
        binder = self.binder_for()
        attribute = binder.to_openerp(attribute_id,browse=True)
        attribute_code = attribute and attribute.attribute_code or False
        if not  attribute_code :
            raise FailedJobError("attribute code not found")
        data.update({'attribute_id':attribute_id})
        data = {
                'attribute':data
                }
        content = super(ProductAttributeAdapter,self).write(attribute_code,data)
        result = content.get('attribute_id',False)
        if not result :
            raise FailedJobError("Attribute not updated : %s "%content)
        return result
    
@magento
class ProductAttributeDeleter(MagentoDeleter):
    _model_name = ['magento.product.attribute']
    

@magento
class ProductAttributeBatchImporter(DelayedBatchImporter):
    _model_name = ['magento.product.attribute']

@magento
class ProductAttributeImporter(MagentoImporter):
    _model_name = ['magento.product.attribute']
    
    def _get_magento_data(self):
        """ Return the raw Magento data for ``self.magento_id`` """
        result = self.backend_adapter.read(self.magento_id)
        if result and result.get('attribute_id'):
            self.magento_id = result.get('attribute_id')
            return result
        else : 
            #23/03/2017
            #if attribute is import custom set to "No" in Magento then
            #in response false will be there so we will skip the attribute import
            if not result :
                return result
            raise FailedJobError("Attribute id not found : %s"%result)     
    
    def _must_skip(self):
        """ Hook called right after we read the data from the backend.
    
            If the method returns a message giving a reason for the
            skipping, the import will be interrupted and the message
            recorded in the job (if the import is called directly by the
            job, not by dependencies).

            If it returns None, the import will continue normally.
    
            :returns: None | str | unicode
            """
        if not self.magento_record :
            return "Product attribute can not imported  because it is not importable."
        apply_to = self.magento_record.get('apply_to')
        if apply_to and len(apply_to) > 0 and 'simple' not in apply_to:
            return "Product attribute can not imported because it not for simple product."
        return     

            
    def _create_attribute_option(self,binding,data):
        magento_option_obj = self.env['magento.attribute.option']
        product_attribute_value = self.env['product.attribute.value']
        option_list = []
        if data.get('options'):
            for item in data.get('options'):
                odoo_attribute_option = product_attribute_value.search([('name','=',item.get('label','-')),('attribute_id','=',binding.erp_id.id)])
                
                check = magento_option_obj.search([('name', '=',item.get('label','-')),
                                                   ('attribute_id', '=', binding.erp_id.id),
                                                   ('magento_attribute_id','=', binding.id)
                                                   
                                                   ])
                if not check :
                    if item.get('value') == 0:
                        value = 0
                    elif item.get('value') is None :
                        value = None
                    elif item.get('value') is False :
                        value = 'False'
                    elif item.get('value') == '':
                        continue
                    else:
                        value = item.get('value')
                    is_default = False
                    if data.get('default_value'):
                        if item.get('value') in data.get('default_value').split(","):
                            is_default = True
                    vals = {'name':item.get('label','-'),
                           'magento_id': value,
                           'magento_attribute_id': binding.id,
                           'attribute_id':binding.erp_id.id,
                           'backend_id': data.get('backend_id'),
                           'is_default' : is_default,
                           'system_option': item.get('system_option','false') == 'true',
                           }
                    if odoo_attribute_option:
                        vals.update({'erp_id' : odoo_attribute_option.id})
                    option = magento_option_obj.create(vals)
                else :
                    option = check[0]
                option_list.append(option.id)
            extra_option_ids = magento_option_obj.search([('id', 'not in', option_list),
                                                          ('magento_attribute_id', '=', binding.id),
                                                          ('backend_id', '=',data.get('backend_id'))
                                                          ]
                                                        )
            if extra_option_ids:
                extra_option_ids.unlink()
        
    def _check_odoo_attribute(self,data):
        if data.get('frontend_label') == 'No frontend label' :
            return data
        else  : 
            attribute = self.env['product.attribute'].search([('name','=',data.get('frontend_label'))],limit=1)
            for magento_attribute in attribute.magento_bind_ids : 
                if magento_attribute.backend_id.id == data.get('backend_id'):
                    if data.get('attribute_code') == magento_attribute.attribute_code :
                        if attribute : 
                            data.update({'erp_id' : attribute.id})
                else :
                    if attribute : 
                        data.update({'erp_id' : attribute.id})
            return data
    
    def _create(self, data):
        """ Create the odoo record """
        model = self.model
        data = self._check_odoo_attribute(data)
        binding = model.create(data)
        self._create_attribute_option(binding, data)
        _logger.debug('%s %d created from magento %s',
                      self.model._name, binding.id, self.magento_id)
        return binding
    
    def _update(self, binding, data):
        """ Update an odoo record """
        self._validate_data(data)
        if not data.get('name',False):
            data['name'] = data.get('frontend_label',False) or 'No Label'
        if not data.get('create_variant',False):
            data['create_variant'] = data.get('is_configurable',False)
        binding.write(data)
        self._create_attribute_option(binding, data)
        _logger.debug('%d updated from magento %s', binding.id, self.magento_id)
        return
    
@magento
class ProductAttributeImportMapper(ImportMapper):
    _model_name = 'magento.product.attribute'
    direct = [
        ('attribute_code', 'attribute_code'),  # required
#         ('frontend_input', 'frontend_input'),
        ('scope', 'scope'),
        ('is_global', 'is_global'),
        ('is_filterable', 'is_filterable'),
        ('is_comparable', 'is_comparable'),
        ('is_visible', 'is_visible'),
        ('is_searchable', 'is_searchable'),
        ('is_user_defined', 'is_user_defined'),
        ('is_configurable', 'is_configurable'),
        ('is_visible_on_front', 'is_visible_on_front'),
        ('is_used_for_price_rules', 'is_used_for_price_rules'),
        ('is_unique', 'is_unique'),
        ('is_required', 'is_required'),
        ('position', 'position'),
        ('group_id', 'group_id'),
        ('default_value', 'default_value'),
        ('is_visible_in_advanced_search', 'is_visible_in_advanced_search'),
        ('note', 'note'),
        ('entity_type_id', 'entity_type_id'),
        ('frontend_label', 'frontend_label'),
#         ('backend_type', 'type'),
        ('attribute_id', 'magento_id'),
        ('options', 'options'),
        ('is_wysiwyg_enabled','is_wysiwyg_enabled'),
        ('is_html_allowed_on_front','is_html_allowed_on_front'),
        ('is_used_for_promo_rules','is_used_for_promo_rules'),
        ('used_for_sort_by','used_for_sort_by'),
        ('used_in_product_listing','used_in_product_listing'),
        ('additional_check','additional_check'),
        ('is_configurable', 'create_variant'),
        ('frontend_label', 'name'),
    ]

    @mapping
    def backend_id(self, record):

        return {'backend_id': self.backend_record.id}

    @mapping
    def frontend_label(self, record):
        #required
        direct = [
        ('updated_date','updated_date_in_magento'),
        ('attribute_code', 'attribute_code'),  # required
#         ('frontend_input', 'frontend_input'),
        ('scope', 'scope'),
        ('is_global', 'is_global'),
        ('is_filterable', 'is_filterable'),
        ('is_comparable', 'is_comparable'),
        ('is_visible', 'is_visible'),
        ('is_searchable', 'is_searchable'),
        ('is_user_defined', 'is_user_defined'),
        ('is_configurable', 'is_configurable'),
        ('is_visible_on_front', 'is_visible_on_front'),
        ('is_used_for_price_rules', 'is_used_for_price_rules'),
        ('is_unique', 'is_unique'),
        ('is_required', 'is_required'),
        ('position', 'position'),
        #('group_id', 'group_id'),
        ('default_value', 'default_value'),
        ('is_visible_in_advanced_search', 'is_visible_in_advanced_search'),
        ('note', 'note'),
        ('entity_type_id', 'entity_type_id'),
        ('frontend_label', 'frontend_label'),
#         ('backend_type', 'type'),
        ('attribute_code', 'magento_id'),
        ('options', 'options'),
        ('is_wysiwyg_enabled','is_wysiwyg_enabled'),
        ('is_html_allowed_on_front','is_html_allowed_on_front'),
        ('is_used_for_promo_rules','is_used_for_promo_rules'),
        ('used_for_sort_by','used_for_sort_by'),
        ('used_in_product_listing','used_in_product_listing'),
        ('is_configurable', 'create_variant'),
        ('frontend_label', 'name'),
    ]
        res = {}
        apply_list = ['grouped', 'configurable', 'virtual', 'bundle', 'downloadable','simple']
        if not record.get('apply_to'):
            record['apply_to'] = apply_list
        for item in direct:
            if record.get(item[0]):
                if record.get(item[0]) == '0':
                    res[item[1]] = False
                else:
                    res[item[1]] = record[item[0]]
        label = None
        if isinstance(record.get('frontend_labels'), list):
            label = record.get('frontend_labels')[0].get('label')
        if record.get('default_frontend_label') :
            label = record.get('default_frontend_label')
        if not label:
            label = 'No frontend label'
        #replace type with 'frontend_input' by krishna
        #print record.get('frontend_input',False)
        if record.get('frontend_input'):
            if record.get('frontend_input') in  ['textarea']:
                record['type'] = 'text'
            elif record.get('frontend_input') == 'text':
                record['type'] = 'char'
            elif record.get('frontend_input') == 'date':
                record['type'] = 'date'
            elif record.get('frontend_input') == 'boolean':
                record['type'] = 'boolean'
            elif record.get('frontend_input') == 'multiselect':
                record['type'] = 'multiselect'
            elif record.get('frontend_input') in ['price', 'weee', 'weight']:
                record['type'] = 'float'
            elif record.get('frontend_input') == 'media_image':
                record['type'] = 'binary'
            elif  record.get('frontend_input') == 'select':
                record['type'] = 'select'
            else:
                record['type'] = 'text'
        else:
            record['type'] = 'text'
        scope = record.get('scope')
        if not scope:
            scope = 'global'
        config_value = False
        if record.get('is_configurable'):
            if record.get('is_configurable') == '1':
                config_value = True
        if record.get('is_filterable'):
            if record.get('is_filterable') != '0':
                res['is_filterable'] = True
        res['is_configurable'] = config_value
        res['frontend_label'] = label
        res['type'] =  record.get('type')
        res['scope'] = scope
        #{'is_configurable': config_value, 'frontend_label': label, 'scope': scope, 'frontend_input': record.get('frontend_input')}
        return res

#Completed

@magento
class ProductAttributeExporter(MagentoExporter):
    _model_name = ['magento.product.attribute']
    
    def validate_fields_for_magento(self,data):
        """
            set booleand fields values as 0 and 1 and not pass 'None' values to magento
            because these values are not allowed when pass data to magento.
        """
        for field in data:
            if data[field] == None :
                del data[field]
            if data[field] == True:
                data[field] = 1
            if data[field] == False :
                data[field] = 0
        
        
    def _validate_create_data(self,data):
        self.validate_fields_for_magento(data)
    
    def _validate_update_data(self,data):
        self.validate_fields_for_magento(data)
    
    def _should_import(self):
        "Attributes in magento doesn't retrieve infos on dates"
        return False

#     def _after_export(self):
#         """ Run the after export"""
#         sess = self.session
#         attribute_location_obj = sess.pool.get('attribute.location')
#         magento_attribute_obj = sess.pool.get('magento.product.attribute')
#         magento_attribute_set_obj = sess.pool.get('magento.attribute.set')
#         attribute_set_adapter = self.get_connector_unit_for_model(
#             GenericAdapter, 'magento.attribute.set')
#         attribute_id = self.binding_record.erp_id.id
#         magento_attribute_id = magento_attribute_obj.browse(
#                     sess.cr, sess.uid,
#                     self.binding_record.id,context=sess.context).magento_id
#         attribute_location_ids = attribute_location_obj.search(
#             sess.cr, sess.uid,
#             [['attribute_id','=',attribute_id]], context=sess.context)
#         for attribute_location in attribute_location_ids:
#             attribute_set_id = attribute_location_obj.browse(
#                 sess.cr, sess.uid,
#                 attribute_location, context=sess.context).attribute_set_id.id
#             magento_attribute_set_ids = magento_attribute_set_obj.search(
#                 sess.cr, sess.uid,
#                 [['erp_id','=',attribute_set_id]],
#                 context=sess.context)
#             for magento_attribute_set in magento_attribute_set_ids:
#                 magento_attribute_set_id = magento_attribute_set_obj.browse(
#                     sess.cr, sess.uid,
#                     magento_attribute_set,context=sess.context).magento_id
#                 attribute_set_adapter.update(
#                     magento_attribute_set_id, magento_attribute_id)

@magento
class ProductAttributeExportMapper(ExportMapper):
    _model_name = ['magento.product.attribute']

    direct = [
        ('attribute_code', 'attribute_code'), # required
        ('frontend_input', 'frontend_input'),
        ('scope', 'scope'),
        ('is_filterable', 'is_filterable'),
        ('is_comparable', 'is_comparable'),
        ('is_visible', 'is_visible'),
        ('is_searchable', 'is_searchable'),
        ('is_user_defined', 'is_user_defined'),
        #('is_configurable', 'is_configurable'),
        ('is_visible_on_front', 'is_visible_on_front'),
        ('is_unique', 'is_unique'),
        ('is_required', 'is_required'),
        ('position', 'position'),
        ('default_value', 'default_value'),
        ('is_visible_in_advanced_search', 'is_visible_in_advanced_search'),
        ('note', 'note'),
        ('entity_type_id', 'entity_type_id'),
        ]

    @mapping
    def frontend_label(self, record):
        #required
        return {'default_frontend_label':record.frontend_label}
        """return {'frontend_labels': [{
                'store_id': 0,
                'label': record.frontend_label,
            }]}"""
        
    @mapping
    def entity_type(self,record):
        if record.entity_type_id :
            return {'entity_type_id':record.entity_type_id}
        else :
            #entity_type_id = 4 means product attribute
            return {'entity_type_id':4} 
        
    @mapping
    def frontend_type(self,record):
        type = record.type
        frontend_input = ""
        if type:
            if type in  ['char','text']:
                frontend_input = 'text'
            elif type == 'date':
                frontend_input = 'date'
            elif type == 'boolean':
                frontend_input = 'boolean'
            elif type == 'multiselect':
                frontend_input = 'multiselect'
            elif type == 'float' :
                frontend_input = 'price'
            elif type == 'binary':
                frontend_input = 'media_image'
            elif  type == 'select':
                frontend_input = 'select'
            else:
                frontend_input = 'text'
        else:
            frontend_input = 'text'
        return {'frontend_input':frontend_input}
