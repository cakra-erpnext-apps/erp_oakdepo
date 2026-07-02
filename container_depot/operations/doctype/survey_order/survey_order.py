"""Survey Order — third-party survey charges billed to a customer (Paid To).

Draft → (submit) → Payment Pending (Cash) / Submitted (TOP). Each row in the
``charges`` table is one survey charge for one container (container optional).
On submit, **Cash** raises a DRAFT Sales Invoice (one line per charge) for the
Paid To — left as draft so the user can review / add tax before submitting &
collecting payment. **TOP** raises no invoice (billed later via the per-customer
invoice run). Cancelling the Survey Order rolls its invoice back: a draft is
deleted, a submitted one is cancelled (blocked if it already has a payment).
"""

import frappe
from frappe.model.document import Document
from frappe.utils import flt

from container_depot import invoicing, pricing_model


class SurveyOrder(Document):
    def validate(self):
        self._resolve_pricing()
        self.total = sum(flt(c.price) for c in self.charges)
        if self.docstatus == 0 and not self.status:
            self.status = "Draft"

    def _resolve_pricing(self):
        """Fill price list / currency from Paid To, and auto-price blank charge rows."""
        if self.paid_to and not self.price_list:
            self.price_list = pricing_model.price_list_for_customer(self.paid_to)
        if not self.currency:
            self.currency = (
                frappe.db.get_value("Price List", self.price_list, "currency")
                if self.price_list
                else None
            ) or frappe.defaults.get_global_default("currency") or "IDR"
        # Auto-price any row that has an item + price list but no manual price yet.
        for c in self.charges:
            if c.item and self.price_list and not flt(c.price):
                c.price = flt(pricing_model.resolve_price(c.item, self.price_list))

    def before_submit(self):
        if not self.paid_to:
            frappe.throw("Paid To wajib diisi.")
        if not any(c.item for c in self.charges):
            frappe.throw("Minimal satu Charge dengan Item wajib diisi.")
        if flt(self.total) <= 0:
            frappe.throw("Total harus lebih dari 0.")

    def on_submit(self):
        if self.payment_type == "Cash":
            # Cash: raise a DRAFT Sales Invoice now (review/add tax, then submit & collect).
            self._create_invoice()
            self.db_set("status", "Payment Pending")
        else:
            # TOP: no invoice yet — billed later via the per-customer invoice run.
            self.db_set("status", "Submitted")
            self.db_set("invoice_status", "Not Invoiced")

    def _create_invoice(self):
        if self.sales_invoice:
            return
        # Cash bills due today (only Cash reaches this path).
        due_days = 0
        lines = []
        for c in self.charges:
            if not c.item:
                continue
            ref = c.container_no or c.container or ""
            desc = f"Survey {c.survey_date or ''} — {ref}".strip(" —")
            if self.notes:
                desc = f"{desc} · {self.notes}" if desc else self.notes
            lines.append({
                "item_code": c.item,
                "description": desc or c.item,
                "qty": 1,
                "rate": flt(c.price),
            })
        if not lines:
            frappe.throw("Tidak ada Charge yang bisa ditagih.")
        inv = invoicing.create_draft_sales_invoice(
            customer=self.paid_to,
            lines=lines,
            due_days=due_days,
            remarks=f"Survey Order {self.name}",
            currency=self.currency,
            selling_price_list=self.price_list or None,
        )
        if not inv:
            frappe.throw(
                "Gagal membuat Sales Invoice — site belum invoice-ready "
                "(cek default Company & Customer). Survey Order tidak jadi disubmit."
            )
        # Leave the invoice as a DRAFT so the user can review / add tax before
        # submitting & collecting payment. invoice_status tracks it live from here
        # on (submit → Unpaid, payment → Paid) via the Sales Invoice / Payment Entry
        # doc_event bridges below.
        self.db_set("sales_invoice", inv)
        self.db_set("invoice_status", _survey_invoice_status(inv))

    def on_cancel(self):
        self._rollback_invoice()
        self.db_set("status", "Cancelled")
        # Draft deleted → link cleared → "Not Invoiced"; submitted-then-cancelled → "Cancelled".
        self.db_set("invoice_status", _survey_invoice_status(self.sales_invoice))

    def _rollback_invoice(self):
        """Roll back the linked Sales Invoice on cancel; block if it's been paid."""
        if not self.sales_invoice or not frappe.db.exists("Sales Invoice", self.sales_invoice):
            return
        si = frappe.get_doc("Sales Invoice", self.sales_invoice)
        if si.docstatus == 2:  # already cancelled — nothing to roll back
            return
        if si.docstatus == 0:  # still a draft — unlink then delete it
            name = si.name
            self.db_set("sales_invoice", None)  # clear the link so delete isn't blocked
            frappe.delete_doc("Sales Invoice", name, ignore_permissions=True)
            return
        paid = flt(si.grand_total) - flt(si.outstanding_amount)
        if paid > 0:
            frappe.throw(
                f"Sales Invoice {si.name} sudah menerima pembayaran ({paid:.2f}). "
                "Batalkan / refund Payment Entry-nya dulu sebelum cancel Survey Order."
            )
        si.flags.ignore_permissions = True
        si.cancel()


