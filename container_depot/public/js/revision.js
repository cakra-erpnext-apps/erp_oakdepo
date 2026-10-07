// container_depot.revision — Revisi Data on the Desk form of a finished order.
//
// The server half is container_depot/revision.py: one save, no "sedang direvisi" state, the
// status and every other document left as they are, refused once the order is invoiced. This
// half offers it: "Revisi Data" opens the finished form for editing IN THE BROWSER only — the
// record itself stays finished, and nothing on the server marks it — and Save/Update then goes
// to revision.save_revision instead of Frappe's own save, which would refuse a finished doc.
// Reloading the form without saving drops the edit, exactly like any form: the mode is tied to
// the loaded copy of the document (__last_sync_on), not to anything stored.
//
// Also "Tolak Revisi" for a pending Ajukan Revisi, and the banner saying where things stand.
// And "Tolak Review" (reject_review_button) for work the field sent for review.
//
// Each doctype's refresh calls container_depot.revision.setup(frm, { locked, unlock }):
//   locked  — fieldnames the form must keep read-only (mirror of the module's REVISION_LOCKED;
//             the server is the rule, this only keeps the form from offering them)
//   unlock  — optional fn(frm) for a doctype whose finished form is locked by hand (the
//             non-submittable Repair Order); a submitted doctype needs none.
//   rowLocked — optional child-table fieldnames to keep read-only in the grids (Survey Order:
//             the tank on a row is not the revision's to change).
frappe.provide('container_depot');

container_depot.revision = {
	setup(frm, opts = {}) {
		const st = (frm.doc.__onload || {}).revision_state;
		if (!st || frm.is_new()) {
			container_depot.form_message(frm, 'revision', '');
			return;
		}
		const editing = this._editing(frm);
		let msg = '';
		if (st.locked) {
			msg = __('Terkunci: order ini sudah diinvoice ({0}). Batalkan invoice-nya dulu, atau keluarkan order ini dari invoice.', [st.locked]);
		} else if (editing) {
			msg = __('Revisi Data — ubah isian lalu Simpan. Status order dan dokumen lain tidak ikut berubah.');
		} else if (st.requested) {
			msg = __('Revisi diminta') + (st.note ? ': ' + st.note : '');
		}
		container_depot.form_message(frm, 'revision', msg, st.locked ? 'red' : 'orange');
		if (st.can_revise && editing) {
			this._unlock(frm, opts);
		} else if (st.can_revise && !st.locked) {
			frm.add_custom_button(__('Revisi Data'), () => {
				frm.__revising = frm.doc.__last_sync_on;
				frm.refresh();
			});
		}
		// can_answer: the right alone — a booking before its bon is answered by Kembali ke
		// Draft, not by Revisi Data, but may still be turned down.
		if ((st.can_answer ?? st.can_revise) && st.requested) {
			frm.add_custom_button(__('Tolak Revisi'), () =>
				frappe.prompt(
					{ fieldname: 'reason', fieldtype: 'Small Text', label: __('Alasan'), reqd: 1 },
					(v) =>
						frappe.call({
							method: 'container_depot.container_depot.revision.reject',
							args: { doctype: frm.doctype, name: frm.doc.name, reason: v.reason },
							freeze: true,
							callback() {
								frappe.show_alert({ message: __('Revisi ditolak'), indicator: 'orange' });
								frm.reload_doc();
							},
						}),
					__('Tolak Revisi'),
					__('Tolak')
				)
			);
		}
	},

	// "Tolak Review": an order the field sent for review goes back to work, with a reason
	// (revision.reject_review — Cleaning / M&R to Dikerjakan, EIR to Draf). `allowed` mirrors
	// the server's right (revision.has_right); the server checks it again.
	reject_review_button(frm, allowed) {
		if (!allowed || frm.is_new() || frm.doc.docstatus !== 0 || frm.doc.status !== 'Pending Review') return;
		frm.add_custom_button(__('Tolak Review'), () =>
			frappe.prompt(
				{ fieldname: 'reason', fieldtype: 'Small Text', label: __('Alasan'), reqd: 1 },
				(v) =>
					frappe.call({
						method: 'container_depot.container_depot.revision.reject_review',
						args: { doctype: frm.doctype, name: frm.doc.name, reason: v.reason },
						freeze: true,
						callback() {
							frappe.show_alert({ message: __('Review ditolak — order kembali dikerjakan'), indicator: 'orange' });
							frm.reload_doc();
						},
					}),
				__('Tolak Review'),
				__('Tolak')
			)
		);
	},

	_editing(frm) {
		return !!frm.__revising && frm.__revising === frm.doc.__last_sync_on;
	},

	_unlock(frm, opts) {
		const locked = opts.locked || [];
		if (opts.unlock) {
			opts.unlock(frm);
		} else {
			// Frappe leaves a field typeable on a submitted doc only when it is allow_on_submit —
			// so say so, per form, and for the grids per row copy (grid rows read
			// frappe.meta.get_docfields(child, docname)).
			frm.meta.fields.forEach((df) => {
				if (locked.includes(df.fieldname) || df.read_only || df.hidden) return;
				frm.set_df_property(df.fieldname, 'allow_on_submit', 1);
				if (df.fieldtype === 'Table') {
					frappe.meta.get_docfields(df.options, frm.doc.name).forEach((cdf) => {
						if (!(opts.rowLocked || []).includes(cdf.fieldname)) cdf.allow_on_submit = 1;
					});
				}
			});
		}
		// Every save of this form now goes through the revision endpoint: the toolbar's
		// Update / Save and Ctrl+S all land on frm.save.
		if (!frm.__plain_save) frm.__plain_save = frm.save;
		frm.save = (action, callback, btn, on_error) => {
			if (!container_depot.revision._editing(frm)) return frm.__plain_save(action, callback, btn, on_error);
			return frappe.call({
				method: 'container_depot.container_depot.revision.save_revision',
				args: { doc: frm.doc },
				freeze: true,
				freeze_message: __('Menyimpan revisi…'),
				callback() {
					frm.__revising = null;
					frappe.show_alert({ message: __('Revisi tersimpan'), indicator: 'green' });
					frm.reload_doc();
				},
				error: on_error,
			});
		};
	},
};
