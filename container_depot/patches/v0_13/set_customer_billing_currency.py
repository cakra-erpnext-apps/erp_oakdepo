"""Set each Customer's billing currency (``default_currency``) from its Price List.

Some principals (OAK, Bertschi) are quoted in USD via their per-principal Price
List. Without a billing currency, a new Sales Invoice defaults to the company base
(IDR) and collides with the USD price list. We set ``default_currency`` = the
customer's Price List currency whenever that currency is FOREIGN (not a company
base currency), so USD principals invoice in USD.

This is native ERPNext multi-currency — the company base currency is unchanged.
The single-party receivable flag is enabled by
``container_depot.install.ensure_multi_currency_billing`` (also ensured here so the
patch is self-sufficient regardless of hook ordering).

Idempotent + non-destructive: only customers whose ``default_currency`` is empty
are touched, so manual choices and re-runs are preserved.
"""

from __future__ import annotations

import frappe


def backfill() -> int:
	"""Set default_currency from the Price List currency for FOREIGN-currency
	customers. Returns the number updated. Does NOT commit (tests run inside the
	test transaction; ``execute`` commits)."""
	base_currencies = {c for c in frappe.get_all("Company", pluck="default_currency") if c}
	rows = frappe.get_all(
		"Customer",
		filters={"default_price_list": ["is", "set"], "default_currency": ["is", "not set"]},
		fields=["name", "default_price_list"],
	)
	updated = 0
	for r in rows:
		currency = frappe.db.get_value("Price List", r.default_price_list, "currency")
		# Only foreign currency needs an explicit billing currency; base (IDR)
		# customers correctly default to the company currency.
		if not currency or currency in base_currencies:
			continue
		frappe.db.set_value(
			"Customer", r.name, "default_currency", currency, update_modified=False
		)
		updated += 1
	return updated


def execute():
	from container_depot.install import ensure_multi_currency_billing

	ensure_multi_currency_billing()
	backfill()
	frappe.db.commit()
