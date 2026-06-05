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
	"Isotank Booking": {
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
	"EIR Damage Code": {
		"Surveyor":          {"read": 1, "create": 1, "write": 1, "report": 1},
		"Admin Ops":         {"read": 1, "create": 1, "write": 1, "report": 1},
		"Ops Supervisor":    {"read": 1, "report": 1},
	},
	"EIR Repair Code": {
		"Surveyor":          {"read": 1, "create": 1, "write": 1, "report": 1},
		"Admin Ops":         {"read": 1, "create": 1, "write": 1, "report": 1},
		"Ops Supervisor":    {"read": 1, "report": 1},
	},
	"Periodic Test": {
		"Customer":          {"read": 1, "report": 1},
		"Surveyor":          {"read": 1, "create": 1, "write": 1, "submit": 1, "report": 1},
		"Admin Ops":         {"read": 1, "create": 1, "write": 1, "submit": 1, "cancel": 1, "report": 1},
		"Commercial":        {"read": 1, "report": 1, "export": 1},
		"Ops Supervisor":    {"read": 1, "write": 1, "report": 1},
		"Management":        {"read": 1, "report": 1, "export": 1},
	},
	"Isotank Leasing": {
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
	# ---- B7 additions (postpaid consolidated billing) ------------------
	"OAK Billing Run": {
		"Commercial":        {"read": 1, "create": 1, "write": 1, "submit": 1, "cancel": 1, "report": 1, "export": 1},
		"Cashier":           {"read": 1, "create": 1, "write": 1, "submit": 1, "report": 1},
		"Admin Ops":         {"read": 1, "create": 1, "write": 1, "submit": 1, "report": 1},
		"Management":        {"read": 1, "report": 1, "export": 1},
	},
}


def after_install():
	"""Run after install hook for container_depot app"""
	ensure_roles_exist()
	setup_permissions()
	setup_custom_fields()
	ensure_selling_settings()
	setup_workspace()
	sync_branding()


def after_migrate():
	"""Idempotent post-migrate hook: ensure roles + DocPerms stay in sync."""
	ensure_roles_exist()
	# setup_permissions() is idempotent (existence-check on Custom DocPerm) so
	# running it on every migrate just picks up new DocTypes as they're added.
	setup_permissions()
	# create_custom_fields is idempotent (upserts by dt+fieldname).
	setup_custom_fields()
	# Keep the depot-pricing invariant: Bertschi Product Bundles must bill at the
	# bundle parent's flat Item Price, not a recomputed sum of component prices.
	ensure_selling_settings()
	# Workspace Sidebar JSON isn't picked up by Frappe's standard module-sync,
	# so we re-import the file every migrate. Idempotent (force=True replaces
	# the existing rows in-place).
	sync_workspace_sidebar()
	# Push env-driven logo into site-wide settings so ALL apps pick it up.
	sync_branding()


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

	frappe.db.commit()


def _set_single_if_exists(doctype: str, values: dict) -> None:
	"""Set field pada Single doctype hanya bila field-nya ada & nilainya berubah."""
	fieldnames = {df.fieldname for df in frappe.get_meta(doctype).fields}
	for key, val in values.items():
		if val and key in fieldnames and frappe.db.get_single_value(doctype, key) != val:
			frappe.db.set_single_value(doctype, key, val)


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
	# manhour × Price List manhour_rate + material_cost; packages are flagged so
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
			"description": "Standard labour hours for a repair service. Effective rate = manhour × Price List manhour rate + material cost.",
		},
		{
			"fieldname": "material_cost",
			"label": "Material Cost",
			"fieldtype": "Currency",
			"insert_after": "manhour",
			"description": "Spare-part / material cost added on top of labour for a repair service.",
		},
	],
	"Price List": [
		{
			"fieldname": "manhour_rate",
			"label": "Manhour Rate",
			"fieldtype": "Currency",
			"options": "currency",
			"insert_after": "currency",
			"description": "Labour rate per hour for repair services priced as manhour × rate + material (e.g. OAK 4.50, Bertschi 4.00).",
		}
	],
}


def setup_custom_fields():
	"""Create/refresh app custom fields on standard doctypes (idempotent)."""
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	create_custom_fields(CUSTOM_FIELDS, ignore_validate=True)
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
