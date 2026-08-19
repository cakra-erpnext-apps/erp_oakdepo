// Facts a document fills in by itself — status, totals, the papers it came from — belong
// in the SIDEBAR, next to Created By / Last Edited By, not in a form section. None of them
// is an isian, and a section full of read-only fields reads like work waiting to be done.
//
// They are written into the very <ul> Frappe uses for "Last Edited By You / 9 minutes ago"
// (one <li> per fact, caption line then a bold value line), so they read as more of the
// same list rather than a widget bolted next to it.
//
// The fields themselves stay on the doctype (hidden): list views, standard filters and the
// server all keep reading them. This is only where a human is shown them.
frappe.provide('container_depot');

// A clickable link to another document, escaped.
container_depot.doc_link = function (doctype, name) {
	if (!name) return null;
	return `<a href="/app/${frappe.router.slug(doctype)}/${encodeURIComponent(name)}">${frappe.utils.escape_html(
		name
	)}</a>`;
};

// `facts`: [[label, value_html], …] — entries with an empty value are dropped, so a fact
// the document does not carry yet simply does not appear.
container_depot.render_system_facts = function (frm, facts) {
	const $side = frm.sidebar && frm.sidebar.sidebar;
	if (!$side) return;
	const $menu = $side.find('.sidebar-menu .modified-by').closest('ul');
	if (!$menu.length) return;
	$menu.find('.oak-system-fact').remove();
	if (frm.is_new()) return;

	const rows = (facts || []).filter(([, value]) => value);
	if (!rows.length) return;
	// Above Last Edited By / Created By: what the document says first, who touched it last.
	$(
		rows
			.map(
				([label, value]) =>
					`<li class="oak-system-fact mb-3">${label} <br> <span class="bold">${value}</span></li>`
			)
			.join('')
	).insertBefore($menu.find('.modified-by'));
};
