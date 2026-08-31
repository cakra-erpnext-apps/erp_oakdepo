"""Inventory KPI per Principal (PRD v0.2 §6).

One row per principal (Container.principal -> Customer) with the v0.2 inventory
KPIs, optionally scoped to a single depot via the ``depot`` filter:

- Stock In Depo   — containers currently in the depot (status != Gate_Out)
- Dirty / Clean   — in-depo tanks with / without an open Cleaning Order
- Total IN / OUT  — submitted Container Booking items by direction
- Total Cleaned   — submitted, Completed Cleaning Orders
- PP Wash / Methanol / Steam — Cleaning Orders by header Jenis Cleaning or by
  the item code of the service chosen (never by item name — see ``_cleaned_counts``)

All activity counts are attributed to the principal that owns the container the
activity is against. Cleaning sub-types (§2) and depot (§3) are the upstream
sources, so this report only lights up once those carry data.
"""

from __future__ import annotations

import frappe

from container_depot.container_depot.container_status import DONE_CLEANING


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
		col("pp_wash", "Total PP Wash"),
		col("methanol", "Total Methanol Rinse", 150),
		col("steam", "Total Steam Wash", 140),
	]


def _data(depot):
	# Container-based metrics (principal lives on Container).
	stock = _container_counts(depot, "status != 'Gate_Out'")
	# Dirty / Clean used to read Container.cleaning_status, which nothing ever reset —
	# a tank cleaned last cycle counted as Clean forever, gated out or not. Both are
	# asked of the open Cleaning Orders instead, over tanks actually in the depo, so
	# the two columns always add up to Stock In Depo.
	dirty = _container_counts(depot, f"c.status != 'Gate_Out' AND {_OPEN_CLEANING}")
	clean = _container_counts(depot, f"c.status != 'Gate_Out' AND NOT {_OPEN_CLEANING}")

	# Activity metrics, attributed via the container's principal.
	total_in = _booking_counts(depot, "Tank In")
	total_out = _booking_counts(depot, "Tank Out")
	total_cleaned = _cleaned_counts(depot)
	pp_wash = _cleaned_counts(depot, "PP Wash", "INT-PP-WASH")
	methanol = _cleaned_counts(depot, "Methanol Rinse", "INT-METHANOL")
	steam = _cleaned_counts(depot, "Steam Wash", "INT-STEAM")

	principals = set()
	for d in (stock, dirty, clean, total_in, total_out, total_cleaned, pp_wash, methanol, steam):
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
			"pp_wash": pp_wash.get(principal, 0),
			"methanol": methanol.get(principal, 0),
			"steam": steam.get(principal, 0),
		})
	return rows


# "Dirty" = the depot still has cleaning to do on the tank. Terminal statuses come from
# container_status so this can never disagree with what keeps a tank from leaving.
_OPEN_CLEANING = (
	"EXISTS (SELECT 1 FROM `tabCleaning Order` co0"
	"        WHERE co0.container = c.name AND co0.docstatus < 2"
	"          AND co0.status NOT IN ('" + "', '".join(DONE_CLEANING) + "'))"
)


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


def _cleaned_counts(depot, wash_type=None, item_code=None):
	"""Finished cleanings per principal, optionally narrowed to one wash kind.

	Dua jalur pencocokan, keduanya lewat NILAI TETAP, tidak pernah lewat nama item:

	* ``wash_type``  — ``Cleaning Order.cleaning_type``, jenis di header. Terisi untuk
	  semua order sejak patch v0_84.
	* ``item_code``  — item code service yang dipilih, untuk order yang header-nya
	  ``Other`` / jenis lain tapi jelas memuat service tersebut.

	Sebelumnya jalur kedua mencocokkan ``cos.item_name LIKE '%<jenis>%'``, dan itu tidak
	pernah kena satu baris pun: item-nya bernama "P&P Wash", "Methanol Wash / Rinse",
	"Steam Cleaning / Wash" — bukan "PP Wash" / "Methanol Rinse" / "Steam Wash". Nama item
	milik finance dan bisa berubah kapan saja; item code tidak. Jangan dikembalikan ke
	pencocokan nama."""
	params = []
	method_clause = ""
	if wash_type or item_code:
		params.extend([wash_type, item_code])
		method_clause = (
			" AND (co.cleaning_type = %s OR EXISTS ("
			"   SELECT 1 FROM `tabCleaning Order Service` cos"
			"   WHERE cos.parent = co.name AND cos.cleaning_item = %s))"
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
