<template>
	<div class="mx-auto w-full max-w-lg space-y-3 md:max-w-2xl">
		<!-- Kepala: kembali, judul, dan status tank. Statusnya duduk di kepala, bukan di dalam
		     kartu, karena itu satu-satunya hal di layar ini yang harus terbaca sebelum apa pun
		     digulir — sisanya menjelaskan, yang ini menyimpulkan. -->
		<div class="flex items-center gap-2">
			<button class="oak-press flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-gray-500" :aria-label="labels.backBtn" @click="goBack">
				<Icon name="chevron-left" :size="22" />
			</button>
			<h1 class="min-w-0 flex-1 truncate text-lg font-extrabold tracking-tight text-gray-900">
				{{ labels.monitorDetailTitle }}
			</h1>
			<span v-if="tank" class="oak-chip shrink-0" :class="badge.tone">{{ badge.label }}</span>
		</div>

		<template v-if="detailRes.loading && !tank">
			<div class="oak-card space-y-3 p-4">
				<div class="oak-skeleton h-5 w-1/2"></div>
				<div class="oak-skeleton h-3 w-3/4"></div>
				<div class="oak-skeleton h-3 w-2/3"></div>
			</div>
		</template>

		<div v-else-if="!tank" class="oak-card flex flex-col items-center gap-2 p-8 text-center">
			<span class="oak-icon-tile h-12 w-12 bg-red-50 text-red-500"><Icon name="alert-circle" :size="24" /></span>
			<p class="text-sm font-bold text-gray-900">{{ labels.monitorErrorTitle }}</p>
			<button class="oak-btn oak-btn-primary mt-1 px-4 py-2" @click="detailRes.reload()">{{ labels.monitorRetry }}</button>
		</div>

		<template v-else>
			<!-- Identitas -->
			<section class="oak-card space-y-3 p-4">
				<div class="flex items-start justify-between gap-3">
					<p class="min-w-0 truncate font-mono text-xl font-extrabold tracking-tight text-gray-900">
						{{ tank.container_no || tank.name }}
					</p>
					<p v-if="tank.serial_no" class="shrink-0 font-mono text-xs text-gray-400">{{ tank.serial_no }}</p>
				</div>
				<p class="text-xs text-gray-500">{{ specLine }}</p>

				<!-- Tiga hal yang ditanyakan orang yang mencari tank ini secara fisik. -->
				<div class="grid grid-cols-3 gap-2 border-t border-gray-100 pt-3">
					<div class="min-w-0">
						<p class="text-[11px] text-gray-400">{{ labels.monitorDepotWord }}</p>
						<p class="truncate text-sm font-bold text-gray-900">{{ tank.depot || "—" }}</p>
					</div>
					<div class="min-w-0">
						<p class="text-[11px] text-gray-400">{{ labels.monitorLocationWord }}</p>
						<p class="truncate text-sm font-bold text-gray-900">{{ tank.location || "—" }}</p>
					</div>
					<div class="min-w-0">
						<p class="text-[11px] text-gray-400">{{ labels.monitorInDepot }}</p>
						<p class="truncate text-sm font-bold text-gray-900">
							{{ tank.in_depot_days === null || tank.in_depot_days === undefined ? "—" : fill(labels.monitorDays, { n: tank.in_depot_days }) }}
						</p>
					</div>
				</div>
			</section>

			<!-- Proses aktif -->
			<section class="oak-card overflow-hidden">
				<div class="flex items-baseline justify-between gap-2 px-4 pb-2 pt-3">
					<p class="text-sm font-extrabold text-gray-900">{{ labels.monitorProcessTitle }}</p>
					<p class="text-xs text-gray-400">{{ openOrders.length }}</p>
				</div>
				<p v-if="!openOrders.length" class="px-4 pb-4 text-xs text-gray-500">{{ labels.monitorProcessEmpty }}</p>
				<ul v-else class="divide-y divide-gray-100 border-t border-gray-100">
					<li v-for="o in openOrders" :key="o.doctype + o.name">
						<div
							class="flex items-center gap-3 px-4 py-3 transition active:bg-gray-50"
							:class="routeOf(o) ? 'cursor-pointer' : ''"
							:role="routeOf(o) ? 'button' : null"
							:tabindex="routeOf(o) ? 0 : null"
							@click="openOrder(o)"
							@keydown.enter="openOrder(o)"
						>
							<span class="oak-icon-tile h-9 w-9 shrink-0 bg-leaf-50 text-leaf-600">
								<Icon :name="orderIcon(o.label)" :size="16" />
							</span>
							<div class="min-w-0 flex-1">
								<p class="truncate text-sm font-bold text-gray-900">
									{{ o.label }} · <span class="font-mono">{{ o.name }}</span>
								</p>
								<p class="truncate text-[11px] text-gray-500">{{ orderLine(o) }}</p>
							</div>
							<Icon v-if="routeOf(o)" name="chevron-right" :size="16" class="shrink-0 text-gray-300" />
						</div>
					</li>
				</ul>
			</section>

			<!-- Letak di yard.
			     Mockup-nya menggambar petak blok/baris/slot. Petak itu TIDAK dibuat di sini dan
			     jangan ditambahkan tanpa modelnya: depot ini tidak menyimpan peta yard sejak
			     patch v0_36 menghapus zona & aturan penempatan, jadi kotak-kotak itu hanya bisa
			     digambar dengan menebak — sebuah peta yang salah dibaca sebagai peta yang benar,
			     dan orang berjalan ke tempat yang ditunjuknya. Yang ada dan benar adalah catatan
			     letak terakhir beserta umurnya. -->
			<section class="oak-card space-y-2 p-4">
				<div class="flex items-baseline justify-between gap-2">
					<p class="text-sm font-extrabold text-gray-900">{{ labels.monitorYardTitle }}</p>
					<p v-if="tank.location_updated_on" class="truncate text-[11px] text-gray-400">
						{{ since(tank.location_updated_on) }}
					</p>
				</div>
				<template v-if="tank.location">
					<p class="font-mono text-lg font-extrabold leading-tight text-gray-900">{{ tank.location }}</p>
					<p class="text-[11px] text-gray-500">
						{{ fill(labels.monitorYardRecorded, { t: fmtDateTime(tank.location_updated_on) }) }}
						<template v-if="tank.location_updated_by"> · {{ tank.location_updated_by }}</template>
					</p>
				</template>
				<p v-else class="text-xs text-gray-500">{{ labels.monitorYardEmpty }}</p>
				<router-link :to="{ path: '/tank-position', query: { c: tank.name } }" class="oak-btn oak-btn-secondary mt-1 w-full">
					<Icon name="map-pin" :size="15" /> {{ labels.monitorYardOpen }}
				</router-link>
			</section>

			<!-- Riwayat aktivitas -->
			<section class="oak-card overflow-hidden">
				<div class="flex items-baseline justify-between gap-2 px-4 pb-2 pt-3">
					<p class="text-sm font-extrabold text-gray-900">{{ labels.monitorActivityTitle }}</p>
					<p class="text-xs text-gray-400">{{ fill(labels.monitorActivityLast, { n: activities.length }) }}</p>
				</div>
				<p v-if="!activities.length" class="px-4 pb-4 text-xs text-gray-500">{{ labels.monitorActivityEmpty }}</p>
				<ol v-else class="space-y-3 px-4 pb-3 pt-1">
					<li v-for="(a, i) in activities" :key="a.name" class="relative flex gap-3">
						<!-- Garis penghubung berhenti di butir terakhir: garis yang menjuntai di
						     bawah butir terakhir menjanjikan baris yang tidak ada. -->
						<span
							v-if="i < activities.length - 1"
							class="absolute left-[5px] top-3 h-full w-px bg-gray-200"
						></span>
						<span class="relative mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full" :class="dotTone(a)"></span>
						<div class="min-w-0 flex-1">
							<p class="truncate text-xs font-bold text-gray-900" :class="a.voided ? 'line-through opacity-60' : ''">
								{{ a.summary || a.activity_type }}
							</p>
							<p class="truncate text-[11px] text-gray-400">
								{{ fmtDateTime(a.activity_time) }}<template v-if="a.performed_by"> · {{ a.performed_by }}</template>
							</p>
						</div>
					</li>
				</ol>
				<div class="border-t border-gray-100 px-4 py-3">
					<router-link
						:to="{ path: '/monitor/history', query: { c: tank.name } }"
						class="oak-btn oak-btn-secondary w-full"
					>
						{{ labels.monitorActivityAll }}
					</router-link>
				</div>
			</section>

			<!-- Kaki: riwayat lengkap + pekerjaan yang sedang berjalan (kalau ada). -->
			<div class="oak-footer flex gap-2">
				<router-link
					:to="{ path: '/monitor/history', query: { c: tank.name } }"
					class="oak-btn oak-btn-secondary min-h-[48px] flex-1"
				>
					{{ labels.monitorFullHistory }}
				</router-link>
				<button
					v-if="primaryOrder"
					class="oak-btn oak-btn-primary min-h-[48px] flex-1"
					@click="openOrder(primaryOrder)"
				>
					{{ fill(labels.monitorOpenOrder, { kind: primaryOrder.label }) }}
				</button>
			</div>
		</template>
	</div>
