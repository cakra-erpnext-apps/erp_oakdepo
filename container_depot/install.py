import os

import frappe

# Legacy blanket-grant role list. Kept for backwards compatibility on existing
# sites — the real per-role matrix below now supersedes it. Anything still in
# this list also gets unrestricted DocPerms on every Operations doctype.
ROLES_TO_GRANT = ["System Manager", "Container Depot"]

# Narrow service role used by SST / agent traffic. Created (idempotently) on
# install and on every migrate, but kept out of ROLES_TO_GRANT so it does not
# accidentally pick up the blanket DocPerm grant.
SST_SERVICE_ROLE = "Container Depot SST Service"

# PWA access role. Gates the /depot page (www/depot.py) and carries the DocPerms
# the PWA exercises under the caller's session. Created with desk_access=0 (website
# /PWA only). The admin assigns it to users; it is not auto-granted to anyone.
PWA_ROLE = "Depot PWA"

# Real per-role matrix introduced in Phase 6. Roles listed here are created on
# install + every migrate; the permission matrix in ROLE_DOCTYPE_PERMISSIONS
# below decides who can see / change what.
PHASE6_ROLES = [
	"Customer",                       # ERPNext built-in; we scope via User Permission.
	"Depot Driver (SST)",
	"Security",
	"Admin Ops",
	"Surveyor",
	"Operator Kalmar",
	"Ops Supervisor",
	"Commercial",
	"Management",
	"IT Support",
	# Cash counter. Confirms walk-in payment by marking the booking's Sales
	# Invoice Paid (which releases the booking code on submit). The payment side
	# itself (Payment Entry / Sales Invoice) uses ERPNext's built-in "Accounts
	# User" role — we deliberately do NOT add Custom DocPerms to those core
	# doctypes, since any custom perm row would override ERPNext's standard
	# accounting permissions. Assign cashier logins both "Cashier" and
	# "Accounts User".
	"Cashier",
]

