<template>
	<div class="mx-auto w-full max-w-lg space-y-5 md:max-w-2xl">
		<!-- Greeting hero -->
		<section class="oak-card relative overflow-hidden animate-slide-up">
			<div class="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-brand-500 to-leaf-500"></div>
			<img
				:src="emblem"
				alt=""
				class="pointer-events-none absolute -right-6 -top-4 h-32 w-32 opacity-[0.06]"
			/>
			<div class="relative z-10 p-5">
				<p class="oak-eyebrow">{{ labels.greeting }} 👋</p>
				<p class="mt-1 truncate text-xl font-extrabold tracking-tight text-gray-900">
					{{ displayUser }}
				</p>
				<p class="mt-0.5 text-sm text-gray-500">{{ labels.homeHint }}</p>
				<!-- Way back to ERPNext for accounts that hold both (supervisors, Admin Ops).
				     A plain <a>, not a router-link: /desk is a different app entirely. -->
				<a
					v-if="menu.deskAccess"
					href="/desk"
					class="oak-link mt-2 inline-flex items-center gap-1 text-sm"
				>
					<Icon name="external-link" :size="14" />{{ labels.openDesk }}
				</a>
			</div>
		</section>

		<!-- No menu at all: office staff, or a field account whose roles are not assigned
		     yet. /depot stays open to any logged-in user by design, so say why it is empty
		     rather than showing a blank page that looks broken. -->
		<section v-if="menu.isEmpty" class="oak-card p-6 text-center">
			<span class="oak-icon-tile mx-auto h-12 w-12 bg-gray-100 text-gray-400">
				<Icon name="lock" :size="24" />
			</span>
			<p class="mt-3 font-bold text-gray-900">{{ labels.menuEmptyTitle }}</p>
			<p class="mt-1 text-sm text-gray-500">{{ labels.menuEmptyBody }}</p>
			<!-- The dead end this card would otherwise be: office staff arrive here from the
			     app switcher, find nothing, and have no way onward but retyping a URL. -->
			<template v-if="menu.deskAccess">
				<a href="/desk" class="oak-btn oak-btn-primary mt-4">
					<Icon name="external-link" :size="16" />
					{{ labels.openDesk }}
				</a>
				<p class="mt-2 text-xs text-gray-400">{{ labels.openDeskHint }}</p>
			</template>
		</section>

		<template v-else>
		<!-- Ringkasan Operasional — collapsible KPI dashboard (tap header to expand) -->
		<button
			type="button"
			@click="dashOpen = !dashOpen"
			:aria-expanded="dashOpen"
			class="oak-card oak-press flex w-full items-center gap-3 p-4 text-left"
		>
			<span class="oak-icon-tile h-10 w-10 bg-brand-50 text-brand-600">
				<Icon name="activity" :size="20" />
			</span>
			<div class="min-w-0 flex-1">
				<p class="font-bold text-gray-900">{{ labels.dashSummaryTitle }}</p>
				<p v-if="dashOpen" class="mt-0.5 text-xs text-gray-400">{{ labels.dashSummaryHide }}</p>
				<p v-else class="mt-0.5 truncate text-xs text-gray-500">
					<template v-if="dashRes.loading && !dash">{{ labels.dashSummaryLoading }}</template>
					<template v-else-if="dash">
						<template v-if="dash.total !== undefined">
							<span class="font-bold text-gray-700">{{ dash.total }}</span> {{ labels.dashSummaryUnit }}
						</template>
						<template v-if="summaryPending"> · {{ summaryPending }} {{ labels.dashSummaryTask }}</template>
						<template v-if="summaryAlerts"> · <span class="font-bold text-amber-600">⚠ {{ summaryAlerts }} {{ labels.dashSummaryAlert }}</span></template>
					</template>
					<template v-else>{{ labels.dashSummaryUnavailable }}</template>
				</p>
			</div>
			<Icon
				name="chevron-down"
				:size="20"
				class="shrink-0 text-gray-400 transition-transform duration-200"
				:class="dashOpen ? 'rotate-180' : ''"
			/>
		</button>

		<!-- Expanded KPI content — kept mounted (v-show) so toggling never re-fetches -->
		<div v-show="dashOpen" class="space-y-5">
		<!-- KPI: loading skeleton (first load only) -->
		<div v-if="dashRes.loading && !dash" class="space-y-3">
			<div class="grid grid-cols-2 gap-2 sm:grid-cols-3">
				<div v-for="n in 5" :key="n" class="oak-skeleton h-20 rounded-2xl"></div>
			</div>
			<div class="oak-skeleton h-24 rounded-2xl"></div>
		</div>

		<!-- KPI sections (only when data is available; degrade silently on error) -->
		<template v-else-if="dash">
			<!-- Container per status — `counts` only ships to accounts with the Monitor menu -->
			<section v-if="dash.counts" class="space-y-2">
				<div class="flex items-center justify-between px-1">
					<p class="oak-eyebrow flex items-center gap-1.5">
						<Icon name="package" :size="14" /> {{ labels.dashStatusTitle }}
					</p>
					<p class="text-xs text-gray-500">
						{{ labels.dashStatusTotal }} <span class="font-bold text-gray-700">{{ dash.total }}</span>
					</p>
				</div>
				<div class="grid grid-cols-2 gap-2 sm:grid-cols-3">
					<router-link
						v-for="s in statusCards"
						:key="s.key"
						:to="{ path: '/monitor', query: { status: s.key } }"
						class="oak-card oak-press relative overflow-hidden p-3"
					>
						<span class="absolute inset-y-0 left-0 w-1" :class="s.dot"></span>
						<span class="flex items-center gap-1.5">
							<span class="h-2 w-2 shrink-0 rounded-full" :class="s.dot"></span>
							<span class="truncate text-[11px] font-semibold text-gray-500">{{ s.label }}</span>
						</span>
						<span class="mt-1.5 block text-3xl font-extrabold leading-none" :class="s.num">{{ s.count }}</span>
					</router-link>
				</div>
			</section>

			<!-- Periodic-test due — its own block, not part of the status grid: Team Repair
			     gets this card without the Monitor menu that carries the grid. -->
			<router-link
				v-if="dash.periodic_test_due > 0"
				to="/periodic-test"
				class="oak-card oak-press flex items-center gap-2 p-3"
			>
				<span class="oak-icon-tile h-8 w-8 bg-amber-50 text-amber-600"><Icon name="alert-triangle" :size="16" /></span>
				<p class="flex-1 text-sm font-medium text-gray-700">
					<span class="font-bold text-amber-700">{{ dash.periodic_test_due }}</span> {{ labels.dashPtDue }}
				</p>
				<Icon name="chevron-right" :size="16" class="text-gray-300" />
			</router-link>

			<!-- Tank dengan job aktif — supervisors only (server sends it to accounts
			     holding every menu). Gap Analysis §4.8.4. -->
			<div v-if="dash.active_jobs !== undefined" class="oak-card flex items-center gap-2 p-3">
				<span class="oak-icon-tile h-8 w-8 bg-blue-50 text-blue-600"><Icon name="tool" :size="16" /></span>
				<p class="flex-1 text-sm font-medium text-gray-700">
					<span class="font-bold text-blue-700">{{ dash.active_jobs }}</span> {{ labels.dashActiveJobs }}
				</p>
			</div>

			<!-- Aktivitas hari ini -->
			<section v-if="todayCards.length" class="space-y-2">
				<p class="oak-eyebrow flex items-center gap-1.5 px-1">
					<Icon name="activity" :size="14" /> {{ labels.dashTodayTitle }}
				</p>
				<div class="grid gap-2" :class="todayCards.length === 1 ? 'grid-cols-1' : todayCards.length === 2 ? 'grid-cols-2' : 'grid-cols-3'">
					<div
						v-for="t in todayCards"
						:key="t.label"
						class="oak-card flex flex-col items-center gap-1 p-3 text-center"
					>
						<span class="oak-icon-tile h-9 w-9" :class="t.tile"><Icon :name="t.icon" :size="18" /></span>
						<p class="mt-0.5 text-xl font-extrabold leading-none text-gray-900">{{ t.count }}</p>
						<p class="text-[11px] text-gray-500">{{ t.label }}</p>
					</div>
				</div>
			</section>

			<!-- Tugas tertunda -->
			<section class="space-y-2">
				<p class="oak-eyebrow flex items-center gap-1.5 px-1">
					<Icon name="inbox" :size="14" /> {{ labels.dashPendingTitle }}
				</p>
				<div v-if="pendingCards.length" class="space-y-2">
					<router-link
						v-for="p in pendingCards"
						:key="p.to"
						:to="p.to"
						class="oak-card oak-press flex items-center gap-3 p-3"
					>
						<span class="oak-icon-tile h-10 w-10" :class="p.tile">
							<Icon :name="p.icon" :size="20" />
						</span>
						<div class="min-w-0 flex-1">
							<p class="truncate font-semibold text-gray-900">{{ p.title }}</p>
							<p v-if="p.sub" class="mt-0.5 text-xs font-medium text-amber-600">{{ p.sub }}</p>
						</div>
						<span class="oak-chip shrink-0 bg-brand-50 text-sm font-bold text-brand-700">{{ p.count }}</span>
						<Icon name="chevron-right" :size="18" class="text-gray-300" />
					</router-link>
				</div>
				<p v-else class="oak-card p-4 text-center text-sm text-gray-400">{{ labels.dashNoPending }}</p>
			</section>
		</template>
		</div>

		<!-- Menu — grouped by workflow phase -->
		<section class="space-y-4">
			<p class="oak-eyebrow flex items-center gap-1.5 px-1">
				<Icon name="grid" :size="14" /> {{ labels.dashMenuTitle }}
			</p>
			<div v-for="g in menuGroups" :key="g.title" class="space-y-2">
				<p class="px-1 text-xs font-semibold uppercase tracking-wide text-gray-400">{{ g.title }}</p>
				<div class="grid gap-3 sm:grid-cols-2">
					<router-link
						v-for="m in g.items"
						:key="m.to"
						:to="m.to"
						class="oak-card oak-press flex items-center gap-4 p-4"
						:class="m.wide ? 'sm:col-span-2' : ''"
					>
						<span class="oak-icon-tile h-12 w-12" :class="m.tile">
							<Icon :name="m.icon" :size="24" />
						</span>
						<div class="min-w-0 flex-1">
							<p class="font-bold text-gray-900">{{ m.title }}</p>
							<p class="mt-0.5 text-sm text-gray-500">{{ m.desc }}</p>
						</div>
						<Icon name="chevron-right" :size="20" class="text-gray-300" />
					</router-link>
				</div>
			</div>
		</section>

		<!-- Riwayat (history) — one entry per main menu the account may open -->
		<div v-if="history.length">
			<p class="oak-eyebrow mb-2 flex items-center gap-1.5 px-1">
				<Icon name="clock" :size="14" /> {{ labels.historySection }}
			</p>
			<div class="grid gap-2 sm:grid-cols-2">
				<router-link
					v-for="h in history"
					:key="h.to"
					:to="h.to"
					class="oak-card oak-press flex items-center gap-3 p-3"
				>
					<span class="oak-icon-tile h-9 w-9 bg-gray-100 text-gray-500">
						<Icon :name="h.icon" :size="18" />
					</span>
					<p class="min-w-0 flex-1 truncate text-sm font-semibold text-gray-700">{{ h.title }}</p>
					<Icon name="chevron-right" :size="18" class="text-gray-300" />
				</router-link>
			</div>
		</div>
		</template>
	</div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from "vue"
