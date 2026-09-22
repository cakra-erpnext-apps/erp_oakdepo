// Table MultiSelect fixes (Container Depot)
//
// 1. Pill tidak terhapus pada klik pertama (bug Frappe < 16.20).
// 2. Opsi dropdown kadang muncul kadang tidak (mis. "Admin Ops" pada Role Profiles).
//    Penyebab:
//    - `set_formatted_input` bawaan tidak memanggil `_update_rows(value)`, sehingga `_rows_list`
//      tetap kosong saat halaman baru dibuka, atau menyimpan sisa baris dari form User sebelumnya
//      saat navigasi Desk (SPA).
//    - `custom_awesomplete_filter` hanya memeriksa `_rows_list` statis tanpa membaca live model,
//      dan tidak menyaring input teks secara client-side.

(function () {
	const Control = frappe.ui?.form?.ControlTableMultiSelect;
	if (!Control) return;

	// -----------------------------------------------------------------------------------
	// 1. Backport perbaikan penghapusan pill untuk versi < 16.20
	if (!/type="button"/.test(Control.prototype.get_pill_html.toString())) {
		const get_pill_html = Control.prototype.get_pill_html;
		Control.prototype.get_pill_html = function (value) {
			return get_pill_html
				.call(this, value)
				.replace("<button class=", '<button type="button" class=');
		};

		const make_input = Control.prototype.make_input;
		Control.prototype.make_input = function () {
			make_input.call(this);

			this.$input_area.off("click", ".btn-remove");
			this.$input_area.on("click", ".btn-remove", (e) => {
				e.preventDefault();
				e.stopPropagation();

				const $value = $(e.currentTarget).closest(".tb-selected-value");
				const value = decodeURIComponent($value.data().value);
				const link_field = this.get_link_field();
				const current_rows = this._get_rows() || [];
				const removed_row = current_rows.find((row) => row[link_field.fieldname] === value);
				const rows = current_rows.filter((row) => row[link_field.fieldname] !== value);

				if (!this.frm) {
					this._update_rows(rows);
					this.set_model_value(rows);
					return;
				}

				if (removed_row) {
					frappe.run_serially([
						() => {
							return this.frm?.script_manager.trigger(
								`before_${this.df.fieldname}_remove`,
								this.df.options,
								removed_row.name
							);
						},
						() => {
							frappe.model.clear_doc(this.df.options, removed_row.name);

							this.frm?.dirty();
							this.refresh();

							return this.frm?.script_manager.trigger(
								`${this.df.fieldname}_remove`,
								this.df.options,
								removed_row.name
							);
						},
					]);
				}
				this._update_rows(rows);
			});
		};
	}

	// -----------------------------------------------------------------------------------
	// 2. Sinkronisasi rows dan live filter untuk Table MultiSelect
	const original_set_formatted_input = Control.prototype.set_formatted_input;
	Control.prototype.set_formatted_input = function (value) {
		this._update_rows(value || []);
		original_set_formatted_input.call(this, value);
	};

	Control.prototype.custom_awesomplete_filter = function (awesomplete) {
		const me = this;
		awesomplete.filter = function (item, input) {
			const rows = me.get_model_value() || me.rows || [];
			const link_field = me.get_link_field();
			const link_fieldname = link_field?.fieldname;
			const current_values = link_fieldname
				? rows.map((r) => r[link_fieldname])
				: me._rows_list || [];

			if (current_values.includes(item.value)) {
				return false;
			}

			if (input && me.input_matches_item) {
				return me.input_matches_item(input.trim().toLowerCase(), item);
			}

			return true;
		};
	};
})();

// ---------------------------------------------------------------------------------------
// 3. Tombol "Add Roles" pada pop up "No Roles Specified"
//
// Saat membuat User baru tanpa role, Frappe menampilkan msgprint peringatan dengan
// primary_action client_action ("frappe.set_route").
// Masalah:
// - Handler client_action bawaan Frappe tidak memanggil `frappe.hide_msgprint()`, sehingga
//   dialog modal tetap menutup layar setelah tombol diklik.
// - Jika form User sudah aktif (mis. setelah create/save user), route sudah sama persis
//   sehingga `frappe.set_route` adalah no-op dan tidak berpindah tab.
// - Form User membuka default ke tab "User Details", sementara field role profile dan roles
//   ada di tab "Roles & Permissions".
// Solusi:
// Intercept `frappe.msgprint`: tutup dialog, lalu buka tab `roles_permissions_tab` dan
// scroll ke field `role_profiles` baik saat form sudah terbuka maupun saat harus bernavigasi.
(function () {
	if (!window.frappe) return;

	function wrap_msgprint() {
		if (!frappe.msgprint || frappe.msgprint.__depot_wrapped) return;

		const original_msgprint = frappe.msgprint;
		frappe.msgprint = function (msg, ...rest) {
			let data = msg;
			let is_parsed = false;

			if (typeof data === "string" && data.trim().startsWith("{")) {
				try {
					data = JSON.parse(data);
					is_parsed = true;
				} catch (e) {}
			}

			if (data && typeof data === "object" && !Array.isArray(data) && data.primary_action) {
				const pa = data.primary_action;
				const is_user_roles_prompt =
					data.title === "No Roles Specified" ||
					(window.__ && data.title === __("No Roles Specified")) ||
					(pa.client_action === "frappe.set_route" &&
						Array.isArray(pa.args) &&
						pa.args[0] === "Form" &&
						pa.args[1] === "User");

				if (is_user_roles_prompt) {
					const user_email = Array.isArray(pa.args) ? pa.args[2] : null;
					pa.client_action = null;
					pa.action = () => {
						frappe.hide_msgprint(true);

						const activate_roles = () => {
							const frm = window.cur_frm;
							if (
								frm &&
								frm.doctype === "User" &&
								(!user_email ||
									frm.docname === user_email ||
									decodeURIComponent(frm.docname || "").toLowerCase() ===
										decodeURIComponent(user_email || "").toLowerCase())
							) {
								if (!frm.scroll_to_field?.("role_profiles")) {
									frm.layout?.select_tab?.("roles_permissions_tab");
								}
								return true;
							}
							return false;
						};

						if (!activate_roles()) {
							frappe.route_options = Object.assign(frappe.route_options || {}, {
								scroll_to: "role_profiles",
							});
							if (user_email) {
								frappe.set_route("Form", "User", user_email).then(() => {
									setTimeout(activate_roles, 150);
								});
							}
						}
					};
				} else if (pa.client_action && typeof pa.client_action === "string") {
					const client_action_str = pa.client_action;
					const action_args = pa.args;
					pa.client_action = null;
					pa.action = () => {
						frappe.hide_msgprint(true);
						let parts = client_action_str.split(".");
						let obj = window;
						for (let part of parts) {
							obj = obj?.[part];
						}
						if (typeof obj === "function") {
							obj(action_args);
						}
					};
				}

				if (is_parsed) {
					msg = data;
				}
			}

			return original_msgprint.call(this, msg, ...rest);
		};

		frappe.msgprint.__depot_wrapped = true;
	}

	wrap_msgprint();
})();
