// Copyright (c) 2026, Oak Depot Team and contributors
// For license information, please see license.txt

// Container Position list view — a feed of readings, newest first.
//
// The indicator answers the only question this list is ever opened with: is this reading
// still worth trusting? Age, not status — the doctype has no status, because a reading is
// simply a fact somebody recorded at a moment.
frappe.listview_settings["Container Position"] = {
	add_fields: ["recorded_on", "location_note"],

	get_indicator(doc) {
		const hours = (frappe.datetime.now_datetime()
			? moment().diff(moment(doc.recorded_on), "hours")
			: 0);
		if (hours < 24) return [__("Hari ini"), "green", ""];
		if (hours < 24 * 7) return [__("Minggu ini"), "blue", ""];
		return [__("Lama"), "gray", ""];
	},
};
