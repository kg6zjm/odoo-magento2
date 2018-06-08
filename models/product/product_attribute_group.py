from odoo import models,fields,api
from odoo.addons.odoo_magento2_ept.models.backend.backend import magento
from odoo.addons.odoo_magento2_ept.models.unit.mapper import (ExportMapper,
                                                             mapping
                                                             )
from odoo.addons.odoo_magento2_ept.models.unit.export_synchronizer import MagentoExporter
from odoo.addons.odoo_magento2_ept.models.unit.delete_synchronizer import MagentoDeleter
from odoo.addons.odoo_magento2_ept.models.unit.backend_adapter import GenericAdapter
from odoo.addons.odoo_magento2_ept.models.backend.exception import NoExternalId
from odoo.addons.odoo_magento2_ept.models.api_request import req
import urllib.parse

# class attribute_group(models.Model):
#     _name = "attribute.group"
#     _description = "Attribute Group"
#     _order ="sequence"
# 
#     name=fields.Char(string='Name',size=128,required=True,translate=True)
#     sequence=fields.Integer('Sequence')
#     attribute_set_id=fields.Many2one(comodel_name='attribute.set',string='Attribute Set')
#     attribute_ids=fields.One2many(comodel_name='attribute.location',inverse_name='attribute_group_id',string='Attributes')
#    
#     @api.model
#     def create(self,vals):
#         if vals.get('attribute_ids'):
#             for attribute in vals['attribute_ids']:
#                 if vals.get('attribute_set_id') and attribute[2] and \
#                         not attribute[2].get('attribute_set_id'):
#                     attribute[2]['attribute_set_id'] = vals['attribute_set_id']
#         else:
#             vals['attribute_ids'] = []
#         return super(attribute_group, self).create(vals)
#     
#     @api.multi
#     def unlink(self):
#         for record in self:
#             attribute_location_ids = self.env['attribute.location'].search([('attribute_group_id','=',record.id)])
#             attribute_location_ids.unlink()
#         return super(attribute_group, self).unlink()


 
class magento_attribute_group(models.Model):
    _name = "magento.attribute.group"
    _inherit = 'magento.binding'
    
    #erp_id=fields.Many2one('attribute.group',string='Odoo Attribute Group',ondelete='cascade')
    name=fields.Char(string='Name',size=64,required=True)
    sort_order=fields.Integer(string='Sort order')
    attribute_list=fields.Text(string='Atrtibute list')
    attribute_set_id=fields.Many2one('magento.attribute.set',string="Attribute Set")
    magento_attribute_ids = fields.Many2many('magento.product.attribute',string="Attributes",domain="[('backend_id','=',backend_id)]")
    attribute_ids=fields.One2many(comodel_name='attribute.location',inverse_name='attribute_group_id',string='Attributes')

    _sql_constraints = [
        ('magento_uniq', 'unique(backend_id, magento_id)',
         'An attribute option with the same ID on Magento already exists.'),
#         ('openerp_uniq', 'unique(backend_id, erp_id)',
#          'An attribute option can not be bound to several records on the same backend.'),
    ]

    @api.onchange('attribute_set_id')
    def onchange_attribute_set_id(self):
        return {'domain':{'backend_id':[('id','in',[self.attribute_set_id.backend_id.id])]}}
    
    @api.onchange('magento_attribute_ids')
    def onchange_magento_attributes(self):
        g_ids = self._origin.search([])
        #result = {'domain':[('')]}
        r = g_ids.read(['magento_attribute_ids'])
        #print r
        pass
    
    @api.multi
    def unlink(self):
        for record in self:
            attribute_location_ids = self.env['attribute.location'].search([('attribute_group_id','=',record.id)])
            attribute_location_ids.unlink()
        return super(magento_attribute_group, self).unlink()
    
    @api.model
    def create(self,vals):
        res = super(magento_attribute_group,self).create(vals)
        
        res.attribute_set_id.create_attribute_location()
        attr_ids = vals.get('magento_attribute_ids')
        attr_location_obj = self.env['attribute.location']
        if attr_ids :
            magento_attributes = res.magento_attribute_ids
            attributes = attr_location_obj.search([('attribute_group_id','=',res.id)])
            attributes.unlink()
            for magento_attr in magento_attributes :
                attr_location_obj.create({
                                              'attribute_id':magento_attr.erp_id.id,
                                              'attribute_group_id':res.id,
                                              'sequence':magento_attr.position or 1
                                              })
        return res
        
    
    @api.multi
    def write(self,vals):
        attr_ids = vals.get('magento_attribute_ids')
        attr_location_obj = self.env['attribute.location']
        result = super(magento_attribute_group,self).write(vals)
        if attr_ids :
            for group in self :
                magento_attributes = group.magento_attribute_ids
                for magento_attr in magento_attributes :
                    attr_loc = attr_location_obj.search([('attribute_id','=',magento_attr.erp_id.id),('attribute_group_id','=',group.id)])
                    if not attr_loc :
                        attr_location_obj.create({
                                              'attribute_id':magento_attr.erp_id.id,
                                              'attribute_group_id':group.id,
                                              'sequence':magento_attr.position
                                              })
                attributes = attr_location_obj.search([('attribute_group_id','=',group.id),('attribute_id','not in',[attr.erp_id.id for attr in magento_attributes])])
                attributes.unlink()
        return result
    


