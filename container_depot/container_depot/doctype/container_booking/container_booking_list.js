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
	'payment_status',
];

// One Status column, not two. A submittable doctype gets Frappe's docstatus badge
// (Draft / Submitted / Cancelled) for free, and Booking Status sat next to it repeating
// most of it — while the states the depot actually works by (Pending Payment, Blocked)
// showed up in neither. Teaching the indicator to read booking_status collapses them.
const STATUS_COLOURS = {
	Draft: 'red',
	'Pending Payment': 'orange',
	'Pending Confirmation': 'orange',
	Confirmed: 'green',
	Cancelled: 'gray',
	Blocked: 'red',
};

frappe.listview_settings['Container Booking'] = {
	// booking_status is no longer a column of its own, so the list query would not fetch
	// it — and `get_indicator` would read undefined on every row and paint them all Draft.
	add_fields: ['booking_status'],
	// Frappe puts an ID box at the FRONT of the quick filters. Nobody hunts a booking by
	// its BKG number from here (the search bar and the Filter button both do it), and it
	// was the widest thing in the row.
	hide_name_filter: true,
	get_indicator(doc) {
		const status = doc.booking_status || 'Draft';
		return [__(status), STATUS_COLOURS[status] || 'gray', `booking_status,=,${status}`];
	},
	// Runs after every list load, i.e. after the filter area exists. Appending each control
	// in turn is idempotent, so re-running it on refresh cannot scramble the row.
	refresh(listview) {
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
