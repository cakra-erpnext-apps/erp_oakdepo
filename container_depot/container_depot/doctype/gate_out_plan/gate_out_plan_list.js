// Gate Out Plan — list view. Reads like Purchase Receipt's billing progress: the status
// pill answers "is this notice still live", and the % Keluar column shows how much of it
// has actually left the depot, so a partly-collected plan is visible as progress instead of
// looking identical to one nobody has touched.

frappe.listview_settings["Gate Out Plan"] = {
	add_fields: ["status", "per_fulfilled", "readiness_summary", "next_lift_on"],

	get_indicator(doc) {
		const per = flt(doc.per_fulfilled, 2);
		if (doc.status === "Cancelled") return [__("Dibatalkan"), "gray", "status,=,Cancelled"];
		if (doc.status === "Fulfilled") return [__("Selesai Keluar"), "green", "status,=,Fulfilled"];
		if (per > 0) return [__("Sebagian Keluar"), "yellow", "status,=,Open"];
		return [__("Open"), "orange", "status,=,Open"];
	},

	formatters: {
		per_fulfilled(value) {
			const per = Math.min(100, Math.max(0, flt(value, 2)));
			const colour = per >= 100 ? "bg-green-500" : per > 0 ? "bg-yellow-500" : "bg-gray-300";
			return `
				<div class="d-flex align-items-center" style="gap:6px">
					<span class="progress" style="height:6px;width:60px;margin:0">
						<span class="progress-bar ${colour}" style="width:${per}%"></span>
					</span>
					<span class="text-muted">${per}%</span>
				</div>`;
		},
	},
};
