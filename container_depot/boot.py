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
