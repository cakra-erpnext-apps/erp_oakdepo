import frappe


def execute():
	"""Fill ``truck_plate`` / ``driver_name`` on existing Gate Entry records.

	The gate log has carried both columns since day one and nothing ever wrote them —
	"Riwayat Gate" read them off Gate Entry and showed "—" for every row, while the plate
	and driver the guard typed sat on the bon (per-container on an Order Bongkar row,
	on the header for an Order Muat). The writers are fixed going forward
	(``OrderBongkar._record_gate_in`` and ``gate.mark_gate_out``); this recovers the
	history already on file.

	Only records that name their bon can be attributed. A gate-out logged for a tank whose
	arrival was never bonned has no ``order_ref`` at all, and guessing one from the
	container would put a plate against the wrong visit — those are left blank and counted.
	"""
	if not frappe.db.table_exists("Gate Entry"):
		return

	# Tank In — the bon's container rows ARE Container Booking Item rows, and the field is
	# `driver` there against `driver_name` on Gate Entry.
	frappe.db.sql(
		"""UPDATE `tabGate Entry` g
		   JOIN `tabContainer Booking Item` i
		     ON i.parenttype = 'Order Bongkar'
		    AND i.parent = g.order_ref
		    AND i.container_no = g.container_no
		   SET g.truck_plate = COALESCE(NULLIF(g.truck_plate, ''), i.truck_plate),
		       g.driver_name = COALESCE(NULLIF(g.driver_name, ''), i.driver)
		   WHERE g.order_doctype = 'Order Bongkar'
		     AND (g.truck_plate IS NULL OR g.truck_plate = ''
		          OR g.driver_name IS NULL OR g.driver_name = '')"""
	)

	# Tank Out — one truck per bon, on the header.
	frappe.db.sql(
		"""UPDATE `tabGate Entry` g
		   JOIN `tabOrder Muat` m ON m.name = g.order_ref
		   SET g.truck_plate = COALESCE(NULLIF(g.truck_plate, ''), m.truck_plate),
		       g.driver_name = COALESCE(NULLIF(g.driver_name, ''), m.driver_name)
		   WHERE g.order_doctype = 'Order Muat'
		     AND (g.truck_plate IS NULL OR g.truck_plate = ''
		          OR g.driver_name IS NULL OR g.driver_name = '')"""
	)

	orphans = frappe.db.count("Gate Entry", {"order_ref": ["in", [None, ""]]})
	if orphans:
		print(f"backfill_gate_entry_vehicle: {orphans} Gate Entry rows have no bon — vehicle left blank")
