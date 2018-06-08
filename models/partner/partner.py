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
from xmlrpc import client
from collections import namedtuple
from odoo import models, fields, api, tools
from odoo.addons.odoo_magento2_ept.models.logs.job import job
from odoo.addons.odoo_magento2_ept.models.backend.connector import (ConnectorUnit,
                                                                    get_environment)
from odoo.addons.odoo_magento2_ept.models.backend.exception import (MappingError,
                                                                   IDMissingInBackend)
from odoo.addons.odoo_magento2_ept.models.unit.mapper import (mapping,
                                                  only_create,
                                                  ImportMapper,
                                                  )

from odoo.addons.odoo_magento2_ept.models.unit.backend_adapter import (BackendAdapter,
                                                                      GenericAdapter,
                                   MAGENTO_DATETIME_FORMAT,
                                   )
from odoo.addons.odoo_magento2_ept.models.unit.import_synchronizer import (DelayedBatchImporter,
                                       MagentoImporter,
                                       )
from odoo.addons.odoo_magento2_ept.models.backend.backend import magento
from odoo.addons.odoo_magento2_ept.models.api_request import req
from odoo.addons.odoo_magento2_ept.models.search_criteria import create_search_criteria
from datetime import datetime

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = 'res.partner'

    backend_id = fields.Many2one('magento.backend',string="Instance")
    magento_id = fields.Char("Magento Id")
    website_id = fields.Many2one("magento.website",string="Website")
    guest_customer = fields.Boolean(string='Guest Customer')
    address_id = fields.Char("address_id")
    
    @api.multi
    def import_magento_partners(self,backends):
        for backend in backends:
            backend.check_magento_structure()
            for website in backend.website_ids:
                website.import_partners()
            backend.write({'last_partner_import_date' : datetime.now()})
        return True
        
#     @api.multi
#     def write(self,vals):
#         if vals.get('type'): 
#             vals['image'] = self._get_default_image(vals.get('type'), vals.get('is_company'),self.parent_id)
#         return super(ResPartner,self).write(vals)
@magento
class PartnerAdapter(GenericAdapter):
    _model_name = 'res.partner'
    _magento_model = 'customer'
    _admin_path = '/{model}/edit/id/{id}'
    _path = "/V1/customers"

    
    def search(self, filters=None, from_date=None, to_date=None,
               magento_website_ids=None):
        """ Search records according to some criteria and return a
        list of ids

        :rtype: list
        """
        dt_fmt = MAGENTO_DATETIME_FORMAT
                
        if from_date is not None:
            # updated_at include the created records
            filters.setdefault('updated_at', {})
            filters['updated_at']['from'] = from_date.strftime(dt_fmt)
        if to_date is not None:
            filters.setdefault('updated_at', {})
            filters['updated_at']['to'] = to_date.strftime(dt_fmt)
        if magento_website_ids is not None:
            filters['website_id'] = {'in': magento_website_ids}

        filters['url']= "%s/search"%(self._path)
        result = super(PartnerAdapter,self).search(filters)
        return result
    
    
@magento
class PartnerBatchImporter(DelayedBatchImporter):
    """ Import the Magento Partners.

    For every partner in the list, a delayed job is created.
    """
    _model_name = ['res.partner']

    def run(self, filters=None):
        """ Run the synchronization """
        from_date = filters.pop('from_date', None)
        to_date = filters.pop('to_date', None)
        magento_website_ids = filters.get('magento_website_id')
        list_magento_website_ids = [filters.pop('magento_website_id')]
        #date : 14/09/2017
        #get CurrentPage from filters and pass it to search
        page_size = self.backend_record.customer_import_page_size
        current_page = filters.get('currentPage',1)
        filters.update({'pageSize':page_size,'currentPage':current_page})
        record_ids = self.backend_adapter.search(
            filters,
            from_date=from_date,
            to_date=to_date,
            magento_website_ids=list_magento_website_ids)
        _logger.info('search for magento partners %s returned %s',
                     filters, record_ids)
        for record_id in record_ids:
            self._import_record(record_id)
        
        #Date : 14-sep-2017
        #if len(record_ids) is equal to page_size then it is possible to have another records
        #so it is creating another batch for next page
        #if len(record_ids) not equal to page_size then it is less than page_size
        #so can guess it is last page.
        if len(record_ids) == page_size :
            current_page +=1
            partner_import_batch.delay(self.session, 'res.partner',
                               self.backend_record.id,
                               filters={
                                        'magento_website_id': magento_website_ids,
                                        'from_date': from_date,
                                        'to_date': to_date,
                                        'currentPage':current_page})

            


