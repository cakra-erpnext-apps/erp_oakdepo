<template>
	<div class="mx-auto w-full max-w-lg space-y-5 md:max-w-2xl">
		<!-- Greeting hero — name plus the depot role(s) the account works as. The KPI
		     dashboard that used to sit under this card was removed on 2026-08-26: on a
		     handset it pushed the menu below the fold on every open, and the numbers it
		     showed were read far less often than the tiles were tapped. The worklists
		     themselves carry their own counts. -->
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
				<!-- What this account IS, in the same role names the admin assigns in the
				     Desk — not a menu list, which the tiles below already are. Falls back to
				     the generic hint for an account with no depot role (office staff), who
				     lands in the empty state underneath anyway. -->
				<div v-if="roles.length" class="mt-2 flex flex-wrap gap-1.5">
					<span v-for="r in roles" :key="r" class="oak-chip bg-brand-50 text-brand-700">
						<Icon name="user" :size="12" />{{ r }}
					</span>
				</div>
				<p v-else class="mt-0.5 text-sm text-gray-500">{{ labels.homeHint }}</p>
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
import { computed, onMounted } from "vue"
import { session } from "@/data/session"
import { userContext } from "@/data/context"
import { fetchMenu, menu } from "@/data/menu"
import { labels } from "@/utils/labels"
import Icon from "@/components/Icon.vue"
import emblem from "@/assets/oak-emblem.png"

onMounted(() => {
	// Confirms the logged-in user server-side (PRD Phase 0 deliverable) and carries the
	// name + depot roles the hero shows, in the one call /profile already makes.
	if (session.isLoggedIn && !userContext.data) userContext.reload()
	// Which menus this account may open. Cached after the first call, so the router
	// guard and this page share one request.
	fetchMenu()
})

const ctx = computed(() => userContext.data || null)
const displayUser = computed(() => ctx.value?.full_name || session.user || "—")
// Depot roles only — the server has already dropped All / Guest / Desk User and the
// ERPNext roles an account may carry alongside (ess.context.depot_roles).
const roles = computed(() => ctx.value?.depot_roles || [])

// --- Menu tiles, grouped by workflow phase ---
// `key` matches the server's menu key (container_depot.ess.context._MENU). No role name
// appears here or anywhere else in the frontend — the server decides, this only renders.
const tiles = {
	gate: { key: "gate", to: "/gate", icon: "log-in", title: labels.gate, desc: labels.gateDesc, tile: "bg-brand-50 text-brand-600", wide: true },
	eir: { key: "eir", to: "/eir", icon: "clipboard", title: labels.eir, desc: labels.eirDesc, tile: "bg-leaf-50 text-leaf-600" },
	cleaning: { key: "cleaning", to: "/cleaning", icon: "droplet", title: labels.cleaningTitle, desc: labels.cleaningDesc, tile: "bg-brand-50 text-brand-600" },
	mr: { key: "mr", to: "/mr", icon: "tool", title: labels.mrTitleFull, desc: labels.mrDesc, tile: "bg-leaf-50 text-leaf-600" },
	monitor: { key: "monitor", to: "/monitor", icon: "grid", title: labels.monitorTitle, desc: labels.monitorDesc, tile: "bg-brand-50 text-brand-600" },
	surveyPos: { key: "surveyPos", to: "/survey-position", icon: "map-pin", title: labels.surveyPosTitle, desc: labels.surveyPosDesc, tile: "bg-amber-50 text-amber-600" },
	posFix: { key: "posFix", to: "/position-fix", icon: "check-circle", title: labels.posFixTitle, desc: labels.posFixDesc, tile: "bg-leaf-50 text-leaf-600" },
}
const allMenuGroups = [
	{ title: labels.grpGate, items: [tiles.gate] },
	{ title: labels.grpInspeksi, items: [tiles.eir] },
	{ title: labels.grpPerawatan, items: [tiles.cleaning, tiles.mr] },
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
	// The only Riwayat with two owners: it lists both halves of the position-survey workflow
	// and is where either one is reopened, so it is offered to whichever menu the account has.
	{ keys: ["surveyPos", "posFix"], to: "/survey-position/history", icon: "map-pin", title: labels.surveyPosHistoryTitle },
	{ key: "monitor", to: "/monitor/history", icon: "activity", title: labels.monitorHistoryTitle },
]
const history = computed(() =>
	allHistory.filter((h) => (h.keys || [h.key]).some((k) => menu.has(k)))
)
</script>
