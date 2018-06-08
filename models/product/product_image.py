import base64
import urllib
import os
import re
import mimetypes
import urllib.parse
from odoo.addons.odoo_magento2_ept.models.backend.session import ConnectorSession
from odoo.exceptions import Warning,ValidationError
from odoo import models, fields, api
from odoo.tools.translate import _
from odoo.addons.odoo_magento2_ept.models.backend.backend import magento
from odoo.addons.odoo_magento2_ept.models.unit.binder import MagentoModelBinder
from odoo.addons.odoo_magento2_ept.models.unit.delete_synchronizer import MagentoDeleter
from odoo.addons.odoo_magento2_ept.models.unit.export_synchronizer import MagentoExporter
from odoo.addons.odoo_magento2_ept.models.unit.import_synchronizer import MagentoImporter
from odoo.addons.odoo_magento2_ept.models.unit.mapper import (ImportMapper,
                                                             ExportMapper,
                                                             mapping,
                                                             changed_by,
                                                             only_create,
                                                             )
from odoo.addons.odoo_magento2_ept.models.unit.backend_adapter import GenericAdapter
from odoo.addons.odoo_magento2_ept.models.api_request import req
from odoo.addons.odoo_magento2_ept.models.backend.exception import (FailedJobError,
                                                                   IDMissingInBackend,NothingToDoJob
                                                                   )
from odoo.addons.odoo_magento2_ept.python_library.requests.exceptions import HTTPError
from odoo.addons.odoo_magento2_ept.models.backend.connector import get_environment
import logging
_logger = logging.getLogger(__name__)

IMAGE_PER_FOLDER = 500

#TODO find a good solution in order to roll back changed done on file system
#TODO add the possibility to move from a store system to an other
# (example : moving existing image on database to file system)

MAGENTO_HELP = "This field is a technical / configuration field for " \
               "the attribute on Magento. \nPlease refer to the Magento " \
               "documentation for details. "
               
@magento(replacing=MagentoModelBinder)
class MagentoImageBinder(MagentoModelBinder):
    _model_name = [
        'magento.product.image',
    ]
 

