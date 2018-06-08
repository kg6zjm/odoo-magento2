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

import socket
import logging
#import xmlrpclib

from odoo.addons.odoo_magento2_ept.models.backend.exception import (NetworkRetryableError,
                                                RetryableJobError)
from odoo.addons.odoo_magento2_ept.models.api_request import req
from odoo.addons.odoo_magento2_ept.models.search_criteria import create_search_criteria
from odoo.addons.odoo_magento2_ept.models.backend.connector import ConnectorUnit
from odoo.addons.odoo_magento2_ept.python_library.php import Php
from datetime import datetime
_logger = logging.getLogger(__name__)


#Magento 2 date format
MAGENTO_DATETIME_FORMAT ='%Y-%m-%d %H:%M:%S'


recorder = {}


def call_to_key(method, arguments):
    """ Used to 'freeze' the method and arguments of a call to Magento
    so they can be hashable; they will be stored in a dict.

    Used in both the recorder and the tests.
    """
    def freeze(arg):
        if isinstance(arg, dict):
            items = dict((key, freeze(value)) for key, value
                         in arg.items())
            return frozenset(items.items())
        elif isinstance(arg, list):
            return tuple([freeze(item) for item in arg])
        else:
            return arg

    new_args = []
    for arg in arguments:
        new_args.append(freeze(arg))
    return (method, tuple(new_args))


def record(method, arguments, result):
    """ Utility function which can be used to record test data
    during synchronisations. Call it from MagentoCRUDAdapter._call

    Then ``output_recorder`` can be used to write the data recorded
    to a file.
    """
    recorder[call_to_key(method, arguments)] = result


def output_recorder(filename):
    import pprint
    with open(filename, 'w') as f:
        pprint.pprint(recorder, f)
    _logger.debug('recorder written to file %s', filename)


class BackendAdapter(ConnectorUnit):
    """ Base Backend Adapter for the connectors """

    _model_name = None  # define in sub-classes


class CRUDAdapter(BackendAdapter):
    """ Base External Adapter specialized in the handling
    of records on external systems.

    Subclasses can implement their own implementation for
    the methods.
    """

    _model_name = None

    def search(self, *args, **kwargs):
        """ Search records according to some criterias
        and returns a list of ids """
        raise NotImplementedError

    def read(self, *args, **kwargs):
        """ Returns the information of a record """
        raise NotImplementedError

    def search_read(self, *args, **kwargs):
        """ Search records according to some criterias
        and returns their information"""
        raise NotImplementedError

    def create(self, *args, **kwargs):
        """ Create a record on the external system """
        raise NotImplementedError

    def write(self, *args, **kwargs):
        """ Update records on the external system """
        raise NotImplementedError

    def delete(self, *args, **kwargs):
        """ Delete a record on the external system """
        raise NotImplementedError

class GenericAdapter(CRUDAdapter):

    _model_name = None
    _magento_model = None
    _admin_path = None
    _path = None

    def search(self, filters=None,params=None):
        """ Search records according to some criterias
        and returns a list of ids

        :rtype: list
        """
        
        queystring = False
        if filters :
            url = filters.get('url',False) and filters.pop('url') or self._path
            #Date : 14-sep-2017
            #If pagesize and currenpage is parameter are given in filters then search 
            #Customers with pagesize and currentPage
            page_size = filters.get('pageSize') and filters.pop('pageSize',None) or 0
            currentPage = filters.get('currentPage') and filters.pop('currentPage',None) or 0
            #First Prepare searchCriteria dictionary and then add pagesize and currentpage in that.
            filters = create_search_criteria(filters)
            if page_size and currentPage and filters.get('searchCriteria'):
                filters['searchCriteria'].update({'currentPage':currentPage,'pageSize':page_size})
            
            #prepare query string from filters 
            queystring = Php.http_build_query(filters)
            url = queystring and "%s?%s"%(url,queystring) or url
        else :
            url = self._path
        result = []
        content = req(self.backend_record,url,params=params)
        if isinstance(content, list) and len(content) > 0 and ('id' in content[0].keys()):
            for record in content:
                result.append(record['id'])
            return result
        if 'items' in content :
            if len(content['items']) == 0 :
                return result
            if 'id' in content['items'][0] :
                for record in content.get('items'):
                    result.append(record['id'])
                return result
                
        """
        if content.get('items') and len(content.get('items')) == 0:
                return result
        if content.get('items',False) :
            if content['items'][0].has_key('id') :
                for record in content.get('items'):
                    result.append(record['id'])
                return result
        """
        return content

    def read(self, id, attributes=None):
        """ Returns the information of a record

        :rtype: dict
        """
        content = req(self.backend_record,self._path+"/%s"%(id))
        return content    

    def search_read(self, filters=None):
        """ Search records according to some criterias
        and returns their information"""
        
        queystring = False
        if filters :
            url = filters.get('url',False) and filters.pop('url') or self._path
            filters = create_search_criteria(filters)
            queystring = Php.http_build_query(filters)
            url = queystring and "%s?%s"%(url,queystring) or url
        else :
            url = self._path
        content = req(self.backend_record,url)
        result = content.get('items',False) or content
        return result

    def create(self, data):
        """ Create a record on the external system """
        
        url = data.get('url',False) and data.pop('url') or self._path
        content = req(self.backend_record,url,method="POST",data=data)     
        return content

    def write(self, id, data):
        """ Update records on the external system """
        url = data.get('url',False) and data.pop('url') or self._path
        url = "%s/%s"%(url,id)
        content = req(self.backend_record,url,method="PUT",data=data)
        return content

    def delete(self, id,data=None):
        """ Delete a record on the external system """
        url = data and data.get('url',False) or self._path
        url = "%s/%s"%(url,id)
        content = req(self.backend_record,url,method='DELETE')
        return content
    '''
    def admin_url(self, id):
        """ Return the URL in the Magento admin for a record """
        if self._admin_path is None:
            raise ValueError('No admin path is defined for this record')
        backend = self.backend_record
        url = backend.admin_location
        if not url:
            raise ValueError('No admin URL configured on the backend.')
        path = self._admin_path.format(model=self._magento_model,
                                       id=id)
        url = url.rstrip('/')
        path = path.lstrip('/')
        url = '/'.join((url, path))
        return url
    '''