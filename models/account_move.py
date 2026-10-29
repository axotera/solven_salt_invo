from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .export_mixin import SOLVEN_CURRENCIES


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
    solven_packing_list_count = fields.Integer(compute="_compute_solven_packing_list_count")
    solven_sale_order_ids = fields.Many2many(
        "sale.order", compute="_compute_solven_sale_order_ids", string="Sales Orders"
    )
    solven_currency_ok = fields.Boolean(compute="_compute_solven_currency_ok")

    @api.depends("invoice_line_ids.sale_line_ids")
    def _compute_solven_sale_order_ids(self):
        for move in self:
            move.solven_sale_order_ids = move.invoice_line_ids.sale_line_ids.order_id

    def _compute_solven_packing_list_count(self):
        for move in self:
            move.solven_packing_list_count = len(move.solven_packing_list_ids)

    @api.depends("currency_id")
    def _compute_solven_currency_ok(self):
        for move in self:
            move.solven_currency_ok = move.currency_id.name in SOLVEN_CURRENCIES

    def _solven_lines(self):
        self.ensure_one()
        return self.invoice_line_ids.filtered(lambda l: l.display_type == "product")

    def _solven_line_qty(self, line):
        return line.quantity, line.product_uom_id or line.product_id.uom_id

    def _solven_customer_po(self):
        return self.ref

    def _solven_destination_country(self):
        self.ensure_one()
        for partner in (self.partner_shipping_id, self.partner_id):
            if partner and partner.country_id:
                return partner.country_id
        return self.env["res.country"]

    # ------------------------------------------------------------------
    # Commercial Invoice -> linked Packing List (same number, same date)
    # ------------------------------------------------------------------
    def _solven_prepare_packing_list(self):
        """Create the linked Packing List once, or refresh the existing draft one.

        Never creates a duplicate and never consumes a sequence number: the
        Packing List shows the invoice's own number and date. The Packing List
        stays in draft until the user issues it."""
        PackingList = self.env["solven.packing.list"]
        result = PackingList
        for move in self:
            if move.move_type != "out_invoice":
                continue
            if move.state != "posted":
                raise UserError(_("Post invoice %s before preparing its Packing List.", move.display_name))
            packing = move.solven_packing_list_ids.filtered(lambda p: p.state != "cancel")[:1]
            if not packing:
                packing = PackingList.create(PackingList._solven_vals_from_invoice(move))
            elif packing.state == "draft" and packing._solven_is_invoice_mirror():
                packing._solven_refresh_from_invoice()
            result |= packing
        return result

    def action_solven_print_documents(self):
        """Print the Commercial Invoice; the linked Packing List is prepared
        (or refreshed while in draft) at the same time."""
        self._solven_prepare_packing_list()
        return self.env.ref(
            "solven_export_invoice.action_report_solven_commercial_invoice").report_action(self)

    def action_solven_open_packing_list(self):
        self.ensure_one()
        packing = self._solven_prepare_packing_list()
        return packing._solven_form_action()

    def action_solven_view_packing_lists(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "solven_export_invoice.action_solven_packing_list")
        action["domain"] = [("invoice_id", "=", self.id)]
        return action
