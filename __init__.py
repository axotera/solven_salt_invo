from . import models
from . import report


def post_init_hook(env):
    """Activate the ten SOLVEN currencies and create one pricelist per currency."""
    from .models.export_mixin import SOLVEN_CURRENCIES
    currencies = env["res.currency"].with_context(active_test=False).search(
        [("name", "in", SOLVEN_CURRENCIES)])
    currencies.filtered(lambda c: not c.active).write({"active": True})
    for currency in currencies:
        env["product.pricelist"]._solven_get_pricelist(currency)