@magento
class AttributeGroupExportMapper(ExportMapper):
    _model_name = ['magento.attribute.group']

    direct = [
        ('name', 'attribute_group_name'),
        #('sort_order', 'sort_order'),
    ]

    @mapping
    def backend_id(self, record):
        return {'attribute_group_name': record.name,
                'attribute_set_id': int(record.attribute_set_id.magento_id)}
        
    @mapping
    def attributes(self,record):
        magento_attributes = record.magento_attribute_ids
        attribute_list = [] 
        if magento_attributes :
            for magento_attribute in magento_attributes :
                attr_loc = self.env['attribute.location'].search([('attribute_id','=',magento_attribute.erp_id.id),
                                                       ('attribute_group_id','=',record.id)],limit =1)
                attribute_list.append((magento_attribute.magento_id,attr_loc.sequence or magento_attribute.position))
        return {'attribute_list':attribute_list} 


@magento
class AttributeGroupExporter(MagentoExporter):
    _model_name = ['magento.attribute.group']

    def _should_import(self):
        """ Before the export, compare the update date
        in Magento and the last sync date in odoo,
        if the former is more recent, schedule an import
        to not miss changes done in Magento.
        """
        return False
    
    def _export_dependencies(self):
        if not self.binding_record.attribute_set_id.magento_id :
            raise NoExternalId('Must be retried later')
        for attribute in self.binding_record.magento_attribute_ids :
            self._export_dependency(attribute,'magento.product.attribute')
        
    
    def _create(self, data):
        """ Create the Magento record """
        # special check on data before export
        self._validate_create_data(data)
        attrs_list = data.pop('attribute_list')
        id = self.backend_adapter.create(data)
        for attribute_id in attrs_list:
            self.backend_adapter.addAttribute(attribute_id=attribute_id[0],
                                            set_id=data.get('attribute_set_id'),
                                            group_id=id,
                                            sequence=attribute_id[1]
                                            )
        
        return id
    
    
    def _update(self, data):
        """ Update an Magento record """
        assert self.magento_id
        # special check on data before export
        self._validate_update_data(data)
        attribute_set_id = data.get('attribute_set_id')
        if data.get('attribute_list'):
            attrs_list = data.pop('attribute_list')
            magento_attrs = self.backend_adapter.read_attributes(attribute_set_id,
                                                                 self.binding_record.name)
            for attribute_id in attrs_list:
                if not attribute_id[0] in magento_attrs :
                    self.backend_adapter.addAttribute(attribute_id=attribute_id[0],
                                                   set_id=attribute_set_id,
                                                   group_id=self.magento_id,
                                                   sequence=attribute_id[1]
                                                   )
                    continue
                if attribute_id[0] in magento_attrs and int(magento_attrs[attribute_id[0]][1]) != attribute_id[1] :     
                    self.backend_adapter.addAttribute(attribute_id=attribute_id[0],
                                                   set_id=attribute_set_id,
                                                   group_id=self.magento_id,
                                                   sequence=attribute_id[1]
                                                   )
                magento_attrs.pop(attribute_id[0])    
            if magento_attrs :
                for attr_code in magento_attrs :
                    self.backend_adapter.delete_attribute(attr_code,attribute_set_id)               
                
        self.backend_adapter.write(self.magento_id, data)
    


@magento
class AttributeGroupDeleter(MagentoDeleter):
    _model_name = ['magento.attribute.group']


@magento
class AttributeGroupAdapter(GenericAdapter):
    _model_name = 'magento.attribute.group'
    _magento_model = 'ol_catalog_product_attribute_group'
    _path='/V1/products/attribute-sets/'

    def create(self,data):
        data = {
                'group' : data
                }
        url = self._path+"groups"
        data.update({'url':url})
        content = super(AttributeGroupAdapter,self).create(data)
        result = content.get('attribute_group_id')
        return result
    
    def delete(self,id):
        url =self._path+"groups"
        data = {'url':url}
        content = super(AttributeGroupAdapter,self).delete(id,data)

        return 
    
    def read_attributes(self,set_id,group_name):
        data = {
                'attribute_set_id':set_id
                }
        url = "/V1/attribute"
        groups = req(self.backend_record,url,method="POST",data=data)
        attribute_list = {}
        for group in groups :
            attributes = group.get(group_name)
            if attributes:
                for attribute in attributes :
                    attribute_list.update({attributes[attribute].values()[0]:(attribute,attributes[attribute].keys()[0])}) 
                return attribute_list
        return attribute_list
        
    def addAttribute(self, attribute_id, set_id, group_id,sequence=1):
        data = {
                'attribute_set_id':set_id,
                'attribute_group_id':group_id,
                'attribute_code':attribute_id,
                'sort_order':sequence 
                }
        url = self._path+"attributes"
        content = req(self.backend_record,url,method="POST",data=data)
        return
    
    def delete_attribute(self,attribute_code,attribute_set_id):
        attribute_code = urllib.parse.quote(attribute_code)
        url = self._path+"%s/attributes"%(attribute_set_id)
        data = {'url':url}
        content = super(AttributeGroupAdapter,self).delete(attribute_code,data)
        return 
    
    def write(self, id, data):
        set_id = data.get('attribute_set_id')
        data.update({
                     'attribute_group_id':id,
                     })
        url = self._path+"%s/groups"%(set_id)
        data={
              'group':data
              }
        content = req(self.backend_record,url,method="PUT",data=data)
        return 
    
   