// "Daftarkan ... baru" langsung di dalam picker, untuk akun portal customer.
//
// Frappe menaruh "Create a new <Doctype>" di daftar picker hanya kalau
// `frappe.model.can_create(doctype)` benar (controls/link.js), dan akun portal tidak punya
// izin `create` pada Customer maupun Container — memberikannya pun percuma untuk Customer:
// penanda perusahaan akun itu adalah User Permission PADA Customer, dan `has_user_permission`
// menolak dokumen yang namanya tidak disebut di permission itu, yang untuk dokumen baru
// selalu benar. Karena itu insert-nya lewat endpoint (`customer_scope.create_party` /
// `create_tank`) dan bukan quick entry bawaan.
//
// Yang tidak perlu ikut pindah ke tombol terpisah adalah PINTU MASUKNYA. `link.js` menyediakan
// `frappe.ui.form.ControlLink.link_options(control)` — baris tambahan yang ditempel ke daftar
// picker, tanpa syarat izin apa pun. Jadi aksinya duduk persis di tempat yang sama dengan
// milik orang internal: ketik nama yang belum ada, pilih baris "+ Daftarkan ... baru".
//
// Hanya untuk akun portal. Orang internal tetap memakai "Create a new" bawaan Frappe, yang
// membuka quick entry penuh — tidak ada yang dipotong dari mereka.
(function () {
	const previous = frappe.ui.form.ControlLink.link_options;

	// Field Customer yang jenis pihaknya sudah pasti dari fieldnya sendiri. Sisanya (Bill To,
	// Customer) memakai dialog dengan pilihan jenis, karena pembayar bisa siapa saja.
	const PARTY_ROLE_BY_FIELD = {
		emkl: "emkl",
		shipper: "shipper",
		surveyor: "surveyor",
	};

	const PARTY_LABEL = {
		emkl: __("EMKL / Transporter"),
		shipper: __("Shipper"),
		surveyor: __("Surveyor"),
	};

	function is_portal_account() {
		return frappe.user.has_role("Customer Desk") && !frappe.user.has_role("System Manager");
	}

	function option(label, action) {
		return {
			html:
				"<span class='link-option'>" +
				"<i class='fa fa-plus' style='margin-right: 5px;'></i> " +
				label +
				"</span>",
			label: label,
			value: "depot_create__link_option",
			action: action,
		};
	}

	function typed_name(control) {
		return (control.get_input_value() || "").trim();
	}

	function party_option(control) {
		const role = PARTY_ROLE_BY_FIELD[control.df.fieldname];
		const label = role
			? __("Daftarkan {0} baru", [PARTY_LABEL[role]])
			: __("Daftarkan pihak baru");
		return option(label, () => open_party_dialog(control, role));
	}

	function open_party_dialog(control, role) {
		const fields = [
			{
				fieldname: "customer_name",
				fieldtype: "Data",
				label: __("Nama Perusahaan"),
				reqd: 1,
				default: typed_name(control),
			},
		];
		if (!role) {
			fields.push({
				fieldname: "role",
				fieldtype: "Select",
				label: __("Jenis"),
				options: [
					{ value: "emkl", label: PARTY_LABEL.emkl },
					{ value: "shipper", label: PARTY_LABEL.shipper },
					{ value: "surveyor", label: PARTY_LABEL.surveyor },
				],
				default: "emkl",
				reqd: 1,
			});
		}
		const d = new frappe.ui.Dialog({
			title: __("Tambah Pihak"),
			fields: fields,
			primary_action_label: __("Simpan"),
			primary_action(values) {
				frappe.call({
					method: "container_depot.customer_scope.create_party",
					args: { customer_name: values.customer_name, role: role || values.role },
					freeze: true,
					callback(r) {
						if (!r.message) return;
						d.hide();
						control.set_value(r.message.name);
						frappe.show_alert({
							message: __("{0} ditambahkan.", [r.message.customer_name]),
							indicator: "green",
						});
					},
				});
			},
		});
		d.show();
	}

	function open_tank_dialog(control) {
		const frm = control.frm;
		const d = new frappe.ui.Dialog({
			title: __("Daftarkan Tank Baru"),
			fields: [
				{
					fieldname: "container_no",
					fieldtype: "Data",
					label: __("Nomor Container"),
					reqd: 1,
					default: typed_name(control).toUpperCase(),
					description: __(
						"Tank yang belum pernah masuk depo. Yang sudah ada, pilih saja dari daftar."
					),
				},
			],
			primary_action_label: __("Daftarkan"),
			primary_action(values) {
				frappe.call({
					method: "container_depot.customer_scope.create_tank",
					args: {
						container_no: values.container_no,
						principal: frm && frm.doc ? frm.doc.principal : null,
					},
					freeze: true,
					callback(r) {
						if (!r.message) return;
						d.hide();
						control.set_value(r.message.name);
						frappe.show_alert({
							message: __("{0} didaftarkan.", [r.message.name]),
							indicator: "green",
						});
					},
				});
			},
		});
		d.show();
	}

	frappe.ui.form.ControlLink.link_options = function (control) {
		// Dirantai, bukan ditimpa: `link_options` cuma satu slot untuk seluruh site.
		const inherited = (previous && previous(control)) || [];
		if (!is_portal_account() || !control || control.df.only_select) return inherited;

		const doctype = control.get_options && control.get_options();
		if (doctype === "Customer") return inherited.concat(party_option(control));
		if (doctype === "Container") return inherited.concat(option(__("Daftarkan tank baru"), () => open_tank_dialog(control)));
		return inherited;
	};
})();
