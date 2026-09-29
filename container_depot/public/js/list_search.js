// One "Cari" box in place of Frappe's quick filters, on every list whose doctype has a
// `search_text` column (container_depot/list_search.py fills it and lists what it holds).
// Anything beyond it goes through Frappe's own Filter button.
//
// Swapped in where the filter area is built, before the saved / URL filters are applied: a
// customer or status filter that used to sit in a quick-filter box then lands under the
// Filter button ("Filters 1") instead of in a box that is no longer there.
(() => {
	const proto = frappe.views.ListView.prototype;
	const setup_filter_area = proto.setup_filter_area;

	proto.setup_filter_area = function () {
		if (this.hide_filters || this.hide_page_form || !frappe.meta.has_field(this.doctype, "search_text")) {
			return setup_filter_area.call(this);
		}
		const filters = this.filters;
		this.filters = [];
		setup_filter_area.call(this);
		this.filters = filters;
		only_cari(this);
		if (filters && filters.length) {
			return this.filter_area.set(filters).catch(() => this.filter_area.clear(false));
		}
	};

	function only_cari(listview) {
		const page = listview.page;
		const area = listview.filter_area;
		// Frappe's quick filters: the title field (always), in_standard_filter fields, ID.
		for (const key of Object.keys(page.fields_dict)) {
			page.fields_dict[key].$wrapper.remove();
			delete page.fields_dict[key];
		}
		area.$filter_list_wrapper.find(".mobile-id-filter").remove();

		const field = page.add_field(
			{
				fieldtype: "Data",
				fieldname: "search_text",
				label: __("Cari…"),
				condition: "like",
				onchange: () => area.debounced_refresh_list_view(),
			},
			area.standard_filters_wrapper
		);
		// A search restored from the last visit comes back as the stored pattern, "%OAKU24%":
		// show what was typed (get_standard_filters wraps it in % again).
		const set_value = field.set_value.bind(field);
		field.set_value = (value) =>
			set_value(typeof value === "string" ? value.replace(/^%+|%+$/g, "") : value);
	}

	frappe.dom.set_style(
		`.page-form .frappe-control[data-fieldname="search_text"] { flex: 0 1 360px; width: 360px; max-width: 100%; }`,
		"container-depot-list-search"
	);
})();
