import { createResource } from "frappe-ui"

// Active user's branch scope (for headers / labels). Cached for the session.
export const userContext = createResource({
	url: "container_depot.ess.context.get_user_context",
	cache: "user_context",
	auto: false,
})

export function branchLabel() {
	const d = userContext.data
	if (!d) return ""
	if (d.all_branches) return "Semua Branch"
	return (d.branches || []).join(", ") || "Semua Branch"
}
