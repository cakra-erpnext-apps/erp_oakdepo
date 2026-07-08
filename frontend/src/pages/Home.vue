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
			</div>
		</section>

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
						<span class="font-bold text-gray-700">{{ dash.total }}</span> {{ labels.dashSummaryUnit }}
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
			<!-- Container per status -->
			<section class="space-y-2">
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
				<router-link
					v-if="dash.periodic_test_due > 0"
					:to="{ path: '/monitor', query: { status: '' } }"
					class="oak-card oak-press flex items-center gap-2 p-3"
				>
					<span class="oak-icon-tile h-8 w-8 bg-amber-50 text-amber-600"><Icon name="alert-triangle" :size="16" /></span>
					<p class="flex-1 text-sm font-medium text-gray-700">
						<span class="font-bold text-amber-700">{{ dash.periodic_test_due }}</span> {{ labels.dashPtDue }}
					</p>
					<Icon name="chevron-right" :size="16" class="text-gray-300" />
				</router-link>
			</section>

			<!-- Aktivitas hari ini -->
			<section class="space-y-2">
				<p class="oak-eyebrow flex items-center gap-1.5 px-1">
					<Icon name="activity" :size="14" /> {{ labels.dashTodayTitle }}
				</p>
				<div class="grid grid-cols-3 gap-2">
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

		<!-- Riwayat (history) — one entry per main menu -->
		<div>
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
	</div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from "vue"
import { session } from "@/data/session"
import { userResource } from "@/data/user"
import { dashboardResource } from "@/data/dashboard"
import { labels, statusLabels } from "@/utils/labels"
import Icon from "@/components/Icon.vue"
import emblem from "@/assets/oak-emblem.png"

const dashRes = dashboardResource

onMounted(() => {
	// Confirm the logged-in user server-side (PRD Phase 0 deliverable).
	if (session.isLoggedIn && !userResource.data) userResource.reload()
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
	return (p.eir_in || 0) + (p.eir_out || 0) + (p.cleaning || 0) + (p.mr_open || 0)
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
const todayCards = computed(() => {
	const t = dash.value?.today || {}
	return [
		{ icon: "log-in", tile: "bg-brand-50 text-brand-600", label: labels.dashTodayIn, count: t.gate_in ?? 0 },
		{ icon: "log-out", tile: "bg-gray-100 text-gray-500", label: labels.dashTodayOut, count: t.gate_out ?? 0 },
		{ icon: "clipboard", tile: "bg-leaf-50 text-leaf-600", label: labels.dashTodayEir, count: t.eir ?? 0 },
	]
})

// --- KPI: pending tasks (hide zero-count rows; tap → the worklist) ---
const pendingCards = computed(() => {
	const p = dash.value?.pending || {}
	const rows = [
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
	]
	return rows.filter((r) => r.count > 0)
})

// --- Menu tiles, grouped by workflow phase ---
const tiles = {
	gate: { to: "/gate", icon: "log-in", title: labels.gate, desc: labels.gateDesc, tile: "bg-brand-50 text-brand-600", wide: true },
	eir: { to: "/eir", icon: "clipboard", title: labels.eir, desc: labels.eirDesc, tile: "bg-leaf-50 text-leaf-600" },
	cleaning: { to: "/cleaning", icon: "droplet", title: labels.cleaningTitle, desc: labels.cleaningDesc, tile: "bg-brand-50 text-brand-600" },
	mr: { to: "/mr", icon: "tool", title: labels.mrTitleFull, desc: labels.mrDesc, tile: "bg-leaf-50 text-leaf-600" },
	monitor: { to: "/monitor", icon: "grid", title: labels.monitorTitle, desc: labels.monitorDesc, tile: "bg-brand-50 text-brand-600" },
	surveyPos: { to: "/survey-position", icon: "map-pin", title: labels.surveyPosTitle, desc: labels.surveyPosDesc, tile: "bg-amber-50 text-amber-600" },
	posFix: { to: "/position-fix", icon: "check-circle", title: labels.posFixTitle, desc: labels.posFixDesc, tile: "bg-leaf-50 text-leaf-600" },
}
const menuGroups = [
	{ title: labels.grpGate, items: [tiles.gate] },
	{ title: labels.grpInspeksi, items: [tiles.eir] },
	{ title: labels.grpPerawatan, items: [tiles.cleaning, tiles.mr] },
	{ title: labels.grpYard, items: [tiles.monitor] },
	{ title: labels.grpSurvey, items: [tiles.surveyPos, tiles.posFix] },
]

// "Riwayat" — a history menu per main menu (list + tap-to-detail).
const history = [
	{ to: "/gate/history", icon: "log-in", title: labels.gateHistoryTitle },
	{ to: "/eir/history", icon: "clipboard", title: labels.eirHistoryTitle },
	{ to: "/cleaning/history", icon: "droplet", title: labels.cleaningHistoryTitle },
	{ to: "/mr/history", icon: "tool", title: labels.mrHistoryTitle },
	{ to: "/survey-position/history", icon: "map-pin", title: labels.surveyPosHistoryTitle },
	{ to: "/monitor/history", icon: "activity", title: labels.monitorHistoryTitle },
]
</script>
