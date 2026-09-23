// Leak Check — Desk form.
// Photo grid handled like M&R's work photos (repair_order.js): a thumbnail in the row, a click
// on the row opens a carousel (‹ ›, arrow keys) where the caption and the leak flag are edited,
// with a per-photo download; "Download Foto" zips them all.

frappe.ui.form.on("Leak Check", {
	// Formatter MUST be installed in setup: form.js paints the grid before refresh fires.
	setup(frm) {
		install_leak_photo_thumbnails(frm);
	},
	refresh(frm) {
		// Retired tanks (Active off) are never offered.
		frm.set_query("container", () => ({ filters: { is_active: 1 } }));
		if (!frm.is_new() && (frm.doc.photos || []).length) {
			frm.add_custom_button(__("Download Foto"), () =>
				container_depot.download_doc_photos("Leak Check", frm.doc.name)
			);
		}
		install_leak_photo_thumbnails(frm);
		bind_leak_photo_clicks(frm);
	},
});

function leak_photo_thumbnail(value, df, options, doc) {
	if (!value) return "";
	const src = frappe.utils.escape_html(value);
	const leak = doc && doc.is_leak ? " oak-grid-photo-leak" : "";
	return `<img class="oak-grid-photo${leak}" src="${src}" data-oak-photo="${src}" loading="lazy" alt="">`;
}

function install_leak_photo_thumbnails(frm) {
	const std = (frappe.meta.docfield_map["Leak Check Photo"] || {}).photo;
	if (std) std.formatter = leak_photo_thumbnail;
	if (!frm.docname) return;
	const df = frappe.meta.get_docfield("Leak Check Photo", "photo", frm.docname);
	if (df) df.formatter = leak_photo_thumbnail;
}

// CAPTURE phase: Frappe binds click-to-edit straight on the cell, so a bubbling handler
// would fire after the inline row form had already opened under the dialog.
function bind_leak_photo_clicks(frm) {
	const grid = frm.fields_dict.photos && frm.fields_dict.photos.grid;
	const el = grid && grid.wrapper && grid.wrapper.get(0);
	if (!el || el._oakLeakPhotoBound) return;
	el._oakLeakPhotoBound = true;
	el.addEventListener(
		"click",
		(e) => {
			if (!e.target.closest) return;
			const row = e.target.closest(".grid-row[data-name]");
			if (!row || e.target.closest(".grid-row-check")) return;
			if (!e.target.closest(".grid-static-col, .btn-open-row")) return;
			// A row with no photo yet opens the normal row editor, where it gets its upload.
			const cdn = row.getAttribute("data-name");
			if (!((locals["Leak Check Photo"] || {})[cdn] || {}).photo) return;
			e.stopPropagation();
			e.preventDefault();
			open_leak_photo_carousel(frm, cdn);
		},
		true
	);
}

function open_leak_photo_carousel(frm, cdn) {
	const rows = (frm.doc.photos || []).filter((r) => r.photo);
	if (!rows.length) return;
	let idx = Math.max(0, rows.findIndex((r) => r.name === cdn));
	const editable = frappe.perm.has_perm(frm.doctype, 0, "write");
	// Guards the controls' own onchange while render() writes the next slide into them.
	let syncing = false;

	const d = new frappe.ui.Dialog({
		title: __("Foto Leak Check"),
		size: "large",
		fields: [
			{ fieldname: "viewer", fieldtype: "HTML" },
			{
				fieldname: "caption",
				fieldtype: "Data",
				label: __("Deskripsi"),
				read_only: editable ? 0 : 1,
				onchange() {
					if (syncing) return;
					const row = rows[idx];
					const value = d.get_value("caption") || "";
					if (value === (row.caption || "")) return;
					frappe.model.set_value("Leak Check Photo", row.name, "caption", value);
					frm.refresh_field("photos");
					render();
				},
			},
			{
				fieldname: "is_leak",
				fieldtype: "Check",
				label: __("Bocor?"),
				read_only: editable ? 0 : 1,
				onchange() {
					if (syncing) return;
					const row = rows[idx];
					const value = cint(d.get_value("is_leak"));
					if (value === cint(row.is_leak)) return;
					frappe.model.set_value("Leak Check Photo", row.name, "is_leak", value);
					frm.refresh_field("photos");
					render();
				},
			},
		],
	});

	if (editable) {
		d.set_primary_action(__("Simpan"), () => {
			d.hide();
			if (frm.is_dirty()) frm.save();
		});
	}

	function render() {
		const row = rows[idx];
		const url = frappe.utils.escape_html(row.photo);
		const leak = cint(row.is_leak)
			? `<span class="indicator-pill red">${__("Bocor")}</span>`
			: `<span class="indicator-pill green">${__("Aman")}</span>`;
		d.fields_dict.viewer.$wrapper.html(`
			<div class="oak-carousel">
				<button class="btn btn-default oak-carousel-nav" data-oak-step="-1"
					title="${__("Sebelumnya")}" ${idx === 0 ? "disabled" : ""}>&lsaquo;</button>
				<div class="oak-carousel-stage"><img src="${url}" alt=""></div>
				<button class="btn btn-default oak-carousel-nav" data-oak-step="1"
					title="${__("Berikutnya")}" ${idx === rows.length - 1 ? "disabled" : ""}>&rsaquo;</button>
			</div>
			<div class="oak-carousel-caption">
				<span class="oak-carousel-count">${idx + 1} / ${rows.length}</span>
				${leak}
				${row.caption ? `<span class="oak-carousel-area">${frappe.utils.escape_html(row.caption)}</span>` : ""}
			</div>
		`);
		d.$wrapper.find(".oak-carousel-nav").on("click", (e) => go(cint($(e.currentTarget).attr("data-oak-step"))));

		// "Detail Foto" = the original file in its own tab (the stage scales every photo down).
		const $open_tab = d.get_secondary_btn();
		d.set_secondary_action_label(__("Detail Foto"));
		d.set_secondary_action(() => window.open(row.photo, "_blank"));

		let $dl_btn = d.$wrapper.find(".oak-btn-download-photo");
		if (!$dl_btn.length) {
			$dl_btn = $(`<button class="btn btn-default btn-sm oak-btn-download-photo" style="margin-right: 8px;">
				<i class="fa fa-download"></i> ${__("Download Foto")}
			</button>`).insertBefore($open_tab);
		}
		$dl_btn.off("click").on("click", () => {
			const ext = row.photo.split(".").pop().split("?")[0] || "jpg";
			container_depot.download_photo(row.photo, `${frm.docname}_leak_${idx + 1}.${ext}`);
		});

		syncing = true;
		d.set_value("caption", row.caption || "");
		d.set_value("is_leak", cint(row.is_leak));
		syncing = false;
	}

	function go(step) {
		const next = idx + step;
		if (next < 0 || next >= rows.length) return;
		idx = next;
		render();
	}

	// Arrow keys, except while typing a caption.
	d.$wrapper.on("keydown", (e) => {
		if ($(e.target).is("input, textarea, select")) return;
		if (e.key === "ArrowLeft") go(-1);
		else if (e.key === "ArrowRight") go(1);
	});

	render();
	d.show();
	d.$wrapper.find(".modal-content").attr("tabindex", "-1").trigger("focus");
}