# Permission matrix: doctype -> {role: perm_dict}. perm_dict keys match the
# Custom DocPerm fields (read/write/create/delete/submit/cancel/amend/export
# /report/share). Missing keys default to 0. permlevel defaults to 0.
#
# Design notes:
# - System Manager always gets full perms; not enumerated here.
# - Customer perms are written but only become visible-per-row via the
#   User Permission link to Customer (auto-created by ensure_customer_user_permission).
# - Append-only logs (SST Activity Log, Container Movement) deny delete to
#   everyone except System Manager.
ROLE_DOCTYPE_PERMISSIONS = {
	"Container Booking": {
		"Customer":          {"read": 1, "create": 1, "submit": 0, "report": 1, "export": 1},
		"Commercial":        {"read": 1, "create": 1, "write": 1, "submit": 1, "cancel": 1, "amend": 1, "report": 1, "export": 1, "share": 1},
		"Admin Ops":         {"read": 1, "create": 1, "write": 1, "submit": 1, "cancel": 1, "report": 1},
		"Ops Supervisor":    {"read": 1, "write": 1, "report": 1},
		# Cashier confirms cash payment then submits to release the booking code.
		"Cashier":           {"read": 1, "write": 1, "submit": 1, "report": 1},
		"Security":          {"read": 1, "report": 1},
		"Surveyor":          {"read": 1, "report": 1},
		"Operator Kalmar":   {"read": 1, "report": 1},
		"Management":        {"read": 1, "report": 1, "export": 1},
		"IT Support":        {"read": 1, "report": 1},
	},
	"Booking Code": {
		"Customer":          {"read": 1, "report": 1},
		"Security":          {"read": 1, "report": 1},
		"Admin Ops":         {"read": 1, "write": 1, "create": 1, "report": 1},
		"Commercial":        {"read": 1, "write": 1, "create": 1, "report": 1},
		# Cashier reads/prints the QR voucher for the driver at the counter.
		"Cashier":           {"read": 1, "report": 1},
		"Ops Supervisor":    {"read": 1, "report": 1},
		"Management":        {"read": 1, "report": 1},
	},
	"Order Bongkar": {
		"Customer":          {"read": 1, "report": 1},
		"Security":          {"read": 1, "write": 1, "create": 1, "submit": 1, "report": 1},
		"Surveyor":          {"read": 1, "write": 1, "report": 1},
		"Admin Ops":         {"read": 1, "write": 1, "create": 1, "submit": 1, "cancel": 1, "report": 1},
		"Ops Supervisor":    {"read": 1, "write": 1, "report": 1},
		"Operator Kalmar":   {"read": 1, "report": 1},
	},
	"Order Muat": {
		"Customer":          {"read": 1, "report": 1},
		"Security":          {"read": 1, "write": 1, "create": 1, "submit": 1, "report": 1},
		"Surveyor":          {"read": 1, "write": 1, "report": 1},
		"Admin Ops":         {"read": 1, "write": 1, "create": 1, "submit": 1, "cancel": 1, "report": 1},
		"Ops Supervisor":    {"read": 1, "write": 1, "report": 1},
		"Operator Kalmar":   {"read": 1, "report": 1},
	},
	"Depot Contract": {
		"Customer":          {"read": 1, "report": 1},
		"Commercial":        {"read": 1, "create": 1, "write": 1, "submit": 1, "cancel": 1, "amend": 1, "report": 1},
		"Management":        {"read": 1, "report": 1, "export": 1},
		"IT Support":        {"read": 1, "report": 1},
	},
	# Depot Service Menu — a dynamic, group-based filter over the Item catalog
	# (Booking / Cleaning / Maintenance). Commercial / Admin Ops maintain it; the
	# M&R picker reads it (also granted to the PWA role via _PWA_DOCTYPE_PERMS).
	"Depot Service Menu": {
		"Commercial":        {"read": 1, "create": 1, "write": 1, "delete": 1, "report": 1},
		"Admin Ops":         {"read": 1, "create": 1, "write": 1, "report": 1},
		"Ops Supervisor":    {"read": 1, "report": 1},
		"Management":        {"read": 1, "report": 1, "export": 1},
		"IT Support":        {"read": 1, "report": 1},
	},
	"Container": {
		"Customer":          {"read": 1, "report": 1},
		"Security":          {"read": 1, "report": 1},
		"Surveyor":          {"read": 1, "write": 1, "report": 1},
		"Operator Kalmar":   {"read": 1, "write": 1, "report": 1},
		"Admin Ops":         {"read": 1, "write": 1, "create": 1, "delete": 1, "report": 1},
		"Ops Supervisor":    {"read": 1, "write": 1, "report": 1},
	},
	"Gate Entry": {
		"Customer":          {"read": 1, "report": 1},
		"Security":          {"read": 1, "create": 1, "write": 1, "submit": 1, "report": 1},
		"Admin Ops":         {"read": 1, "create": 1, "write": 1, "submit": 1, "cancel": 1, "report": 1},
	},
	"Inspection": {
		"Customer":          {"read": 1, "report": 1},
		"Surveyor":          {"read": 1, "create": 1, "write": 1, "submit": 1, "report": 1},
		"Admin Ops":         {"read": 1, "create": 1, "write": 1, "submit": 1, "cancel": 1, "report": 1},
		"Operator Kalmar":   {"read": 1, "report": 1},
	},
	"Repair Order": {
		# Tank Owner (Customer) approves/rejects M&R from Desk: status edit only.
		"Customer":          {"read": 1, "write": 1, "report": 1},
		"Surveyor":          {"read": 1, "write": 1, "report": 1},
		"Admin Ops":         {"read": 1, "create": 1, "write": 1, "submit": 1, "cancel": 1, "report": 1},
		"Ops Supervisor":    {"read": 1, "write": 1, "report": 1},
		"Management":        {"read": 1, "report": 1, "export": 1},
	},
	"Cleaning Certificate": {
		"Customer":          {"read": 1, "report": 1},
		"Surveyor":          {"read": 1, "create": 1, "write": 1, "submit": 1, "report": 1},
		"Admin Ops":         {"read": 1, "create": 1, "write": 1, "submit": 1, "cancel": 1, "report": 1},
	},
	"Cleaning Checklist Item": {
		"Surveyor":          {"read": 1, "report": 1},
		"Admin Ops":         {"read": 1, "create": 1, "write": 1, "report": 1},
		"Ops Supervisor":    {"read": 1, "report": 1},
	},
	# Cleaning Order — the cleaning team's worklist (auto-created from Empty-Dirty EIRs).
	# The team fills the cleanliness checklist and submits it (= Completed), which mints
	# the Cleaning Certificate. Editable + submittable from the PWA.
	"Cleaning Order": {
		"Surveyor":          {"read": 1, "write": 1, "submit": 1, "report": 1},
		"Operator Kalmar":   {"read": 1, "write": 1, "submit": 1, "report": 1},
		"Admin Ops":         {"read": 1, "create": 1, "write": 1, "submit": 1, "cancel": 1, "report": 1},
		"Ops Supervisor":    {"read": 1, "write": 1, "submit": 1, "report": 1},
		"Management":        {"read": 1, "report": 1, "export": 1},
	},
	"SST Activity Log": {
		"IT Support":        {"read": 1, "report": 1},
		"Ops Supervisor":    {"read": 1, "report": 1},
		# create-only for the SST service role lives in the doctype JSON itself.
	},
	"Container Movement": {
		"Operator Kalmar":   {"read": 1, "create": 1, "report": 1},
		"Admin Ops":         {"read": 1, "create": 1, "report": 1},
		"Ops Supervisor":    {"read": 1, "report": 1},
		"IT Support":        {"read": 1, "report": 1},
	},
	"Self Service Terminal": {
		"IT Support":        {"read": 1, "create": 1, "write": 1, "delete": 1, "report": 1},
		"Ops Supervisor":    {"read": 1, "report": 1},
	},
	# ---- v0.2 additions ------------------------------------------------
	"Depot": {
		"Admin Ops":         {"read": 1, "create": 1, "write": 1, "report": 1},
		"Commercial":        {"read": 1, "report": 1},
		"Ops Supervisor":    {"read": 1, "report": 1},
		"Management":        {"read": 1, "report": 1, "export": 1},
		"IT Support":        {"read": 1, "report": 1},
	},
	# Yard Zone master (Depot Storage feature). Operator Kalmar reads zones to place
	# tanks; Admin Ops maintains the zone/capacity config.
	"Yard Zone": {
		"Operator Kalmar":   {"read": 1, "report": 1},
		"Admin Ops":         {"read": 1, "create": 1, "write": 1, "report": 1},
		"Ops Supervisor":    {"read": 1, "report": 1},
		"Management":        {"read": 1, "report": 1, "export": 1},
		"IT Support":        {"read": 1, "report": 1},
	},
	"Inspection Damage Code": {
		"Surveyor":          {"read": 1, "create": 1, "write": 1, "report": 1},
		"Admin Ops":         {"read": 1, "create": 1, "write": 1, "report": 1},
		"Ops Supervisor":    {"read": 1, "report": 1},
	},
	"Inspection Repair Code": {
		"Surveyor":          {"read": 1, "create": 1, "write": 1, "report": 1},
		"Admin Ops":         {"read": 1, "create": 1, "write": 1, "report": 1},
		"Ops Supervisor":    {"read": 1, "report": 1},
	},
	"Inspection Checklist Item": {
		"Surveyor":          {"read": 1, "report": 1},
		"Admin Ops":         {"read": 1, "create": 1, "write": 1, "report": 1},
		"Ops Supervisor":    {"read": 1, "report": 1},
	},
	# Status -> allowed yard category master (drives placement + the 'needs move' list).
	"Yard Placement Rule": {
		"Operator Kalmar":   {"read": 1, "report": 1},
		"Surveyor":          {"read": 1, "report": 1},
		"Admin Ops":         {"read": 1, "create": 1, "write": 1, "delete": 1, "report": 1},
		"Ops Supervisor":    {"read": 1, "report": 1},
		"Management":        {"read": 1, "report": 1, "export": 1},
		"IT Support":        {"read": 1, "report": 1},
	},
	"Periodic Test": {
		"Customer":          {"read": 1, "report": 1},
		"Surveyor":          {"read": 1, "create": 1, "write": 1, "submit": 1, "report": 1},
		"Admin Ops":         {"read": 1, "create": 1, "write": 1, "submit": 1, "cancel": 1, "report": 1},
		"Commercial":        {"read": 1, "report": 1, "export": 1},
		"Ops Supervisor":    {"read": 1, "write": 1, "report": 1},
		"Management":        {"read": 1, "report": 1, "export": 1},
	},
	"Container Leasing": {
		"Customer":          {"read": 1, "report": 1},
		"Commercial":        {"read": 1, "create": 1, "write": 1, "report": 1, "export": 1},
		"Admin Ops":         {"read": 1, "create": 1, "write": 1, "report": 1},
		"Management":        {"read": 1, "report": 1, "export": 1},
	},
	# ---- B2 additions (customer portal backbone) -----------------------
	"Release DO": {
		"Customer":          {"read": 1, "create": 1, "write": 1, "submit": 1, "report": 1},
		"Admin Ops":         {"read": 1, "create": 1, "write": 1, "submit": 1, "cancel": 1, "report": 1},
		"Ops Supervisor":    {"read": 1, "write": 1, "report": 1},
		"Operator Kalmar":   {"read": 1, "report": 1},
		"Management":        {"read": 1, "report": 1, "export": 1},
	},
	"Survey Request": {
		"Customer":          {"read": 1, "create": 1, "report": 1},
		"Surveyor":          {"read": 1, "write": 1, "report": 1},
		"Admin Ops":         {"read": 1, "create": 1, "write": 1, "submit": 1, "cancel": 1, "report": 1},
		"Ops Supervisor":    {"read": 1, "write": 1, "report": 1},
	},
	"Surveyor Company": {
		"Surveyor":          {"read": 1, "report": 1},
		"Admin Ops":         {"read": 1, "create": 1, "write": 1, "report": 1},
		"Commercial":        {"read": 1, "report": 1},
		"Management":        {"read": 1, "report": 1},
	},
	"Customer Portal User": {
		"Admin Ops":         {"read": 1, "create": 1, "write": 1, "delete": 1, "report": 1},
		"Commercial":        {"read": 1, "report": 1},
		"IT Support":        {"read": 1, "create": 1, "write": 1, "report": 1},
	},
	"Shipping Line": {
		"Customer":          {"read": 1, "report": 1},
		"Admin Ops":         {"read": 1, "create": 1, "write": 1, "report": 1},
		"Commercial":        {"read": 1, "report": 1},
	},
	# ---- B4 additions (monthly billing) --------------------------------
	"OAK Monthly Invoice": {
		"Customer":          {"read": 1, "report": 1, "export": 1},
		"Commercial":        {"read": 1, "create": 1, "write": 1, "submit": 1, "cancel": 1, "report": 1, "export": 1},
		"Admin Ops":         {"read": 1, "create": 1, "write": 1, "submit": 1, "report": 1},
		"Management":        {"read": 1, "report": 1, "export": 1},
	},
	# ---- Survey Order (third-party survey charges billed to Paid To) ----
	# Same tier as OAK Monthly Invoice (customer billing doc, submittable):
	# Commercial/Admin Ops act; Customer (Paid To) & Management view-only.
	"Survey Order": {
		"Customer":          {"read": 1, "report": 1, "export": 1},
		"Commercial":        {"read": 1, "create": 1, "write": 1, "submit": 1, "cancel": 1, "report": 1, "export": 1},
		"Admin Ops":         {"read": 1, "create": 1, "write": 1, "submit": 1, "report": 1},
		"Management":        {"read": 1, "report": 1, "export": 1},
	},
}

