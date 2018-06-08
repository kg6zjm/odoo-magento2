from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import datetime

class export_multi_products(models.TransientModel):
    _name = 'export.multi.products'
    _description = 'Wizard to export multiple products'
    
    @api.model
    def _get_product_ids(self):
        context=self.env.context or {}
        
        res = False
        if (context.get('active_model') == 'product.template' and context.get('active_ids')):
            res = context['active_ids']
        return res
    
    @api.model 
    def _get_product_product_ids(self):
        context=self.env.context or {}
        res = False
        if (context.get('active_model') == 'product.product' and context.get('active_ids')):
            res = context['active_ids']
        return res

    product_tmpl_ids=fields.Many2many('product.template', string='Jobs',default=_get_product_ids)   
    backend_id = fields.Many2one('magento.backend', 'Magento Instance', required=True, ondelete='restrict')
    website_m2m_ids = fields.Many2many('magento.website',string='Websites',domain="[('backend_id','=',backend_id)]")
    product_product_ids = fields.Many2many('product.product',string="Products",default=_get_product_product_ids)
    magento_attribute_set_id = fields.Many2one('magento.attribute.set',string="Attribute Set")
    
    @api.multi
    def export(self):      
        magento_product=self.env['magento.product.product']
        magento_product_template = self.env['magento.product.template']
        for wizard in self:
            for product_template in wizard.product_tmpl_ids:
                if not product_template.magento_bind_ids.id:
                    if len(product_template.product_variant_ids) > 1:
                        prodcut_type = "configurable"
                        magento_product_template = magento_product_template.create({'erp_id':product_template.id,'magento_product_name' : product_template.name,'magento_sku' : product_template.default_code,'backend_id':wizard.backend_id.id,'website_ids':[((6,0, wizard.website_m2m_ids.ids))],
                                            'created_at': datetime.now(),'updated_at':datetime.now(),'product_type':prodcut_type,'attribute_set_id' : wizard.magento_attribute_set_id.id})
                        
                        prodcut_type = 'simple'
                        if product_template.product_variant_ids:
                            for product_variant in product_template.product_variant_ids:
                                if not product_variant.default_code:
                                    raise ValidationError("Please set SKU for all variant of product %s"%product_variant.name)
                                product_type='simple'
                                product_name = product_variant.name
                                for value in product_variant.attribute_value_ids :
                                    if value.name :
                                        product_name = product_name + '-' + value.name
                                magento_product.create({'erp_id':product_variant.id,'magento_product_name' : product_name,'magento_sku' : product_variant.default_code,'backend_id':wizard.backend_id.id,'website_ids':[((6,0, wizard.website_m2m_ids.ids))],
                                        'created_at': datetime.now(),'updated_at':datetime.now(),'product_type':prodcut_type,'attribute_set_id' : wizard.magento_attribute_set_id.id,'magento_tmpl_id' : magento_product_template.id,
                                        'description' : product_variant.description , 'description_sale' : product_variant.description_sale})
                    else :
                        product_type = "simple"
                        product = product_template.product_variant_ids[0]
                        if not product.default_code:
                            raise ValidationError("Please set SKU for product [%s]"%product.name)
                        magento_product.create({'erp_id':product.id,'magento_product_name' : product.name,'magento_sku' : product.default_code,'backend_id':wizard.backend_id.id,'website_ids':[((6,0, wizard.website_m2m_ids.ids))],
                                            'created_at': datetime.now(),'updated_at':datetime.now(),'product_type':product_type,'attribute_set_id' : wizard.magento_attribute_set_id.id,
                                            'description' : product.description , 'description_sale' : product.description_sale})
            for product in wizard.product_product_ids:
                if not product.magento_bind_ids.id:
                    product_type = "simple"
                    if not product.default_code:
                        raise ValidationError("Please set SKU for product [%s]"%product.name)
                    magento_product.create({'erp_id':product.id,'magento_product_name' : product.name,'magento_sku' : product.default_code,'backend_id':wizard.backend_id.id,'website_ids':[((6,0, wizard.website_m2m_ids.ids))],
                                            'created_at': datetime.now(),'updated_at':datetime.now(),'product_type':product_type,'attribute_set_id' : wizard.magento_attribute_set_id.id,
                                            'description' : product.description , 'description_sale' : product.description_sale})
                    
        return {'type': 'ir.actions.act_window_close'}
