from odoo import api, models


class ReportProformaInvoice(models.AbstractModel):
    _name = "report.solven_export_invoice.report_proforma_invoice"
    _description = "SOLVEN Proforma Invoice"

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env["sale.order"].browse(docids)
        # First print issues the Proforma number/date; reprints keep them.
        docs._solven_ensure_proforma_number()
        return {"doc_ids": docs.ids, "doc_model": "sale.order", "docs": docs}
