# Copyright (c) 2026, Oak Depot Team and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class RepairWorkPhoto(Document):
	"""One photo proving one line of a Repair Order's Service & Parts was actually done.

	It is a table of its own rather than a column on ``Repair Used Item`` because the two
	have different shapes: a line is one row of money that the owner approves, while the
	evidence for it is many photos taken at different moments by a different person. Folded
	into the estimate grid, the photos would widen the row the owner reads their bill from and
	make an eleven-column grid unreadable on a phone; kept apart, the estimate stays a price
	list and this stays an album.

	``item`` is the link the CUSTOMER reads — they know "Renew Corner Post", not a row id — so
	it is the visible one, restricted on the Desk to items actually on the order. ``used_item``
	holds the exact Repair Used Item row underneath it, which only matters when one item
	appears on the order twice; nothing asks a human to fill it.
	"""

	pass
