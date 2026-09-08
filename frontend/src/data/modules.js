// The PWA's module catalogue — one entry per menu key the server may grant
// (container_depot.ess.context._MENU), with the route, icon and short label that name it.
//
// It lives here because THREE surfaces draw the same set and they must not drift: Beranda's
// shortcut grids, the bottom bar's tabs, and the "Lainnya" sheet, which exists precisely to
// hold whatever the bar had no room for. When they disagree, a module silently disappears
// from the app — reachable only by typing its URL.
//
// No role name appears here, and none should: the server answers with menu keys, and every
// consumer filters this catalogue through `menu.has()`.
//
// `surveyPos` is deliberately absent. It is a menu KEY (the surveyor's right to close a
// Survey Order) but not a module: it opens the same /survey-orders screen `surveyList`
// does, and two tiles racing to the same route is how a menu grid gets confusing.

import { labels } from "@/utils/labels"

export const MODULES = {
	schedule: { key: "schedule", to: "/schedule", icon: "calendar", title: labels.navSchedule, tone: "bg-brand-50 text-brand-600" },
	gate: { key: "gate", to: "/gate", icon: "log-in", title: labels.navGate, tone: "bg-brand-50 text-brand-600" },
	eir: { key: "eir", to: "/eir", icon: "clipboard", title: labels.navEir, tone: "bg-leaf-50 text-leaf-600" },
	cleaning: { key: "cleaning", to: "/cleaning", icon: "droplet", title: labels.navCleaning, tone: "bg-leaf-50 text-leaf-600" },
	mr: { key: "mr", to: "/mr", icon: "tool", title: labels.navMr, tone: "bg-amber-50 text-amber-600" },
	monitor: { key: "monitor", to: "/monitor", icon: "grid", title: labels.navMonitor, tone: "bg-brand-50 text-brand-600" },
	tankPos: { key: "tankPos", to: "/tank-position", icon: "map-pin", title: labels.tankPosTitle, tone: "bg-leaf-50 text-leaf-600" },
	surveyList: { key: "surveyList", to: "/survey-orders", icon: "list", title: labels.navSurveyList, tone: "bg-brand-50 text-brand-600" },
	posFix: { key: "posFix", to: "/position-fix", icon: "arrow-down-circle", title: labels.navPosFix, tone: "bg-leaf-50 text-leaf-600" },
}

// Beranda's two shortcut grids. "Operasional" is the work done per DOCUMENT (a bon, an EIR,
// an order); "Yard" is the work done per TANK, standing in front of it.
export const GROUP_OPS = ["schedule", "gate", "eir", "cleaning", "mr"]
export const GROUP_YARD = ["monitor", "tankPos", "surveyList", "posFix"]

// Which modules earn a tab in the bottom bar, most-used first. The bar takes the first few
// of these that the account actually holds; everything else moves into "Lainnya".
//
// Gate / EIR / M&R lead because they are the three screens a shift is spent inside, and the
// order is what decides the bar for an account that holds everything (SPV Lapangan).
export const TAB_ORDER = ["gate", "eir", "mr", "cleaning", "monitor", "schedule", "surveyList", "posFix", "tankPos"]

/** The modules this account may open, in catalogue order, filtered by the server's menu. */
export function modulesFor(keys, menu) {
	return keys.map((k) => MODULES[k]).filter((m) => m && menu.has(m.key))
}
