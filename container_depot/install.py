import os

import frappe

from container_depot.container_depot.container_status import (
	DONE_CLEANING,
	DONE_REPAIR,
)
from container_depot.container_depot.doctype.cleaning_order.cleaning_order import (
	SPECIAL_WASH_TYPES,
)
from container_depot.state_machine import IN_DEPO_STAGES

# Roles that get a blanket DocPerm on EVERY Container Depot doctype, including ones added
# after this line was written. The per-role matrix lives further down (FIELD_ROLE_MATRIX
# / OFFICE_ROLE_MATRIX); this is only the catch-all beneath it.
#
# This list must never be empty: most Container Depot doctypes ship with an empty
# "permissions" array in their JSON, so a new doctype's ONLY grant is the one here until
# somebody adds it to the matrix.
ROLES_TO_GRANT = ["System Manager"]


def after_install():
	"""Run after install hook for container_depot app"""
	# Custom fields FIRST: the role seeder inside setup_permissions() writes
	# Role.is_depot_field_role, which does not exist as a column until this runs.
	setup_custom_fields()
	setup_permissions()
	# One Role Profile per app role, so assigning a user is one pick instead of three.
	# Runs after setup_permissions() because it seeds the Roles the profiles point at.
	setup_role_profiles()
	setup_property_setters()
	ensure_selling_settings()
	ensure_payment_terms_templates()
	ensure_modes_of_payment()
	ensure_multi_currency_billing()
	# PPN template. An ensure_* rather than the old one-time patch, which ran before the
	# setup wizard existed on a fresh site and left every invoice untaxed. See the docstring.
	ensure_ppn_template()
	# Store the finance master switch's default (on) the first time only, so a site that
	# has turned invoicing off is never switched back on by a later migrate.
	from container_depot import finance
	finance.ensure_defaults()
	setup_workspace()
	setup_notification_rules()
	sync_desktop_icons()
	sync_branding()


def after_migrate():
	"""Idempotent post-migrate hook: keep DocPerms in sync as doctypes are added."""
	# create_custom_fields is idempotent (upserts by dt+fieldname). It runs FIRST because
	# the role seeder inside setup_permissions() writes Role.is_depot_field_role, and that
	# column only exists once this has run.
	setup_custom_fields()
	# setup_permissions() is idempotent (existence-check on Custom DocPerm) so
	# running it on every migrate just picks up new DocTypes as they're added.
	setup_permissions()
	# Role Profiles: one per app role (role + its COMPANION_ROLES). Add-only, so a profile
	# an admin extended keeps the extra roles; only missing ones are written. Also retires
	# the six stock ERPNext/HRMS bundles, skipping any a user still holds.
	setup_role_profiles()
	# Doctype-level UX tweaks on standard doctypes (Property Setters, idempotent):
	# Item links show the item name, Item Price 'New' uses the full form, and a
	# Customer's Default Price List is read-only (the Depot Contract owns it).
	setup_property_setters()
	# Container Inventory monitoring dashboard (Number Cards + Charts). Idempotent
	# upsert by name; safe to re-run every migrate.
	setup_inventory_dashboard()
	# Notification routing table — one Depot Notification Rule per depot event, plus the
	# Depot Notification Settings single. Add-only: an existing event_key is never
	# rewritten, so admin routing tweaks survive every migrate.
	setup_notification_rules()
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
	# PPN template. An ensure_* rather than the old one-time patch, which ran before the
	# setup wizard existed on a fresh site and left every invoice untaxed. See the docstring.
	ensure_ppn_template()
	# Store the finance master switch's default (on) the first time only, so a site that
	# has turned invoicing off is never switched back on by a later migrate.
	from container_depot import finance
	finance.ensure_defaults()
	# Workspace Sidebar JSON isn't picked up by Frappe's standard module-sync,
	# so we re-import the file every migrate. Idempotent (force=True replaces
	# the existing rows in-place).
	sync_workspace_sidebar()
	# Close the /desk home-screen holes where an app icon ignores Allow Modules.
	sync_desktop_icons()
	# Keep the Desk "Depot PWA" shortcut visible only to roles flagged as depot field
	# roles. Runs after the sidebar re-import, which is what re-creates the entry.
	setup_pwa_page_roles()
	# Gameplan and Telephony ship their roles as fixtures, and sync_fixtures() runs after
	# the patch queue — so patch v0_54 parks them and the same migrate hands them straight
	# back. after_migrate is the only hook that lands after fixtures. See PARKED_ROLES.
	reassert_parked_fixture_roles()
	# Point existing yard accounts at the app their Role Profile names. New ones are stamped
	# on save by the User on_update hook; this catches everyone assigned a profile before that
	# hook existed. Runs AFTER setup_role_profiles, which is what seeds the profile's
	# home_page. Only fills a blank default_app — see desk_landing.py.
	from container_depot.desk_landing import backfill_landing_app
	backfill_landing_app()
	# Push env-driven logo into site-wide settings so ALL apps pick it up.
	sync_branding()


