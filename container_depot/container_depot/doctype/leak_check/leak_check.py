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