PartnerBatchImport = PartnerBatchImporter  # deprecated


@magento
class PartnerImportMapper(ImportMapper):
    _model_name = ['res.partner']

    direct = [
        ('email', 'email'),    
        ('taxvat' , 'vat')   
    ]
    
    @mapping
    def backend_id(self,record):
        return {'backend_id' :  self.backend_record.id}
        

    @mapping
    def names(self, record):
        # TODO create a glue module for base_surname
        parts = [part for part in (record['firstname'],
                                   record.get('middlename'),
                                   record['lastname']) if part]
        return {'name': ' '.join(parts)}    
    
    @mapping
    def customer_group_id(self, record):
        # import customer groups
        binder = self.binder_for(model='magento.res.partner.category')
        category_id = binder.to_openerp(record['group_id'], unwrap=True)

        if category_id is None:
            raise MappingError("The partner category with "
                               "magento id %s does not exist" %
                               record['group_id'])
        return {'category_id': [(4, category_id)]}

    @mapping
    def website_id(self, record):
        binder = self.binder_for(model='magento.website')
        website_id = binder.to_openerp(record['website_id'])
        return {'website_id': website_id}

#     @only_create
#     @mapping
#     def company_id(self, record):
#         binder = self.binder_for(model='magento.storeview')
#         storeview = binder.to_openerp(record['store_id'], browse=True)
#         if storeview:
#             company = storeview.website_id.company_id
#             if company:
#                 return {'company_id': company.id}
#         return {'company_id': False}

    @mapping
    def lang(self, record):
        binder = self.binder_for(model='magento.storeview')
        if record.get('store_id') :
            storeview = binder.to_openerp(record['store_id'], browse=True)
            if storeview:
                if storeview.lang_id:
                    return {'lang': storeview.lang_id.code}

    @mapping
    def magento_id(self,record):
        return {'magento_id' : record.get('id')}
    
    @mapping
    def type(self,record):
        return {'type' : 'other'}
@magento
class AddressImportMapper(ImportMapper):
    _model_name = ['res.partner']
    
    @mapping
    def direct_mapping(self,record):
        return {
                'zip' : record.get('postcode'),
                'city' : record.get('city'),
                'phone' : record.get('telephone')
            }
    
    @mapping
    def backend_id(self,record):
        return {'backend_id' :  self.backend_record.id}
    @mapping
    def consider_as_company(self, record):
        return {'is_company':True if record.get('company') else False}
        
    @mapping
    def names(self, record):
        parts = [part for part in (record['firstname'],
                                   record.get('middlename'),
                                   record['lastname']) if part]
        return {'name': ' '.join(parts)}

    @mapping
    def type(self, record):
        if record.get('default_billing') or record.get('address_type') == 'billing':
            address_type = 'invoice'
        elif record.get('default_shipping') or record.get('address_type') == 'shipping':
            address_type = 'delivery'
        else:
            address_type = 'other'
        return {'type': address_type}
    
    @mapping
    def state(self, record):
        if not record.get('region'):
            return
        
        if isinstance(record.get('region'),str) :
            region = record.get('region')
        else :
            region = record['region']['region']
            
        state = self.env['res.country.state'].search(
            [('name', '=ilike', region )],
            limit=1,
        )
        if state:
            return {'state_id': state.id}
    
    @mapping
    def vat_id(self,record):
        return {'vat' : record.get('vat_id')}
    
    @mapping
    def country(self, record):
        if not record.get('country_id'):
            return
        country = self.env['res.country'].search(
            [('code', '=', record['country_id'])],
            limit=1,
        )
        if country:
            return {'country_id': country.id}

    @mapping
    def street(self, record):
        streets = record['street']
        result= {}
        if streets :
            if len(streets)== 1:
                result = {'street':streets[0],'street2':False}
            elif len(streets)==2 :
                result = {'street':streets[0],'street2':streets[1]}
            elif len(streets)==3:
                result = {'street' : streets[0] + ' , ' + streets[1],'street2' : streets[2]}
            elif len(streets)==4:
                result = {'street' : streets[0] + ' , ' + streets[1],'street2' : streets[2] + ' , ' + streets[3]}
            else :
                result = {}
        return result

    @mapping
    def title(self, record):
        prefix = record.get('prefix')
        if not prefix:
            return
        title = self.env['res.partner.title'].search(
            [
             ('shortcut', '=ilike', prefix)],
            limit=1
        )
        if not title:
            title = self.env['res.partner.title'].create(
                {
                 'shortcut': prefix,
                 'name': prefix,
                 }
            )
        return {'title': title.id}

    @only_create
    @mapping
    def company_id(self, record):
        parent = self.options.parent_partner
        if parent:
            if parent.company_id:
                return {'company_id': parent.company_id.id}
            else:
                return {'company_id': False}
        return

    @mapping
    def address_id(self,record):
        return {'address_id' :  int(record.get('id') if record.get('id') else False )}