import { session } from "@/data/session"
import { userResource } from "@/data/user"
import { dashboardResource } from "@/data/dashboard"
import { fetchMenu, menu } from "@/data/menu"
import { labels, statusLabels } from "@/utils/labels"
import Icon from "@/components/Icon.vue"
import emblem from "@/assets/oak-emblem.png"

const dashRes = dashboardResource

onMounted(() => {
	// Confirm the logged-in user server-side (PRD Phase 0 deliverable).
	if (session.isLoggedIn && !userResource.data) userResource.reload()
	// Which menus this account may open. Cached after the first call, so the router
	// guard and this page share one request.
	fetchMenu()
	// Refresh the dashboard KPIs each visit (component remounts on navigation).
	dashRes.reload()
})

const displayUser = computed(() => userResource.data || session.user || "—")

const dash = computed(() => dashRes.data || null)

// --- Collapsible "Ringkasan" dashboard ---
// Default collapsed so the menu is reachable on open without scrolling; the
// summary line keeps the key numbers glanceable while closed. Choice persists
// per user (per browser) so supervisors who keep it open stay that way.
const DASH_OPEN_KEY = "depot.home.dashOpen"
const dashOpen = ref(localStorage.getItem(DASH_OPEN_KEY) === "1")
watch(dashOpen, (v) => localStorage.setItem(DASH_OPEN_KEY, v ? "1" : "0"))

