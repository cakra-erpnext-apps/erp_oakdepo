app_name = "container_depot"
app_title = "Container Depot"
app_publisher = "Oak Depot Team"
app_description = "Container and ISO Tank Management System"
app_email = "info@oakdepot.com"
app_license = "MIT"

# Installation
# ------------

after_install = "container_depot.install.after_install"
after_migrate = "container_depot.install.after_migrate"

# Scheduled Jobs
# --------------

scheduler_events = {
	"hourly": [
		"container_depot.tasks.expire_booking_codes",
	],
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
]

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

# website
# update_website_context = "container_depot.www.index.website_context"

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
