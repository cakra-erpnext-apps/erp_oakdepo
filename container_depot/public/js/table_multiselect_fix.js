// Table MultiSelect: pill tidak terhapus pada klik pertama.
//
// Ini bug Frappe, bukan bug app ini. Paling terasa di form/quick entry User baru: field
// "Role Profiles" bisa diisi tapi tombol x pada pill tidak menghapus apa pun.
//
// Penyebabnya ada di `ControlTableMultiSelect.make_input`. Handler klik `.btn-remove` tidak
// memanggil `preventDefault`/`stopPropagation`, dan pill-nya dirender sebagai `<button>` tanpa
// `type`, jadi defaultnya `submit` di dalam `<form>` yang dibuat tiap kolom form
// (form/column.js). Penghapusan barisnya sendiri asinkron (`frappe.run_serially` →
// `clear_doc` → `refresh`), sehingga penanganan default klik itu balapan dengannya: nilai
// lama ditulis balik ke model dan pill muncul lagi — terlihat seperti "tidak bisa dihapus".
//
// Upstream sudah memperbaikinya di commit 9b2c57a7 ("fix: remove table multiselect pills on
// first click"), rilis v16.20.0. Bench ini masih di 16.18.3, jadi perbaikan itu di-backport
// di sini apa adanya. Begitu Frappe naik ke >= 16.20, patch ini mendeteksi sendiri bahwa
// perbaikannya sudah ada dan tidak memasang apa-apa — file boleh dihapus saat itu.

(function () {
	const Control = frappe.ui?.form?.ControlTableMultiSelect;
	if (!Control) return;

	// Feature-detect, bukan bandingkan versi: `type="button"` pada pill masuk di commit yang
	// sama dengan perbaikan handler-nya, jadi kehadirannya adalah penanda paling jujur bahwa
	// Frappe di bench ini sudah membawa perbaikan itu.
	if (/type="button"/.test(Control.prototype.get_pill_html.toString())) return;

	const get_pill_html = Control.prototype.get_pill_html;
	Control.prototype.get_pill_html = function (value) {
		return get_pill_html
			.call(this, value)
			.replace("<button class=", '<button type="button" class=');
	};

	const make_input = Control.prototype.make_input;
	Control.prototype.make_input = function () {
		make_input.call(this);

		// Lepas handler bawaan lalu pasang versi upstream yang sudah diperbaiki. Selector ini
		// hanya dipakai oleh handler tersebut, jadi tidak ada listener lain yang ikut lepas.
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
})();
