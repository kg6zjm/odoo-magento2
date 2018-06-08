from odoo import models, fields


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    sale_ids = fields.Many2many(comodel_name='sale.order',string='Sales Orders')
