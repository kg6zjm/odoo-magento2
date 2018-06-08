from odoo import fields,models,api

class product_attribute_value(models.Model):
    _inherit = 'product.attribute.value'
    _sql_constraints = [('value_company_uniq', 'CHECK(1=1)', 'This attribute value already exists !')]
    
