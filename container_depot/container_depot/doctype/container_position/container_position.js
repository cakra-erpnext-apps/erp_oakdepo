// Container Position — Desk form.
// Render the position photos (an "Attach Image" child table that only shows file
// links in the grid) as an inline, click-to-enlarge thumbnail gallery.

frappe.ui.form.on("Container Position", {
	refresh(frm) {
		// Retired tanks (Active off) are out of the fleet and never offered.
		frm.set_query("container", () => ({ filters: { is_active: 1 } }));
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
		.map((r) => {
			const url = frappe.utils.escape_html(r.photo);
			const note = frappe.utils.escape_html(r.caption || "");
			return `<div style="width:120px;">
					<a href="${url}" target="_blank" rel="noopener"
						style="display:block;width:120px;height:120px;border:1px solid var(--border-color);
						border-radius:8px;overflow:hidden;background:var(--control-bg);">
						<img src="${url}" style="width:100%;height:100%;object-fit:cover;" loading="lazy" />
					</a>
					${
						note
							? `<div title="${note}" style="margin-top:2px;font-size:var(--text-xs);
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
}
