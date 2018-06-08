# -*- coding: utf-8 -*-
##############################################################################
#
#    Author: Guewen Baconnier
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

import logging
from datetime import datetime, timedelta
from odoo import models, fields,api,_
from odoo.exceptions import ValidationError
from odoo.addons.odoo_magento2_ept.models.unit.mapper import (mapping,
                                                  ImportMapper,
                                                  ExportMapper,
                                                  )
from odoo.addons.odoo_magento2_ept.models.backend.exception import (IDMissingInBackend,
                                                MappingError,
                                                )
from odoo.addons.odoo_magento2_ept.models.unit.backend_adapter import (GenericAdapter,
                                   MAGENTO_DATETIME_FORMAT,
                                   )
from odoo.addons.odoo_magento2_ept.models.unit.import_synchronizer import (DelayedBatchImporter,
                                       MagentoImporter,
                                       TranslationImporter,import_batch
                                       )
from odoo.addons.odoo_magento2_ept.models.unit.delete_synchronizer import MagentoDeleter
from odoo.addons.odoo_magento2_ept.models.unit.export_synchronizer import (MagentoExporter, export_record)
from odoo.addons.odoo_magento2_ept.models.backend.backend import magento
from odoo.addons.odoo_magento2_ept.models.api_request import req
from odoo.addons.odoo_magento2_ept.models.search_criteria import create_search_criteria
import urllib.request as urllib
import base64
from odoo.addons.odoo_magento2_ept.models.backend.magento_model import IMPORT_DELTA_BUFFER
from odoo.addons.odoo_magento2_ept.models.backend.session import ConnectorSession


_logger = logging.getLogger(__name__)


