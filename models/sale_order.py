from odoo import _, fields, models
from odoo.exceptions import UserError

from .export_mixin import EXPORT_FIELDS


class SaleOrder(models.Model):
    _name = "sale.order"
    _inherit = ["sale.order", "solven.export.mixin"]

    # Proforma identity: issued once, never regenerated on reprint.
    solven_proforma_number = fields.Char(
        "Proforma Invoice No.", readonly=True, copy=False, index=True,
        help="Assigned once from the SOLVEN Proforma sequence when the Proforma "
             "is first issued or printed. Reprinting keeps this number.",
    )
    solven_proforma_date = fields.Date("Proforma Invoice Date", readonly=True, copy=False)
    solven_packing_list_ids = fields.One2many(
        "solven.packing.list", "sale_order_id", string="Packing Lists", copy=False
    )
    solven_packing_list_count = fields.Integer(compute="_compute_solven_packing_list_count")

    _solven_proforma_number_uniq = models.Constraint(
        "UNIQUE(company_id, solven_proforma_number)",
        "Proforma Invoice numbers must be unique per company.",
    )

    def _compute_solven_packing_list_count(self):
        for order in self:
            order.solven_packing_list_count = len(order.solven_packing_list_ids)

    # ------------------------------------------------------------------
    # Proforma numbering
    # ------------------------------------------------------------------
    def _solven_ensure_proforma_number(self):
        """Assign a Proforma number/date once. Existing values are kept."""
        for order in self.filtered(lambda o: not o.solven_proforma_number):
            if order.state == "cancel":
                raise UserError(_("A Proforma Invoice cannot be issued for the cancelled order %s.", order.name))
            number = self.env["ir.sequence"].with_company(order.company_id).next_by_code(
                "solven.proforma.invoice", sequence_date=fields.Date.context_today(order)
            )
            if not number:
                raise UserError(_("The SOLVEN Proforma Invoice sequence is missing."))
            order.sudo().write({
                "solven_proforma_number": number,
                "solven_proforma_date": fields.Date.context_today(order),
            })

    def action_solven_issue_proforma(self):
        self._solven_ensure_proforma_number()
        return True

    # ------------------------------------------------------------------
    # Packing lists
    # ------------------------------------------------------------------
    def action_solven_create_packing_list(self):
        self.ensure_one()
        if self.state == "cancel":
            raise UserError(_("A Packing List cannot be created for a cancelled order."))
        invoices = self._solven_candidate_invoices()
        vals = {
            "sale_order_id": self.id,
            # Only pre-select when exactly one posted invoice exists; never guess.
            "invoice_id": invoices.id if len(invoices) == 1 else False,
            "line_ids": [
                (0, 0, {
                    "sale_line_id": line.id,
                    "product_id": line.product_id.id,
                    "name": line.product_id.name or line.name,
                    "quantity": self._solven_line_qty(line)[0],
                    "uom_id": self._solven_line_qty(line)[1].id,
                })
                for line in self._solven_lines() if line.product_id
            ],
        }
        for fname in EXPORT_FIELDS:
            if fname == "solven_doc_version":
                continue
            value = self[fname]
            vals[fname] = value.id if fname.endswith("_id") else value
        packing = self.env["solven.packing.list"].create(vals)
        return packing._solven_form_action()

    def action_solven_view_packing_lists(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "solven_export_invoice.action_solven_packing_list"
        )
        action["domain"] = [("sale_order_id", "=", self.id)]
        action["context"] = {"default_sale_order_id": self.id}
        return action

    def _solven_candidate_invoices(self):
        """Posted, non-cancelled customer invoices generated from this order."""
        self.ensure_one()
        return self.invoice_ids.filtered(
            lambda m: m.state == "posted" and m.move_type == "out_invoice"
        )

    # ------------------------------------------------------------------
    def _prepare_invoice(self):
        vals = super()._prepare_invoice()
        for fname in EXPORT_FIELDS:
            value = self[fname]
            if not value:
                continue
            vals[fname] = value.id if fname.endswith("_id") else value
        if self.solven_proforma_number:
            vals["solven_proforma_number"] = self.solven_proforma_number
            vals["solven_proforma_date"] = self.solven_proforma_date
        return vals

    def _solven_lines(self):
        self.ensure_one()
        return self.order_line.filtered(lambda l: not l.display_type)

    def _solven_line_qty(self, line):
        uom = line.product_uom_id if "product_uom_id" in line._fields else line.product_uom
        return line.product_uom_qty, uom or line.product_id.uom_id

    def _solven_customer_po(self):
        return self.client_order_ref

    def _solven_pack_totals(self):
        """(total qty, total net kg, total gross kg) for the order-level packing preview."""
        self.ensure_one()
        qty = net = gross = 0.0
        for line in self._solven_lines():
            line_qty, _uom = self._solven_line_qty(line)
            tmpl = line.product_id.product_tmpl_id
            qty += line_qty
            net += (tmpl.weight or 0.0) * line_qty
            gross += (tmpl.solven_gross_weight or 0.0) * line_qty
        return qty, net, gross

    def _solven_destination_country(self):
        """Destination country: delivery address first, then customer."""
        self.ensure_one()
        for partner in (self.partner_shipping_id, self.partner_id):
            if partner and partner.country_id:
                return partner.country_id.name
        return False
