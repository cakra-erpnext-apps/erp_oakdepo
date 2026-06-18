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
		"on_submit": "container_depot.operations.doctype.container_booking.container_booking.on_payment_entry_change",
		"on_cancel": "container_depot.operations.doctype.container_booking.container_booking.on_payment_entry_change",
	},
}

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
	{"from_route": "/api/v1/yard/update-location", "to_route": "container_depot.api.update_container_location"},
	{"from_route": "/api/v1/inspection/upload-evidence", "to_route": "container_depot.api.upload_inspection_evidence"},
	{"from_route": "/api/v1/webhook/message", "to_route": "container_depot.api.handle_webhook"},
	{"from_route": "/api/v1/agent/skills", "to_route": "container_depot.api.get_agent_skills"},
	{"from_route": "/api/v1/sst/issue-order", "to_route": "container_depot.api.sst_issue_order"},
	{"from_route": "/api/v1/sst/heartbeat", "to_route": "container_depot.api.sst_heartbeat"},
	{"from_route": "/api/v1/inspection/offline-batch", "to_route": "container_depot.api.upload_inspection_offline_batch"},
	# ESS PWA read endpoints (F1 — Tank Inventory & Live Status)
	{"from_route": "/api/v1/ess/inventory-summary", "to_route": "container_depot.ess.inventory.get_inventory_summary"},
	{"from_route": "/api/v1/ess/tank-list", "to_route": "container_depot.ess.inventory.get_tank_list"},
	{"from_route": "/api/v1/ess/tank-detail", "to_route": "container_depot.ess.inventory.get_tank_detail"},
	# ESS PWA EIR (Equipment Interchange Receipt) checklist endpoints
	{"from_route": "/api/v1/ess/eir-masters", "to_route": "container_depot.ess.inspections.eir_masters"},
	{"from_route": "/api/v1/ess/eir-prefill", "to_route": "container_depot.ess.inspections.eir_prefill"},
	{"from_route": "/api/v1/ess/eir-create", "to_route": "container_depot.ess.inspections.eir_create"},
	{"from_route": "/api/v1/ess/eir-open-draft", "to_route": "container_depot.ess.inspections.eir_open_draft"},
	{"from_route": "/api/v1/ess/eir-save-draft", "to_route": "container_depot.ess.inspections.eir_save_draft"},
	# ESS PWA Cleaning Order (ISO tank cleanliness) endpoints
	{"from_route": "/api/v1/ess/cleaning-masters", "to_route": "container_depot.ess.cleaning.cleaning_masters"},
	{"from_route": "/api/v1/ess/cleaning-orders", "to_route": "container_depot.ess.cleaning.cleaning_orders"},
	{"from_route": "/api/v1/ess/cleaning-order-detail", "to_route": "container_depot.ess.cleaning.cleaning_order_detail"},
	{"from_route": "/api/v1/ess/cleaning-start", "to_route": "container_depot.ess.cleaning.cleaning_start"},
	{"from_route": "/api/v1/ess/cleaning-order-save", "to_route": "container_depot.ess.cleaning.cleaning_order_save"},
	# ESS PWA M&R (Maintenance & Repair) endpoints — auto-created from EIRs with damage
	{"from_route": "/api/v1/ess/mr-orders", "to_route": "container_depot.ess.repairs.mr_orders"},
	{"from_route": "/api/v1/ess/mr-order-detail", "to_route": "container_depot.ess.repairs.mr_order_detail"},
	{"from_route": "/api/v1/ess/mr-warehouses", "to_route": "container_depot.ess.repairs.mr_warehouses"},
	{"from_route": "/api/v1/ess/mr-items", "to_route": "container_depot.ess.repairs.mr_items"},
	{"from_route": "/api/v1/ess/mr-start", "to_route": "container_depot.ess.repairs.mr_start"},
	{"from_route": "/api/v1/ess/mr-order-save", "to_route": "container_depot.ess.repairs.mr_order_save"},
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
	]
}

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/container_depot/css/container_depot.css"
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

# doctype js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
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
