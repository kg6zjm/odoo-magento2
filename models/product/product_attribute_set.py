from odoo.addons.odoo_magento2_ept.python_library.requests.exceptions import HTTPError
from odoo import models,fields,api    
from odoo.addons.odoo_magento2_ept.models.backend.backend import magento
from odoo.addons.odoo_magento2_ept.models.unit.backend_adapter import GenericAdapter
from odoo.addons.odoo_magento2_ept.models.unit.import_synchronizer import (DelayedBatchImporter,
                                                                          MagentoImporter ,import_batch)
from odoo.addons.odoo_magento2_ept.models.unit.mapper import (ExportMapper,
                                                             ImportMapper,
                                                             mapping)
from odoo.addons.odoo_magento2_ept.models.unit.delete_synchronizer import MagentoDeleter
from odoo.addons.odoo_magento2_ept.models.unit.export_synchronizer import (MagentoExporter , export_record)
from odoo.addons.odoo_magento2_ept.models.backend.exception import FailedJobError
from odoo.addons.odoo_magento2_ept.models.backend.connector import get_environment
from odoo.addons.odoo_magento2_ept.models.backend.session import ConnectorSession
from odoo.addons.odoo_magento2_ept.models.api_request import req
from odoo.addons.odoo_magento2_ept.models.search_criteria import create_search_criteria
from odoo.addons.odoo_magento2_ept.python_library.php import Php
import logging
from datetime import datetime
_logger = logging.getLogger(__name__)
    
# class attribute_set(models.Model):
#     _name = "attribute.set"
#     _description = "Attribute Set"
#     _rec_name = "display_name"
#     
#     name=fields.Char(string='Name',size=128,required=True,translate=True)
#     attribute_group_ids=fields.One2many('attribute.group','attribute_set_id',string='Attribute Groups')
#     magento_bind_ids=fields.One2many(comodel_name='magento.attribute.set',inverse_name='erp_id',string='Magento Bindings')
#     display_name = fields.Char('Name', compute='_get_display_name')
# 
#     @api.multi
#     def _get_display_name(self):
#         for attribute_set in self:
#             magento = attribute_set.magento_bind_ids and attribute_set.magento_bind_ids[0].backend_id.name or ''
#             attribute_set.display_name = "%s - %s" % (
#                 attribute_set.name,magento)

class MagentoAttributeSet(models.Model):
    _name = 'magento.attribute.set'
    _description = "Magento attribute set"
    _inherit = 'magento.binding'
    _rec_name = 'attribute_set_name'

    #erp_id=fields.Many2one('attribute.set',string='Attribute set',ondelete='cascade')
    attribute_set_name=fields.Char(string='Name',size=64,required=True)
    sort_order=fields.Integer(string='Sort order',readonly=True)
    attribute_list=fields.Text(string="Attribute List")
    group_list=fields.Text(string="Group List")
    attribute_group_ids = fields.One2many('magento.attribute.group','attribute_set_id',stribg="Attribute group")
    display_name = fields.Char('Name', compute='_get_display_name')

    @api.multi
    def _get_display_name(self):
        for attribute_set in self:
            magento = attribute_set.backend_id and attribute_set.backend_id.name or ''
            attribute_set.display_name = "%s - %s" % (
                attribute_set.attribute_set_name,magento)
    
    @api.multi
    def name_get(self):
        res = []
        for elm in self.read( ['attribute_set_name']):
            res.append((elm['id'], elm['attribute_set_name']))
        return res

    _sql_constraints = [
        ('unique_backend_magento_attribute_set', 'unique(attribute_set_name, backend_id)',
        'There is already record exists for same magento attribute set and magento instance.')
                        ]

    @api.multi
    def create_attribute_location(self):
        ctx=self.env.context.copy()
        ctx.update({'connector_no_export': True})
        for attributeset in self:
#             product_template_models = self.env['ir.model'].search([('model', '=', 'product.product')])
#             product_template_model_id=[x.id for x in product_template_models]
#             if not attributeset.erp_id:
#                 new_set = self.env['attribute.set'].with_context(ctx).create({
#                                                                               #'model_id': product_template_model_id[0],
#                                                                           'name': attributeset.attribute_set_name})
#                 new_set=new_set.id
#                 attributeset.with_context(ctx).write({'erp_id': new_set})
#             else:
#                 new_set = attributeset.erp_id.id
            groups = self.env['magento.attribute.group'].search([('attribute_set_id', '=', attributeset.id)])

            for group in groups: 
