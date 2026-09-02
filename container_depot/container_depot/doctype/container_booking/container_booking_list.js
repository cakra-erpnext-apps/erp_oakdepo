// Copyright (c) 2026, Oak Depot Team and contributors
// For license information, please see license.txt

// The filter row and the columns say the same things in the same order.
//
// Frappe builds the two from the same doctype meta but assembles them differently: the
// columns start with the title field (Customer) and end with the auto-appended ID, while
// the filter row starts with ID and drops Customer wherever `field_order` happens to put
// it. Reading down a booking list then meant re-finding each field in a different place.
//
// The columns are the fixed side (their order is meta order, and the title/ID slots cannot
// be moved), so the filters are lined up to them here — a DOM reorder of controls Frappe
// has already rendered, not a second set of filters.
// Every quick filter is drawn this wide, so the row reads as an even strip.
const FILTER_WIDTH = 180;

// Only the four the depot actually filters by. Eight of them wrapped onto three ragged
// lines — the Data ones (Containers, ID) each drag a "≈" condition toggle along, which
// wraps on its own. Branch / Depot / Containers keep their COLUMNS and stay reachable
// through the Filter button; ID is dropped from the row entirely (hide_name_filter).
const FILTER_ORDER = [
	'customer',
	'direction',
	'booking_status', // the Status column is this field
	'bon_status',
	'payment_status',
];

// "Sudah dibonkan belum?" is the other half of a booking's state, and it is invisible on the
// booking itself — the bons live in another doctype and reach it only through Booking Codes.
// A confirmed booking whose containers have no bon yet is work nobody has started; on a list
// of forty bookings that is exactly what an operator is scanning for, so it is a pill, not a
// word: amber = nothing issued, yellow = half done, green = every container on paper.
const BON_COLOURS = {
	'Belum Dibon': 'orange',
	'Sebagian Dibon': 'yellow',
	'Bon Lengkap': 'green',
};

// One Status column, not two. A submittable doctype gets Frappe's docstatus badge
// (Draft / Submitted / Cancelled) for free, and Booking Status sat next to it repeating
// most of it — while the states the depot actually works by (Pending Payment, Blocked)
// showed up in neither. Teaching the indicator to read booking_status collapses them.
//
// Colour convention, shared by every Container Depot list: grey = draft, red =
// dibatalkan / void, blue = the terminal "confirmed / submitted" state, any other
// colour = a stage in between. Blocked is a hold, not a cancellation, so it stays out
// of red — it gets pink, which still shouts across a list.
const STATUS_COLOURS = {
	Draft: 'grey',
	'Pending Payment': 'orange',
	'Pending Confirmation': 'yellow',
	Confirmed: 'blue',
	// Every tank on it has left. Green rather than blue: Confirmed is where a booking starts
	// being work, this is where it stops being work at all.
	Completed: 'green',
	Cancelled: 'red',
	Blocked: 'pink',
};

