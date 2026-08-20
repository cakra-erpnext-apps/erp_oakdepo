// "Owner tank ini belum punya kontrak" — the warning every depot order form owes its user.
//
// Nothing in the depot flow blocks on a Depot Contract: a tank is imported, gated in, cleaned
// and repaired whether or not its owner has one. But the rates on those orders come from the
// owner's contract price list, so with no contract every line prices at 0 — and consolidated
// billing invoices straight off those zeros. The work gets done and silently never billed.
//
// So the forms say it out loud, once, at the top: what is missing and where to fix it.
frappe.provide('container_depot');

// `customer` = the party whose rate card prices this order (the tank OWNER on a work order,
// not the party being billed). Answers are cached on the form per customer: refresh fires
// often and the answer only changes when a contract does.
container_depot.rate_card_notice = function (frm, customer) {
	if (frm.is_new() || !customer) return;
	if (frm.__oak_rate_card && frm.__oak_rate_card.customer === customer) {
		return container_depot._paint_rate_card_notice(frm, frm.__oak_rate_card);
	}
	frappe.call({
		method: 'container_depot.container_depot.doctype.depot_contract.depot_contract.rate_card_status',
		args: { customer },
		callback(r) {
			if (!r.message) return;
			frm.__oak_rate_card = r.message;
			container_depot._paint_rate_card_notice(frm, r.message);
		},
	});
};

container_depot._paint_rate_card_notice = function (frm, status) {
	if (!status || status.ok) return;
	const esc = frappe.utils.escape_html;
	const who = esc(status.customer);
	let msg;
	if (!status.contract) {
		// Nothing agreed yet — the contract has to be made AND activated (a Draft publishes
		// no Item Prices, so it prices nothing either).
		const href = `/app/depot-contract/new?customer=${encodeURIComponent(status.customer)}`;
		msg =
			__('Owner tank <b>{0}</b> belum punya Depot Contract yang Active.', [who]) +
			' ' +
			__('Semua tarif di order ini akan 0 dan tidak bisa ditagih sampai kontraknya dibuat lalu diaktifkan.') +
			` <a href="${href}">${__('Buat Depot Contract')}</a>`;
	} else {
		// Agreed, but the tariff is empty — the published price list has no Item Prices.
		const href = `/app/depot-contract/${encodeURIComponent(status.contract)}`;
		msg =
			__('Kontrak <b>{0}</b> aktif tapi belum menerbitkan tarif apa pun.', [esc(status.contract)]) +
			' ' +
			__('Isi Tariff Lines-nya, lalu simpan — tanpa itu setiap baris order harganya 0.') +
			` <a href="${href}">${__('Buka kontrak')}</a>`;
	}
	// Replaces whatever headline was set before it: a missing rate card is the most
	// actionable thing on the form, and the layout shows one message at a time.
	frm.dashboard.add_comment(msg, 'red', true);
};
