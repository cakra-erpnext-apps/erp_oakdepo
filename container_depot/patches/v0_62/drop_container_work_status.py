"""Drop the three Container work-status hints, and the two dashboard cards that read one.

``cleaning_status`` / ``repair_status`` / ``certification_status`` mirrored the state of
the Cleaning / Repair order onto the tank master. Nothing ever cleared them:

* ``certification_status`` had exactly one writer (a finished Cleaning Order set it to
  ``Completed``) and **no reader anywhere** — not a report, card, notification or rule;
* ``repair_status`` was read only by two report columns, next to the M&R link column that
  already answered the same question from the order itself;
* ``cleaning_status`` fed the ``Dirty Tank`` / ``Clean Tank`` number cards and the KPI
  report — neither of which filtered to tanks still in the depo, so a tank cleaned last
  cycle counted as "Clean" months after it had gated out.

Since a tank is cleaned and repaired once per cycle but the fields were never reset on
gate-out, all three stated the LAST cycle's outcome as if it were current. The open orders
(``container_status.container_open_orders``) are the same answer asked of the documents
that actually know, and are already what decides whether a tank may leave. Readers were
moved onto them; the fields go.

The DocFields themselves are removed by ``bench migrate`` re-importing container.json —
this drops the leftover table columns and the two cards, neither of which migrate touches.

Idempotent, and best-effort on each half: a missing column or card is a no-op, and a card
that refuses to delete (someone pinned it to their own workspace) is logged, never fatal.
"""

from __future__ import annotations

import frappe

_COLUMNS = ("cleaning_status", "repair_status", "certification_status")
# Deleting the record — not just unlinking it from the workspace — is deliberate: a Number
# Card left behind stays offerable in the "Add Card" picker, which is how a dead card gets
# put back on a dashboard. Same reasoning as v0_59.
_CARDS = ("Dirty Tank", "Clean Tank")


def execute():
	dropped = []
	for card in _CARDS:
		if not frappe.db.exists("Number Card", card):
			continue
		try:
			frappe.db.delete("Workspace Number Card", {"number_card_name": card})
			frappe.delete_doc("Number Card", card, force=True, ignore_permissions=True)
			dropped.append(card)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"drop number card {card}")

	for column in _COLUMNS:
		if not frappe.db.has_column("Container", column):
			continue
		try:
			frappe.db.sql_ddl(f"ALTER TABLE `tabContainer` DROP COLUMN `{column}`")
			dropped.append(column)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"drop Container.{column}")

	frappe.db.commit()
	if dropped:
		print(f"[container_depot] v0_62: dropped {', '.join(dropped)}")
