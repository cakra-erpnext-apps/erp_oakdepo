import { createResource } from "frappe-ui"

// Aggregated home-dashboard KPI payload — status buckets, today's activity,
// and pending work counts — in one GET. Branch-scoped server-side
// (see container_depot.ess.inventory.get_dashboard_summary).
export const dashboardResource = createResource({
	url: "container_depot.ess.inventory.get_dashboard_summary",
	method: "GET",
	auto: false,
})
