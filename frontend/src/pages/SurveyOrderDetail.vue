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
				<div class="flex items-start justify-between gap-3">
					<div class="min-w-0">
						<p class="truncate text-lg font-extrabold tracking-tight text-gray-900">
							{{ order.principal || order.booking || order.name }}
						</p>
						<p class="truncate text-xs text-gray-500">
							{{ labels.svListHint }}<template v-if="order.booking"> · {{ order.booking }}</template>
						</p>
						<!-- Dokumen survey milik customer/surveyor sendiri — sengaja terpisah dari
						     Reff Doc booking, karena kertasnya memang dua dan sering beda nomor. -->
						<p v-if="order.reff_doc" class="truncate font-mono text-[11px] text-gray-400">
							{{ labels.svReffDoc }}: {{ order.reff_doc }}
						</p>
					</div>
					<p class="shrink-0 font-mono text-[11px] text-gray-400">{{ order.name }}</p>
				</div>
				<div class="grid grid-cols-3 gap-2 border-t border-gray-100 pt-3">
					<div class="min-w-0">
						<p class="text-[11px] text-gray-400">{{ labels.svScheduleDate }}</p>
						<p class="truncate text-sm font-bold text-gray-900">{{ fmtDate(order.survey_date) }}</p>
					</div>
					<div class="min-w-0">
						<p class="text-[11px] text-gray-400">{{ labels.svPickupDate }}</p>
						<p class="truncate text-sm font-bold text-gray-900">{{ order.plan_date ? fmtDate(order.plan_date) : "—" }}</p>
					</div>
					<div class="min-w-0">
						<p class="text-[11px] text-gray-400">{{ labels.svSurveyor }}</p>
						<p class="truncate text-sm font-bold text-gray-900">{{ order.surveyor || "—" }}</p>
					</div>
				</div>
			</section>

			<!-- Three counts, in the order the day is worked: what is down, what is still up,
			     what is finished. The middle number is the one that means "go and do
			     something", so it gets the warm colour. -->
			<section class="grid grid-cols-3 gap-2">
				<div class="oak-card space-y-0.5 p-3 text-center">
					<p class="text-2xl font-extrabold text-leaf-600">{{ order.lowered_count || 0 }}</p>
					<p class="text-[10px] font-semibold uppercase tracking-wide text-gray-400">
						{{ labels.surveyPosStatusLowered }}
					</p>
				</div>
				<div class="oak-card space-y-0.5 p-3 text-center" :class="order.waiting_count ? 'border-amber-300' : ''">
					<p class="text-2xl font-extrabold text-amber-600">{{ order.waiting_count || 0 }}</p>
					<p class="text-[10px] font-semibold uppercase tracking-wide text-gray-400">
						{{ labels.surveyPosStatusWaiting }}
					</p>
				</div>
				<div class="oak-card space-y-0.5 p-3 text-center">
					<p class="text-2xl font-extrabold text-brand-600">{{ order.survey_done_count || 0 }}</p>
					<p class="text-[10px] font-semibold uppercase tracking-wide text-gray-400">
						{{ labels.surveyPosStatusDone }}
					</p>
				</div>
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

				<p v-if="!order.tanks.length" class="py-4 text-center text-sm text-gray-400">
					{{ labels.surveyOrderEmptyTanks }}
				</p>
				<ul v-else class="divide-y divide-gray-100">
					<li v-for="t in order.tanks" :key="t.name">
						<router-link
							:to="`/survey-orders/tank/${t.name}`"
							class="oak-press flex items-center gap-3 py-2.5"
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
									<span v-if="t.located" class="shrink-0" :class="t.fresh ? 'text-gray-400' : 'text-amber-600 font-semibold'">
										· {{ since(t.location_updated_on) }}
									</span>
								</p>
								<!-- When the tank came down, and how long ago. A lowered tank is the
								     surveyor's cue to walk over and is blocking the reachstacker's next
								     move, so "sudah lowered" alone is not enough: one from ten minutes
								     ago and one from three days ago are different jobs. -->
								<p v-if="t.lowered_on" class="mt-0.5 flex items-center gap-1 text-[11px] text-leaf-600">
									<Icon name="arrow-down-circle" :size="11" class="shrink-0" />
									<span class="truncate">{{ stamp(t.lowered_on) }}</span>
								</p>
							</div>
							<span class="oak-chip shrink-0" :class="chipClass(t.status)">{{ statusLabel(t.status) }}</span>
							<Icon name="chevron-right" :size="16" class="shrink-0 text-gray-300" />
						</router-link>
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
import { cachedResource } from "@/data/cache"
import { chipClass, fmtDate, since, stamp, statusIcon, statusLabel, tileClass } from "@/utils/surveyStatus"

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
		Scheduled: "bg-gray-100 text-gray-600",
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
