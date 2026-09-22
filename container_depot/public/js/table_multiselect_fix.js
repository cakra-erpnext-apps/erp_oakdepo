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
