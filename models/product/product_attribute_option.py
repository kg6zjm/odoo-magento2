from lxml import etree
from odoo import models, fields, api, _
from odoo.addons.odoo_magento2_ept.models.unit.backend_adapter import GenericAdapter
from odoo.addons.odoo_magento2_ept.models.unit.delete_synchronizer import MagentoDeleter
from odoo.addons.odoo_magento2_ept.models.unit.export_synchronizer import MagentoExporter
from odoo.addons.odoo_magento2_ept.models.unit.mapper import (ExportMapper,
                                                             mapping,
                                                             )
from odoo.addons.odoo_magento2_ept.models.backend.connector import get_environment
from odoo.addons.odoo_magento2_ept.models.backend.backend import magento
from odoo.addons.odoo_magento2_ept.models.backend.related_action import unwrap_binding
from odoo.addons.odoo_magento2_ept.models.backend.session import ConnectorSession
from odoo.addons.odoo_magento2_ept.models.logs.job import job, related_action
from odoo.addons.odoo_magento2_ept.models.backend.backend import magento
from odoo.addons.odoo_magento2_ept.models.api_request import req
from odoo.addons.odoo_magento2_ept.models.unit.mapper import (ExportMapper,
                                                             ImportMapper,
                                                             mapping)
from odoo import models, fields, api, _
from odoo.addons.odoo_magento2_ept.models.logs.job import job, related_action
from odoo.addons.odoo_magento2_ept.models.unit.synchronizer import Exporter
from odoo.addons.odoo_magento2_ept.models.unit.export_synchronizer import export_record
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
from odoo.addons.odoo_magento2_ept.models.product.product import ProductProductAdapter,ProductImportMapper
class AttributeOption(models.Model):

    _inherit = "product.attribute.value"
    _description = "Attribute Option"


    @api.multi
    def _get_model_list(self):
        model_pool = self.env['ir.model']
        res = model_pool.search( [])        
        return [(r.model, r.name) for r in res]

    
    value_ref=fields.Reference(string='Reference',selection="_get_model_list",size=128)
    magento_bind_ids=fields.One2many('magento.attribute.option','erp_id',string='Magento Bindings')
    is_default=fields.Boolean(string='Is default',default=False)
    system_option=fields.Boolean(string='System Option',default=False)
    create_variants = fields.Boolean(string="Create Variants",default=True)
    
    @api.multi
    def name_change(self, name, relation_model_id):
        if relation_model_id:
            warning = {'title': _('Error!'),
                       'message': _("Use the 'Load Options' button "
                                    "instead to select appropriate "
                                    "model references'")}
            return {"value": {"name": False}, "warning": warning}
        else:
            return True

        
    @api.multi
    def unlink(self):
        for option in self:
            if not option.system_option:
                for magento_option in option.magento_bind_ids:
                #self.env['magento.attribute.option'].unlink(cr, uid, magento_option.id)
                    magento_option.unlink()
            else:
                raise Warning('You can not delete default Magento Attribute option')
        return super(AttributeOption, self).unlink()

        
class MagentoAttributeOption(models.Model):
    _name = 'magento.attribute.option'
    _description = ""
    _inherit = 'magento.binding'
    _inherits = {'product.attribute.value' : 'erp_id'}
    
    
    erp_id=fields.Many2one('product.attribute.value',required=True,string='Odoo Attribute option',ondelete='cascade')
    is_default=fields.Boolean(string='Is default',default=False)
    magento_attribute_id=fields.Many2one('magento.product.attribute',string='Product Attribute',ondelete='cascade')
    magento_id=fields.Char(string='ID on Magento', size=255)
    system_option=fields.Boolean(string='System Option',default=False)
    magento_product_ids = fields.Many2many('magento.product.product',string='Magento Products')
    magento_template_ids = fields.Many2many('magento.product.template',string="Magento Template")
   
    #Never remove 'magento unique' constraint, We need to remove (backend id, magento id) constrain of magento binding,
    # If we remove from this then it will automatic add that constrain 
    # So always put check(1=1) here for magento unique
    _sql_constraints = [
        ('magento_uniq','CHECK(1=1)',
         'An attribute option with the same ID on Magento already exists.'),
        ('openerp_uniq', 'unique(backend_id, erp_id)',
         'An attribute can not be bound to several records on the same backend.'),
    ]
    
    
    @api.multi
    def unlink(self):
        if not self.env.context.get('connector_no_export',False):
            for option in self:
                if option.system_option:
                    raise Warning('You can not delete default Magento Attribute option')
                
        return super(MagentoAttributeOption, self).unlink()

    @api.multi
    def write(self,vals):
        if not self.env.context.get('connector_no_export',False):
            for option in self:
                if option.system_option:
                    raise Warning('You can not update default Magento Attribute option')
                
        return super(MagentoAttributeOption, self).write(vals)
    
