// Copyright (c) 2026, Oak Depot Team and contributors
// The Generate Bon form, shared by "Generate Bon / Order" on Container Booking and by
// "Revisi Bon" on a submitted Order Bongkar / Order Muat (container_depot/bon_revision.py).
//
// A revision is the same form with the same answers and the same rules as the generate it
// corrects (user, 2026-10-07): one truck / driver / party set for the whole bon, condition
// and cargo per tank on Tank In only. The server writes each value where it really lives.

frappe.provide('container_depot');

(() => {
	const API = 'container_depot.container_depot.bon_revision';
	// Condition and cargo are asked PER TANK, not per bon: one truck can bring a clean tank and
	// a dirty one, each with its own last cargo. One slot per tank the bon can hold.
	const TANK_SLOTS = [1, 2];
	const CONDITION_OPTIONS = 'EMPTY CLEAN\nEMPTY DIRTY\nLADEN';
	// Asked once for the whole bon and written onto every tank line of it.
	const SHARED_FIELDS = ['emkl', 'shipper', 'truck_plate', 'driver', 'driver_phone', 'ro', 'remarks'];

	container_depot.bon_form = {
		MAX_TANKS: TANK_SLOTS.length,
		SHARED_FIELDS,

		// Everything below the tank picker. `out` = Tank Out (Order Muat).
		fields(out, customer) {
			return [
				...(out
					? []
					: [
						{ fieldtype: 'Section Break', label: __('Kondisi & Cargo per Tank') },
						...TANK_SLOTS.flatMap((i) => [
							...(i > 1 ? [{ fieldtype: 'Column Break' }] : []),
							{ fieldname: `tank_${i}`, fieldtype: 'HTML', hidden: 1 },
							{ fieldname: `condition_${i}`, fieldtype: 'Select', label: __('Condition'), options: CONDITION_OPTIONS, hidden: 1 },
							{ fieldname: `cargo_${i}`, fieldtype: 'Link', label: __('Cargo'), options: 'Cargo', hidden: 1 },
						]),
					]),
				{ fieldtype: 'Section Break', label: __('Detail (auto-isi dari container pertama)') },
				// Required set mirrors the PWA gate form (GateEntry.vue vehicleFields):
				// truck/driver/phone identify the truck on the bon, so a voucher without
				// them is not usable at the gate. The two paths generate the same document
				// and must not disagree on what is mandatory.
				...(out
					? [
						{ fieldname: 'destination', fieldtype: 'Data', label: __('Destination') },
						{ fieldname: 'tanggal_muat', fieldtype: 'Date', label: __('Tgl. Muat'), default: frappe.datetime.get_today() },
					]
					: [
						// Actual unload date for the bon — today, not the Plan Date: it becomes the
						// line's realisation, and the Plan Date is only the estimate.
						{ fieldname: 'tanggal_bongkar_actual', fieldtype: 'Date', label: __('Tanggal Bongkar'), default: frappe.datetime.get_today() },
					]),
				{ fieldtype: 'Column Break' },
				{ fieldname: 'truck_plate', fieldtype: 'Data', label: __('Truck Number'), reqd: 1 },
				{ fieldname: 'driver', fieldtype: 'Data', label: __('Driver'), reqd: 1 },
				{ fieldname: 'driver_phone', fieldtype: 'Data', label: __('No. HP Driver'), reqd: 1 },
				{ fieldname: 'ro', fieldtype: 'Data', label: __('RO') },
				{ fieldtype: 'Section Break', label: __('Order') },
				// Two parties, not one. EMKL / angkutan is the hauler — one company under
				// several names, which Tank Out used to ask for twice (a free-text "Angkutan"
				// beside this link) so the same company could land in two places with nothing
				// tying them together. Shipper is the factory that ordered the haul: no
				// default, because Bill To is the payer and standing it in here would print a
				// plausible wrong name on the bon. Both are auto-filled from the first picked
				// container's booking line.
				{ fieldname: 'emkl', fieldtype: 'Link', label: __('EMKL / Angkutan'), options: 'Customer', default: customer },
				{ fieldname: 'shipper', fieldtype: 'Link', label: __('Shipper'), options: 'Customer' },
				...(out ? [] : [{ fieldname: 'ex_vessel', fieldtype: 'Data', label: __('Ex Vessel') }]),
				{ fieldname: 'remarks', fieldtype: 'Small Text', label: __('Remarks') },
			];
		},

		// Show one condition/cargo slot per picked tank, headed by its container number. A slot is
		// (re)filled from the booking line only when a different tank lands in it, so a value the
		// operator changed survives picking or dropping the SECOND tank (dropping the first moves the
		// second into slot 1, which refills it from its own line).
		sync_slots(d, picked, by_value, slot_tank) {
			TANK_SLOTS.forEach((i) => {
				const no = picked[i - 1];
				const show = !!no;
				d.set_df_property(`tank_${i}`, 'hidden', show ? 0 : 1);
				d.set_df_property(`condition_${i}`, 'hidden', show ? 0 : 1);
				d.set_df_property(`condition_${i}`, 'reqd', show ? 1 : 0);
				d.set_df_property(`cargo_${i}`, 'hidden', show ? 0 : 1);
				if (!show || slot_tank[i] === no) return;
				slot_tank[i] = no;
				const line = by_value[no] || {};
				d.fields_dict[`tank_${i}`].$wrapper.html(`<p class="font-weight-bold mb-2">${frappe.utils.escape_html(no)}</p>`);
				d.set_value(`condition_${i}`, line.condition || 'EMPTY CLEAN');
				d.set_value(`cargo_${i}`, line.cargo || '');
			});
			// The section was built with every slot hidden, so the layout marked it empty and hid
			// it; set_df_property does not re-check that.
			d.refresh_sections();
		},
	};

	container_depot.revise_bon = function (frm) {
		frappe.call({
			method: `${API}.get_bon_revision`,
			type: 'GET',
			args: { doctype: frm.doctype, name: frm.docname },
			callback: ({ message: data }) => data && open(frm, data),
		});
	};

	const blank = (v) => (v === undefined || v === null || v === '' ? null : v);

	function open(frm, data) {
		const out = frm.doctype === 'Order Muat';
		const lines = data.lines;
		const tank_no = (l) => l.container_no || l.container;
		const date_key = out ? 'tanggal_muat' : 'tanggal_bongkar_actual';
		// The bon's own fields, as the generate form names them → as the bon names them.
		const header_map = out
			? { tanggal_muat: 'tanggal_muat', destination: 'destination' }
			: { tanggal_bongkar_actual: 'tanggal_bongkar', ex_vessel: 'ex_vessel' };

		// What the form opens with: the shared fields from the first tank's line, as Generate
		// fills them; the bon's date and ex-vessel / destination from the bon.
		const first = lines[0] || {};
		const start = Object.fromEntries(SHARED_FIELDS.map((f) => [f, first[f] || '']));
		Object.entries(header_map).forEach(([key, field]) => { start[key] = data.header[field] || ''; });

		const d = new frappe.ui.Dialog({
			title: `${__('Revisi Bon')} · ${frm.docname}`,
			size: 'large',
			fields: [
				{
					fieldname: 'tanks',
					fieldtype: 'HTML',
					options: `<p class="font-weight-bold">${lines.map((l) => frappe.utils.escape_html(tank_no(l))).join(', ')}</p>`,
				},
				...container_depot.bon_form.fields(out, null),
			],
			primary_action_label: __('Simpan Revisi'),
			primary_action(values) {
				const header = {};
				Object.entries(header_map).forEach(([key, field]) => {
					if (blank(values[key]) !== blank(start[key])) header[field] = values[key] || '';
				});
				// A shared field the operator changed goes onto every tank of the bon, as on Generate.
				const shared = {};
				SHARED_FIELDS.forEach((f) => {
					if (blank(values[f]) !== blank(start[f])) shared[f] = values[f] || '';
				});
				const rows = lines.map((l, i) => {
					const row = { name: l.name, ...shared };
					if (!out) {
						['condition', 'cargo'].forEach((f) => {
							const v = values[`${f}_${i + 1}`];
							if (blank(v) !== blank(l[f])) row[f] = v || '';
						});
					}
					return row;
				}).filter((r) => Object.keys(r).length > 1);
				if (!Object.keys(header).length && !rows.length) {
					frappe.show_alert({ message: __('Tidak ada yang berubah.'), indicator: 'blue' });
					return;
				}
				frappe.call({
					method: `${API}.save_bon_revision`,
					args: { doctype: frm.doctype, name: frm.docname, header, lines: rows },
					freeze: true,
					callback: () => {
						d.hide();
						frappe.show_alert({ message: __('Bon diperbarui'), indicator: 'green' });
						frm.reload_doc();
					},
				});
			},
		});
		d.set_values({ ...start, [date_key]: start[date_key] || frappe.datetime.get_today() });
		if (!out) {
			container_depot.bon_form.sync_slots(
				d, lines.map(tank_no), Object.fromEntries(lines.map((l) => [tank_no(l), l])), {}
			);
		}
		d.show();
	}

	['Order Bongkar', 'Order Muat'].forEach((doctype) =>
		frappe.ui.form.on(doctype, {
			refresh(frm) {
				if (frm.doc.docstatus !== 1) return;
				frm.add_custom_button(__('Revisi Bon'), () => container_depot.revise_bon(frm));
			},
		})
	);
})();
