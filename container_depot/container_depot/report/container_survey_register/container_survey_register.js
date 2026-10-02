frappe.query_reports["Container Survey Register"] = {
	filters: [
		...container_depot.report_kit.filters([
			["survey_date", "Jadwal Survei"],
			["requested_on", "Diminta"],
			["target_lift_on", "Plan Pickup Date"],
			["lowered_on", "Turun (Lowered)"],
			["surveyed_on", "Survei Selesai"],
			["location_updated_on", "Letak Diperbarui"],
		]),
		{ fieldname: "principal", label: __("Principle"), fieldtype: "Link", options: "Customer" },
		{ fieldname: "depot", label: __("Depot"), fieldtype: "Link", options: "Depot" },
		{ fieldname: "container", label: __("Tank No"), fieldtype: "Link", options: "Container" },
		{
			fieldname: "status",
			label: __("Status"),
			fieldtype: "Select",
			options: "\nWaiting Lowering\nLowered\nSurvey Done",
		},
		{ fieldname: "only_outstanding", label: __("Hanya yang belum selesai"), fieldtype: "Check", default: 0 },
	],

	onload: container_depot.report_kit.onload,

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "status" && data && data.status) {
			const colour = {
				// Hijau = selesai. Biru = sudah turun, tinggal disurvei. Merah = masih
				// ditumpuk, yaitu satu-satunya keadaan yang benar-benar menahan tank.
				"Survey Done": "green",
				Lowered: "blue",
				"Waiting Lowering": "red",
			}[data.status];
			if (colour) value = `<span class="indicator-pill ${colour}">${data.status}</span>`;
		}
		return value;
	},
};
