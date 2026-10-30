from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .export_mixin import EXPORT_FIELDS, SOLVEN_CURRENCIES, SOLVEN_DEFAULT_CURRENCY


class SaleOrder(models.Model):
    _name = "sale.order"
    _inherit = ["sale.order", "solven.export.mixin"]

    # Proforma identity: issued once, never regenerated on reprint.
    solven_proforma_number = fields.Char(
        "Proforma Invoice No.", readonly=True, copy=False, index=True,
        help="Assigned once from the SOLVEN Proforma sequence when the quotation "
             "is converted to a Proforma Invoice. Reprinting keeps this number.",
    )
    solven_proforma_date = fields.Date("Proforma Invoice Date", readonly=True, copy=False)
    solven_packing_list_ids = fields.One2many(
        "solven.packing.list", "sale_order_id", string="Packing Lists", copy=False
    )
    solven_packing_list_count = fields.Integer(compute="_compute_solven_packing_list_count")

    # Incoterms 2020 on the order (sale_stock is not required). Carried to the
    # invoice's native invoice_incoterm_id / incoterm_location.
    solven_incoterm_id = fields.Many2one("account.incoterms", "Incoterms")
    solven_incoterm_place = fields.Char("Incoterm Named Place")

    # Visible currency selector. It is not a display-only field: it drives the
    # native pricelist_id, which in turn sets Odoo's real currency_id.
    solven_currency_id = fields.Many2one(
        "res.currency", "Order Currency",
        compute="_compute_solven_currency_id", inverse="_inverse_solven_currency_id",
        domain=lambda self: [("name", "in", SOLVEN_CURRENCIES)],
        help="Currency of this quotation/order. Changing it selects the matching "
             "SOLVEN pricelist; use Update Prices to re-price existing lines.",
    )

    _solven_proforma_number_uniq = models.Constraint(
        "UNIQUE(company_id, solven_proforma_number)",
        "Proforma Invoice numbers must be unique per company.",
    )

    def _compute_solven_packing_list_count(self):
        for order in self:
            order.solven_packing_list_count = len(order.solven_packing_list_ids)

    # ------------------------------------------------------------------
    # Create Invoice: resume an existing draft instead of getting stuck
    # ------------------------------------------------------------------
    solven_draft_invoice_ids = fields.Many2many(
        "account.move", compute="_compute_solven_draft_invoice_ids", string="Draft Invoices")
    solven_draft_invoice_count = fields.Integer(compute="_compute_solven_draft_invoice_ids")

    @api.depends("invoice_ids.state", "invoice_ids.move_type")
    def _compute_solven_draft_invoice_ids(self):
        for order in self:
            drafts = order.invoice_ids.filtered(
                lambda m: m.state == "draft" and m.move_type == "out_invoice")
            order.solven_draft_invoice_ids = drafts
            order.solven_draft_invoice_count = len(drafts)

    def action_solven_continue_invoice(self):
        """Reopen the draft invoice(s) already created from this order.

        Odoo counts draft invoice lines as invoiced, so after a first click on
        Create Invoice the native button disappears. Leaving the draft (to
        check or edit the order) must not block the user: this reopens the
        existing draft so the process continues without a duplicate."""
        self.ensure_one()
        drafts = self.solven_draft_invoice_ids
        if not drafts:
            raise UserError(_("There is no draft invoice to continue for %s.", self.name))
        return self.action_view_invoice(invoices=drafts)

    # ------------------------------------------------------------------
    # Currency (through the native pricelist)
    # ------------------------------------------------------------------
    @api.depends("pricelist_id", "currency_id")
    def _compute_solven_currency_id(self):
        for order in self:
            order.solven_currency_id = order.currency_id

    def _inverse_solven_currency_id(self):
        for order in self:
            currency = order.solven_currency_id
            if currency and currency != order.currency_id:
                if order.state not in ("draft", "sent"):
                    raise UserError(_("The currency of a confirmed order cannot be changed."))
                order.pricelist_id = self.env["product.pricelist"]._solven_get_pricelist(
                    currency, order.company_id)

    @api.onchange("solven_currency_id")
    def _onchange_solven_currency_id(self):
        currency = self.solven_currency_id
        if currency and currency != self.currency_id and self.state in ("draft", "sent"):
            self.pricelist_id = self.env["product.pricelist"]._solven_get_pricelist(
                currency, self.company_id)

    def _compute_pricelist_id(self):
        """Native pricelist logic first; a customer without a specific
        pricelist gets the USD SOLVEN pricelist (USD is the default currency)."""
        super()._compute_pricelist_id()
        Pricelist = self.env["product.pricelist"]
        for order in self:
            if order.state != "draft" or not order.partner_id:
                continue
            partner = order.partner_id.commercial_partner_id
            if partner.specific_property_product_pricelist:
                continue
            usd = self.env["res.currency"].search([("name", "=", SOLVEN_DEFAULT_CURRENCY)], limit=1)
            if usd and order.pricelist_id.currency_id != usd:
                order.pricelist_id = Pricelist._solven_get_pricelist(usd, order.company_id)

    # ------------------------------------------------------------------
    # Quotation -> Proforma Invoice
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
        """Convert the quotation to a Proforma Invoice: the Proforma is this same
        record (customer, lines, prices, taxes, currency, terms and shipment
        data are reused, nothing is retyped) with its own Proforma number."""
        self._solven_ensure_proforma_number()
        return self.env.ref("solven_export_invoice.action_report_solven_proforma_invoice").report_action(self)

    def action_solven_print_quotation(self):
        return self.env.ref("solven_export_invoice.action_report_solven_quotation").report_action(self)

    # ------------------------------------------------------------------
    # Packing lists (split shipments from the order are still possible)
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
                (0, 0, self.env["solven.packing.list.line"]._solven_vals_from_line(
                    line, *self._solven_line_qty(line), sale_line=line))
                for line in self._solven_lines() if line.product_id
            ],
        }
        vals.update({k: v for k, v in self._solven_export_vals().items() if k != "solven_doc_version"})
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
        vals.update(self._solven_export_vals())
        if self.solven_proforma_number:
            vals["solven_proforma_number"] = self.solven_proforma_number
            vals["solven_proforma_date"] = self.solven_proforma_date
        if self.solven_incoterm_id and not vals.get("invoice_incoterm_id"):
            vals["invoice_incoterm_id"] = self.solven_incoterm_id.id
        if self.solven_incoterm_place and not vals.get("incoterm_location"):
            vals["incoterm_location"] = self.solven_incoterm_place
        return vals

    def _solven_lines(self):
        self.ensure_one()
        return self.order_line.filtered(lambda l: not l.display_type)

    def _solven_line_qty(self, line):
        uom = line.product_uom_id if "product_uom_id" in line._fields else line.product_uom
        return line.product_uom_qty, uom or line.product_id.uom_id

    def _solven_customer_po(self):
        return self.client_order_ref

    def _solven_destination_country(self):
        """Destination country: delivery address first, then customer."""
        self.ensure_one()
        for partner in (self.partner_shipping_id, self.partner_id):
            if partner and partner.country_id:
                return partner.country_id
        return self.env["res.country"]


