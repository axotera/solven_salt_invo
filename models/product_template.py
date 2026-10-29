from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    solven_hs_code = fields.Char("HS Code")
    solven_packing = fields.Char(
        "Packing", help="Packing description printed under the goods line."
    )
    solven_gross_weight = fields.Float(
        "Gross Weight per Unit",
        digits="Stock Weight",
        help="Gross weight (kg) of one sales unit. Net weight uses the standard Weight field.",
    )
