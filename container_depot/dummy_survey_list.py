"""Dummy Tank Out bookings + Survey Orders for eyeballing the PWA Jadwal Survey list.

Dev only. Everything it creates carries the ``DMY`` marker (Customer names, container numbers,
Reff Doc), and ``clear`` removes exactly that — nothing else on the site is touched.

    bench --site oakdepo.localhost execute container_depot.dummy_survey_list.seed
    bench --site oakdepo.localhost execute container_depot.dummy_survey_list.clear
"""

from __future__ import annotations

import frappe
from frappe.utils import add_days, today

from container_depot.container_depot import container_position as cp
from container_depot.container_depot import tank_survey as ts

PRINCIPALS = ["DMY Stolt Tank Containers", "DMY Hoyer Indonesia", "DMY Bertschi Asia"]
SHIPPERS = ["DMY Pertamina Patra Niaga", "DMY Wilmar Nabati", "DMY Musim Mas", None]
EMKLS = ["DMY Samudera Logistik", "DMY Puninar Jaya", "DMY Lintas Trans"]
SURVEYORS = ["DMY Sucofindo", "DMY Intertek Utama", None]

# (day offset, tanks, depots, what happens to it). "run" = 1 surveyed + 1 lowered.
PLAN = [
	(-3, 2, ["OAK1"], "done"),        # finished in the past: hidden from the default list
	(-2, 1, ["OAK1"], "open"),        # overdue and still open: must stay visible
	(0, 3, ["OAK1"], "run"),
	(0, 2, ["OAK1"], "open"),
	(0, 1, ["OAK2"], "open"),
	(0, 2, ["OAK1"], "done"),
	(0, 1, ["OAK1"], "cancel"),
	(1, 2, ["OAK1"], "open"),
	(1, 4, ["OAK1", "OAK2"], "open"),  # multi-depot pickup: header depot left empty
	(1, 2, ["OAK2"], "run"),
	(2, 2, ["OAK1"], "urgent"),
	(2, 1, ["OAK1"], "open"),
] + [(d, 1 + d % 3, ["OAK1" if d % 2 else "OAK2"], "open") for d in range(4, 12) for _ in (0, 1)]


def seed():
	frappe.set_user("Administrator")
	clear()
	for name in PRINCIPALS + [s for s in SHIPPERS + SURVEYORS if s] + EMKLS:
		_customer(name, transporter=name in EMKLS)

	n = 0
	for i, (offset, tanks, depots, fate) in enumerate(PLAN):
		principal = PRINCIPALS[i % len(PRINCIPALS)]
		containers = []
		for t in range(tanks):
			n += 1
			depot = depots[t % len(depots)]
			c = frappe.get_doc({
				"doctype": "Container", "container_no": f"DMYU{n:07d}", "container_type": "ISO Tank",
				"status": "In_Depot", "depot": depot, "principal": principal,
			}).insert(ignore_permissions=True).name
			cp.record_position(c, f"Blok {chr(65 + t % 4)}{1 + n % 9}, tumpuk {1 + t % 3}")
			containers.append(c)

		survey = add_days(today(), offset)
		booking = frappe.get_doc({
			"doctype": "Container Booking",
			"direction": "Tank Out",
			"branch": frappe.db.get_value("Depot", depots[0], "branch"),
			"depot": depots[0] if len(depots) == 1 else None,
			"principal": principal,
			"customer": EMKLS[i % len(EMKLS)],
			"shipper": SHIPPERS[i % len(SHIPPERS)],
			"surveyor": SURVEYORS[i % len(SURVEYORS)],
			"reff_doc": f"DMY/DO/{principal.split()[1][:3].upper()}/{2600 + i}",
			"survey_date": survey,
			"plan_date": add_days(survey, 1),
			"urgent_date": survey if fate == "urgent" else None,
			"items": [{"container": c} for c in containers],
		})
		booking.insert(ignore_permissions=True)

		order = frappe.db.get_value("Survey Order", {"booking": booking.name}, "name")
		rows = frappe.get_all("Survey Order Tank", filters={"parent": order}, pluck="name", order_by="idx")
		if fate == "cancel":
			frappe.get_doc("Survey Order", order).discard()
		elif fate == "done":
			for r in rows:
				ts.mark_lowered(r)
				ts.finish_survey(r, notes="Dummy: bersih, siap muat")
		elif fate == "run":
			ts.mark_lowered(rows[0])
			ts.finish_survey(rows[0], notes="Dummy")
			if len(rows) > 1:
				ts.mark_lowered(rows[1])
	frappe.db.commit()
	print(f"seeded {len(PLAN)} bookings, {n} tanks")


def clear():
	frappe.set_user("Administrator")
	from container_depot.tests.test_tank_survey import _purge

	containers = frappe.get_all("Container", filters={"container_no": ["like", "DMYU%"]}, pluck="name")
	bookings = frappe.get_all("Container Booking", filters={"reff_doc": ["like", "DMY/%"]}, pluck="name")
	for dt in ("Container Activity", "Container Movement"):
		if containers and frappe.db.exists("DocType", dt) and frappe.db.has_column(dt, "container"):
			frappe.db.delete(dt, {"container": ["in", containers]})
	_purge(containers, bookings)
	for name in frappe.get_all("Customer", filters={"name": ["like", "DMY %"]}, pluck="name"):
		frappe.delete_doc("Customer", name, force=True, ignore_permissions=True)
	frappe.db.commit()
	print(f"cleared {len(bookings)} bookings, {len(containers)} tanks")


def _customer(name, transporter=False):
	if frappe.db.exists("Customer", name):
		return
	doc = frappe.new_doc("Customer")
	doc.customer_name = name
	doc.customer_group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
	doc.territory = frappe.db.get_value("Territory", {"is_group": 0}, "name")
	if doc.meta.has_field("is_transporter"):
		doc.is_transporter = int(transporter)
	doc.insert(ignore_permissions=True)
