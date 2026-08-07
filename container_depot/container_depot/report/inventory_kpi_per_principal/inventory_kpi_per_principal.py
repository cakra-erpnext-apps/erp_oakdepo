"""Inventory KPI per Principal (PRD v0.2 §6).

One row per principal (Container.principal -> Customer) with the v0.2 inventory
KPIs, optionally scoped to a single depot via the ``depot`` filter:

- Stock In Depo   — containers currently in the depot (status != Gate_Out)
- Dirty / Clean   — by Container.cleaning_status
- Total IN / OUT  — submitted Container Booking items by direction
- Total Cleaned   — submitted, Completed Cleaning Orders
- Total PT2.5 / PT5 — Periodic Tests by type
- PP Wash / Methanol / Steam — Cleaning Orders by chosen service / legacy type

All activity counts are attributed to the principal that owns the container the
activity is against. Cleaning sub-types (§2) and depot (§3) and Periodic Test
(§4) are the upstream sources, so this report only lights up once those carry
data.
"""

from __future__ import annotations

import frappe


def execute(filters=None):
	filters = filters or {}
	depot = filters.get("depot")
	return _columns(), _data(depot)


def _columns():
	def col(fieldname, label, width=110, fieldtype="Int"):
		return {"fieldname": fieldname, "label": label, "fieldtype": fieldtype, "width": width}

	return [
		{"fieldname": "principal", "label": "Principle", "fieldtype": "Link", "options": "Customer", "width": 200},
		col("stock_in_depo", "Stock Tank In Depo", 130),
		col("dirty", "Dirty Tank"),
		col("clean", "Clean Tank"),
		col("total_in", "Total IN"),
		col("total_out", "Total OUT"),
		col("total_cleaned", "Total Cleaned"),
		col("pt_25", "Total PT2,5"),
		col("pt_5", "Total PT5"),
		col("pp_wash", "Total PP Wash"),
		col("methanol", "Total Methanol Rinse", 150),
		col("steam", "Total Steam Wash", 140),
	]


def _data(depot):
	# Container-based metrics (principal + cleaning_status live on Container).
	stock = _container_counts(depot, "status != 'Gate_Out'")
	dirty = _container_counts(depot, "cleaning_status IN ('Pending', 'In_Progress')")
	clean = _container_counts(depot, "cleaning_status = 'Completed'")

	# Activity metrics, attributed via the container's principal.
	total_in = _booking_counts(depot, "Tank In")
	total_out = _booking_counts(depot, "Tank Out")
	total_cleaned = _cleaned_counts(depot, None)
	pp_wash = _cleaned_counts(depot, "PP Wash")
	methanol = _cleaned_counts(depot, "Methanol Rinse")
	steam = _cleaned_counts(depot, "Steam Wash")
	pt_25 = _pt_counts(depot, "2,5Y")
	pt_5 = _pt_counts(depot, "5Y")

	principals = set()
	for d in (stock, dirty, clean, total_in, total_out, total_cleaned, pp_wash, methanol, steam, pt_25, pt_5):
		principals.update(d.keys())

	rows = []
	for principal in sorted(p for p in principals if p):
		rows.append({
			"principal": principal,
			"stock_in_depo": stock.get(principal, 0),
			"dirty": dirty.get(principal, 0),
			"clean": clean.get(principal, 0),
			"total_in": total_in.get(principal, 0),
			"total_out": total_out.get(principal, 0),
			"total_cleaned": total_cleaned.get(principal, 0),
			"pt_25": pt_25.get(principal, 0),
			"pt_5": pt_5.get(principal, 0),
			"pp_wash": pp_wash.get(principal, 0),
			"methanol": methanol.get(principal, 0),
			"steam": steam.get(principal, 0),
		})
	return rows


def _depot_clause(alias, depot, params):
	if depot:
		params.append(depot)
		return f" AND {alias}.depot = %s"
	return ""


def _container_counts(depot, where):
	params = []
	clause = _depot_clause("c", depot, params)
	rows = frappe.db.sql(
		f"""
		SELECT c.principal AS principal, COUNT(*) AS c
		FROM `tabContainer` c
		WHERE c.principal IS NOT NULL AND c.principal != ''
		  AND ({where}){clause}
		GROUP BY c.principal
		""",
		tuple(params),
		as_dict=True,
	)
	return {r["principal"]: r["c"] for r in rows}


def _booking_counts(depot, direction):
	params = [direction]
	clause = _depot_clause("c", depot, params)
	rows = frappe.db.sql(
		f"""
		SELECT c.principal AS principal, COUNT(*) AS c
		FROM `tabContainer Booking Item` it
		JOIN `tabContainer Booking` b ON it.parent = b.name
		JOIN `tabContainer` c ON it.container = c.name
		WHERE b.direction = %s AND b.docstatus < 2
		  AND c.principal IS NOT NULL AND c.principal != ''{clause}
		GROUP BY c.principal
		""",
		tuple(params),
		as_dict=True,
	)
	return {r["principal"]: r["c"] for r in rows}


def _cleaned_counts(depot, method):
	"""Finished cleanings per principal. ``method`` narrows to a cleaning kind, matched
	against the chosen Service item names (the current mechanism) or the legacy
	``cleaning_type`` free-text kept on older orders."""
	params = []
	method_clause = ""
	if method:
		like = f"%{method}%"
		params.extend([method, like])
		method_clause = (
			" AND (co.cleaning_type = %s OR EXISTS ("
			"   SELECT 1 FROM `tabCleaning Order Service` cos"
			"   WHERE cos.parent = co.name AND cos.item_name LIKE %s))"
		)
	clause = _depot_clause("c", depot, params)
	rows = frappe.db.sql(
		f"""
		SELECT c.principal AS principal, COUNT(*) AS c
		FROM `tabCleaning Order` co
		JOIN `tabContainer` c ON co.container = c.name
		WHERE co.docstatus = 1 AND co.status = 'Completed'
		  AND c.principal IS NOT NULL AND c.principal != ''{method_clause}{clause}
		GROUP BY c.principal
		""",
		tuple(params),
		as_dict=True,
	)
	return {r["principal"]: r["c"] for r in rows}


def _pt_counts(depot, test_type):
	params = [test_type]
	clause = _depot_clause("c", depot, params)
	rows = frappe.db.sql(
		f"""
		SELECT c.principal AS principal, COUNT(*) AS c
		FROM `tabPeriodic Test` pt
		JOIN `tabContainer` c ON pt.container = c.name
		WHERE pt.test_type = %s AND pt.docstatus < 2
		  AND c.principal IS NOT NULL AND c.principal != ''{clause}
		GROUP BY c.principal
		""",
		tuple(params),
		as_dict=True,
	)
	return {r["principal"]: r["c"] for r in rows}
