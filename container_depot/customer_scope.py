"""Scope an external customer account to its own company's records.

A customer login is an ordinary Frappe user holding the `Customer Desk` role plus a
**User Permission** ``allow=Customer`` naming the company it belongs to — written by
``portal.sync_portal_user_permission`` when a `Customer Portal User` row goes Active.
That single row is the company flag; there is no user group and no second doctype.

Frappe applies it natively to any doctype carrying a Link to Customer
(``db_query.add_user_permissions``), which covers Depot Contract, Container and
Container Activity for free. This module fills the two holes that leaves:

1. **Doctypes with no Customer link at all.** Gate Entry (its ``container_no`` is plain
   Data) and Container Movement are not touched by User Permissions, so a customer would
   read the whole depot's gate history. They are filtered here, by walking one link to the
   owning record.

2. **Doctypes with SEVERAL Customer links.** ``add_user_permissions`` joins one
   condition per link field with **and**, not or — so on Container Booking
   (customer + principal + surveyor) a booking billed to PT Cakra but shipped for
   another principal would vanish from PT Cakra's own list. The link fields that are not
   the ownership test carry ``ignore_user_permissions`` in their doctype JSON, and the
   or-condition this file returns replaces them.

Both halves run through ``frappe.get_list``, so the same conditions also scope the Desk
list views, the Number Cards and the Dashboard Charts with nothing extra: a number card
whose doctype the customer cannot read is already dropped by Frappe
(``number_card.get_permission_query_conditions``).

Internal staff hold no Customer User Permission, so every function here returns None for
them and nothing changes.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint

# Modules a customer account may read outside the depot: what the Desk itself is built
# from — files, comments, notes, list settings, dashboards, print formats — and nothing
# else. `Contacts` and `Geo` are deliberately NOT here; Contact and Address are other
# customers' data, and no depot form a customer can open needs to pick one. See
# `foreign_doctype_*` at the bottom of this file for what this list is for.
_DESK_PLUMBING_MODULES = {"Core", "Custom", "Desk", "Printing"}

# Doctypes outside the Container Depot module the wildcard gate below must NOT empty.
# `Customer` is scoped natively — a User Permission on a doctype applies to that doctype's
# own `name`, so the list shows only the companies the account is tied to. `Item` and
# `Item Group` are here for their PICKERS only: the role holds `select` on them and no
# `read` (install.CUSTOMER_DESK_MASTERS), so neither has a list view or a menu entry.
#
# The read itself is a Custom DocPerm seeded by `install._grant_customer_desk_masters`,
# written after `setup_custom_perms` has copied ERPNext's own rows across.
# `Branch` is here for a different reason than the other three: it is the one REQUIRED link
# on a Container Booking, so without it the wildcard gate below empties the picker and a
# customer cannot save the booking it is allowed to raise at all. It carries no customer
# data — a branch is a depot location, already printed on every document they hold.
_ALLOWED_FOREIGN_DOCTYPES: set[str] = {"Customer", "Item", "Item Group", "Branch"}

# The only reports a customer account may see or run. An allowlist BY NAME, not by the ref
# doctype's `report` permission: that flag is per doctype, and four of this app's reports
# hang off `Container Booking` alone. One of them (`Lift On Register`) builds raw SQL that
# no `permission_query_conditions` touches, so granting the flag and stopping there would
# hand over the whole depot.
#
# EVERY entry reads through a filter it asks for BY HAND, and that is the price of entry:
# `permission_query_conditions` never reaches a Script Report, and neither does a User
# Permission — `frappe.get_all` runs with `ignore_permissions=True`, so even the reports
# that look like ordinary list reads are unscoped until they call one of the filters below
# (`booking_sql_filter`, `container_sql_filter`, `principal_sql_filter`, or
# `get_user_customers` straight into a `frappe.get_all` filter dict).
#
#   Container Booking Register  — booking_sql_filter in its WHERE
#   Storage Charges             — frappe.get_all + get_user_customers
#   Container Inventory         — frappe.get_all + get_user_customers (principal)
#   Container Activity          — container_sql_filter in its WHERE
#   Inventory KPI per Principal — principal_sql_filter in each of its WHEREs
#
# A report added here needs the same treatment before it goes in.
CUSTOMER_REPORTS = {
	"Container Booking Register",
	"Storage Charges",
	# The "Container Inventory" section of the sidebar: the customer's own tanks, their
	# history, and the rollup of both. It replaced the raw Audit lists (Gate Entry /
	# Container Movement / Container Activity) for this role — same facts, read through a
	# report that can be filtered, rather than three doctype lists that could not carry a
	# storage age or an order column.
	"Container Inventory",
	"Container Activity",
	"Inventory KPI per Principal",
}

# Core doctypes the Desk plumbing would otherwise carry through, kept shut anyway. Empty
# since `Report` became a name allowlist (2026-09-18) rather than a closed door — see
# `report_query` below for what replaced it and why the menu still cannot lie.
_DENIED_CORE_DOCTYPES: set[str] = set()

_SKIP_USERS = {"Administrator", "Guest"}


def get_user_customers(user: str | None = None) -> list[str] | None:
	"""Customers this user is restricted to, or ``None`` when unrestricted.

	Mirrors the convention in ``user_branch.get_user_branches``: no User Permission at
	all means no restriction (that is every internal account), NOT "sees nothing".
	"""
	user = user or frappe.session.user
	if user in _SKIP_USERS:
		return None
	# Frappe's own cached reader, not a fresh query: these functions run on every list
	# load, every dashboard number and every document open.
	permissions = frappe.permissions.get_user_permissions(user) or {}
	customers = [
		p.get("doc") for p in permissions.get("Customer", []) if not p.get("applicable_for")
	]
	return customers or None


def _values(user: str | None) -> str | None:
	"""Escaped, comma-joined customer names for an SQL ``in`` clause."""
	customers = get_user_customers(user)
	if not customers:
		return None
	return ", ".join(frappe.db.escape(c, percent=False) for c in customers)


def _owned_containers(values: str) -> str:
	return f"(select `name` from `tabContainer` where `principal` in ({values}))"


# --- permission_query_conditions (list views, reports, cards, charts) -------


def gate_entry_query(user=None, doctype=None) -> str:
	"""Gate Entry has no Customer link — join through its tank's principal.

	``Container.container_no`` is the doctype's autoname, so ``container_no`` on the gate
	row IS the Container's primary key.
	"""
	values = _values(user)
	if not values:
		return ""
	return f"`tabGate Entry`.`container_no` in {_owned_containers(values)}"


def container_movement_query(user=None, doctype=None) -> str:
	values = _values(user)
	if not values:
		return ""
	return f"`tabContainer Movement`.`container` in {_owned_containers(values)}"


def container_booking_query(user=None, doctype=None) -> str:
	"""Billed-to OR tank owner for a customer; everyone else, minus unsent customer drafts.

	The second half is the only place in this file that restricts an INTERNAL account, and it
	is not a permission so much as an inbox: a booking a customer is still typing says
	``Draft`` and belongs to nobody's queue. Pressing **Ajukan**
	(``container_booking.submit_request``) moves it to ``Pengajuan``, which is what puts it on
	the office's list — and every guard on the office side treats the two the same
	(``container_booking.EDITABLE_STATUSES``).
	"""
	values = _values(user)
	if not values:
		return _unsent_request_filter(user)
	return (
		f"(`tabContainer Booking`.`customer` in ({values})"
		f" or `tabContainer Booking`.`principal` in ({values})"
		# An EMKL raises bookings for tanks it neither owns nor is billed for. Without this
		# it would lose sight of its own request the moment it was saved.
		f" or `tabContainer Booking`.`requested_by_customer` in ({values}))"
	)


def _unsent_request_filter(user: str | None) -> str:
	"""Hide a customer's not-yet-submitted draft from the internal lists."""
	user = user or frappe.session.user
	if user == "Administrator":
		return ""
	return (
		"(ifnull(`tabContainer Booking`.`requested_by_customer`, '') = ''"
		" or `tabContainer Booking`.`booking_status` != 'Draft'"
		f" or `tabContainer Booking`.`owner` = {frappe.db.escape(user, percent=False)})"
	)