// Collapsed-summary figures: pending tasks awaiting action + urgent alerts
// (periodic test due, M&R approvals, near-full yard).
const summaryPending = computed(() => {
	const p = dash.value?.pending || {}
	return (
		(p.eir_in || 0) +
		(p.eir_out || 0) +
		(p.cleaning || 0) +
		(p.mr_open || 0) +
		(p.position_survey || 0) +
		(p.position_fix || 0)
	)
})
const summaryAlerts = computed(() => {
	const p = dash.value?.pending || {}
	return (dash.value?.periodic_test_due || 0) + (p.mr_approval || 0)
})

// --- KPI: container per order-state (tap → Monitor pre-filtered to the bucket) ---
const STATUS_ORDER = ["available", "draft", "pending", "in_progress", "gate_out"]
// Per-bucket accent (number colour + side/dot tint) — aligned to statusColors.
const STATUS_STYLE = {
	available: { num: "text-leaf-700", dot: "bg-leaf-500" },
	draft: { num: "text-gray-600", dot: "bg-gray-400" },
	pending: { num: "text-amber-700", dot: "bg-amber-500" },
	in_progress: { num: "text-blue-700", dot: "bg-blue-500" },
	gate_out: { num: "text-gray-600", dot: "bg-gray-400" },
}
const statusCards = computed(() => {
	const counts = dash.value?.counts || {}
	return STATUS_ORDER.map((k) => ({
		key: k,
		label: statusLabels[k] || k,
		num: STATUS_STYLE[k]?.num || "text-gray-900",
		dot: STATUS_STYLE[k]?.dot || "bg-gray-400",
		count: counts[k] ?? 0,
	}))
})

