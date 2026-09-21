// The row form behind a NON-editable grid (`editable_grid: 0`), tidied the same way on every
// depot order that uses one — Service & Parts on the M&R, Metode Cleaning on the Cleaning
// Order. A line on those grids is filled in a SEQUENCE (item, then qty, then the numbers the
// item seeds) and the grid can only ever show a few columns at once, so a click on a row
// opens its own form, where the whole line is visible in the order it is meant to be filled.
//
// Two edits to what Frappe gives that form:
//
//  1. Insert Above / Insert Below (and the footer's second "Insert Below") go. A line's
//     position in an estimate carries no meaning — nothing sorts, prices or bills by idx —
//     so they are three buttons that only add ways to misfire next to Delete. Adding a line
//     stays one road, the grid's own "Add Row".
//  2. A labelled "Tutup" button. The form's own close control is an icon-only chevron in the
//     corner of the heading, which reads as "collapse" rather than "done with this line".
//
// It ONLY closes. There is deliberately no Save: every field writes straight into the parent
// document as it is typed, so a closed row has lost nothing, and what puts it in the database
// is the order's own Save — one press at the end, not one per line.
frappe.provide('container_depot');

// Call from the grid's `<fieldname>_on_form_rendered` handler. Re-run on every render because
// the toolbar is rebuilt with the form; the button guards itself by class so a second render
// never stacks two.
container_depot.grid_row_form = function (frm, fieldname) {
	const field = frm.fields_dict[fieldname];
	const grid_form = field && field.grid && field.grid.open_grid_row;
	if (!grid_form) return;
	grid_form.wrapper.find('.grid-insert-row, .grid-insert-row-below, .grid-append-row').remove();
	const actions = grid_form.wrapper.find('.grid-form-heading .row-actions');
	if (!actions.length || actions.find('.oak-row-close').length) return;
	$(`<button class="btn btn-primary btn-sm pull-right oak-row-close">${__('Tutup')}</button>`)
		.prependTo(actions)
		.on('click', () => {
			grid_form.row.toggle_view(false);
			// Swallow the click. The heading this button sits in carries a handler of its own
			// that TOGGLES the row, so a bubbling click reopens what was just closed — which
			// is why every native button in this toolbar returns false too.
			return false;
		});
};
