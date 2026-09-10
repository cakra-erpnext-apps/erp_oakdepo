// Container list view.
//
// `Container.status` stores machine values (Booked / In_Depot / Available / Gate_Out) that
// the whole app branches on, so they are NOT renamed — they are only ever *rendered*
// differently. Left alone, Frappe prints them verbatim and the operator reads "In_Depot",
// which says where the tank is but not the thing they actually want to know: can it leave?
//
// So each status is badged with what it MEANS for the yard, in the same vocabulary the
// gate-out rules use (container_depot/container_status.py):
//
//   Booked     — reserved by an inbound booking, not physically here yet.
//   In_Depot   — here, but an order (EIR-In / Cleaning / M&R) is still open.
//   Available  — here with nothing open: free to be booked out.
//   Gate_Out   — has left.
//
// Clicking a badge filters the list to that status.
//
// A retired tank (Active off) overrides all of it: where it last stood stopped mattering
// the moment it left the fleet, and the one thing to know about the row is that it is out
// of service — otherwise a scrapped tank reads "Sudah Keluar", exactly like one that just
// drove off this morning.

// Tenggat tank ini, urut seperti `container_depot/worklist.py` mengurutkannya. Ketiganya
// distempel di master oleh `lift_on.push_to_open_orders` dari booking keluarnya.
const PRIORITY = { urgent: "target_urgent_on", survey: "target_survey_on", due: "target_lift_on" };

frappe.listview_settings["Container"] = {
	// status / is_active ditarik eksplisit supaya indicator tetap jalan waktu kolomnya
	// disetel ulang; ketiga tanggal tenggat supaya hitung mundurnya memakai tanggal yang sama
	// dengan yang dipakai worklist PWA mengurutkan pekerjaannya.
	add_fields: ["status", "is_active", ...Object.values(PRIORITY)],
	// Prioritas — dua bentuk sekaligus (lihat public/js/urgency_mark.js): pill di kolom
	// Prioritas berisi hitung mundur beserta tanggalnya, persis kosakata PWA ("MENDESAK ·
	// H-2 · 9 Sep"), bisa diklik untuk menyaring yang mendesak saja; plus awalan MENDESAK
	// pada kolom subject yang tidak pernah terpotong sesempit apa pun layarnya. Pill status
	// sengaja tidak diganggu: merah di daftar ini sudah berarti dibatalkan.
	formatters: {
		container_no(value, df, doc) {
			return container_depot.urgency_subject(value, doc, PRIORITY.urgent);
		},
		target_urgent_on(value, df, doc) {
			return container_depot.priority_pill(doc, PRIORITY);
		},
	},

	onload(listview) {
		container_depot.priority_column(listview, PRIORITY.urgent);
	},

	get_indicator(doc) {
		if (!doc.is_active) return [__("Non-Aktif"), "red", "is_active,=,0"];
		// Colour convention, shared by every Container Depot list: grey = draft,
		// red = dibatalkan / void (here: a retired tank), blue = the terminal state,
		// any other colour = a stage in between. A tank's life ends at Gate_Out, so
		// that is the blue one; grey is reserved for drafts and this doctype has none.
		const map = {
			Booked: [__("Dipesan"), "purple", "status,=,Booked"],
			// Deliberately not "In Depo": being here is not the point — the open work is.
			In_Depot: [__("Ada Pekerjaan"), "orange", "status,=,In_Depot"],
			Available: [__("Siap Keluar"), "green", "status,=,Available"],
			Gate_Out: [__("Sudah Keluar"), "blue", "status,=,Gate_Out"],
		};
		return map[doc.status] || [__(doc.status || "-"), "gray", `status,=,${doc.status || ""}`];
	},
};