</template>

<script setup>
import { computed } from "vue"
import { useRoute, useRouter } from "vue-router"
import { cachedResource } from "@/data/cache"
import { labels, statusLabels } from "@/utils/labels"
import { since, fmtDateTime } from "@/utils/surveyStatus"
import Icon from "@/components/Icon.vue"

const route = useRoute()
const router = useRouter()
const container = computed(() => String(route.params.container || ""))

const detailRes = cachedResource({
	url: "container_depot.ess.inventory.get_tank_detail",
	method: "GET",
	makeParams: () => ({ container: container.value }),
	auto: true,
})
const tank = computed(() => (detailRes.data?.success ? detailRes.data : null))
const openOrders = computed(() => tank.value?.open_orders || [])
const activities = computed(() => tank.value?.activities || [])

function fill(tpl, vars) {
	return Object.entries(vars).reduce((s, [k, v]) => s.replace(`{${k}}`, v), tpl)
}

const BADGE_TONE = {
	available: "bg-leaf-100 text-leaf-800",
	draft: "bg-gray-100 text-gray-700",
	pending: "bg-amber-100 text-amber-800",
	in_progress: "bg-blue-100 text-blue-800",
	gate_out: "bg-gray-200 text-gray-700",
}
const badge = computed(() => ({
	label: statusLabels[tank.value?.status] || tank.value?.status || "—",
	tone: BADGE_TONE[tank.value?.status] || "bg-gray-100 text-gray-600",
}))