frappe.listview_settings['Container Booking'] = {
	// booking_status is no longer a column of its own, so the list query would not fetch
	// it — and `get_indicator` would read undefined on every row and paint them all Draft.
	add_fields: ['booking_status', 'bon_status', 'bon_summary', 'direction', 'per_fulfilled'],
	formatters: {
		// How much of an outbound booking has actually left the depot. A lift-on is
		// routinely collected over several visits (a bon carries at most two tanks), so a
		// five-tank booking spends most of its life part-collected — and used to look
		// exactly like one nobody had touched. Inbound has no such measure: the tanks
		// arriving is what the EIR records, not what this column counts.
		per_fulfilled(value, df, doc) {
			if (doc.direction !== 'Tank Out') return '';
			const per = Math.min(100, Math.max(0, flt(value, 2)));
			const colour = per >= 100 ? 'bg-green-500' : per > 0 ? 'bg-yellow-500' : 'bg-gray-300';
			return `
				<div class="d-flex align-items-center" style="gap:6px">
					<span class="progress" style="height:6px;width:60px;margin:0">
						<span class="progress-bar ${colour}" style="width:${per}%"></span>
					</span>
					<span class="text-muted">${per}%</span>
				</div>`;
		},
		// The count carries the message ("2/5"), the colour makes it findable, and a booking
		// with no live codes at all (draft / cancelled) shows nothing — there is no bon owed.
		bon_status(value, df, doc) {
			if (!value) return '';
			const colour = BON_COLOURS[value] || 'gray';
			const count = doc.bon_summary ? ` ${frappe.utils.escape_html(doc.bon_summary)}` : '';
			return `<span class="indicator-pill ${colour}" title="${__('Container yang sudah masuk bon')}">${__(value)}${count}</span>`;
		},
	},
	// Container Booking is submittable, and frappe.get_indicator returns a blanket red
	// "Draft" / "Cancelled" for docstatus 0 / 2 — bailing out BEFORE get_indicator below
	// is ever called — unless these opt out of that default. Without them the booking_status
	// pill only ever showed on submitted rows. `on_cancel` writes booking_status =
	// 'Cancelled', but docstatus 2 is also handled explicitly so a stale value cannot make
	// a cancelled booking read as live.
	has_indicator_for_draft: 1,
	has_indicator_for_cancelled: 1,
	// Frappe puts an ID box at the FRONT of the quick filters. Nobody hunts a booking by
	// its BKG number from here (the search bar and the Filter button both do it), and it
	// was the widest thing in the row.
	hide_name_filter: true,
	get_indicator(doc) {
		if (doc.docstatus === 2) return [__('Cancelled'), 'red', 'docstatus,=,2'];
		const status = doc.booking_status || 'Draft';
		return [__(status), STATUS_COLOURS[status] || 'grey', `booking_status,=,${status}`];
	},
	// Runs after every list load, i.e. after the filter area exists. Appending each control
	// in turn is idempotent, so re-running it on refresh cannot scramble the row.
	refresh(listview) {
		strip_bulk_cancel(listview);
		const $form = listview.page && listview.page.page_form;
		if (!$form || !$form.length) return;
		// Prepended in REVERSE, so the row ends up in FILTER_ORDER with the filters on the
		// left and Frappe's own Filter button + sort selector left where they belong, at
		// the right end. Appending instead pushed the filters PAST those buttons.
		[...FILTER_ORDER].reverse().forEach((fieldname) => {
			const $control = $form.find(`[data-fieldname="${fieldname}"]`).closest('.frappe-control');
			if (!$control.length) return;
			$control.prependTo($form);
			// One width for all of them. Frappe sizes each control to its own label, so
			// eight filters wrapped onto two ragged lines with nothing lining up; a fixed
			// width turns the wrap into a grid — the second row sits under the first.
			$control.css({
				width: `${FILTER_WIDTH}px`,
				'min-width': `${FILTER_WIDTH}px`,
				'max-width': `${FILTER_WIDTH}px`,
			});
			$control.find('.form-control, .awesomplete').css({ width: '100%', 'max-width': '100%' });
		});
	},
};

// Actions -> Cancel can only fail from here, whichever rows are ticked. A draft is voided
// through the booking's own Cancel button (`void_draft` — the native cancel cannot touch a
// docstatus 0 record anyway), and a submitted booking refuses cancel outright
// (`before_cancel`: the way back is Kembali ke Draft, then cancelling the draft). Bulk
// "Cancel 3 documents?" therefore ends in three errors, so the item goes — the same strip
// the form does on its Menu (container_booking.js, _lock_actions).
function strip_bulk_cancel(listview) {
	const $actions = listview.page && listview.page.actions;
	if (!$actions || !$actions.length) return;
	// Frappe labels this one with a translation CONTEXT, which can resolve to a different
	// string than a bare __('Cancel') on a translated Desk. Match both.
	[__('Cancel'), __('Cancel', null, 'Button in list view actions menu')].forEach((label) => {
		$actions.find(`a[data-label="${encodeURIComponent(label)}"]`).parent().remove();
	});
}
