// Container Position — Desk form.
// Render the position photos (an "Attach Image" child table that only shows file
// links in the grid) as an inline, click-to-enlarge thumbnail gallery.

frappe.ui.form.on("Container Position", {
	refresh(frm) {
		// Retired tanks (Active off) are out of the fleet and never offered.
		frm.set_query("container", () => ({ filters: { is_active: 1 } }));
		if (!frm.is_new() && (frm.doc.position_photos || []).length) {
			frm.add_custom_button(__('Download Foto'), () => container_depot.download_doc_photos('Container Position', frm.doc.name));
		}
		render_photo_gallery(frm);
	},
});

frappe.ui.form.on("Container Position Photo", {
	photo(frm) {
		render_photo_gallery(frm);
	},
	caption(frm) {
		render_photo_gallery(frm);
	},
	position_photos_remove(frm) {
		render_photo_gallery(frm);
	},
});

function render_photo_gallery(frm) {
	const field = frm.fields_dict.photos_preview;
	if (!field) return;

	const rows = (frm.doc.position_photos || []).filter((r) => r.photo);
	if (!rows.length) {
		field.$wrapper.empty();
		return;
	}

	// Keterangan foto ikut tercetak di bawah petaknya: yang mengetiknya berdiri di depan tank
	// ("di bawah pipa, deret kedua"), dan letak itulah yang dicari pembacanya — `location_note`
	// milik SELURUH pembacaan, bukan milik satu frame.
	const thumbs = rows
		.map((r, i) => {
			const url = frappe.utils.escape_html(r.photo);
			const note = frappe.utils.escape_html(r.caption || "");
			const time_raw = r.timestamp || r.creation;
			const time_str = time_raw ? frappe.datetime.str_to_user(time_raw) : "";
			return `<div style="width:130px;">
					<a href="${url}" target="_blank" rel="noopener"
						style="display:block;width:130px;height:130px;border:1px solid var(--border-color);
						border-radius:8px;overflow:hidden;background:var(--control-bg);position:relative;">
						<img src="${url}" style="width:100%;height:100%;object-fit:cover;" loading="lazy" />
					</a>
					<div style="display:flex;justify-content:space-between;align-items:center;margin-top:3px;">
						<span style="font-size:var(--text-xs);color:var(--text-muted);">${frappe.utils.escape_html(time_str)}</span>
						<a href="javascript:void(0)" class="oak-pos-dl" data-url="${url}" data-name="pos_${i + 1}" title="${__('Download Foto')}" style="color:var(--text-muted);font-size:12px;padding:2px;">
							<i class="fa fa-download"></i>
						</a>
					</div>
					${
						note
							? `<div title="${note}" style="margin-top:1px;font-size:var(--text-xs);
								color:var(--text-muted);white-space:nowrap;overflow:hidden;
								text-overflow:ellipsis;">${note}</div>`
							: ""
					}
				</div>`;
		})
		.join("");

	field.$wrapper.html(
		`<div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:4px;">${thumbs}</div>`
	);

	field.$wrapper.find('.oak-pos-dl').on('click', function (e) {
		e.preventDefault();
		const u = $(this).attr('data-url');
		const n = $(this).attr('data-name');
		const ext = (u || '').split('.').pop().split('?')[0] || 'jpg';
		container_depot.download_photo(u, `${frm.docname || 'pos'}_${n}.${ext}`);
	});
}
