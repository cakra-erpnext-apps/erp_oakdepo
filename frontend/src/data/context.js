import { cachedResource } from "@/data/cache"

// Active user's branch scope (for headers / labels). One module-level resource, so it is
// fetched once per app load. No frappe-ui `cache:` here: that persists to IndexedDB under a
// key with no user in it, and hydrates on the next load before any request — so after a
// logout and a login as someone else, the header, Beranda and Profil kept showing the old
// account and never refetched. The offline copy comes from cachedResource, keyed per user.
export const userContext = cachedResource({
	url: "container_depot.ess.context.get_user_context",
	method: "GET",
	auto: false,
})

export function branchLabel() {
	const d = userContext.data
	if (!d) return ""
	if (d.all_branches) return "Semua Branch"
	return (d.branches || []).join(", ") || "Semua Branch"
}
