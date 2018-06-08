from odoo import models,fields,api
import odoo.addons.decimal_precision as dp
from odoo import tools

class magento_invoice_report(models.Model):
    _name="magento.invoice.report"
    _auto = False
    description = "Invoice Statistics"
    _rec_name = 'date'
    _order = 'date desc'
    
       
    date=fields.Date('Date', readonly=True)
    state = fields.Selection([
                                ('draft','Draft'),
                                ('proforma','Pro-forma'),
                                ('proforma2','Pro-forma'),
                                ('open','Open'),
                                ('paid','Done'),
                                ('cancel','Cancelled')
                                ],'Invoice State',readonly=True)
    type=fields.Selection([
                           ('out_invoice','Customer Invoice'),
                           ('in_invoice','Supplier Invoice'),
                           ('out_refund','Customer Refund'),
                           ('in_refund','Supplier Refund'),
                           ],readonly=True)
    price_total = fields.Float('Total Without Tax',readonly=True)
    product_qty = fields.Float('Product Quantity',readonly=True)
    uom_name = fields.Char('Reference Unit of Measure',size=128,readonly=True)
    payment_term_id = fields.Many2one('account.payment.term','Payment Term',readonly=True)
    #period_id= fields.Many2one('account.period','Force Period',domain=[('state','<>','done')],readonly=True)
    fiscal_position_id=fields.Many2one('account.fiscal.position','Fiscal Position', readonly=True)
    currency_id = fields.Many2one('res.currency','Currency',readonly=True)
    categ_id = fields.Many2one('product.category','Category of Product',readonly=True)
    journal_id = fields.Many2one('account.journal','Journal',readonly=True)    
    commercial_partner_id = fields.Many2one('res.partner','Partner Company',help='Commercial Entity')
    price_average = fields.Float('Average Price',readonly=True,group_operator="avg")
    currency_rate= fields.Float('Currency Rate',readonly=True)
    nbr = fields.Integer('# of Invoices',readonly=True)
    product_id=fields.Many2one('product.product', 'Product', readonly=True)
    categ_id = fields.Many2one('product.category','Category of Product',readonly=True)
    partner_id=fields.Many2one('res.partner', 'Partner', readonly=True)
    company_id=fields.Many2one('res.company', 'Company', readonly=True)
    user_id= fields.Many2one('res.users', 'Salesperson', readonly=True)
    date_due = fields.Date('Due Date',readonly=True)
    account_id = fields.Many2one('account.account','Account',readonly=True)
    account_line_id = fields.Many2one('account.account','Account Line',readonly=True)
    partner_bank_id = fields.Many2one('res.partner.bank','Bank Account',readonly=True)
    residual = fields.Float('Total Residual',readonly=True)
    country_id = fields.Many2one('res.country','Country of Partner Company')
    backend_id = fields.Many2one('magento.backend','Instance',readonly=True)
    store_id = fields.Many2one('magento.store','Store',readonly=True)
    website_id = fields.Many2one('magento.website','Website',readonly=True) 
     
    
    def _select(self):
        select_str = """
            SELECT sub.id, sub.date, sub.product_id, sub.partner_id, sub.country_id,
                sub.payment_term_id, sub.uom_name, sub.currency_id, sub.journal_id,
                sub.fiscal_position_id, sub.user_id, sub.company_id, sub.nbr, sub.type, sub.state,
                sub.categ_id, sub.date_due, sub.account_id, sub.account_line_id, sub.partner_bank_id,
                sub.product_qty, sub.price_total/ COALESCE(cr.rate, 1) as price_total, sub.price_average /COALESCE(cr.rate, 1)  as price_average,
                COALESCE(cr.rate, 1) as currency_rate, sub.residual /COALESCE(cr.rate, 1) as residual, sub.commercial_partner_id as commercial_partner_id,
                sub.store_id,
                sub.website_id,
                sub.backend_id
                
        """
        return select_str
    
    def _sub_select(self):
        select_str = """
                SELECT min(ail.id) AS id,
                    ai.date_invoice AS date,
                    ail.product_id, ai.partner_id, ai.payment_term_id,
                    u2.name AS uom_name,
                    ai.currency_id, ai.journal_id, ai.fiscal_position_id, ai.user_id, ai.company_id,
                    count(ail.*) AS nbr,
                    ai.type, ai.state, pt.categ_id, ai.date_due, ai.account_id, ail.account_id AS account_line_id,
                    ai.partner_bank_id,
                    SUM(CASE
                         WHEN ai.type::text = ANY (ARRAY['out_refund'::character varying::text, 'in_invoice'::character varying::text])
                            THEN (- ail.quantity) / u.factor * u2.factor
                            ELSE ail.quantity / u.factor * u2.factor
                        END) AS product_qty,
                    SUM(CASE
                         WHEN ai.type::text = ANY (ARRAY['out_refund'::character varying::text, 'in_invoice'::character varying::text])
                            THEN - ail.price_subtotal
                            ELSE ail.price_subtotal
                        END) AS price_total,
                    CASE
                     WHEN ai.type::text = ANY (ARRAY['out_refund'::character varying::text, 'in_invoice'::character varying::text])
                        THEN SUM(- ail.price_subtotal)
                        ELSE SUM(ail.price_subtotal)
                    END / CASE
                           WHEN SUM(ail.quantity / u.factor * u2.factor) <> 0::numeric
                               THEN CASE
                                     WHEN ai.type::text = ANY (ARRAY['out_refund'::character varying::text, 'in_invoice'::character varying::text])
                                        THEN SUM((- ail.quantity) / u.factor * u2.factor)
                                        ELSE SUM(ail.quantity / u.factor * u2.factor)
                                    END
                               ELSE 1::numeric
                          END AS price_average,
                    CASE
                     WHEN ai.type::text = ANY (ARRAY['out_refund'::character varying::text, 'in_invoice'::character varying::text])
                        THEN - ai.residual
                        ELSE ai.residual
                    END / (SELECT count(*) FROM account_invoice_line l where invoice_id = ai.id) *
                    count(*) AS residual,
                    ai.commercial_partner_id as commercial_partner_id,
                    partner.country_id,
                    mso.store_id as store_id,
                    mso.website_id as website_id,
                    ai.backend_id as backend_id
                    
        """
        return select_str
    
    def _from(self):
        from_str = """
                FROM account_invoice_line ail
                JOIN account_invoice ai ON ai.id = ail.invoice_id
                JOIN sale_order so on so.id = ai.sale_id
                JOIN magento_sale_order mso ON mso.erp_id = so.id
                JOIN res_partner partner ON ai.commercial_partner_id = partner.id
                LEFT JOIN product_product pr ON pr.id = ail.product_id
                left JOIN product_template pt ON pt.id = pr.product_tmpl_id
                LEFT JOIN product_uom u ON u.id = ail.uom_id
                LEFT JOIN product_uom u2 ON u2.id = pt.uom_id
        """
        return from_str

    def _group_by(self):
        group_by_str = """
                GROUP BY ail.product_id, ai.date_invoice, ai.id,
                    ai.partner_id, ai.payment_term_id, u2.name, u2.id, ai.currency_id, ai.journal_id,
                    ai.fiscal_position_id, ai.user_id, ai.company_id, ai.type, ai.state, pt.categ_id,
                    ai.date_due, ai.account_id, ail.account_id, ai.partner_bank_id, ai.residual,
                    ai.amount_total, ai.commercial_partner_id, partner.country_id,
                    mso.store_id,
                    mso.website_id,
                    ai.backend_id
        """
        return group_by_str
    
    @api.model_cr
    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""CREATE or REPLACE VIEW %s as (
            WITH currency_rate AS (%s)
            %s
            FROM (
                %s %s %s
            ) AS sub
            LEFT JOIN currency_rate cr ON
                (cr.currency_id = sub.currency_id AND
                 cr.company_id = sub.company_id AND
                 cr.date_start <= COALESCE(sub.date, NOW()) AND
                 (cr.date_end IS NULL OR cr.date_end > COALESCE(sub.date, NOW())))
        )""" % (
                    self._table, self.env['res.currency']._select_companies_rates(),
                    self._select(), self._sub_select(), self._from(), self._group_by()))