# Depot PWA role gets the DocPerms the PWA exercises under the caller's session.
# EIR creation/submit runs WITHOUT ignore_permissions (operations/eir.py), so the
# role must carry Inspection create/submit or the PWA 403s. Gate lookup uses
# frappe.db/ignore_permissions, so the order/booking reads are courtesy. Injected
# into the matrix so setup_permissions() grants it like any other role.
_PWA_DOCTYPE_PERMS = {
	"Inspection":        {"read": 1, "create": 1, "write": 1, "submit": 1, "report": 1},
	# The PWA Cleaning menu edits + submits Cleaning Orders WITHOUT ignore_permissions
	# (operations/cleaning.py), so the PWA role must carry write + submit.
	"Cleaning Checklist Item": {"read": 1, "report": 1},
	"Cleaning Order":          {"read": 1, "write": 1, "submit": 1, "report": 1},
	# The PWA M&R menu edits Repair Orders WITHOUT ignore_permissions (operations/mr.py),
	# so the PWA role must carry read + write (+ create for manual M&R). The Material
	# Issue Stock Entry it raises on completion is created with ignore_permissions.
	"Repair Order":            {"read": 1, "write": 1, "create": 1, "report": 1},
	"Container":         {"read": 1, "report": 1},
	"Yard Zone":         {"read": 1, "report": 1},
	"Yard Placement Rule": {"read": 1, "report": 1},
	# The M&R item picker filters by the "Maintenance" Depot Service Menu under the
	# caller's session (operations/service_menu.py), so the PWA role must read it.
	"Depot Service Menu": {"read": 1, "report": 1},
	"Cargo":             {"read": 1, "report": 1},
	"Order Bongkar":     {"read": 1, "report": 1},
	"Order Muat":        {"read": 1, "report": 1},
	# EIR-Out shows the tank's Cleaning Certificate (no + validity) before load-out.
	"Cleaning Certificate": {"read": 1, "report": 1},
	"Container Booking": {"read": 1, "report": 1},
	"Booking Code":      {"read": 1, "report": 1},
}
for _pwa_dt, _pwa_perms in _PWA_DOCTYPE_PERMS.items():
	ROLE_DOCTYPE_PERMISSIONS.setdefault(_pwa_dt, {})[PWA_ROLE] = _pwa_perms


def after_install():
	"""Run after install hook for container_depot app"""
	ensure_roles_exist()
	setup_permissions()
	setup_custom_fields()
	setup_property_setters()
	ensure_selling_settings()
	ensure_payment_terms_templates()
	ensure_modes_of_payment()
	ensure_multi_currency_billing()
	setup_workspace()
	setup_document_notifications()
	sync_branding()


def after_migrate():
	"""Idempotent post-migrate hook: ensure roles + DocPerms stay in sync."""
	ensure_roles_exist()
	# setup_permissions() is idempotent (existence-check on Custom DocPerm) so
	# running it on every migrate just picks up new DocTypes as they're added.
	setup_permissions()
	# create_custom_fields is idempotent (upserts by dt+fieldname).
	setup_custom_fields()
	# Doctype-level UX tweaks on standard doctypes (Property Setters, idempotent):
	# Item links show the item name, Item Price 'New' uses the full form.
	setup_property_setters()
	# Container Inventory monitoring dashboard (Number Cards + Charts). Idempotent
	# upsert by name; safe to re-run every migrate.
	setup_inventory_dashboard()
	# Built-in ERPNext Notifications for key doc events (orders, contract, booking,
	# EIR). System Notification channel → Desk + PWA bell. Idempotent — skipped once
	# present. Recipients are editable per role in Desk → Notification.
	setup_document_notifications()
	# Keep the depot-pricing invariant: Bertschi Product Bundles must bill at the
	# bundle parent's flat Item Price, not a recomputed sum of component prices.
	ensure_selling_settings()
	# Cash-vs-Termin billing primitives (Payment Terms Templates + Modes of
	# Payment account mapping). Idempotent — created on fresh install AND kept in
	# sync for existing sites on every migrate. See set_customer_payment_terms
	# patch for wiring each customer's default from its Depot Contract mode.
	ensure_payment_terms_templates()
	ensure_modes_of_payment()
	ensure_multi_currency_billing()
	# Workspace Sidebar JSON isn't picked up by Frappe's standard module-sync,
	# so we re-import the file every migrate. Idempotent (force=True replaces
	# the existing rows in-place).
	sync_workspace_sidebar()
	# Push env-driven logo into site-wide settings so ALL apps pick it up.
	sync_branding()


