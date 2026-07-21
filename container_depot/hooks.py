import os

app_name = "container_depot"
app_title = "Container Depot"
app_publisher = "Oak Depot Team"
app_description = "Container and ISO Tank Management System"
app_email = "info@oakdepot.com"
app_license = "MIT"

# Required apps
# -------------
# ERPNext is a hard dependency: the app imports erpnext (e.g. invoicing.py uses
# erpnext.controllers.accounts_controller) and builds on ERPNext selling masters
# (Item / Price List / Product Bundle / Sales Invoice). Declaring it here makes
# `bench install-app` fail fast on a frappe-only site instead of erroring later.
required_apps = ["erpnext"]

# Installation
# ------------

after_install = "container_depot.install.after_install"
after_migrate = "container_depot.install.after_migrate"

# Boot
# ----
# Trim the desk app-switcher so a user never sees apps they can't actually use
# (Frappe lists every installed app regardless of workspace access). See boot.py.
extend_bootinfo = ["container_depot.boot.prune_app_switcher"]

# Warm the domain-restricted caches before boot so the Workspace Sidebar never
# reads them as None (a Frappe core crash for users with no allowed workspaces).
before_request = ["container_depot.boot.warm_domain_restricted_caches"]

# Document Events
# ---------------

doc_events = {
	"Customer Portal User": {
		"after_insert": "container_depot.portal.sync_portal_user_permission",
		"on_update": "container_depot.portal.sync_portal_user_permission",
	},
	# Mirror a User's selected depot Branches into User Permissions so data is
	# scoped per branch (empty = all branches). See operations/user_branch.py.
	"User": {
		"on_update": "container_depot.operations.user_branch.sync_user_branch_permissions",
	},
	# Keep an Container Booking's payment_status in step with its Sales Invoice when
	# a payment is recorded / reversed. Scoped to bookings only.
	"Payment Entry": {
		"on_submit": [
			"container_depot.operations.doctype.container_booking.container_booking.on_payment_entry_change",
			"container_depot.operations.doctype.survey_order.survey_order.on_payment_entry_change",
		],
		"on_cancel": [
			"container_depot.operations.doctype.container_booking.container_booking.on_payment_entry_change",
			"container_depot.operations.doctype.survey_order.survey_order.on_payment_entry_change",
		],
	},
	# Keep a Container Booking pinned to a VALID Sales Invoice. EVERY handler below is a
	# no-op unless a Container Booking links the invoice (or its amended_from), so general
	# ERPNext invoicing is untouched:
	#   amend  -> repoint the booking to the new (amended) invoice
	#   submit -> resync the booking's payment_status from the invoice
	#   cancel -> mark the booking Unpaid so it can be regenerated
	"Sales Invoice": {
		# A generated (consolidated) invoice's line items are frozen — no manual add /
		# remove / edit. No-op on ordinary invoices (no billed-sources manifest).
		"validate": [
			"container_depot.consolidated_billing.protect_consolidated_items",
		],
		"after_insert": [
			"container_depot.operations.doctype.container_booking.container_booking.relink_amended_invoice",
			"container_depot.operations.doctype.survey_order.survey_order.relink_amended_invoice",
		],
		"on_submit": [
			"container_depot.operations.doctype.container_booking.container_booking.sync_booking_on_invoice_submit",
			"container_depot.operations.doctype.survey_order.survey_order.sync_survey_on_invoice_submit",
			# Tell the Cashier / Commercial there is a bill (and, unless it is already
			# settled, money to collect).
			"container_depot.operations.notify.notify_invoice_submitted",
		],
		"on_cancel": [
			"container_depot.operations.doctype.container_booking.container_booking.resync_booking_on_invoice_cancel",
			"container_depot.operations.doctype.survey_order.survey_order.sync_survey_on_invoice_cancel",
			# Roll a generated invoice's orders back to un-invoiced (no-op otherwise).
			"container_depot.consolidated_billing.rollback_billed_sources",
		],
		# Discarding a generated DRAFT invoice rolls its orders back to un-invoiced.
		# Runs before Frappe's link-integrity check, so it also unblocks the delete.
		"on_trash": [
			"container_depot.consolidated_billing.rollback_billed_sources",
		],
	},
}

# Voiding a document revokes the notifications it raised, so a cancelled booking /
# bon stops sitting in everyone's bell as work to do. Kept as a loop over
# ``notify.REVOCABLE_DOCTYPES`` so a new notified doctype is wired up in one place.
#
# APPENDED, never assigned: Sales Invoice already carries handlers for these events
# above, and overwriting them would silently unhook the booking/survey resync.
#
# Bookings and bons refuse deletion outright (their ``on_trash`` throws), so only the
# deletable ones need the trash hook — a deleted document's notification would
# otherwise link to nothing.
#
# Depot Contract and Repair Order are not submittable, so ``on_cancel`` never reaches
# them; their controllers revoke on the status move to Void / Cancelled instead.
from container_depot.operations.notify import REVOCABLE_DOCTYPES as _REVOCABLE_DOCTYPES

