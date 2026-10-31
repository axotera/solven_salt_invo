from odoo import api, fields, models
from odoo.tools import formatLang, is_html_empty

# Currencies offered in the SOLVEN entry screens (USD is the default).
SOLVEN_CURRENCIES = ["USD", "EUR", "GBP", "JPY", "CNY", "CHF", "CAD", "AUD", "HKD", "EGP"]
SOLVEN_DEFAULT_CURRENCY = "USD"

# Egyptian commercial seaports. "other" keeps the free-text port field editable.
PORT_CHOICES = [
    ("Alexandria, Egypt", "Alexandria"),
    ("El Dekheila, Egypt", "El Dekheila"),
    ("Abu Qir, Egypt", "Abu Qir"),
    ("Damietta, Egypt", "Damietta"),
    ("Port Said, Egypt", "Port Said"),
    ("East Port Said, Egypt", "East Port Said"),
    ("Suez (Port Ibrahim), Egypt", "Suez / Port Ibrahim"),
    ("Adabiya, Egypt", "Adabiya"),
    ("Ain Sokhna, Egypt", "Ain Sokhna"),
    ("Safaga, Egypt", "Safaga"),
    ("Nuweiba, Egypt", "Nuweiba"),
    ("El Arish, Egypt", "El Arish"),
    ("other", "Other (type below)"),
]
TRANSPORT_CHOICES = [
    ("Sea freight", "Sea"),
    ("Air freight", "Air"),
    ("Road freight", "Road"),
    ("Rail freight", "Rail"),
    ("Multimodal", "Multimodal"),
    ("other", "Other (type below)"),
]
PAYMENT_METHODS = [
    ("tt", "T/T (Telegraphic Transfer)"),
    ("lc_sight", "L/C at sight"),
    ("lc_usance", "L/C usance"),
    ("advance", "Advance payment"),
    ("part_advance", "Part advance / balance against documents"),
    ("cad", "Cash against documents (CAD)"),
    ("cheque", "Cheque"),
    ("other", "Other"),
]
PACKAGE_TYPES = [
    ("Carton", "Carton"),
    ("Pallet", "Pallet"),
    ("Wooden Box", "Wooden Box / Crate"),
    ("Bag", "Bag / Sack"),
    ("Drum", "Drum"),
    ("Bundle", "Bundle"),
    ("Bulk", "Bulk"),
    ("other", "Other (type below)"),
]

# Field names copied from the sales order to the invoice it generates
# and from the invoice to its Packing List.
EXPORT_FIELDS = [
    "solven_port_loading_choice",
    "solven_port_loading",
    "solven_port_discharge_choice",
    "solven_port_discharge",
    "solven_transport_choice",
    "solven_transport_mode",
    "solven_vessel_voyage",
    "solven_bl_number",
    "solven_container_number",
    "solven_seal_number",
    "solven_loading_berth",
    "solven_stowage_reference",
    "solven_etd",
    "solven_atd",
    "solven_lc_number",
    "solven_origin_country_id",
    "solven_doc_version",
    "solven_acid_number",
    "solven_acid_required",
    "solven_payment_method",
    "solven_payment_method_other",
    "solven_notify_party_id",
]


