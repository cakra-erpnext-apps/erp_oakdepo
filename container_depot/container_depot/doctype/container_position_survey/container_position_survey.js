// Container Position Survey — Desk form.
// Render the position photos (an "Attach Image" child table that only shows file
// links in the grid) as an inline, click-to-enlarge thumbnail gallery.

frappe.ui.form.on("Container Position Survey", {
	refresh(frm) {
		render_photo_gallery(frm);
	},
});

frappe.ui.form.on("Container Position Survey Photo", {
	photo(frm) {
		render_photo_gallery(frm);
	},
	position_photos_remove(frm) {
		render_photo_gallery(frm);
	},
});

function render_photo_gallery(frm) {
	const field = frm.fields_dict.photos_preview;
	if (!field) return;

	const urls = (frm.doc.position_photos || []).map((r) => r.photo).filter(Boolean);
	if (!urls.length) {
		field.$wrapper.empty();
		return;
	}

	const thumbs = urls
		.map(
			(url) =>
				`<a href="${frappe.utils.escape_html(url)}" target="_blank" rel="noopener"
					style="display:inline-block;width:120px;height:120px;border:1px solid var(--border-color);
					border-radius:8px;overflow:hidden;background:var(--control-bg);">
					<img src="${frappe.utils.escape_html(url)}"
						style="width:100%;height:100%;object-fit:cover;" loading="lazy" />
				</a>`
		)
		.join("");

	field.$wrapper.html(
		`<div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:4px;">${thumbs}</div>`
	);
}
