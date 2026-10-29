from odoo import fields, models
from odoo.tools import formatLang

# Field names copied from the sales order to the invoice it generates.
EXPORT_FIELDS = [
    "solven_port_loading",
    "solven_port_discharge",
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
]


class SolvenExportMixin(models.AbstractModel):
    """Optional export information shared by sale.order and account.move.

    Every field is optional; the reports hide empty values instead of
    printing invented data.
    """

    _name = "solven.export.mixin"
    _description = "SOLVEN Export Details"

    solven_port_loading = fields.Char("Port of Loading")
    solven_port_discharge = fields.Char("Port of Discharge")
    solven_transport_mode = fields.Char("Mode of Transport")
    solven_vessel_voyage = fields.Char("Vessel / Voyage")
    solven_bl_number = fields.Char("B/L No.")
    solven_container_number = fields.Char("Container No.")
    solven_seal_number = fields.Char("Seal No.")
    solven_loading_berth = fields.Char("Loading Berth")
    solven_stowage_reference = fields.Char("Stowage Plan Reference")
    solven_etd = fields.Date("ETD")
    solven_atd = fields.Date("ATD")
    solven_lc_number = fields.Char("L/C No.")
    solven_origin_country_id = fields.Many2one(
        "res.country",
        string="Country of Origin",
        default=lambda self: self.env.company.country_id,
    )
    solven_doc_version = fields.Char("Document Version")
    solven_acid_required = fields.Boolean(
        "ACID Required",
        help="Tick when the destination requires an ACID number (e.g. Egyptian "
             "imports). A missing ACID is then reported as a warning.",
    )
    solven_acid_number = fields.Char(
        "ACID No.", help="Advance Cargo Information Declaration number of this shipment."
    )

    # ------------------------------------------------------------------
    # Helpers used by the QWeb templates
    # ------------------------------------------------------------------
    def _solven_fmt_date(self, value):
        return value.strftime("%d %b %Y") if value else False

    def _solven_fmt_qty(self, qty):
        digits = 0 if float(qty).is_integer() else 2
        return formatLang(self.env, qty, digits=digits)

    def _solven_incoterm_label(self):
        # sale.order.incoterm (added by sale_stock) / account.move.invoice_incoterm_id
        inc = False
        for fname in ("incoterm", "invoice_incoterm_id"):
            if fname in self._fields and self[fname]:
                inc = self[fname]
                break
        if not inc:
            return False
        label = inc.code or inc.name
        location = False
        if "incoterm_location" in self._fields:
            location = self.incoterm_location
        if location:
            label = f"{label} {location}"
        return label

    def _solven_address_lines(self, partner):
        """Compact address: street, street2, 'zip city, state, country'."""
        last = " ".join(filter(None, [partner.zip, partner.city]))
        last = ", ".join(filter(None, [last, partner.state_id.name, partner.country_id.name]))
        return [line for line in (partner.street, partner.street2, last) if line]

    def _solven_pairs(self, spec):
        """Return [(label, value)] with empty optional values removed.

        A spec item may be (label, value) or (label, value, required). A
        required item with an empty value is kept with value False so the
        report prints it as visibly MISSING instead of hiding or inventing it.
        """
        pairs = []
        for item in spec:
            label, value = item[0], item[1]
            required = len(item) > 2 and item[2]
            if value or required:
                pairs.append((label, value or False))
        return pairs

    def _solven_rows(self, pairs, cols=3):
        """Split pairs into rows of `cols` cells for the compact shipment grid."""
        return [pairs[i:i + cols] for i in range(0, len(pairs), cols)]

    def _solven_terms(self):
        self.ensure_one()
        return self.company_id.solven_export_terms or False

    def _solven_payment_term(self):
        self.ensure_one()
        for fname in ("invoice_payment_term_id", "payment_term_id"):
            if fname in self._fields and self[fname]:
                return self[fname]
        return self.env["account.payment.term"]

    def _solven_bank_accounts(self):
        self.ensure_one()
        partner_bank = getattr(self, "partner_bank_id", False)
        if partner_bank:
            return partner_bank
        return self.company_id.partner_id.bank_ids[:1]
