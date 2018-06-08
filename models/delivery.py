from odoo import models, fields, api


class magento_delivery_carrier(models.Model):
    _name = 'magento.delivery.carrier'
    _rec_name = 'carrier_code'
    
    backend_id = fields.Many2one('magento.backend',string="Instance")
    carrier_label = fields.Char("Carrier Label")
    carrier_code = fields.Char("Carrier Code")
    magento_carrier_title = fields.Char("Magento Carrier Title")
    
    _sql_constraints = [
        ('unique_payment_method_code','unique(backend_id,carrier_code)',
         'This delivery carrier code is already exists')]

# TODO magento.delivery.carrier & move specific stuff
class DeliveryCarrier(models.Model):
    _inherit = "delivery.carrier"
    
    magento_carrier = fields.Many2one('magento.delivery.carrier',string="Magento Carrier")
    magento_carrier_code = fields.Char(compute='_compute_carrier_code',string='Base Carrier Code',)
    
    @api.depends('magento_carrier.carrier_code')
    def _compute_carrier_code(self):
        for carrier in self:
            if carrier.magento_carrier.carrier_code:
                self.magento_carrier_code = carrier.magento_carrier.carrier_code.split('_')[0]
        