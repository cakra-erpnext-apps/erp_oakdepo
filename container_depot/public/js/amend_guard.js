// "Amend" is Frappe's undo of last resort: on a cancelled document it copies the record
// into a fresh draft stamped with `amended_from`, pointing back at the one it replaces.
//
// No Container Depot doctype has that field, and none is meant to. Undoing work here is
// each doctype's own reopen flow — Kembali ke Draft on a booking, void + reissue on a bon —
// which keeps ONE record and its history, rather than leaving a cancelled document and a
// near-identical live copy for the yard to tell apart. So the Amend button was an action
// whose only possible answer was the framework's own refusal:
//
//     "amended_from" field must be present to do an amendment.
//
// `install._ensure_docperm` takes the `amend` flag off every doctype with no `amended_from`,
// which covers every role — except Administrator, who bypasses DocPerm wholesale
// (`get_role_permissions` hands them every flag), and is exactly who meets this while
// testing. `can_amend` is the one question the toolbar asks before offering the button, on
// both paths it offers it from, so the answer goes here and covers everybody.
//
// Feature-detected, not version-checked, and not scoped to this app: a doctype that grows an
// `amended_from` gets Amend back, and one that never had it never offers a button that
// cannot work — whichever app it belongs to.
const _can_amend = frappe.ui.form.Toolbar.prototype.can_amend;
frappe.ui.form.Toolbar.prototype.can_amend = function () {
	const fields = (this.frm && this.frm.meta && this.frm.meta.fields) || [];
	if (!fields.some((df) => df.fieldname === "amended_from")) return false;
	return _can_amend.call(this);
};
