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

from odoo import models, fields,api
from odoo.addons.odoo_magento2_ept.models.unit.mapper import (mapping,
                                                  only_create,
                                                  ImportMapper
                                                  )
from odoo.addons.odoo_magento2_ept.models.unit.backend_adapter import GenericAdapter
from odoo.addons.odoo_magento2_ept.models.backend.session import ConnectorSession
from odoo.addons.odoo_magento2_ept.models.unit.import_synchronizer import (DelayedBatchImporter,import_batch)
from odoo.addons.odoo_magento2_ept.models.backend.backend import magento
from odoo.addons.odoo_magento2_ept.models.search_criteria import create_search_criteria
from odoo.addons.odoo_magento2_ept.models.api_request import req


class ResPartnerCategory(models.Model):
    _inherit = 'res.partner.category'

    magento_bind_ids = fields.One2many(
        comodel_name='magento.res.partner.category',
        inverse_name='erp_id',
        string='Magento Customer Group',
        readonly=True,
    )


class MagentoResPartnerCategory(models.Model):
    _name = 'magento.res.partner.category'
    _inherit = 'magento.binding'
    _inherits = {'res.partner.category': 'erp_id'}

    erp_id = fields.Many2one(comodel_name='res.partner.category',
                                 string='Partner Category',
                                 required=True,
                                 ondelete='cascade')
    # TODO : replace by a m2o when tax class will be implemented
    tax_class_id = fields.Integer(string='Tax Class ID')
    
    @api.multi
    def import_customer_group(self,backends):
        session = ConnectorSession(self.env.cr, self.env.uid,context=self.env.context)
        for backend in backends:
            backend.check_magento_structure()
            import_batch.delay(session, 'magento.res.partner.category',backend.id)
        return True

@magento
class PartnerCategoryAdapter(GenericAdapter):
    _model_name = ['magento.res.partner.category']
    _magento_model = 'ol_customer_groups'
    _admin_path = '/customer_group/edit/id/{id}'
    _path = "/V1/customerGroups"

    def search(self, filters=None):
        """ Search records according to some criterias
        and returns a list of ids

        :rtype: list
        """
        if filters is None :
            filters = {}
        filters['url']= "%s/search"%(self._path)
           
        result = []
        result = super(PartnerCategoryAdapter,self).search(filters)
         
        return result

        
@magento
class PartnerCategoryBatchImporter(DelayedBatchImporter):
    """ Delay import of the records """
    _model_name = ['magento.res.partner.category']


PartnerCategoryBatchImport = PartnerCategoryBatchImporter  # deprecated


@magento
class PartnerCategoryImportMapper(ImportMapper):
    _model_name = ['magento.res.partner.category']

    direct = [
        ('code', 'name'),
        ('tax_class_id', 'tax_class_id'),
    ]

    @mapping
    def magento_id(self, record):
        return {'magento_id': record['id']}

    @mapping
    def backend_id(self, record):
        return {'backend_id': self.backend_record.id}

    @only_create
    @mapping
    def erp_id(self, record):
        """ Will bind the category on a existing one with the same name."""
        existing = self.env['res.partner.category'].search(
            [('name', '=', record['code'])],
            limit=1,
        )
        if existing:
            return {'erp_id': existing.id}