class MagentoProductImage(models.Model):
    _name = 'magento.product.image'
    _description = "Magento product image"
    _inherit = 'magento.binding'
    
    @api.multi
    def get_image(self):
        for image in self:
            if image.link:
                if image.url:
                    from odoo.addons.odoo_magento2_ept.python_library import requests
                    response = requests.get(image.url)
                    if response.ok and response.content : 
                        img = base64.b64encode(response.content)
                    else :
                        img = False
                else:
                    return False
            else:
                img = image.file_db_store
            return img
    
    @api.multi
    def _get_image(self):        
        for each in self:
            each.file = each.get_image()

    
    magento_product_id=fields.Many2one('magento.product.product',string="Magento Product")
    magento_tmpl_id = fields.Many2one('magento.product.template',string="Magento Template")
    #storeview_id = fields.Many2one('magento.storeview',string="Storeview")
    is_base_image = fields.Boolean("Is Base Image?")
    is_small_image = fields.Boolean("Is Small Image?")
    is_thumbnail = fields.Boolean("Is Thumbnail?")
    is_swatch_image = fields.Boolean("Is Swatch Image?")
    name=fields.Char(string='Name',help="File name")
    label=fields.Char(string='Image label',translate=True,size=64,help="")
    extension=fields.Char(string='File extension',readonly=True,oldname='extention')
    link=fields.Boolean(string='Link?', help="Images can be linked from files on "
                        "your file system or remote (Preferred)",default=False)
    file_db_store=fields.Binary(string='Image stored in database')
    file=fields.Binary(compute='_get_image',string="File",filters='*.png,*.jpg,*.gif')
    url=fields.Char(string='File Location',help="URL")
    comments=fields.Text(string='Comments')
    sequence=fields.Integer(string='Sequence',help="The sequence number will use this to order the product images")
    #_order = "sequence"
    
    @api.model
    def create(self,vals):
        if vals.get('name') and not vals.get('extension'):
            name, extension = os.path.splitext(vals['name'])
            if not extension :
                raise ValueError('Please select proper image or name with extension')
            vals['name'] = name
            vals['extension'] = extension
            vals['name'] = re.sub(r'[?%*:|\"<>]','', vals['name'])
            vals['name'] = re.sub(r'[- ()]','_', vals['name'])
            vals['label'] = vals['name'].replace('_', ' ').capitalize()
        res = super(MagentoProductImage,self).create(vals)
        product = res.magento_product_id
        images = product.magento_product_image_ids - res       
        for image in images :
            types = {}
            if image.is_base_image and res.is_base_image:
                types.update({'is_base_image':False})
            if image.is_small_image and res.is_small_image :
                types.update({'is_small_image':False})
            if image.is_thumbnail and res.is_thumbnail :
                types.update({'is_thumbnail':False})
            if image.is_swatch_image and res.is_swatch_image :
                types.update({'is_swatch_image':False}) 
            if types :
                image.write(types)    
        return res 
    
    @api.multi
    def write(self,vals):
        if vals.get('name') and not vals.get('extension'):
            name, extension = os.path.splitext(vals['name'])
            if not extension :
                raise ValueError('Please select proper image or name with extension')
            vals['name'] = name
            vals['extension'] = extension
            vals['name'] = re.sub(r'[?%*:|\"<>]','', vals['name'])
            vals['name'] = re.sub(r'[- ()]','_', vals['name'])
            vals['label'] = vals['name'].replace('_', ' ').capitalize()
        if vals.get('is_base_image') or vals.get('is_small_image') or vals.get('is_thumbnail') or vals.get('is_swatch_image') :
            for magento_image in self :
                product = magento_image.magento_product_id
                images = product.magento_product_image_ids - magento_image
                for image in images :
                    types = {}
                    if image.is_base_image and vals.get('is_base_image'):
                        types.update({'is_base_image':False})
                    if image.is_small_image and vals.get('is_small_image') :
                        types.update({'is_small_image':False})
                    if image.is_thumbnail and vals.get('is_thumbnail'):
                        types.update({'is_thumbnail':False})
                    if image.is_swatch_image and vals.get('is_swatch_image'):
                        types.update({'is_swatch_image':False})
                    if types :
                        image.write(types)
        return super(MagentoProductImage,self).write(vals)    
    
    @api.multi
    def unlink(self):
        session = ConnectorSession(self.env.cr, self.env.uid,self.env.context)
        if self.backend_id.image_delete_on_magento:
            env = get_environment(session, 'magento.product.image', self.backend_id.id)
            image_deleter = env.get_connector_unit(ProductImageAdapter)
            image_deleter.delete(self.magento_id,self.magento_product_id.magento_sku)
        res = super(MagentoProductImage, self).unlink()
        return res
    @api.multi
    def _get_backend(self):
        backend_id = False
        backend_m = self.env['magento.backend']
        back_obj = backend_m.search([])[0]
        if back_obj:
            backend_id = back_obj.id           
        return backend_id


    _defaults = {
        'backend_id': _get_backend,
    }
    
@magento
class ProductImageDeleter(MagentoDeleter):
    _model_name = ['magento.product.image']


@magento
class ProductImageExporter(MagentoExporter):
    _model_name = ['magento.product.image']

    def _should_import(self):
        "Images in magento doesn't retrieve infos on dates"
        return False
    
    def _has_to_skip(self):
        image_type = mimetypes.guess_type(self.binding_record.name + self.binding_record.extension)[0]
        if not image_type:
            raise NothingToDoJob('Image type snot supported')
    def _export_dependencies(self):
        self._export_dependency(self.binding_record.magento_product_id,'magento.product.product')
        
    def _update(self, data):
        """ Update an Magento record """
        assert self.magento_id
        # special check on data before export
        self._validate_update_data(data)
#         if 'content' in data :
#             data = {'id':self.magento_id,
#                     'sku':data.get('product')}
#             self.backend_adapter.delete(data)
#             map_record = self._map_data()
#             record = self._create_data(map_record, fields=None)
#             if not record:
#                 return _('Nothing to export.')
#             self.magento_id = self._create(record)
#         else :
        self.backend_adapter.write(self.magento_id, data)