#                 group_check = self.env['attribute.group'].search([('name', '=', group.name),('attribute_set_id', '=', new_set)])
#                 group_check_id=[x.id for x in group_check]
#                 if group_check_id:
#                     new_group_id = group_check_id[0]
#                 else:
#                     new_group = self.env['attribute.group'].with_context(ctx).create({'name': group.name,
#                                                                          'attribute_set_id': new_set,
#                                                                          'sequence': group.sort_order
#                                                                          })
#                     new_group_id=new_group.id
#                 group.with_context(ctx).write({'erp_id': new_group_id})

                if group.attribute_list:
                    check_attribute = eval(group.attribute_list)
                else:
                    check_attribute = {}
                attribute_ids = []
                for key in check_attribute.keys():
                    openerp_attribute_list = self.env['magento.product.attribute'].search([('backend_id','=',attributeset.backend_id.id),('attribute_code', '=', key)])
                    for attribute in openerp_attribute_list:
                        if attribute.erp_id:
                            check = self.env['attribute.location'].search([('attribute_id', '=', attribute.erp_id.id),('attribute_group_id', '=', group.id)])
                            sequence = check_attribute.get(key)
                            if isinstance(sequence, list) :
                                sequence = 0                            
                            if not check:
                                self.env['attribute.location'].with_context(ctx).create({'attribute_id': attribute.erp_id.id,
                                                                            'attribute_group_id': group.id,
                                                                            'sequence': sequence
                                                                             
                                                                           })
                            else :
                                check.write({'sequence': sequence})
                        attribute_ids.append(attribute.id)
                group.with_context(ctx).write({'magento_attribute_ids':[(6,0,attribute_ids)]})
        return True
    
    @api.multi
    def import_attribute_set(self,backends):
        for backend in backends:
            backend.check_magento_structure()
            session = ConnectorSession(self.env.cr,self.env.uid,self.env.context)
            import_batch.delay(session, 'magento.attribute.set', backend.id)
            backend.write({'last_attribute_set_import_date' : datetime.now()})
        return True
    
    @api.multi
    def export_attribute_set(self):
        session = ConnectorSession(self.env.cr, self.env.uid,self.env.context)
        for record in self:
            export_record.delay(session,'magento.attribute.set',record.id)
    
    @api.multi
    def update_attribute_set(self):
        session = ConnectorSession(self.env.cr, self.env.uid,self.env.context)
        for record in self:
            export_record.delay(session,'magento.attribute.set',record.id)
