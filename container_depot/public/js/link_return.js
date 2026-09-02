// Membuat master baru dari sebuah field Link adalah simpangan, bukan tujuan.
//
// Selama quick entry masih hidup, simpangan itu berupa modal: ada tombol tutup, dan form
// yang sedang dikerjakan tetap terlihat di belakangnya. Sejak modal itu dimatikan
// (install.PROPERTY_SETTERS — form penuh dipilih justru supaya masternya lengkap), user
// dipindahkan ke halaman lain. Yang ikut hilang bersama modal adalah tombol tutupnya:
// user yang berubah pikiran mendarat di form kosong tanpa jalan pulang selain tombol back
// browser, dan tidak ada apa pun di layar yang menyebut dia sedang di tengah pekerjaan mana.
//
// Berkas ini mengembalikan dua hal itu di setiap form master yang dibuka dengan cara
// tersebut — bukan hanya enam doctype yang quick entry-nya baru dimatikan, tapi juga yang
// memang tidak pernah punya modal (Container, Depot, Cargo, Shipping Line, dan seterusnya):
//
//   * spanduk yang menyebut field dan dokumen asalnya, supaya konteksnya tidak putus;
//   * tombol "Kembali tanpa menyimpan", padanan tombol tutup yang hilang.
//
// Keduanya dibaca dari `frappe._from_link` — catatan yang ditinggalkan link.js sebelum
// berpindah halaman, dan yang dipakai save.js (`update_calling_link`) untuk mengisi balik
// field pemanggilnya begitu master barunya disimpan.

(function () {
	const RETURN_BTN = 'oak-link-return';

	// Mirrors `is_valid_doctype()` inside save.js's own update_calling_link: which doctype
	// the calling field is actually waiting for. Any other form is not this detour.
	function awaited_doctype(from) {
		const df = from.field_obj && from.field_obj.df;
		if (!df) return null;
		if (df.fieldtype === 'Link') return df.options;
		if (df.fieldtype === 'Dynamic Link') return from.doc && from.doc[df.options];
		if (df.fieldtype === 'Table MultiSelect') return from.field_obj.get_options();
		return null;
	}

	// The document the user came from, named the way they would recognise it.
	function origin_label(from) {
		const [, doctype, docname] = from.set_route_args || [];
		if (!doctype) return null;
		// A caller that is itself unsaved carries a "new-…" placeholder instead of a name;
		// showing that string would be noise, so it is named by its doctype alone.
		const named = docname && !String(docname).startsWith('new-');
		return named
			? `${__(doctype)} <b>${frappe.utils.escape_html(docname)}</b>`
			: __('{0} baru', [__(doctype)]);
	}

	function go_back(from) {
		const back_to = from.set_route_args || [];
		// Dropped BEFORE routing, and deliberately: while the note stands, save.js writes the
		// next document saved of this doctype straight into the calling field — and the user
		// has just said that is not what they want.
		delete frappe._from_link;
		// The abandoned draft is left in `locals` on purpose. Clearing it would break the
		// browser's forward button (the route stays in history and would render a document
		// that no longer exists), and it costs nothing: the next "Create a new …" builds a
		// fresh doc rather than reusing this one. Going forward simply undoes the cancel.
		frappe.set_route(...back_to).then(() => frappe.utils.scroll_to(from.scrollY));
	}

	function paint(frm) {
		const from = frappe._from_link;
		if (!from || !frm.is_new()) return;
		// No calling FORM means nowhere to return to — the link lived in a dialog, and
		// update_calling_link skips its own return route in exactly the same case.
		if (!from.field_obj || !from.field_obj.frm) return;
		if (awaited_doctype(from) !== frm.doctype) return;

		const where = origin_label(from);
		if (!where) return;
		const df = from.field_obj.df;
		const field = frappe.utils.escape_html(__(df.label || df.fieldname));

		const html =
			__('Anda sedang membuat {0} baru untuk field <b>{1}</b> di {2}.', [
				__(frm.doctype),
				field,
				where,
			]) +
			' ' +
			__('Simpan untuk langsung mengisikannya ke sana.') +
			` <button type="button" class="btn btn-xs btn-default ml-2 ${RETURN_BTN}">` +
			`${__('Kembali tanpa menyimpan')}</button>`;

		// Safe to paint on every refresh: form.js empties the message area just before it
		// runs the client hooks, so this replaces itself instead of stacking.
		frm.layout.show_message(html, 'blue', true);
		// Namespaced and re-bound each paint — show_message rebuilds the node it lives in.
		frm.layout.message
			.off('click.oak_link_return')
			.on('click.oak_link_return', `.${RETURN_BTN}`, () => go_back(from));
	}

	// form.js fires this for every form it renders, new or saved — the one global hook that
	// saves this from having to name every master doctype the depot creates on the fly.
	$(document).on('form-refresh', (e, frm) => {
		try {
			paint(frm);
		} catch (err) {
			console.error(err);
		}
	});

	// A stale `frappe._from_link` is not harmless: it makes save.js write the next document
	// saved of that doctype into a field the user stopped caring about. Inside a modal the
	// note lived a few seconds; on a full page it would survive every click afterwards. So
	// it is dropped as soon as the user goes somewhere that is neither the master being
	// created nor the document that asked for it — leaving the back button as safe as the
	// button above it.
	frappe.router &&
		frappe.router.on('change', () => {
			const from = frappe._from_link;
			if (!from) return;
			const route = frappe.get_route() || [];
			const back_to = from.set_route_args || [];
			const slug = (v) => frappe.router.slug(String(v || ''));
			const heading_home = route[0] === back_to[0] && slug(route[1]) === slug(back_to[1]);
			const still_creating = route[0] === 'Form' && slug(route[1]) === slug(awaited_doctype(from));
			if (heading_home || still_creating) return;
			delete frappe._from_link;
		});
})();
