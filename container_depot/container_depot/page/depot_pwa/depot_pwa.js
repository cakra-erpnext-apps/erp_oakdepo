/**
 * "Depot PWA (Lapangan)" — a Desk page whose only job is to hand the user to /depot.
 *
 * Why a page at all, rather than a plain URL entry in the sidebar? Because permission.
 * Frappe's sidebar and workspace-shortcut filters wave every `URL` item through
 * unconditionally (`desk_views.py::is_item_allowed` returns True for type "url"), so a URL
 * shortcut is visible to everyone with Desk access — including office staff who would land
 * on an empty PWA. A `Page` carries a `roles` table and IS filtered, and its roles are kept
 * in step with `Role.is_depot_field_role` by install.setup_pwa_page_roles(). One permission
 * object, respected by the sidebar, the workspace shortcut and the /apps tile alike.
 *
 * The redirect is a full page load on purpose: /depot is a separate Vue app with its own
 * bundle and service worker, not a Desk route.
 */
frappe.pages["depot-pwa"].on_page_load = function (wrapper) {
	frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Depot PWA (Lapangan)"),
		single_column: true,
	});

	// Leave something on screen in case the redirect is slow or blocked, so the page is
	// never just a blank frame the user has to guess at.
	$(wrapper)
		.find(".layout-main-section")
		.html(
			`<div class="text-muted" style="padding: 2rem 0; text-align: center;">
				${__("Membuka Depot PWA…")}
			</div>`
		);

	window.location.href = "/depot";
};