@magento
class AttributeSetAdapter(GenericAdapter):
    _model_name = ['magento.attribute.set']
    _magento_default_model = 'product_attribute_set'
    _magento_model = 'ol_catalog_product_attributeset'
    _path="/V1/products/attribute-sets"
    
    def update(self, id, attribute_id):
        """ Add an existing attribute to an attribute set on the external system
        :rtype: boolean
        """
        return self._call('%s.attributeAdd' % self._magento_default_model,
                          [str(attribute_id),str(id)])
        
    def search(self, filters=None):
        """ Search records according and returns a list of ids
        :rtype: list
        """
        #filters = create_search_criteria(filters)
        filters =  {'searchCriteria':{'filterGroups':[{'filters':[{'field':'entity_type_id','value':-1,'condition_type':'gt'}]}]}}        
        qs = Php.http_build_query(filters)
        url = "%s/sets/list?%s"%(self._path,qs)
        
        result = []
        content = req(self.backend_record,url)
        for record in content.get('items') :
            result.append(record['attribute_set_id'])
        return result
    
    def read(self, id,storeview_id=None, attributes=None):
        """ Returns the information of a record
        :rtype: dict
        """
        content = req(self.backend_record,self._path+"/%s"%(id))
        
        # to get list of groups
        filters={'attribute_set_id':int(id)}
        filters = create_search_criteria(filters)
        qs = Php.http_build_query(filters)
        url = "%s/groups/list?%s"%(self._path,qs)
        groups_list = []
        groups = req(self.backend_record,url)
        groups = groups and groups.get('items',False)
        attributes = []
        url = "/V1/attribute"
        data = {
                'attribute_set_id':id
                }
        set_attribute_list = {}
        try :
            attributes = req(self.backend_record,url,method="POST",data=data)
        except HTTPError as e :
            response = e.response
            status_code = response.get('status_code','')
            if status_code and status_code == 404 :
                raise FailedJobError("""
                                            Attribute Set Import Job Failed : it seems Magento plugin not installed on Magento side.
                                            Resolution : 
                                            You have to install magento plugin named "Emipro_Apichange"
                                            Please Install Magento plugin 'Emipro_Apichange' on Magento.
                                    """)
            else :
                raise FailedJobError("Attribute Set Import Job Failed : \n\n\t%s"%response)
        for group in groups :
            for attribute in attributes :
                if 'attribute_group_name' in group and group['attribute_group_name'] in attribute :
                    attribute_list = attribute[group['attribute_group_name']]
                    group_attributes = {}
                    for attri in attribute_list :
                        group_attributes.update({list(attribute_list[attri].values())[0]:list(attribute_list[attri].keys())[0]})
                    group.update({'attribute_list':group_attributes})
                    set_attribute_list.update(group_attributes)
                    break
            groups_list.append(group)
        content.setdefault('group_list',groups_list)
        content.update({'attribute_list':set_attribute_list})
        return content
    
    def create(self,data):
        skeleton_id = data.pop('skeletonSetId')
        data = {
                'attributeSet':data,
                'skeletonId':skeleton_id
                }
        content = req(self.backend_record,self._path,method="POST",data=data)
        
        result = content.get('attribute_set_id')
        if not result :
            raise FailedJobError("Result from Magento : %s"%content)
        return result
    
    def write(self,set_id,data):
        skeleton_id = data.pop('skeletonSetId')
        data = {
                'attributeSet':data
                }
        content = super(AttributeSetAdapter,self).write(set_id,data) 
        return content


@magento
class AttributeSetDelayedBatchImporter(DelayedBatchImporter):
    _model_name = ['magento.attribute.set']


@magento
class AttributeSetImporter(MagentoImporter):
    _model_name = ['magento.attribute.set']
    
    def _import_dependencies(self):
        record = self.magento_record
        if record.get('attribute_list',{}):
            for attribute_code in record['attribute_list'].keys():
                attribute = self.env['magento.product.attribute'].search([('backend_id','=',self.backend_record.id),
                                                          ('attribute_code','=',str(attribute_code))])
                if not attribute :
                    self._import_dependency(attribute_code,'magento.product.attribute')
            
    def _create(self, data):
        """ Create the odoo record """
        model = self.model
        group_obj = self.env['magento.attribute.group']
        binding = model.create(data)
        option_list = []
        if data.get('group_list') :
            for item in data.get('group_list'):
                check = group_obj.search([('magento_id', '=', item.get('attribute_group_id')),
                                          ('backend_id', '=', data.get('backend_id'))])
                if not check :
                    group = group_obj.create({'magento_id': item.get('attribute_group_id'),
                                                'sort_order': item.get('sort_order'),
                                                'attribute_list': item.get('attribute_list'),
                                                'attribute_set_id': binding.id,
                                                'backend_id': data.get('backend_id'),
                                                'name': item.get('attribute_group_name'), })
                else :
                    group = check[0]
                    group.write({'magento_id': item.get('attribute_group_id'),
                                                                        'sort_order': item.get('sort_order'),
                                                                        'attribute_list': item.get('attribute_list'),
                                                                        'attribute_set_id': binding.id,
                                                                        'backend_id': data.get('backend_id'),
                                                                        'name': item.get('attribute_group_name')})
                option_list.append(group.id)
            check_link = group_obj.search([('id', 'not in', option_list),
                                            ('attribute_set_id', '=', binding.id),
                                            ('backend_id', '=',data.get('backend_id'))])
            check_link.unlink()
        binding.create_attribute_location()
        _logger.debug('%s %d created from magento %s',
                      self.model._name, binding.id, self.magento_id)
        return binding

    def _update(self, binding, data):
        binding.write(data)
        group_obj = self.env['magento.attribute.group']
        option_list = []
        if data.get('group_list'):
            for item in data.get('group_list'):
                check = group_obj.search([('magento_id','=',item.get('attribute_group_id')),
                                                                     ('attribute_set_id','=',binding.id),
                                                                     ('backend_id','=',data.get('backend_id'))])
                if not check:
                    group = group_obj.create({
                                                                                     'magento_id':item.get('attribute_group_id'),
                                                                                     'sort_order':item.get('sort_order'),
                                                                                     'attribute_list': item.get('attribute_list'),
                                                                                     'attribute_set_id':binding.id,
                                                                                     'backend_id':data.get('backend_id'),
                                                                                     'name':item.get('attribute_group_name')
                                                                                     })
                else:
                    group = check[0]
                    group.write({
                                                                        'magento_id':item.get('attribute_group_id'),
                                                                        'sort_order':item.get('sort_order'),
                                                                        'attribute_list': item.get('attribute_list'),
                                                                        'attribute_set_id':binding.id,
                                                                        'backend_id':data.get('backend_id'),
                                                                        'name':item.get('attribute_group_name')
                                                                        })
                option_list.append(group.id)
            check_link = group_obj.search([('id','not in',option_list),
                                           ('attribute_set_id','=',binding.id),
                                           ('backend_id','=',data.get('backend_id'))])
            check_link.unlink()
            binding.create_attribute_location()
        _logger.debug('%s %d created from magento %s',
                      self.model._name, binding.id, self.magento_id)
        return binding

