import math

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_is_zero

from .export_mixin import PACKAGE_TYPES


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
    """Shipment Packing List.

    Paired with a Commercial Invoice it prints exactly the invoice's number and
    issue date (both taken from account.move, never typed). Prepared
    automatically from the invoice, it stays in draft until the user issues it.
    Packing lists created from a sales order before invoicing (split shipments)
    keep an internal reference until they are linked to their invoice.
    """

    _name = "solven.packing.list"
    _inherit = ["solven.export.mixin", "mail.thread"]
    _description = "SOLVEN Packing List"
    _order = "date desc, id desc"
    _check_company_auto = True
    _rec_name = "solven_number"

    name = fields.Char("Internal Reference", readonly=True, copy=False, default="/", index=True)
    solven_number = fields.Char(
        "Packing List No.", compute="_compute_solven_number", store=True,
        help="Same number as the linked Commercial Invoice.")
    date = fields.Date(
        "Packing List Date", compute="_compute_date", store=True, readonly=False,
        required=True, copy=False, precompute=True,
        help="Same date as the linked Commercial Invoice; editable only while no invoice is linked.")
    state = fields.Selection(
        [("draft", "Draft"), ("done", "Issued"), ("cancel", "Cancelled")],
        default="draft", required=True, copy=False, tracking=True,
    )
    source = fields.Selection(
        [("invoice", "Commercial Invoice"), ("order", "Sales Order")],
        default="order", readonly=True, copy=False,
        help="Invoice-sourced lists mirror the invoice lines while in draft.")
    sale_order_id = fields.Many2one(
        "sale.order", "Sales Order", index=True, check_company=True,
        domain="[('state', '!=', 'cancel')]", tracking=True,
    )
    company_id = fields.Many2one(
        "res.company", compute="_compute_company_partner", store=True, index=True, readonly=False,
        precompute=True, default=lambda self: self.env.company, required=True)
    partner_id = fields.Many2one(
        "res.partner", compute="_compute_company_partner", store=True, string="Customer", precompute=True)
    currency_id = fields.Many2one("res.currency", compute="_compute_currency_id")
    invoice_candidate_ids = fields.Many2many("account.move", compute="_compute_invoice_candidate_ids")
    invoice_id = fields.Many2one(
        "account.move", "Related Commercial Invoice", index=True, check_company=True, tracking=True,
        domain="[('id', 'in', invoice_candidate_ids)]",
        help="Posted customer invoice this shipment belongs to.",
    )
    invoice_number = fields.Char(related="invoice_id.name", string="Commercial Invoice No.")
    invoice_date = fields.Date(related="invoice_id.invoice_date", string="Commercial Invoice Date")
    proforma_number = fields.Char("Related Proforma Invoice No.", compute="_compute_proforma")
    proforma_date = fields.Date("Proforma Invoice Date", compute="_compute_proforma")
    line_ids = fields.One2many("solven.packing.list.line", "packing_id", "Lines", copy=True)
    warning_text = fields.Text("Checks", compute="_compute_warning_text")
    note = fields.Text("Notes")

    _name_company_uniq = models.Constraint(
        "UNIQUE(company_id, name)", "Packing List references must be unique per company."
    )

    # ------------------------------------------------------------------
    @api.depends("name", "invoice_id.name")
    def _compute_solven_number(self):
        for rec in self:
            inv_name = rec.invoice_id.name
            rec.solven_number = inv_name if inv_name and inv_name != "/" else rec.name

    @api.depends("invoice_id.invoice_date")
    def _compute_date(self):
        for rec in self:
            if rec.invoice_id.invoice_date:
                rec.date = rec.invoice_id.invoice_date
            elif not rec.date:
                rec.date = fields.Date.context_today(rec)

    @api.depends("sale_order_id", "invoice_id")
    def _compute_company_partner(self):
        for rec in self:
            src = rec.invoice_id or rec.sale_order_id
            if src:
                rec.company_id = src.company_id
                rec.partner_id = src.partner_id
            else:
                rec.company_id = rec.company_id or self.env.company
                rec.partner_id = rec.partner_id

    @api.depends("sale_order_id", "invoice_id", "company_id")
    def _compute_currency_id(self):
        for rec in self:
            src = rec.invoice_id or rec.sale_order_id
            rec.currency_id = src.currency_id if src else rec.company_id.currency_id

    @api.model
    def _solven_free_name(self, base, company, taken=()):
        name, n = base, 1
        while name in taken or self.with_context(active_test=False).search_count(
                [("name", "=", name), ("company_id", "=", company.id)]):
            n += 1
            name = f"{base}-{n}"
        return name

    @api.model_create_multi
    def create(self, vals_list):
        # Numbers are assigned before the INSERT (no pending-write conflicts).
        taken = set()
        for vals in vals_list:
            if vals.get("name") and vals["name"] != "/":
                continue
            move = self.env["account.move"].browse(vals.get("invoice_id"))
            order = self.env["sale.order"].browse(vals.get("sale_order_id"))
            company = (move.company_id or order.company_id
                       or self.env["res.company"].browse(vals.get("company_id")) or self.env.company)
            if move and move.name not in (False, "/"):
                # Same number as the Commercial Invoice: no sequence is consumed.
                vals["name"] = self._solven_free_name(move.name, company, taken)
            else:
                number = self.env["ir.sequence"].with_company(company).next_by_code(
                    "solven.packing.list", sequence_date=vals.get("date") or fields.Date.context_today(self)
                )
                if not number:
                    raise UserError(_("The SOLVEN Packing List sequence is missing."))
                vals["name"] = number
            taken.add(vals["name"])
        return super().create(vals_list)

    def copy(self, default=None):
        default = dict(default or {}, name="/")
        return super().copy(default)

    @api.depends("sale_order_id.invoice_ids.state")
    def _compute_invoice_candidate_ids(self):
        for rec in self:
            rec.invoice_candidate_ids = (
                rec.sale_order_id._solven_candidate_invoices() if rec.sale_order_id else rec.invoice_id
            )

    @api.depends("invoice_id.solven_proforma_number", "sale_order_id.solven_proforma_number")
    def _compute_proforma(self):
        for rec in self:
            src = rec.invoice_id if rec.invoice_id.solven_proforma_number else rec.sale_order_id
            rec.proforma_number = src.solven_proforma_number or False
            rec.proforma_date = src.solven_proforma_date or False

    # ------------------------------------------------------------------
    # Built from the Commercial Invoice
    # ------------------------------------------------------------------
    @api.model
    def _solven_vals_from_invoice(self, move):
        Line = self.env["solven.packing.list.line"]
        orders = move.solven_sale_order_ids
        vals = {
            "source": "invoice",
            "invoice_id": move.id,
            "sale_order_id": orders.id if len(orders) == 1 else False,
            "company_id": move.company_id.id,
            "line_ids": [
                (0, 0, Line._solven_vals_from_line(
                    line, *move._solven_line_qty(line),
                    sale_line=line.sale_line_ids[:1], invoice_line=line))
                for line in move._solven_lines() if line.product_id
            ],
        }
        vals.update({k: v for k, v in move._solven_export_vals().items() if k != "solven_doc_version"})
        return vals

    def _solven_is_invoice_mirror(self):
        self.ensure_one()
        return self.source == "invoice" and bool(self.invoice_id)

    def _solven_refresh_from_invoice(self):
        """Draft only: re-sync goods lines with the invoice lines (added/removed
        goods, quantities) and shipment fields filled on the invoice. Weights and
        packages the user corrected are kept unless the quantity changed."""
        Line = self.env["solven.packing.list.line"]
        for rec in self.filtered(lambda r: r.state == "draft" and r._solven_is_invoice_mirror()):
            move = rec.invoice_id
            inv_lines = move._solven_lines().filtered("product_id")
            by_inv = {l.invoice_line_id.id: l for l in rec.line_ids if l.invoice_line_id}
            commands = []
            for il in inv_lines:
                qty, uom = move._solven_line_qty(il)
                pl_line = by_inv.pop(il.id, False)
                if not pl_line:
                    commands.append((0, 0, Line._solven_vals_from_line(
                        il, qty, uom, sale_line=il.sale_line_ids[:1], invoice_line=il)))
                    continue
                upd = {}
                if pl_line.product_id != il.product_id:
                    upd = Line._solven_vals_from_line(il, qty, uom, sale_line=il.sale_line_ids[:1], invoice_line=il)
                elif float_compare(pl_line.quantity, qty, precision_rounding=uom.rounding) or pl_line.uom_id != uom:
                    upd = Line._solven_vals_from_line(il, qty, uom, sale_line=il.sale_line_ids[:1], invoice_line=il)
                    upd.pop("name", None)
                if upd:
                    commands.append((1, pl_line.id, upd))
            # Lines whose invoice line disappeared.
            commands += [(2, l.id) for l in by_inv.values()]
            vals = {k: v for k, v in move._solven_export_vals().items() if k != "solven_doc_version"}
            if commands:
                vals["line_ids"] = commands
            if vals:
                rec.write(vals)

    # ------------------------------------------------------------------
    # Checks: blocking errors and non-blocking warnings, never auto-fixed.
    # ------------------------------------------------------------------
    def _solven_check(self):
        """Return (errors, warnings) as lists of strings naming field and documents."""
        self.ensure_one()
        errors, warnings = [], []
        order, inv = self.sale_order_id, self.invoice_id
        if order and order.state == "cancel":
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
            if order:
                if inv.commercial_partner_id != order.partner_id.commercial_partner_id:
                    errors.append(_("Customer: invoice %(i)s is for %(a)s, order %(o)s is for %(b)s.",
                                    i=inv.name, a=inv.commercial_partner_id.name,
                                    o=order.name, b=order.partner_id.commercial_partner_id.name))
                if order not in inv.solven_sale_order_ids:
                    warnings.append(_("Invoice %(i)s was not generated from order %(o)s.", i=inv.name, o=order.name))
                if inv.currency_id != order.currency_id:
                    warnings.append(_("Currency: invoice %(i)s uses %(a)s, order uses %(b)s.",
                                      i=inv.name, a=inv.currency_id.name, b=order.currency_id.name))
            if inv.solven_acid_number and (inv.solven_acid_number or False) != (self.solven_acid_number or False):
                warnings.append(_("ACID No.: packing list has '%(a)s', invoice %(i)s has '%(b)s'.",
                                  a=self.solven_acid_number or "-", i=inv.name, b=inv.solven_acid_number))
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
            if not (rec.sale_order_id or rec.invoice_id):
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
                raise UserError(_("Packing List %(n)s cannot be issued:\n%(e)s", n=rec.solven_number, e="\n".join(errors)))
            rec.state = "done"

    def action_cancel(self):
        self.write({"state": "cancel"})

    def action_draft(self):
        self.filtered(lambda r: r.state == "cancel").write({"state": "draft"})

    def action_fill_from_invoice(self):
        """Copy the shipment fields of the related invoice (only those set there)
        and, for invoice-sourced lists, re-sync the goods lines."""
        for rec in self.filtered(lambda r: r.invoice_id and r.state == "draft"):
            if rec._solven_is_invoice_mirror():
                rec._solven_refresh_from_invoice()
            else:
                rec.write({k: v for k, v in rec.invoice_id._solven_export_vals().items()
                           if k != "solven_doc_version"})

    def action_print(self):
        return self.env.ref("solven_export_invoice.action_report_solven_packing_list").report_action(self)

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
        """dict(qty, uom, net, gross, packages, cbm); qty only when all lines share a unit."""
        self.ensure_one()
        lines = self.line_ids
        uoms = lines.uom_id
        same_uom = len(uoms) == 1
        return {
            "qty": sum(lines.mapped("quantity")) if same_uom else False,
            "uom": uoms.name if same_uom else False,
            "net": sum(lines.mapped("net_weight")),
            "gross": sum(lines.mapped("gross_weight")),
            "packages": sum(lines.mapped("package_count")) or False,
            "package_type": (lines.mapped("package_type")[0] if len(set(lines.mapped("package_type"))) == 1
                             and lines[:1].package_type else False),
            "cbm": sum(lines.mapped("volume_cbm")) if lines and all(lines.mapped("volume_cbm")) else False,
        }

    def _solven_destination_country(self):
        src = self.invoice_id or self.sale_order_id
        return src._solven_destination_country() if src else self.env["res.country"]


