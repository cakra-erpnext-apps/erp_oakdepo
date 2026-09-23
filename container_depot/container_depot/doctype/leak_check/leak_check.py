# Copyright (c) 2026, Oak Depot Team and contributors
# For license information, please see license.txt

"""Leak Check — photos of a tank, each flagged leaking or not. One order per container.

Born ``Open`` when the Tank In bon (Order Bongkar) is submitted — one per container row, see
:func:`provision_for_order_bongkar` — and ``Completed`` the moment it carries a photo. It holds
no other order; its one consequence is at the exit: a tank may not gate out without a
Completed Leak Check filed during its current visit (``gate.mark_gate_out`` via
:func:`has_leak_check_this_visit`).
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_datetime, now_datetime

from container_depot.container_depot.container_status import assert_container_active

OPEN = "Open"
COMPLETED = "Completed"


class LeakCheck(Document):
	def validate(self):
		if self.container and self.has_value_changed("container"):
			assert_container_active(self.container)
		self.has_leak = int(any(row.is_leak for row in self.photos))
		if any(row.photo for row in self.photos):
			self.status = COMPLETED
			# Stamped at completion, not at birth: an order provisioned on the bon has not
			# been checked by anybody yet.
			self.recorded_by = self.recorded_by or frappe.session.user
			self.recorded_on = self.recorded_on or now_datetime()
			return
		before = self.get_doc_before_save()
		# A finished check cannot be emptied back out, and a hand-made one must carry
		# evidence — only a bon-provisioned order may exist without photos.
		if (before and before.status == COMPLETED) or (self.is_new() and not self.order_bongkar):
			frappe.throw(_("Leak check wajib minimal satu foto."))
		self.status = OPEN

	def after_insert(self):
		if self.status == OPEN:
			from container_depot.container_depot.notify import notify_leak_check_created

			notify_leak_check_created(self)


def has_leak_check_this_visit(container: str) -> bool:
	"""A Completed Leak Check filed since the tank's arrival (``Container.eir_in_date``).

	No arrival stamp (an imported tank) = any Completed Leak Check on the tank counts.
	"""
	arrived = frappe.db.get_value("Container", container, "eir_in_date")
	filters = {"container": container, "status": COMPLETED}
	if arrived:
		filters["recorded_on"] = [">=", get_datetime(arrived)]
	return bool(frappe.db.exists("Leak Check", filters))


def open_leak_check(container: str) -> str | None:
	"""The container's Open Leak Check order, newest first — what the PWA fills in."""
	return frappe.db.get_value(
		"Leak Check", {"container": container, "status": OPEN}, "name", order_by="creation desc"
	)


# ---------------------------------------------------------------------------
# Lifecycle on the Tank In bon — mirrors the EIR-In drafts (eir.provision_eirs_for_order_bongkar
# / release_eirs_for_cancelled_order).
# ---------------------------------------------------------------------------
def _bon_containers(order_name: str) -> list[str]:
	return [
		c for c in frappe.get_all(
			"Container Booking Item",
			filters={"parent": order_name, "parenttype": "Order Bongkar"},
			pluck="container",
		) if c
	]


def provision_for_order_bongkar(order_name: str) -> list:
	"""Submit-time: one Open Leak Check per container on the bon.

	Idempotent. A container that already has an Open Leak Check (from any bon) or one raised
	by THIS bon before (a revert-to-draft + re-submit) gets nothing new. Rows dropped while
	the bon was back in draft are released first (:func:`release_removed_rows`). Best-effort
	per container: one failure is logged and never blocks the bon submit.
	"""
	release_removed_rows(order_name)
	booking = frappe.db.get_value("Order Bongkar", order_name, "booking")
	created = []
	for container in _bon_containers(order_name):
		if open_leak_check(container) or frappe.db.exists(
			"Leak Check", {"container": container, "order_bongkar": order_name}
		):
			continue
		try:
			doc = frappe.new_doc("Leak Check")
			doc.container = container
			doc.order_bongkar = order_name
			doc.booking = booking
			doc.insert(ignore_permissions=True)  # system automation on bon submit
			created.append(doc.name)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"auto Leak Check for {container} on {order_name}")
	return created


