import frappe
from frappe import _
from frappe.model.document import Document

# A container may be put on a Release DO only from one of these states.
ELIGIBLE_STATUSES = {"Ready_For_Release", "Cleaning_Cert_Issued", "Empty_Clean"}


class ReleaseDO(Document):
	def validate(self):
		"""Every listed container must be release-eligible (unless already on the
		release path from a prior submit of this same DO)."""
		for row in self.containers:
			if not row.container:
				continue
			status = frappe.db.get_value("Container", row.container, "status")
			if status in ELIGIBLE_STATUSES or status in ("Released_Pending_Pickup", "Gate_Out"):
				continue
			frappe.throw(
				_("Container {0} is not ready for release (status: {1}).").format(
					row.container_no or row.container, status
				)
			)

	def on_submit(self):
		"""Issue the DO: move each container to Released_Pending_Pickup."""
		self._set_container_status("Released_Pending_Pickup")

	def on_update_after_submit(self):
		"""When the DO is marked Picked Up, gate the containers out."""
		if self.status == "Picked Up":
			self._set_container_status("Gate_Out")

	def on_cancel(self):
		"""Best-effort rollback: pending-pickup containers go back to ready."""
		self._set_container_status("Ready_For_Release", only_from={"Released_Pending_Pickup"})

	def _set_container_status(self, target, only_from=None):
		from container_depot.operations.container_activity import log_container_activity

		activity = {
			"Released_Pending_Pickup": ("Release", "Released — pending pickup"),
			"Gate_Out": ("Gate Out", f"Gated out (Release DO {self.name})"),
		}.get(target)
		for row in self.containers:
			if not row.container:
				continue
			container = frappe.get_doc("Container", row.container)
			if only_from and container.status not in only_from:
				continue
			if container.status == target:
				continue
			from_status = container.status
			container.status = target
			# Controller-driven change: bypass the manual-transition guard.
			frappe.flags.in_status_automation = True
			try:
				container.save(ignore_permissions=True)
			finally:
				frappe.flags.in_status_automation = False
			if activity:
				log_container_activity(
					container.name, activity[0],
					reference_doctype=self.doctype, reference_name=self.name,
					from_status=from_status, to_status=target,
					summary=activity[1],
				)
