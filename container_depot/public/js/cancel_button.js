// One Cancel for every Container Depot form: same name, same colour, same place.
//
// The rule (user, 2026-09-23): a document is only ever Cancelled while it is still a draft
// or otherwise in flight. Once it is submitted or has reached its last status, it goes back
// through that doctype's own rollback first (Kembalikan ke Draft / Buka Lagi), because the
// rollback carries the guards a cancel does not — already billed, parts back to stock, log.
//
// So Frappe's own two ways out are taken off every Container Depot doctype here, once,
// instead of per form: the "Discard" menu item on a draft and the grey "Cancel" secondary
// action on a submitted document. Each form that may be ended puts back exactly one red
// "Cancel" through `container_depot.cancel_button`, wired to its own server call.
//
// OAK Monthly Invoice keeps Frappe's buttons: it is a billing document, not an order, and
// has no rollback of its own to send people to.
frappe.provide("container_depot");

const KEEP_NATIVE = new Set(["OAK Monthly Invoice"]);
const is_depot = (frm) =>
	frm && frm.meta && frm.meta.module === "Container Depot" && !KEEP_NATIVE.has(frm.doctype);

const _add_discard = frappe.ui.form.Toolbar.prototype.add_discard;
frappe.ui.form.Toolbar.prototype.add_discard = function () {
	if (is_depot(this.frm)) return;
	return _add_discard.call(this);
};

const _can_cancel = frappe.ui.form.Toolbar.prototype.can_cancel;
frappe.ui.form.Toolbar.prototype.can_cancel = function () {
	if (is_depot(this.frm)) return false;
	return _can_cancel.call(this);
};

// Always the FIRST custom button, whatever else the form adds before or after it — far
// from Save/Submit, so ending an order is never a slip of the thumb next to the next step.
container_depot.cancel_button = function (frm, action) {
	const btn = frm.add_custom_button(__("Cancel"), action);
	btn.removeClass("btn-default").addClass("btn-danger").prependTo(frm.page.inner_toolbar);
	return btn;
};