@magento
class AttributeSetImportMapper(ImportMapper):
    _model_name = ['magento.attribute.set']

    direct = [
        ('attribute_set_name', 'attribute_set_name'),
        ('attribute_set_id', 'magento_id'),
        ('sort_order', 'sort_order'),
        ('group_list', 'group_list'),
        ('attribute_list', 'attribute_list')]
         

    @mapping
    def backend_id(self, record):
        return {'backend_id': self.backend_record.id}


@magento
class AttributeSetDeleteSynchronizer(MagentoDeleter):
    _model_name = ['magento.attribute.set']


@magento
class AttributeSetExporter(MagentoExporter):
    _model_name = ['magento.attribute.set']
        
    def _should_import(self):
        "Attributes in magento doesn't retrieve infos on dates"
        return False
    
    def _after_export(self):
        backend = self.binding_record.backend_id
        session = ConnectorSession(self.env.cr, self.env.uid,
                                   context=self.env.context)
        env = get_environment(session, 'magento.attribute.set', backend.id)
        importer = env.get_connector_unit(AttributeSetImporter)
        importer.run(self.magento_id)  


@magento
class AttributeSetExportMapper(ExportMapper):
    _model_name = 'magento.attribute.set'

    direct = [
        ('attribute_set_name', 'attribute_set_name'),
    ]
    
    @mapping
    def sort_order(self,record):
        result = {}
        if record.sort_order :
            result.update({'sort_order':1})
        else :
            result.update({'sort_order':0})
        return result
            
    
    @mapping
    def skeletonSetId(self, record):
        tmpl_set_id = self.backend_record.attribute_set_tpl_id.id
        if tmpl_set_id:
            binder = self.binder_for('magento.attribute.set')
            magento_tpl_set_id = binder.to_backend(tmpl_set_id)
        else:
            raise FailedJobError((
                "\n\n'Default Attribute Set' field must be define on "
                "the Magento Global.\n\n"
                "Resolution: \n"
                "- Go to Magento > Settings > Globals > '%s'\n"
                "- Set the field Attribte set Tempalte\n"
                )% self.backend_record.name)
        return {'skeletonSetId': magento_tpl_set_id}
    
    @mapping
    def entity_type_id(self,record):
        """To create product type attribute set.""" 
        return {'entity_type_id':4}

class attribute_location(models.Model):
    _name = "attribute.location"
    _description = "Attribute Location"
    _order="sequence"
    _inherits = {'product.attribute': 'attribute_id'}

    
#     @api.multi
#     #@api.depends('attribute_group_id','attribute_set_id')
#     def _get_attribute_loc_from_group(self):
#         return self.env['attribute.location'].search([('attribute_group_id', 'in', self.ids)])

    attribute_id=fields.Many2one('product.attribute',string='Product Attribute',required=True,ondelete="cascade")
    attribute_set_id=fields.Many2one('magento.attribute.set',related="attribute_group_id.attribute_set_id",string='Attribute Set',readonly=True,store=True)
    attribute_group_id=fields.Many2one(comodel_name='magento.attribute.group',string='Attribute Group',required=True)
    sequence=fields.Integer(string='Sequence')
        