# --- the customer's own address book ---------------------------------------
# A portal account fills in the parties its booking needs (its EMKL, its shipper) itself.
# Two halves: the record is STAMPED with the company that asked for it, and the pickers on
# the booking form are narrowed to "mine + what I created" — because the fields those
# pickers sit on carry `ignore_user_permissions`, which switches the User Permission filter
# off entirely and would otherwise hand a customer OAK's whole customer book.


def stamp_customer_created_master(doc, method=None) -> None:
	"""Stamp a Customer created by a portal account with the company that created it.

	`doc_events` on Customer.before_insert. A no-op for every internal account, which holds
	no Customer User Permission — so OAK's own masters are never stamped, and "blank" keeps
	meaning "the depot's own, shared by everyone".
	"""
	if doc.get("created_by_customer"):
		return
	customers = get_user_customers()
	if customers:
		doc.created_by_customer = customers[0]


def allowed_principals(user: str | None = None) -> list[str] | None:
	"""Tank owners this account may raise a booking FOR, or ``None`` when unrestricted.

	Read straight off the OAK Party Roles on the account's own Customer master — the
	checkboxes the office already keeps there, not a second list to maintain:

	* **Tank Owner only** — its own tanks. Nobody else's is any of its business.
	* **EMKL (`is_transporter`)** — every registered tank owner. Lifting somebody else's
	  tank IS the job; the tanks it may then pick are that principal's, narrowed by
	  `booking_container_query`.
	* **Both** — the union, which is the tank-owner list with its own company in it.

	Anything else (an agent, a surveyor) gets its own company and nothing more: a party
	role this app cannot read as "moves other people's tanks" is not one that widens
	access.
	"""
	customers = get_user_customers(user)
	if not customers:
		return None
	is_transporter = frappe.db.exists(
		"Customer", {"name": ["in", customers], "is_transporter": 1}
	)
	if not is_transporter:
		return customers
	owners = frappe.get_all(
		"Customer", filters={"is_tank_owner": 1, "disabled": 0}, pluck="name"
	)
	return sorted(set(owners) | set(customers))


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def principal_link_query(doctype, txt, searchfield, start, page_len, filters):
	"""The Principal (Tank Owner) picker on a booking, for a portal account.

	Wired from the form script for portal accounts only — see `allowed_principals` for what
	decides the list, and `container_booking._clamp_customer_request` for the server-side
	half a hand-built API call meets instead.
	"""
	allowed = allowed_principals()
	conditions = [["Customer", "name", "in", allowed]] if allowed else []
	if txt:
		conditions.append(["Customer", "customer_name", "like", f"%{txt}%"])
	return frappe.get_all(
		"Customer",
		filters=conditions,
		fields=["name", "customer_name"],
		limit_start=start,
		limit_page_length=page_len,
		order_by="customer_name asc",
		as_list=True,
	)


