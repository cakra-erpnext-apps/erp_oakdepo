# Copyright (c) 2026, Oak Depot Team and contributors
# For license information, please see license.txt

"""Container Position Survey — a per-container task to locate/map an outbound (Lift On /
Tank Out) container's yard position before it is pulled, then confirmed ("udah turun") by
an Operator Kalmar.

The flow logic (provision / record position / approve) lives in
``container_depot.container_depot.position_survey`` so the same code backs the PWA and Desk.
This controller only guards the status transitions; it never touches ``Container.status``.
"""

import frappe
from frappe import _
from frappe.model.document import Document

from container_depot.container_depot.container_status import assert_container_active

# status graph — an edge (from -> to) that is not listed is rejected.
_TRANSITIONS = {
	"Pending Survey": {"Surveyed", "Cancelled"},
	"Surveyed": {"Confirmed", "Cancelled", "Pending Survey"},
	"Confirmed": {"Cancelled"},
	"Cancelled": set(),
}


class ContainerPositionSurvey(Document):
	def validate(self):
		# A retired tank takes no new work (container_status.assert_container_active);
		# only checked when the link is set or moved, so a finished order stays editable
		# after its tank leaves the fleet.
		if self.container and self.has_value_changed("container"):
			assert_container_active(self.container)
		# Tolerant like the rest of the app: new docs, no-op saves, and unknown source
		# states never block. Only a real, illegal transition is rejected.
		if self.is_new():
			return
		before = self.get_doc_before_save()
		if not before or before.status == self.status:
			return
		allowed = _TRANSITIONS.get(before.status)
		if allowed is not None and self.status not in allowed:
			frappe.throw(
				_("Tidak bisa mengubah status dari {0} ke {1}.").format(before.status, self.status)
			)
