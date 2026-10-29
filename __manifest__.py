{
    "name": "SOLVEN Export Documents",
    "version": "19.0.1.2.0",
    "summary": "SOLVEN Commercial Invoice, Proforma Invoice, Quotation and Packing List (A4 export layout)",
    "description": """
Adds four SOLVEN export documents next to the standard Odoo reports:

* Commercial Invoice  -> posted customer invoices / credit notes (account.move)
* Proforma Invoice    -> sales orders (sale.order)
* Quotation           -> sales orders (sale.order), with validity date
* Packing List        -> own record (solven.packing.list) with its own number,
                         linked to the sales order and posted Commercial Invoice

Standard Odoo invoice / quotation reports are NOT replaced.
Adds optional export fields (ports, vessel, B/L, container, seal,
loading berth, stowage plan reference, ETD/ATD, L/C, country of origin,
HS code, packing, gross weight, export terms).
Empty optional fields are hidden, never invented.
""",
    "category": "Accounting/Accounting",
    "author": "SOLVEN",
    "license": "LGPL-3",
    "depends": ["account", "sale_management", "mail"],
    "data": [
        "security/ir.model.access.csv",
        "security/solven_security.xml",
        "data/paperformat.xml",
        "data/sequences.xml",
        "views/product_views.xml",
        "views/res_company_views.xml",
        "views/sale_order_views.xml",
        "views/account_move_views.xml",
        "views/packing_list_views.xml",
        "report/solven_document_layout.xml",
        "report/report_commercial_invoice.xml",
        "report/report_proforma_invoice.xml",
        "report/report_quotation.xml",
        "report/report_packing_list.xml",
        "report/report_actions.xml",
    ],
    "assets": {
        "web.report_assets_common": [
            "solven_export_invoice/static/src/css/solven_report.css",
        ],
    },
    "installable": True,
    "application": False,
}
