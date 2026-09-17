"""Take the app off Price List / Item Price — the contract IS the rate card now.

Until 2026-09-17 an Active ``Depot Contract`` published its ``tariff_lines`` to a customer
Price List and every order read the rate back out of ``Item Price``. The mirror is gone:
``pricing_model`` reads ``Tariff Rate`` straight off the contract. What is left behind on a
site that has been running is the mirror itself, plus the fingerprints the app pressed into
two ERPNext doctypes it no longer uses. This removes them.

Nothing here touches a figure anybody agreed to. Every rate and manhour rate in a published
list was copied FROM ``tariff_lines`` and is still there, on the contract, which is now the
only place it is read from.

What this does, in order:

1. **``Customer.default_price_list``** — cleared wherever it points at a contract-published
   list. It used to be the answer to "does this customer have a rate card"; nothing asks it
   any more, and leaving it set would be a stale pointer on the Customer form.
2. **The published lists are disabled, not deleted.** Submitted Sales Invoices carry the
   list name in ``selling_price_list``, so deleting the row would leave a dangling link on
   accounting documents that are already filed. Disabled is enough: nothing offers them, the
   history stays readable, and the app never looks at them again.
3. **The app's custom fields come off both doctypes** — ``Item Price.manhour_rate`` and
   ``Price List.customer``. Both were ours; the manhour rate lives on ``Tariff Rate`` and the
   customer link only ever existed to mark a generated list.
4. **The app's Custom DocPerm rows on both doctypes are deleted**, which hands them back to
   ERPNext: with no custom rows left, Frappe falls back to the shipped permissions. We wrote
   those rows for a rate card we no longer keep there (the customer-portal read, and the
   write lock that replaced it), and an app should not hold permissions on a doctype it does
   not use.
5. **The obsolete Property Setters go**, so the Customer form stops explaining a field that
   no longer decides anything. ``setup_property_setters`` writes its replacement (hidden) on
   the same migrate.
"""

import frappe

RATE_CARD_DOCTYPES = ("Price List", "Item Price")
OBSOLETE_PROPERTY_SETTERS = (
	("Customer", "default_price_list", "read_only"),
	("Customer", "default_price_list", "description"),
	("Item Price", None, "quick_entry"),
)


def execute():
	if not frappe.db.exists("DocType", "Price List"):
		return

	# The lists this app published, identified by the custom `customer` link it stamped on
	# them — `Depot Contract.generated_price_list` is already gone by the time this runs
	# (post-model-sync), so it cannot be the key.
	published = []
	if frappe.db.has_column("Price List", "customer"):
		published = frappe.get_all(
			"Price List", filters={"customer": ["is", "set"]}, pluck="name"
		)

	if published:
		frappe.db.sql(
			"""update `tabCustomer` set default_price_list = null
			   where default_price_list in %(lists)s""",
			{"lists": tuple(published)},
		)
		frappe.db.sql(
			"update `tabPrice List` set enabled = 0 where name in %(lists)s",
			{"lists": tuple(published)},
		)

	# ...and the pointers that now lead nowhere. A published list whose contract was deleted
	# took the list with it but left this field naming it, so the row above cannot see it.
	frappe.db.sql(
		"""update `tabCustomer` c set c.default_price_list = null
		   where c.default_price_list is not null and c.default_price_list != ''
		     and not exists (select 1 from `tabPrice List` p where p.name = c.default_price_list)"""
	)

	for doctype, fieldname in (("Item Price", "manhour_rate"), ("Price List", "customer")):
		name = frappe.db.get_value("Custom Field", {"dt": doctype, "fieldname": fieldname})
		if name:
			frappe.delete_doc("Custom Field", name, ignore_permissions=True, force=True)

	# Deleting every custom row is what restores the shipped ones: Frappe reads Custom
	# DocPerm only while at least one row exists for the doctype.
	for doctype in RATE_CARD_DOCTYPES:
		frappe.db.delete("Custom DocPerm", {"parent": doctype})
		frappe.clear_cache(doctype=doctype)

	for doctype, fieldname, prop in OBSOLETE_PROPERTY_SETTERS:
		filters = {"doc_type": doctype, "property": prop}
		filters["field_name"] = fieldname if fieldname else ["in", ["", None]]
		for name in frappe.get_all("Property Setter", filters=filters, pluck="name"):
			frappe.delete_doc("Property Setter", name, ignore_permissions=True, force=True)

	frappe.db.commit()