# ── Invoice-status sync (Survey Order ↔ its Sales Invoice) ─────────────────────
# Mirrors the linked Sales Invoice's live state onto the Survey Order so the form
# and list always show whether the survey is Draft / Unpaid / Paid / Cancelled —
# instead of freezing at "Payment Pending". Same shape as the Container Booking
# bridge: every handler is a no-op unless a Survey Order links the invoice, so
# plain ERPNext invoices/payments are left untouched. Wired in hooks.doc_events.

def _survey_invoice_status(sales_invoice):
    """Map a linked Sales Invoice's live state to a Survey Order ``invoice_status``."""
    if not sales_invoice or not frappe.db.exists("Sales Invoice", sales_invoice):
        return "Not Invoiced"
    si = frappe.db.get_value(
        "Sales Invoice", sales_invoice,
        ["docstatus", "status", "outstanding_amount", "grand_total"], as_dict=True,
    )
    if not si:
        return "Not Invoiced"
    if si.docstatus == 0:
        return "Draft"
    if si.docstatus == 2:
        return "Cancelled"
    # Submitted: read settlement from status / outstanding.
    if si.status in ("Paid", "Credit Note Issued") or flt(si.outstanding_amount) <= 0:
        return "Paid"
    if "Overdue" in (si.status or ""):
        return "Overdue"
    if flt(si.outstanding_amount) < flt(si.grand_total):
        return "Partly Paid"
    return "Unpaid"


def sync_survey_orders_for_invoice(sales_invoice):
    """Push a Sales Invoice's live status onto every Survey Order pinned to it.
    No-op unless a Survey Order links the invoice."""
    status = _survey_invoice_status(sales_invoice)
    for name in frappe.get_all("Survey Order", filters={"sales_invoice": sales_invoice}, pluck="name"):
        row = frappe.db.get_value(
            "Survey Order", name, ["docstatus", "status", "invoice_status"], as_dict=True
        )
        if not row or row.docstatus == 2:  # cancelled order — leave it be
            continue
        if row.invoice_status != status:
            frappe.db.set_value("Survey Order", name, "invoice_status", status, update_modified=False)
        # Close out a Cash order once its invoice is settled.
        if status == "Paid" and row.status == "Payment Pending":
            frappe.db.set_value("Survey Order", name, "status", "Paid", update_modified=False)


# --- Sales Invoice / Payment Entry → Survey Order bridges (hooks.doc_events) -------
def relink_amended_invoice(doc, method=None):
    """after_insert: follow a Cash order's invoice across an amendment (new invoice
    carries ``amended_from`` = the old one), then refresh invoice_status."""
    if not doc.amended_from:
        return
    moved = frappe.get_all("Survey Order", filters={"sales_invoice": doc.amended_from}, pluck="name")
    for name in moved:
        frappe.db.set_value("Survey Order", name, "sales_invoice", doc.name, update_modified=False)
    if moved:
        sync_survey_orders_for_invoice(doc.name)


def sync_survey_on_invoice_submit(doc, method=None):
    """on_submit: Cash draft invoice submitted → Survey Order reads Unpaid (or Paid)."""
    sync_survey_orders_for_invoice(doc.name)


def sync_survey_on_invoice_cancel(doc, method=None):
    """on_cancel: invoice cancelled directly → Survey Order reads Cancelled."""
    sync_survey_orders_for_invoice(doc.name)


def on_payment_entry_change(doc, method=None):
    """Payment Entry on_submit / on_cancel: refresh the invoice_status of any Survey
    Order tied to the Sales Invoice(s) this payment settles (runs after ERPNext has
    recomputed the invoice outstanding, so the read is current)."""
    seen = set()
    for ref in (doc.get("references") or []):
        si = ref.reference_name if ref.reference_doctype == "Sales Invoice" else None
        if si and si not in seen:
            seen.add(si)
            sync_survey_orders_for_invoice(si)


# ── Whitelisted helpers used by the client form ───────────────────────────────
@frappe.whitelist()
def get_pricing_context(customer):
    """Price list + currency for a Paid To (customer)."""
    pl = pricing_model.price_list_for_customer(customer)
    cur = frappe.db.get_value("Price List", pl, "currency") if pl else None
    return {"price_list": pl, "currency": cur}


@frappe.whitelist()
def get_item_price(item, price_list):
    """Resolved selling rate for an item in a price list."""
    if not price_list:
        return 0
    return pricing_model.resolve_price(item, price_list)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def item_price_query(doctype, txt, searchfield, start, page_len, filters):
    """Link-field query: items that have a selling Item Price in the given price list."""
    price_list = (filters or {}).get("price_list")
    if not price_list:
        return []
    like = f"%{txt}%"
    return frappe.db.sql(
        """
        select distinct ip.item_code, i.item_name
        from `tabItem Price` ip
        join `tabItem` i on i.name = ip.item_code
        where ip.price_list = %(pl)s and ip.selling = 1
          and (ip.item_code like %(txt)s or i.item_name like %(txt)s)
        order by ip.item_code
        limit %(start)s, %(page_len)s
        """,
        {"pl": price_list, "txt": like, "start": start, "page_len": page_len},
    )