def release_removed_rows(order_name: str) -> dict:
	"""Release this bon's Leak Checks whose container is no longer on the bon (row deleted)."""
	keep = set(_bon_containers(order_name))
	return _release(order_name, lambda lc: lc.container not in keep)


def release_for_cancelled_order(order_name: str) -> dict:
	"""Cancel / void: release every Leak Check this bon raised."""
	return _release(order_name, lambda lc: True)


def _release(order_name: str, wanted) -> dict:
	"""Per Leak Check, in order:

	* a **replacement** submitted bon carries the container → re-point at it;
	* else still **Open** (no photo = no work in it) → delete;
	* else (Completed) → keep the evidence, drop the dangling bon link, say so on its timeline.
	"""
	out = {"repointed": [], "deleted": [], "detached": []}
	for lc in frappe.get_all(
		"Leak Check", filters={"order_bongkar": order_name}, fields=["name", "container", "status"]
	):
		if not wanted(lc):
			continue
		try:
			replacement = frappe.db.sql(
				"""SELECT o.name, o.booking FROM `tabOrder Bongkar` o
				JOIN `tabContainer Booking Item` i ON i.parent = o.name AND i.parenttype = 'Order Bongkar'
				WHERE i.container = %s AND o.docstatus = 1 AND o.name != %s
				ORDER BY o.creation DESC LIMIT 1""",
				(lc.container, order_name),
				as_dict=True,
			)
			if replacement:
				frappe.db.set_value(
					"Leak Check", lc.name,
					{"order_bongkar": replacement[0].name, "booking": replacement[0].booking},
					update_modified=False,
				)
				out["repointed"].append(lc.name)
			elif lc.status == OPEN:
				frappe.delete_doc("Leak Check", lc.name, ignore_permissions=True, force=True)
				out["deleted"].append(lc.name)
			else:
				frappe.db.set_value("Leak Check", lc.name, "order_bongkar", None, update_modified=False)
				frappe.get_doc("Leak Check", lc.name).add_comment(
					"Info",
					_("Bon {0} dibatalkan / container dilepas dari bon — link bon dilepas, foto dipertahankan.").format(order_name),
				)
				out["detached"].append(lc.name)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"release Leak Check {lc.name} on {order_name}")
	return out


# ---------------------------------------------------------------------------
# PWA list / detail — same shape as the Jadwal Survey list (tank_survey.list_all_survey_orders)
# ---------------------------------------------------------------------------
LEAK = "leak"  # pseudo-status for the "Bocor" pill


def _scope() -> dict:
	from container_depot.container_depot.user_branch import get_user_depots

	depots = get_user_depots()
	return {} if depots is None else {"depot": ["in", depots or [""]]}


def _booking_parties(bookings) -> dict:
	"""{booking: {reff_doc, customer, shipper}} — read live, so a Reff Doc corrected on the
	booking is what every Leak Check shows."""
	if not bookings:
		return {}
	return {
		b.name: b
		for b in frappe.get_all(
			"Container Booking", filters={"name": ["in", list(bookings)]},
			fields=["name", "reff_doc", "customer", "shipper"],
		)
	}