class MagentoProductCategory(models.Model):
    _name = 'magento.product.category'
    _inherit = 'magento.binding'
    #_inherits = {'product.category': 'erp_id'}
    _description = 'Magento Product Category'
    MAGENTO_HELP = "This field is a technical / configuration field for " \
                   "the category on Magento. \nPlease refer to the Magento " \
                   "documentation for details. "
    _rec_name='complete_category_name'
                   
    def get_custom_design(self):
        return [
                ('1','Magento Blank'),
                ('2','Magento Luma')
            ]

    @api.multi
    def _get_custom_design(self):
        return self.get_custom_design()

    @api.multi
    def get_page_layout(self):
        return [
            ('empty', 'Empty'),
            ('1column', '1 colmun'),
            ('2columns-left', '2 columns with left bar'),
            ('2columns-right', '2 columns with right bar'),
            ('3columns', '3 columns'),
            ]

    @api.multi
    def _get_page_layout(self):
        return self.get_page_layout()


    #erp_id = fields.Many2one(comodel_name='product.category',string='Product Category',required=True,ondelete='cascade')
    name = fields.Char("Name")
    complete_category_name = fields.Char(string="Complete name",compute="_compute_complete_name")
    description = fields.Text(translate=True)
    magento_parent_id = fields.Many2one(comodel_name='magento.product.category',string='Magento Parent Category',ondelete='cascade',)
    magento_child_ids = fields.One2many(comodel_name='magento.product.category',inverse_name='magento_parent_id',string='Magento Child Categories',)
    #==== General Information ====
    thumbnail_like_image=fields.Boolean(string='Thumbnail like main image',default=True)
    thumbnail_binary=fields.Binary(string='Thumbnail')
    thumbnail=fields.Char(string='Thumbnail name',size=100, help=MAGENTO_HELP)
    image_binary=fields.Binary(string='Image')
    image=fields.Char(string='Image name', size=100, help=MAGENTO_HELP)
    meta_title=fields.Char(string='Title (Meta)', size=75, help=MAGENTO_HELP)
    meta_keywords=fields.Text(string='Meta Keywords', help=MAGENTO_HELP)
    meta_description=fields.Text(string='Meta Description', help=MAGENTO_HELP)
    url_key=fields.Char(string='URL-key', size=100, readonly="True")
        #==== Display Settings ====
    display_mode=fields.Selection([
                                   ('PRODUCTS', 'Products Only'),
                                   ('PAGE', 'Static Block Only'),
                                   ('PRODUCTS_AND_PAGE', 'Static Block & Products')],
                                  string='Display Mode', required=True, help=MAGENTO_HELP,default='PRODUCTS')
    
    is_anchor=fields.Boolean(string='Anchor?', help=MAGENTO_HELP,default=True)
    use_default_available_sort_by=fields.Boolean(string='Default Config For Available Sort By', help=MAGENTO_HELP,default=True)

    #TODO use custom attribut for category

        #'available_sort_by': fields.sparse(
        #    type='many2many',
        #    relation='magerp.product_category_attribute_options',
        #    string='Available Product Listing (Sort By)',
        #    serialization_field='magerp_fields',
        #    domain="[('attribute_name', '=', 'sort_by'), ('value', '!=','None')]",
        #    help=MAGENTO_HELP),
        #filter_price_range landing_page ?????????????
    default_sort_by=fields.Selection([
                    ('_', 'Config settings'), #?????????????
                    ('position', 'Best Value'),
                    ('name', 'Name'),
                    ('price', 'Price')],
                    string='Default sort by', required=True, help=MAGENTO_HELP,default='_')

        #==== Custom Design ====
    custom_apply_to_products=fields.Boolean(string='Apply to products', help=MAGENTO_HELP)
    custom_design=fields.Selection( _get_custom_design,string='Custom design',help=MAGENTO_HELP)
    custom_design_from=fields.Date(string='Active from', help=MAGENTO_HELP)
    custom_design_to=fields.Date(string='Active to', help=MAGENTO_HELP)
    custom_layout_update=fields.Text(string='Layout update', help=MAGENTO_HELP)
    page_layout=fields.Selection(_get_page_layout,string='Page layout', help=MAGENTO_HELP)
    is_active= fields.Boolean(string="Is Active",help=MAGENTO_HELP,default=True)

    _sql_constraints = [
        ('magento_img_uniq', 'unique(backend_id, image)',
         "'Image file name' already exists : must be unique"),
        ('magento_thumb_uniq', 'unique(backend_id, thumbnail)',
         "'thumbnail name' already exists : must be unique"),
    ]
    
    @api.depends('name', 'magento_parent_id.complete_category_name')
    def _compute_complete_name(self):
        for category in self:
            if category.magento_parent_id:
                category.complete_category_name = '%s / %s' % (category.magento_parent_id.complete_category_name, category.name)
            else:
                category.complete_category_name = category.name
                
    
    @api.multi
    def import_product_category(self,backends):
        session = ConnectorSession(self.env.cr, self.env.uid,self.env.context)
        for backend in backends:
            backend.check_magento_structure()
            from_date = getattr(backend, 'last_product_category_import_date')
            if from_date:
                from_date = fields.Datetime.from_string(from_date)
            else:
                from_date = None
            import_batch.delay(session, 'magento.product.category',
                               backend.id,
                               filters={'from_date': from_date,
                                        'to_date': datetime.now()})
            backend.write({'last_product_category_import_date' : datetime.now()})
        return True
        
    @api.multi
    def export_product_category(self):
        session = ConnectorSession(self.env.cr, self.env.uid,self.env.context)
        for record in self:
            export_record.delay(session,'magento.product.category',record.id)
    
    @api.multi
    def update_product_category(self):
        session = ConnectorSession(self.env.cr, self.env.uid,self.env.context)
        for record in self:
            export_record.delay(session,'magento.product.category',record.id)

@magento
class ProductCategoryAdapter(GenericAdapter):
    _model_name = ['magento.product.category']
    _magento_model = 'catalog_category'
    _admin_path = '/{model}/index/'
    _path = '/V1/categories'

 
    def search(self, filters=None, from_date=None, to_date=None):
        """ Search records according to some criteria and return a
        list of ids

        :rtype: list
        """
        result = []
        def filter_ids(tree,res):         
            if tree['children_data']:
                for node in tree.get('children_data'):
                    res.append(filter_ids(node,res))
            return tree['id'] 
        params = {'rootCategoryId':1}               
        tree = super(ProductCategoryAdapter,self).search(filters,params=params)
        result.append(tree.get('parent_id'))
        result.append(filter_ids(tree, result))

        return result
    
    def tree(self, parent_id=None, storeview_id=None):
        """ Returns a tree of product categories

        :rtype: dict
        """
        def filter_ids(tree):
            children = {}
            if tree['children_data']:
                for node in tree['children_data']:
                    children.update(filter_ids(node))
            category_id = {tree['id']: children}
            return category_id
        if parent_id:
            parent_id = int(parent_id)
        params = {'rootCategoryId':1}   
        tree = super(ProductCategoryAdapter,self).search(params=params)
        result = {tree.get('parent_id'):filter_ids(tree)}
        
        return result   
    
    def read(self, id, storeview_id=None, attributes=None):
        """ Returns the information of a record

        :rtype: dict
        """
        if storeview_id :
            url = self._path+"/%s?store_id=%s"%(id,storeview_id)
        else :
            url = self._path+"/%s"%(id)
        content = req(self.backend_record,url)
        if content.get('custom_attributes') :
            for attribute in content.get('custom_attributes'):
                content.update({attribute['attribute_code']:attribute['value']})
        return content
    
    def create(self,data):
        data = {
                'category':data
                }
        res = super(ProductCategoryAdapter,self).create(data)
        return res.get('id')
    
    def write(self,magento_id,data):
        data = {
                'category':data
                }
        content = super(ProductCategoryAdapter,self).write(magento_id,data)
        return

    def move(self, categ_id, parent_id, after_categ_id=None):
        return self._call('%s.move' % self._magento_model,
                          [categ_id, parent_id, after_categ_id])

    def get_assigned_product(self, categ_id):
        return self._call('%s.assignedProducts' % self._magento_model,
                          [categ_id])

    def assign_product(self, categ_id, product_id, position=0):
        return self._call('%s.assignProduct' % self._magento_model,
                          [categ_id, product_id, position, 'id'])

    def update_product(self, categ_id, product_id, position=0):
        return self._call('%s.updateProduct' % self._magento_model,
                          [categ_id, product_id, position, 'id'])

    def remove_product(self, categ_id, product_id):
        return self._call('%s.removeProduct' % self._magento_model,
                          [categ_id, product_id, 'id'])


