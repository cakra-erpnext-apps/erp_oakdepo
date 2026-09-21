import frappe

# Roles that always see the full desk app switcher (never trimmed).
_UNRESTRICTED = {"Administrator", "System Manager", "Workspace Manager"}


def prune_app_switcher(bootinfo):
	"""Hide desk app-switcher entries the user can't actually use.

	Frappe's ``load_desktop_data`` lists an app in ``bootinfo.app_data`` even when
	the user can see ZERO of that app's workspaces — it only honours each app's
	``add_to_apps_screen`` ``has_permission`` hook (and frappe itself has none).
	So an Employee-only user with every module blocked still sees
	Framework / Raven / Frappe HR / etc. in the switcher: present but unusable,
	which confuses users.

	We trim ``app_data`` to apps exposing at least one workspace the user can see
	— the same visibility the left sidebar already computes (blocked modules +
	workspace roles + domains). Admins (System / Workspace Manager) keep the full
	list. Wired via the ``extend_bootinfo`` hook, which runs after the app list is
	built.
	"""
	app_data = bootinfo.get("app_data")
	if not app_data:
		return
	if _UNRESTRICTED & set(frappe.get_roles()):
		return
	bootinfo.app_data = [app for app in app_data if app.get("workspaces")]


def expose_finance_switch(bootinfo):
	"""Publish the finance master switch to the desk client.

	Forms need it to decide whether to offer a billing button at all. Reading it from
	boot rather than per-form keeps it to one query per session, and means a form can
	never disagree with the server guard it is mirroring (container_depot.finance).
	"""
	from container_depot import finance

	bootinfo.depot_finance_enabled = 1 if finance.is_enabled() else 0


def expose_user_list_block(bootinfo):
	"""Beri tahu klien kalau akun ini tidak boleh membuka DAFTAR User.

	Servernya sudah menolak (``container_depot.user_directory.user_query``), tapi list view
	menjawab 403 dengan kerangka halaman yang menggantung di "Refreshing…". Flag ini yang
	dipakai ``user_list.js`` untuk menggambar "Not Permitted" sebelum permintaannya berangkat.

	Tidak bisa dibaca dari `frappe.boot.user.can_read` di klien: daftar itu ikut memuat
	doctype yang izinnya cuma `select`, jadi User selalu ada di sana.
	"""
	bootinfo.depot_block_user_list = 1 if frappe.only_has_select_perm("User") else 0


def patch_workspace_sidebar_can_read():
	"""Backport satu `return` yang hilang di Frappe, yang mengosongkan sidebar kiri.

	`WorkspaceSidebar.__init__` mengisi daftar doctype yang boleh dibaca lewat::

	    self.can_read = self.get_cached("user_perm_can_read", self.get_can_read_items)

	tapi salinan `get_can_read_items` di kelas itu MEMBANGUN izinnya lalu tidak
	mengembalikan apa pun — kembarannya di `desk/desktop.py` mengembalikan
	`self.user.can_read`, dan keduanya memakai kunci cache yang sama. Akibatnya
	`self.can_read` bernilai None, dan `is_item_allowed` menguji
	`name in (self.can_read or [])`, jadi **setiap item ber-type DocType disembunyikan**
	dari semua orang kecuali Administrator (yang di-short-circuit di baris pertama).

	Gejalanya menyesatkan karena tidak konsisten: kunci cache-nya dipakai bersama, jadi
	begitu sebuah workspace dibuka lewat jalur `desktop.py`, cache-nya terisi daftar yang
	benar dan sidebar berikutnya tampil normal. Yang selalu kena justru boot pertama
	(`frappe/boot.py` membangun sidebar sebelum workspace mana pun dibuka) — persis saat
	orang mencari menunya dan menyimpulkan "izinnya belum ada".

	Dipasang sebagai monkey patch di app ini, bukan suntingan di core: aturan repo melarang
	menyentuh berkas frappe/erpnext (lihat STRUCTURE.md), dan app ini memang sudah
	memuat beberapa backport perbaikan Frappe lain lewat `app_include_js`. Idempoten, dan
	tidak ada cache yang perlu dibuang: `get_cached` menyimpan None dan membacanya sebagai
	"belum ada", jadi nilai basi itu tidak pernah ikut terpakai.
	"""
	try:
		from frappe.desk.doctype.workspace_sidebar.workspace_sidebar import WorkspaceSidebar

		if getattr(WorkspaceSidebar.get_can_read_items, "_cd_patched", False):
			return

		def get_can_read_items(self):
			if not self.user.can_read:
				self.user.build_permissions()
			return self.user.can_read

		get_can_read_items._cd_patched = True
		WorkspaceSidebar.get_can_read_items = get_can_read_items
	except Exception:
		# Sidebar yang kosong jauh lebih baik daripada request yang mati.
		frappe.log_error("patch_workspace_sidebar_can_read failed")