def list_leak_checks(status=None, search=None, depot=None, principal=None, day=None,
					 sort=None, start=0, page_length=20) -> dict:
	from frappe.utils import cint, getdate

	scope = _scope()
	filters = dict(scope)
	if status in (OPEN, COMPLETED):
		filters["status"] = status
	elif status == LEAK:
		filters["has_leak"] = 1
	if depot:
		filters["depot"] = depot if "depot" not in scope or depot in scope["depot"][1] else ""
	if principal:
		filters["principal"] = principal
	if day:
		d = getdate(day)
		filters["creation"] = ["between", [d, d]]
	or_filters = None
	search = (search or "").strip()
	if search:
		like = f"%{search}%"
		bookings = frappe.get_all("Container Booking", filters={"reff_doc": ["like", like]}, pluck="name")
		or_filters = [["container_no", "like", like], ["name", "like", like],
					  ["order_bongkar", "like", like], ["booking", "like", like]]
		if bookings:
			or_filters.append(["booking", "in", bookings])

	order = "creation asc" if sort == "oldest" else "creation desc"
	fields = ["name", "container", "container_no", "depot", "principal", "status", "has_leak",
			  "booking", "order_bongkar", "creation", "recorded_on", "recorded_by", "remarks"]
	items = frappe.get_all("Leak Check", filters=filters, or_filters=or_filters, fields=fields,
						   order_by=order, limit_start=cint(start), limit_page_length=cint(page_length))
	total = len(frappe.get_all("Leak Check", filters=filters, or_filters=or_filters, pluck="name"))
	day_counts: dict = {}
	for c in frappe.get_all("Leak Check", filters=filters, or_filters=or_filters, pluck="creation"):
		k = str(getdate(c))
		day_counts[k] = day_counts.get(k, 0) + 1

	names = [i.name for i in items]
	photos: dict = {}
	for p in frappe.get_all("Leak Check Photo", filters={"parent": ["in", names or [""]], "parenttype": "Leak Check"},
							fields=["parent", "is_leak"]):
		c = photos.setdefault(p.parent, [0, 0])
		c[0] += 1
		c[1] += p.is_leak or 0
	parties = _booking_parties({i.booking for i in items if i.booking})
	for it in items:
		b = parties.get(it.booking) or {}
		it["reff_doc"], it["emkl"], it["shipper"] = b.get("reff_doc"), b.get("customer"), b.get("shipper")
		it["photo_count"], it["leak_count"] = photos.get(it.name, [0, 0])
		it["day"] = str(getdate(it.creation))
		it["recorded_by_name"] = frappe.utils.get_fullname(it.recorded_by) if it.recorded_by else None
		for k in ("creation", "recorded_on"):
			it[k] = str(it[k]) if it.get(k) else None

	# Pills count WITHOUT the current filter (same reason as tank_survey._status_counts): they
	# are how the filter gets changed.
	counts = {"all": 0, OPEN: 0, COMPLETED: 0, LEAK: 0}
	for r in frappe.get_all("Leak Check", filters=scope, fields=["status", "has_leak"], limit_page_length=0):
		counts["all"] += 1
		counts[r.status] = counts.get(r.status, 0) + 1
		counts[LEAK] += 1 if r.has_leak else 0
	return {
		"items": items, "total": total, "counts": counts, "day_counts": day_counts,
		"depots": sorted({d for d in frappe.get_all("Leak Check", filters=scope, pluck="depot", distinct=True) if d}),
		"principals": sorted({p for p in frappe.get_all("Leak Check", filters=scope, pluck="principal", distinct=True) if p}),
	}


def get_leak_check_detail(name: str) -> dict:
	from container_depot.container_depot.user_branch import assert_in_user_branch

	doc = frappe.get_doc("Leak Check", name)
	assert_in_user_branch(depot=doc.depot)
	b = _booking_parties([doc.booking] if doc.booking else []).get(doc.booking) or {}
	return {
		"name": doc.name, "container": doc.container, "container_no": doc.container_no,
		"depot": doc.depot, "principal": doc.principal, "status": doc.status, "has_leak": doc.has_leak,
		"booking": doc.booking, "order_bongkar": doc.order_bongkar, "remarks": doc.remarks,
		"reff_doc": b.get("reff_doc"), "emkl": b.get("customer"), "shipper": b.get("shipper"),
		"creation": str(doc.creation), "recorded_on": str(doc.recorded_on) if doc.recorded_on else None,
		"recorded_by": frappe.utils.get_fullname(doc.recorded_by) if doc.recorded_by else None,
		"photos": [{"photo": p.photo, "caption": p.caption or "", "is_leak": p.is_leak} for p in doc.photos],
		"photo_count": len(doc.photos),
		"can_edit": doc.status == OPEN and frappe.has_permission("Leak Check", "write", doc=doc),
	}