@magento
class ProductCategoryBatchImporter(DelayedBatchImporter):
    """ Import the Magento Product Categories.

    For every product category in the list, a delayed job is created.
    A priority is set on the jobs according to their level to rise the
    chance to have the top level categories imported first.
    """
    _model_name = ['magento.product.category']

    def _import_record(self, magento_id, priority=None):
        """ Delay a job for the import """
        super(ProductCategoryBatchImporter, self)._import_record(
            magento_id, priority=priority)

    def run(self, filters=None):
        """ Run the synchronization """
        from_date = filters.pop('from_date', None)
        to_date = filters.pop('to_date', None)
        if from_date or to_date:
            updated_ids = self.backend_adapter.search(filters,
                                                      from_date=from_date,
                                                      to_date=to_date)
        else:
            updated_ids = None

        base_priority = 10

        def import_nodes(tree, level=0):
            for node_id, children in tree.items():
                # By changing the priority, the top level category has
                # more chance to be imported before the childrens.
                # However, importers have to ensure that their parent is
                # there and import it if it doesn't exist
                if updated_ids is None or node_id in updated_ids:
                    if node_id != 0:
                        self._import_record(node_id, priority=base_priority+level)
                import_nodes(children, level=level+1)
        tree = self.backend_adapter.tree()
        import_start_time = to_date or datetime.now()
        next_time = import_start_time - timedelta(seconds=IMPORT_DELTA_BUFFER)
        next_time = fields.Datetime.to_string(next_time)
        self.backend_record.write({'last_product_category_import_date': next_time})
        import_nodes(tree)


ProductCategoryBatchImport = ProductCategoryBatchImporter  # deprecated


@magento
class ProductCategoryImporter(MagentoImporter):
    _model_name = ['magento.product.category']

    def _import_dependencies(self):
        """ Import the dependencies for the record"""
        record = self.magento_record
        # import parent category
        # the root category has a 0 parent_id
        if record.get('parent_id'):
            parent_id = record['parent_id']
            importer = self.unit_for(MagentoImporter)
            importer.run(parent_id)
        
    def _after_import(self, binding):
        """ Hook called at the end of the import """
        backend = self.backend_record
        if backend.allow_import_traslation :
            translation_importer = self.unit_for(TranslationImporter)
            translation_importer.run(self.magento_id, binding.id)


ProductCategoryImport = ProductCategoryImporter  # deprecated


