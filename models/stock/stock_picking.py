# -*- coding: utf-8 -*-
##############################################################################
#
#    Author: Joël Grand-Guillaume
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
from xmlrpc import client as xmlrpclib
from odoo import models, fields,api
from odoo.tools.translate import _
from odoo.addons.odoo_magento2_ept.models.logs.job import job, related_action,unwrap_binding
from odoo.addons.odoo_magento2_ept.models.backend.exception import (NothingToDoJob,FailedJobError)
from odoo.addons.odoo_magento2_ept.models.unit.synchronizer import Exporter
from odoo.addons.odoo_magento2_ept.models.backend.exception import IDMissingInBackend
from odoo.addons.odoo_magento2_ept.models.unit.backend_adapter import GenericAdapter
from odoo.addons.odoo_magento2_ept.models.backend.connector import get_environment
from odoo.addons.odoo_magento2_ept.models.backend.backend import magento
#from .related_action import unwrap_binding
from odoo.addons.odoo_magento2_ept.models.backend.session import ConnectorSession
from odoo.addons.odoo_magento2_ept.models.api_request import req
from odoo.addons.odoo_magento2_ept.models.search_criteria import create_search_criteria
from odoo.addons.odoo_magento2_ept.python_library.php import Php
_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = 'stock.picking'
    
    @api.one
    @api.depends("group_id")
    def calc_magento_picking(self):
        if self.picking_type_id and self.picking_type_id.code=='outgoing' and self.group_id:
            sale_order = self.env['sale.order'].search([('procurement_group_id', '=', self.group_id.id)])
            magento_order=sale_order and self.env['magento.sale.order'].search([('erp_id','=',sale_order.id)])
            if magento_order:
                self.is_magento_picking=True
            else:
                self.is_magento_picking=False    
    

    @api.multi
    @api.depends("sale_id")
    def _set_magento_info(self):
        for record in self :
            if record.sale_id.magento_bind_ids :
                record.website_id = record.sale_id.website_id
                record.store_id = record.sale_id.store_id
                record.storeview_id = record.sale_id.storeview_id     
                
    is_magento_picking = fields.Boolean('Is Magento Picking',compute='calc_magento_picking',store=True)
    
    magento_order_id = fields.Many2one(comodel_name='magento.sale.order',
                                       string='Sale Order',
                                       ondelete='set null')
    
    magento_workflow_process_id = fields.Many2one(comodel_name='magento.sale.workflow.process',
                                          string='Sale Workflow Process')
    
    related_backorder_ids = fields.One2many(
        comodel_name='stock.picking',
        inverse_name='backorder_id',
        string="Related backorders",
    )
    
    website_id = fields.Many2one(compute="_set_magento_info",comodel_name="magento.website", store=True,readonly=True,string="Website")
    store_id = fields.Many2one(compute="_set_magento_info", comodel_name="magento.store", store=True,readonly=True,string="Store")
    storeview_id = fields.Many2one(compute="_set_magento_info", comodel_name="magento.storeview", store=True,readonly=True,string="Storeview")
    magento_order_status = fields.Char(related='sale_id.magento_order_status',string="Magento Order Status",readonly=True)
    is_exported_to_magento = fields.Boolean("Is exported to Magento")
    backend_id = fields.Many2one('magento.backend',string="Instance")
    magento_id = fields.Char("Magento Id")
    @api.multi
    def write(self, vals):
        res = super(StockPicking, self).write(vals)
        return res
    
    @api.multi
    def action_done(self):
        # The key in the context avoid the event to be fired in
        # StockMove.action_done(). Allow to handle the partial pickings
        self_context = self.with_context(__no_on_event_out_done=True)
        result = super(StockPicking, self_context).action_done()
        return result
    
    @api.multi
    def export_shipment_to_magento(self,backends):
        session = ConnectorSession(self.env.cr, self.env.uid,context=self.env.context)
        pickings = self.search([('is_magento_picking','=',True),('is_exported_to_magento','=',False),('state','in',['done']),('backend_id','in',backends.ids)])
        for picking in pickings:
            if picking.picking_type_id.code != 'outgoing':
                continue
            export_picking_done.delay(session,'stock.picking',picking.id)

    
    @api.multi
    def validate_picking(self):
        self.force_assign()
        self.action_done()
        return True
    
    
    @api.multi
    def view_magento_stock_picking(self):
        magento_picking_ids = self.mapped('magento_bind_ids')
        xmlid=('odoo_magento2_ept','action_magento_stock_picking')
        action = self.env['ir.actions.act_window'].for_xml_id(*xmlid)
        action['domain']= "[('id','in',%s)]" % magento_picking_ids.ids
        if not magento_picking_ids : 
            return {'type': 'ir.actions.act_window_close'}
        return action
    
    @api.multi
    def get_magento_order_status(self):
        for picking in self:
            if picking.sale_id :
                picking.sale_id.get_magento_order_status()


