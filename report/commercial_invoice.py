from odoo import _, api, models
from odoo.exceptions import UserError


class ReportCommercialInvoice(models.AbstractModel):
    _name = "report.solven_export_invoice.report_commercial_invoice"
    _description = "SOLVEN Commercial Invoice"

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env["account.move"].browse(docids)
        invalid = docs.filtered(
            lambda m: m.state != "posted" or m.move_type not in ("out_invoice", "out_refund")
        )
        if invalid:
            raise UserError(
                _(
                    "The SOLVEN Commercial Invoice can only be printed for posted "
                    "customer invoices. Not allowed: %s",
                    ", ".join(invalid.mapped("display_name")),
                )
            )
        return {"doc_ids": docs.ids, "doc_model": "account.move", "docs": docs}
