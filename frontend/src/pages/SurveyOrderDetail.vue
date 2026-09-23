<template>
	<div class="mx-auto w-full max-w-lg space-y-4 md:max-w-2xl">
		<div class="flex items-center gap-2">
			<button
				class="oak-press flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-gray-500"
				:aria-label="labels.surveyPosBack"
				@click="goBack"
			>
				<Icon name="chevron-left" :size="22" />
			</button>
			<h1 class="min-w-0 flex-1 truncate text-lg font-extrabold tracking-tight text-gray-900">
				{{ labels.svDetailTitle }}
			</h1>
			<span v-if="order" class="oak-chip shrink-0" :class="orderChipClass">{{ orderStatusLabel }}</span>
		</div>

		<SkeletonDetail v-if="pending" :cells="4" :sections="2" />

		<section v-else-if="failed" class="oak-card space-y-3 p-6 text-center">
			<span class="oak-icon-tile mx-auto h-12 w-12 bg-red-50 text-red-500">
				<Icon name="alert-triangle" :size="24" />
			</span>
			<p class="text-sm text-gray-600">{{ error }}</p>
			<div class="flex gap-2">
				<button class="oak-btn oak-btn-secondary flex-1" @click="goBack">{{ labels.surveyPosBack }}</button>
				<button class="oak-btn oak-btn-primary flex-1" @click="load">{{ labels.retry }}</button>
			</div>
		</section>

		<template v-else-if="order">
			<!-- Kepala hari kerja: milik siapa tank-nya, siapa yang mensurvey, kapan truknya
			     datang. Tiga tanggal itu berdampingan dalam satu baris karena ketiganya dibaca
			     bersamaan — surveyor memutuskan berangkat hari ini atau besok dari selisihnya. -->
			<section class="oak-card space-y-3 p-4">
				<!-- Info yang sama persis dengan kartunya di list — satu komponen, supaya yang
				     dicocokkan di list masih ada saat detailnya dibuka. -->
				<SurveyOrderInfo :o="order" />
				<div class="grid grid-cols-2 gap-2 border-t border-gray-100 pt-3">
					<div class="min-w-0">
						<p class="text-[11px] text-gray-400">{{ labels.svScheduleDate }}</p>
						<p class="truncate text-sm font-bold text-gray-900">{{ fmtDate(order.survey_date) }}</p>
					</div>
					<div class="min-w-0">
						<p class="text-[11px] text-gray-400">{{ labels.svPickupDate }}</p>
						<p class="truncate text-sm font-bold text-gray-900">{{ order.plan_date ? fmtDate(order.plan_date) : "—" }}</p>
					</div>
				</div>
				<!-- Siapa yang membuat jadwal ini, dan siapa yang sudah turun tangan di yard. -->
				<div class="space-y-1 border-t border-gray-100 pt-3 text-xs">
					<p class="flex gap-2">
						<span class="w-24 shrink-0 text-gray-400">{{ labels.svCreatedBy }}</span>
						<span class="min-w-0 text-gray-700">
							<span class="font-semibold">{{ order.created_by || "—" }}</span>
							<span v-if="order.created_on" class="text-gray-400"> · {{ fmtDateTime(order.created_on) }}</span>
						</span>
					</p>
					<p class="flex gap-2">
						<span class="w-24 shrink-0 text-gray-400">{{ labels.svWorkedBy }}</span>
						<span class="min-w-0 font-semibold" :class="order.worked_by?.length ? 'text-gray-700' : 'text-gray-400'">
							{{ order.worked_by?.length ? order.worked_by.join(", ") : labels.svNotStarted }}
						</span>
					</p>
				</div>
			</section>

			<!-- Three counts, in the order the day is worked: what is down, what is still up,
			     what is finished. The middle number is the one that means "go and do
			     something", so it gets the warm colour. -->
			<!-- Tiga angka = filter daftar tank di bawahnya: ketuk untuk menyaring, ketuk lagi
			     untuk kembali ke semua. "Lowered" menghitung yang sudah turun termasuk yang sudah
			     disurvey (lowered_count), jadi saringannya juga begitu — angka dan isi daftar
			     harus selalu sama. -->
			<section class="grid grid-cols-2 gap-2">
				<button
					v-for="c in countTiles"
					:key="c.key"
					class="oak-card oak-press space-y-0.5 p-3 text-center transition"
					:class="tankFilter === c.key ? 'border-brand-500 bg-brand-500/10' : ''"
					:aria-pressed="tankFilter === c.key"
					@click="tankFilter = tankFilter === c.key ? '' : c.key"
				>
					<p class="text-2xl font-extrabold" :class="c.tone">{{ c.count }}</p>
					<p class="text-[10px] font-semibold uppercase tracking-wide" :class="tankFilter === c.key ? 'text-brand-700' : 'text-gray-400'">
						{{ c.label }}
					</p>
				</button>
			</section>

			<section class="oak-section space-y-3">
				<div class="flex items-center justify-between">
					<div class="flex items-center gap-2">
						<Icon name="package" :size="16" class="text-brand-500" />
						<p class="oak-section-title">{{ labels.surveyOrderTanksTitle }}</p>
					</div>
					<span class="text-xs text-gray-400">
						{{ order.tank_count || 0 }} {{ labels.surveyOrderTankTotal }}
					</span>
				</div>

				<!-- Filter aktif harus kelihatan, bukan cuma lewat kotak yang menyala di atas:
				     tanpa ini daftar yang kosong terbaca "jadwal ini tidak punya tank". -->
				<div
					v-if="tankFilter"
					class="flex items-center gap-2 rounded-xl border border-brand-300 bg-brand-500/10 py-1.5 pl-3 pr-1.5"
				>
					<Icon name="filter" :size="14" class="shrink-0 text-brand-600" />
					<p class="min-w-0 flex-1 text-xs text-brand-700">
						<span class="font-bold">{{ activeTile?.label }}</span>
						· {{ fill(labels.svFilterShown, { n: shownTanks.length, total: order.tanks.length }) }}
					</p>
					<button class="oak-press flex min-h-[36px] shrink-0 items-center gap-1 rounded-lg px-2 text-xs font-bold text-brand-700" @click="tankFilter = ''">
						<Icon name="x" :size="14" /> {{ labels.monitorFilterReset }}
					</button>
				</div>

				<div v-if="!shownTanks.length" class="space-y-2 py-4 text-center">
					<p class="text-sm text-gray-400">
						{{ tankFilter ? labels.svFilterEmpty : labels.surveyOrderEmptyTanks }}
					</p>
					<button v-if="tankFilter" class="oak-btn oak-btn-secondary min-h-[44px] px-4" @click="tankFilter = ''">
						{{ labels.svFilterShowAll }}
					</button>
				</div>
				<ul v-else class="divide-y divide-gray-100">
					<li v-for="t in shownTanks" :key="t.name" class="flex items-center gap-2">
						<router-link
							:to="`/survey-orders/tank/${t.name}`"
							class="oak-press flex min-w-0 flex-1 items-center gap-3 py-2.5"
						>
							<span class="oak-icon-tile h-9 w-9 shrink-0" :class="tileClass(t.status)">
								<Icon :name="statusIcon(t.status)" :size="16" />
							</span>
							<div class="min-w-0 flex-1">
								<p class="truncate font-semibold text-gray-900">{{ t.container_no || t.container }}</p>
								<!-- Read live off the Container master, with its age: this screen is the
								     one place a surveyor decides which stack to walk to, and a place
								     without a date is a guess dressed as an instruction. -->
								<p class="flex items-center gap-1.5 text-[11px]">
									<span class="truncate" :class="t.located ? 'text-gray-600' : 'text-red-500'">
										{{ t.located ? t.location_note : labels.tankPosUnlocated }}
									</span>
									<span v-if="t.located" class="shrink-0" :class="needsPos(t) ? 'text-amber-600 font-semibold' : 'text-gray-400'">
										· {{ since(t.location_updated_on) }}
									</span>
								</p>
								<!-- When the tank came down, and how long ago. A lowered tank is the
								     surveyor's cue to walk over and is blocking the reachstacker's next
								     move, so "sudah lowered" alone is not enough: one from ten minutes
								     ago and one from three days ago are different jobs. -->
								<p v-if="t.lowered_on" class="mt-0.5 flex items-start gap-1 text-[11px] text-leaf-600">
									<Icon name="arrow-down-circle" :size="11" class="mt-0.5 shrink-0" />
									<span class="min-w-0">
										{{ stamp(t.lowered_on) }}<template v-if="t.lowered_by_name"> · {{ t.lowered_by_name }}</template>
									</span>
								</p>
								<p v-if="t.surveyed_on" class="mt-0.5 flex items-start gap-1 text-[11px] text-brand-600">
									<Icon name="check-circle" :size="11" class="mt-0.5 shrink-0" />
									<span class="min-w-0">
										{{ stamp(t.surveyed_on) }}<template v-if="t.surveyed_by_name"> · {{ t.surveyed_by_name }}</template>
									</span>
								</p>
							</div>
							<span class="oak-chip shrink-0" :class="chipClass(t.status)">{{ statusLabel(t.status) }}</span>
							<Icon v-if="!(canLower && t.status === WAITING) && !(canPos && needsPos(t))" name="chevron-right" :size="16" class="shrink-0 text-gray-300" />
						</router-link>
						<!-- Pin = posisi belum ada / sudah basi: buka Letak Tank untuk tank ini. -->
						<router-link
							v-if="canPos && needsPos(t)"
							:to="`/tank-position?c=${encodeURIComponent(t.container)}`"
							class="oak-press flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border-2 border-amber-400 text-amber-600"
							:aria-label="`${labels.svPosUpdate} ${t.container_no || ''}`"
						>
							<Icon name="map-pin" :size="20" />
						</router-link>
						<!-- Centang = selesai lowering, langsung dari sini (Kalmar / Team Survey). -->
						<button
							v-if="canLower && t.status === WAITING"
							class="oak-press flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border-2 border-leaf-500 text-leaf-600 disabled:opacity-40"
							:aria-label="`${labels.tankMarkLowered} ${t.container_no || ''}`"
							:disabled="busy.has(t.name)"
							@click="tick(t)"
						>
							<Icon :name="busy.has(t.name) ? 'loader' : 'check'" :size="20" :class="busy.has(t.name) ? 'animate-spin' : ''" />
						</button>
					</li>
				</ul>
			</section>

			<!-- Berapa yang sudah bisa dikerjakan surveyor, dan syarat menutup harinya. Tanpa
			     kalimat kedua, sebuah hari dengan satu tank siap terbaca seolah surveynya sudah
			     bisa ditutup. -->
			<div v-if="readyCount" class="flex gap-2 rounded-xl border border-amber-200 bg-amber-50 p-3">
				<Icon name="info" :size="16" class="mt-0.5 shrink-0 text-amber-600" />
				<div class="min-w-0">
					<p class="text-xs font-bold text-amber-900">{{ fill(labels.svReadyNote, { n: readyCount }) }}</p>
					<p class="mt-0.5 text-[11px] text-amber-800">{{ labels.svReadyNoteHint }}</p>
				</div>
			</div>

			<!-- Satu tombol ke pekerjaan berikutnya: tank yang paling siap disentuh. Sebuah
			     daftar yang setiap barisnya bisa ditekan tetap butuh ini di HP — jempol ada di
			     bawah layar, daftarnya di atas. -->
			<div v-if="nextTank" class="oak-footer">
				<router-link
					:to="`/survey-orders/tank/${nextTank.name}`"
					class="oak-btn oak-btn-primary min-h-[52px] w-full text-base"
				>
					{{ fill(labels.svOpenTank, { no: nextTank.container_no || nextTank.container }) }}
				</router-link>
			</div>
		</template>
	</div>