def warm_domain_restricted_caches():
	"""Prevent a Frappe desk-boot crash on the Workspace Sidebar.

	``WorkspaceSidebar.__init__`` reads the ``domain_restricted_pages`` /
	``domain_restricted_doctypes`` caches WITHOUT the lazy-build fallback that
	``desk/desktop.py`` uses. When those caches are empty (e.g. right after a
	``bench clear-cache`` / migrate) AND the user has no allowed workspaces — so
	``get_workspace_sidebar_items`` never builds them — ``is_item_allowed`` does
	``name in None`` and the whole boot dies with SessionBootFailed.

	Wired as a ``before_request`` hook (runs before ``get_bootinfo``), so the
	values are always a list, never None. Cheap when warm (a single cache read);
	only rebuilds right after a cache clear. Defensive: never let this break a
	request — a failure just leaves the original (visible) boot behaviour.
	"""
	try:
		from frappe.cache_manager import (
			build_domain_restricted_doctype_cache,
			build_domain_restricted_page_cache,
		)

		if frappe.cache.get_value("domain_restricted_doctypes") is None:
			build_domain_restricted_doctype_cache()
		if frappe.cache.get_value("domain_restricted_pages") is None:
			build_domain_restricted_page_cache()
	except Exception:
		frappe.log_error("warm_domain_restricted_caches failed")


def prune_empty_sidebar_sections(bootinfo):
	"""Drop left-sidebar section headers whose every item was filtered away.

	`frappe.boot.get_sidebar_items` appends a Section Break unconditionally — the
	permission test it runs on every other item is explicitly skipped for them
	(``item.type == "Section Break" or sidebar_doc.is_item_allowed(...)``). So a role that
	may read two doctypes out of forty still gets all eleven headings: "Pekerjaan Depo",
	"Invoicing & Pembayaran", "Sparepart & Stock" — each one now a label with nothing
	under it. A customer account, which may read six, sees more headings than links.

	A heading that opens onto nothing is not a smaller menu, it is a menu that lies about
	what the account can do. This keeps a Section Break only when at least one real item
	follows it before the next one.

	Wired through `extend_bootinfo`, which runs after the sidebar is built, and applies to
	every role — the yard and the office have the same empty headings today.
	"""
	sidebars = bootinfo.get("workspace_sidebar_item")
	if not sidebars:
		return
	try:
		for sidebar in sidebars.values():
			items = sidebar.get("items") or []
			keep, section = [], None
			for item in items:
				if item.get("type") == "Section Break":
					section = item
					continue
				if section is not None:
					keep.append(section)
					section = None
				keep.append(item)
			sidebar["items"] = keep
	except Exception:
		# A sidebar with dead headings beats a boot that fails.
		frappe.log_error("prune_empty_sidebar_sections failed")


