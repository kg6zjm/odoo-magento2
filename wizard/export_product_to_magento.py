from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import datetime
from odoo.addons.odoo_magento2_ept.models.backend.session import ConnectorSession
from odoo.addons.odoo_magento2_ept.models.backend.event import on_export_product_to_magento

class export_multi_products(models.TransientModel):
    _name = 'export.magento.products'
    _description = 'Wizard to export products to magento'

    @api.multi
    def export(self):
        context=self.env.context or {}
        
        res = False
        if context.get('active_ids'):
            res = context['active_ids']
        model = context.get('active_model')
        products = self.env[model].browse(res)
        for product in products:
            if product.product_type == 'configurable':
                for child in product.magento_product_ids:
                    if not child.magento_sku:
                        raise ValidationError("Sku is not set for the variant of %s"%child.name)
                    if not child.attribute_set_id :
                        raise ValidationError("Attribute set is not selected for %s"%child.name)
            if not product.magento_sku:
                raise ValidationError("Sku is not set for %s"%product.name)
            if not product.attribute_set_id:
                raise ValidationError("Attribute set is not set for %s"%product.name)
            
        session = ConnectorSession(self.env.cr, self.env.uid,
                                       context=self.env.context)

        for record_id in res:
            on_export_product_to_magento.fire(session, model, record_id)
    
