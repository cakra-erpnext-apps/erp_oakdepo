"""Drop ``Repair Used Item.manhour_amount`` — the row's labour is one figure again.

The row used to carry labour twice: ``manhour_amount`` (Biaya Manhour, the figure Admin Ops
typed, seeded as hours × the customer's hourly tariff) and ``manhour_rate``, derived straight
back out of it as ``manhour_amount ÷ manhour``. The multiplication is gone from the order:
the row now takes the tariff AS IT STANDS from the owner's rate card, exactly the way
Cleaning Order Service has carried its own ``manhour_rate`` since v0_65. That leaves
``manhour_amount`` as the same number a second time, so it goes.

Nothing about billing moves. The invoice charges labour the way it always has — total hours
(``Sales Invoice Item.manhour``) × ONE tariff in its header — and the tariff it reads back is
``manhour_rate`` (``consolidated_billing._negotiated_manhour_hour``), which is untouched. Rows
already saved therefore keep billing exactly what they billed before; only the figure the FORM
shows changes, from the line's labour total to the tariff behind it.

Frappe never drops a column on its own, so the data would otherwise sit in the table for good.
Idempotent: ``DROP COLUMN IF EXISTS`` on a site already through it is a no-op.
"""

from __future__ import annotations

import frappe


def execute():
	frappe.reload_doc("container_depot", "doctype", "repair_used_item")
	frappe.db.sql_ddl("ALTER TABLE `tabRepair Used Item` DROP COLUMN IF EXISTS `manhour_amount`")
	frappe.clear_cache(doctype="Repair Used Item")
