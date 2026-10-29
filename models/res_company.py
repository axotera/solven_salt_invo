from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    solven_export_terms = fields.Html(
        "Export Terms and Conditions",
        help="Printed in the Terms and Conditions section of SOLVEN documents.",
    )
