from odoo import models,fields,api
import time

class stock_inventory(models.Model):
    _inherit="stock.inventory"
    
    @api.multi
    def _get_theoretical_qty(self, product,qty,location):
        location_obj = self.env['stock.location']        
        locations = location_obj.search([('id', 'child_of', [location])])
        domain = ' location_id in %s and product_id = %s'
        args = (tuple(locations.ids),(product.id,))
        vals = []
        flag = True                                 
        self._cr.execute('''
           SELECT product_id, sum(quantity) as product_qty, location_id, lot_id as prod_lot_id, package_id, owner_id as partner_id
           FROM stock_quant WHERE''' + domain + '''
           GROUP BY product_id, location_id, lot_id, package_id, partner_id''', args)
        
        for product_line in self._cr.dictfetchall():            
            for key, value in product_line.items():
                if not value:
                    product_line[key] = False
            product_line['inventory_id'] = self.id
            product_line['theoretical_qty'] = product_line['product_qty']
            if flag:
                product_line['product_qty'] = qty
                flag = False
            else:
                product_line['product_qty'] = 0.0
            if product_line['product_id']:                
                product_line['product_uom_id'] = product.uom_id.id
            vals.append(product_line)            

        if not vals:
            if qty > 0.0:
                vals.append({'product_id':product.id,
                                       'inventory_id': self.id,
                                       'theoretical_qty': 0.0,
                                       'location_id':location,
                                       'product_qty':qty,
                                       'product_uom_id':product.uom_id.id,
                                       })            

        return vals
    
    @api.model
    def create_stock_inventory(self,products,location_id,auto_validate=False):
        inventory_line_obj=self.env['stock.inventory.line']
        inventory_name = 'product_inventory_%s'%(time.strftime("%Y-%m-%d %H:%M:%S"))
        inventory_vals = {
                        'name':inventory_name,
                        'location_id':location_id.id or False,
                        'date':time.strftime("%Y-%m-%d %H:%M:%S"),
                        'filter':'partial',
                        }
        inventory = self.create(inventory_vals)
        
        for product in products:
            vals = inventory._get_theoretical_qty(product.get('product_id',''),product.get('product_qty',''),location_id.id)
            for product_line in vals:
                    inventory_line_obj.create(product_line)            
        if inventory:
            inventory.action_start()
        if auto_validate == True: 
            inventory.action_done()  