#     @api.model
#     def create(self,vals):
#         result = False
#         context=dict(self._context) or {}
#         if not context.get('open_attributes'):
#             return super(MagentoAttributeOption,self).create(vals)
#  
#         magento_product = self.env['magento.product.product'].browse(self._context.get('magento_product_id',False))
#         if magento_product:
#             attributes = magento_product.attribute_option_ids
#             for attribute in attributes:
#                 if attribute and attribute.magento_attribute_id:
#                     field_name = attribute.magento_attribute_id.attribute_code.lower().replace(" ", "_")
#                     if field_name in vals.keys():
#                         result = attribute.write({'name':vals.get(field_name)})
#                      
#                 result = attribute
#         return
            
    
    
   
        
#     @api.model  
#     def fields_view_get(self, view_id=None, view_type='form', toolbar=False, submenu=False):
#         context=dict(self._context) or {}     
#         result = super(MagentoAttributeOption, self).fields_view_get(view_id=view_id,view_type=view_type,toolbar=toolbar, submenu=submenu)
#         if view_type == 'form' and context.get('attribute_group_ids'):
#             eview = etree.fromstring(result['arch'])
#             attributes_notebook, toupdate_fields = self.env['magento.product.attribute']._build_attributes_notebook( context['attribute_group_ids'])
#             result['fields'].update(self.fields_get(toupdate_fields))
#             if context.get('open_attributes'):
#                 placeholder = eview.xpath("//separator[@string='attributes_placeholder']")[0]
#                 placeholder.getparent().replace(placeholder, attributes_notebook)
#             elif context.get('open_product_by_attribute_set'):
#                 main_page = etree.Element('page', string=_('Custom Attributes'))
#                 main_page.append(attributes_notebook)
#                 info_page = eview.xpath("//page[@string='%s']" % (_('Information'),))[0]
#                 info_page.addnext(main_page)
#             result['arch'] = etree.tostring(eview, pretty_print=True)
#         return result


@magento
class AttributeOptionAdapter(GenericAdapter):
    _model_name = ['magento.attribute.option']
    _magento_model = 'oerp_product_attribute'
    _path = "/V1/products/attributes/{attributeCode}/options"

    def create(self, data):
        attribute_id = data.pop('attribute')
        if not attribute_id :
            job = self.env['queue.job'].search([('model_name','=','magento.attribute.option'),('state','=','started')])
            job.requeue()
            #raise FailedJobError(("Attribute not found for attribute option : %s")% data.get('label'))
        data={
              'option':data
            }
        
        path = self._path.format(attributeCode=attribute_id)
        result = req(self.backend_record,path,method="POST",data=data)
        if result == True :
            path = self._path.format(attributeCode=attribute_id)
            options = req(self.backend_record,path,method="GET")
            for option in options :
                if option.get('label')==data['option'].get('label'):
                    return option.get('value')
        return 

    def delete(self, vals):
        """ Delete a record on the external system """
        option_id = vals.get('option_mag_id','')
        attribute_id=vals.get('attribute_mag_id','')
        path = str(self._path+"/{option_id}").format(attributeCode=attribute_id,option_id=option_id)
        result = req(self.backend_record,path,method="DELETE")
        return result

    def read(self, id, attribute_id=None):
        """ Returns the information of a record

        :rtype: dict
        """
        try:
            id = int(id)
        except ValueError:
            pass

        return self._call('ol_catalog_product_attribute.infoOption' % self._magento_model,
                          [int(attribute_id), id])
    #over

@magento
class AttributeOptionDeleteSynchronizer(MagentoDeleter):
    _model_name = ['magento.attribute.option']
    #added by krishna
    def run(self,vals):
        self.backend_adapter.delete(vals)
        return _('Record %s deleted on Magento') % vals.get('option_id','')

@magento
class AttributeOptionExporter(MagentoExporter):
    _model_name = ['magento.attribute.option']
    
    def _should_import(self):
        return False
    
    def _has_to_skip(self):
        magento_attribute = self.binding_record.magento_attribute_id
        if magento_attribute.type not in ['select','multiselect']:
            magento_product_product =  self.env['magento.product.product'].search([('magento_id','=',self.binding_record.magento_id),'|',('active','=',True),('active','=',False)],limit=1)
            magento_product_product.write({'custom_attributes':self.binding_record.name})
            return True
        return False
        
    def _export_dependencies(self):
        attribute = self.binding_record.magento_attribute_id
        if not attribute.magento_id :
            self._export_dependency(attribute,'magento.product.attribute')
    
@magento
class AttributeOptionExportMapper(ExportMapper):
    _model_name = ['magento.attribute.option']

    direct = []

    @mapping
    def label(self, record):
        storeviews = self.env['magento.storeview'].search([('backend_id','=',self.backend_record.id)])
        storeview_label = []
        for storeview in storeviews:
            name = record.name
            storeview_label.append({
                'store_id': storeview.magento_id,
                'label': name
                })
        label = record.name
        return {'label': label,'store_labels':storeview_label}

    @mapping
    def attribute(self, record):
        #binder = self.binder_for('magento.product.attribute')
        #magento_attribute_id = binder.to_backend(record.erp_id.attribute_id.id, wrap=True)
        magento_attribute_id = record.magento_attribute_id and record.magento_attribute_id.magento_id
        return {'attribute': magento_attribute_id}  

    @mapping
    def order(self, record):
        #TODO FIXME
        return {'sort_order': record.erp_id.sequence + 1 }

    @mapping
    def is_default(self, record):
        return {'is_default': record.is_default}
