from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare


def _to_product_uom(qty, uom, product):
    """Convert qty to the product's base unit; incompatible units stay as-is
    (the quantity check then reports a mismatch instead of crashing)."""
    if not uom or uom == product.uom_id:
        return qty
    try:
        return uom._compute_quantity(qty, product.uom_id)
    except UserError:
        return qty


class SolvenPackingList(models.Model):
    """A shipment Packing List with its own number, linked to one sales order
    and (optionally, until invoicing) one posted Commercial Invoice.

    One order can have several invoices and several packing lists; one invoice
    can have several packing lists (split shipments). Nothing is guessed: the
    invoice is pre-selected only when exactly one candidate exists.
    """

    _name = "solven.packing.list"
    _inherit = ["solven.export.mixin", "mail.thread"]
    _description = "SOLVEN Packing List"
    _order = "date desc, id desc"
    _check_company_auto = True

    name = fields.Char("Packing List No.", readonly=True, copy=False, default="/", index=True)
    date = fields.Date("Packing List Date", required=True, default=fields.Date.context_today, copy=False)
    state = fields.Selection(
        [("draft", "Draft"), ("done", "Issued"), ("cancel", "Cancelled")],
        default="draft", required=True, copy=False, tracking=True,
    )
    sale_order_id = fields.Many2one(
        "sale.order", "Sales Order", required=True, index=True, check_company=True,
        domain="[('state', '!=', 'cancel')]", tracking=True,
    )
    company_id = fields.Many2one(related="sale_order_id.company_id", store=True, index=True)
    partner_id = fields.Many2one(related="sale_order_id.partner_id", store=True, string="Customer")
    currency_id = fields.Many2one(related="sale_order_id.currency_id")
    invoice_candidate_ids = fields.Many2many("account.move", compute="_compute_invoice_candidate_ids")
    invoice_id = fields.Many2one(
        "account.move", "Related Commercial Invoice", index=True, check_company=True, tracking=True,
        domain="[('id', 'in', invoice_candidate_ids)]",
        help="Posted customer invoice of the same order this shipment belongs to.",
    )
    invoice_number = fields.Char(related="invoice_id.name", string="Commercial Invoice No.")
    invoice_date = fields.Date(related="invoice_id.invoice_date", string="Commercial Invoice Date")
    proforma_number = fields.Char("Related Proforma Invoice No.", compute="_compute_proforma")
    proforma_date = fields.Date("Proforma Invoice Date", compute="_compute_proforma")
    line_ids = fields.One2many("solven.packing.list.line", "packing_id", "Lines", copy=True)
    warning_text = fields.Text("Checks", compute="_compute_warning_text")
    note = fields.Text("Notes")

    _name_company_uniq = models.Constraint(
        "UNIQUE(company_id, name)", "Packing List numbers must be unique per company."
    )

    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records.filtered(lambda r: not r.name or r.name == "/"):
            number = self.env["ir.sequence"].with_company(rec.company_id).next_by_code(
                "solven.packing.list", sequence_date=rec.date
            )
            if not number:
                raise UserError(_("The SOLVEN Packing List sequence is missing."))
            rec.name = number
        return records

    def copy(self, default=None):
        default = dict(default or {}, name="/")
        return super().copy(default)

    @api.depends("sale_order_id.invoice_ids.state")
    def _compute_invoice_candidate_ids(self):
        for rec in self:
            rec.invoice_candidate_ids = (
                rec.sale_order_id._solven_candidate_invoices() if rec.sale_order_id else False
            )

    @api.depends("invoice_id.solven_proforma_number", "sale_order_id.solven_proforma_number")
    def _compute_proforma(self):
        for rec in self:
            src = rec.invoice_id if rec.invoice_id.solven_proforma_number else rec.sale_order_id
            rec.proforma_number = src.solven_proforma_number or False
            rec.proforma_date = src.solven_proforma_date or False

    # ------------------------------------------------------------------
    # Checks: blocking errors and non-blocking warnings, never auto-fixed.
    # ------------------------------------------------------------------
    def _solven_check(self):
        """Return (errors, warnings) as lists of strings naming field and documents."""
        self.ensure_one()
        errors, warnings = [], []
        order, inv = self.sale_order_id, self.invoice_id
        if order.state == "cancel":
            errors.append(_("Sales order %s is cancelled.", order.name))
        if not inv:
            candidates = order._solven_candidate_invoices() if order else self.env["account.move"]
            if len(candidates) > 1:
                warnings.append(_("Related Commercial Invoice: not selected; order %(o)s has %(n)s posted invoices (%(l)s). Select the correct one.",
                                  o=order.name, n=len(candidates), l=", ".join(candidates.mapped("name"))))
            else:
                warnings.append(_("Related Commercial Invoice: not selected (no posted invoice yet)."))
        else:
            if inv.state == "cancel":
                errors.append(_("Commercial Invoice %s is cancelled.", inv.name))
            elif inv.state != "posted":
                errors.append(_("Commercial Invoice %s is not posted.", inv.name))
            if inv.move_type != "out_invoice":
                errors.append(_("%s is not a customer invoice.", inv.display_name))
            if inv.commercial_partner_id != order.partner_id.commercial_partner_id:
                errors.append(_("Customer: invoice %(i)s is for %(a)s, order %(o)s is for %(b)s.",
                                i=inv.name, a=inv.commercial_partner_id.name,
                                o=order.name, b=order.partner_id.commercial_partner_id.name))
            if order not in inv.solven_sale_order_ids:
                warnings.append(_("Invoice %(i)s was not generated from order %(o)s.", i=inv.name, o=order.name))
            if (inv.solven_acid_number or False) != (self.solven_acid_number or False) and inv.solven_acid_number:
                warnings.append(_("ACID No.: packing list %(p)s has '%(a)s', invoice %(i)s has '%(b)s'.",
                                  p=self.name, a=self.solven_acid_number or "-", i=inv.name, b=inv.solven_acid_number))
            if (order.solven_proforma_number and inv.solven_proforma_number
                    and order.solven_proforma_number != inv.solven_proforma_number):
                warnings.append(_("Proforma No.: order %(o)s has %(a)s, invoice %(i)s has %(b)s.",
                                  o=order.name, a=order.solven_proforma_number,
                                  i=inv.name, b=inv.solven_proforma_number))
            if inv.currency_id != order.currency_id:
                warnings.append(_("Currency: invoice %(i)s uses %(a)s, order uses %(b)s.",
                                  i=inv.name, a=inv.currency_id.name, b=order.currency_id.name))
            warnings += self._solven_check_quantities()
        if self.solven_acid_required and not self.solven_acid_number:
            warnings.append(_("ACID No.: required for this shipment but missing."))
        if not self.line_ids:
            warnings.append(_("No goods lines."))
        for line in self.line_ids:
            if not line.net_weight:
                warnings.append(_("Net weight missing for %s.", line.name))
            if not line.gross_weight:
                warnings.append(_("Gross weight missing for %s.", line.name))
            if line.net_weight and line.gross_weight and line.gross_weight < line.net_weight:
                warnings.append(_("Gross weight is lower than net weight for %s.", line.name))
            if not line.product_id.solven_hs_code:
                warnings.append(_("HS Code missing on product %s.", line.product_id.display_name))
        return errors, warnings

    def _solven_check_quantities(self):
        """Packed quantity per product (over all non-cancelled packing lists of
        the same invoice) must not exceed the invoiced quantity."""
        self.ensure_one()
        inv = self.invoice_id
        warnings = []
        siblings = inv.solven_packing_list_ids.filtered(lambda p: p.state != "cancel") | self
        invoiced, packed = {}, {}
        for line in inv._solven_lines():
            invoiced[line.product_id] = invoiced.get(line.product_id, 0.0) + _to_product_uom(
                line.quantity, line.product_uom_id, line.product_id)
        for line in siblings.line_ids:
            packed[line.product_id] = packed.get(line.product_id, 0.0) + _to_product_uom(
                line.quantity, line.uom_id, line.product_id)
        for product, qty in packed.items():
            if product not in invoiced:
                warnings.append(_("Product %(p)s is not on invoice %(i)s.", p=product.display_name, i=inv.name))
            elif float_compare(qty, invoiced[product], precision_rounding=product.uom_id.rounding) > 0:
                warnings.append(_("Quantity: %(p)s packed %(a)s on all packing lists of invoice %(i)s, invoiced %(b)s.",
                                  p=product.display_name, a=qty, i=inv.name, b=invoiced[product]))
        return warnings

    @api.depends("invoice_id", "sale_order_id", "solven_acid_number", "solven_acid_required",
                 "line_ids.net_weight", "line_ids.gross_weight", "line_ids.quantity", "line_ids.product_id")
    def _compute_warning_text(self):
        for rec in self:
            if not rec.sale_order_id:
                rec.warning_text = False
                continue
            errors, warnings = rec._solven_check()
            rec.warning_text = "\n".join(
                [f"ERROR: {e}" for e in errors] + [f"WARNING: {w}" for w in warnings]
            ) or False

    # ------------------------------------------------------------------
    def action_issue(self):
        for rec in self:
            errors, _warnings = rec._solven_check()
            if not rec.invoice_id:
                errors.append(_("Select the related posted Commercial Invoice before issuing."))
            if errors:
                raise UserError(_("Packing List %(n)s cannot be issued:\n%(e)s", n=rec.name, e="\n".join(errors)))
            rec.state = "done"

    def action_cancel(self):
        self.write({"state": "cancel"})

    def action_draft(self):
        self.filtered(lambda r: r.state == "cancel").write({"state": "draft"})

    def action_fill_from_invoice(self):
        """Copy the shipment fields of the related invoice (only those set there)."""
        from .export_mixin import EXPORT_FIELDS
        for rec in self.filtered("invoice_id"):
            vals = {}
            for fname in EXPORT_FIELDS:
                value = rec.invoice_id[fname]
                if value and fname != "solven_doc_version":
                    vals[fname] = value.id if fname.endswith("_id") else value
            rec.write(vals)

    def _solven_form_action(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "current",
        }

    # ------------------------------------------------------------------
    # Report helpers
    # ------------------------------------------------------------------
    def _solven_lines(self):
        self.ensure_one()
        return self.line_ids

    def _solven_line_qty(self, line):
        return line.quantity, line.uom_id or line.product_id.uom_id

    def _solven_pack_totals(self):
        self.ensure_one()
        lines = self.line_ids
        uoms = lines.mapped("uom_id.category_id" if "category_id" in lines.uom_id._fields else "uom_id")
        qty = sum(lines.mapped("quantity")) if len(uoms) <= 1 else False
        packages = sum(lines.mapped("package_count")) if lines and all(lines.mapped("package_count")) else False
        return qty, sum(lines.mapped("net_weight")), sum(lines.mapped("gross_weight")), packages

    def _solven_destination_country(self):
        return self.sale_order_id._solven_destination_country()


