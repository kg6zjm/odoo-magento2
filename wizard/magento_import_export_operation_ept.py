from odoo import fields,models,api

class magento_import_export_ept(models.TransientModel):
    
    _name='magento.import.export.ept'
    
    backend_ids = fields.Many2many('magento.backend',string="Instances")
    
    import_res_partner_category = fields.Boolean('Import Customer Category')
    import_res_partner = fields.Boolean("Import Customer")
    
    import_attribute_set = fields.Boolean("Import Attribute Set")
    import_attribute = fields.Boolean("Import Attributes")
    
    import_product_category = fields.Boolean("Import Product Category")
    import_products = fields.Boolean("Import Products")
    import_product_images = fields.Boolean("Import Product Images")
    
    import_sale_order = fields.Boolean("Import Sale Order")
    import_specific_order = fields.Boolean("Import Specific Order",help="Import specific order from Magento")
    import_sale_order_manually = fields.Char("Sale Order Reference",help="You can import Magento Order by giving order number here,Ex.000000021 \n If multiple orders are there give order number comma (,) seperated ")
    
    update_order_status = fields.Boolean("Export Shipment Information")
    export_order_invoice = fields.Boolean("Export Invoice Information") 
    
    export_product_stock = fields.Boolean("Export Product Stock")
    import_product_stock = fields.Boolean("Import Product Stock")
    
    @api.model
    def default_get(self,fields):
        res = super(magento_import_export_ept,self).default_get(fields)
        if 'default_backend_id' in self._context:
            res.update({'backend_ids':[(6,0,[self._context.get('default_backend_id')])]})
        else :
            if 'backend_ids' in fields:
                backend_ids = self.env['magento.backend'].search([])
                res.update({'backend_ids':[(6,0,backend_ids.ids)]})
        return res
    
    @api.multi
    def execute(self):
        magento_backend = self.env['magento.backend']
        magento_res_partner_category = self.env['magento.res.partner.category']
        magento_res_partner = self.env['res.partner']
        magento_attribute_set = self.env['magento.attribute.set']
        magento_attribute = self.env['magento.product.attribute']
        magento_product_category = self.env['magento.product.category']
        magento_sale_order = self.env['magento.sale.order']
        magento_product_product = self.env['magento.product.product']
        account_invoice = self.env['account.invoice']
        picking = self.env['stock.picking']
        if self.backend_ids:
            backends=self.backend_ids
        else :
            backends = magento_backend.search([])
        if self.import_res_partner_category:
            magento_res_partner_category.import_customer_group(backends)
        if self.import_res_partner:
            magento_res_partner.import_magento_partners(backends)
        if self.import_attribute_set:
            magento_attribute_set.import_attribute_set(backends)
        if self.import_attribute:
            magento_attribute.import_attribute(backends)
        if self.import_product_category:
            magento_product_category.import_product_category(backends)
        if self.import_sale_order:
            magento_sale_order.import_sale_orders(backends)
        if self.import_products:
            magento_product_product.import_products(backends)
        if self.import_sale_order_manually :
            sale_order_list = self.import_sale_order_manually.split(',')
            for sale_order in sale_order_list:
                magento_sale_order.import_sale_order_by_number(backends,sale_order)
        if self.export_order_invoice:
            account_invoice.export_invoice_to_magento(backends)
        if self.update_order_status :
            picking.export_shipment_to_magento(backends)
        if self.export_product_stock :
            for backend in backends :
                product_ids = magento_product_product.search([('backend_id','=',backend.id)])
                magento_product_product.export_multiple_product_stock_to_magento(product_ids)
        if self.import_product_stock :
            for backend in backends:
                product_ids = magento_product_product.search([('backend_id','=',backend.id)])
                magento_product_product.create_product_inventory(product_ids)
        if self.import_product_images:
            for backend in backends:
                product_ids = magento_product_product.search([('backend_id','=',backend.id)])
                magento_product_product.import_all_images_products(product_ids)
        return {
                'type': 'ir.actions.client',
                'tag': 'reload',
               }

    