// Spesifikasi tank dalam satu baris — hanya bagian yang benar-benar terisi, supaya sebuah
// master yang setengah lengkap tidak tampil sebagai deretan tanda hubung.
const specLine = computed(() => {
	const t = tank.value
	if (!t) return ""
	const type = [t.container_type, t.size].filter(Boolean).join(" ")
	const parts = [t.principal, type]
	if (t.capacity) parts.push(`${num(t.capacity)} L`)
	if (t.tare_weight) parts.push(`${labels.monitorTare} ${num(t.tare_weight)} kg`)
	return parts.filter(Boolean).join(" · ")
})
function num(v) {
	return new Intl.NumberFormat("id-ID").format(v)
}

function orderIcon(label) {
	return { "M&R": "tool", Cleaning: "droplet", "EIR-In": "clipboard", EIR: "clipboard" }[label] || "file-text"
}
function orderLine(o) {
	const started = o.since ? `${labels.monitorProcessStart} ${String(o.since).slice(11, 16)}` : null
	return [started, o.by, o.status].filter(Boolean).join(" · ")
}

const ROUTES = { "Repair Order": "/mr", "Cleaning Order": "/cleaning" }
function routeOf(o) {
	return ROUTES[o.doctype] || null
}
function openOrder(o) {
	const path = routeOf(o)
	if (!path) return
	router.push({ path, query: { o: o.name } })
}
// Pekerjaan yang ditawarkan tombol kaki: yang pertama yang PUNYA layar untuk dibuka.
// Sebuah EIR draft tidak dibuka dari sini (layar EIR punya alur batch-nya sendiri).
const primaryOrder = computed(() => openOrders.value.find((o) => routeOf(o)) || null)

function dotTone(a) {
	if (a.voided) return "bg-gray-300"
	return (
		{
			"Gate In": "bg-brand-500",
			"Gate Out": "bg-gray-400",
			Repair: "bg-amber-500",
			Cleaning: "bg-leaf-500",
			"Inspection (EIR)": "bg-blue-500",
		}[a.activity_type] || "bg-gray-300"
	)
}

function goBack() {
	if (window.history.length > 1) router.back()
	else router.push("/monitor")
}
</script>