</template>

<script setup>
import { computed, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import { labels } from "@/utils/labels"
import Icon from "@/components/Icon.vue"
import SkeletonDetail from "@/components/SkeletonDetail.vue"
import SurveyOrderInfo from "@/components/SurveyOrderInfo.vue"
import { cachedResource } from "@/data/cache"
import { session } from "@/data/session"
import { menu } from "@/data/menu"
import { lowerTank } from "@/utils/lowering"
import {
	DONE,
	LOWERED,
	WAITING,
	chipClass,
	fmtDate,
	fmtDateTime,
	since,
	stamp,
	statusIcon,
	statusLabel,
	tileClass,
} from "@/utils/surveyStatus"

const route = useRoute()
const router = useRouter()

const order = ref(null)

function fill(tpl, vars) {
	return Object.entries(vars).reduce((s, [k, v]) => s.replace(`{${k}}`, v), tpl)
}
const pending = ref(true)
const failed = ref(false)
const error = ref("")

const res = cachedResource({
	url: "container_depot.ess.tank_survey.survey_order_detail",
	method: "GET",
	onSuccess(data) {
		pending.value = false
		failed.value = false
		order.value = data
	},
	// Inline, never a toast: a toast disappears and would leave the surveyor on a blank
	// screen with nothing to press.
	onError(err) {
		pending.value = false
		failed.value = true
		error.value = err?.messages?.[0] || err?.message || labels.error
	},
})

function load() {
	pending.value = true
	failed.value = false
	res.submit({ name: route.params.name })
}

// Re-fetched on every entry, including coming BACK from a tank whose status was just
// changed — the counts above are the whole reason this screen exists, and a cached copy
// would show the day as unfinished seconds after it was finished.
watch(() => route.params.name, load, { immediate: true })

// Filter daftar tank dari tiga kotak angka. Default kosong = semua. Disimpan di perangkat,
// dikunci per user, sama seperti filter list — satu pilihan untuk semua jadwal.
const TANK_FILTER_KEY = `oak-survey-tank-filter:${session.user || ""}`
const tankFilter = ref(readTankFilter())
function readTankFilter() {
	try {
		const v = localStorage.getItem(TANK_FILTER_KEY) || ""
		return ["lowered", "waiting", "done", "pos"].includes(v) ? v : ""
	} catch {
		return ""
	}
}
watch(tankFilter, (v) => {
	try {
		localStorage.setItem(TANK_FILTER_KEY, v)
	} catch {
		/* mode privat: filter tetap berlaku sampai halaman ditutup */
	}
})

// Centang lowering dari daftar tank. Gerbang yang sama dengan detail tank; server tetap
// memeriksa ulang.
const canLower = computed(() => menu.has("posFix") || menu.has("surveyPos"))
const busy = ref(new Set())
async function tick(t) {
	if (busy.value.has(t.name)) return
	busy.value = new Set(busy.value).add(t.name)
	const ok = await lowerTank(t)
	const next = new Set(busy.value)
	next.delete(t.name)
	busy.value = next
	// Muat ulang diam-diam — tanpa skeleton, supaya daftarnya tidak berkedip tiap centang.
	if (ok) res.submit({ name: route.params.name })
}
// Posisi perlu diperbarui: belum pernah dicatat, atau catatannya lebih tua dari batas ini —
// hanya untuk tank yang masih akan didatangi (belum selesai survey).
const POS_STALE_HOURS = 24
const needsPos = (t) =>
	[WAITING, LOWERED].includes(t.status) && (!t.located || t.hours == null || t.hours > POS_STALE_HOURS)
const canPos = computed(() => menu.has("tankPos"))

const TANK_FILTER = {
	lowered: (t) => t.status === LOWERED || t.status === DONE,
	waiting: (t) => t.status === WAITING,
	done: (t) => t.status === DONE,
	pos: needsPos,
}
const shownTanks = computed(() => {
	const tanks = order.value?.tanks || []
	return tankFilter.value ? tanks.filter(TANK_FILTER[tankFilter.value]) : tanks
})
const activeTile = computed(() => countTiles.value.find((c) => c.key === tankFilter.value))
// Urutan kotak (2×2 di HP) ditentukan user: Perlu update posisi, Menunggu Lowering / Survey Done, Lowered.
const countTiles = computed(() => [
	{ key: "pos", label: labels.svPosNeeded, count: (order.value?.tanks || []).filter(needsPos).length, tone: "text-red-600" },
	{ key: "waiting", label: labels.surveyPosStatusWaiting, count: order.value?.waiting_count || 0, tone: "text-amber-600" },
	{ key: "done", label: labels.surveyPosStatusDone, count: order.value?.survey_done_count || 0, tone: "text-brand-600" },
	{ key: "lowered", label: labels.surveyPosStatusLowered, count: order.value?.lowered_count || 0, tone: "text-leaf-600" },
])

const orderStatusLabel = computed(() => {
	const map = {
		Scheduled: labels.surveyOrderStatusScheduled,
		"In Progress": labels.surveyOrderStatusProgress,
		Completed: labels.surveyOrderStatusCompleted,
		Cancelled: labels.surveyOrderStatusCancelled,
	}
	return map[order.value?.status] || order.value?.status || "—"
})

const orderChipClass = computed(() => {
	const map = {
		Scheduled: "bg-blue-100 text-blue-700",
		"In Progress": "bg-amber-100 text-amber-800",
		Completed: "bg-leaf-100 text-leaf-700",
		Cancelled: "bg-red-100 text-red-700",
	}
	return map[order.value?.status] || "bg-gray-100 text-gray-600"
})

// Berapa tank yang sudah di bawah dan menunggu surveyor.
const readyCount = computed(
	() => (order.value?.tanks || []).filter((t) => t.status === "Lowered").length
)
// Tank berikutnya yang pantas dibuka: yang sudah siap disurvey lebih dulu, kalau tidak ada
// yang masih menunggu diturunkan. Bukan sekadar baris pertama — urutan daftar mengikuti
// jadwal, sementara tombol ini mengikuti pekerjaan.
const nextTank = computed(() => {
	const tanks = order.value?.tanks || []
	return (
		tanks.find((t) => t.status === "Lowered") ||
		tanks.find((t) => t.status === "Waiting Lowering") ||
		null
	)
})

function goBack() {
	// Back to the calendar on the day this schedule belongs to, not to whatever the history
	// stack happens to hold — a deep link from the bell has no list behind it.
	if (window.history.length > 1) router.back()
	else router.push("/survey-orders")
}
</script>
