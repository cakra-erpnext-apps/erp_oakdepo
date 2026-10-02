"""Put every tank still in the depot on its EIR-In's own date.

Until 2026-10-02 an EIR-In submit stamped ``Container.eir_in_date`` with the submit time, and
storage counted from it. Both now read the date set on the EIR (``storage._eir_ins``), never
before the gate stamp. This moves the tanks already inside onto where their storage starts and
refreshes their Storage Charge rows.
"""

import frappe
from frappe.utils import getdate

from container_depot import storage, storage_charge
from container_depot.container_depot.container_status import PRESENT


def execute():
	for c in frappe.get_all(
		"Container", filters={"status": ["in", PRESENT]}, fields=["name", "container_no", "eir_in_date"]
	):
		visits = storage.stay_periods(c.name, c.container_no)
		start = visits[-1]["start"] if visits and not visits[-1]["end"] else None
		if start and (not c.eir_in_date or getdate(c.eir_in_date) != getdate(start)):
			frappe.db.set_value("Container", c.name, "eir_in_date", start, update_modified=False)
	storage_charge.sync_all()