def setup_document_notifications():
	"""Built-in Frappe Notifications for key document events. Channel = System
	Notification → shows in the in-app bell (Desk + the Depot OAK PWA bell) for the
	recipient role. Idempotent: skipped once a matching Notification exists.
	Best-effort — a quirk in the Notification schema never breaks a migrate.

	Recipient is a placeholder role (System Manager). Edit each Notification's
	``receiver_by_role`` in Desk → Notification to route per role.
	"""
	# (document_type, subject, event). Depot Contract is not submittable → "New".
	specs = [
		("Order Bongkar", "Bon Bongkar {{ doc.name }} diterbitkan", "Submit"),
		("Order Muat", "Bon Muat {{ doc.name }} diterbitkan", "Submit"),
		("Depot Contract", "Kontrak Depo {{ doc.name }} dibuat", "New"),
		("Container Booking", "Booking {{ doc.name }} dikonfirmasi", "Submit"),
		("Inspection", "EIR {{ doc.name }} disubmit", "Submit"),
	]
	for doctype, subject, event in specs:
		if frappe.db.exists(
			"Notification", {"document_type": doctype, "event": event, "is_standard": 0}
		):
			continue
		try:
			n = frappe.new_doc("Notification")
			n.subject = subject
			n.document_type = doctype
			n.event = event
			n.channel = "System Notification"
			n.enabled = 1
			n.is_standard = 0
			n.message = subject
			n.append("recipients", {"receiver_by_role": "System Manager"})
			n.insert(ignore_permissions=True)
		except Exception:
			frappe.log_error(frappe.get_traceback(), "setup_document_notifications")


# ---------------------------------------------------------------------------
# Branding: env-driven logo -> site-wide settings (berlaku untuk SEMUA app)
# ---------------------------------------------------------------------------
# Sumber nilai = container_depot.branding (site_config -> OS env -> default asset).
# Disinkronkan ke mekanisme native Frappe yang dihormati lintas app:
#   - Navbar Settings  -> logo navbar desk (mengalahkan hook app_logo_url)
#   - Website Settings -> brand/banner/favicon web & portal
#   - Letter Head      -> logo header semua print/PDF (ERPNext/HRMS/dll)

LETTER_HEAD_NAME = "OAK Brand"


def sync_branding():
	"""Idempotent: tulis logo env-driven ke Navbar/Website Settings + Letter Head.

	Tidak pernah menggagalkan migrate — tiap bagian dibungkus try/except.
	"""
	from container_depot import branding

	logo_main = branding.get_logo_main()  # emblem (navbar/web/favicon)
	logo_pdf = branding.get_logo_pdf()    # logo lengkap (PDF/letterhead)

	try:
		_set_single_if_exists("Navbar Settings", {"app_logo": logo_main})
	except Exception:
		frappe.log_error(frappe.get_traceback(), "container_depot branding: navbar")

	try:
		_set_single_if_exists("Website Settings", {
			"app_logo": logo_main,
			"banner_image": logo_main,
			"favicon": logo_main,
		})
	except Exception:
		frappe.log_error(frappe.get_traceback(), "container_depot branding: website")

	try:
		_sync_default_letter_head(logo_pdf)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "container_depot branding: letterhead")

	try:
		_sync_desktop_logo(logo_main)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "container_depot branding: desktop logo")

	frappe.db.commit()


def _set_single_if_exists(doctype: str, values: dict) -> None:
	"""Set field pada Single doctype hanya bila field-nya ada & nilainya berubah."""
	fieldnames = {df.fieldname for df in frappe.get_meta(doctype).fields}
	for key, val in values.items():
		if val and key in fieldnames and frappe.db.get_single_value(doctype, key) != val:
			frappe.db.set_single_value(doctype, key, val)


def _sync_desktop_logo(logo_main: str) -> None:
	"""Tampilkan logo OAK (bukan ikon generik) di header sidebar Desk untuk workspace
	Container Depot.

	Frappe me-render ``<img src=logo_url>`` di header sidebar bila Desktop Icon yang
	label-nya == judul workspace punya ``logo_url``; kalau tidak, jatuh ke ikon modul
	abu-abu generik. Di-set ``standard=1`` supaya semua user melihatnya. Idempotent
	(upsert) dan dijalankan di after_migrate (sesudah orphan-removal).
	"""
	name = frappe.db.exists("Desktop Icon", {"label": "Container Depot"})
	if name:
		frappe.db.set_value(
			"Desktop Icon",
			name,
			{"logo_url": logo_main, "standard": 1, "app": "container_depot"},
			update_modified=False,
		)
	else:
		frappe.get_doc(
			{
				"doctype": "Desktop Icon",
				"label": "Container Depot",
				"standard": 1,
				"app": "container_depot",
				"logo_url": logo_main,
			}
		).insert(ignore_permissions=True)


def _sync_default_letter_head(logo_pdf: str) -> None:
	"""Buat/segarkan Letter Head 'OAK Brand' dari env dan jadikan default.

	Default print Frappe/ERPNext memakai Letter Head, jadi ini membuat logo PDF
	berlaku ke print format SEMUA app sekaligus. Set BRAND_LETTERHEAD_DEFAULT=0
	untuk berhenti memaksanya jadi default (mis. kalau kamu kelola manual).
	"""
	if not logo_pdf:
		return
	content = (
		'<div style="text-align:center; padding:6px 0;">'
		f'<img src="{logo_pdf}" alt="OAK Depot" style="max-height:70px; object-fit:contain;">'
		"</div>"
	)
	set_default = os.getenv("BRAND_LETTERHEAD_DEFAULT", "1") != "0"

	if frappe.db.exists("Letter Head", LETTER_HEAD_NAME):
		doc = frappe.get_doc("Letter Head", LETTER_HEAD_NAME)
		doc.source = "HTML"
		doc.content = content
		doc.disabled = 0
		if set_default:
			doc.is_default = 1
		doc.save(ignore_permissions=True)
	else:
		frappe.get_doc({
			"doctype": "Letter Head",
			"letter_head_name": LETTER_HEAD_NAME,
			"source": "HTML",
			"content": content,
			"is_default": 1 if set_default else 0,
		}).insert(ignore_permissions=True)


