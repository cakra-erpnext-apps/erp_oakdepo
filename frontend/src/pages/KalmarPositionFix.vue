<template>
	<div class="mx-auto w-full max-w-lg space-y-4 md:max-w-2xl">
		<div class="flex items-start justify-between gap-3">
			<div class="min-w-0">
				<h1 class="text-xl font-extrabold tracking-tight text-gray-900">{{ labels.lowTitle }}</h1>
				<p class="mt-0.5 truncate text-xs text-gray-500">{{ labels.lowHint }}</p>
			</div>
			<router-link to="/survey-orders/history" class="oak-btn oak-btn-secondary min-h-[44px] shrink-0 px-3">
				<Icon name="clock" :size="15" /> {{ labels.navHistory }}
			</router-link>
		</div>

		<div class="relative">
			<Icon name="search" :size="18" class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
			<input
				v-model="search"
				type="search"
				:placeholder="labels.lowSearch"
				class="oak-input pl-10 pr-10 uppercase"
				autocapitalize="characters"
				autocorrect="off"
				spellcheck="false"
				@input="onSearchInput"
			/>
			<button
				v-if="search"
				class="oak-press absolute right-2 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-full text-gray-400"
				:aria-label="labels.tplCancel"
				@click="clearSearch"
			>
				<Icon name="x" :size="16" />
			</button>
		</div>

		<!-- Hasil pencarian menggantikan papan: yang mengetik nomor sedang mencari satu tank. -->
		<template v-if="search.trim()">
			<ul v-if="searchRows.length" class="oak-card divide-y divide-gray-100 overflow-hidden">
				<TankRow v-for="r in searchRows" :key="r.name" :row="r" tone="waiting" />
			</ul>
			<div v-else-if="!searchRes.loading" class="oak-card p-8 text-center text-sm text-gray-400">
				{{ labels.posFixEmpty }}
			</div>
		</template>

		<template v-else>
			<!-- Empat angka yang bisa dipencet. "Mendesak" dipisah dari "Menunggu" karena
			     antrean yang mengurut apa adanya menyembunyikan tank yang truknya datang besok
			     di tengah dua puluh tank yang truknya bulan depan. -->
			<div class="grid grid-cols-4 gap-1.5">
				<button
					v-for="s in stats"
					:key="s.key"
					class="oak-press flex min-h-[68px] flex-col items-center justify-center rounded-xl border px-1 py-2 transition"
					:class="pillClass(s)"
					:aria-pressed="group === s.key"
					@click="setGroup(s.key)"
				>
					<span class="text-lg font-extrabold leading-none" :class="group === s.key ? 'text-brand-700' : s.tone">
						{{ s.count }}
					</span>
					<span class="mt-1 truncate text-[11px] font-semibold" :class="group === s.key ? 'text-brand-700' : 'text-gray-500'">
						{{ s.label }}
					</span>
				</button>
			</div>

			<div v-if="boardRes.loading && !board" class="oak-card space-y-3 p-4">
				<div class="oak-skeleton h-4 w-2/3"></div>
				<div class="oak-skeleton h-4 w-1/2"></div>
			</div>

			<div
				v-else-if="board && !board.urgent.length && !board.waiting.length && !board.lowered.length"
				class="oak-card flex flex-col items-center gap-2 p-8 text-center"
			>
				<span class="oak-icon-tile h-12 w-12 bg-gray-100 text-gray-300"><Icon name="arrow-down-circle" :size="24" /></span>
				<p class="text-sm font-bold text-gray-900">{{ labels.lowEmpty }}</p>
				<p class="text-xs text-gray-500">{{ labels.lowEmptyHint }}</p>
				<router-link to="/survey-orders" class="oak-btn oak-btn-secondary mt-1 min-h-[44px] px-4">
					{{ labels.lowEmptyCta }}
				</router-link>
			</div>

			<template v-else-if="board">
				<section v-if="board.urgent.length" class="space-y-1.5">
					<div class="flex items-baseline justify-between gap-2 px-1">
						<p class="text-xs font-bold text-red-600">{{ labels.lowSecUrgent }} · {{ board.counts.urgent }}</p>
						<p class="truncate text-[11px] text-gray-400">
							{{ fill(labels.lowSecUrgentHint, { n: board.urgent_days }) }}
						</p>
					</div>
					<ul class="oak-card divide-y divide-gray-100 overflow-hidden border-red-200">
						<TankRow v-for="r in board.urgent" :key="r.name" :row="r" tone="urgent" />
					</ul>
				</section>

				<section v-if="board.waiting.length" class="space-y-1.5">
					<p class="px-1 text-xs font-bold text-gray-500">
						{{ labels.lowSecWaiting }} · {{ board.counts.waiting }}
					</p>
					<ul class="oak-card divide-y divide-gray-100 overflow-hidden">
						<TankRow v-for="r in board.waiting" :key="r.name" :row="r" tone="waiting" />
					</ul>
					<button
						v-if="markable.length > 1"
						class="oak-btn oak-btn-secondary min-h-[48px] w-full"
						@click="bulkFrom(markable)"
					>
						{{ fill(labels.lowMarkMany, { n: markable.length }) }}
					</button>
				</section>

				<!-- Bukan pekerjaan, melainkan bukti bahwa shift ini menghasilkan sesuatu: tanpa
				     ini operator yang sudah menurunkan lima tank melihat layar yang sama saja. -->
				<section v-if="board.lowered.length" class="space-y-1.5">
					<div class="flex items-baseline justify-between gap-2 px-1">
						<p class="text-xs font-bold text-gray-500">{{ labels.lowSecToday }} · {{ board.counts.lowered }}</p>
						<router-link to="/survey-orders/history" class="shrink-0 text-[11px] font-bold text-brand-600">
							{{ svMore }}
						</router-link>
					</div>
					<ul class="oak-card divide-y divide-gray-100 overflow-hidden">
						<TankRow v-for="r in board.lowered" :key="r.name" :row="r" tone="done" />
					</ul>
				</section>
			</template>
		</template>
	</div>
