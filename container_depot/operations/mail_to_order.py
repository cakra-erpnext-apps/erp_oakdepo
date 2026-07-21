"""Email → Order bridge.

An incoming email (a ``Communication`` of medium Email, ``Received``) is the paper
trail behind most depot work: a customer mails a booking request, a repair estimate
reply, a survey ask, a cleaning request. This module lets an operator turn that email
into a draft order (Container Booking / Repair Order / Survey Order / Cleaning Order)
straight from the Communication form, and pull new mail on demand — the desk mirror of
the Email Account "Pull Emails" button, but scoped to the accounts set on the user.

Nothing here creates a record on its own: ``get_order_prefill`` only computes what to
pre-fill; the operator opens a fresh, unsaved order form with those values and completes
the mandatory bits (container / items) before saving. So the email stays the *reference*
and no half-empty drafts leak into the DB.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import strip_html_tags

# order_type (as sent by the client) -> (target doctype, customer field or None).
# The customer field is where the sender-resolved Customer lands; None means the
# doctype has no party field (repair / cleaning are container-centric).
ORDER_MAP = {
	"Booking": ("Container Booking", "customer"),
	"M&R": ("Repair Order", None),
	"Survey": ("Survey Order", "paid_to"),
	"Cleaning": ("Cleaning Order", None),
}

# Where the email body lands. Survey Order has no `remarks` — it uses `notes`.
_NOTE_FIELD = {
	"Container Booking": "remarks",
	"Repair Order": "remarks",
	"Cleaning Order": "remarks",
	"Survey Order": "notes",
}

# The link back to the source email. Deliberately NOT `reff_doc`: that field is the
# vendor's own document number (it propagates booking → bon → EIR → Cleaning / M&R and
# is hand-entered), so stuffing an email reference in there would corrupt that chain.
# `reff_email` is read-only and only ever written here.
_EMAIL_REF_FIELD = "reff_email"

_SNIPPET_LEN = 600


def _resolve_customer(email: str | None) -> str | None:
	"""Best-effort: find the Customer behind a sender email via its Contact.

	Returns None (never raises) when nothing matches — the operator then picks the
	Customer by hand on the new order.
	"""
	if not email:
		return None
	email = email.strip().lower()
	contacts = frappe.get_all(
		"Contact Email", filters={"email_id": ("like", email)}, pluck="parent"
	)
	for contact in contacts:
		customer = frappe.db.get_value(
			"Dynamic Link",
			{
				"parent": contact,
				"parenttype": "Contact",
				"link_doctype": "Customer",
			},
			"link_name",
		)
		if customer:
			return customer
	return None


def _email_reference(comm) -> str:
	"""Human-readable provenance line stuffed into the order's remarks/notes."""
	body = strip_html_tags(comm.content or "").strip()
	if len(body) > _SNIPPET_LEN:
		body = body[:_SNIPPET_LEN].rstrip() + "…"
	lines = [
		_("Dibuat dari email:"),
		_("Subjek: {0}").format(comm.subject or "-"),
		_("Dari: {0}").format(comm.sender or "-"),
		_("Tanggal: {0}").format(comm.communication_date or comm.creation or "-"),
	]
	if body:
		lines += ["", body]
	return "\n".join(lines)


@frappe.whitelist()
def get_order_prefill(communication: str, order_type: str) -> dict:
	"""Return {doctype, values} to seed a new order form from an email.

	Read-only: creates nothing. The client opens a fresh order form pre-filled with
	these values (customer resolved from sender, email content copied into remarks,
	source email linked via the read-only `reff_email`).
	"""
	target = ORDER_MAP.get(order_type)
	if not target:
		frappe.throw(_("Tipe order tidak dikenal: {0}").format(order_type))
	doctype, customer_field = target

	frappe.has_permission("Communication", "read", doc=communication, throw=True)
	if not frappe.has_permission(doctype, "create"):
		frappe.throw(
			_("Anda tidak punya izin membuat {0}.").format(_(doctype)),
			frappe.PermissionError,
		)

	comm = frappe.get_doc("Communication", communication)

	values: dict[str, str] = {
		_NOTE_FIELD[doctype]: _email_reference(comm),
		_EMAIL_REF_FIELD: comm.name,
	}
	if customer_field:
		customer = _resolve_customer(comm.sender)
		if customer:
			values[customer_field] = customer

	return {"doctype": doctype, "values": values}


@frappe.whitelist()
def pull_my_emails() -> dict:
	"""Pull new mail for the incoming Email Accounts set on the current user.

	Desk mirror of the Email Account "Pull Emails" button, but scoped to the accounts
	linked under the user's ``User Emails`` — so each operator only fetches their own
	inbox (nothing configured → a clear message, no error).
	"""
	user = frappe.session.user
	accounts = frappe.get_all("User Email", filters={"parent": user}, pluck="email_account")
	incoming = [
		a
		for a in dict.fromkeys(accounts)  # dedupe, keep order
		if a and frappe.db.get_value("Email Account", a, "enable_incoming")
	]
	if not incoming:
		frappe.msgprint(
			_("Belum ada Email Account (incoming) yang di-set di user Anda. "
			  "Set di User → Settings → Email Inbox terlebih dahulu."),
			title=_("Tarik Email"),
		)
		return {"pulled": [], "failed": []}

	pulled, failed = [], []
	for account in incoming:
		try:
			frappe.get_doc("Email Account", account).receive()
			pulled.append(account)
		except Exception:
			failed.append(account)
			frappe.log_error(
				title=f"pull_my_emails: {account}",
				message=frappe.get_traceback(),
			)

	if pulled:
		frappe.msgprint(
			_("Email ditarik dari: {0}").format(", ".join(pulled)),
			title=_("Tarik Email"),
			indicator="green",
		)
	if failed:
		frappe.msgprint(
			_("Gagal menarik dari: {0}. Cek konfigurasi/kata sandi akun tersebut.").format(
				", ".join(failed)
			),
			title=_("Tarik Email"),
			indicator="orange",
		)
	return {"pulled": pulled, "failed": failed}