# Custom fields this app adds to standard ERPNext doctypes. Keyed by target
# doctype; applied idempotently via Frappe's create_custom_fields helper.
CUSTOM_FIELDS = {
	"Customer": [
		{
			"fieldname": "oak_customer_type",
			"label": "OAK Customer Type",
			"fieldtype": "Select",
			# Portal capability: Tank Owner books storage/cleaning/M&R/release;
			# Transporter does gate lift on/off. "Both" covers dual-role clients.
			"options": "\nTank Owner\nTransporter\nBoth",
			"insert_after": "customer_group",
			"in_standard_filter": 1,
		}
	],
	# Depot-pricing fields (pricing spec §3.2). Repair services price as
	# manhour × Item Price manhour_rate + material_cost; packages are flagged so
	# they can be filtered apart from single services.
	"Item": [
		{
			"fieldname": "depot_pricing_section",
			"label": "Depot Pricing",
			"fieldtype": "Section Break",
			"insert_after": "stock_uom",
			"collapsible": 1,
		},
		{
			"fieldname": "is_depot_package",
			"label": "Is Depot Package",
			"fieldtype": "Check",
			"insert_after": "depot_pricing_section",
			"in_standard_filter": 1,
			"description": "Bundle parent sold at one flat price (e.g. a Bertschi package).",
		},
		{
			"fieldname": "service_unit",
			"label": "Service Unit",
			"fieldtype": "Data",
			"insert_after": "is_depot_package",
			"description": "Billing unit from the rate card (tank / per / day / hour).",
		},
		{
			"fieldname": "manhour",
			"label": "Manhour",
			"fieldtype": "Float",
			"insert_after": "service_unit",
			"description": "Standard labour hours for a repair service. Effective rate = manhour × Item Price manhour rate + material cost.",
		},
		{
			"fieldname": "material_cost",
			"label": "Material Cost",
			"fieldtype": "Currency",
			"insert_after": "manhour",
			"description": "Spare-part / material cost added on top of labour for a repair service.",
		},
	],
	"Item Price": [
		{
			"fieldname": "manhour_rate",
			"label": "Manhour Rate",
			"fieldtype": "Currency",
			"options": "currency",
			"insert_after": "price_list_rate",
			"allow_in_quick_entry": 1,
			"description": "Labour rate per hour for repair services priced as manhour × rate + material. Held per Item Price so each principal's rate card can carry its own rate (e.g. OAK 4.50, Bertschi 4.00).",
		}
	],
	"Price List": [
		{
			"fieldname": "customer",
			"label": "Customer",
			"fieldtype": "Link",
			"options": "Customer",
			"insert_after": "currency",
			"in_standard_filter": 1,
			# Optional: a per-principal rate card can be tied to its Customer
			# master; standard/shared price lists leave this blank.
			"description": "Optional — the Customer this rate card belongs to. Leave blank for shared/standard price lists.",
		}
	],
	# Stamp the depot Branch on receivables so invoices can be filtered / reported per
	# branch (Sales Invoice has no native branch field). Set from the Container Booking.
	"Sales Invoice": [
		{
			"fieldname": "branch",
			"label": "Branch",
			"fieldtype": "Link",
			"options": "Branch",
			"insert_after": "customer",
			"in_standard_filter": 1,
			"description": "Depot branch this invoice was raised for (carried from the Container Booking).",
		},
		{
			# Internal rollback manifest for consolidated ("generate") invoices — a JSON
			# list of the depot orders swept into this invoice. Drives roll-back of those
			# orders to un-invoiced when the invoice is discarded (on_trash) or cancelled,
			# and marks the invoice as generated so its line items are frozen (see
			# container_depot.consolidated_billing). Not user-editable.
			"fieldname": "depot_billed_sources",
			"label": "Depot Billed Sources",
			"fieldtype": "Long Text",
			"insert_after": "branch",
			"hidden": 1,
			"read_only": 1,
			"no_copy": 1,
			"print_hide": 1,
			"description": "Internal: depot orders swept into this consolidated invoice (rollback manifest).",
		},
	],
	# Back-link a Repair Order to the consolidated invoice it was billed into. Repair
	# Order has no native invoice link (billing state lives in billing_status); this lets
	# the Order Billing Status report show its live invoice status (Draft/Unpaid/Paid)
	# like the other order types, and lets rollback clear the link. Set on Generate
	# (consolidated_billing._mark_billed), cleared on rollback (_unmark_billed).
	"Repair Order": [
		{
			"fieldname": "sales_invoice",
			"label": "Sales Invoice",
			"fieldtype": "Link",
			"options": "Sales Invoice",
			"insert_after": "billing_status",
			"read_only": 1,
			"no_copy": 1,
			"description": "Consolidated invoice this repair was billed into (set on Generate, cleared on rollback).",
		}
	],
	# Optional multi-branch tag on the User — pick zero, one, or many depot Branches to
	# scope the data this user sees. Empty = all branches; one/many = only those.
	# Backed by the "Allowed Branch" child table so it renders as a multi-select.
	"User": [
		{
			"fieldname": "branch",
			"label": "Branch",
			"fieldtype": "Table MultiSelect",
			"options": "Allowed Branch",
			"insert_after": "user_image",
			"description": "Opsional. Kosongkan = akses semua branch. Pilih satu atau beberapa branch untuk membatasi data (mis. order) hanya ke branch tersebut.",
		}
	],
	# Tag a Warehouse with its depot Branch so the M&R parts picker can scope the
	# source-warehouse list by branch (blank = visible to all branches).
	"Warehouse": [
		{
			"fieldname": "branch",
			"label": "Branch",
			"fieldtype": "Link",
			"options": "Branch",
			"insert_after": "company",
			"in_standard_filter": 1,
			"description": "Depot branch this warehouse belongs to. Kosong = tampil untuk semua branch. Dipakai untuk memfilter gudang sumber part di M&R.",
		}
	],
}


def setup_custom_fields():
	"""Create/refresh app custom fields on standard doctypes (idempotent)."""
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	create_custom_fields(CUSTOM_FIELDS, ignore_validate=True)
	frappe.db.commit()


# Doctype-level property tweaks on standard (ERPNext) doctypes. One Property Setter
# per (doctype, property); applied on after_install + after_migrate.
#   (doctype, fieldname|None, property, value, property_type)
PROPERTY_SETTERS = [
	# Item Link fields show the item NAME (title field) instead of the bare code,
	# so pickers (incl. the Item Price item selector) are human-readable.
	("Item", None, "show_title_field_in_link", "1", "Check"),
	# Item Price "New" opens the full form, not the cramped quick-entry modal — the
	# modal has no `frm`, so manhour rate is hidden and the price-list→currency
	# fetch_from never fires. The full form shows manhour and live-fetches currency.
	("Item Price", None, "quick_entry", "0", "Check"),
	# Hide Sales Invoice fields the depot never uses, decluttering the invoice form.
	# Values are untouched (fields stay in the DB) — this is UI-only. Section break
	# ``time_sheet_list`` hides the whole timesheet section; ``timesheets`` hidden too
	# for good measure.
	("Sales Invoice", "is_pos", "hidden", "1", "Check"),           # Include Payment (POS)
	("Sales Invoice", "is_return", "hidden", "1", "Check"),        # Is Return (Credit Note)
	("Sales Invoice", "is_debit_note", "hidden", "1", "Check"),    # Is Rate Adjustment Entry (Debit Note)
	("Sales Invoice", "apply_tds", "hidden", "1", "Check"),        # Consider for Tax Withholding
	("Sales Invoice", "scan_barcode", "hidden", "1", "Check"),     # Scan Barcode
	("Sales Invoice", "update_stock", "hidden", "1", "Check"),     # Update Stock
	("Sales Invoice", "time_sheet_list", "hidden", "1", "Check"),  # Time Sheet List (section)
	("Sales Invoice", "timesheets", "hidden", "1", "Check"),       # Time Sheet List (table)
]