class SolvenExportMixin(models.AbstractModel):
    """Optional export information shared by sale.order, account.move and
    solven.packing.list. Every field is optional; the reports hide empty
    values instead of printing invented data."""

    _name = "solven.export.mixin"
    _description = "SOLVEN Export Details"

    # Port / transport: a dropdown drives the stored text, "Other" lets the
    # user type it. Existing text values are kept as they are.
    solven_port_loading_choice = fields.Selection(PORT_CHOICES, "Port of Loading (list)")
    solven_port_loading = fields.Char("Port of Loading")
    solven_port_discharge_choice = fields.Selection(PORT_CHOICES, "Port of Discharge (list)")
    solven_port_discharge = fields.Char("Port of Discharge")
    solven_transport_choice = fields.Selection(TRANSPORT_CHOICES, "Transport")
    solven_transport_mode = fields.Char("Mode of Transport")
    solven_vessel_voyage = fields.Char("Vessel / Voyage")
    solven_bl_number = fields.Char("B/L / AWB No.")
    solven_container_number = fields.Char("Container No.")
    solven_seal_number = fields.Char("Seal No.")
    solven_loading_berth = fields.Char("Loading Berth")
    solven_stowage_reference = fields.Char("Stowage Plan Reference")
    solven_etd = fields.Date("ETD")
    solven_atd = fields.Date("ATD")
    solven_lc_number = fields.Char("L/C No.")
    solven_payment_method = fields.Selection(PAYMENT_METHODS, "Export Payment Method")
    solven_payment_method_other = fields.Char("Payment Method (other)")
    solven_notify_party_id = fields.Many2one("res.partner", "Notify Party")
    solven_origin_country_id = fields.Many2one(
        "res.country",
        string="Country of Origin",
        default=lambda self: self.env.company.country_id,
    )
    solven_doc_version = fields.Char("Document Version")
    solven_acid_required = fields.Boolean(
        "ACID Required",
        help="Tick when the destination requires an ACID number (e.g. Egyptian "
             "imports). A missing ACID is then shown as a warning on screen only.",
    )
    solven_acid_number = fields.Char(
        "ACID No.", help="Advance Cargo Information Declaration number. Printed only on the "
                         "Commercial Invoice and Packing List, and only when filled in.")

    # Dropdown -> stored text. The text field stays the single printed value,
    # so existing records keep their data and "Other" stays free text.
    _SOLVEN_CHOICE_MAP = {
        "solven_port_loading_choice": "solven_port_loading",
        "solven_port_discharge_choice": "solven_port_discharge",
        "solven_transport_choice": "solven_transport_mode",
    }

    @api.model
    def _solven_sync_choice_vals(self, vals):
        for choice, text in self._SOLVEN_CHOICE_MAP.items():
            value = vals.get(choice)
            if value and value != "other":
                vals[text] = value
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._solven_sync_choice_vals(vals)
        return super().create(vals_list)

    def write(self, vals):
        return super().write(self._solven_sync_choice_vals(dict(vals)))

    @api.onchange("solven_port_loading_choice")
    def _onchange_solven_port_loading_choice(self):
        if self.solven_port_loading_choice and self.solven_port_loading_choice != "other":
            self.solven_port_loading = self.solven_port_loading_choice

    @api.onchange("solven_port_discharge_choice")
    def _onchange_solven_port_discharge_choice(self):
        if self.solven_port_discharge_choice and self.solven_port_discharge_choice != "other":
            self.solven_port_discharge = self.solven_port_discharge_choice

    @api.onchange("solven_transport_choice")
    def _onchange_solven_transport_choice(self):
        if self.solven_transport_choice and self.solven_transport_choice != "other":
            self.solven_transport_mode = self.solven_transport_choice

    # ------------------------------------------------------------------
    # Helpers used by the QWeb templates
    # ------------------------------------------------------------------
    def _solven_fmt_date(self, value):
        return value.strftime("%d %b %Y") if value else False

    def _solven_fmt_qty(self, qty):
        digits = 0 if float(qty).is_integer() else 2
        return formatLang(self.env, qty, digits=digits)

    def _solven_fmt_num(self, value, digits=2):
        return formatLang(self.env, value, digits=digits)

    def _solven_incoterm(self):
        for fname in ("solven_incoterm_id", "incoterm", "invoice_incoterm_id"):
            if fname in self._fields and self[fname]:
                return self[fname]
        return False

    def _solven_incoterm_label(self):
        inc = self._solven_incoterm()
        if not inc:
            return False
        label = inc.code or inc.name
        location = False
        for fname in ("solven_incoterm_place", "incoterm_location"):
            if fname in self._fields and self[fname]:
                location = self[fname]
                break
        if location:
            label = f"{label} {location}"
        return f"{label} (Incoterms 2020)"

    def _solven_payment_method_label(self):
        self.ensure_one()
        if self.solven_payment_method == "other":
            return self.solven_payment_method_other or False
        return dict(PAYMENT_METHODS).get(self.solven_payment_method) or False

    def _solven_payment_label(self):
        """'<payment term>, <method>' with empty parts omitted."""
        self.ensure_one()
        term = self._solven_payment_term()
        parts = [term.name if term else False, self._solven_payment_method_label()]
        return " · ".join(p for p in parts if p) or False

    def _solven_address_lines(self, partner):
        """Compact address: street, street2, 'zip city, state, country'."""
        last = " ".join(filter(None, [partner.zip, partner.city]))
        last = ", ".join(filter(None, [last, partner.state_id.name, partner.country_id.name]))
        return [line for line in (partner.street, partner.street2, last) if line]

    def _solven_pairs(self, spec):
        """Return [(label, value)] with empty optional values removed.
        Nothing is ever printed as 'missing' and nothing is invented."""
        return [(item[0], item[1]) for item in spec if item[1]]

    def _solven_rows(self, pairs, cols=3):
        return [pairs[i:i + cols] for i in range(0, len(pairs), cols)]

    def _solven_terms(self):
        self.ensure_one()
        for field_name in ("note", "narration"):
            if field_name in self._fields and not is_html_empty(self[field_name]):
                return self[field_name]
        if self.company_id.solven_export_terms and not is_html_empty(self.company_id.solven_export_terms):
            return self.company_id.solven_export_terms
        terms = getattr(self.company_id, "invoice_terms", False)
        if terms and not is_html_empty(terms):
            return terms
        return False

    def _solven_line_notes(self):
        self.ensure_one()
        lines = self.order_line if self._name == "sale.order" else self.invoice_line_ids
        result, current, pending = {}, None, []
        for line in lines.sorted(lambda item: (item.sequence, item.id)):
            if line.display_type in (False, "product"):
                current = line
                if pending:
                    result.setdefault(line.id, []).extend(pending)
                    pending.clear()
            elif line.display_type == "line_note" and (line.name or "").strip():
                note = " ".join(line.name.split())
                if current:
                    result.setdefault(current.id, []).append(note)
                else:
                    pending.append(note)
            else:
                current = None
        return result

    def _solven_line_description(self, line, notes=None):
        product = line.product_id
        text = (line.name or "").strip()
        if product:
            names = {value.strip() for value in (product.display_name, product.name,
                     product.product_tmpl_id.name) if value and value.strip()}
            for name in sorted(names, key=len, reverse=True):
                if text.startswith(name):
                    text = text[len(name):].lstrip(" \t\r\n-:,·")
                    break
        parts = [" ".join(text.split())]
        if product:
            tmpl = product.product_tmpl_id
            if tmpl.solven_hs_code:
                parts.append(f"HS {tmpl.solven_hs_code}")
            if tmpl.solven_packing:
                parts.append(f"Packing: {tmpl.solven_packing}")
        if "solven_packaging_ids" in line._fields:
            parts.extend(line.solven_packaging_ids.mapped("name"))
            if line.solven_packaging_custom:
                parts.append(line.solven_packaging_custom.strip())
        if line.discount:
            parts.append(f"Discount: {self._solven_fmt_qty(line.discount)}%")
        parts.extend((notes or {}).get(line.id, []))
        return " - ".join(dict.fromkeys(part for part in parts if part))

    def _solven_payment_term(self):
        """Odoo payment term printed on Quotation / Proforma only. The
        Commercial Invoice (account.move) never prints Odoo's default term;
        it shows only the SOLVEN export payment method chosen explicitly."""
        self.ensure_one()
        if self._name == "account.move":
            return self.env["account.payment.term"]
        for fname in ("invoice_payment_term_id", "payment_term_id"):
            if fname in self._fields and self[fname]:
                return self[fname]
        return self.env["account.payment.term"]

    def _solven_bank_accounts(self):
        """Official bank account: the invoice's recipient bank, else the
        company's first configured bank account. Never invented."""
        self.ensure_one()
        partner_bank = self["partner_bank_id"] if "partner_bank_id" in self._fields else False
        if partner_bank:
            return partner_bank
        bank = self.company_id.partner_id.bank_ids[:1]
        if not bank:
            journal = self.env["account.journal"].sudo().search([
                ("type", "=", "bank"), ("company_id", "=", self.company_id.id),
                ("bank_account_id", "!=", False)], limit=1)
            bank = journal.bank_account_id
        return bank

    def _solven_export_vals(self):
        """Values of EXPORT_FIELDS that are set on this record (for copying)."""
        self.ensure_one()
        vals = {}
        for fname in EXPORT_FIELDS:
            value = self[fname]
            if not value:
                continue
            vals[fname] = value.id if isinstance(value, models.BaseModel) else value
        return vals

    @api.model
    def _solven_currency_domain(self):
        return [("name", "in", SOLVEN_CURRENCIES)]


class SolvenPackaging(models.Model):
    _name = "solven.packaging"
    _description = "SOLVEN Product Packaging"
    _order = "sequence, id"

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