class ProductPricelist(models.Model):
    _inherit = "product.pricelist"

    @api.model
    def _solven_get_pricelist(self, currency, company=None):
        """Return (creating it if needed) the SOLVEN pricelist of a currency."""
        company = company or self.env.company
        domain = [("currency_id", "=", currency.id), ("company_id", "in", (company.id, False))]
        pricelist = self.sudo().search(domain + [("name", "=like", "SOLVEN %")], limit=1) \
            or self.sudo().search(domain, limit=1)
        if not pricelist:
            if not currency.active:
                currency.sudo().active = True
            pricelist = self.sudo().create({
                "name": f"SOLVEN {currency.name}",
                "currency_id": currency.id,
                "company_id": False,
            })
        return pricelist.sudo(False)


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    @api.model
    def _solven_product_from_description(self, description):
        """Product for a line that only has a typed description.

        Odoo requires a product on every sales line, so a line typed without
        picking a product would be lost. Reuse a product with exactly that
        name, otherwise create one, so the typed line is saved and printed."""
        name = (description or "").strip().splitlines()[0].strip()
        Product = self.env["product.product"]
        product = Product.search([("name", "=", name), ("sale_ok", "=", True)], limit=1)
        if not product:
            product = Product.create({"name": name, "type": "consu", "sale_ok": True})
        return product

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if (not vals.get("display_type") and not vals.get("product_id")
                    and not vals.get("is_downpayment") and (vals.get("name") or "").strip()):
                product = self._solven_product_from_description(vals["name"])
                vals["product_id"] = product.id
                vals.setdefault("product_uom_id", product.uom_id.id)
        return super().create(vals_list)