def _set_property(doctype, fieldname, prop, value, property_type):
	"""Idempotent Property Setter upsert (doctype-level when fieldname is None)."""
	# Key the existence check on field_name too — otherwise several field-level
	# setters that share a (doc_type, property) pair (e.g. many ``hidden`` fields on
	# Sales Invoice) collide and only the first is ever created.
	filters = {"doc_type": doctype, "property": prop}
	if fieldname:
		filters["field_name"] = fieldname
	existing = frappe.db.get_value("Property Setter", filters, "name")
	if existing:
		frappe.db.set_value("Property Setter", existing, "value", str(value))
		return
	frappe.make_property_setter(
		{
			"doctype": doctype,
			"doctype_or_field": "DocField" if fieldname else "DocType",
			"fieldname": fieldname,
			"property": prop,
			"value": value,
			"property_type": property_type,
		},
		ignore_validate=True,
	)


def setup_property_setters():
	"""Apply app Property Setters on standard doctypes (idempotent)."""
	for doctype, fieldname, prop, value, property_type in PROPERTY_SETTERS:
		_set_property(doctype, fieldname, prop, value, property_type)
	frappe.db.commit()


# ---------------------------------------------------------------------------
# Container Inventory dashboard — Number Cards + Dashboard Charts (native
# records, no custom source). Seeded idempotently so the "Container Inventory"
# workspace lights up on fresh install and stays in sync on every migrate.
# "In Depo" = every inventory_stage except Pre-Arrival / Departed.
# ---------------------------------------------------------------------------

_IN_DEPO_FILTER = [["inventory_stage", "not in", ["Pre-Arrival", "Departed"]]]

# Number Card autonames from ``label`` and Dashboard Chart from ``chart_name``,
# so those fields ARE the record name — keep them unique + readable; the
# Container Inventory workspace references them by exactly these strings.
INVENTORY_NUMBER_CARDS = [
	{"label": "Stock In Depo",
	 "document_type": "Container", "filters_json": _IN_DEPO_FILTER},
	{"label": "Dirty Tank",
	 "document_type": "Container", "filters_json": [["cleaning_status", "in", ["Pending", "In_Progress"]]]},
	{"label": "Clean Tank",
	 "document_type": "Container", "filters_json": [["cleaning_status", "=", "Completed"]]},
	{"label": "Tanks In Cleaning",
	 "document_type": "Container", "filters_json": [["inventory_stage", "=", "Cleaning"]]},
	{"label": "Tanks In Survey or Repair",
	 "document_type": "Container", "filters_json": [["inventory_stage", "in", ["Survey", "Repair (M&R)"]]]},
	{"label": "Tanks Ready for Release",
	 "document_type": "Container", "filters_json": [["inventory_stage", "=", "Ready"]]},
	{"label": "Tank In Today",
	 "document_type": "Gate Entry", "filters_json": [["gate_in_timestamp", "Timespan", "today"]]},
	{"label": "Tank Out Today",
	 "document_type": "Container Movement",
	 "filters_json": [["to_status", "=", "Gate_Out"], ["movement_timestamp", "Timespan", "today"]]},
]

INVENTORY_CHARTS = [
	{"chart_name": "Tanks by Stage",
	 "document_type": "Container", "chart_type": "Group By", "group_by_type": "Count",
	 "group_by_based_on": "inventory_stage", "type": "Bar", "filters_json": _IN_DEPO_FILTER},
	{"chart_name": "Tanks by Principal",
	 "document_type": "Container", "chart_type": "Group By", "group_by_type": "Count",
	 "group_by_based_on": "principal", "type": "Donut", "number_of_groups": 10, "filters_json": _IN_DEPO_FILTER},
	{"chart_name": "Tanks by Yard Zone",
	 "document_type": "Container", "chart_type": "Group By", "group_by_type": "Count",
	 "group_by_based_on": "yard_zone", "type": "Bar", "filters_json": _IN_DEPO_FILTER},
	{"chart_name": "Tank IN (Last Month)",
	 "document_type": "Gate Entry", "chart_type": "Count", "based_on": "gate_in_timestamp",
	 "timespan": "Last Month", "time_interval": "Daily", "type": "Line", "timeseries": 1},
	{"chart_name": "Tank OUT (Last Month)",
	 "document_type": "Container Movement", "chart_type": "Count", "based_on": "movement_timestamp",
	 "timespan": "Last Month", "time_interval": "Daily", "type": "Line", "timeseries": 1,
	 "filters_json": [["to_status", "=", "Gate_Out"]]},
	{"chart_name": "Activity by Type (Last Month)",
	 "document_type": "Container Activity", "chart_type": "Group By", "group_by_type": "Count",
	 "group_by_based_on": "activity_type", "type": "Bar",
	 "filters_json": [["activity_time", "Timespan", "last month"]]},
]


def _qualify_filters(filters, document_type):
	"""Return dashboard filters in the 4-element ``[doctype, field, op, value]``
	shape the Number Card / Dashboard Chart widgets require.

	The specs above are written compactly as ``[field, op, value]``; the widget
	reads element 0 as the doctype and element 1 as the fieldname, so a 3-element
	filter is mis-parsed and the desk throws ``Invalid filter: <op>``. Prepend the
	card/chart's own ``document_type`` so element 1 is the real field again.
	Already-qualified 4-element filters pass through untouched."""
	out = []
	for f in filters or []:
		f = list(f)
		out.append([document_type, *f] if len(f) == 3 else f)
	return out


def _ensure_dashboard_doc(doctype: str, name: str, values: dict) -> None:
	"""Upsert a Number Card / Dashboard Chart by its (autonamed) name — idempotent.

	``name`` must equal the value of the doctype's naming field (Number Card.label
	/ Dashboard Chart.chart_name), since both autoname from it."""
	import json

	payload = dict(values)
	if "filters_json" in payload:
		# The widgets need 4-element [doctype, field, op, value] filters; qualify the
		# compact 3-element specs so they aren't mis-read as [doctype, field, op].
		payload["filters_json"] = json.dumps(
			_qualify_filters(payload["filters_json"], payload.get("document_type"))
		)
	if frappe.db.exists(doctype, name):
		doc = frappe.get_doc(doctype, name)
		doc.update(payload)
		doc.save(ignore_permissions=True)
	else:
		doc = frappe.get_doc({"doctype": doctype, **payload})
		doc.insert(ignore_permissions=True)


