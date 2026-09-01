"""Periodic Test Register — pengganti sheet PERIODIC TEST di Tank Inventory at KIM.

Uji berkala dibukukan sebagai M&R (keputusan patch v0_66: tidak ada doctype Periodic Test
Order), jadi sumbernya Repair Order ber-``job_type = Periodic Test``. Kolomnya mengikuti
sheet aslinya, dan tiga di antaranya DITURUNKAN, bukan disimpan:

* **Type PT** — dari item yang dipakai di ordernya (``TEST-2-5YR`` / ``SVY-CLASS-2-5YR``
  -> 2,5Y; ``TEST-5-0YR`` / ``SVY-CLASS-5-0YR`` -> 5Y). Dikunci ke item CODE, tidak pernah
  ke nama item.
* **Last PT Type / Last PT Date** — dari uji berkala SEBELUMNYA atas tank yang sama yang
  sudah selesai. Kalau tank itu belum pernah diuji di dalam sistem, jatuh ke
  ``Container.last_test_date`` — tanggal plat tank yang memang sengaja dipertahankan v0_66
  — dan tipenya dikosongkan, karena data lama itu tidak menyimpan tipenya.
* **Due Date** — tanggal uji + 30 bulan (2,5Y) atau 60 bulan (5Y). Watermark
  ``Container.next_pt_due`` dihapus v0_66 bersama fiturnya, jadi jatuh temponya dihitung
  di sini, bukan dibaca. Untuk order yang belum selesai, dihitung dari uji SEBELUMNYA —
  itu tanggal yang sebenarnya mengikat.

**Billed To** dibaca dari ``billing_status``: siapa yang ditagih (Client / Principal),
bukan nama perusahaannya — itu satu-satunya yang direkam Repair Order.

Order yang BELUM selesai tetap tampil, dengan Periodic Date kosong: itu antrean uji, dan
sebuah register yang hanya memuat uji selesai justru menghapus pertanyaan yang dibawa
orang ke halaman ini.
"""

from __future__ import annotations

import frappe
from frappe.utils import add_months, getdate

from container_depot.container_depot.container_status import DONE_REPAIR

# Item code -> tipe uji. Item survey ikut, karena sertifikasi kelas mengikuti siklus yang
# sama dan sering jadi satu-satunya baris di order yang uji fisiknya dikerjakan pihak lain.
_PT_TYPE_BY_ITEM = {
	"TEST-2-5YR": "2,5Y",
	"SVY-CLASS-2-5YR": "2,5Y",
	"TEST-5-0YR": "5Y",
	"SVY-CLASS-5-0YR": "5Y",
}

_MONTHS = {"2,5Y": 30, "5Y": 60}

_BILLED_TO = {"Client Billed": "Client", "Principal Billed": "Principal"}


def execute(filters=None):
	filters = filters or {}
	orders = _orders(filters)
	types = _types_by_order([o["repair_order"] for o in orders])
	history = _history(orders, types)

	rows = []
	for o in orders:
		pt_type = types.get(o["repair_order"], "")
		# Hanya order yang benar-benar Completed punya Periodic Date; Rejected tidak
		# pernah menghasilkan uji, dan Cancelled sudah disaring di query.
		periodic_date = (
			getdate(o["completion_date"])
			if o["status"] == "Completed" and o["completion_date"]
			else None
		)
		last_type, last_date = history.get(o["repair_order"], ("", None))
		rows.append({
			"tank_no": o["tank_no"],
			"principal": o["principal"],
			"order_date": getdate(o["order_created"]) if o["order_created"] else None,
			"plan_date": o["plan_date"],
			"type_pt": pt_type,
			"periodic_date": periodic_date,
			"last_pt_type": last_type,
			"last_pt_date": last_date,
			# Kode gabungan principal+tipe, persis pola di sheet aslinya ("Bertschi5Y").
			"code": f"{o['principal'] or ''}{pt_type}" if pt_type else "",
			"due_date": _due(periodic_date or last_date, pt_type or last_type),
			"billed_to": _BILLED_TO.get(o["billing_status"], ""),
			"status": o["status"],
			"repair_order": o["repair_order"],
		})
	return _columns(), rows, None, None, _summary(rows)


def _orders(filters) -> list:
	where = ["ro.job_type = 'Periodic Test'", "ro.status != 'Cancelled'"]
	params = {}
	if filters.get("principal"):
		where.append("COALESCE(NULLIF(ro.principal, ''), c.principal) = %(principal)s")
		params["principal"] = filters["principal"]
	if filters.get("depot"):
		where.append("COALESCE(NULLIF(ro.depot, ''), c.depot) = %(depot)s")
		params["depot"] = filters["depot"]
	if filters.get("from_date"):
		where.append("DATE(ro.order_created) >= %(from_date)s")
		params["from_date"] = filters["from_date"]
	if filters.get("to_date"):
		where.append("DATE(ro.order_created) <= %(to_date)s")
		params["to_date"] = filters["to_date"]
	if filters.get("only_outstanding"):
		where.append("ro.status NOT IN %(done)s")
		params["done"] = tuple(DONE_REPAIR)

	return frappe.db.sql(
		f"""
		SELECT
			ro.name AS repair_order,
			ro.container AS tank_no,
			COALESCE(NULLIF(ro.principal, ''), c.principal) AS principal,
			ro.order_created, ro.plan_date, ro.completion_date, ro.status, ro.billing_status
		FROM `tabRepair Order` ro
		LEFT JOIN `tabContainer` c ON ro.container = c.name
		WHERE {' AND '.join(where)}
		ORDER BY ro.order_created ASC
		""",
		params,
		as_dict=True,
	)


