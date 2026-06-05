"""Pricing spec §3.3 — seed per-principal selling Price Lists.

Each principal gets its own Price List carrying its own currency (per-principal
currency) and a ``manhour_rate`` (custom field) used to price repair services as
manhour × rate + material. OAK and Bertschi rate cards are in USD (ex-VAT 11%);
local principals default to IDR pending their own contracted rate cards.

Idempotent: existing price lists are kept, with manhour_rate refreshed.
"""

from __future__ import annotations

import frappe

from container_depot.install import setup_custom_fields

# (name, currency, manhour_rate). manhour_rate 0.0 => not yet contracted.
PRICE_LISTS = [
	("OAK 2026", "USD", 4.50),
	("Bertschi 2026", "USD", 4.00),
	# Local principals: currency + rate card to be confirmed per contract.
	("Stolt 2026", "IDR", 0.0),
	("CIMI 2026", "IDR", 0.0),
	("NCS 2026", "IDR", 0.0),
]


def execute():
	# manhour_rate is a custom field declared in install.CUSTOM_FIELDS. Ensure it
	# exists now: post_model_sync patches run BEFORE the after_migrate hook that
	# normally creates custom fields, so on a first migrate the column would not
	# yet exist. setup_custom_fields() is idempotent.
	setup_custom_fields()

	created = 0
	for name, currency, manhour_rate in PRICE_LISTS:
		if not frappe.db.exists("Currency", currency):
			print(f"[container_depot] seed_price_lists: currency {currency} missing; skipped {name}.")
			continue
		if frappe.db.exists("Price List", name):
			frappe.db.set_value("Price List", name, "manhour_rate", manhour_rate, update_modified=False)
			continue
		frappe.get_doc({
			"doctype": "Price List",
			"price_list_name": name,
			"currency": currency,
			"selling": 1,
			"buying": 0,
			"enabled": 1,
			"manhour_rate": manhour_rate,
		}).insert(ignore_permissions=True)
		created += 1

	frappe.db.commit()
	print(f"[container_depot] seed_price_lists: created {created}, ensured {len(PRICE_LISTS)} price list(s).")
