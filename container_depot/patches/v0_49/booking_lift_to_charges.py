import frappe

_LIFT_COLS = ("lift_item", "lift_rate", "lift_qty", "lift_amount")


def execute():
	"""Move each booking's single lift charge onto the new ``charges`` child table.

	Container Booking used to carry exactly one priced service — ``lift_item`` + a rate
	resolved from the price list — and derived its direction from that item's name. Pricing
	is now a free table (any number of services, or none) and direction is picked, so the
	old columns become one charge row per booking and are dropped.

	Bookings that never had a lift item (or whose rate was 0) get no row: a booking that
	billed nothing is exactly what an empty charge table means. Idempotent — once the
	columns are gone there is nothing left to migrate.
	"""
	if not (
		frappe.db.table_exists("Container Booking")
		and frappe.db.table_exists("Container Booking Charge")
	):
		return
	if not all(frappe.db.has_column("Container Booking", c) for c in _LIFT_COLS):
		return

	rows = frappe.db.sql(
		"""
		SELECT name, owner, creation, modified, docstatus, currency,
		       lift_item, lift_rate, lift_qty, lift_amount
		FROM `tabContainer Booking`
		WHERE lift_item IS NOT NULL AND lift_item != ''
		""",
		as_dict=True,
	)
	migrated = 0
	for b in rows:
		# Never double-migrate: a booking that already has a charge row is left alone.
		if frappe.db.exists(
			"Container Booking Charge", {"parent": b.name, "parenttype": "Container Booking"}
		):
			continue
		qty = b.lift_qty or frappe.db.count("Container Booking Item", {"parent": b.name}) or 1
		rate = b.lift_rate or 0
		frappe.get_doc({
			"doctype": "Container Booking Charge",
			"parent": b.name,
			"parenttype": "Container Booking",
			"parentfield": "charges",
			"idx": 1,
			# Child rows mirror the parent's docstatus, or a submitted booking's table
			# would come back empty in the UI.
			"docstatus": b.docstatus,
			"item": b.lift_item,
			"item_name": frappe.db.get_value("Item", b.lift_item, "item_name") or b.lift_item,
			"qty": qty,
			"rate": rate,
			"amount": b.lift_amount or (qty * rate),
			"currency": b.currency,
		}).db_insert()
		migrated += 1

	# charges_total mirrors what the old lift_amount already held.
	frappe.db.sql(
		"""
		UPDATE `tabContainer Booking`
		SET charges_total = COALESCE(lift_amount, 0)
		WHERE lift_item IS NOT NULL AND lift_item != ''
		"""
	)

	for col in _LIFT_COLS:
		frappe.db.sql_ddl(f"ALTER TABLE `tabContainer Booking` DROP COLUMN IF EXISTS `{col}`")
	frappe.db.commit()
	print(f"[container_depot] booking_lift_to_charges: {migrated} booking(s) migrated")