def setup_document_notifications():
	"""No-op since 2026-08-06. Kept so ``after_install`` / ``after_migrate`` keep working.

	This used to seed five built-in Frappe Notifications (Order Bongkar, Order Muat,
	Depot Contract, Container Booking, Inspection). Every one of them duplicated an event
	``container_depot.notify`` already raises, so submitting one Order Muat produced THREE bell
	rows for the same thing — the notify event, the built-in rule, and the EIR-Out follow
	up. Three rows for one fact trains people to swipe the bell away without reading it.

	Routing now lives in ``Depot Notification Rule`` (see ``setup_notification_rules``),
	which is editable per event without a deploy and cannot double-fire. The five stale
	Notifications are removed from existing sites by
	``patches.v0_51.drop_duplicate_notifications``.

	Admins may still create their own ad-hoc Notification records in Desk; nothing here
	touches those.
	"""
	return


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
	# Party roles — independent checkboxes, NOT one exclusive type. A single customer
	# routinely wears more than one hat (an EMKL that also owns tanks, an agent that also
	# trucks), which the old ``oak_customer_type`` Select could only express with a "Both"
	# value that never scaled past two roles. Retired in patch v0_49.
	"Customer": [
		{
			"fieldname": "oak_roles_section",
			"label": "OAK Party Roles",
			"fieldtype": "Section Break",
			"insert_after": "customer_group",
			"collapsible": 0,
		},
		{
			"fieldname": "is_tank_owner",
			"label": "Tank Owner (Principal)",
			"fieldtype": "Check",
			"insert_after": "oak_roles_section",
			"in_standard_filter": 1,
			"description": "Owns the ISO tanks — billed periodically (storage / cleaning / repair / LOLO / steam wash).",
		},
		{
			"fieldname": "is_transporter",
			"label": "Transporter (EMKL)",
			"fieldtype": "Check",
			"insert_after": "is_tank_owner",
			"in_standard_filter": 1,
			"description": "Physically lifts the tanks on / off — billed per gate in / out.",
		},
		{
			"fieldname": "is_agent",
			"label": "Agent",
			"fieldtype": "Check",
			"insert_after": "is_transporter",
			"in_standard_filter": 1,
			"description": "Supplies reference numbers (PO / STC PO / WO) and survey / pickup schedules. Not a billed party.",
		},
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
		# --- Tagihan Depot (consolidated billing) -----------------------------------
		# No filters live here any more. The operator presses Ambil Tagihan and gets EVERY
		# unbilled order the customer has, then ticks the ones to bill in the dialog — the
		# section checkboxes and date window they replaced were a second place to say the
		# same thing, and the form was drowning in them.
		{
			"fieldname": "depot_bill_group",
			"label": "Nomor Tagihan",
			"fieldtype": "Data",
			"insert_after": "branch",
			"read_only": 1,
			"no_copy": 1,
			# ERPNext invoices are single-currency, so a run that picks up both IDR and USD
			# charges becomes two documents. This ties them together: the print format renders
			# every member of a group as ONE pdf, a page per currency, under this number.
			"description": "Invoice lain dengan nomor ini adalah bagian dari tagihan yang sama (mata uang berbeda).",
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
			"insert_after": "depot_bill_group",
			"hidden": 1,
			"read_only": 1,
			"no_copy": 1,
			"print_hide": 1,
			"description": "Internal: depot orders swept into this consolidated invoice (rollback manifest).",
		},
		# --- Labour (manhour) -------------------------------------------------------
		# Every item line carries the manhour its contract books for it (see the Sales
		# Invoice Item field below). The hours are NOT priced into the line — they are
		# totalled here and charged once, so the invoice reads:
		#
		#     Total Price + (Total Jam × Tarif per Jam) -> tax -> Grand Total
		#
		# These live in the standard Totals block, right under Total / Net Total, so labour
		# is read side by side with the price it accompanies instead of in a section of its
		# own that has to be hunted for.
		{
			"fieldname": "total_manhour",
			"label": "Total Manhour (jam)",
			"fieldtype": "Float",
			"precision": "2",
			"insert_after": "net_total",
			"read_only": 1,
			"description": "Jumlah JAM semua item (tidak dikali qty). Di luar Total.",
		},
		{
			"fieldname": "manhour_hour",
			"label": "Tarif per Jam",
			"fieldtype": "Currency",
			"options": "currency",
			# NO default: the tariff is the customer's own (seeded from their rate card by
			# invoicing.apply_manhour_charge). A hardcoded default would quietly bill every
			# customer the same hourly rate — and, because the seed only fills a BLANK field,
			# would stop the real rate from ever landing.
			"default": "",
			"insert_after": "total_manhour",
			"description": "Tarif labour per jam, dari rate card pelanggan. Bisa diubah per invoice.",
		},
		{
			"fieldname": "manhour_amount",
			"label": "Biaya Manhour",
			"fieldtype": "Currency",
			"options": "currency",
			"insert_after": "manhour_hour",
			"read_only": 1,
			"bold": 1,
			"description": "Total Manhour × Tarif per Jam — masuk ke Grand Total.",
		},
	],
	# The manhour the contract books for this service. Shown in the items grid beside the
	# qty and summed into the invoice's Total Manhour; never folded into the line's amount,
	# and never scaled by qty — unlike the rate, it is the labour the line books as a whole.
	"Sales Invoice Item": [
		{
			"fieldname": "manhour",
			"label": "Manhour",
			"fieldtype": "Float",
			"precision": "2",
			"insert_after": "qty",
			"in_list_view": 1,
			"columns": 1,
			"description": "Manhour dari Price List kontrak — tidak dikali qty dan tidak menambah harga baris ini. Ditotal di header lalu dikali Hour.",
		}
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
			# Right below Role Profiles, so it also lands there in the New User quick-entry
			# popup (that dialog lists fields in docfield order).
			"insert_after": "role_profiles",
			"allow_in_quick_entry": 1,
			"description": "Opsional. Kosongkan = akses semua branch. Pilih satu atau beberapa branch untuk membatasi data (mis. order) hanya ke branch tersebut.",
		},
		{
			# The value actually used. The Role Profile field above is the default it is seeded
			# FROM — one is the template, the other is the setting, and keeping them apart is what
			# lets one person be moved without redefining the job (or a job be redefined without
			# chasing every account).
			"fieldname": "home_page",
			"label": "Home Page",
			"fieldtype": "Data",
			"insert_after": "default_app",
			"description": (
				"Halaman awal setelah login, mis. <code>/depot</code>. Kosong = ikut bawaan Role "
				"Profile. Diisi sekali saat user disimpan, lalu tidak pernah ditimpa. "
				"<b>Catatan:</b> path yang lebih dalam (mis. <code>/depot/monitor</code>) dipakai "
				"saat user membuka Desk, tapi login tetap mendarat di akar app (<code>/depot</code>) "
				"— batas dari Frappe, bukan setelan ini."
			),
		},
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
	# Which depot event produced this notification. Stamped by ``notify()`` and read by
	# ``ess/notification_routes.py`` to decide where a tap on the bell goes.
	#
	# It has to be stored, and the doctype is not a substitute: `Order Muat` is the subject
	# of several events belonging to different screens (bon generated → Gate, survey
	# requested → Survey Posisi, tank held after its EIR-Out → EIR). Routing on the doctype
	# alone would send most of them to the wrong menu.
	#
	# Hidden and read-only: it is machinery, not something an admin sets.
	"Notification Log": [
		{
			"fieldname": "depot_event",
			"label": "Depot Event",
			"fieldtype": "Data",
			"insert_after": "document_name",
			"hidden": 1,
			"read_only": 1,
			"no_copy": 1,
			"description": "Event key from container_depot notify() — drives notification click-through.",
		}
	],
	# Marks a Role as a depot FIELD role — the ones whose users work in the yard through
	# the /depot PWA. Deliberately a checkbox on Role rather than a Python constant: a
	# list in code means every new field role needs a deploy, whereas the whole point of
	# the redesign is that adding a role is an admin action. What the role may actually
	# SEE is never encoded here — that comes from its DocPerms (ess.context._MENU).
	"Role": [
		{
			"fieldname": "is_depot_field_role",
			"label": "Depot Field Role (PWA)",
			"fieldtype": "Check",
			"insert_after": "desk_access",
			"in_standard_filter": 1,
			"description": (
				"Centang untuk role tim lapangan. Role bercentang boleh membuka /depot; "
				"isi menunya ditentukan DocPerm lewat Permission Manager."
			),
		}
	],
	# Where a job lands after logging in. It sits on the PROFILE, not on the Role, so a Role
	# stays a permission object and nothing else.
	#
	# Frappe's own `Role.home_page` is the field this replaces, and it is a trap:
	# `website/utils.py::get_home_page` walks EVERY role a user holds and takes the first
	# home page it finds, so setting it on one field role also redirects Administrator (who
	# holds every role) and any supervisor who happens to hold that role too. A user has one
	# job and one profile, so the profile is the honest place for it.
	"Role Profile": [
		{
			"fieldname": "home_page",
			"label": "Home Page (default)",
			"fieldtype": "Data",
			"insert_after": "role_profile",
			"description": (
				"Halaman awal <b>bawaan</b> untuk pemegang profil ini, mis. <code>/depot</code>. "
				"Disalin ke User saat kolom Home Page user masih kosong; nilai di User yang dipakai. "
				"Kosongkan untuk memakai Desk."
			),
		}
	],
}


def setup_custom_fields():
	"""Create/refresh app custom fields on standard doctypes (idempotent)."""
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	create_custom_fields(CUSTOM_FIELDS, ignore_validate=True)
	_drop_obsolete_custom_fields()
	frappe.db.commit()


# Custom fields this app used to create and no longer defines. ``create_custom_fields`` only
# ever upserts, so a field dropped from CUSTOM_FIELDS lingers on every existing site — still
# rendering on the form — until it is deleted explicitly.
OBSOLETE_CUSTOM_FIELDS = [
	# The Tagihan Depot filters (2026-08-11). Billing now shows every unbilled order and
	# lets the operator tick what to bill, so the section checkboxes and the date window
	# were a second, redundant way to say the same thing.
	("Sales Invoice", "depot_bill_section"),
	("Sales Invoice", "depot_bill_col"),
	("Sales Invoice", "depot_bill_from_date"),
	("Sales Invoice", "depot_bill_to_date"),
	("Sales Invoice", "depot_bill_booking"),
	("Sales Invoice", "depot_bill_survey"),
	("Sales Invoice", "depot_bill_cleaning"),
	("Sales Invoice", "depot_bill_mr"),
	("Sales Invoice", "depot_bill_periodic"),
	("Sales Invoice", "depot_bill_storage"),
]


