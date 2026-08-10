import { createRouter, createWebHistory } from "vue-router"
import { session, redirectToLogin } from "@/data/session"
import { fetchMenu, menu } from "@/data/menu"

// `meta.menuKey` ties a route to the same menu key the server grants in
// container_depot.ess.context.get_menu. A route without one (Home) is open to anyone
// with a session — Home renders its own empty state when the menu is empty.
const routes = [
	{
		path: "/",
		name: "Home",
		component: () => import("@/pages/Home.vue"),
	},
	{
		// No menuKey, same as Home: the profile is about the account itself, so it must
		// stay reachable by someone whose menu is empty — that is exactly who needs to
		// read why.
		path: "/profile",
		name: "Profile",
		component: () => import("@/pages/Profile.vue"),
	},
	{
		path: "/gate",
		name: "GateEntry",
		meta: { menuKey: "gate" },
		component: () => import("@/pages/GateEntry.vue"),
	},
	{
		path: "/ready-out",
		name: "ReadyToLoad",
		meta: { menuKey: "readyOut" },
		component: () => import("@/pages/ReadyToLoad.vue"),
	},
	{
		path: "/eir",
		name: "Eir",
		meta: { menuKey: "eir" },
		component: () => import("@/pages/Eir.vue"),
	},
	{
		path: "/eir/history",
		name: "EirHistory",
		meta: { menuKey: "eir" },
		component: () => import("@/pages/EirHistory.vue"),
	},
	{
		path: "/eir/sort",
		name: "EirSort",
		meta: { menuKey: "eir" },
		component: () => import("@/pages/EirSort.vue"),
	},
	{
		path: "/gate/history",
		name: "GateHistory",
		meta: { menuKey: "gate" },
		component: () => import("@/pages/GateHistory.vue"),
	},
	{
		path: "/cleaning",
		name: "CleaningOrder",
		meta: { menuKey: "cleaning" },
		component: () => import("@/pages/CleaningOrder.vue"),
	},
	{
		path: "/cleaning/history",
		name: "CleaningHistory",
		meta: { menuKey: "cleaning" },
		component: () => import("@/pages/CleaningHistory.vue"),
	},
	{
		path: "/mr",
		name: "MaintenanceRepair",
		meta: { menuKey: "mr" },
		component: () => import("@/pages/MaintenanceRepair.vue"),
	},
	{
		path: "/mr/history",
		name: "MrHistory",
		meta: { menuKey: "mr" },
		component: () => import("@/pages/MrHistory.vue"),
	},
	{
		path: "/periodic-test",
		name: "PeriodicTest",
		meta: { menuKey: "periodicTest" },
		component: () => import("@/pages/PeriodicTest.vue"),
	},
	{
		path: "/periodic-test/history",
		name: "PeriodicTestHistory",
		meta: { menuKey: "periodicTest" },
		component: () => import("@/pages/PeriodicTestHistory.vue"),
	},
	{
		path: "/monitor",
		name: "MonitorContainer",
		meta: { menuKey: "monitor" },
		component: () => import("@/pages/MonitorContainer.vue"),
	},
	{
		path: "/monitor/history",
		name: "MonitorHistory",
		meta: { menuKey: "monitor" },
		component: () => import("@/pages/MonitorHistory.vue"),
	},
	{
		path: "/survey-position",
		name: "SurveyPosition",
		meta: { menuKey: "surveyPos" },
		component: () => import("@/pages/SurveyPosition.vue"),
	},
	{
		path: "/survey-position/history",
		name: "SurveyPositionHistory",
		meta: { menuKey: "surveyPos" },
		component: () => import("@/pages/SurveyPositionHistory.vue"),
	},
	{
		path: "/position-fix",
		name: "KalmarPositionFix",
		meta: { menuKey: "posFix" },
		component: () => import("@/pages/KalmarPositionFix.vue"),
	},
]

const router = createRouter({
	// Served under /depot (see www/depot.html). All in-app routes are relative.
	history: createWebHistory("/depot"),
	routes,
})

// Two guards, neither of which is a security boundary — the endpoints enforce
// themselves (container_depot/ess/guard.py). These just keep the UI honest.
//
// 1. Session: the server already redirects Guests on the /depot page load, but if the
//    cookie is missing/expired client-side, bounce to the standard Frappe login.
// 2. Menu: typing /depot/mr as Team Cleaning lands on Home instead of a page that would
//    only fill with 403s. The menu is fetched once and cached, so this awaits a request
//    on the first navigation only.
router.beforeEach(async (to, from, next) => {
	if (!session.isLoggedIn) {
		redirectToLogin()
		return
	}
	const key = to.meta?.menuKey
	if (!key) {
		next()
		return
	}
	if (!menu.ready) await fetchMenu()
	next(menu.has(key) ? undefined : { path: "/" })
})

export default router
