from odoo import tools
from odoo import fields,models,api

class sale_report(models.Model):
    _name = "magento.sale.report"
    _description = "Sales Orders Statistics"
    _auto = False
    _rec_name = 'date'

    date=fields.Datetime('Date Order', readonly=True)
    product_id=fields.Many2one('product.product', 'Product', readonly=True)
    product_uom=fields.Many2one('product.uom', 'Unit of Measure', readonly=True)
    product_uom_qty=fields.Float('# of Qty', readonly=True)
    partner_id=fields.Many2one('res.partner', 'Partner', readonly=True)
    company_id=fields.Many2one('res.company', 'Company', readonly=True)
    user_id= fields.Many2one('res.users', 'Salesperson', readonly=True)
    price_total=fields.Float('Total Price', readonly=True)
    delay=fields.Float('Commitment Delay', digits=(16,2), readonly=True)
    categ_id=fields.Many2one('product.category','Category of Product', readonly=True)
    nbr=fields.Integer('# of Lines', readonly=True)
    state=fields.Selection([
            ('draft', 'Quotation'),
            ('waiting_date', 'Waiting Schedule'),
            ('manual', 'Manual In Progress'),
            ('progress', 'In Progress'),
            ('invoice_except', 'Invoice Exception'),
            ('done', 'Done'),
            ('cancel', 'Cancelled')
            ], 'Order Status', readonly=True)
    pricelist_id=fields.Many2one('product.pricelist', 'Pricelist', readonly=True)
    analytic_account_id=fields.Many2one('account.analytic.account', 'Analytic Account', readonly=True)
    team_id=fields.Many2one('crm.team', 'Sales Team',oldname='section_id',)
    instance_id=fields.Many2one("magento.backend","Instance",readonly=True)
    #storeview_id = fields.Many2one("magento.storeview","Storeview",readonly=True)
    store_id = fields.Many2one("magento.store",
                               string='Store',
                               readonly=True,
                               )
    website_id = fields.Many2one("magento.website",
                                 string='Website',
                                 readonly=True,
                                 )

    _order = 'date desc'

    def _select(self):
        select_str = """
             SELECT min(l.id) as id,
                    l.product_id as product_id,
                    t.uom_id as product_uom,
                    sum(l.product_uom_qty / u.factor * u2.factor) as product_uom_qty,
                    sum(l.product_uom_qty * l.price_unit * (100.0-l.discount) / 100.0) as price_total,
                    count(*) as nbr,
                    s.date_order as date,
                    s.partner_id as partner_id,
                    s.user_id as user_id,
                    s.company_id as company_id,
                    extract(epoch from avg(date_trunc('day',s.date_order)-date_trunc('day',s.create_date)))/(24*60*60)::decimal(16,2) as delay,
                    s.state,
                    t.categ_id as categ_id,
                    s.pricelist_id as pricelist_id,
                    s.analytic_account_id as analytic_account_id,
                    s.team_id as team_id,
                    mb.id as instance_id,
                    mso.store_id,
                    mso.website_id
                    
        """
        return select_str

    def _from(self):
        from_str = """
                sale_order_line l
                      join sale_order s on (l.order_id=s.id)
                      join magento_sale_order mso on (l.order_id=mso.erp_id)
                      join magento_backend mb on (mb.id=mso.backend_id)
                      left join product_product p on (l.product_id=p.id)
                      left join product_template t on (p.product_tmpl_id=t.id)
                      left join product_uom u on (u.id=l.product_uom)
                      left join product_uom u2 on (u2.id=t.uom_id)
        """
        return from_str

    def _group_by(self):
        group_by_str = """
            GROUP BY l.product_id,
                    l.order_id,
                    t.uom_id,
                    t.categ_id,
                    s.date_order,
                    s.partner_id,
                    s.user_id,
                    s.company_id,
                    s.state,
                    s.pricelist_id,
                    s.analytic_account_id,
                    s.team_id,
                    mb.id,
                    mso.store_id,
                    mso.website_id
        """
        return group_by_str

    @api.model_cr
    def init(self):
        # self._table = sale_report
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""CREATE or REPLACE VIEW %s as (
            %s
            FROM ( %s )
            %s
            )""" % (self._table, self._select(), self._from(), self._group_by()))

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
