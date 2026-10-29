from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestSolvenDocuments(TransactionCase):
    """Numbering, cross-references and report rendering of the SOLVEN documents.

    All values below are neutral test fixtures, not business data.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.customer = cls.env["res.partner"].create({"name": "Test Buyer A", "country_id": cls.env.ref("base.eg").id})
        cls.other = cls.env["res.partner"].create({"name": "Test Buyer B"})
        cls.product = cls.env["product.product"].create({
            "name": "Test Product", "type": "consu", "list_price": 10.0,
            "weight": 2.0, "solven_gross_weight": 2.5, "solven_hs_code": "0000.00",
            "invoice_policy": "order",
        })

    def _order(self, partner=None, qty=10.0, **vals):
        order = self.env["sale.order"].create({
            "partner_id": (partner or self.customer).id,
            "order_line": [Command.create({"product_id": self.product.id, "product_uom_qty": qty, "price_unit": 10.0})],
            **vals,
        })
        order.action_confirm()
        return order

    def _invoice(self, order):
        move = order._create_invoices()
        move.action_post()
        return move

    def _render(self, xmlid, records):
        html, _fmt = self.env["ir.actions.report"]._render_qweb_html(xmlid, records.ids)
        return html.decode()

    # 1, 8: proforma number stays stable on reprint
    def test_proforma_number_stable(self):
        order = self._order()
        self.assertFalse(order.solven_proforma_number)
        html1 = self._render("solven_export_invoice.report_proforma_invoice", order)
        number, date = order.solven_proforma_number, order.solven_proforma_date
        self.assertTrue(number)
        self.assertIn(number, html1)
        self._render("solven_export_invoice.report_proforma_invoice", order)
        self.assertEqual(order.solven_proforma_number, number)
        self.assertEqual(order.solven_proforma_date, date)

    # 2, 4: commercial invoice shows its own number/date and the proforma reference
    def test_commercial_invoice_refs(self):
        order = self._order(solven_acid_number="ACID-TEST-1")
        order.action_solven_issue_proforma()
        move = self._invoice(order)
        self.assertEqual(move.solven_proforma_number, order.solven_proforma_number)
        self.assertEqual(move.solven_acid_number, "ACID-TEST-1")
        html = self._render("solven_export_invoice.report_commercial_invoice", move)
        self.assertIn(move.name, html)
        self.assertIn(order.solven_proforma_number, html)
        self.assertIn("ACID-TEST-1", html)

    def test_commercial_invoice_refuses_draft(self):
        order = self._order()
        move = order._create_invoices()
        with self.assertRaises(UserError):
            self._render("solven_export_invoice.report_commercial_invoice", move)

    # 3, 6, 8: packing list numbers and invoice references
    def test_packing_list_references_and_split(self):
        order = self._order(qty=10.0)
        order.action_solven_issue_proforma()
        move = self._invoice(order)
        pl1 = self.env["solven.packing.list"].browse(order.action_solven_create_packing_list()["res_id"])
        self.assertEqual(pl1.invoice_id, move, "Single posted invoice is pre-selected")
        self.assertNotEqual(pl1.name, move.name)
        self.assertNotEqual(pl1.name, "/")
        pl1.line_ids.quantity = 6.0
        pl2 = self.env["solven.packing.list"].browse(order.action_solven_create_packing_list()["res_id"])
        pl2.line_ids.quantity = 4.0
        self.assertNotEqual(pl1.name, pl2.name)
        self.assertNotIn("Quantity:", pl2.warning_text or "")
        pl2.line_ids.quantity = 5.0
        self.assertIn("Quantity:", pl2.warning_text)
        pl2.line_ids.quantity = 4.0
        name = pl1.name
        html = self._render("solven_export_invoice.report_packing_list", pl1)
        for text in (pl1.name, move.name, order.solven_proforma_number, "RELATED COMMERCIAL INVOICE NO."):
            self.assertIn(text, html)
        self._render("solven_export_invoice.report_packing_list", pl1)
        self.assertEqual(pl1.name, name)
        pl1.action_issue()
        self.assertEqual(pl1.state, "done")

    # 5: several invoices -> nothing pre-selected, warning lists them
    def test_multiple_invoices_require_selection(self):
        order = self._order(qty=10.0)
        order.order_line.qty_to_invoice  # noqa: B018 - ensure computed
        inv1 = self._invoice(order)
        order2 = self._order(qty=3.0)
        inv2 = self._invoice(order2)
        # Second invoice of the same order via a down payment-free extra line.
        order.order_line = [Command.create({"product_id": self.product.id, "product_uom_qty": 2.0, "price_unit": 10.0})]
        inv3 = self._invoice(order)
        pl = self.env["solven.packing.list"].browse(order.action_solven_create_packing_list()["res_id"])
        self.assertFalse(pl.invoice_id)
        self.assertIn(inv1.name, pl.warning_text)
        self.assertIn(inv3.name, pl.warning_text)
        self.assertNotIn(inv2, pl.invoice_candidate_ids)
        with self.assertRaises(UserError):
            pl.action_issue()

    # 7: missing ACID visible and warned
    def test_missing_acid(self):
        order = self._order(solven_acid_required=True)
        self._invoice(order)
        pl = self.env["solven.packing.list"].browse(order.action_solven_create_packing_list()["res_id"])
        self.assertIn("ACID No.: required", pl.warning_text)
        html = self._render("solven_export_invoice.report_packing_list", pl)
        self.assertIn("MISSING", html)

    # 9: cancelled / foreign documents
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

    # 10: all four reports still render; compact shipment grid wraps long values
    def test_reports_render_with_long_values(self):
        long_port = "Port " + "Verylongportname" * 6
        order = self._order(solven_port_loading=long_port, solven_vessel_voyage="Vessel & <Test> ü عربي")
        for xmlid in ("solven_export_invoice.report_quotation", "solven_export_invoice.report_proforma_invoice"):
            html = self._render(xmlid, order)
            self.assertIn("sv-ship", html)
            self.assertIn(long_port, html)
            self.assertNotIn("sv-h50", html)
        move = self._invoice(order)
        self.assertIn(long_port, self._render("solven_export_invoice.report_commercial_invoice", move))
        pl = self.env["solven.packing.list"].browse(order.action_solven_create_packing_list()["res_id"])
        self.assertIn("Vessel &amp; &lt;Test&gt;", self._render("solven_export_invoice.report_packing_list", pl))
