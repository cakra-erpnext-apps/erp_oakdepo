// Repair Order list view.
//
// Kolom paling kiri (the "Subject") is always the doctype's `title_field`, and that is
// `container_no`: an M&R is looked up by the tank it is for, never by its own id. Frappe
// still appends the RO series name as an "ID" column on the far right, so nothing is lost.
//
// Filters above the list are trimmed to the five the depot actually uses:
//   Container No — comes free, Frappe always offers the title_field as a standard filter
//   Status / Principal (Owner) / Depot — in_standard_filter in repair_order.json
//   Order Created — the from→to range added below
// `hide_name_filter` drops Frappe's default "ID" (RO-series) box, which nobody searches by
// now that the container number is the subject.

// Tenggat pekerjaan ini, urut seperti `container_depot/worklist.py` mengurutkannya.
const PRIORITY = { urgent: "target_urgent_on", survey: "target_survey_on", due: "target_lift_on" };

frappe.listview_settings["Repair Order"] = {
	hide_name_filter: 1,

	// status is not a column here, so the list query would not fetch it and get_indicator
	// would read undefined on every row.
	// target_survey_on bukan kolom di sini, tapi dialah tenggat sebenarnya pekerjaan ini —
	// tanpa ikut ditarik, pill prioritasnya akan menghitung mundur ke hari pickup sementara
	// PWA menghitung ke hari survey, dan satu order akan terbaca H-5 di Desk tapi H-2 di HP.
	add_fields: ["status", ...Object.values(PRIORITY)],
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

	// Ten statuses, and without this map Frappe falls back to `guess_colour`, which paints
	// most of them the same grey and gives "Rejected" the same red as "Cancelled" but also
	// hands red to plain drafts. Colour convention, shared by every Container Depot list:
	//   grey   — Draft: belum diteruskan ke team, masih bisa diubah
	//   red    — Cancelled / Rejected: mati, tidak diteruskan
	//   blue   — Completed: the terminal "done" state (M&R selesai dan ditutup)
	//   others — the stages in between; Approved is green rather than blue because the
	//            owner's approval only STARTS the work, it does not finish the order.
	// Labels mirror frontend/src/utils/labels.js (repairStatusLabels) so Desk and the PWA
	// name the same status the same way.
	get_indicator(doc) {
		const map = {
			Draft: container_depot.status_pill("draft", "status,=,Draft"),
			"Pending Approval": [__("Menunggu Persetujuan"), "orange", "status,=,Pending Approval"],
			Approved: [__("Disetujui"), "green", "status,=,Approved"],
			Rejected: [__("Ditolak"), "red", "status,=,Rejected"],
			"Revision Requested": container_depot.status_pill("revision", "status,=,Revision Requested"),
			Pending: container_depot.status_pill("ready", "status,=,Pending"),
			"In Progress": container_depot.status_pill("doing", "status,=,In Progress"),
			"Pending Review": container_depot.status_pill("review", "status,=,Pending Review"),
			Completed: container_depot.status_pill("done", "status,=,Completed"),
			Cancelled: container_depot.status_pill("cancelled", "status,=,Cancelled"),
		};
		return map[doc.status] || [__(doc.status || "-"), "gray", `status,=,${doc.status || ""}`];
	},

	// Dua menu sidebar, satu doctype (lihat container_depot/mr_scope.py): judul dan menu yang
	// menyala mengikuti filter job_type, supaya M&R dan Periodic Test tidak terbaca satu menu.
	refresh(listview) {
		const jt = listview.filters.find((f) => f[1] === "job_type" && f[2] === "=")?.[3];
		const title = { Repair: __("M&R (Maintenance & Repair)"), "Periodic Test": __("Periodic Test") }[jt];
		listview.page.set_title(title || listview.page_title);
		frappe.app.sidebar?.set_active_workspace_item();
		// plan_date milik kedua jenis; labelnya ikut menu. Salinan df, bukan df meta — label
		// meta dipakai juga oleh form dan list lain.
		const plan = { Repair: __("Repair Plan Date"), "Periodic Test": __("Periodic Plan Date") }[jt] || __("Plan Date");
		listview.page.fields_dict.plan_date?.$input?.attr("placeholder", plan);
		const col = listview.columns.find((c) => c.df?.fieldname === "plan_date");
		if (col && col.df.label !== plan) {
			col.df = { ...col.df, label: plan };
			listview.render_header(true);
		}
	},

	// A Datetime field with in_standard_filter would only give an "=" box, which is useless
	// for a created-on search. Add a DateRange control instead: its value is a [from, to]
	// pair and its `between` condition is what get_standard_filters passes to the server,
	// which widens the two dates to 00:00:00 / 23:59:59 for the Datetime column.
	// Added in onload (not via custom_filter_configs) so it lands AFTER the doctype's own
	// standard filters rather than ahead of them.
	onload(listview) {
		const filter_area = listview.filter_area;
		listview.page.add_field(
			{
				fieldtype: "DateRange",
				fieldname: "order_created",
				label: __("Order Created"),
				condition: "between",
				onchange: () => filter_area.debounced_refresh_list_view(),
			},
			filter_area.standard_filters_wrapper
		);
	},
};
