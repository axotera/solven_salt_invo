# SOLVEN Export Invoice (Odoo 19 Community)

Adds four A4 export documents, built from the approved SOLVEN invoice design
(210x297 mm page, 200 mm frame, #E6E6E6 heading strips):

| Print menu entry            | Record                                   |
|-----------------------------|------------------------------------------|
| SOLVEN Commercial Invoice   | Posted customer invoice / credit note    |
| SOLVEN Proforma Invoice     | Sales order                              |
| SOLVEN Quotation            | Sales order (shows Validity Date)        |
| SOLVEN Packing List         | Packing List record (Sales > SOLVEN Packing Lists) |

Standard Odoo invoice / quotation / pro-forma reports are left unchanged.

## Document numbers and links (v19.0.1.2.0)

```
Customer -> Sales Order -> Proforma (PI/YYYY/NNNN) -> posted Invoice (Odoo number) -> Packing List(s) (PL/YYYY/NNNN)
```

- **Quotation**: the sales order number.
- **Proforma Invoice**: own number + date, issued once (button *Issue Proforma No.*
  on the order, or automatically on first print). Reprints keep it.
- **Commercial Invoice**: always the official posted Odoo invoice number and
  date. Shows the related Proforma number/date and the ACID No.
- **Packing List**: its own record with its own number and date. Created from a
  confirmed order (*Create Packing List*). The related invoice is pre-selected
  only when exactly one posted invoice exists; otherwise you must choose.
  One order can have several invoices and packing lists; one invoice can have
  several packing lists (split shipments). Shipment weights and packages are
  entered on the packing list lines (pre-filled from product weights if set).
- **ACID No.**: on the order (copied to the invoice and packing list). Tick
  *ACID Required* for destinations that need it; a missing ACID then prints as
  MISSING and is warned about.
- **Checks** (yellow box on the packing list): wrong customer, cancelled or
  unposted invoice, invoice from another order, ACID / Proforma / currency
  mismatch, packed quantity above invoiced quantity across all packing lists,
  missing weights or HS codes. *Issue* is blocked on errors. Posted invoices
  are never changed automatically.
- Missing required references print in red as **MISSING**; nothing is invented.

## Install / update
Back up your database first and test on a copy before production.
1. Unzip so the folder `solven_export_invoice/` sits in one of your addons paths.
2. Restart Odoo, enable Developer Mode, Apps > Update Apps List.
3. Search "SOLVEN Export Documents" and click Activate (needs Invoicing + Sales).
   Updating an existing install: replace the folder, restart Odoo, then
   Apps > SOLVEN Export Documents > Upgrade (or `odoo -u solven_export_invoice -d <db>`).
   Upgrading from 19.0.1.1.0 was tested; the order-level packing-list print
   entry is replaced by the Packing List record.
4. Odoo must have wkhtmltopdf 0.12.6 (patched Qt) installed, as for any PDF report.

## Fill in your data (nothing is invented; empty fields are hidden)
- Company form > **Export Documents** tab: terms and conditions.
- Company contact > bank account: printed in Bank Details (an invoice's own
  Recipient Bank takes priority).
- Customer > Internal Reference: printed as Customer Code.
- Product > **Export** tab: HS code, packing, net weight (standard Weight), gross weight per unit.
- Sales order / invoice > **Export Details** tab: ports, transport, vessel,
  B/L, container, seal no, loading berth, stowage plan reference, ETD/ATD,
  L/C, country of origin, document version.
  Values on the order are copied to the invoice when it is created.
- Packing List: origin/destination come from the order's Country of Origin
  and the delivery address country; net weight uses the product's standard
  Weight, gross weight the Export tab's Gross Weight per Unit; totals are
  summed over the order lines.
- Incoterm: the invoice's standard Incoterm field. On sales orders it shows
  when the Inventory-based `sale_stock` module adds the field.
- Customer PO: order "Customer Reference" / invoice "Reference".

## Behaviour
- Commercial Invoice refuses drafts and vendor bills (clear error message).
- Totals, taxes, currency, quantities and prices come straight from Odoo.
  With taxes, Sub Total and Taxes print above the grand Total.
- More than ~4 goods lines continue onto a second page.
- Signature & Stamp is left blank for a wet signature.

## Customizing layout, logo and texts
- Shared layout (header, FROM/TO, shipment grid, goods, totals, bank, terms):
  `report/solven_document_layout.xml`; Packing List: `report/report_packing_list.xml`.
- Which fields appear in Shipment Details / Payment & Origin: the
  `solven_shipment`, `solven_payment`, `solven_refs`, `solven_vessel` lists in
  each `report/report_*.xml`. Add `, True` as a third item to make a field required
  (printed as MISSING when empty).
- Shipment Details is a 3-column grid with no fixed height (`.sv-ship` /
  `.sv-compact` in `static/src/css/solven_report.css`).
- Logo and corner mark: replace `static/img/logo03.svg` and `static/img/tri03.svg`
  (same file names), then upgrade the module.
- Sequences: Settings > Technical > Sequences, "SOLVEN Proforma Invoice" /
  "SOLVEN Packing List".

## Tests
`odoo -d <test_db> -i solven_export_invoice --test-tags=/solven_export_invoice --stop-after-init`
(never on production).