_REVOKE = "container_depot.operations.notify.revoke_on_cancel"


def _append_event(doctype, event, handler):
	events = doc_events.setdefault(doctype, {})
	existing = events.get(event) or []
	if isinstance(existing, str):
		existing = [existing]
	events[event] = existing + [handler]


for _dt in _REVOCABLE_DOCTYPES:
	_append_event(_dt, "on_cancel", _REVOKE)
for _dt in ("Inspection", "Cleaning Order", "Cleaning Certificate", "Survey Order", "Gate Entry"):
	_append_event(_dt, "on_trash", _REVOKE)
del _dt

# Scheduled Jobs
# --------------

scheduler_events = {
	"daily": [
		"container_depot.tasks.remind_periodic_test_due",
		"container_depot.tasks.notify_customers",
	],
	"cron": {
		"*/5 * * * *": [
			"container_depot.tasks.mark_stale_sst_heartbeats",
		],
		# 02:00 on the 1st of each month: bill the prior month.
		"0 2 1 * *": [
			"container_depot.tasks.generate_monthly_invoices",
		],
	},
}

# API Routes
# ----------

website_route_rules = [
	{"from_route": "/api/v1/gate/validate-qr", "to_route": "container_depot.api.validate_qr"},
	{"from_route": "/api/v1/gate/entry", "to_route": "container_depot.api.register_gate_entry"},
	{"from_route": "/api/v1/yard/pending-lifts", "to_route": "container_depot.api.get_pending_lifts"},
	{"from_route": "/api/v1/inspection/upload-evidence", "to_route": "container_depot.api.upload_inspection_evidence"},
	{"from_route": "/api/v1/webhook/message", "to_route": "container_depot.api.handle_webhook"},
	{"from_route": "/api/v1/agent/skills", "to_route": "container_depot.api.get_agent_skills"},
	{"from_route": "/api/v1/sst/issue-order", "to_route": "container_depot.api.sst_issue_order"},
	{"from_route": "/api/v1/sst/heartbeat", "to_route": "container_depot.api.sst_heartbeat"},
	{"from_route": "/api/v1/inspection/offline-batch", "to_route": "container_depot.api.upload_inspection_offline_batch"},
	# ESS PWA read endpoints (F1 — Tank Inventory & Live Status)
	{"from_route": "/api/v1/ess/inventory-summary", "to_route": "container_depot.ess.inventory.get_inventory_summary"},
	{"from_route": "/api/v1/ess/dashboard-summary", "to_route": "container_depot.ess.inventory.get_dashboard_summary"},
	{"from_route": "/api/v1/ess/tank-list", "to_route": "container_depot.ess.inventory.get_tank_list"},
	{"from_route": "/api/v1/ess/tank-detail", "to_route": "container_depot.ess.inventory.get_tank_detail"},
	# ESS PWA EIR (Equipment Interchange Receipt) checklist endpoints
	{"from_route": "/api/v1/ess/eir-masters", "to_route": "container_depot.ess.inspections.eir_masters"},
	{"from_route": "/api/v1/ess/eir-prefill", "to_route": "container_depot.ess.inspections.eir_prefill"},
	{"from_route": "/api/v1/ess/eir-create", "to_route": "container_depot.ess.inspections.eir_create"},
	{"from_route": "/api/v1/ess/eir-open-draft", "to_route": "container_depot.ess.inspections.eir_open_draft"},
	{"from_route": "/api/v1/ess/eir-save-draft", "to_route": "container_depot.ess.inspections.eir_save_draft"},
	# ESS PWA EIR-Out (Fase G — surveyor load-out inspection vs last EIR-In)
	{"from_route": "/api/v1/ess/eir-out-pending", "to_route": "container_depot.ess.inspections.eir_out_pending"},
	{"from_route": "/api/v1/ess/eir-out-open", "to_route": "container_depot.ess.inspections.eir_out_open"},
	# ESS PWA Cleaning Order (ISO tank cleanliness) endpoints
	{"from_route": "/api/v1/ess/cleaning-masters", "to_route": "container_depot.ess.cleaning.cleaning_masters"},
	{"from_route": "/api/v1/ess/cleaning-orders", "to_route": "container_depot.ess.cleaning.cleaning_orders"},
	{"from_route": "/api/v1/ess/cleaning-order-detail", "to_route": "container_depot.ess.cleaning.cleaning_order_detail"},
	{"from_route": "/api/v1/ess/cleaning-start", "to_route": "container_depot.ess.cleaning.cleaning_start"},
	{"from_route": "/api/v1/ess/cleaning-order-save", "to_route": "container_depot.ess.cleaning.cleaning_order_save"},
	# ESS PWA M&R (Maintenance & Repair) endpoints — auto-created from EIRs with damage
	{"from_route": "/api/v1/ess/mr-orders", "to_route": "container_depot.ess.repairs.mr_orders"},
	{"from_route": "/api/v1/ess/mr-execution", "to_route": "container_depot.ess.repairs.mr_execution"},
	{"from_route": "/api/v1/ess/mr-bypass-approval", "to_route": "container_depot.ess.repairs.mr_bypass_approval"},
	{"from_route": "/api/v1/ess/mr-order-detail", "to_route": "container_depot.ess.repairs.mr_order_detail"},
	{"from_route": "/api/v1/ess/mr-warehouses", "to_route": "container_depot.ess.repairs.mr_warehouses"},
	{"from_route": "/api/v1/ess/mr-items", "to_route": "container_depot.ess.repairs.mr_items"},
	{"from_route": "/api/v1/ess/mr-item-pricing", "to_route": "container_depot.ess.repairs.mr_item_pricing"},
	{"from_route": "/api/v1/ess/mr-submit-approval", "to_route": "container_depot.ess.repairs.mr_submit_approval"},
	{"from_route": "/api/v1/ess/mr-decision", "to_route": "container_depot.ess.repairs.mr_decision"},
	{"from_route": "/api/v1/ess/mr-start", "to_route": "container_depot.ess.repairs.mr_start"},
	{"from_route": "/api/v1/ess/mr-order-save", "to_route": "container_depot.ess.repairs.mr_order_save"},
	{"from_route": "/api/v1/ess/gate-out", "to_route": "container_depot.ess.gate.gate_out"},
	# SPA deep links: serve the /depot shell for any sub-route so a hard refresh on
	# e.g. /depot/eir doesn't 404 — the Vue router then renders the route client-side.
	{"from_route": "/depot/<path:app_path>", "to_route": "depot"},
]

