from odoo import api, fields, models


class AccountMove(models.Model):
    _name = "account.move"
    _inherit = ["account.move", "solven.export.mixin"]

    # Copied from the sales order when the invoice is created; the invoice's
    # own number and date stay the official Odoo name / invoice_date.
    solven_proforma_number = fields.Char("Related Proforma Invoice No.", copy=False)
    solven_proforma_date = fields.Date("Related Proforma Invoice Date", copy=False)
    solven_packing_list_ids = fields.One2many(
        "solven.packing.list", "invoice_id", string="Packing Lists", copy=False
    )
    solven_sale_order_ids = fields.Many2many(
        "sale.order", compute="_compute_solven_sale_order_ids", string="Sales Orders"
    )

    @api.depends("invoice_line_ids.sale_line_ids")
    def _compute_solven_sale_order_ids(self):
        for move in self:
            move.solven_sale_order_ids = move.invoice_line_ids.sale_line_ids.order_id

    def _solven_lines(self):
        self.ensure_one()
        return self.invoice_line_ids.filtered(lambda l: l.display_type == "product")

    def _solven_line_qty(self, line):
        return line.quantity, line.product_uom_id or line.product_id.uom_id

    def _solven_customer_po(self):
        return self.ref

    def _solven_missing_references(self):
        """Human-readable list of missing references for the Commercial Invoice."""
        self.ensure_one()
        missing = []
        if self.solven_acid_required and not self.solven_acid_number:
            missing.append("ACID No.")
        orders = self.solven_sale_order_ids
        if orders and not self.solven_proforma_number and any(o.solven_proforma_number for o in orders):
            missing.append("Related Proforma Invoice No. (issued on the order but not on this invoice)")
        return missing