class SolvenPackingListLine(models.Model):
    _name = "solven.packing.list.line"
    _description = "SOLVEN Packing List Line"
    _order = "sequence, id"

    packing_id = fields.Many2one("solven.packing.list", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="packing_id.company_id", store=True)
    sequence = fields.Integer(default=10)
    sale_line_id = fields.Many2one("sale.order.line", "Order Line", ondelete="set null")
    invoice_line_id = fields.Many2one("account.move.line", "Invoice Line", ondelete="set null")
    product_id = fields.Many2one("product.product", "Product", required=True)
    name = fields.Char("Description", required=True)
    quantity = fields.Float("Quantity", digits="Product Unit", required=True, default=1.0)
    uom_id = fields.Many2one("uom.uom", "Unit", required=True)
    package_count = fields.Integer("Packages")
    package_type_choice = fields.Selection(PACKAGE_TYPES, "Packaging")
    package_type = fields.Char("Package Type", help="e.g. Carton, Pallet, Drum.")
    marks = fields.Char("Marks & Nos.")
    net_weight = fields.Float("Net Weight (kg)", digits="Stock Weight",
                              help="Net weight of this line for this shipment.")
    gross_weight = fields.Float("Gross Weight (kg)", digits="Stock Weight",
                                help="Gross weight of this line for this shipment.")
    volume_cbm = fields.Float("Volume (m³)", digits=(16, 3),
                              help="Shipment volume of this line; filled from the product volume when known.")

    def _solven_packing_text(self):
        """'<product packing> · <count> <package type> · Marks' with empty parts omitted."""
        self.ensure_one()
        count = f"{self.package_count:,} {self.package_type or ''}".strip() if self.package_count else False
        return " · ".join(p for p in (self.product_id.product_tmpl_id.solven_packing, count) if p)

    @api.model
    def _solven_product_defaults(self, product, qty, uom):
        """Shipment defaults from the product master; nothing is invented."""
        tmpl = product.product_tmpl_id
        base_qty = _to_product_uom(qty, uom, product)
        vals = {}
        if tmpl.weight:
            vals["net_weight"] = tmpl.weight * base_qty
        if tmpl.solven_gross_weight:
            vals["gross_weight"] = tmpl.solven_gross_weight * base_qty
        if tmpl.volume:
            vals["volume_cbm"] = tmpl.volume * base_qty
        if tmpl.solven_package_type:
            vals["package_type_choice"] = tmpl.solven_package_type
            if tmpl.solven_package_type != "other":
                vals["package_type"] = tmpl.solven_package_type
        if tmpl.solven_units_per_package and not float_is_zero(base_qty, precision_digits=6):
            vals["package_count"] = int(math.ceil(base_qty / tmpl.solven_units_per_package - 1e-9))
        return vals

    @api.model
    def _solven_vals_from_line(self, line, qty, uom, sale_line=None, invoice_line=None):
        product = line.product_id
        vals = {
            "product_id": product.id,
            "name": product.name or line.name,
            "quantity": qty,
            "uom_id": uom.id,
            "sale_line_id": sale_line.id if sale_line else False,
            "invoice_line_id": invoice_line.id if invoice_line else False,
            "net_weight": 0.0, "gross_weight": 0.0, "volume_cbm": 0.0, "package_count": 0,
        }
        vals.update(self._solven_product_defaults(product, qty, uom))
        return vals

    @api.onchange("product_id")
    def _onchange_product_id(self):
        if self.product_id:
            self.name = self.product_id.name
            self.uom_id = self.product_id.uom_id
            for k, v in self._solven_product_defaults(self.product_id, self.quantity, self.uom_id).items():
                self[k] = v

    @api.onchange("quantity", "uom_id")
    def _onchange_quantity(self):
        if self.product_id and self.uom_id:
            for k, v in self._solven_product_defaults(self.product_id, self.quantity, self.uom_id).items():
                if k in ("net_weight", "gross_weight", "volume_cbm", "package_count"):
                    self[k] = v

    @api.onchange("package_type_choice")
    def _onchange_package_type_choice(self):
        if self.package_type_choice and self.package_type_choice != "other":
            self.package_type = self.package_type_choice

    @api.model_create_multi
    def create(self, vals_list):
        # Manual lines: pre-fill empty shipment values from the product master.
        for vals in vals_list:
            if vals.get("package_type_choice") and vals["package_type_choice"] != "other":
                vals["package_type"] = vals["package_type_choice"]
            if "net_weight" in vals and "invoice_line_id" in vals:
                continue
            product = self.env["product.product"].browse(vals.get("product_id"))
            uom = self.env["uom.uom"].browse(vals.get("uom_id")) or product.uom_id
            for k, v in self._solven_product_defaults(product, vals.get("quantity", 1.0), uom).items():
                if not vals.get(k):
                    vals[k] = v
        return super().create(vals_list)

    def write(self, vals):
        if vals.get("package_type_choice") and vals["package_type_choice"] != "other":
            vals = dict(vals, package_type=vals["package_type_choice"])
        return super().write(vals)