// --- KPI: today's activity ---
// The server only sends the keys this account's menu covers (§6), so a missing key
// means "not your card" — different from a zero, which means "your card, nothing yet".
const todayCards = computed(() => {
	const t = dash.value?.today || {}
	return [
		{ key: "gate_in", icon: "log-in", tile: "bg-brand-50 text-brand-600", label: labels.dashTodayIn },
		{ key: "gate_out", icon: "log-out", tile: "bg-gray-100 text-gray-500", label: labels.dashTodayOut },
		{ key: "clipboard", icon: "clipboard", tile: "bg-leaf-50 text-leaf-600", label: labels.dashTodayEir, field: "eir" },
	]
		.map((c) => ({ ...c, count: t[c.field || c.key] }))
		.filter((c) => c.count !== undefined)
})

// --- KPI: pending tasks (hide zero-count rows; tap → the worklist) ---
const pendingCards = computed(() => {
	const p = dash.value?.pending || {}
	const rows = [
		{ to: "/ready-out", icon: "log-out", tile: "bg-amber-50 text-amber-600", title: labels.readyOutTitle, count: p.ready_out ?? 0, sub: labels.readyOutSubtitle },
		{ to: "/eir", icon: "clipboard", tile: "bg-leaf-50 text-leaf-600", title: labels.eir, count: (p.eir_in ?? 0) + (p.eir_out ?? 0) },
		{ to: "/cleaning", icon: "droplet", tile: "bg-brand-50 text-brand-600", title: labels.cleaningTitle, count: p.cleaning ?? 0 },
		{
			to: "/mr",
			icon: "tool",
			tile: "bg-leaf-50 text-leaf-600",
			title: labels.mrTitleFull,
			count: p.mr_open ?? 0,
			sub: p.mr_approval ? `${p.mr_approval} ${labels.dashPendingApproval}` : "",
		},
		{ to: "/survey-position", icon: "map-pin", tile: "bg-amber-50 text-amber-600", title: labels.dashPosSurvey, count: p.position_survey ?? 0 },
		{ to: "/position-fix", icon: "check-circle", tile: "bg-leaf-50 text-leaf-600", title: labels.dashPosFix, count: p.position_fix ?? 0 },
	]
	return rows.filter((r) => r.count > 0)
})