@magento
class MagentoImageImporter(MagentoImporter):
    """ Import images for a record.

    Usually called from importers, in ``_after_import``.
    For instance from the products importer.
    """

    _model_name = ['magento.product.image',
                   ]
    
    def _get_magento_data(self):
        """ Return the raw Magento data for ``self.magento_id`` """
        return self.backend_adapter.read(self.magento_id,self.sku)

#     def run(self, magento_id, binding_id):
#         return True
    def run(self, magento_id, magento_product, file_name=False,force=False,image_data=None):
        """ Run the synchronization

        :param magento_id: identifier of the record on Magento
        """
        self.magento_id = magento_id # pass this
        self.file_name=file_name
        #self.product_erp_id = magento_product.erp_id.id
        if magento_product._name == 'magento.product.template' :
            self.magento_tmpl_id = magento_product.id
            self.magento_product_id = False
        else :
            self.magento_product_id = magento_product.id
            self.magento_tmpl_id = False
        self.sku = magento_product.magento_sku
        try:
            if image_data :
                self.magento_record = image_data
            else :
                self.magento_record = self._get_magento_data()
        except IDMissingInBackend:
            return _('Record does no longer exist in Magento')
        
        binding_id = self._get_binding()

        if not force and self._is_uptodate(binding_id):
            return _('Already up-to-date.')               

        map_record = self._map_data()
        if binding_id:
            record = self._update_data(map_record,magento_product_id=self.magento_product_id,magento_tmpl_id=self.magento_tmpl_id)                       
            self._update(binding_id, record)
        else:
            record = self._create_data(map_record,magento_product_id=self.magento_product_id,magento_tmpl_id=self.magento_tmpl_id)
            binding_id = self._create(record)

        self.binder.bind(self.magento_id, binding_id)

        return binding_id


# Added by krishna
@magento
class ProductImageImportMapper(ImportMapper):
    _model_name = ['magento.product.image']

    direct = [
            ('label', 'label'),
            ('position', 'sequence'),
            ('url','url'),
            ('file','name'),
                        
        ]
    @mapping
    def link(self, record):        
        return {'link': True}
    
    @mapping
    def backend_id(self, record):
        #print self.backend_record.id
        return {'backend_id': self.backend_record.id}
    
    @mapping
    def types(self,record):
        types = {}
        for type in record.get('types') :
            if 'image' == type :
                types.update({'is_base_image':True})
            if 'small_image' == type :
                types.update({'is_small_image':True})
            if 'swatch_image' == type :
                types.update({'is_swatch_image':True})
            if 'thumbnail' == type :
                types.update({'is_thumbnail':True})
        if types :
            return types
        
    @mapping
    def product(self,record):
        return {'magento_product_id':self.options.magento_product_id,
                'magento_tmpl_id' : self.options.magento_tmpl_id}
     
@magento
class ProductImageExportMapper(ExportMapper):
    _model_name = ['magento.product.image']

    direct = [
            ('label', 'label'),
        ]
 
    @mapping
    def media_type(self,record):
        return {'mediaType':'image'}
    
    @mapping
    def position(self,record):
        return {'position':int(record.sequence)}
        
    @mapping
    def product(self, record):
        product = record.magento_product_id.magento_sku
#         if not product :
#             product = record.magento_product_id.erp_id.default_code 
        return {'product': product}

    @changed_by('is_base_image','is_small_image','is_swatch_image','is_thumbnail')
    @mapping
    def types(self, record):
        types = []
        if record.is_base_image :
            types.append('image')
        if record.is_small_image :
            types.append('small_image')
        if record.is_thumbnail :
            types.append('thumbnail')
        if record.is_swatch_image :
            types.append('swatch_image')
        return {'types':types}
    
    @changed_by('name','extension')
    @mapping
    def file(self, record):
        if True: 
            return {
                    'content': {
                                    'base64_encoded_data':record.get_image().decode('ascii'),
                                    'name':record.name+record.extension,
                                    'type':mimetypes.guess_type(record.name + record.extension)[0],
                                 }
                    }
        
    @mapping
    def disabled(self,record):
        return {'disabled':0}


