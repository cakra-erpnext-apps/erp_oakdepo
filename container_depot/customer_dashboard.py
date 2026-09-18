"""Depot connections on the ERPNext Customer form.

ERPNext ships Customer with a **Portal Users** tab of its own (`Customer.portal_users`,
child doctype `Portal User`). That table belongs to ERPNext's WEBSITE portal and this app
never writes to it, so on this site it is always empty — while the depot's own portal
accounts live in `Customer Portal User`, a doctype of ours. The empty tab reads as a bug;
this puts the real thing one click away, under Connections.

`override_doctype_dashboards` rather than a DocType Link row: Customer is ERPNext's
doctype, and a link written into its JSON is overwritten on the next `bench migrate`.
"""

from frappe import _

# Every doctype here links to Customer through a plain `customer` field, which is the
# `fieldname` ERPNext's own dashboard declares — so none of them needs a
# `non_standard_fieldnames` entry. `Container` deliberately is NOT here: it hangs off
# `principal`, and the tanks of a customer are a list of their own.
DEPOT_LINKS = ["Customer Portal User", "Depot Contract", "Container Booking"]


def get_data(data=None):
	data = dict(data or {})
	data["transactions"] = list(data.get("transactions") or []) + [
		{"label": _("Depot OAK"), "items": DEPOT_LINKS}
	]
	return data