PARTY_ROLES = {
	# What the booking form offers when a customer adds a party of its own, and the flag
	# each one sets on the Customer master. `shipper` carries no flag — ERPNext has no such
	# party role and this app never asks for one.
	"emkl": "is_transporter",
	"surveyor": "is_surveyor",
	"shipper": None,
}


@frappe.whitelist()
def create_party(customer_name, role=None):
	"""Create one party (EMKL / shipper / surveyor) on behalf of a portal account.

	Why this exists rather than a `create` DocPerm on Customer: the account's company flag
	is a User Permission ON Customer, and `has_user_permission` refuses any document of that
	doctype whose own name is not named in the permission — a record that does not exist yet
	never is. Frappe's own "Create a new Customer" from the link field therefore cannot work
	for this account whatever the role permissions say, and granting `create` would only
	produce a button that always 403s.

	So the insert runs with `ignore_permissions`, and the guard is this function: the caller
	must BE a portal account, and what it writes is a name, one role flag, and the stamp
	(`stamp_customer_created_master`, on before_insert) that ties the record to the company
	that asked for it. Nothing else — no credit limit, no tax template, no price list.
	"""
	customers = get_user_customers()
	if not customers:
		frappe.throw(_("Hanya akun customer yang bisa menambah pihak dari form ini."), frappe.PermissionError)
	name = (customer_name or "").strip()
	if not name:
		frappe.throw(_("Nama pihak wajib diisi."))
	if role and role not in PARTY_ROLES:
		frappe.throw(_("Jenis pihak tidak dikenal: {0}").format(role))
	if frappe.db.exists("Customer", {"customer_name": name}):
		frappe.throw(_("{0} sudah terdaftar — pilih dari daftar.").format(name))
	doc = frappe.get_doc({
		"doctype": "Customer",
		"customer_name": name,
		"customer_type": "Company",
	})
	flag = PARTY_ROLES.get(role or "")
	if flag:
		doc.set(flag, 1)
	doc.insert(ignore_permissions=True)
	return {"name": doc.name, "customer_name": doc.customer_name}


