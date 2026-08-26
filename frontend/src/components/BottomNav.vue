<template>
	<nav
		class="fixed inset-x-0 bottom-0 z-30 border-t border-gray-200 bg-white/95 pb-safe-bottom backdrop-blur-md"
	>
		<!-- `overflow-x-auto` + a per-tab floor rather than a hard cap on how many tabs may
		     show: SPV Lapangan holds every menu, and squeezing nine tabs into a handset width
		     turns the labels into unreadable slivers. Everyone else holds three or four and
		     never sees a scrollbar, because `flex-1` still spreads them edge to edge. -->
		<div class="mx-auto flex max-w-2xl items-stretch justify-around overflow-x-auto px-1">
			<router-link
				v-for="t in tabs"
				:key="t.to"
				:to="t.to"
				class="group flex min-w-[3.75rem] flex-1 flex-col items-center gap-1 py-1.5 transition-colors"
				:class="isActive(t) ? 'text-brand-600' : 'text-gray-400 hover:text-gray-600'"
			>
				<span
					class="oak-icon-tile h-8 w-10 transition-colors"
					:class="isActive(t) ? 'bg-brand-50' : 'bg-transparent'"
				>
					<Icon :name="t.icon" :size="20" :stroke="isActive(t) ? 2.4 : 2" />
				</span>
				<span class="text-center text-[11px] font-semibold leading-tight">{{ t.label }}</span>
			</router-link>
		</div>
	</nav>
</template>

<script setup>
import { computed, onMounted } from "vue"
import { useRoute } from "vue-router"
import Icon from "@/components/Icon.vue"
import { fetchMenu, menu } from "@/data/menu"
import { labels } from "@/utils/labels"

const route = useRoute()

// `key` is the server's menu key (container_depot.ess.context._MENU), exactly as Home's
// tiles use it — the two surfaces must agree, or the bar offers a tab the router guard
// then bounces back to Home. A tab with no key is unconditional: Beranda and Profil are
// the two pages every logged-in account may open, menu or no menu.
const allTabs = [
	{ to: "/", icon: "home", label: labels.navHome },
	{ key: "gate", to: "/gate", icon: "log-in", label: labels.navGate },
	{ key: "eir", to: "/eir", icon: "clipboard", label: labels.navEir },
	{ key: "cleaning", to: "/cleaning", icon: "droplet", label: labels.navCleaning },
	{ key: "mr", to: "/mr", icon: "tool", label: labels.navMr },
	{ key: "monitor", to: "/monitor", icon: "grid", label: labels.navMonitor || labels.monitorTitle },
	// The two halves of the position-survey workflow. One doctype, two menu keys, and almost
	// nobody holds both — Team Survey sees "Survey", Team Kalmar sees "Fix".
	{ key: "surveyPos", to: "/survey-position", icon: "map-pin", label: labels.navSurveyPos },
	{ key: "posFix", to: "/position-fix", icon: "check-circle", label: labels.navPosFix },
	{ to: "/profile", icon: "user", label: labels.navProfile },
]

// Until the menu resolves, `menu.has` is false for everything and the bar shows just the
// two unconditional tabs. Fail-closed, same call as data/menu.js: a tab that appears and
// then vanishes is better than one that 403s on tap.
const tabs = computed(() => allTabs.filter((t) => !t.key || menu.has(t.key)))

// The bar outlives any single page, so it cannot rely on Home or the router guard having
// fetched the menu — landing straight on /profile runs neither. Cached, so this is free
// whenever one of them got there first.
onMounted(fetchMenu)

function isActive(t) {
	const p = route.path
	if (t.to === "/") return p === "/"
	if (t.to === "/eir") return p === "/eir" // not /eir/history
	// Same reason as /eir: Riwayat Survey Posisi is its own screen, reached from the header,
	// and lighting the Survey tab there would claim the operator is in the worklist.
	if (t.to === "/survey-position") return p === "/survey-position"
	return p === t.to || p.startsWith(t.to + "/")
}
</script>
