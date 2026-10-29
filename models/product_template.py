from odoo import fields, models

from .export_mixin import PACKAGE_TYPES


class ProductTemplate(models.Model):
    _inherit = "product.template"

    solven_hs_code = fields.Char("HS Code")
    solven_packing = fields.Char(
        "Packing", help="Packing description printed under the goods line, e.g. '15 kg telescopic cartons'."
    )
    solven_gross_weight = fields.Float(
        "Gross Weight per Unit",
        digits="Stock Weight",
        help="Gross weight (kg) of one sales unit. Net weight uses the standard Weight field.",
    )
    solven_package_type = fields.Selection(PACKAGE_TYPES, "Default Packaging")
    solven_units_per_package = fields.Float(
        "Units per Package", digits="Product Unit",
        help="Sales units in one package (e.g. 15 for 15 kg cartons). Used to propose the package count.",
    )