@frappe.whitelist()
def create_tank(container_no, principal=None, container_type=None):
	"""Register one tank for a portal account — the Desk's "Create a new Container", guarded.

	Same reasoning as :func:`create_party`, and the same road round the same wall: a portal
	account holds `read` on Container and nothing more, so Frappe's own "Create a new ..."
	from the Link field is not offered to it. Without this the only way to announce a tank
	the master does not know yet is the grid's Excel import — fine for twenty tanks, absurd
	for one.

	The tank is born the way an imported one is (`_create_imported_container`): owned by the
	booking's Principal and left at the Container default `Gate_Out`, i.e. outside the depot.
	Picking it on a Tank In row is what reserves it; nothing here touches a booking.
	"""
	allowed = allowed_principals()
	if allowed is None:
		frappe.throw(_("Hanya akun customer yang bisa mendaftarkan tank dari form ini."), frappe.PermissionError)
	principal = principal or (allowed[0] if len(allowed) == 1 else None)
	if not principal:
		frappe.throw(_("Pilih <b>Principal / Tank Owner</b> dulu — tank ini milik siapa."))
	if principal not in allowed:
		frappe.throw(
			_("Anda tidak boleh mendaftarkan tank untuk principal {0}.").format(principal),
			frappe.PermissionError,
		)
	no = (container_no or "").strip().upper()
	if not no:
		frappe.throw(_("Nomor container wajib diisi."))
	if frappe.db.exists("Container", no):
		frappe.throw(_("Container {0} sudah terdaftar — pilih dari daftar.").format(no))
	doc = frappe.get_doc({
		"doctype": "Container",
		"container_no": no,
		"container_type": container_type or "ISO Tank",
		"principal": principal,
	})
	doc.insert(ignore_permissions=True)
	return {"name": doc.name, "principal": doc.principal}


