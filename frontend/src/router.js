import { createRouter, createWebHistory } from "vue-router"
import { session, redirectToLogin } from "@/data/session"

const routes = [
	{
		path: "/",
		name: "Home",
		component: () => import("@/pages/Home.vue"),
	},
	{
		path: "/gate",
		name: "GateEntry",
		component: () => import("@/pages/GateEntry.vue"),
	},
	{
		path: "/eir",
		name: "EirChecklist",
		component: () => import("@/pages/EirChecklist.vue"),
	},
	{
		path: "/eir/history",
		name: "EirHistory",
		component: () => import("@/pages/EirHistory.vue"),
	},
	{
		path: "/cleaning",
		name: "CleaningOrder",
		component: () => import("@/pages/CleaningOrder.vue"),
	},
	{
		path: "/mr",
		name: "MaintenanceRepair",
		component: () => import("@/pages/MaintenanceRepair.vue"),
	},
	{
		path: "/storage",
		name: "DepotStorage",
		component: () => import("@/pages/DepotStorage.vue"),
	},
	{
		path: "/monitor",
		name: "MonitorContainer",
		component: () => import("@/pages/MonitorContainer.vue"),
	},
]

const router = createRouter({
	// Served under /depot (see www/depot.html). All in-app routes are relative.
	history: createWebHistory("/depot"),
	routes,
})

// Defence-in-depth guard: the server already redirects Guests on the /depot
// page load, but if the session cookie is missing/expired client-side, bounce
// to the standard Frappe login and return to /depot.
router.beforeEach((to, from, next) => {
	if (!session.isLoggedIn) {
		redirectToLogin()
		return
	}
	next()
})

export default router
