"""Container Depot — DEV-ONLY site bootstrap (setup wizard + master data).

    bench --site <site> execute container_depot.dev_setup.run

Invoked by compose.dev.yaml's create-site so a single `up` yields a site you can
log into and run the test suite against. A bare site has 0 Company and no depot
masters, which makes the app unusable and collapses most of the suite.

⚠️  DEVELOPMENT ONLY — delegates to [seed_dev] for dummy master data. Never run
on production.

Both halves are idempotent (skip-if-exists), so re-running is safe.

Run via ``bench execute``, not ``env/bin/python``: calling ``frappe.init()``
directly misresolves the bench root and dies looking for /home/frappe/logs.
"""

from __future__ import annotations

import frappe

SETUP_ARGS = {
	"language": "English (United States)",
	"country": "Indonesia",
	"timezone": "Asia/Jakarta",
	"currency": "IDR",
	"company_name": "Oak Depo",
	"company_abbr": "OD",
	"chart_of_accounts": "Standard",
	"fy_start_date": "2026-01-01",
	"fy_end_date": "2026-12-31",
	"full_name": "Administrator",
	"email": "admin@example.com",
}


def run() -> None:
	frappe.set_user("Administrator")

	if frappe.db.count("Company"):
		print("[dev_setup] Company already exists — skipping setup wizard.")
	else:
		print("[dev_setup] running ERPNext setup wizard...")
		from frappe.desk.page.setup_wizard.setup_wizard import setup_complete

		setup_complete(SETUP_ARGS)
		frappe.db.commit()

	print("[dev_setup] seeding container_depot dev masters...")
	from container_depot import seed_dev

	seed_dev.run()
	frappe.db.commit()

	for doctype in ("Company", "Item", "Depot", "Branch"):
		print(f"[dev_setup] {doctype}: {frappe.db.count(doctype)}")

	print("[dev_setup] DONE")
