// The depot's Portal Users tab on the Customer form.
//
// ERPNext ships a "Portal Users" tab of its own — `Customer.portal_users`, child doctype
// `Portal User` — which belongs to its WEBSITE portal: a row there opens the ERPNext portal
// pages, not the Desk. This app never writes one, so that tab was empty on every customer
// while the depot's real accounts sat in `Customer Portal User`, a doctype of ours. Both
// halves of ERPNext's are hidden (install.PROPERTY_SETTERS) and this draws the real list in
// their place.
//
// A doctype of ours cannot be a child table on ERPNext's form, so the rows are fetched and
// drawn by hand. Read-only on purpose: creating an account is what grants a login, and that
// belongs on the `Customer Portal User` form where its own guards live.

// `Customer Portal User.approval_status` — its three values, no more.
const STATUS_COLOUR = { Active: 'green', Inactive: 'gray', 'Pending Approval': 'orange' };

frappe.ui.form.on('Customer', {
	refresh(frm) {
		frm.trigger('_render_oak_portal_users');
	},
	_render_oak_portal_users(frm) {
		const field = frm.get_field('oak_portal_users_html');
		if (!field) return;
		// The customer's own portal account can open this form (its own company only) and
		// holds no permission on Customer Portal User — an empty table would read as "no
		// accounts" rather than "not yours to see". Hidden through the Tab object, not
		// `set_df_property`: a Tab Break's visibility is two CSS classes the Tab owns
		// (frappe/form/tab.js `toggle`), and nothing re-reads `df.hidden` after render.
		const tab = (frm.layout.tabs || []).find(
			(t) => t.df && t.df.fieldname === 'oak_portal_users_tab'
		);
		if (frm.is_new() || !frappe.model.can_read('Customer Portal User')) {
			if (tab) tab.toggle(false);
			return;
		}
		if (tab) tab.toggle(true);
		frappe.db
			.get_list('Customer Portal User', {
				filters: { customer: frm.doc.name },
				fields: ['name', 'user', 'approval_status'],
				order_by: 'creation asc',
				limit: 100,
			})
			.then((rows) => _draw(frm, field, rows || []));
	},
});

function _draw(frm, field, rows) {
	const body = rows.length
		? rows
				.map(
					(r) => `
			<tr>
				<td><a href="/app/user/${encodeURIComponent(r.user)}">${frappe.utils.escape_html(r.user)}</a></td>
				<td><span class="indicator-pill ${STATUS_COLOUR[r.approval_status] || 'gray'}">
					${frappe.utils.escape_html(r.approval_status || '')}</span></td>
				<td class="text-right">
					<a href="/app/customer-portal-user/${encodeURIComponent(r.name)}">${__('Buka')}</a>
				</td>
			</tr>`
				)
				.join('')
		: `<tr><td colspan="3" class="text-muted">${__('Belum ada akun portal untuk customer ini.')}</td></tr>`;

	field.html(`
		<table class="table table-bordered" style="margin-bottom: 12px">
			<thead><tr>
				<th style="width: 55%">${__('User')}</th>
				<th style="width: 25%">${__('Status')}</th>
				<th></th>
			</tr></thead>
			<tbody>${body}</tbody>
		</table>
		<button class="btn btn-default btn-sm oak-add-portal-user">${__('Tambah Akun Portal')}</button>
	`);
	field.$wrapper
		.find('.oak-add-portal-user')
		.toggle(frappe.model.can_create('Customer Portal User'))
		.on('click', () => frappe.new_doc('Customer Portal User', { customer: frm.doc.name }));
}
