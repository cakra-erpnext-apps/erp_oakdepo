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
