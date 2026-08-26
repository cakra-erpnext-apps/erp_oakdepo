"""Open a Storage Charge for every visit already in the gate records.

Without this the ledger starts empty, and every historical stay would read as never
billed — so the first run of any storage billing would re-charge months of days.

The seeding of ``billed_until`` is the delicate half. The only thing the old model knew
was ``Container.storage_billed_until``: ONE date per container, meaning "billed
chronologically up to here". Read faithfully, that says a visit is billed up to
``min(watermark, hari terakhir kunjungan)`` and untouched when the watermark predates it.
That is what this patch writes — no more, since the old data cannot say more. A visit the
old model swallowed (an unbilled visit older than the watermark) therefore comes across as
billed; that is the pre-existing loss being recorded, not one this patch creates, and from
here on each visit carries its own watermark so it cannot happen again.
"""

from __future__ import annotations

import frappe
from frappe.utils import getdate

from container_depot import storage, storage_charge
from container_depot.container_depot.container_status import GATE_OUT, PRESENT


def execute():
	containers = frappe.get_all(
		"Container",
		filters={"status": ["in", PRESENT + (GATE_OUT,)]},
		fields=["name", "container_no", "storage_billed_until"],
	)
	count_mode = storage.count_mode()
	made = 0
	for c in containers:
		names = storage_charge.sync(c.name, c.container_no)
		if not c.storage_billed_until:
			made += len(names)
			continue
		watermark = getdate(c.storage_billed_until)
		for period in storage.stay_periods(c.name, c.container_no):
			if watermark < getdate(period["start"]):
				continue  # billed before this visit began — nothing of it was covered
			row = frappe.db.get_value(
				"Storage Charge", storage_charge._key(c.name, period), "name"
			)
			if not row:
				continue
			last = storage.last_billable_day(period, watermark, count_mode)
			frappe.db.set_value(
				"Storage Charge", row, "billed_until", min(watermark, last), update_modified=False
			)
		made += len(names)
	# Recompute the day figures now the watermarks are in place.
	storage_charge.sync_all()
	frappe.db.commit()
	print(f"[container_depot] backfill_storage_charges: {made} visit(s) recorded.")