def _own_and_created(user: str | None = None) -> list[str] | None:
	"""The customers a portal account may NAME on a booking, or None if unrestricted."""
	customers = get_user_customers(user)
	if not customers:
		return None
	created = frappe.get_all(
		"Customer", filters={"created_by_customer": ["in", customers]}, pluck="name"
	)
	return sorted(set(customers) | set(created))


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def customer_link_query(doctype, txt, searchfield, start, page_len, filters):
	"""Link query for the party pickers on a Container Booking.

	Wired from the form script for PORTAL ACCOUNTS ONLY (`container_booking.js`), so an
	internal desk keeps Frappe's stock search and everything it does — nothing about the
	office's pickers changes.

	It exists because the fields it serves (`customer`, `principal`, `surveyor`, and the
	`emkl` / `shipper` / `surveyor` on each row) carry `ignore_user_permissions`: that flag
	is what keeps a booking billed to A for tanks owned by B visible to both, and it also
	switches OFF the only filter standing between a customer and every party name OAK has
	ever keyed in. This puts a filter back, and a narrower one: the account's own company,
	plus the parties that company created for itself.
	"""
	allowed = _own_and_created()
	conditions = [["Customer", "name", "in", allowed]] if allowed else []
	if txt:
		conditions.append(["Customer", "customer_name", "like", f"%{txt}%"])
	# Whatever the field already narrowed by — `is_surveyor` on the two surveyor pickers.
	# Equality only: that is every filter a link query on this form passes.
	for field, value in (filters or {}).items():
		conditions.append(["Customer", field, "=", value])
	return frappe.get_all(
		"Customer",
		filters=conditions,
		fields=["name", "customer_name"],
		limit_start=start,
		limit_page_length=page_len,
		order_by="customer_name asc",
		as_list=True,
	)


def report_query(user=None, doctype=None) -> str:
	"""Show a customer only the reports in ``CUSTOMER_REPORTS``.

	This is what keeps the report links in the workspace cards and the left sidebar honest.
	Both menus ask `boot.get_allowed_reports`, which ends by running
	`frappe.get_list("Report", ...)` and dropping everything that query does not return
	(`non_permitted_reports`) — so a report filtered out here is never drawn, rather than
	drawn and then refused on click.

	It used to be the whole doctype: `Report` sat in `_DENIED_CORE_DOCTYPES`, the list came
	back empty and the customer got no report links at all. Narrowed to a name filter on
	2026-09-18 so the two reports the customer is owed can be reached. The run path is
	guarded separately — a list filter does not stop an API call, see
	`boot.patch_query_report_customer_scope`.
	"""
	if not get_user_customers(user):
		return ""
	names = ", ".join(frappe.db.escape(n, percent=False) for n in sorted(CUSTOMER_REPORTS))
	return f"`tabReport`.`name` in ({names})"


def booking_sql_filter(alias: str) -> str:
	"""AND-clause scoping raw SQL over Container Booking; ``1=1`` for internal accounts.

	`permission_query_conditions` only reaches queries built by `frappe.get_all`. A Script
	Report that writes its own SELECT has to ask for the same condition by hand, and every
	report in `CUSTOMER_REPORTS` that does so calls this.
	"""
	values = _values(None)
	if not values:
		return "1=1"
	return (
		f"({alias}.customer in ({values}) or {alias}.principal in ({values})"
		f" or {alias}.requested_by_customer in ({values}))"
	)


def container_sql_filter(column: str) -> str:
	"""AND-clause scoping raw SQL that names a Container; ``1=1`` for internal accounts.

	``column`` is the qualified column holding the container name (e.g. ``a.container``).
	"""
	values = _values(None)
	if not values:
		return "1=1"
	return f"{column} in {_owned_containers(values)}"


def principal_sql_filter(column: str) -> str:
	"""AND-clause scoping raw SQL by tank owner; ``1=1`` for internal accounts.

	``column`` is the qualified column holding the principal (e.g. ``c.principal``).
	"""
	values = _values(None)
	if not values:
		return "1=1"
	return f"{column} in ({values})"


# --- has_permission (opening one document directly) ------------------------
# A query condition only guards the list. Frappe routes a single-document read through
# has_permission, so every doctype filtered above needs the same test again here.
#
# A controller hook can only DENY (frappe.permissions.has_controller_permissions treats a
# falsy return — None included — as a refusal), so each of these returns True explicitly.


def _allowed(value: str | None, user: str | None) -> bool:
	customers = get_user_customers(user)
	return not customers or value in customers


def _principal_of(container: str | None) -> str | None:
	return frappe.db.get_value("Container", container, "principal") if container else None


