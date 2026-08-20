// Cleaning Order list: colour-code the lifecycle so a glance separates the three stages —
// still with Admin Ops (belum diteruskan), handed to the wash operator (menunggu), and
// being worked. The raw status codes (Service Setup / Pending / In_Progress) don't read as
// stages on their own, so each gets a clear Indonesian badge. Clicking a badge filters the
// list to that status.
//
// has_indicator_for_draft / _cancelled are REQUIRED here: Cleaning Order is submittable, and
// frappe.get_indicator returns a blanket red "Draft" for every docstatus 0 doc — bailing out
// before it ever calls get_indicator — unless these opt out of that default. Since they also
// suppress the built-in "Cancelled" badge, docstatus 2 is handled explicitly below.
// Kolom paling kiri (the "Subject") is always the doctype's `title_field`, and that is
// `container_no`: an order is looked up by the tank it is for, never by its own id. Frappe
// still appends the CO series name as an "ID" column on the far right, so nothing is lost.
// Filters above the list: Status, Container, Owner (Principal), Depot (in_standard_filter
// in cleaning_order.json).
frappe.listview_settings["Cleaning Order"] = {
	// Pull status so get_indicator always has it even when columns are customised.
	add_fields: ["status", "revision_requested"],
	has_indicator_for_draft: 1,
	has_indicator_for_cancelled: 1,
	get_indicator(doc) {
		// A cancelled document is cancelled whatever stage its status was left at.
		if (doc.docstatus === 2) {
			return [__("Dibatalkan"), "red", "docstatus,=,2"];
		}
		// A finished order the field asked to reopen (PWA "Ajukan Revisi") needs Admin Ops,
		// so it outranks the plain "Selesai" badge — otherwise the request leaves no mark
		// anywhere in the list.
		if (doc.docstatus === 1 && doc.revision_requested) {
			return [__("Revisi Diminta"), "orange", "revision_requested,=,1"];
		}
		const map = {
			// Belum diteruskan — Admin Ops masih memilih metode cleaning.
			"Service Setup": [__("Belum Diteruskan"), "orange", "status,=,Service Setup"],
			// Sudah diteruskan ke operator cuci, menunggu dikerjakan.
			Pending: [__("Menunggu Operator"), "blue", "status,=,Pending"],
			// Operator sedang mengerjakan.
			In_Progress: [__("Dikerjakan"), "yellow", "status,=,In_Progress"],
			// Selesai di lapangan, menunggu Admin Ops memeriksa lalu Submit.
			"Pending Review": [__("Menunggu Review"), "purple", "status,=,Pending Review"],
			Completed: [__("Selesai"), "green", "status,=,Completed"],
			Cancelled: [__("Dibatalkan"), "red", "status,=,Cancelled"],
		};
		return map[doc.status] || [__(doc.status), "gray", `status,=,${doc.status}`];
	},
};
