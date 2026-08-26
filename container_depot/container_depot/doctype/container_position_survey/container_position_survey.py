# Copyright (c) 2026, Oak Depot Team and contributors
# For license information, please see license.txt

"""Container Position Survey — a per-container task to locate/map an outbound (Lift On /
Tank Out) container's yard position before it is pulled, then confirmed ("udah turun") by
an Operator Kalmar. Each half is picked up with Mulai and finished in one press: no review
sits between the two, and the way back is a reopen rather than an approval queue.

The flow logic (provision / start / record position / approve / reopen) lives in
``container_depot.container_depot.position_survey`` so the same code backs the PWA and Desk.
This controller only guards the status transitions; it never touches ``Container.status``.
"""

import frappe
from frappe import _
from frappe.model.document import Document

from container_depot.container_depot.container_status import assert_container_active

# status graph — an edge (from -> to) that is not listed is rejected.
#
# Two halves, each with its own "sedang dikerjakan" state: a Surveyor takes the job with
# Mulai (Pending Survey -> In Survey) and finishes it (-> Surveyed); an Operator Kalmar then
# takes it with Mulai (Surveyed -> In Fix) and approves it (-> Confirmed). There is no review
# step in between — the finish IS the submit.
#
# What pays for the missing review is the way back: a finished step can be reopened to the
# in-progress state of the half that owns it (-> In Survey / -> In Fix), so the operator who
# got it wrong is the one who fixes it. Confirmed -> In Fix / In Survey are those edges;
# see position_survey.reopen_survey / reopen_fix for what each one clears.
_TRANSITIONS = {
	"Pending Survey": {"In Survey", "Surveyed", "Cancelled"},
	"In Survey": {"Surveyed", "Pending Survey", "Cancelled"},
	"Surveyed": {"In Fix", "Confirmed", "Cancelled", "In Survey", "Pending Survey"},
	"In Fix": {"Confirmed", "Surveyed", "In Survey", "Cancelled"},
	"Confirmed": {"In Fix", "In Survey", "Cancelled"},
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
