import frappe


def execute():
	"""Realign existing ``Manhour`` charge rows with the item lines they belong to.

	Labour is not a product of its own — it is the same revenue as the services on the
	invoice, just charged once as a flat amount instead of per unit. So the charge row
	posts exactly where the item lines do, and both its **account** and its **cost center**
	are read from them (see ``invoicing._sync_manhour_charge_row``).

	Rows written before that carried neither: the account came from a separate lookup on
	``Company.default_income_account``, and the cost center was simply never set — which
	let the invoice save but made it fail at SUBMIT with "Cost Center is required for
	'Profit and Loss' account ...".

	Only DRAFT rows are touched: a submitted invoice has already posted its GL and must not
	be rewritten underneath it.
	"""
	if not frappe.db.table_exists("Sales Taxes and Charges"):
		return
	rows = frappe.db.sql(
		"""
		SELECT t.name, t.parent
		FROM `tabSales Taxes and Charges` t
		WHERE t.parenttype = 'Sales Invoice' AND t.docstatus = 0
		  AND t.description = 'Manhour'
		""",
		as_dict=True,
	)
	if not rows:
		return

	fixed = 0
	for r in rows:
		# The invoice's own item lines are the single source for both values.
		item = frappe.db.get_value(
			"Sales Invoice Item",
			{"parent": r.parent, "income_account": ["is", "set"]},
			["income_account", "cost_center"],
			order_by="idx asc",
			as_dict=True,
		)
		if not item:
			continue  # nothing to copy from — the next save resolves it
		frappe.db.set_value(
			"Sales Taxes and Charges",
			r.name,
			{"account_head": item.income_account, "cost_center": item.cost_center},
			update_modified=False,
		)
		fixed += 1
	frappe.db.commit()
	print(f"[container_depot] backfill_manhour_cost_center: {fixed} charge row(s) realigned")
