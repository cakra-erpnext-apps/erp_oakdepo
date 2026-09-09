<template>
	<nav
		ref="bar"
		class="fixed inset-x-0 bottom-0 z-30 border-t border-gray-200 bg-paper/95 pb-safe-bottom backdrop-blur-md"
	>
		<!-- Exactly five slots, always: Beranda, up to three of this account's own screens,
		     and Lainnya. The bar used to grow a tab per menu, which meant SPV Lapangan (who
		     holds every menu) got nine slivers of unreadable text across a handset. Anything
		     that does not fit lives one tap away in the sheet, whole. -->
		<div class="mx-auto flex max-w-2xl items-stretch justify-around px-1">
			<router-link
				v-for="t in tabs"
				:key="t.to"
				:to="t.to"
				class="group flex flex-1 flex-col items-center gap-1 py-1.5 transition-colors"
				:class="isActive(t) ? 'text-brand-600' : 'text-gray-400 hover:text-gray-600'"
			>
				<span
					class="oak-icon-tile h-8 w-10 transition-colors"
					:class="isActive(t) ? 'bg-brand-50' : 'bg-transparent'"
				>
					<Icon :name="t.icon" :size="20" :stroke="isActive(t) ? 2.4 : 2" />
				</span>
				<span class="text-center text-[11px] font-semibold leading-tight">{{ t.title }}</span>
			</router-link>

			<button
				class="flex flex-1 flex-col items-center gap-1 py-1.5 transition-colors"
				:class="moreActive ? 'text-brand-600' : 'text-gray-400'"
				:aria-expanded="moreOpen"
				@click="moreOpen = true"
			>
				<span
					class="oak-icon-tile h-8 w-10 transition-colors"
					:class="moreActive ? 'bg-brand-50' : 'bg-transparent'"
				>
					<Icon name="more-horizontal" :size="20" :stroke="moreActive ? 2.4 : 2" />
				</span>
				<span class="text-center text-[11px] font-semibold leading-tight">{{ labels.navMore }}</span>
			</button>
		</div>
	</nav>

	<MoreSheet :open="moreOpen" :exclude="tabKeys" @close="moreOpen = false" />
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue"
import { useRoute } from "vue-router"
import Icon from "@/components/Icon.vue"
import MoreSheet from "@/components/MoreSheet.vue"
import { fetchMenu, menu } from "@/data/menu"
import { TAB_ORDER, modulesFor } from "@/data/modules"
import { labels } from "@/utils/labels"

const route = useRoute()
const moreOpen = ref(false)

// Tapping a tab from inside the sheet has to leave the sheet behind.
watch(() => route.fullPath, () => (moreOpen.value = false))

// Tinggi bar ini — termasuk safe-area handset — diumumkan ke seluruh aplikasi sebagai
// --oak-bottom-h, supaya aksi yang menempel di bawah halaman (.oak-footer) duduk DI ATAS
// bar, bukan di belakangnya. Diukur, bukan ditebak: tinggi safe area berbeda per HP, dan
// label tab bisa membungkus jadi dua baris.
const bar = ref(null)
let ro = null
onMounted(() => {
	if (!bar.value || typeof ResizeObserver === "undefined") return
	ro = new ResizeObserver(([entry]) => {
		const h = entry.borderBoxSize?.[0]?.blockSize ?? entry.target.getBoundingClientRect().height
		document.documentElement.style.setProperty("--oak-bottom-h", `${Math.round(h)}px`)
	})
	ro.observe(bar.value)
})
onBeforeUnmount(() => {
	ro?.disconnect()
	document.documentElement.style.removeProperty("--oak-bottom-h")
})

// How many of the account's own screens sit in the bar, next to Beranda and Lainnya.
const WORK_TABS = 3

// Beranda is unconditional: it is the one page every logged-in account may open, menu or no
// menu, and the empty state lives there.
const home = { to: "/", icon: "home", title: labels.navHome }

// Until the menu resolves, `menu.has` is false for everything and the bar is just Beranda +
// Lainnya. Fail-closed, same call as data/menu.js: a tab that appears and then vanishes is
// better than one that 403s on tap.
const workTabs = computed(() => modulesFor(TAB_ORDER, menu).slice(0, WORK_TABS))
const tabs = computed(() => [home, ...workTabs.value])
const tabKeys = computed(() => workTabs.value.map((t) => t.key))

// The bar outlives any single page, so it cannot rely on Beranda or the router guard having
// fetched the menu — landing straight on /profile runs neither. Cached, so this is free
// whenever one of them got there first.
onMounted(fetchMenu)

function isActive(t) {
	const p = route.path
	if (t.to === "/") return p === "/"
	if (t.to === "/eir") return p === "/eir" // not /eir/history
	// Same reason as /eir: Riwayat Survey Posisi is its own screen, reached from the header,
	// and lighting the Survey tab there would claim the operator is in the list.
	if (t.to === "/survey-orders") return p === "/survey-orders"
	return p === t.to || p.startsWith(t.to + "/")
}

// Lainnya lights up while the sheet is open AND whenever the operator is on a screen the bar
// has no tab for (Profil, Jadwal, a module that did not fit) — that is where they came in
// from, so the bar should not read as if they were nowhere.
const moreActive = computed(
	() => moreOpen.value || (menu.ready && !tabs.value.some((t) => isActive(t)))
)
</script>
