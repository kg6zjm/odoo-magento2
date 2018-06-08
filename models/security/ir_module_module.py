
from odoo import api, fields, models, _

class ir_module_module(models.Model):
    _inherit = 'ir.module.module'
    
    @api.multi
    def button_install(self):
        
        if self.name=='odoo_magento2_ept':
            pass
        
        return super(ir_module_module,self).button_install()