@magento
class PartnerImporter(MagentoImporter):
    _model_name = ['res.partner']

    _base_mapper = PartnerImportMapper
    
    def _get_binding(self):
        """
        We search existing partner based on magento_id , email and name of customer
        """
        #result = super(PartnerImporter,self)._get_binding()
        result = False
        record = self.magento_record
        if record:
            email = record.get('email')
            magento_id = record.get('id')
            parts = [part for part in (record['firstname'],
                                   record.get('middlename'),
                                   record['lastname']) if part]
            name = ' '.join(parts)
            result = self.env['res.partner'].search([('magento_id','=',magento_id),('backend_id','=',self.backend_record.id)])    
            if not result :
                result = self.env['res.partner'].search([('magento_id','=',magento_id),('email','=',email),('backend_id','=',self.backend_record.id)],limit=1)
            if not result :
                result = self.env['res.partner'].search([('magento_id','=',magento_id),('email','=',email),('name','ilike',name),('backend_id','=',self.backend_record.id)],limit=1)
            if not result:
                if record.get('company') :
                    result = self.env['res.partner'].search([('email','=',email),('name','ilike',record.get('company')),('backend_id','=',self.backend_record.id)],limit=1)
            if not result:
                result = self.env['res.partner'].search([('email','=',email),('name','ilike',name),('backend_id','=',self.backend_record.id)],limit=1)
            if len(result) > 1 :
                for res in result:
                    if not res.parent_id : 
                        result = res
            if result: 
                result = result[0]
        return result    

    def _import_dependencies(self):
        """ Import the dependencies for the record"""
        record = self.magento_record
        self._import_dependency(record['group_id'],
                                'magento.res.partner.category')

    def _after_import(self, partner_binding):
        """ Import the addresses 
            We create a partner based on Addresses which are found in the customer
        """
        record = self.magento_record
        parent_id = partner_binding
        addresses = record.get('addresses')
        parent_to_update = []
        for address in addresses:
            address_mapper = self.unit_for(AddressImportMapper,'res.partner')
            address_vals = address_mapper.map_record(address).values()
            address_vals.update({'website_id' : parent_id.website_id and parent_id.website_id.id,'lang' : parent_id.lang,'magento_id' : parent_id.magento_id,'email' : parent_id.email})
            is_exist_address = self.env['res.partner'].search([('address_id','=',int(address_vals.get('address_id'))),('backend_id','=',parent_id.backend_id.id)])
            if is_exist_address :
                continue
            if address_vals.get('is_company') and address_vals.get('type') == 'invoice' :
                address_vals.update({'name' : address.get('company')})
                new_partner = self.env['res.partner'].create(address_vals)
                parent_id.write({'parent_id' : new_partner.id})
                parent_id = new_partner
            else : 
                address_vals.update({'parent_id' : parent_id.id})
                new_partner = self.env['res.partner'].create(address_vals)
                parent_to_update.append(new_partner)
        for partner in parent_to_update : 
            partner.write({'parent_id' : parent_id.id})
        parent_id.write({'parent_id' : False})    
        return     
            

PartnerImport = PartnerImporter  # deprecated

@job(default_channel='root.magento')
def partner_import_batch(session, model_name, backend_id, filters=None):
    """ Prepare the import of partners modified on Magento """
    if filters is None:
        filters = {}
    assert 'magento_website_id' in filters, (
        'Missing information about Magento Website')
    env = get_environment(session, 'res.partner', backend_id)
    importer = env.get_connector_unit(PartnerBatchImporter)
    importer.run(filters=filters)