# Branding / Logo (env-driven)
# ----------------------------
# Lihat container_depot/branding.py. Override via BRAND_LOGO_MAIN / BRAND_LOGO_PDF
# (env / docker-compose) atau brand_logo_main / brand_logo_pdf (site_config.json).

# Logo navbar desk (dibaca dari OS env saat worker start; default = asset ter-bundle)
app_logo_url = os.getenv("BRAND_LOGO_MAIN") or "/assets/container_depot/images/oak-emblem.png"

# Method yang bisa dipanggil di Jinja (print format & web template), mis. {{ get_logo_pdf() }}
jinja = {
	"methods": [
		"container_depot.branding.get_logo_main",
		"container_depot.branding.get_logo_pdf",
		"container_depot.print_utils.qr_data_uri",
	]
}

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# Small desk-form polish (e.g. aligning Section Break descriptions with their
# centered section head/body — a Frappe rendering quirk). See public/css.
app_include_css = "/assets/container_depot/css/container_depot.css"
# app_include_js = "/assets/container_depot/js/container_depot.js"

# include js, css files in header of web template
# web_include_css = "/assets/container_depot/css/container_depot.css"
# web_include_js = "/assets/container_depot/js/container_depot.js"

# include custom scss in every website theme (without file extension)
# website_scss = "container_depot/public/scss/website"

# include js, css files in header of web template
# web_include_css = "/assets/container_depot/css/container_depot.css"
# web_include_js = "/assets/container_depot/js/container_depot.js"

# website — set logo navbar web/portal dari env (lihat branding.py)
update_website_context = "container_depot.branding.update_website_context"

# Client script for standard ERPNext Sales Invoice — surfaces a visible
# "Batalkan & Kembalikan Order" button on generated (consolidated) invoices.
# Communication — "Buat Order" buttons that seed a booking/M&R/survey/cleaning draft
# from an incoming email (see operations/mail_to_order.py).
doctype_js = {
	"Sales Invoice": "public/js/sales_invoice.js",
	"Communication": "public/js/communication.js",
}
# Communication list — on-demand "Tarik Email" (pull) button, scoped to the user's accounts.
doctype_list_js = {"Communication": "public/js/communication_list.js"}
# doctype_tree = {"doctype" : "doctype_tree.js"}
# doctype_calendar = {"doctype" : "public/js/doctype_calendar.js"}

# fixtures
# ----------

fixtures = [
	{
		"doctype": "Custom Field",
		"filters": [
			["name", "in", []]
		]
	}
]

# Installation
# ------------

# before_install = "container_depot.install.before_install"
# after_install = "container_depot.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "container_depot.uninstall.before_uninstall"
# after_uninstall = "container_depot.uninstall.after_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_list

# Notifications
# -------------
# See frappe.utils.get_notification_list

# Standard Document Exceptions
# ----------------------------
# See frappe.exceptions

# License
# -------
# See frappe.license