def setup_inventory_dashboard():
	"""Seed the Container Inventory Number Cards + Dashboard Charts (idempotent).

	Skipped quietly if the dashboard doctypes or the inventory_stage column aren't
	present yet (e.g. very early in a fresh bootstrap)."""
	if not frappe.db.has_column("Container", "inventory_stage"):
		return
	for card in INVENTORY_NUMBER_CARDS:
		# Number Card autonames from label → that is the record name.
		_ensure_dashboard_doc("Number Card", card["label"], {
			"is_public": 1,
			"function": "Count",
			"type": "Document Type",
			**card,
		})
	for chart in INVENTORY_CHARTS:
		spec = dict(chart)
		spec.setdefault("filters_json", [])  # Dashboard Chart requires filters_json.
		# Dashboard Chart autonames from chart_name → that is the record name.
		_ensure_dashboard_doc("Dashboard Chart", chart["chart_name"], {
			"is_public": 1,
			"chart_type": "Group By",
			**spec,
		})
	frappe.db.commit()


def ensure_selling_settings():
	"""Pin Selling Settings so Product Bundle parents bill at their own flat price.

	With ``editable_bundle_item_rates`` ON, ERPNext recomputes a bundle's rate from
	the sum of its component Item Prices (see erpnext stock ``packed_item``). The
	Bertschi packages are sold at a single negotiated price held on the bundle
	parent's Item Price, so we keep this OFF. Idempotent: only writes when needed,
	and never breaks a migrate if Selling Settings is unavailable (frappe-only site).
	"""
	try:
		if not frappe.db.exists("DocType", "Selling Settings"):
			return
		if frappe.db.get_single_value("Selling Settings", "editable_bundle_item_rates"):
			frappe.db.set_single_value("Selling Settings", "editable_bundle_item_rates", 0)
			frappe.db.commit()
	except Exception:
		frappe.log_error(frappe.get_traceback(), "container_depot selling-settings sync failed")


# ---------------------------------------------------------------------------
# Cash-vs-Termin billing primitives (native ERPNext, minim custom)
# ---------------------------------------------------------------------------
# Two billing modes for MDN depot operations:
#   - Bayar langsung (Cash/Bank) -> Mode of Payment + Payment Entry.
#   - Bayar nanti (termin)       -> Payment Terms Template on the invoice.
# The DEFAULT lives on Customer.payment_terms (built-in field, flows into a new
# Sales Invoice's payment_terms_template) and is overridable per invoice. The
# statement side (Process Statement Of Accounts) is read-only and is NOT seeded
# here — it never creates accounting documents. See BILLING_MODE.md.

# Payment Terms Templates are GLOBAL (not company-scoped). Each maps to one
# Payment Term row at 100% invoice portion. Idempotent: created only if absent so
# an owner can re-tune the rows without a migrate clobbering them.
PAYMENT_TERMS = {
	"Immediate": {
		"due_date_based_on": "Day(s) after invoice date",
		"credit_days": 0,
		"description": "Bayar langsung — jatuh tempo = tanggal invoice.",
	},
	"Net 30": {
		"due_date_based_on": "Day(s) after invoice date",
		"credit_days": 30,
		"description": "Jatuh tempo 30 hari setelah tanggal invoice.",
	},
	"End of Following Month": {
		"due_date_based_on": "Month(s) after the end of the invoice month",
		"credit_months": 1,
		"description": "Jatuh tempo akhir bulan berikutnya (1 bulan setelah akhir bulan invoice).",
	},
}


def ensure_payment_terms_templates():
	"""Create Payment Term + Payment Terms Template masters for Cash-vs-Termin.

	Idempotent and defensive: never breaks a migrate on a site where the Accounts
	module / Payment Terms Template doctype is unavailable.
	"""
	try:
		if not frappe.db.exists("DocType", "Payment Terms Template"):
			return
		for name, spec in PAYMENT_TERMS.items():
			_ensure_payment_term(name, spec)
			_ensure_payment_terms_template(name, spec)
		frappe.db.commit()
	except Exception:
		frappe.log_error(frappe.get_traceback(), "container_depot payment-terms seed failed")


def _term_fields(spec: dict) -> dict:
	row = {
		"invoice_portion": 100,
		"due_date_based_on": spec["due_date_based_on"],
		"description": spec.get("description"),
		"credit_days": spec.get("credit_days", 0),
		"credit_months": spec.get("credit_months", 0),
	}
	return row


def _ensure_payment_term(name: str, spec: dict) -> None:
	if frappe.db.exists("Payment Term", name):
		return
	doc = {"doctype": "Payment Term", "payment_term_name": name}
	doc.update(_term_fields(spec))
	frappe.get_doc(doc).insert(ignore_permissions=True)


def _ensure_payment_terms_template(name: str, spec: dict) -> None:
	if frappe.db.exists("Payment Terms Template", name):
		return
	row = {"payment_term": name}
	row.update(_term_fields(spec))
	frappe.get_doc({
		"doctype": "Payment Terms Template",
		"template_name": name,
		"terms": [row],
	}).insert(ignore_permissions=True)


def ensure_modes_of_payment():
	"""Ensure Cash + Bank Transfer Modes of Payment exist and are mapped to a
	sensible default account for EVERY company (idempotent).

	Cash maps to each company's Cash account; Bank Transfer to a Bank account.
	Existing rows are never duplicated; only missing company mappings are added.
	"""
	try:
		if not frappe.db.exists("DocType", "Mode of Payment"):
			return
		companies = frappe.get_all("Company", pluck="name")
		if not companies:
			return
		_ensure_mode_of_payment("Cash", "Cash", companies, _cash_account)
		_ensure_mode_of_payment("Bank Transfer", "Bank", companies, _bank_account)
		frappe.db.commit()
	except Exception:
		frappe.log_error(frappe.get_traceback(), "container_depot mode-of-payment seed failed")


def _cash_account(company: str):
	acc = frappe.db.get_value("Company", company, "default_cash_account")
	if acc and frappe.db.get_value("Account", acc, "account_type") == "Cash":
		return acc
	return frappe.db.get_value(
		"Account", {"company": company, "account_type": "Cash", "is_group": 0}, "name"
	)


def _bank_account(company: str):
	acc = frappe.db.get_value("Company", company, "default_bank_account")
	if acc and frappe.db.get_value("Account", acc, "account_type") == "Bank":
		return acc
	return frappe.db.get_value(
		"Account", {"company": company, "account_type": "Bank", "is_group": 0}, "name"
	)


