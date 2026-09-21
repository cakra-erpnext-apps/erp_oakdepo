"""Backfill the two columns the cleaning grid grew when it was reshaped after Service & Parts.

"Metode Cleaning (Service)" used to be one price per row, quantity implied. It is now a LINE —
``quantity`` x ``rate`` = ``amount`` — which is what the M&R estimate has always been. Migrate
adds the columns, but every row written before this lands carries NULL in both, and a NULL qty
reads as "zero of it" on the cleaning certificate.

The readers already treat a missing qty as one (``flt(qty) or 1``), so nothing is mis-billed
in the meantime; this is about what a printed statement of an old order shows. Only untouched
rows are filled, so a re-saved order (whose controller already did this) is left alone.

The header ``currency`` needs nothing: it was mandatory before and its meaning did not change
— it is derived from the rows now, and the rows were all on the header's currency anyway.
"""

import frappe

TABLE = "tabCleaning Order Service"


def execute():
	frappe.db.sql(f"UPDATE `{TABLE}` SET quantity = 1 WHERE quantity IS NULL OR quantity = 0")
	frappe.db.sql(f"UPDATE `{TABLE}` SET amount = quantity * rate WHERE amount IS NULL OR amount = 0")