@magento
class StockPickingAdapter(GenericAdapter):
    _model_name = ['stock.picking']
    _magento_model = 'sales_order_shipment'
    _admin_path = 'sales_shipment/view/shipment_id/{id}'
    _path = "/V1/shipment"
    
    def search(self,filters=None):       
        filters['url']="%ss"%(self._path)
        result = []
        content = super(StockPickingAdapter,self).search(filters)
        if isinstance(content,list) and len(content) == 0 :
            return content
        for record in content.get('items') :
            result.append(record['entity_id'])
        return result   
    
    def create(self, order_id, items, comment, picking ,email, include_comment):
        """ Create a record on the external system """
        order_item = []
        if items :
            for item_id,qty in items.items() :
                item={}
                item.setdefault("orderItemId",item_id)
                item.setdefault("qty",qty)
                order_item.append(item)
        else :
            order_item.append(items)
        
        track_numbers = self.add_tracking_number(picking)
        values = {"entity":{"orderId":order_id,
                            "items":order_item,
                            "tracks" : track_numbers or []
                            }}
       
        values['url']="%s/"%self._path
        result = super(StockPickingAdapter,self).create(values)
        magento_id = result.get('entity_id')
        
        if not magento_id : 
            filters = {'order_id':order_id}
            filters = create_search_criteria(filters)
                    
            qs = Php.http_build_query(filters)
            url = "%ss?%s"%(self._path,qs)
        
            result = []
            content = req(self.backend_record,url)
            shipments = content.get('items',False)
            if shipments : 
                if len(shipments) == 1 :
                    magento_id = shipments[0]['entity_id']   
                else :
                    shipment_dates = {}
                    for shipment in shipments :
                        shipment_dates.setdefault(shipment['entity_id'],shipment['created_at'])
                    latest_date = max(shipment_dates.values())
                    for shipment in shipment_dates:
                        if latest_date == shipment_dates[shipment] :
                            magento_id = shipment
                            break
                    
        return magento_id    
    
    def add_tracking_number(self, picking):
        """ Add new tracking number.

        :param magento_id: shipment increment id
        :param carrier_code: code of the carrier on Magento
        :param tracking_title: title displayed on Magento for the tracking
        :param tracking_number: tracking number
        """
        tracking_numbers = []
        package_ids = picking.package_ids
        if package_ids : 
            for package in package_ids:
                track = {
                        'orderId' : picking.sale_id.magento_bind_ids[0].magento_id,
                        'carrierCode' : picking.carrier_id.magento_carrier_code or '',
                        'title' : picking.carrier_id.magento_carrier.magento_carrier_title or '',
                        'trackNumber' : package.name,
                    }
                tracking_numbers.append(track)
        else :
            if picking.carrier_tracking_ref :
                track = {
                            'orderId' : picking.sale_id.magento_bind_ids[0].magento_id,
                            'carrierCode' : picking.carrier_id.magento_carrier_code or '',
                            'title' : picking.carrier_id.magento_carrier.magento_carrier_title or '',
                            'trackNumber' : picking.carrier_tracking_ref or '',
                        }
                tracking_numbers.append(track)
        return tracking_numbers
@magento
class MagentoPickingExporter(Exporter):
    _model_name = ['stock.picking']

    def _get_args(self, picking, lines_info=None):
        if lines_info is None:
            lines_info = {}
        sale_binder = self.binder_for('magento.sale.order')
        magento_sale_id = sale_binder.to_backend(picking.sale_id.magento_bind_ids[0].id)
        mail_notification = self._get_picking_mail_option(picking)
        return (magento_sale_id, lines_info,
                _("Shipping Created"), picking , mail_notification, True)

    def _get_lines_info(self, picking):
        """
        Get the line to export to Magento. In case some lines doesn't have a
        matching on Magento, we ignore them. This allow to add lines manually.

        :param picking: picking is a record of a stock.picking
        :type picking: browse_record
        :return: dict of {magento_product_id: quantity}
        :rtype: dict
        """
        item_qty = {}
        # get product and quantities to ship from the picking
        for line in picking.move_lines:
            sale_line = line.sale_line_id
            if not sale_line.magento_bind_ids:
                continue
            magento_sale_line = next(
                (line for line in sale_line.magento_bind_ids
                 if line.backend_id.id == picking.backend_id.id),
                None
            )
            if not magento_sale_line:
                continue
            item_id = magento_sale_line.magento_id
            item_qty.setdefault(item_id, 0)
            item_qty[item_id] += line.product_qty
        return item_qty

    def _get_picking_mail_option(self, picking):
        """

        :param picking: picking is an instance of a stock.picking browse record
        :type picking: browse_record
        :returns: value of send_picking_done_mail chosen on magento shop
        :rtype: boolean
        """
        magento_shop = picking.sale_id.magento_bind_ids[0].store_id
        return magento_shop.send_picking_done_mail

    def run(self, binding_id):
        """
        Export the picking to Magento
        """
        picking = self.model.browse(binding_id)
#         if picking.magento_id:
#             return _('Already exported')
        lines_info = self._get_lines_info(picking)
        args = self._get_args(picking, lines_info)
        try:
            magento_id = self.backend_adapter.create(*args)
        except xmlrpclib.Fault as err:
            if err.faultCode == 102:
                raise NothingToDoJob('Canceled: the delivery order already '
                                     'exists on Magento (fault 102).')
            else:
                raise
        else:
            picking.write({'magento_id' : magento_id,'is_exported_to_magento' : True})
            self.session.commit()
        return "Shipment is exported with Magento ID %s"%(magento_id)


MagentoPickingExport = MagentoPickingExporter  # deprecated

@job(default_channel='root.magento')
@related_action(action=unwrap_binding)
def export_picking_done(session, model_name, record_id):
    """ Export a complete or partial delivery order. """
    # with_tracking is True to keep a backward compatibility (jobs that
    # are pending and miss this argument will behave the same, but
    # it should be called with True only if the carrier_tracking_ref
    # is True when the job is created.
    picking = session.env[model_name].browse(record_id)
    backend_id = picking.backend_id.id
    env = get_environment(session, model_name, backend_id)
    picking_exporter = env.get_connector_unit(MagentoPickingExporter)
    res = picking_exporter.run(record_id)
#     if picking.erp_id and picking.erp_id.sale_id :
#         picking.erp_id.sale_id.get_magento_order_status()
    return res
