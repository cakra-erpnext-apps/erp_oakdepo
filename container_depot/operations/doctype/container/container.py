import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime

from container_depot.state_machine import assert_transition, stage_for_status


class Container(Document):
	def validate(self):
		# Container number is required (enforced by the field) but not length-checked —
		# real depot data carries non-ISO / short numbers, so only presence is required.

		# Guard manual status transitions against the canonical state machine.
		# Internal automation (Repair/Cleaning/Inspection controllers) and
		# migrations bypass via frappe.flags.in_status_automation.
		if not self.is_new() and self.has_value_changed("status"):
			previous = self.get_doc_before_save()
			assert_transition(previous.status if previous else None, self.status)

	def before_save(self):
		"""Auto-format container number + keep the monitoring stage in step with the
		raw status (every ORM save: gate entry, inspection, cleaning, repair, release)."""
		if self.container_no:
			self.container_no = self.container_no.upper()
		self.inventory_stage = stage_for_status(self.status)

	def on_update(self):
		"""Audit-trail: log a Container Movement row whenever ``status`` changes.

		Skipped when the save was *caused* by a Container Movement (avoids the
		Movement -> Container -> Movement loop), and when the new value is the
		same as the previous one (no-op save).
		"""
		if getattr(frappe.flags, "in_container_movement", False):
			return
		if not self.has_value_changed("status"):
			return
		previous = self.get_doc_before_save()
		from_status = previous.status if previous else None
		frappe.get_doc({
			"doctype": "Container Movement",
			"container": self.name,
			"event_type": "Status",
			"movement_timestamp": now_datetime(),
			"moved_by": frappe.session.user or "Administrator",
			"from_status": from_status,
			"to_status": self.status,
		}).insert(ignore_permissions=True)


@frappe.whitelist()
def seal_history(container: str) -> list:
	"""The seal numbers this tank left the depot with, newest release first.

	Seals are fitted and written down on the EIR-Out at the moment the tank is released, so
	that document IS the record — the master keeps no seal fields of its own. It used to carry
	five (manhole / airline / bottom outlet / top discharge / vapour valve), but nothing ever
	wrote them: a tank is sealed once per release, so a single set on the master could only
	show the LAST one, and would read as current long after the tank came back and was
	unsealed. Dropped in ``v0_50.drop_container_seal_fields``.

	Only submitted EIR-Outs count — a draft's seal numbers are still being typed. Ordered by
	the EIR date the surveyor recorded (``creation`` only breaks ties): a backdated EIR-Out
	entered late must not jump to the top of what reads as a chronological history.
	"""
	frappe.has_permission("Container", "read", doc=container, throw=True)
	if not frappe.has_permission("Inspection", "read"):
		return []
	eirs = frappe.get_all(
		"Inspection",
		filters={"container": container, "inspection_type": "EIR-Out", "docstatus": 1},
		fields=["name", "eir_date", "out_outcome"],
		order_by="eir_date desc, creation desc",
	)
	if not eirs:
		return []
	by_eir = {}
	for row in frappe.get_all(
		"Inspection Seal",
		filters={"parent": ["in", [e.name for e in eirs]], "parenttype": "Inspection"},
		fields=["parent", "seal_no", "remarks"],
		order_by="idx asc",
	):
		by_eir.setdefault(row.parent, []).append({"seal_no": row.seal_no, "remarks": row.remarks})
	# An EIR-Out with no seal row has nothing to say here — this is the seal history, not the
	# release history (the EIRs themselves are already listed on their own doctype).
	return [
		{
			"eir": e.name,
			"eir_date": str(e.eir_date) if e.eir_date else None,
			"outcome": e.out_outcome,
			"seals": by_eir[e.name],
		}
		for e in eirs
		if by_eir.get(e.name)
	]
