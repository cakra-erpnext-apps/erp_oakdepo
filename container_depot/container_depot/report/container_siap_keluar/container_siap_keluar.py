"""Container Siap Keluar — the Desk twin of the PWA "Siap Keluar" worklist.

Every tank whose EIR-Out is submitted clean but that is still standing in the depot: the
reminder queue between the surveyor finishing and the truck actually leaving. The rows come
straight from :func:`container_depot.container_depot.gate.list_ready_to_load` so the Desk and the
PWA can never disagree, and the "ACC Keluar" button in the last column calls the same
``gate_out`` endpoint the PWA does (see ``container_siap_keluar.js``).
"""

from frappe.utils import get_datetime, now_datetime

from container_depot.container_depot.gate import list_ready_to_load


def execute(filters=None):
	return get_columns(), get_data(filters)


def get_columns():
	return [
		{"fieldname": "container", "label": "Container", "fieldtype": "Link", "options": "Container", "width": 130},
		{"fieldname": "order_muat", "label": "Bon Muat", "fieldtype": "Link", "options": "Order Muat", "width": 140},
		{"fieldname": "waiting", "label": "Menunggu", "fieldtype": "Data", "width": 100},
		{"fieldname": "ready_since", "label": "Siap Sejak", "fieldtype": "Datetime", "width": 160},
		{"fieldname": "truck_no", "label": "Truk", "fieldtype": "Data", "width": 110},
		{"fieldname": "driver", "label": "Sopir", "fieldtype": "Data", "width": 130},
		{"fieldname": "destination", "label": "Tujuan", "fieldtype": "Data", "width": 140},
		{"fieldname": "principal", "label": "Principal", "fieldtype": "Data", "width": 130},
		{"fieldname": "depot", "label": "Depo", "fieldtype": "Data", "width": 110},
		{"fieldname": "inspection", "label": "EIR-Out", "fieldtype": "Link", "options": "Inspection", "width": 140},
		{"fieldname": "acc", "label": "Aksi", "fieldtype": "Data", "width": 120},
	]


def get_data(filters=None):
	filters = filters or {}
	rows = list_ready_to_load(
		search=filters.get("search"), start=0, page_length=500
	)["items"]
	now = now_datetime()
	for row in rows:
		row["waiting"] = _humanize_wait(row.get("ready_since"), now)
		row["acc"] = ""  # rendered as a button by the report's formatter
	return rows


def _humanize_wait(ready_since, now):
	"""How long the tank has been standing ready — the whole point of the reminder."""
	if not ready_since:
		return ""
	hours = (now - get_datetime(ready_since)).total_seconds() / 3600
	if hours < 1:
		return f"{int(hours * 60)} menit"
	if hours < 24:
		return f"{int(hours)} jam"
	return f"{int(hours // 24)} hari"
