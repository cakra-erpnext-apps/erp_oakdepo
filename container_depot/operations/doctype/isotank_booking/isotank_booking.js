// Copyright (c) 2026, Oak Depot Team and contributors
// For license information, please see license.txt

frappe.ui.form.on('Isotank Booking', {
	refresh(frm) {
		// A confirmed booking can spawn multiple bon/voucher (Order Bongkar/Muat),
		// each carrying up to 3 of its still-pending containers.
		if (!frm.is_new() && frm.doc.booking_status === 'Confirmed') {
			frm.add_custom_button(__('Generate Bon / Order'), () => open_generate_dialog(frm));
		}
	}
});

const MAX_CONTAINERS_PER_ORDER = 3;

function open_generate_dialog(frm) {
	frappe.call({
		method: 'container_depot.api.get_booking_pending_containers',
		args: { booking: frm.doc.name },
		callback(r) {
			const pending = r.message || [];
			if (!pending.length) {
				frappe.msgprint(__('No pending containers left on this booking.'));
				return;
			}
			const is_muat = frm.doc.direction === 'Tank Out';
			const cont_by_code = {};
			pending.forEach(p => { cont_by_code[p.booking_code] = p; });

			const d = new frappe.ui.Dialog({
				title: __('Generate {0}', [is_muat ? 'Order Muat' : 'Order Bongkar']),
				fields: [
					{
						fieldname: 'codes',
						fieldtype: 'MultiSelectPills',
						label: __('Containers (max {0})', [MAX_CONTAINERS_PER_ORDER]),
						reqd: 1,
						get_data: () => pending.map(p => ({
							value: p.booking_code,
							description: `${p.container_no || p.booking_code} · ${p.status_tag || ''}`
						}))
					},
					{ fieldtype: 'Section Break', label: __('Bon') },
					{ fieldname: 'ro', fieldtype: 'Data', label: __('R/O') },
					{ fieldname: 'shipper', fieldtype: 'Link', label: __('Shipper'), options: 'Customer', default: frm.doc.customer },
					{ fieldtype: 'Column Break' },
					{ fieldname: 'tanggal', fieldtype: 'Date', label: is_muat ? __('Tgl. Muat') : __('Tgl. Bongkar') },
					is_muat
						? { fieldname: 'destination', fieldtype: 'Data', label: __('Destination') }
						: { fieldname: 'ex_vessel', fieldtype: 'Data', label: __('Ex Vessel') },
					{ fieldtype: 'Section Break', label: __('Truck & Driver') },
					{ fieldname: 'truck_plate', fieldtype: 'Data', label: __('No. Pol (Truck Plate)') },
					{ fieldname: 'angkutan', fieldtype: 'Data', label: __('Angkutan') },
					{ fieldtype: 'Column Break' },
					{ fieldname: 'driver_name', fieldtype: 'Data', label: __('Supir (Driver)') },
					{ fieldname: 'driver_phone', fieldtype: 'Data', label: __('Driver Phone') }
				],
				primary_action_label: __('Generate'),
				primary_action(values) {
					const codes = values.codes || [];
					if (codes.length < 1 || codes.length > MAX_CONTAINERS_PER_ORDER) {
						frappe.msgprint(__('Pick 1 to {0} containers.', [MAX_CONTAINERS_PER_ORDER]));
						return;
					}
					const vehicle_data = {
						ro: values.ro,
						shipper: values.shipper,
						angkutan: values.angkutan,
						tanggal: values.tanggal,
						truck_plate: values.truck_plate,
						driver_name: values.driver_name,
						driver_phone: values.driver_phone
					};
					if (is_muat) {
						vehicle_data.destination = values.destination;
						// Tank Out needs a Cleaning Certificate per container.
						collect_certs_then_generate(frm, d, codes, cont_by_code, vehicle_data);
					} else {
						vehicle_data.ex_vessel = values.ex_vessel;
						submit_generation(frm, d, codes, vehicle_data);
					}
				}
			});
			d.show();
		}
	});
}

function collect_certs_then_generate(frm, parent_dialog, codes, cont_by_code, vehicle_data) {
	const fields = [];
	codes.forEach((code, i) => {
		const p = cont_by_code[code] || {};
		fields.push({
			fieldname: `cert_${i}`,
			fieldtype: 'Link',
			options: 'Cleaning Certificate',
			label: __('Cert for {0}', [p.container_no || code]),
			reqd: 1,
			get_query: () => ({ filters: { container: p.container, docstatus: 1 } })
		});
	});
	const cd = new frappe.ui.Dialog({
		title: __('Cleaning Certificates'),
		fields,
		primary_action_label: __('Generate'),
		primary_action(values) {
			const certs = {};
			codes.forEach((code, i) => { certs[code] = values[`cert_${i}`]; });
			vehicle_data.cleaning_certificates = certs;
			cd.hide();
			submit_generation(frm, parent_dialog, codes, vehicle_data);
		}
	});
	cd.show();
}

function submit_generation(frm, dialog, codes, vehicle_data) {
	frappe.call({
		method: 'container_depot.api.generate_order_from_booking',
		args: {
			booking: frm.doc.name,
			selected_codes: JSON.stringify(codes),
			vehicle_data: JSON.stringify(vehicle_data)
		},
		freeze: true,
		freeze_message: __('Generating bon …'),
		callback(r) {
			if (r.message && r.message.success) {
				dialog.hide();
				frappe.show_alert({
					message: __('Created {0} {1}', [r.message.order_doctype, r.message.order_name]),
					indicator: 'green'
				});
				frappe.set_route('Form', r.message.order_doctype, r.message.order_name);
			}
		}
	});
}