def patch_workspace_url_shortcuts():
	"""Hide URL shortcut tiles from customer accounts.

	`Workspace.is_item_allowed` waves through every shortcut whose type is URL — there is
	no role or permission on a `Workspace Shortcut` row to test (the child doctype has
	`restrict_to_domain` and nothing else). The one on the Container Depot workspace is
	"Download App", the APK share page for the yard PWA, and a customer account holds no
	`Depot PWA` role: the tile hands them an installer for an app that refuses them at the
	door.

	Scoped to accounts with a Customer User Permission, so the yard and the office keep the
	button. A monkey patch for the same reason as `patch_workspace_sidebar_can_read`: the
	repo does not edit frappe/erpnext, and Frappe exposes no hook here. Idempotent.
	"""
	try:
		from frappe.desk.desktop import Workspace

		from container_depot.customer_scope import get_user_customers

		if getattr(Workspace.is_item_allowed, "_cd_patched", False):
			return

		original = Workspace.is_item_allowed

		def is_item_allowed(self, name, item_type):
			if (item_type or "").lower() == "url" and get_user_customers():
				return False
			return original(self, name, item_type)

		is_item_allowed._cd_patched = True
		Workspace.is_item_allowed = is_item_allowed
	except Exception:
		frappe.log_error("patch_workspace_url_shortcuts failed")


def patch_number_card_empty_report_list():
	"""Stop the Number Card list from dying for an account that may run NO report.

	`number_card.get_permission_query_conditions` builds its filter with
	``nc.report_name.isin(get_allowed_report_names())`` and never checks the set for
	emptiness — pypika renders `IN ()`, and MariaDB answers::

	    (1064, "You have an error in your SQL syntax ... near '))'")

	Every dashboard the account opens then 500s. Its sibling in `dashboard_chart.py` gets
	this right (`if allowed_reports:`), so it is the one function, not the pattern.

	Nobody hit it before because every depot role can run something. A customer account
	can run nothing at all, by design: it holds no `report` permission, so the Report
	doctype is closed to it (container_depot/customer_scope.py) and the allowlist comes
	back empty.

	The fix is to hand that function a name no report will ever have instead of an empty
	set — `IN ('...')` is valid SQL and matches nothing, which is exactly the intent. Only
	the copy imported into `number_card` is rebound; `frappe.boot` keeps its own.
	"""
	try:
		from frappe.boot import get_allowed_report_names
		from frappe.desk.doctype.number_card import number_card

		if getattr(number_card.get_allowed_report_names, "_cd_patched", False):
			return

		def _non_empty_report_names(*args, **kwargs):
			return get_allowed_report_names(*args, **kwargs) or {"__container_depot_no_report__"}

		_non_empty_report_names._cd_patched = True
		number_card.get_allowed_report_names = _non_empty_report_names
	except Exception:
		frappe.log_error("patch_number_card_empty_report_list failed")


def patch_query_report_customer_scope():
	"""Refuse a customer account any report outside ``customer_scope.CUSTOMER_REPORTS``.

	`permission_query_conditions` on `Report` decides which links the menus DRAW; it has no
	say over `/api/method/frappe.desk.query_report.run`, which fetches the report with
	`frappe.get_doc` (no read check) and then asks only two questions: does the report list
	roles (`Report.is_permitted` — these do not), and does the user hold `report` on the ref
	doctype. A customer holds it on `Container Booking`, and four reports hang off that one
	doctype — two of which build raw SQL nothing in customer_scope can filter.

	`get_report_doc` is the single gate every run, export and prepared-report path in
	`frappe.desk.query_report` goes through, so the allowlist is held there once instead of
	at each caller. A monkey patch for the same reason as the others in this file: the repo
	does not edit frappe/erpnext, and Frappe exposes no hook on this path. Idempotent.
	"""
	try:
		from frappe import _
		from frappe.desk import query_report

		from container_depot.customer_scope import CUSTOMER_REPORTS, get_user_customers

		if getattr(query_report.get_report_doc, "_cd_patched", False):
			return

		original = query_report.get_report_doc

		def get_report_doc(report_name):
			if report_name not in CUSTOMER_REPORTS and get_user_customers():
				frappe.throw(
					_("You don't have access to Report: {0}").format(_(report_name)),
					frappe.PermissionError,
				)
			return original(report_name)

		get_report_doc._cd_patched = True
		query_report.get_report_doc = get_report_doc
	except Exception:
		frappe.log_error("patch_query_report_customer_scope failed")
