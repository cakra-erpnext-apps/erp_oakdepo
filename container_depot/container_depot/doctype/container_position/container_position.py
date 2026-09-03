# Copyright (c) 2026, Oak Depot Team and contributors
# For license information, please see license.txt

"""Container Position — where a tank stands right now, and when somebody last checked.

An append-only reading, not an editable field. Every time anyone in the yard finds a tank
somewhere they write a new one, and the newest reading is mirrored onto the ``Container``
master (``current_location`` / ``location_updated_on`` / ``location_updated_by``). Everything
that needs to know where a tank is — the Survey Order screen above all — reads the master and
gets both the place and the age of that answer.

WHY A DOCUMENT PER READING RATHER THAN A FIELD ON THE TANK
----------------------------------------------------------
A bare field says where the tank is and nothing about how much to trust it. "Blok kanan" is a
different fact when it was written an hour ago than when it was written in June, and an
operator standing in an empty bay needs to know which one they are looking at. Keeping each
reading as a row gives the master's timestamp something real behind it, and gives the yard a
history it can argue with: who said that, and when.

It is also why this is deliberately NOT tied to a booking. A tank's position changes because
a reachstacker moved it, not because a customer ordered something — so the record of it
belongs to the tank, and outlives every booking the tank ever appears on.

Open to every field team (see ``install.FIELD_ROLE_MATRIX``): a wrong position costs whoever
walks to the wrong stack next, whichever crew they are on, so fencing off the correction
would only slow the fix down.

The logic (record / read / search) lives in ``container_depot.container_depot.container_position``
so the same code backs the PWA and the Desk.
"""

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime

from container_depot.container_depot.container_status import assert_container_active


class ContainerPosition(Document):
	def validate(self):
		# A retired tank takes no new work (container_status.assert_container_active).
		if self.container and self.has_value_changed("container"):
			assert_container_active(self.container)
		if not (self.location_note or "").strip():
			frappe.throw(frappe._("Isi dulu letak container-nya."))
		# Stamped here rather than left to the caller so a Desk entry, a PWA post and a
		# migration all record the same two facts. `or` and not an overwrite: a backfill that
		# knows the real author must be able to say so.
		self.recorded_by = self.recorded_by or frappe.session.user
		self.recorded_on = self.recorded_on or now_datetime()

	def on_update(self):
		self.push_to_container()

	def after_delete(self):
		# Deleting the newest reading has to hand the master back to the one before it, or the
		# tank would keep pointing at a position nobody stands behind any more.
		self.push_to_container()

	def push_to_container(self):
		"""Mirror the NEWEST reading for this tank onto the Container master.

		Newest by ``recorded_on`` rather than "this document", because a correction typed
		after the fact — or a reading deleted — must not leave the master quoting the wrong
		row. Written with ``db.set_value`` and never ``doc.save()``: this runs from inside
		this document's own save, where re-running the tank's validation could throw on
		something entirely unrelated to where it is parked.
		"""
		if not self.container:
			return
		latest = frappe.db.get_value(
			"Container Position",
			{"container": self.container},
			["location_note", "recorded_on", "recorded_by"],
			order_by="recorded_on desc, creation desc",
			as_dict=True,
		)
		frappe.db.set_value(
			"Container",
			self.container,
			{
				"current_location": latest.location_note if latest else None,
				"location_updated_on": latest.recorded_on if latest else None,
				"location_updated_by": latest.recorded_by if latest else None,
			},
			update_modified=False,
		)