def _types_by_order(names) -> dict:
	"""Tipe uji per order, dari item yang dipakai. Satu order boleh memuat uji fisik dan
	sertifikat kelasnya sekaligus; keduanya menunjuk siklus yang sama, jadi baris pertama
	yang dikenali sudah cukup."""
	if not names:
		return {}
	out = {}
	rows = frappe.get_all(
		"Repair Used Item",
		filters={"parent": ["in", names], "item": ["in", list(_PT_TYPE_BY_ITEM)]},
		fields=["parent", "item", "idx"],
		order_by="parent asc, idx asc",
	)
	for r in rows:
		out.setdefault(r.parent, _PT_TYPE_BY_ITEM[r.item])
	return out


def _history(orders, types) -> dict:
	"""Uji SEBELUMNYA per order: (tipe, tanggal).

	Dicari di antara order uji berkala tank yang sama yang sudah selesai lebih dulu. Kalau
	tidak ada, jatuh ke ``Container.last_test_date`` — tanggal plat tank dari sebelum sistem
	ini ada, yang tidak menyimpan tipenya.
	"""
	by_tank: dict = {}
	for o in orders:
		if o["status"] == "Completed" and o["completion_date"]:
			by_tank.setdefault(o["tank_no"], []).append(
				(getdate(o["completion_date"]), types.get(o["repair_order"], ""))
			)
	for done in by_tank.values():
		done.sort()

	plate = {}
	tanks = {o["tank_no"] for o in orders if o["tank_no"]}
	if tanks:
		plate = {
			c.name: c.last_test_date
			for c in frappe.get_all(
				"Container", filters={"name": ["in", list(tanks)]},
				fields=["name", "last_test_date"],
			)
		}

	out = {}
	for o in orders:
		anchor = getdate(o["order_created"]) if o["order_created"] else None
		earlier = [
			(d, t) for d, t in by_tank.get(o["tank_no"], [])
			if anchor and d < anchor
		]
		if earlier:
			date, pt_type = earlier[-1]
			out[o["repair_order"]] = (pt_type, date)
		elif plate.get(o["tank_no"]):
			out[o["repair_order"]] = ("", getdate(plate[o["tank_no"]]))
	return out


def _due(anchor, pt_type):
	months = _MONTHS.get(pt_type)
	if not anchor or not months:
		return None
	return add_months(anchor, months)


def _columns() -> list:
	return [
		{"fieldname": "tank_no", "label": "Tank No", "fieldtype": "Link",
		 "options": "Container", "width": 140},
		{"fieldname": "principal", "label": "Principle", "fieldtype": "Link",
		 "options": "Customer", "width": 160},
		{"fieldname": "order_date", "label": "Order Date", "fieldtype": "Date", "width": 105},
		{"fieldname": "plan_date", "label": "Plan Date", "fieldtype": "Date", "width": 105},
		{"fieldname": "type_pt", "label": "Type PT", "fieldtype": "Data", "width": 80},
		{"fieldname": "periodic_date", "label": "Periodic Date", "fieldtype": "Date", "width": 115},
		{"fieldname": "last_pt_type", "label": "Last PT Type", "fieldtype": "Data", "width": 105},
		{"fieldname": "last_pt_date", "label": "Last PT Date", "fieldtype": "Date", "width": 110},
		{"fieldname": "code", "label": "Code", "fieldtype": "Data", "width": 140},
		{"fieldname": "due_date", "label": "Due Date", "fieldtype": "Date", "width": 105},
		{"fieldname": "billed_to", "label": "Billed To", "fieldtype": "Data", "width": 100},
		{"fieldname": "status", "label": "Status", "fieldtype": "Data", "width": 130},
		{"fieldname": "repair_order", "label": "M&R", "fieldtype": "Link",
		 "options": "Repair Order", "width": 150},
	]


def _summary(rows) -> list:
	done = sum(1 for r in rows if r["periodic_date"])
	overdue = sum(
		1 for r in rows
		if not r["periodic_date"] and r["due_date"] and getdate(r["due_date"]) < getdate()
	)
	return [
		{"label": "Total Order", "value": len(rows), "datatype": "Int"},
		{"label": "Sudah Diuji", "value": done, "datatype": "Int", "indicator": "Green"},
		{"label": "Belum Selesai", "value": len(rows) - done, "datatype": "Int",
		 "indicator": "Red" if len(rows) - done else "Green"},
		# Lewat jatuh tempo dan masih belum diuji — satu-satunya angka di halaman ini yang
		# berarti tank tidak boleh dipakai.
		{"label": "Lewat Due Date", "value": overdue, "datatype": "Int",
		 "indicator": "Red" if overdue else "Green"},
	]