</template>

<script setup>
import { computed, h, onMounted, onBeforeUnmount, ref } from "vue"
import { useRoute, useRouter } from "vue-router"
import { RouterLink } from "vue-router"
import { labels } from "@/utils/labels"
import { since } from "@/utils/surveyStatus"
import { setLoweringPreselect } from "@/utils/positionPick"
import Icon from "@/components/Icon.vue"
import LiftOnBadge from "@/components/LiftOnBadge.vue"
import { cachedResource } from "@/data/cache"

const route = useRoute()
const router = useRouter()

const svMore = labels.svMore

function fill(tpl, vars) {
	return Object.entries(vars).reduce((s, [k, v]) => s.replace(`{${k}}`, v), tpl)
}

// ---- papan ----
// Pil yang ditekan dikirim ke server, bukan disaring di klien: yang dijanjikan pil adalah
// angka penuh, dan menyaring delapan baris yang terlanjur diambil tidak akan sampai ke sana.
const group = ref("")
const boardRes = cachedResource({
	url: "container_depot.ess.tank_survey.lowering_board",
	method: "GET",
	makeParams: () => ({ group: group.value || "", limit: 8 }),
	auto: true,
})
const board = computed(() => (boardRes.data?.success ? boardRes.data : null))

const stats = computed(() => {
	const c = board.value?.counts || { all: 0, urgent: 0, waiting: 0, lowered: 0 }
	return [
		{ key: "all", label: labels.lowStatAll, count: c.all, tone: "text-gray-900" },
		{ key: "urgent", label: labels.lowStatUrgent, count: c.urgent, tone: "text-red-600" },
		{ key: "waiting", label: labels.lowStatWaiting, count: c.waiting, tone: "text-amber-600" },
		{ key: "lowered", label: labels.lowStatLowered, count: c.lowered, tone: "text-leaf-600" },
	]
})
function pillClass(s) {
	if (group.value === s.key) return "border-brand-500 bg-brand-500/10"
	if (s.key === "urgent" && s.count) return "border-red-300 bg-red-50"
	return "border-gray-200 bg-paper"
}
function setGroup(key) {
	group.value = group.value === key || key === "all" ? "" : key
	boardRes.reload()
}