class SolvenPackingListLine(models.Model):
    _name = "solven.packing.list.line"
    _description = "SOLVEN Packing List Line"
    _order = "sequence, id"

    packing_id = fields.Many2one("solven.packing.list", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="packing_id.company_id", store=True)
    sequence = fields.Integer(default=10)
    sale_line_id = fields.Many2one("sale.order.line", "Order Line", ondelete="set null")
    product_id = fields.Many2one("product.product", "Product", required=True)
    name = fields.Char("Description", required=True)
    quantity = fields.Float("Quantity", digits="Product Unit", required=True, default=1.0)
    uom_id = fields.Many2one("uom.uom", "Unit", required=True)
    package_count = fields.Integer("Packages")
    package_type = fields.Char("Package Type", help="e.g. cartons, drums, bags.")
    net_weight = fields.Float("Net Weight (kg)", digits="Stock Weight",
                              help="Net weight of this line for this shipment.")
    gross_weight = fields.Float("Gross Weight (kg)", digits="Stock Weight",
                                help="Gross weight of this line for this shipment.")

    def _solven_packing_text(self):
        """'<product packing>, <count> <package type>' with empty parts omitted."""
        self.ensure_one()
        count = f"{self.package_count} {self.package_type or ''}".strip() if self.package_count else False
        return ", ".join(p for p in (self.product_id.product_tmpl_id.solven_packing, count) if p)

    @api.onchange("product_id")
    def _onchange_product_id(self):
        if self.product_id:
            self.name = self.product_id.name
            self.uom_id = self.product_id.uom_id

    @api.model_create_multi
    def create(self, vals_list):
        # Pre-fill weights from the product master only when the product has them
        # and the user left the shipment weight empty. Nothing is invented.
        for vals in vals_list:
            product = self.env["product.product"].browse(vals.get("product_id"))
            qty = vals.get("quantity", 1.0)
            tmpl = product.product_tmpl_id
            if not vals.get("net_weight") and tmpl.weight:
                vals["net_weight"] = tmpl.weight * qty
            if not vals.get("gross_weight") and tmpl.solven_gross_weight:
                vals["gross_weight"] = tmpl.solven_gross_weight * qty
        return super().create(vals_list)