def _ensure_mode_of_payment(name: str, mop_type: str, companies: list, account_fn) -> None:
	if frappe.db.exists("Mode of Payment", name):
		doc = frappe.get_doc("Mode of Payment", name)
	else:
		doc = frappe.new_doc("Mode of Payment")
		doc.mode_of_payment = name
		doc.enabled = 1

	dirty = False
	if doc.type != mop_type:
		doc.type = mop_type
		dirty = True

	existing = {a.company for a in (doc.accounts or [])}
	for company in companies:
		if company in existing:
			continue
		account = account_fn(company)
		if not account:
			continue
		doc.append("accounts", {"company": company, "default_account": account})
		dirty = True

	if doc.is_new():
		doc.insert(ignore_permissions=True)
	elif dirty:
		doc.save(ignore_permissions=True)


def ensure_multi_currency_billing():
	"""Allow foreign-currency (USD) invoices against the single party receivable.

	The depot books in IDR (company base currency) but quotes some principals
	(OAK, Bertschi) in USD via their Price List. Turning this on lets one IDR
	receivable account hold those USD invoices — tracked per-party with an
	exchange rate — instead of forcing a separate USD receivable account. This is
	native ERPNext multi-currency; the company base currency is unchanged.

	Idempotent + defensive: only writes when the flag is off, never breaks a
	migrate. Per-customer billing currency is set by the set_customer_billing_currency
	patch (from each customer's Price List currency).
	"""
	try:
		if not frappe.db.exists("DocType", "Accounts Settings"):
			return
		field = "allow_multi_currency_invoices_against_single_party_account"
		if field not in {df.fieldname for df in frappe.get_meta("Accounts Settings").fields}:
			return
		if not frappe.db.get_single_value("Accounts Settings", field):
			frappe.db.set_single_value("Accounts Settings", field, 1)
			frappe.db.commit()
	except Exception:
		frappe.log_error(frappe.get_traceback(), "container_depot multi-currency setting failed")


def sync_workspace_sidebar():
	"""Force-resync the Container Depot Workspace Sidebar from JSON.

	Frappe's standard `bench migrate` syncs DocTypes, Workspaces, Reports, etc.
	but not ``workspace_sidebar/*.json``. We import it manually here so the
	left-rail navigation always matches the file on disk.
	"""
	import os
	from frappe.modules.import_file import import_file_by_path

	path = os.path.join(
		os.path.dirname(__file__),
		"workspace_sidebar",
		"container_depot.json",
	)
	if not os.path.exists(path):
		return
	try:
		import_file_by_path(path, force=True, reset_permissions=True)
		frappe.db.commit()
	except Exception:
		# Never break a migrate over a sidebar; just log and continue.
		frappe.log_error(frappe.get_traceback(), "container_depot sidebar sync failed")


def ensure_roles_exist():
	"""Create app-specific roles referenced by setup_permissions if missing."""
	for role_name in ROLES_TO_GRANT + PHASE6_ROLES:
		if not frappe.db.exists("Role", role_name):
			frappe.get_doc({
				"doctype": "Role",
				"role_name": role_name,
				"desk_access": 0 if role_name == "Customer" else 1,
			}).insert(ignore_permissions=True)
	# SST Service role: API-only (no desk access). Created here so the
	# Frappe token-auth path can reject anonymous traffic against the SST API.
	if not frappe.db.exists("Role", SST_SERVICE_ROLE):
		frappe.get_doc({
			"doctype": "Role",
			"role_name": SST_SERVICE_ROLE,
			"desk_access": 0,
		}).insert(ignore_permissions=True)
	# Depot PWA access role: website/PWA only (no desk access). The admin assigns it
	# to users; it gates the /depot page and carries the PWA's DocPerms.
	if not frappe.db.exists("Role", PWA_ROLE):
		frappe.get_doc({
			"doctype": "Role",
			"role_name": PWA_ROLE,
			"desk_access": 0,
		}).insert(ignore_permissions=True)
	frappe.db.commit()


def setup_permissions():
	"""Sync DocPerms.

	1. Legacy: every role in ROLES_TO_GRANT keeps unrestricted DocPerms on
	   every Operations doctype (back-compat for existing sites).
	2. Phase-6 matrix: ROLE_DOCTYPE_PERMISSIONS adds narrow per-role grants
	   on top, so the real role list is in effect for new doctypes.
	"""
	doctypes = [d.name for d in frappe.get_all("DocType", filters={"module": "Operations"})]
	for dt in doctypes:
		meta = frappe.get_meta(dt)
		for role_name in ROLES_TO_GRANT:
			if frappe.db.exists("Custom DocPerm", {"parent": dt, "role": role_name}):
				continue
			frappe.get_doc({
				"doctype": "Custom DocPerm",
				"parent": dt,
				"parenttype": "DocType",
				"parentfield": "permissions",
				"role": role_name,
				"permlevel": 0,
				"read": 1,
				"write": 1,
				"create": 1,
				"delete": 1,
				"submit": 1 if meta.is_submittable else 0,
				"cancel": 1 if meta.is_submittable else 0,
				"amend": 1 if meta.is_submittable else 0,
				"export": 1,
				"import": 1,
				"share": 1,
				"report": 1,
			}).insert(ignore_permissions=True)

	# Phase-6 narrow matrix.
	for dt, role_map in ROLE_DOCTYPE_PERMISSIONS.items():
		if not frappe.db.exists("DocType", dt):
			continue
		meta = frappe.get_meta(dt)
		for role, perms in role_map.items():
			if frappe.db.exists("Custom DocPerm", {"parent": dt, "role": role}):
				continue
			row = {
				"doctype": "Custom DocPerm",
				"parent": dt,
				"parenttype": "DocType",
				"parentfield": "permissions",
				"role": role,
				"permlevel": 0,
			}
			row.update(perms)
			# submit/cancel/amend only make sense on submittable doctypes.
			if not meta.is_submittable:
				row.pop("submit", None)
				row.pop("cancel", None)
				row.pop("amend", None)
			frappe.get_doc(row).insert(ignore_permissions=True)

	frappe.db.commit()


def ensure_customer_user_permission(user: str, customer: str) -> None:
	"""Create a User Permission row scoping a user to a single Customer.

	Idempotent. Used by the on-signup hook (and tests) so a Customer-role user
	can only see records linked to *their* Customer through standard Frappe
	permission filtering.
	"""
	if not user or not customer:
		return
	if frappe.db.exists(
		"User Permission",
		{"user": user, "allow": "Customer", "for_value": customer},
	):
		return
	frappe.get_doc({
		"doctype": "User Permission",
		"user": user,
		"allow": "Customer",
		"for_value": customer,
		"apply_to_all_doctypes": 1,
	}).insert(ignore_permissions=True)


def setup_workspace():
	"""Pin Container Depot workspace to the top of the sidebar."""
	if frappe.db.exists("Workspace", "Container Depot"):
		frappe.db.set_value("Workspace", "Container Depot", "sequence_id", 0)
		frappe.db.set_value("Workspace", "Container Depot", "parent_page", "")
		frappe.db.commit()