@magento
class ProductImageAdapter(GenericAdapter):
    _model_name = ['magento.product.image']
    _magento_model = 'catalog_product_attribute_media'
    _path = '/V1/products/{sku}/media'

    def create(self, data, storeview_id=None):
        sku = data.pop('product')
        sku = urllib.parse.quote(sku)
        if not sku: 
            raise FailedJobError("SKU not found for product image.")
        path = self._path.format(sku=sku)
        data = {
                'entry':data
                }
        try :
            res = req(self.backend_record,path,method="POST",data=data)
        except HTTPError as err:
            response = err.response
            if response.get('status_code') == 400 :
                raise NothingToDoJob('Product Image is not exported : ' + response.get('message'))
        if isinstance(res,str):
            """If media gallery entry created and return ID if id not found then raise exception"""
            return res
        else :
            raise FailedJobError("%s"%res)
        

    def write(self, id, data):
        """ Update records on the external system """
        sku = data.pop('product')
        sku = urllib.parse.quote(sku)
        if not sku: 
            raise FailedJobError("SKU not found for product image.")
        url = str(self._path).format(sku=sku)
        data.update({'id':id})
        data = {
                'entry':data
                }
        data.update({'url':url})
        try:
            res = super(ProductImageAdapter,self).write(id,data)
        except HTTPError as err:
            response = err.response
            if response.get('status_code') == 400 :
                raise NothingToDoJob('Product Image is not exported : ' + response.get('message'))
        return res

    def delete(self, id,sku):
        """ Delete a record on the external system """
        if not sku: 
            raise FailedJobError("SKU not found for product image.")
        if not id:
            raise FailedJobError("External ID not found for product image.")
        url = str(self._path).format(sku=sku)
        data = {'url':url}
        res = super(ProductImageAdapter,self).delete(id,data)
        if res and isinstance(res,bool):
            return res
        else :
            raise FailedJobError("Product image not deleted in external system : %s"%res)
    
    def search(self, id, storeview_id=None):
        """ Returns the information of a record

        :rtype: dict
        """
        return self._call('product_media.list', [int(id), storeview_id, 'id'])

    def read(self, id, sku,storeview_id=None):
        sku = urllib.parse.quote(sku)
        if not sku :
            raise FailedJobError("SKU not found for product image.")
        url = str(self._path+"/{id}").format(sku=sku,id=id)
        res = req(self.backend_record,url,method="GET")
        return res


class MagentoProductProduct(models.Model):
    _inherit = 'magento.product.product'

    @api.multi
    def _get_images(self):
        res={}
        for prd in self:
            imgs = self.env['magento.product.image'].search([
                    ('magento_product_id', '=', prd.id),
                    ('backend_id', '=', prd.backend_id.id), ])
            img_ids=[x.id for x in imgs]
            res[prd.id] = img_ids
        return res

    @api.multi
    def copy(self, default=None):
        #take care about duplicate on one2many and function fields
        #https://bugs.launchpad.net/openobject-server/+bug/705364
        if default is None:
            default = {}
        default['magento_product_image_ids'] = None
        return super(MagentoProductProduct, self).copy(default=default)
    
    
    magento_product_image_ids = fields.One2many('magento.product.image','magento_product_id',            
                                              string='Magento product images')
    #magento_product_storeview_ids=fields.One2many('magento.product.storeview',
    #                                          'magento_product_id',
    #                                              string='Magento storeview')
    
    @api.multi
    def open_images(self):
        view_id = self.env['ir.model.data'].get_object_reference('odoo_magento2_ept',
                                                                 'magento_product_img_form_view')[1]
        return {
            'name': 'Product images',
            'view_type': 'form',
            'view_mode': 'form',
            'view_id': view_id,
            'res_model': self._name,
            'context': self._context,
            'type': 'ir.actions.act_window',
            'res_id': self.ids and self.ids[0] or False,
        }



