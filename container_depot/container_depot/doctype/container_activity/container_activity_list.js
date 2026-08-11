// Timeline log — rows come from `container_activity.log_container_activity`, never from a
// person. `install.NO_MANUAL_CREATE` takes the create permission away from every role; this
// takes the "+ Add" button away from Administrator, who bypasses permissions. See
// gate_entry_list.js for the full note on why `can_create` is set as well as the button cleared.
frappe.listview_settings['Container Activity'] = {
	onload(listview) {
		listview.can_create = false;
		listview.page.clear_primary_action();
	},
};
