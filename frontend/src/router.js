import { createRouter, createWebHistory } from "vue-router"
import { session, redirectToLogin } from "@/data/session"
import { installBackGuard } from "@/utils/backstack"
import { fetchMenu, menu } from "@/data/menu"

// `meta.menuKey` ties a route to the same menu key the server grants in
// container_depot.ess.context.get_menu. A route without one (Home) is open to anyone
// with a session — Home renders its own empty state when the menu is empty. `meta.menuKeys`
// is the plural form for the one route two menus share (Riwayat Survey Posisi).
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
		// Two owners, unlike every other route: this Riwayat lists both halves of the
		// position-survey workflow and is where either one is reopened, so a Kalmar-only
		// operator must be able to open it (see ess.position_survey.position_history).
		meta: { menuKeys: ["surveyPos", "posFix"] },
		component: () => import("@/pages/SurveyPositionHistory.vue"),
	},
	{
		path: "/position-fix",
		name: "KalmarPositionFix",
		meta: { menuKey: "posFix" },
		component: () => import("@/pages/KalmarPositionFix.vue"),
	},
]

// Opt out of the scroll reset for one navigation. Eir's batch ◀ / ▶ swaps to the next EIR
// on purpose without moving the page, and re-applies the old offset itself over the frames
// that follow; resetting to the top first would just make the operator watch it jump twice.
let keepScrollOnce = false
export function keepScrollForNextNavigation() {
	keepScrollOnce = true
}

const router = createRouter({
	// Served under /depot (see www/depot.html). All in-app routes are relative.
	history: createWebHistory("/depot"),
	routes,
	// Vue Router does nothing about scroll unless asked, and "nothing" on a phone means
	// opening a record from row 20 of a worklist renders it with the page still scrolled
	// down past where the shorter detail ends — a blank screen, for a tap that worked.
	// Going Back is the opposite case: the operator wants the row they came from, so the
	// saved offset wins whenever the browser has one.
	scrollBehavior(to, from, savedPosition) {
		if (keepScrollOnce) {
			keepScrollOnce = false
			return false
		}
		return savedPosition || { top: 0 }
	},
})

// Before the guards below: a Back press has to be able to close whatever is on top of the
// page before it is allowed to leave the page.
installBackGuard(router)

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
	// `menuKeys` (plural) means "any one of these is enough" — see the Riwayat route above.
	const keys = to.meta?.menuKeys || (to.meta?.menuKey ? [to.meta.menuKey] : null)
	if (!keys) {
		next()
		return
	}
	if (!menu.ready) await fetchMenu()
	next(keys.some((k) => menu.has(k)) ? undefined : { path: "/" })
})

export default router