def _drop_obsolete_custom_fields():
	for dt, fieldname in OBSOLETE_CUSTOM_FIELDS:
		name = frappe.db.get_value("Custom Field", {"dt": dt, "fieldname": fieldname}, "name")
		if name:
			frappe.delete_doc("Custom Field", name, force=True, ignore_permissions=True)


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
	# A customer's rate card is the OUTPUT of their Depot Contract: going Active publishes
	# a Price List named after the contract and mirrors it here
	# (DepotContract._publish_price_list). Typing a different list on the Customer form
	# silently re-rates every future booking, bon and invoice for that party while the
	# contract everyone reads still says otherwise — so the field is read-only, and the
	# description says where to change it instead. The server refuses it too
	# (depot_contract.guard_manual_price_list); this is the half that stops the mistake
	# being made rather than reported.
	("Customer", "default_price_list", "read_only", "1", "Check"),
	("Customer", "default_price_list", "description",
	 "Diatur otomatis dari Depot Contract yang Active. Untuk mengubahnya, amend contract "
	 "customer ini — bukan dari sini.", "Small Text"),
	# The booking print is a customer-facing document, so Print must open the OAK format
	# rather than Frappe's Standard field-dump. Nothing else selects it: /desk/print/...
	# falls back to the doctype default. The driver's copy is a separate pick from the
	# dropdown ("OAK Booking Voucher"), one page per container.
	("Container Booking", None, "default_print_format", "OAK Booking Confirmation", "Data"),
] + [
	# Declutter the Sales Invoice form. UI-only: the fields stay in the DB and every
	# controller still reads them — nothing is deleted, only hidden.
	#
	# Deliberately NOT hidden, unlike erp_cakra's much longer list: total / net_total /
	# grand_total / taxes / taxes_and_charges. erp_cakra can hide the native totals because
	# it replaced them with its own Amounts fields (Discount / PPh / Tax / Materai /
	# Adjustment). This app has no replacement, so hiding them would leave an invoice with
	# no visible total and no way to see or change its tax.
	("Sales Invoice", fn, "hidden", "1", "Check")
	for fn in (
		# --- header noise -------------------------------------------------------
		"title",              # derived from the customer; just repeats it
		"project",
		"company_tax_id",
		"customer_name",      # the Customer link already shows the name
		# --- POS / credit-note machinery the depot never uses --------------------
		"is_pos", "pos_profile", "is_consolidated", "is_created_using_pos",
		"pos_closing_entry", "is_return", "return_against", "is_debit_note",
		"update_outstanding_for_self", "update_billed_amount_in_sales_order",
		"update_billed_amount_in_delivery_note", "has_subcontracted", "amended_from",
		# --- price list: the rate card is decided by the contract, not here ------
		"selling_price_list", "price_list_currency", "plc_conversion_rate",
		"ignore_pricing_rule", "pricing_rule_details", "pricing_rules",
		# --- items area ----------------------------------------------------------
		"scan_barcode", "update_stock", "last_scanned_warehouse",
		"set_warehouse", "set_target_warehouse",
		"packed_items", "product_bundle_help",
		"total_qty", "total_net_weight",
		"time_sheet_list", "timesheets", "total_billing_hours", "total_billing_amount",
		# --- tax clutter (§ "rapikan tampilan pajak") ----------------------------
		# The tax TABLE and its template stay; what goes is everything around them:
		# withholding, shipping/incoterm, the native discount block, and the verbose
		# tax-breakdown HTML that restates the table underneath it.
		"tax_category", "shipping_rule", "incoterm", "named_place",
		"apply_tds", "tax_withholding_group", "ignore_tax_withholding_threshold",
		"override_tax_withholding_entries", "tax_withholding_entries",
		"other_charges_calculation",
		"apply_discount_on", "additional_discount_percentage", "discount_amount",
		"base_discount_amount", "is_cash_or_non_trade_discount", "coupon_code",
		# --- base-currency mirrors: every one restates a figure already on screen -
		"base_total", "base_net_total", "base_total_taxes_and_charges",
		"base_grand_total", "base_in_words", "base_rounding_adjustment",
		"base_rounded_total",
	)
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
#
# Two halves, and the split matters:
#   * SNAPSHOT  — counted on Container / Gate Entry / Container Movement. Where the
#     tanks are right now.
#   * ORDER WATCH — counted on the order doctypes themselves. Container.status is
#     presence-based (Booked / In_Depot / Available / Gate_Out) and carries NO work
#     detail any more, so "how much work is open" can only be read off the orders.
#     The old stage-based cards (inventory_stage = Cleaning / Survey / Repair (M&R))
#     silently counted zero from the day those stages were removed — v0_59 deletes
#     them; the ``* Aktif`` cards below are their replacement.
#     ``Dirty Tank`` / ``Clean Tank`` went the same way in v0_62: they counted
#     Container.cleaning_status, which nothing ever reset, so a tank cleaned last cycle
#     stayed "Clean" long after it had gated out — and the card did not even filter to
#     tanks still in the depo. ``Cleaning Order Aktif`` counts the work itself.
# ---------------------------------------------------------------------------

# "In Depo" = physically present. Stated positively (IN_DEPO_STAGES) rather than as
# "not Pre-Arrival/Departed", so a container with a blank stage (never saved through
# the controller) is not silently counted as stock.
_IN_DEPO_FILTER = [["inventory_stage", "in", IN_DEPO_STAGES]]

# "Open" is defined by listing the CLOSED statuses, not the open ones: a status added to
# the Select later then counts as outstanding work by default. The other way round it
# would drop out of the dashboard silently, which is how work goes missing. The terminal
# sets come from container_status — the same ones that decide whether a tank is Available
# — so a card can never disagree with the tank's own readiness.

# Number Card autonames from ``label`` and Dashboard Chart from ``chart_name``,
# so those fields ARE the record name — keep them unique + readable; the
# Container Inventory workspace references them by exactly these strings.
INVENTORY_NUMBER_CARDS = [
	{"label": "Stock In Depo",
	 "document_type": "Container", "filters_json": _IN_DEPO_FILTER},
	{"label": "Tanks Ready for Release",
	 "document_type": "Container", "filters_json": [["inventory_stage", "=", "Ready"]]},
	{"label": "Tank In Today",
	 "document_type": "Gate Entry", "filters_json": [["gate_in_timestamp", "Timespan", "today"]]},
	{"label": "Tank Out Today",
	 "document_type": "Container Movement",
	 "filters_json": [["to_status", "=", "Gate_Out"], ["movement_timestamp", "Timespan", "today"]]},
]

# Order watch — one card per order doctype, each counting only what is still open, so
# the dashboard answers "what is outstanding" without opening nine list views.
# Submittable doctypes get an explicit ``docstatus`` filter where a cancelled document
# keeps its last status (Order Bongkar / Order Muat have no "Cancelled" option at all).
ORDER_NUMBER_CARDS = [
	{"label": "EIR Menunggu Review",
	 "document_type": "Inspection", "filters_json": [["status", "=", "Pending Review"]]},
	{"label": "Cleaning Order Aktif",
	 "document_type": "Cleaning Order",
	 "filters_json": [["status", "not in", list(DONE_CLEANING)], ["docstatus", "<", 2]]},
	{"label": "M&R Aktif",
	 "document_type": "Repair Order", "filters_json": [["status", "not in", list(DONE_REPAIR)]]},
	{"label": "M&R Menunggu Approval",
	 "document_type": "Repair Order", "filters_json": [["status", "=", "Pending Approval"]]},
	# Uji berkala dibukukan sebagai M&R (v0_66), jadi ia SUDAH ikut terhitung di "M&R Aktif"
	# — kartu ini himpunan bagiannya, bukan angka di sebelahnya, dan "M&R Aktif" sengaja
	# tidak dikurangi supaya angka yang sudah dibaca orang tiap hari tidak berubah diam-diam.
	# Yang dijawab kartu ini: dari sekian M&R terbuka, berapa yang sebenarnya uji berkala —
	# pekerjaan yang punya tenggat kelas dan tidak boleh ikut antre di belakang repair.
	{"label": "Periodic Test Aktif",
	 "document_type": "Repair Order",
	 "filters_json": [["job_type", "=", "Periodic Test"], ["status", "not in", list(DONE_REPAIR)]]},
	{"label": "Survey Posisi Pending",
	 "document_type": "Container Position Survey",
	 # "In Survey" too: somebody has picked it up, but the tank is still un-located, so it is
	 # every bit as outstanding as one nobody has started.
	 "filters_json": [["status", "in", ["Pending Survey", "In Survey"]], ["docstatus", "<", 2]]},
	{"label": "Order Bongkar Aktif",
	 "document_type": "Order Bongkar",
	 "filters_json": [["order_status", "!=", "Completed"], ["docstatus", "=", 1]]},
	{"label": "Order Muat Aktif",
	 "document_type": "Order Muat",
	 "filters_json": [["order_status", "!=", "Completed"], ["docstatus", "=", 1]]},
	{"label": "Gate Out Plan Open",
	 "document_type": "Gate Out Plan", "filters_json": [["status", "=", "Open"]]},
	{"label": "Booking Belum Dibayar",
	 "document_type": "Container Booking",
	 "filters_json": [["payment_status", "=", "Unpaid"], ["docstatus", "=", 1]]},
	# Backlog wash khusus — pekerjaan yang diminta principal lewat email atas tank yang
	# sudah bersih, dan yang paling gampang tenggelam justru karena tidak lahir dari EIR:
	# di register manual, 512 dari 537 Steam Wash tidak pernah punya tanggal selesai.
	# "Cleaning Order Aktif" menghitung semuanya jadi satu angka dan menyembunyikan ini.
	{"label": "Wash Khusus Belum Selesai",
	 "document_type": "Cleaning Order",
	 "filters_json": [["cleaning_type", "in", list(SPECIAL_WASH_TYPES)],
			  ["status", "not in", list(DONE_CLEANING)], ["docstatus", "<", 2]]},
]

INVENTORY_CHARTS = [
	{"chart_name": "Tanks by Stage",
	 "document_type": "Container", "chart_type": "Group By", "group_by_type": "Count",
	 "group_by_based_on": "inventory_stage", "type": "Bar", "filters_json": _IN_DEPO_FILTER},
	{"chart_name": "Tanks by Principal",
	 "document_type": "Container", "chart_type": "Group By", "group_by_type": "Count",
	 "group_by_based_on": "principal", "type": "Donut", "number_of_groups": 10, "filters_json": _IN_DEPO_FILTER},
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
	# Order watch, the distribution behind the counters: where the open work is stuck.
	# Cancelled documents are filtered out so the bar chart is a worklist, not a ledger.
	{"chart_name": "Cleaning Order by Status",
	 "document_type": "Cleaning Order", "chart_type": "Group By", "group_by_type": "Count",
	 "group_by_based_on": "status", "type": "Bar", "filters_json": [["docstatus", "<", 2]]},
	{"chart_name": "M&R by Status",
	 "document_type": "Repair Order", "chart_type": "Group By", "group_by_type": "Count",
	 "group_by_based_on": "status", "type": "Bar",
	 "filters_json": [["status", "!=", "Cancelled"]]},
	# Komposisi beban M&R: repair versus uji berkala. Dibaca berdampingan dengan "M&R by
	# Status" — yang satu bilang di mana pekerjaan tersangkut, yang ini bilang pekerjaan apa.
	{"chart_name": "M&R by Jenis Pekerjaan",
	 "document_type": "Repair Order", "chart_type": "Group By", "group_by_type": "Count",
	 "group_by_based_on": "job_type", "type": "Bar",
	 "filters_json": [["status", "!=", "Cancelled"]]},
	# Sebaran Jenis Cleaning: berapa banyak cuci standar (lahir dari EIR-In tank kotor)
	# dibanding tiga wash khusus yang diminta principal. Cancelled dibuang supaya bar-nya
	# membaca beban kerja, bukan buku besar.
	{"chart_name": "Cleaning by Type (Last Month)",
	 "document_type": "Cleaning Order", "chart_type": "Group By", "group_by_type": "Count",
	 "group_by_based_on": "cleaning_type", "type": "Bar",
	 "filters_json": [["docstatus", "<", 2], ["order_created", "Timespan", "last month"]]},
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
	present yet (e.g. very early in a fresh bootstrap). A single spec whose
	``document_type`` does not exist yet is skipped too, so adding a card for a
	doctype that lands in the same release can never break the migrate."""
	if not frappe.db.has_column("Container", "inventory_stage"):
		return
	for card in INVENTORY_NUMBER_CARDS + ORDER_NUMBER_CARDS:
		if not frappe.db.exists("DocType", card["document_type"]):
			continue
		# Number Card autonames from label → that is the record name.
		_ensure_dashboard_doc("Number Card", card["label"], {
			"is_public": 1,
			"function": "Count",
			"type": "Document Type",
			**card,
		})
	for chart in INVENTORY_CHARTS:
		if not frappe.db.exists("DocType", chart["document_type"]):
			continue
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


def ensure_ppn_template():
	"""Ensure the PPN Sales Taxes and Charges Template exists for EVERY company.

	Every depot invoice is raised with ``taxes_and_charges = invoicing.PPN_TEMPLATE``; when
	the template is missing, ``_resolve_tax_template`` returns None and the invoice goes out
	with **no tax row at all** — silently, since a missing template is not an error to
	ERPNext. So this has to be an ``ensure_*`` that runs on every migrate, not the one-time
	patch it used to be (``patches.v0_9.seed_ppn_template``).

	That patch is exactly why this exists: on a fresh site it runs during install, BEFORE the
	setup wizard has created the company and its chart of accounts, hits its "no company"
	early return, and is then logged as done forever. The tax account it was waiting for
	arrives minutes later and the patch never looks again. Re-running the condition on every
	migrate is what makes the seed survive that ordering.
	"""
	try:
		if not frappe.db.exists("DocType", "Sales Taxes and Charges Template"):
			return
		from container_depot.invoicing import PPN_TEMPLATE

		for company in frappe.get_all("Company", pluck="name"):
			existing = frappe.db.get_value(
				"Sales Taxes and Charges Template", {"title": PPN_TEMPLATE, "company": company}, "name"
			)
			# An EXISTING template with no rows is as broken as a missing one, and worse: it
			# resolves, so the invoice is stamped with a template that charges nothing and no
			# error is raised anywhere. Guard on the rows, not on the parent.
			if existing and frappe.db.count("Sales Taxes and Charges", {"parent": existing}):
				continue
			account = _output_vat_account(company)
			if not account:
				# Unusual chart of accounts — skip this company rather than fail the migrate.
				# The next migrate tries again, which is the whole point of being an ensure_*.
				continue
			row = {
				"charge_type": "On Net Total",
				"account_head": account,
				"rate": 11,
				"description": "PPN 11%",
			}
			if existing:
				doc = frappe.get_doc("Sales Taxes and Charges Template", existing)
				doc.append("taxes", row)
				doc.save(ignore_permissions=True)
			else:
				frappe.get_doc({
					"doctype": "Sales Taxes and Charges Template",
					"title": PPN_TEMPLATE,
					"company": company,
					"taxes": [row],
				}).insert(ignore_permissions=True)
		frappe.db.commit()
	except Exception:
		frappe.log_error(frappe.get_traceback(), "container_depot PPN template seed failed")


def _output_vat_account(company):
	"""The company's output-VAT account (PPN Keluaran), else any liability tax account."""
	return (
		frappe.db.get_value(
			"Account",
			{"company": company, "account_type": "Tax", "name": ["like", "%Keluaran%"]},
			"name",
		)
		or frappe.db.get_value(
			"Account",
			{"company": company, "account_type": "Tax", "root_type": "Liability"},
			"name",
		)
		or frappe.db.get_value("Account", {"company": company, "account_type": "Tax"}, "name")
	)


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


PWA_PAGE = "depot-pwa"


def setup_pwa_page_roles():
	"""Keep the "Depot PWA (Lapangan)" Page open to whoever currently holds a field role.

	The page itself does nothing but redirect to /depot; its ``roles`` table is the whole
	point. It used to gate two Desk menu entries — a sidebar row and a workspace Shortcut
	card — both removed 2026-08-11 because the /desk **home tile** (Desktop Icon "Depot OAK
	(Mobile)", the Raven-style App icon) already puts the PWA one click from the landing
	screen, and three doors to one app is two too many.

	So the roles table now guards the page itself: its /app/depot-pwa URL and its awesomebar
	entry, both of which Frappe filters against ``roles``. That still matters — office staff
	who follow an old bookmark would otherwise land on an empty PWA. Restoring either menu
	entry needs nothing here; the gate travels with the Page.

	A full sync, not add-only: the flag is the source of truth, so unticking
	``Role.is_depot_field_role`` must close the page as surely as ticking it opens one. That
	does mean roles hand-added to this page are dropped — it is app-owned
	(``standard: Yes``); tick the flag on the role instead.

	Unlike the PWA menu, this needs a ``bench migrate`` to pick up a newly ticked role.
	Frappe reads page permissions from the stored ``roles`` table and there is no hook to
	compute them per request; the PWA menu stays instant, only this lags.
	"""
	if not frappe.db.exists("Page", PWA_PAGE):
		return  # not imported yet (first migrate of a fresh install) — next run catches it
	try:
		wanted = set(frappe.get_all("Role", filters={"is_depot_field_role": 1}, pluck="name"))
	except Exception:
		# Custom field not migrated yet. Leave the shipped role list alone rather than
		# clearing it — an empty `roles` table means "everyone", the wrong way to fail.
		frappe.log_error(title="depot-pwa page roles unreadable", message=frappe.get_traceback())
		return
	page = frappe.get_doc("Page", PWA_PAGE)
	if {r.role for r in page.roles} == wanted:
		return
	page.set("roles", [])
	for role in sorted(wanted):
		page.append("roles", {"role": role})
	page.save(ignore_permissions=True)
	frappe.db.commit()


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

	drop_legacy_inventory_sidebar()


# Container Inventory used to own a second left rail of its own: an auto-generated,
# non-standard ``Workspace Sidebar`` (plus a matching Desktop Icon) that Frappe creates
# when a public Workspace is pinned to the desktop. Opening /desk/container-inventory
# therefore swapped the whole navigation out for six report links and nothing else — no
# way back to bookings, gate, or M&R without going Home first.
#
# Those six links now live in the "Container Inventory" section of the Container Depot
# sidebar. With the standalone rail gone, ``sidebar.set_workspace_sidebar`` finds no
# ``workspace_sidebar_item["container inventory"]`` entry and falls through to
# ``get_workspace_sidebars()``, which matches the section's Workspace link and keeps the
# Container Depot rail on screen.
#
# Idempotent, and runs every migrate rather than as a one-shot patch: frappe recreates the
# Desktop Icon half on a fresh install (``create_desktop_icons_from_workspace``).
LEGACY_INVENTORY_SIDEBAR = "Container Inventory"


def drop_legacy_inventory_sidebar():
	"""Remove the standalone Container Inventory rail; it is a section now."""
	for doctype in ("Workspace Sidebar", "Desktop Icon"):
		try:
			if not frappe.db.exists(doctype, LEGACY_INVENTORY_SIDEBAR):
				continue
			# Never touch a fixture shipped by an app — only the auto-generated copy.
			if frappe.db.get_value(doctype, LEGACY_INVENTORY_SIDEBAR, "standard"):
				continue
			frappe.delete_doc(doctype, LEGACY_INVENTORY_SIDEBAR, force=True, ignore_permissions=True)
			frappe.db.commit()
		except Exception:
			frappe.log_error(
				frappe.get_traceback(), f"container_depot legacy {doctype} cleanup failed"
			)


# ---------------------------------------------------------------------------
# Desktop Icons: plug the two holes in the /desk home screen's permission filter
# ---------------------------------------------------------------------------
# `DesktopIcon.is_permitted()` only honours the User's "Allow Modules" list for
# icons of type Link that carry a `link_to` (it resolves the module through
# Workspace.link_to). Two icons on this site slip past that:
#
#   Framework — icon_type "App". App icons are gated by the owning app's
#     `add_to_apps_screen.has_permission` hook, and frappe 16.18 ships that hook
#     WITHOUT a has_permission key, so check_app_permission() falls through to
#     `return True` for every System User. Upstream added the System Manager gate
#     in a later 16.x; until the image is rebuilt we enforce it with a role.
#   Raven — icon_type "App" too. raven's own gate only asks whether a `Raven User`
#     record exists, and Raven auto-creates one for every user, so it is never a
#     gate at all. The `Raven User` role IS deliberate, so gate on that instead.
#
# The roles table is checked before the icon_type dispatch, so it works on App
# icons as well. Add-only: an icon that already has roles is left alone, so an
# admin can widen or narrow either one from the UI without a deploy undoing it.
#
# THIS APP SHIPS TWO ICONS, and the same quirk is why (desktop_icon/*.json):
#   Container Depot     — icon_type "Link" -> the Desk workspace. Correctly hidden by
#     Allow Modules, which is what we want for the Desk side.
#   Depot OAK (Mobile)  — icon_type "App", link "/depot". Deliberately NOT a Link icon:
#     the PWA is a separate surface that has nothing to do with Desk module access,
#     so an operator whose Allow Modules omits Container Depot must still reach it.
#     An App icon skips the module check entirely and gates on
#     `www.depot.check_app_permission` (= holds a field role) instead — the same
#     rule as the /apps tile, and it tracks the flag with no migrate.
#     Its `roles` table stays empty on purpose; adding roles here would shadow that
#     hook with a static list that a newly flagged role would not appear in.
#
# Note frappe would never have created the mobile icon on its own:
# `create_desktop_icons_from_installed_apps` labels App icons with `app_title`
# ("Container Depot"), and Desktop Icon is autonamed `field:label` — it would
# collide with the workspace icon above and die. Hence the explicit fixture.
#
# That fixture's filename is load-bearing and must stay `frappe.scrub(label)` —
# parentheses and all, hence `depot_oak_(mobile).json`. Every migrate,
# `model.sync.remove_orphan_entities` looks for exactly that path and DELETES any
# standard Desktop Icon it cannot find a file for. Rename the label without
# renaming the file and the tile silently disappears on the next deploy.
FOREIGN_ICON_ROLES = {
	"Framework": ["System Manager"],
	"Raven": ["Raven User", "Raven Admin"],
}


def sync_desktop_icons():
	"""Role-gate the foreign app icons that ignore the user's Allow Modules list."""
	for icon, roles in FOREIGN_ICON_ROLES.items():
		try:
			_ensure_icon_roles(icon, roles)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"container_depot desktop icon sync failed: {icon}")


def _ensure_icon_roles(icon: str, roles: list[str]) -> None:
	if not frappe.db.exists("Desktop Icon", icon):
		return
	if frappe.db.exists("Has Role", {"parenttype": "Desktop Icon", "parent": icon}):
		# Already curated (by us on an earlier migrate, or by an admin) — don't touch.
		return

	roles = [r for r in roles if frappe.db.exists("Role", r)]
	if not roles:
		return

	doc = frappe.get_doc("Desktop Icon", icon)
	for role in roles:
		doc.append("roles", {"role": role})
	doc.save(ignore_permissions=True)


# ---------------------------------------------------------------------------
# Role model (rebuilt 2026-08-06, replaces the Phase-6 model purged 2026-08-05)
# ---------------------------------------------------------------------------
# Two families. FIELD roles work the yard through the /depot PWA and have
# desk_access = 0 — their users are bounced out of /app on purpose. OFFICE roles
# work in the Desk; they get an empty PWA unless listed in PWA_OFFICE_ROLES below.
#
# The checkbox `Role.is_depot_field_role` (see CUSTOM_FIELDS) is what ess.context
# reads, NOT this list: an admin can add a 14th field role from the UI and it works
# without a deploy. This list only seeds the ones the app ships with.

FIELD_ROLES = [
	"Security",
	"Team EIR",
	"Team Kalmar",
	"Team Cleaning",
	"Team Repair",
	"Team Survey",
	"SPV Lapangan",
]

OFFICE_ROLES = [
	"Admin Ops",
	"Cashier",
	"Finance",
	"Commercial",
	"Warehouse",
	"Management",
]

# Office roles that work the PWA as well as the Desk. The two flags are independent —
# `is_depot_field_role` opens /depot, `desk_access` keeps /app — so this is not the same
# as moving the role into FIELD_ROLES, which would lock it out of the Desk.
#
# Admin Ops is here because it is the ops backstop: it already holds DocPerm on every
# depot doctype, so it lands in the yard to unstick a job the field roles cannot finish
# (a mis-submitted bon, a gate entry nobody may amend). Sending that person to a desktop
# to do it was the wrong default. The consequence is worth stating plainly: because the
# PWA menu is DocPerm-driven, Admin Ops sees EVERY tile, not a subset.
PWA_OFFICE_ROLES = {"Admin Ops"}

# Standard ERPNext roles to assign ALONGSIDE the office role when creating a user.
# Deliberately not automated: granting these means writing Custom DocPerm rows on
# standard doctypes (Sales Invoice, Item, Purchase Order…), and the first Custom
# DocPerm on a doctype makes Frappe ignore that doctype's shipped permissions
# entirely — it would silently strip ERPNext's own accounting/stock roles. So the
# custom roles below carry Container Depot module perms only, and the standard access is
# granted the standard way: give the user both roles. Surfaced in STRUCTURE.md.
COMPANION_ROLES = {
	"Cashier": ["Accounts User"],
	"Finance": ["Accounts Manager"],
	"Commercial": ["Sales Manager", "Item Manager"],
	"Warehouse": ["Stock User", "Purchase User"],
}

# ---------------------------------------------------------------------------
# Role Profiles — the assignment UX for the model above
# ---------------------------------------------------------------------------
# One profile per app role, named after the role, carrying that role plus its
# COMPANION_ROLES. Step 2+3 of "Assigning a user" (STRUCTURE.md) collapse into one pick:
# choosing "Cashier" grants `Cashier` AND `Accounts User`, so the companion role can no
# longer be forgotten. PARKED_ROLES already shrank the picker; this removes the picking.
#
# WHAT A PROFILE DOES TO A USER — read before editing one
# -------------------------------------------------------
# `User.populate_role_profile_roles` sets the user's roles to the UNION of their assigned
# profiles and DROPS everything else (frappe/core/doctype/user/user.py). A profile is
# therefore authoritative, not additive: a role that is not in any of the user's profiles
# is removed on the next save. Two consequences:
#
#   * A user needing something outside the depot model (e.g. `Raven User` for chat, or a
#     second depot role) must have it added TO a profile, or hold no profile at all.
#     That is why this seeder is add-only below.
#   * Editing a profile re-saves every user holding it, in a background job.
#
# The seeder is ADD-ONLY on the roles table: it creates a missing profile and adds a
# missing app role to an existing one, but never removes a role an admin put there. Extra
# roles on a profile are a supported customisation, not drift to be corrected.
def _role_profile_roles(role: str) -> list[str]:
	"""Roles a profile for `role` must carry: the role itself plus its companions."""
	return [role, *COMPANION_ROLES.get(role, [])]


# ERPNext (`erpnext.setup.install.create_default_role_profiles`) and HRMS ship these six
# as generic module bundles. They are retired here: they hand out standard roles that do
# not map to any depot job, and a picker with both "Sales" and "Commercial" in it is the
# same wrong-box problem PARKED_ROLES was written to solve. Both apps create them from
# `after_install` only, so deleting them does not start a fight with the next migrate.
#
# A profile still held by a user is left alone and reported — see `_delete_role_profile`.
STOCK_ROLE_PROFILES = ["Accounts", "HR", "Inventory", "Manufacturing", "Purchase", "Sales"]

# Container Depot doctypes that record what happened rather than drive it. Read-only for
# everyone: these are written by hooks, never by hand.
# Storage Charge belongs here for the same reason as the rest: every field on it is
# derived from the gate records by ``storage_charge.sync``, so a hand-typed row is a row
# that disagrees with the yard — and one hand-edited "Ditagih s/d" is a day billed twice
# or never. It is read + corrected, never created.
AUDIT_DOCTYPES = {"Container Activity", "Container Movement", "SST Activity Log", "Storage Charge"}

# Doctypes nobody may CREATE from the Desk — the audit ledgers above plus Gate Entry.
#
# Gate Entry is the odd one out and worth explaining: it is a real submittable transaction,
# but every row is written by a hook or an integration — the arrival by
# ``Order Bongkar._record_gate_in``, the departure by ``gate.mark_gate_out``, the SST lane by
# ``api.register_gate_entry`` — and all three insert with ``ignore_permissions``. A gate log
# typed in by hand is a gate log that disagrees with the yard, so the "+ Add" button on
# "Riwayat Gate" was an invitation to corrupt it, not a feature.
#
# ``write`` survives: an admin correcting a mistyped truck plate on an audit row is fine.
# create / submit / cancel / amend / delete do not, for EVERY role — including the System
# Manager blanket grant, which is otherwise how the button came back.
NO_MANUAL_CREATE = AUDIT_DOCTYPES | {"Gate Entry"}

# Container Depot doctypes owned by finance/commercial, kept OUT of Admin Ops' blanket
# grant (§8.2: "TANPA Sales Invoice, Payment Entry, Depot Contract…").
FINANCE_DOCTYPES = {"Depot Contract", "OAK Monthly Invoice", "Depot Finance Settings"}

# Reference/config records. Admin Ops may correct them but not spawn new ones.
MASTER_DOCTYPES = {
	"Booking Code",
	"Cargo",
	"Cleaning Checklist Item",
	"Customer Portal User",
	"Depot",
	"Depot Service Menu",
	"Inspection Checklist Item",
	"Inspection Damage Code",
	"Inspection Fitting Item",
	"Inspection Repair Code",
	"Self Service Terminal",
	"Shipping Line",
	"Surveyor Company",
}

# Compact permission grammar, one letter per flag. `r` carries report+export+print with it
# because a role that may read a doctype has no reason to be barred from listing it — or
# from printing it. `print` is its own Frappe flag and was missing here, which is why the
# Desk showed no Print action on ANY Container Depot document: the first Custom DocPerm on
# a doctype makes Frappe ignore its shipped permissions wholesale, so a flag this seeder
# never sets is a flag nobody has. Note `export` was always granted, and export hands over
# strictly more than a printed copy does — print was the odd one out, not the risky one.
#
# `email` is deliberately NOT in the bundle: printing produces a copy for the person
# already allowed to read the document, emailing sends it to someone who is not.
_PERM_LETTERS = {
	"r": ("read", "report", "export", "print"),
	"w": ("write",),
	"c": ("create",),
	"s": ("submit",),
	"x": ("cancel",),
	"a": ("amend",),
	"d": ("delete",),
}

# §8.1 — field-role matrix, transcribed column-for-column from the handoff table.
# "" = no DocPerm at all for that role on that doctype.
#
# Note the `Container Position Survey` row: Team Survey gets rwc (record the survey),
# Team Kalmar gets rws (approve "udah turun"). That write/submit split on ONE doctype
# is exactly what separates the `surveyPos` and `posFix` menus — see ess.context._MENU.
_FIELD_ROLE_ORDER = FIELD_ROLES
FIELD_ROLE_MATRIX = [
	#  DocType                       Security  TeamEIR  Kalmar  Cleaning  Repair  Survey  SPV
	("Container",                   ("r",     "r",     "r",    "r",      "r",    "r",    "r")),
	# Gate Entry reads "rwcs" in the handoff table. It is seeded rw: NO_MANUAL_CREATE strips
	# create/submit app-wide because every gate record is written by a hook. Security, Kalmar
	# and SPV keep write so a mistyped truck plate stays correctable.
	("Gate Entry",                  ("rw",    "r",     "rw",   "",       "",     "",     "rw")),
	# Kalmar reads "r" in the handoff table, which left them holding gate notifications they
	# could not open: the Gate tile keys on create over Order Bongkar (ess.context._MENU), and
	# gate-out / load-complete is their work. Granted rwc to match Security and SPV.
	("Order Bongkar",               ("rwc",   "r",     "rwc",  "",       "",     "",     "rwc")),
	# SPV reads "rw" in the handoff table, which left NOBODY below Admin Ops able to issue a
	# bon Muat: `_require_order_create` keys on create over the direction's doctype, so on a
	# Tank Out booking the "Generate Bon / Order" button never rendered for the yard. Granting
	# create mirrors Order Bongkar one line up. Security stays read-only — that half of the
	# asymmetry is the deliberate one (see api._require_order_create's docstring).
	("Order Muat",                  ("r",     "r",     "r",    "",       "",     "",     "rwc")),
	# Not in the handoff table at all, and it has to be: the Generate Bon / Order button lives
	# on the Container Booking FORM, so create on the order doctype is a dead grant without
	# read on the booking it is issued from. Read only — a booking's charges, customer and
	# payment terms belong to the office, never to the yard.
	("Container Booking",           ("",      "",      "",     "",       "",     "",     "r")),
	("Booking Code",                ("r",     "",      "",     "",       "",     "",     "r")),
	("Inspection",                  ("",      "rwcs",  "r",    "r",      "r",    "r",    "rwcs")),
	("Cleaning Order",              ("",      "r",     "r",    "rwcs",   "",     "",     "rwcs")),
	("Repair Order",                ("",      "r",     "r",    "",       "rwc",  "",     "rwc")),
	("Container Position Survey",   ("",      "",      "rws",  "",       "",     "rwc",  "rwcs")),
	("Container Activity",          ("r",     "r",     "r",    "r",      "r",    "r",    "r")),
	("Container Movement",          ("r",     "r",     "r",    "r",      "r",    "r",    "r")),
]

# §8.2 — office roles, Container Depot module doctypes only (see COMPANION_ROLES for the
# rest). Admin Ops and Management are computed in :func:`_office_role_perms` because
# they are defined as "everything except…" rather than as a list.
OFFICE_ROLE_MATRIX = {
	"Cashier": {
		"Storage Charge": "r",
		"Container Booking": "r",
		"Gate Entry": "r",
		"Container": "r",
		"Order Muat": "r",
		"Order Bongkar": "r",
	},
	"Finance": {
		"Storage Charge": "r",
		"Container Booking": "r",
		"Gate Entry": "r",
		"Container": "r",
		"Order Muat": "r",
		"Order Bongkar": "r",
		"OAK Monthly Invoice": "rwcsxa",
		"Depot Finance Settings": "rw",
		"Depot Contract": "r",
	},
	"Commercial": {
		"Storage Charge": "r",
		"Depot Contract": "rwcsxa",
		"Depot Service Menu": "rwc",
		"Container": "r",
		"Container Booking": "r",
	},
	"Warehouse": {
		# Purchase Order / Receipt / Stock Entry / Supplier live outside this module —
		# granted via COMPANION_ROLES (Q-01 answered 2026-08-06: Warehouse owns them).
		"Repair Order": "r",
		"Container": "r",
	},
}

# Report access is NOT seeded. A Report with an empty `roles` table falls back to the
# permission on its ref_doctype (Report.is_permitted), so Order Billing Status is already
# reachable by exactly the roles that may read Container Booking — Cashier, Finance,
# Commercial, Admin Ops, Management — and unreachable by the field roles, which have no
# Container Booking perm at all. Listing roles on the report as well would be a second
# place to keep in sync, and saving a standard Report rewrites its JSON on disk.


def _perm_dict(letters: str, is_submittable: bool) -> dict:
	"""Expand the compact grammar into a Custom DocPerm payload."""
	perms = {}
	for letter in letters:
		for flag in _PERM_LETTERS[letter]:
			perms[flag] = 1
	if not is_submittable:
		# Frappe rejects submit/cancel/amend on a non-submittable doctype.
		for flag in ("submit", "cancel", "amend"):
			perms.pop(flag, None)
	return perms


def _depot_doctypes() -> list[str]:
	"""Non-child Container Depot doctypes. Child tables inherit their parent's perms."""
	return frappe.get_all(
		"DocType",
		filters={"module": "Container Depot", "istable": 0},
		pluck="name",
		order_by="name",
	)


def _office_role_perms(role: str, doctypes: list[str]) -> dict:
	"""DocType -> permission letters for an office role."""
	if role == "Management":
		# Read-only across the whole app. No write/create/submit/cancel/delete, ever —
		# a manager who can edit an EIR is how audit trails rot.
		return {dt: "r" for dt in doctypes}
	if role == "Admin Ops":
		out = {}
		for dt in doctypes:
			if dt in FINANCE_DOCTYPES:
				continue
			elif dt in AUDIT_DOCTYPES:
				out[dt] = "r"
			elif dt in MASTER_DOCTYPES:
				out[dt] = "rw"
			else:
				# Operational transactions: full lifecycle including cancel/amend. Admin Ops
				# is the backstop for a mis-submitted bon — field roles get submit only
				# (see FIELD_ROLE_MATRIX), so undoing one escalates here by design.
				out[dt] = "rwcsxa"
		return out
	return OFFICE_ROLE_MATRIX.get(role, {})


# ---------------------------------------------------------------------------
# Role picker hygiene — hide roles this depot will never assign
# ---------------------------------------------------------------------------
# Nine apps are installed and every one contributes roles to the same flat,
# alphabetical checkbox list on the User form: 71 entries, six of them held by an
# actual person. Picking "Team Cleaning" out of that is how the wrong box gets ticked.
#
# WHY A DOMAIN TAG AND NOT `Role.disabled`
# ----------------------------------------
# `disabled` is the obvious lever and it is a trap. `Role.validate` routes it to
# `remove_roles()`, which runs `frappe.db.delete("Has Role", {"role": ...})` — ticking
# the box STRIPS the role from everyone holding it, and unticking does not give it back.
# There is no record of who had it, so the mistake cannot be undone by hand.
#
# `get_all_roles` (the picker) also drops any role whose `restrict_to_domain` is not an
# active domain, and nothing on that path touches `Has Role`. Same effect on screen,
# fully reversible. Both were verified before choosing.
#
# TO BRING ONE BACK: Role list -> clear **Restrict To Domain** -> Save. Or all at once:
#     bench --site <site> execute container_depot.install.unpark_roles
PARKED_DOMAIN = "Unused"

# Grouped by origin so the next person can judge a line instead of trusting the list.
# Anything held by a real depot account, carrying a DocPerm on a Container Depot doctype,
# or named in COMPANION_ROLES is deliberately absent.
PARKED_ROLES = [
	# Gameplan
	"Gameplan Admin", "Gameplan Guest", "Gameplan Member",
	# Helpdesk
	"Agent", "Agent Manager", "Helpdesk Contact",
	"Knowledge Base Contributor", "Knowledge Base Editor", "Support Team",
	# Telephony
	"TP Agent", "TP Manager",
	# HR / Payroll
	"Employee", "Employee Self Service", "Expense Approver",
	"HR Manager", "HR User", "Interviewer", "Leave Approver",
	# Manufacturing / Quality
	"Manufacturing Manager", "Manufacturing User", "Quality Manager",
	# ERPNext modules this depot does not run
	"Academics User", "Analytics", "Auditor", "Delivery Manager", "Delivery User",
	"Fleet Manager", "Fulfillment User", "Maintenance Manager", "Maintenance User",
	"Marketing Manager", "Newsletter Manager", "Projects Manager", "Projects User",
	"Supplier",
	# Master/Manager tiers of companion roles we do grant (COMPANION_ROLES hands out the
	# plain User tier). Un-park the manager tier if a lead genuinely needs it.
	"Purchase Manager", "Purchase Master Manager", "Sales Master Manager",
	"Sales User", "Stock Manager",
	# Desk power-user tooling — nobody here writes Server Scripts or edits Workspaces.
	"Dashboard Manager", "Inbox User", "Prepared Report User", "Report Manager",
	"Script Manager", "Translator", "Website Manager", "Workspace Manager",
]

# These five are shipped by their app as FIXTURES (gameplan: `role_name like "Gameplan %"`,
# telephony: `like "TP%"`), and `sync_fixtures()` runs AFTER the patch queue — so a one-time
# patch parks them and the same migrate un-parks them again. They are the one group that has
# to be re-asserted on every migrate, which means un-parking one by hand will not survive:
# delete it from this list instead.
FIXTURE_OWNED_ROLES = ["Gameplan Admin", "Gameplan Guest", "Gameplan Member", "TP Agent", "TP Manager"]


def _ensure_parked_domain():
	if not frappe.db.exists("Domain", PARKED_DOMAIN):
		frappe.get_doc({"doctype": "Domain", "domain": PARKED_DOMAIN}).insert(ignore_permissions=True)


def park_roles(names=None):
	"""Tag roles with the inactive `Unused` domain so they leave the User form picker.

	Never overwrites a role that already carries some other domain — that is an admin's
	choice. Returns the names actually parked.
	"""
	_ensure_parked_domain()
	parked = []
	for role in names if names is not None else PARKED_ROLES:
		if not frappe.db.exists("Role", role):
			continue  # a site without that app
		if frappe.db.get_value("Role", role, "restrict_to_domain"):
			continue
		# db.set_value, not doc.save(): saving a Role runs validate(), and validate() is
		# exactly where the Has Role wipe lives. Writing the column cannot trip it.
		frappe.db.set_value("Role", role, "restrict_to_domain", PARKED_DOMAIN, update_modified=False)
		parked.append(role)
	if parked:
		frappe.clear_cache()
	return parked


def reassert_parked_fixture_roles():
	"""after_migrate: re-park the five roles their own app's fixtures just un-parked."""
	try:
		park_roles(FIXTURE_OWNED_ROLES)
	except Exception:
		frappe.log_error(title="container_depot role parking failed", message=frappe.get_traceback())


def unpark_roles():
	"""Undo: put every parked role back in the picker. Assignments were never touched."""
	names = frappe.get_all("Role", filters={"restrict_to_domain": PARKED_DOMAIN}, pluck="name")
	for role in names:
		frappe.db.set_value("Role", role, "restrict_to_domain", None, update_modified=False)
	frappe.clear_cache()
	print(f"Un-parked {len(names)} roles")
	return names


def ensure_roles_exist():
	"""Create the 13 app roles and keep their two flags in sync. Idempotent.

	The flags are re-asserted on every migrate because they are app-owned: a field role
	that loses `is_depot_field_role` silently empties its users' PWA, with no error to
	trace it back from. Roles an ADMIN creates are never touched — this only knows about
	the names below.
	"""
	for name in FIELD_ROLES + OFFICE_ROLES:
		is_field = name in FIELD_ROLES
		flags = {
			"desk_access": 0 if is_field else 1,
			"is_depot_field_role": 1 if (is_field or name in PWA_OFFICE_ROLES) else 0,
		}
		if not frappe.db.exists("Role", name):
			frappe.get_doc({"doctype": "Role", "role_name": name, **flags}).insert(
				ignore_permissions=True
			)
			continue
		current = frappe.db.get_value("Role", name, list(flags), as_dict=True)
		drift = {k: v for k, v in flags.items() if (current.get(k) or 0) != v}
		if drift:
			frappe.db.set_value("Role", name, drift)

	frappe.db.commit()


def _role_profile_holders(profile: str) -> list[str]:
	"""Users holding `profile`, via the child table or the deprecated single field."""
	holders = frappe.get_all(
		"User Role Profile", filters={"role_profile": profile, "parenttype": "User"}, pluck="parent"
	)
	holders += frappe.get_all("User", filters={"role_profile_name": profile}, pluck="name")
	return sorted(set(holders))


def _delete_role_profile(profile: str) -> bool:
	"""Drop a Role Profile, unless a user still holds it. True if it went."""
	if not frappe.db.exists("Role Profile", profile):
		return False
	holders = _role_profile_holders(profile)
	if holders:
		# Deleting it would strip those users' roles on their next save, with nothing left
		# on the account to say what they used to have. Leave it and say so.
		print(
			f"[container_depot] kept Role Profile {profile}: still held by {', '.join(holders)}"
		)
		return False
	frappe.delete_doc("Role Profile", profile, ignore_permissions=True)
	print(f"[container_depot] deleted Role Profile {profile}")
	return True


def setup_role_profiles():
	"""Seed one Role Profile per app role and retire the stock ERPNext/HRMS bundles.

	Idempotent, and ADD-ONLY on the roles table: a profile an admin has extended (an extra
	depot role, `Raven User`, anything) keeps those rows. Only a missing profile, or a
	missing app-owned role inside an existing one, is written — so this re-asserts the
	model without undoing customisation. See STOCK_ROLE_PROFILES / _role_profile_roles.
	"""
	for profile in STOCK_ROLE_PROFILES:
		_delete_role_profile(profile)

	for name in FIELD_ROLES + OFFICE_ROLES:
		wanted = [r for r in _role_profile_roles(name) if frappe.db.exists("Role", r)]
		if not frappe.db.exists("Role Profile", name):
			doc = frappe.new_doc("Role Profile")
			doc.role_profile = name
			doc.home_page = _profile_home_page(name)
			for role in wanted:
				doc.append("roles", {"role": role})
			doc.insert(ignore_permissions=True)
			continue
		doc = frappe.get_doc("Role Profile", name)
		missing = [r for r in wanted if r not in {row.role for row in doc.roles}]
		# Fill a BLANK home page only. An admin who pointed a profile somewhere else keeps
		# it, exactly as the roles table is add-only above.
		home_page = None if doc.get("home_page") else _profile_home_page(name)
		if not missing and not home_page:
			continue
		if home_page:
			doc.home_page = home_page
		for role in missing:
			doc.append("roles", {"role": role})
		# save(), not db_insert on the child rows: on_update re-saves every user holding
		# the profile, which is what actually pushes the new role onto their account.
		doc.save(ignore_permissions=True)

	frappe.db.commit()


def _profile_home_page(name: str) -> str | None:
	"""Landing page for a shipped profile: the PWA for the yard, the Desk for the office.

	Admin Ops is deliberately absent even though it carries the field-role flag. It is the
	ops backstop and works both surfaces; it keeps ``desk_access`` and so keeps the Desk as
	its home. Sending it to /depot would take the Desk away from the one account that most
	needs it — the same asymmetry ``desk_landing`` enforces at request time.
	"""
	return "/depot" if name in FIELD_ROLES else None


def _ensure_docperm(doctype: str, role: str, letters: str, is_submittable: bool) -> None:
	"""Add-only: an existing (doctype, role) row is left exactly as the admin tuned it."""
	if doctype in NO_MANUAL_CREATE:
		# Enforced here rather than in each matrix so a doctype added to the set later is
		# covered without hunting down every table that mentions it.
		letters = "".join(c for c in letters if c in "rw")
	if not letters or frappe.db.exists("Custom DocPerm", {"parent": doctype, "role": role}):
		return
	frappe.get_doc({
		"doctype": "Custom DocPerm",
		"parent": doctype,
		"parenttype": "DocType",
		"parentfield": "permissions",
		"role": role,
		"permlevel": 0,
		**_perm_dict(letters, is_submittable),
	}).insert(ignore_permissions=True)


def setup_permissions():
	"""Seed the role permission matrix (§8) on every Container Depot doctype. Idempotent.

	Add-only and existence-checked per (doctype, role), so running it on every migrate
	just picks up doctypes added since the last one. Once a row exists it belongs to the
	admin — Permission Manager edits survive migrates.

	Custom DocPerm is written ONLY for module=Container Depot doctypes. The first Custom
	DocPerm on any doctype makes Frappe ignore that doctype's shipped permissions
	wholesale, so touching a standard ERPNext doctype here would quietly disable its
	own roles. Office access to Sales Invoice / Item / Purchase Order is granted by
	assigning the matching standard role instead — see COMPANION_ROLES.
	"""
	ensure_roles_exist()

	doctypes = _depot_doctypes()
	submittable = {dt: frappe.get_meta(dt).is_submittable for dt in doctypes}

	# ROLES_TO_GRANT (System Manager) keeps its blanket grant so a doctype added later is
	# never unreachable — most Container Depot JSONs ship with an empty "permissions" array.
	for dt in doctypes:
		for role_name in ROLES_TO_GRANT:
			_ensure_docperm(dt, role_name, "rwcsxad", submittable[dt])

	# §8.1 field roles.
	for dt, letters_per_role in FIELD_ROLE_MATRIX:
		if dt not in submittable:
			continue  # doctype retired since this table was written; skip, don't crash
		for role_name, letters in zip(_FIELD_ROLE_ORDER, letters_per_role):
			_ensure_docperm(dt, role_name, letters, submittable[dt])

	# §8.2 office roles.
	for role_name in OFFICE_ROLES:
		for dt, letters in _office_role_perms(role_name, doctypes).items():
			_ensure_docperm(dt, role_name, letters, submittable[dt])

	frappe.db.commit()


# ---------------------------------------------------------------------------
# Notification routing (§7.2)
# ---------------------------------------------------------------------------
# Starting points only. Once seeded, these rows belong to the admin: the seeder never
# overwrites an existing event_key, so tuning survives every migrate. That is the whole
# reason routing is a doctype instead of a dict — see the module docstring in
# container_depot/notify.py for why the menu went the other way.
#
# `Management` appears on three strategic events only (repair approval, contracts). A
# manager who gets a bell for every tank arriving stops reading the bell, and then misses
# the approval that mattered. Resist adding them to operational events.
#
# THE FIELD TEAMS ARE ONLY TOLD ON HANDOFF. Team EIR / Team Cleaning / Team Repair sit on
# the events where work is HANDED to them, never on "an order was created / submitted".
# A tank arriving is not yet their job: Admin Ops still picks the cleaning method, still
# waits for the owner to approve an estimate, still decides the depot is ready to start.
# Ringing the team at creation trains them to chase orders Admin Ops has not released —
# and to tune out the bell that finally says the work is theirs. So creation is Admin Ops
# + SPV Lapangan, and each team hears exactly one thing:
#
#     cleaning_order_forwarded  Cleaning Order, Service Setup -> Pending ("Teruskan ke Team")
#     repair_order_forwarded    Repair Order,   Approved      -> Pending ("Teruskan ke Team")
#     eir_created               Inspection,     draft dibuat  ("EIR dibuat")
#
# Team EIR's line reads differently from the other two, and deliberately. There IS no Admin
# Ops step in front of an EIR — the tank is at the gate, the draft is provisioned by the bon
# submit itself, and the checklist is the work — so for this queue creation and handoff are
# the same moment, and `eir_created` is that moment. It is still ONE bell on ONE event: they
# stay off `order_muat_survey` and `eir_submitted`, which fire on the bon and on a FINISHED
# inspection respectively, neither of which is a job landing in their worklist.
# (v0_78.team_notified_on_handoff_only took them off those two; `eir_created` is what they
# were given instead.)
#
# (event_key, label, description, [roles])
NOTIFICATION_RULES = [
	# The only rule Team EIR is on. Fires on the DRAFT, which is the thing they can actually
	# pick up — see `notify.notify_eir_created` for why creation is the handoff here.
	("eir_created", "EIR dibuat", "EIR draft dibuat (otomatis dari bon Bongkar/Muat, atau manual) — tank menunggu diperiksa.",
		["Team EIR", "SPV Lapangan", "Admin Ops"]),
	# No field team here at all. Team Cleaning / Team Repair hold read-only Inspection, so `/eir`
	# (which the tap resolves to) refuses them the menu and the bell leads nowhere. Team EIR was
	# dropped for the other reason: this fires when an EIR is *finished*, which is news to whoever
	# is waiting on the tank, not to the crew that just recorded it.
	("eir_submitted", "EIR disubmit", "Sebuah EIR (In/Out) disubmit — tank selesai diperiksa.",
		["SPV Lapangan", "Admin Ops"]),
	("eir_pending_review", "EIR menunggu review", "Operator lapangan mengirim EIR untuk direview Admin Ops.",
		["Admin Ops", "SPV Lapangan"]),
	("cleaning_pending_review", "Cleaning menunggu review", "Operator cuci selesai di PWA dan mengirim order untuk direview Admin Ops.",
		["Admin Ops", "SPV Lapangan"]),
	# Lands in Admin Ops' queue as Service Setup, where the cleaning method is still to be picked —
	# the crew cannot start on it yet, so they are not told yet. `cleaning_order_forwarded` is theirs.
	("cleaning_order_created", "Cleaning Order dibuat", "Cleaning Order otomatis dibuat dari EIR Empty-Dirty — masuk antrean Admin Ops (Service Setup).",
		["SPV Lapangan", "Admin Ops"]),
	("cleaning_order_forwarded", "Cleaning diteruskan ke team", "Admin Ops sudah memilih metode cleaning dan meneruskan order — masuk worklist PWA team cuci.",
		["Team Cleaning", "SPV Lapangan", "Admin Ops"]),
	# Draft only: nothing may be worked until the owner approves the estimate and Admin Ops
	# forwards it. The team's bell is `repair_order_forwarded`.
	("repair_order_created", "M&R dibuat", "Repair Order draft otomatis dibuat dari EIR yang menemukan kerusakan.",
		["SPV Lapangan", "Admin Ops"]),
	("repair_order_service_setup", "M&R menunggu review", "Team repair selesai di PWA dan mengirim order untuk direview Admin Ops; part belum keluar gudang sampai Desk menyelesaikan.",
		["Admin Ops", "SPV Lapangan"]),
	("repair_order_forwarded", "M&R diteruskan ke team", "Admin Ops meneruskan M&R yang sudah disetujui owner — order masuk worklist PWA team repair.",
		["Team Repair", "SPV Lapangan", "Admin Ops"]),
	("repair_order_pending_approval", "M&R menunggu approval owner", "Estimasi M&R dikirim ke owner tank.",
		["Admin Ops", "Management"]),
	# An owner's "yes" is not yet a work order — dispatch is a separate decision Admin Ops takes
	# (`repair_order_forwarded`), so telling the team here would ring twice for one job and, on a
	# "no", ring about work that will never come.
	("repair_order_decided", "Owner memutuskan M&R", "Owner menyetujui / menolak / minta revisi estimasi M&R.",
		["SPV Lapangan", "Admin Ops"]),
	("repair_revision_requested", "Team minta M&R dibuka lagi", "Team repair mengajukan revisi atas M&R yang sudah ditutup — Admin Ops yang memutuskan membukanya.",
		["Admin Ops", "SPV Lapangan"]),
	("eir_revision_requested", "Team minta EIR dibuka lagi", "Operator mengajukan revisi atas EIR yang sudah disubmit — Admin Ops yang memutuskan membukanya.",
		["Admin Ops", "SPV Lapangan"]),
	("cleaning_revision_requested", "Team minta cleaning dibuka lagi", "Operator cuci mengajukan revisi atas Cleaning Order yang sudah disubmit — Admin Ops yang memutuskan membukanya.",
		["Admin Ops", "SPV Lapangan"]),
	("order_gate_in", "Bon Bongkar terbit", "Order Bongkar disubmit — bon gate-in siap diprint.",
		["Security", "SPV Lapangan", "Admin Ops"]),
	("order_gate_out", "Bon Muat terbit", "Order Muat disubmit — bon gate-out siap diprint.",
		["Security", "Team Kalmar", "SPV Lapangan", "Admin Ops"]),
	# Fires on the Order Muat submit itself, which is creation-time by any reading, so no field
	# team is on it. (Team Survey was removed earlier for a different reason: this is the EIR-Out,
	# not the position survey, and they hold no Inspection perm at all.)
	("order_muat_survey", "EIR-Out jatuh tempo", "Order Muat disubmit — EIR-Out wajib sebelum tank boleh dimuat.",
		["SPV Lapangan", "Admin Ops"]),
	("eir_out_hold", "Tank di-HOLD", "EIR-Out menemukan masalah — perlu clearance supervisor.",
		["SPV Lapangan", "Admin Ops"]),
	# Survey posisi (Lift On). One doctype, two menus, so two handoffs: the survey lands in
	# Team Survey's worklist, then the recorded position lands in Team Kalmar's. Each team is
	# on its own handoff and nothing else — the same rule the cleaning / M&R crews follow.
	("position_survey_pending", "Survey posisi dibuat", "Booking Tank Out disubmit — posisi tank harus disurvei sebelum bisa ditarik.",
		["Team Survey", "SPV Lapangan", "Admin Ops"]),
	("position_surveyed", "Posisi menunggu approval Kalmar", "Surveyor sudah mencatat letak tank — menunggu konfirmasi \"udah turun\" dari Team Kalmar.",
		["Team Kalmar", "SPV Lapangan", "Admin Ops"]),
	# Oversight only: both field teams are finished by the time this fires, and the route
	# behind it is Riwayat — a bell about work nobody may pick up is the kind that gets muted.
	("position_confirmed", "Posisi dikonfirmasi", "Team Kalmar sudah approve \"udah turun\" — survey posisi selesai.",
		["SPV Lapangan", "Admin Ops"]),
	("gate_out", "Isotank keluar depo", "Gate-out / load-complete selesai untuk sebuah tank.",
		["Security", "Team Kalmar", "Admin Ops", "Cashier"]),
	("booking_created", "Booking baru", "Container Booking dibuat (masih draft).",
		["Admin Ops", "Cashier", "Commercial"]),
	("booking_submitted", "Booking dikonfirmasi", "Container Booking disubmit / dikonfirmasi.",
		["Admin Ops", "Cashier", "Security"]),
	("contract_created", "Kontrak depo dibuat", "Depot Contract dibuat — belum bisa dipakai sampai diaktifkan.",
		["Commercial", "Management"]),
	("contract_activated", "Kontrak depo aktif", "Depot Contract berstatus Active — tarifnya sudah live.",
		["Commercial", "Management", "Admin Ops"]),
	("invoice_submitted", "Invoice terbit", "Sales Invoice disubmit — ada tagihan untuk ditagih/dicatat.",
		["Cashier", "Finance"]),
]

# Recipients when an event fires with no rule at all (a new event_key shipped without a
# seed entry). Never "everyone" — a silent broadcast is the exact regression this replaces.
NOTIFICATION_FALLBACK_ROLES = ["Admin Ops", "SPV Lapangan"]


def setup_notification_rules():
	"""Seed the notification routing table. Idempotent and NEVER overwrites.

	An existing ``event_key`` is left exactly as the admin tuned it — that is the point of
	the doctype. Only rows that do not exist yet are inserted, so a migrate can add a new
	event without undoing months of routing adjustments.
	"""
	from container_depot.container_depot import notify

	if not frappe.db.exists("DocType", "Depot Notification Rule"):
		return  # first migrate of this release; the next one seeds it

	for event_key, label, description, roles in NOTIFICATION_RULES:
		if frappe.db.exists("Depot Notification Rule", event_key):
			continue
		doc = frappe.new_doc("Depot Notification Rule")
		doc.event_key = event_key
		doc.label = label
		doc.description = description
		doc.enabled = 1
		doc.channel = "Bell"
		for role in roles:
			if frappe.db.exists("Role", role):
				doc.append("roles", {"role": role})
		if not doc.roles:
			# validate() refuses an enabled rule with no recipients, and rightly so. Seed
			# it disabled rather than skipping it, so the row exists to be configured.
			doc.enabled = 0
		doc.insert(ignore_permissions=True)

	settings = frappe.get_single("Depot Notification Settings")
	if not settings.fallback_roles:
		for role in NOTIFICATION_FALLBACK_ROLES:
			if frappe.db.exists("Role", role):
				settings.append("fallback_roles", {"role": role})
		if settings.get("notifications_enabled") is None:
			settings.notifications_enabled = 1
		settings.save(ignore_permissions=True)

	notify.clear_rule_cache()
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
