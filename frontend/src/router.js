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
		name: "Eir",
		component: () => import("@/pages/Eir.vue"),
	},
	{
		path: "/eir/history",
		name: "EirHistory",
		component: () => import("@/pages/EirHistory.vue"),
	},
	{
		path: "/eir/sort",
		name: "EirSort",
		component: () => import("@/pages/EirSort.vue"),
	},
	{
		path: "/gate/history",
		name: "GateHistory",
		component: () => import("@/pages/GateHistory.vue"),
	},
	{
		path: "/cleaning",
		name: "CleaningOrder",
		component: () => import("@/pages/CleaningOrder.vue"),
	},
	{
		path: "/cleaning/history",
		name: "CleaningHistory",
		component: () => import("@/pages/CleaningHistory.vue"),
	},
	{
		path: "/mr",
		name: "MaintenanceRepair",
		component: () => import("@/pages/MaintenanceRepair.vue"),
	},
	{
		path: "/mr/history",
		name: "MrHistory",
		component: () => import("@/pages/MrHistory.vue"),
	},
	{
		path: "/storage",
		name: "DepotStorage",
		component: () => import("@/pages/DepotStorage.vue"),
	},
	{
		path: "/storage/history",
		name: "StorageHistory",
		component: () => import("@/pages/StorageHistory.vue"),
	},
	{
		path: "/monitor",
		name: "MonitorContainer",
		component: () => import("@/pages/MonitorContainer.vue"),
	},
	{
		path: "/monitor/history",
		name: "MonitorHistory",
		component: () => import("@/pages/MonitorHistory.vue"),
	},
	{
		path: "/survey-position",
		name: "SurveyPosition",
		component: () => import("@/pages/SurveyPosition.vue"),
	},
	{
		path: "/position-fix",
		name: "KalmarPositionFix",
		component: () => import("@/pages/KalmarPositionFix.vue"),
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