def gate_entry_permission(doc, ptype=None, user=None, **kwargs) -> bool:
	return _allowed(_principal_of(doc.get("container_no")), user)


def container_movement_permission(doc, ptype=None, user=None, **kwargs) -> bool:
	return _allowed(_principal_of(doc.get("container")), user)


# What a customer account may do to a Container Booking, beyond reading it. Anything not
# listed is refused outright — `submit` and `amend` among them: confirming a booking is the
# office's decision, and amending a cancelled one is how a customer would otherwise get back
# inside a document the office closed.
#
# `cancel` is in, and it is not the office's Cancel: on a draft it reaches
# `container_booking.void_draft` (the ONLY undo a draft has — a booking is never deleted,
# `on_trash` refuses), and the window below keeps it to a booking the customer has not yet
# handed over. A `Pengajuan` or anything past it is out of reach, as is every submitted one.
_CUSTOMER_BOOKING_WRITES = {"write", "create", "delete", "cancel"}


def container_booking_permission(doc, ptype=None, user=None, **kwargs) -> bool:
	customers = get_user_customers(user)
	if not customers:
		# Internal: everything except somebody's unsent customer draft — see
		# `_unsent_request_filter`, this is the same rule for a direct document open.
		if (user or frappe.session.user) == "Administrator":
			return True
		if doc.get("requested_by_customer") and doc.get("booking_status") == "Draft":
			return doc.get("owner") == (user or frappe.session.user)
		return True
	if not (
		doc.get("customer") in customers
		or doc.get("principal") in customers
		or doc.get("requested_by_customer") in customers
	):
		return False
	if ptype in (None, "read", "select", "print", "export", "report", "email"):
		return True
	if ptype == "create":
		# A brand-new document: there is no window to test yet, and what it may contain is
		# pinned server-side the moment it is saved (`_clamp_customer_request` forces the
		# Principal to this account's own company). The ownership test above still applies —
		# a payload naming somebody else's company never reaches the clamp.
		return True
	if ptype not in _CUSTOMER_BOOKING_WRITES:
		return False
	# The editing window: their OWN booking, before they hand it over. `Pengajuan` onwards
	# the office owns the document — see `container_booking.submit_request`.
	return (
		bool(doc.get("requested_by_customer"))
		and doc.get("owner") == (user or frappe.session.user)
		and cint(doc.get("docstatus")) == 0
		and doc.get("booking_status") == "Draft"
	)


def report_permission(doc, ptype=None, user=None, **kwargs) -> bool:
	return doc.get("name") in CUSTOMER_REPORTS or not get_user_customers(user)


# --- the rest of the site --------------------------------------------------
# A customer account is a System User, and a System User inherits every doctype the stock
# `All` / `Desk User` roles can read — which on this site includes another app's support
# tickets (HD Ticket), staff leave ledgers, Quality records and a pile of integration
# settings. Blocking the modules (portal._restrict_modules) takes those off the sidebar; it
# does not stop someone typing /app/hd-ticket. These two close the doctype itself.
#
# An allowlist, not a list of the offenders: the next app installed adds its own doctypes
# to that inheritance, and a deny-list would not know about them.


def _is_foreign(doctype: str | None) -> bool:
	if not doctype or doctype in _ALLOWED_FOREIGN_DOCTYPES:
		return False
	if doctype in _DENIED_CORE_DOCTYPES:
		return True
	module = frappe.get_cached_value("DocType", doctype, "module")
	if module == "Container Depot":
		return False  # its own DocPerm decides — the customer role holds six of them
	return module not in _DESK_PLUMBING_MODULES


def foreign_doctype_query(user=None, doctype=None) -> str:
	"""Empty every list outside the depot for a customer account (hooks `*`)."""
	if not get_user_customers(user) or not _is_foreign(doctype):
		return ""
	return "1=0"


def foreign_doctype_permission(doc, ptype=None, user=None, **kwargs) -> bool:
	if not get_user_customers(user):
		return True
	return not _is_foreign(doc.get("doctype"))
