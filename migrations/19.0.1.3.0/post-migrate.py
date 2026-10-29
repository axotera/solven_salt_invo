from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Upgrade from 19.0.1.2.x: activate SOLVEN currencies/pricelists and give
    packing lists already linked to an invoice the invoice's number/date."""
    from odoo.addons.solven_export_invoice import post_init_hook
    env = api.Environment(cr, SUPERUSER_ID, {})
    post_init_hook(env)
    packs = env["solven.packing.list"].search([])
    packs._compute_solven_number()
    packs.filtered("invoice_id")._compute_date()