@magento
class ProductCategoryImportMapper(ImportMapper):
    _model_name = 'magento.product.category'

    direct = [
        ('description', 'description'),
        ('meta_title','meta_title'),
        ('meta_keywords','meta_keywords'),
        ('meta_description','meta_description'),
        ('image','image'),
        ('url_key','url_key'),
        ('is_anchor','is_anchor'),
        ('custom_apply_to_products','custom_apply_to_products'),
        ('custom_design_from','custom_design_from'),
        ('custom_design_to','custom_design_to'),
        ('custom_layout_update','custom_layout_update'),
        #('page_layout','page_layout')
    ]

    @mapping
    def name(self, record):
        """
        if record['level'] == '0':  # top level category; has no name
            return {'name': self.backend_record.name}
        #level=0 is int and has name also so removed this.
        """
        if record['name']:  # may be empty in storeviews
            return {'name': record['name']}
        
    @mapping
    def magento_id(self, record):
        return {'magento_id': record['id']}

    @mapping
    def backend_id(self, record):
        return {'backend_id': self.backend_record.id}

    @mapping
    def parent_id(self, record):
        if not record.get('parent_id'):
            return
        mag_cat_id = self.env['magento.product.category'].search([('magento_id','=',record['parent_id']),('backend_id','=',self.backend_record.id)])
        if mag_cat_id is None:
            raise MappingError("The product category with "
                               "magento id %s is not imported." %
                               record['parent_id'])
        return {'magento_parent_id': mag_cat_id.id}
    
    @mapping
    def display_mode(self,record):
        if record.get('display_mode'):
            return {'display_mode':record.get('display_mode')}
        return 
    
    @mapping
    def boolean_field(self,record):
        res = {}
        fields = ['is_anchor','custom_apply_to_products']
        for field in fields :
            if record.get(field)=='0':
                res.update({field:False})
            if not record.get('is_anchor'):
                res.update({'is_anchor':True})
        return res
    
    @mapping
    def image(self,record):
        url = record.get('image')
        if url :
            backend_id = self.backend_record.id
            storeviews = self.env['magento.storeview'].search([('backend_id','=',backend_id)])
            for storeview in storeviews:
                if storeview.base_media_url :
                    base_media_url = storeview.base_media_url
                    break
            url = "%s/catalog/category/%s"%(base_media_url,url)
            binary = ""
            try : 
                response = urllib.urlopen(url)
                binary = base64.b64encode(response.read())
            except :
                pass
            
            return {'image_binary':binary if binary else False}
        return
    
    @mapping
    def default_sort_by(self,record):
        if record.get('default_sort_by'):
            return {'default_sort_by':record['default_sort_by']}

@magento
class ProductCategoryDeleteSynchronizer(MagentoDeleter):
    """ Product category deleter for Magento """
    _model_name = ['magento.product.category']


@magento
class ProductCategoryExporter(MagentoExporter):
    _model_name = ['magento.product.category']
 
    def _export_dependencies(self):
        """Export parent of the category"""
        #TODO FIXME
        env = self.environment
        record = self.binding_record
        binder = self.binder_for()
        if record.magento_parent_id:
            mag_parent_id = record.magento_parent_id.id
            if binder.to_backend(mag_parent_id) is None:
                exporter = env.get_connector_unit(ProductCategoryExporter)
                exporter.run(mag_parent_id)
        return True
    
    def create_custom_attribute_vals(self,data):
        custom_attributes = ['description','meta_title','meta_keywords','meta_description','is_anchor','image','url_key','custom_design','display_mode','custom_design_from','custom_design_to','custom_layout_update','page_layout','default_sort_by']
        attributes = []
        for attribute in custom_attributes :
            if attribute in data :
                attributes.append({'attribute_code':attribute,'value':data.pop(attribute)})
        if attributes :
            data.update({'custom_attributes':attributes})
        return data
    
    def _create(self, data):
        data = self.create_custom_attribute_vals(data)
        return super(ProductCategoryExporter,self)._create(data)
    
    def _update(self, data):
        data = self.create_custom_attribute_vals(data)
        return super(ProductCategoryExporter,self)._update(data)
    
    
        
    
@magento
class ProductCategoryExportMapper(ExportMapper):
    _model_name = ['magento.product.category']

    direct = [('description', 'description'),
              #change that to mapping top level category has no name
              ('is_active', 'is_active'),
              ('meta_title', 'meta_title'),
              ('meta_keywords', 'meta_keywords'),
              ('meta_description', 'meta_description'),
              ('display_mode', 'display_mode'),
              ('is_anchor', 'is_anchor'),
              #('use_default_available_sort_by', 'use_default_available_sort_by'),
              ('custom_design', 'custom_design'),
              ('custom_design_from', 'custom_design_from'),
              ('custom_design_to', 'custom_design_to'),
              ('custom_layout_update', 'custom_layout_update'),
              ('page_layout', 'page_layout'),
              
             ]

    @mapping
    def sort(self, record):
        return {'default_sort_by':'price', 'available_sort_by': ['price']}


    @mapping
    def parent(self, record):
        """ Magento root category's Id equals 1 """
        if record.magento_parent_id:
            parent_id = record.magento_parent_id.magento_id 
        if not parent_id:
            parent_id = 1
        return {'parent_id':parent_id}
    
    @mapping
    def name(self,record):
        return {'name':record.name}

    @mapping
    def image(self, record):
        res = {}
        if record.image_binary:
            res.update({'image': record.image,
                        #'image_binary': record.image_binary
                        })
        return res