from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.solven_export_invoice.models.export_mixin import SOLVEN_CURRENCIES


@tagged("post_install", "-at_install")
class TestSolvenDocuments(TransactionCase):
    """Numbering, links, currency and report rendering of the SOLVEN documents.
    All values are neutral test fixtures, not business data."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.customer = cls.env["res.partner"].create({"name": "Test Buyer A", "country_id": cls.env.ref("base.nl").id})
        cls.other = cls.env["res.partner"].create({"name": "Test Buyer B"})
        cls.product = cls.env["product.product"].create({
            "name": "Test Product", "type": "consu", "list_price": 10.0,
            "weight": 2.0, "solven_gross_weight": 2.5, "solven_hs_code": "0000.00",
            "volume": 0.01, "solven_package_type": "Carton", "solven_units_per_package": 4,
            "invoice_policy": "order",
        })
        cls.product2 = cls.env["product.product"].create({
            "name": "Second Product", "type": "consu", "list_price": 5.0, "weight": 1.0,
            "invoice_policy": "order",
        })

    def _order(self, partner=None, qty=10.0, confirm=True, **vals):
        order = self.env["sale.order"].create({
            "partner_id": (partner or self.customer).id,
            "order_line": [Command.create({"product_id": self.product.id, "product_uom_qty": qty, "price_unit": 10.0})],
            **vals,
        })
        if confirm:
            order.action_confirm()
        return order

    def _invoice(self, order, post=True):
        move = order._create_invoices()
        if post:
            move.action_post()
        return move

    def _render(self, xmlid, records):
        html, _fmt = self.env["ir.actions.report"]._render_qweb_html(xmlid, records.ids)
        return html.decode()

    # --- Commercial Invoice <-> Packing List: same number, same date ----------
    def test_ci_and_packing_list_share_number_and_date(self):
        order = self._order()
        move = self._invoice(order)
        seq_before = self.env["ir.sequence"].search([("code", "=", "solven.packing.list")]).number_next_actual
        self._render("solven_export_invoice.report_commercial_invoice", move)
        packing = move.solven_packing_list_ids
        self.assertEqual(len(packing), 1)
        self.assertEqual(packing.solven_number, move.name)
        self.assertEqual(packing.date, move.invoice_date)
        self.assertEqual(packing.state, "draft", "Prepared, never auto-issued")
        self.assertEqual(move.state, "posted")
        html = self._render("solven_export_invoice.report_packing_list", packing)
        self.assertIn(move.name, html)
        self.assertIn(move.invoice_date.strftime("%d %b %Y"), html)
        self.assertNotIn("DOCUMENT REFERENCES", html)
        # Reprint: no duplicate, no number consumed.
        self._render("solven_export_invoice.report_commercial_invoice", move)
        move.action_solven_print_documents()
        self.assertEqual(move.solven_packing_list_ids, packing)
        seq_after = self.env["ir.sequence"].search([("code", "=", "solven.packing.list")]).number_next_actual
        self.assertEqual(seq_before, seq_after)

    def test_packing_list_date_follows_invoice(self):
        order = self._order()
        move = self._invoice(order)
        packing = move._solven_prepare_packing_list()
        move.button_draft()
        move.invoice_date = fields.Date.add(move.invoice_date, days=-3)
        move.action_post()
        self.assertEqual(packing.date, move.invoice_date)
        self.assertEqual(packing.solven_number, move.name)

    def test_packing_list_lines_follow_draft_invoice(self):
        order = self._order(qty=8.0)
        move = self._invoice(order)
        packing = move._solven_prepare_packing_list()
        line = packing.line_ids
        self.assertEqual(line.quantity, 8.0)
        self.assertAlmostEqual(line.net_weight, 16.0)
        self.assertAlmostEqual(line.gross_weight, 20.0)
        self.assertAlmostEqual(line.volume_cbm, 0.08)
        self.assertEqual(line.package_count, 2)
        self.assertEqual(line.package_type, "Carton")
        # User corrects weights; a refresh without invoice change keeps them.
        line.gross_weight = 21.0
        move._solven_prepare_packing_list()
        self.assertEqual(packing.line_ids.gross_weight, 21.0)
        # Goods added on the invoice (after reset to draft) appear in the draft list.
        move.button_draft()
        move.invoice_line_ids = [Command.create({"product_id": self.product2.id, "quantity": 3, "price_unit": 5.0})]
        move.action_post()
        move._solven_prepare_packing_list()
        self.assertEqual(len(packing.line_ids), 2)
        # Issued list is never rewritten.
        packing.action_issue()
        move.button_draft()
        move.invoice_line_ids.filtered(lambda l: l.product_id == self.product2).unlink()
        move.action_post()
        move._solven_prepare_packing_list()
        self.assertEqual(len(packing.line_ids), 2)

    def test_draft_invoice_cannot_prepare_packing_list(self):
        move = self._invoice(self._order(), post=False)
        with self.assertRaises(UserError):
            move._solven_prepare_packing_list()
        with self.assertRaises(UserError):
            self._render("solven_export_invoice.report_commercial_invoice", move)

    # --- Quotation -> Proforma -------------------------------------------------
    def test_proforma_conversion_keeps_data_and_number(self):
        order = self._order(confirm=False, solven_port_loading_choice="Damietta, Egypt",
                            client_order_ref="PO-1")
        self.assertEqual(order.solven_port_loading, "Damietta, Egypt")
        self.assertFalse(order.solven_proforma_number)
        action = order.action_solven_issue_proforma()
        self.assertIn("solven_export_invoice.report_proforma_invoice", str(action))
        number, date = order.solven_proforma_number, order.solven_proforma_date
        self.assertTrue(number)
        self.assertEqual(order.state, "draft", "Conversion does not confirm the order")
        html = self._render("solven_export_invoice.report_proforma_invoice", order)
        for text in (number, order.name, "Test Product", "Damietta, Egypt", "PO-1"):
            self.assertIn(text, html)
        self._render("solven_export_invoice.report_proforma_invoice", order)
        self.assertEqual((order.solven_proforma_number, order.solven_proforma_date), (number, date))
        order.action_confirm()
        move = self._invoice(order)
        self.assertEqual(move.solven_proforma_number, number)
        self.assertEqual(move.solven_port_loading, "Damietta, Egypt")

    # --- ACID: only on CI and Packing List, only when filled -------------------
    def test_acid_printing_rules(self):
        order = self._order(solven_acid_required=True, solven_acid_number="ACID-TEST-1")
        for xmlid in ("solven_export_invoice.report_quotation", "solven_export_invoice.report_proforma_invoice"):
            html = self._render(xmlid, order)
            self.assertNotIn("ACID", html)
        move = self._invoice(order)
        self.assertIn("ACID-TEST-1", self._render("solven_export_invoice.report_commercial_invoice", move))
        self.assertIn("ACID-TEST-1", self._render("solven_export_invoice.report_packing_list", move.solven_packing_list_ids))
        empty = self._order(solven_acid_required=True)
        move2 = self._invoice(empty)
        html = self._render("solven_export_invoice.report_commercial_invoice", move2)
        self.assertNotIn("ACID", html)
        self.assertNotIn("MISSING", html)

    def test_acid_linked_between_invoice_and_packing_list(self):
        move = self._invoice(self._order(solven_acid_number="ACID-A"))
        self._render("solven_export_invoice.report_commercial_invoice", move)
        pl = move.solven_packing_list_ids
        self.assertEqual(len(pl), 1)
        self.assertEqual(pl.solven_acid_number, "ACID-A")
        move.solven_acid_number = "ACID-B"
        self.assertEqual(pl.solven_acid_number, "ACID-B")
        pl.solven_acid_number = "ACID-C"
        self.assertEqual(move.solven_acid_number, "ACID-C")
        self.assertIn("ACID-C", self._render("solven_export_invoice.report_packing_list", pl))

    # --- Currency ----------------------------------------------------------------
    def test_currency_default_usd_and_choices(self):
        order = self._order(confirm=False)
        self.assertEqual(order.currency_id.name, "USD")
        self.assertEqual(order.solven_currency_id.name, "USD")
        for code in SOLVEN_CURRENCIES:
            currency = self.env["res.currency"].with_context(active_test=False).search([("name", "=", code)])
            self.assertTrue(currency.active, code)
            order.solven_currency_id = currency
            self.assertEqual(order.pricelist_id.currency_id, currency)
            self.assertEqual(order.currency_id, currency)
        egp = self.env.ref("base.EGP")
        order.solven_currency_id = egp
        order.action_confirm()
        move = self._invoice(order)
        self.assertEqual(move.currency_id, egp)
        html = self._render("solven_export_invoice.report_commercial_invoice", move)
        self.assertIn("EGP", html)
        with self.assertRaises(UserError):
            order.solven_currency_id = self.env.ref("base.USD")

    # --- Split shipments from the order are still supported -------------------
    def test_order_packing_lists_split(self):
        order = self._order(qty=10.0)
        move = self._invoice(order)
        pl1 = self.env["solven.packing.list"].browse(order.action_solven_create_packing_list()["res_id"])
        self.assertEqual(pl1.invoice_id, move)
        self.assertEqual(pl1.solven_number, move.name)
        self.assertEqual(pl1.date, move.invoice_date)
        pl1.line_ids.quantity = 6.0
        pl2 = self.env["solven.packing.list"].browse(order.action_solven_create_packing_list()["res_id"])
        pl2.line_ids.quantity = 4.0
        self.assertNotIn("Quantity:", pl2.warning_text or "")
        pl2.line_ids.quantity = 5.0
        self.assertIn("Quantity:", pl2.warning_text)
        pl1.action_issue()
        self.assertEqual(pl1.state, "done")

    def test_cancelled_and_wrong_customer(self):
        order = self._order()
        move = self._invoice(order)
        pl = self.env["solven.packing.list"].browse(order.action_solven_create_packing_list()["res_id"])
        other_move = self._invoice(self._order(partner=self.other))
        pl.invoice_id = other_move
        self.assertIn("ERROR: Customer", pl.warning_text)
        with self.assertRaises(UserError):
            pl.action_issue()
        pl.invoice_id = move
        move.button_draft()
        move.button_cancel()
        self.assertIn("is cancelled", pl.warning_text)
        pl.action_cancel()
        self.assertIn("CANCELLED", self._render("solven_export_invoice.report_packing_list", pl))

    def test_reports_render_with_long_values(self):
        long_port = "Port " + "Verylongportname" * 6
        order = self._order(solven_port_loading=long_port, solven_vessel_voyage="Vessel & <Test> ü عربي")
        for xmlid in ("solven_export_invoice.report_quotation", "solven_export_invoice.report_proforma_invoice"):
            self.assertIn(long_port, self._render(xmlid, order))
        move = self._invoice(order)
        self.assertIn(long_port, self._render("solven_export_invoice.report_commercial_invoice", move))
        self.assertIn("Vessel &amp; &lt;Test&gt;", self._render("solven_export_invoice.report_packing_list",
                                                                  move.solven_packing_list_ids))

    def test_packaging_description_and_add_note_print_inline(self):
        order = self.env["sale.order"].create({
            "partner_id": self.customer.id,
            "note": "Default Odoo Terms for SOLVEN",
            "order_line": [
                Command.create({
                    "product_id": self.product.id,
                    "product_uom_qty": 2,
                    "price_unit": 10,
                    "name": "Test Product\nFine refined salt 99.5%",
                    "solven_packaging_ids": [Command.set([
                        self.env.ref("solven_export_invoice.pack_pp25").id,
                        self.env.ref("solven_export_invoice.pack_custom").id,
                    ])],
                    "solven_packaging_custom": "Big blue bags",
                }),
                Command.create({"display_type": "line_note", "name": "Shipment within 2 weeks"}),
            ],
        })
        order.company_id.solven_export_terms = "Company default export terms"
        html = self._render("solven_export_invoice.report_quotation", order)
        for text in ("Fine refined salt 99.5%", "25 kg PP Bags", "Big blue bags",
                     "Shipment within 2 weeks", "Default Odoo Terms for SOLVEN"):
            self.assertIn(text, html)
        self.assertNotIn("Test Product - Fine refined salt", html)
        order.action_confirm()
        move = self._invoice(order)
        inv_line = move.invoice_line_ids.filtered(lambda line: line.display_type == "product")
        self.assertEqual(inv_line.solven_packaging_ids, order.order_line.filtered(lambda line: not line.display_type).solven_packaging_ids)
        html = self._render("solven_export_invoice.report_commercial_invoice", move)
        for text in ("25 kg PP Bags", "Big blue bags", "Shipment within 2 weeks"):
            self.assertIn(text, html)