// --- Menu tiles, grouped by workflow phase ---
// `key` matches the server's menu key (container_depot.ess.context._MENU). No role name
// appears here or anywhere else in the frontend — the server decides, this only renders.
const tiles = {
	gate: { key: "gate", to: "/gate", icon: "log-in", title: labels.gate, desc: labels.gateDesc, tile: "bg-brand-50 text-brand-600", wide: true },
	eir: { key: "eir", to: "/eir", icon: "clipboard", title: labels.eir, desc: labels.eirDesc, tile: "bg-leaf-50 text-leaf-600" },
	cleaning: { key: "cleaning", to: "/cleaning", icon: "droplet", title: labels.cleaningTitle, desc: labels.cleaningDesc, tile: "bg-brand-50 text-brand-600" },
	mr: { key: "mr", to: "/mr", icon: "tool", title: labels.mrTitleFull, desc: labels.mrDesc, tile: "bg-leaf-50 text-leaf-600" },
	periodicTest: { key: "periodicTest", to: "/periodic-test", icon: "activity", title: labels.ptTitleFull, desc: labels.ptDesc, tile: "bg-amber-50 text-amber-600" },
	readyOut: { key: "readyOut", to: "/ready-out", icon: "log-out", title: labels.readyOutTitle, desc: labels.readyOutDesc, tile: "bg-amber-50 text-amber-600", wide: true },
	monitor: { key: "monitor", to: "/monitor", icon: "grid", title: labels.monitorTitle, desc: labels.monitorDesc, tile: "bg-brand-50 text-brand-600" },
	surveyPos: { key: "surveyPos", to: "/survey-position", icon: "map-pin", title: labels.surveyPosTitle, desc: labels.surveyPosDesc, tile: "bg-amber-50 text-amber-600" },
	posFix: { key: "posFix", to: "/position-fix", icon: "check-circle", title: labels.posFixTitle, desc: labels.posFixDesc, tile: "bg-leaf-50 text-leaf-600" },
}
const allMenuGroups = [
	{ title: labels.grpGate, items: [tiles.gate, tiles.readyOut] },
	{ title: labels.grpInspeksi, items: [tiles.eir] },
	{ title: labels.grpPerawatan, items: [tiles.cleaning, tiles.mr, tiles.periodicTest] },
	{ title: labels.grpYard, items: [tiles.monitor] },
	{ title: labels.grpSurvey, items: [tiles.surveyPos, tiles.posFix] },
]

// Drop tiles the account may not open, then drop groups left with nothing in them — a
// heading over an empty grid reads as a loading bug.
const menuGroups = computed(() =>
	allMenuGroups
		.map((g) => ({ ...g, items: g.items.filter((m) => menu.has(m.key)) }))
		.filter((g) => g.items.length)
)

// "Riwayat" — a history menu per main menu (list + tap-to-detail). Each rides on the
// same key as its main menu, so a role that cannot open M&R cannot browse M&R history.
const allHistory = [
	{ key: "gate", to: "/gate/history", icon: "log-in", title: labels.gateHistoryTitle },
	{ key: "eir", to: "/eir/history", icon: "clipboard", title: labels.eirHistoryTitle },
	{ key: "cleaning", to: "/cleaning/history", icon: "droplet", title: labels.cleaningHistoryTitle },
	{ key: "mr", to: "/mr/history", icon: "tool", title: labels.mrHistoryTitle },
	{ key: "periodicTest", to: "/periodic-test/history", icon: "activity", title: labels.ptHistoryTitle },
	{ key: "surveyPos", to: "/survey-position/history", icon: "map-pin", title: labels.surveyPosHistoryTitle },
	{ key: "monitor", to: "/monitor/history", icon: "activity", title: labels.monitorHistoryTitle },
]
const history = computed(() => allHistory.filter((h) => menu.has(h.key)))
</script>
