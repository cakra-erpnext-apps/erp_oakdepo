// Container Inventory — satu baris per tank: letak, kesiapan, dan setiap order yang
// menempel padanya. Gabungan dari report "Container Inventory" + "Container Status
// Report" (2026-09-18) — lihat container_inventory.py.
//
// Status/Type/Stage tetap Select (persis Select di Container), Principal/Depot Link supaya
// daftarnya datang dari datanya sendiri, bukan salinan yang dijaga tangan.
//
// Kolom & judulnya mengikuti sheet "Tank Stock Report" yang sudah dipakai user; "Cari" dan
// "Tanggal" (kolom tanggal mana yang disaring Dari/Sampai) dari container_depot.report_kit.
frappe.query_reports["Container Inventory"] = {
	filters: [
		...container_depot.report_kit.filters([
			["in_date", "In Depot"],
			["cleaning_start", "Cleaning Start"],
			["cleaning_end", "Cleaning End"],
			["repair_start", "Start Repair"],
			["available_date", "Available Date"],
			["survey_date", "Survey Date"],
			["out_date", "Depot Out"],
			["target_lift_on", "Plan Pickup Date"],
			["last_test_date", "Test"],
			["next_test_date", "Next Test"],
		]),
		{
			fieldname: "principal",
			label: __("Principal"),
			fieldtype: "Link",
			options: "Customer",
		},
		{
			fieldname: "depot",
			label: __("Depot"),
			fieldtype: "Link",
			options: "Depot",
		},
		{
			fieldname: "status",
			label: __("Status"),
			fieldtype: "Select",
			options: "\nBooked\nIn_Depot\nAvailable\nGate_Out",
		},
		{
			fieldname: "inventory_stage",
			label: __("Stage"),
			fieldtype: "Select",
			options: "\nPre-Arrival\nIn Depot\nReady\nDeparted",
		},
		{
			fieldname: "container_type",
			label: __("Container Type"),
			fieldtype: "Select",
			options: "\nISO Tank\n20ft Dry\n40ft HC\n20ft Reefer\n40ft Reefer\nOpen Top\nFlat Rack",
		},
		// Menyala secara default: yang dicari orang yang membuka "Inventory" adalah tank
		// yang ADA di depo. Dimatikan untuk ikut melihat yang dipesan tapi belum tiba dan
		// yang sudah keluar. Diabaikan saat Stage dipilih sendiri, dan saat Tanggal = Depot
		// Out (tank yang sudah keluar tidak pernah ada di depo).
		{
			fieldname: "in_depo_only",
			label: __("Hanya yang ada di depo"),
			fieldtype: "Check",
			default: 1,
		},
		{
			fieldname: "with_open_work",
			label: __("Hanya yang ada order terbuka"),
			fieldtype: "Check",
			default: 0,
		},
		{
			fieldname: "include_retired",
			label: __("Termasuk tank non-aktif"),
			fieldtype: "Check",
			default: 0,
		},
	],

	onload: container_depot.report_kit.onload,

	// A tank nobody is waiting on should not read the same as one with work stuck on it.
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "readiness" && data && data.readiness) {
			// Orange is "someone has to do something". A tank that has not arrived or has
			// already gone is nobody's queue, so it stays grey rather than reading as work.
			const idle = ["Belum tiba", "Sudah keluar"].includes(data.readiness);
			const colour = data.readiness === "Siap" ? "green" : idle ? "gray" : "orange";
			value = `<span class="indicator-pill ${colour}">${data.readiness}</span>`;
		}
		return value;
	},
};