// Yang bisa ditandai sekaligus: semua yang masih menunggu, mendesak maupun tidak.
const markable = computed(() => [...(board.value?.urgent || []), ...(board.value?.waiting || [])])
function bulkFrom(rows) {
	setLoweringPreselect(rows)
	router.push("/position-fix/bulk")
}

// ---- pencarian ----
const search = ref("")
const searchRes = cachedResource({
	url: "container_depot.ess.tank_survey.survey_waiting",
	method: "GET",
	makeParams: () => ({ search: search.value || "", page_length: 30 }),
})
const searchRows = computed(() => (search.value.trim() ? searchRes.data?.items || [] : []))
let searchTimer = null
function onSearchInput() {
	clearTimeout(searchTimer)
	searchTimer = setTimeout(() => search.value.trim() && searchRes.reload(), 300)
}
function clearSearch() {
	search.value = ""
}

// Satu baris tank, dipakai empat kali di atas. Ditulis sebagai render function di file yang
// sama karena ia tidak punya arti di luar layar ini — file terpisah cuma memindahkan tempat
// mencarinya.
const TONE = {
	urgent: "bg-red-50 text-red-600",
	waiting: "bg-amber-50 text-amber-600",
	done: "bg-leaf-50 text-leaf-600",
}
const TankRow = (p) => {
	const r = p.row
	const meta = [r.principal, r.days_to === null || r.days_to === undefined ? null : dueWord(r)]
		.filter(Boolean)
		.join(" · ")
	return h("li", {}, [
		h(
			RouterLink,
			{ to: `/survey-orders/tank/${r.name}`, class: "oak-press flex min-h-[64px] items-center gap-3 px-4 py-3" },
			() => [
				h("span", { class: `oak-icon-tile h-10 w-10 shrink-0 ${TONE[p.tone] || TONE.waiting}` }, [
					h(Icon, { name: p.tone === "done" ? "check" : "arrow-down", size: 17 }),
				]),
				h("span", { class: "min-w-0 flex-1" }, [
					h("span", { class: "flex items-center gap-2" }, [
						h(
							"span",
							{ class: "min-w-0 truncate font-mono text-sm font-extrabold text-gray-900" },
							r.container_no || r.container || labels.monitorNoNumber
						),
						r.located
							? h(
									"span",
									{ class: "oak-chip shrink-0 bg-gray-100 font-mono text-gray-600" },
									r.location_note
								)
							: null,
					]),
					h("span", { class: "block truncate text-[11px] text-gray-500" }, meta),
					h("span", { class: "mt-1 flex flex-wrap items-center gap-1.5" }, [
						r.reopen_note
							? h("span", { class: "oak-chip shrink-0 bg-orange-100 text-orange-800" }, labels.posReopenNote)
							: null,
						h(LiftOnBadge, {
							survey: r.target_survey_on,
							target: r.target_lift_on,
							urgent: r.target_urgent_on,
						}),
						p.tone === "done" && r.lowered_on
							? h("span", { class: "shrink-0 text-[11px] text-gray-400" }, since(r.lowered_on))
							: null,
					]),
				]),
				h(Icon, { name: "chevron-right", size: 18, class: "shrink-0 text-gray-300" }),
			]
		),
	])
}
TankRow.props = ["row", "tone"]

function dueWord(r) {
	const d = r.days_to
	if (d === null || d === undefined) return ""
	if (d < 0) return `${labels.lowPickup} lewat ${-d} hari`
	if (d === 0) return `${labels.lowPickup} hari ini`
	if (d === 1) return `${labels.lowPickup} besok`
	return `${labels.lowPickup} ${d} hari lagi`
}

// Deep link dari lonceng: `/position-fix?s=CPS-0001` langsung ke tank itu
// (ess/notification_routes._survey).
onMounted(() => {
	const s = route.query.s
	if (s) router.replace(`/survey-orders/tank/${String(s)}`)
})
onBeforeUnmount(() => clearTimeout(searchTimer))
</script>
