<template>
	<HistoryPage
		:title="labels.gateHistoryTitle"
		icon="log-in"
		back-to="/gate"
		:back-label="labels.gate"
		list-url="container_depot.ess.gate.gate_history"
		detail-url="container_depot.ess.gate.gate_detail"
		detail-param="name"
		:search-placeholder="labels.gateHistorySearch"
		:count-label="labels.gateHistoryCount"
		:list-params="listParams"
	>
		<!-- Datang dari kartu Beranda: daftarnya sudah disaring persis seperti angka yang
		     barusan ditekan. Chip-nya mengatakannya, dan sekali ketuk membuka riwayat penuh. -->
		<template v-if="filterNote" #filters>
			<div class="flex items-center gap-2">
				<span class="oak-chip bg-brand-50 text-brand-700">
					<Icon name="filter" :size="12" /> {{ filterNote }}
				</span>
				<router-link to="/gate/history" class="oak-link text-xs">{{ labels.gateHistoryAll }}</router-link>
			</div>
		</template>

		<template #row="{ item }">
			<span class="oak-icon-tile h-9 w-9 shrink-0 bg-brand-50 text-brand-600"><Icon name="log-in" :size="16" /></span>
			<div class="min-w-0 flex-1">
				<div class="flex items-center justify-between gap-2">
					<p class="truncate font-semibold text-gray-900">{{ item.container_no }}</p>
					<span class="oak-chip shrink-0" :class="statusClass(item.status)">{{ statusText(item.status) }}</span>
				</div>
				<div class="mt-0.5 flex items-center justify-between gap-2 text-xs text-gray-500">
					<span class="truncate">{{ item.truck_plate || "—" }}<span v-if="item.driver_name"> · {{ item.driver_name }}</span></span>
					<span class="shrink-0">{{ fmtDate(item.gate_in_timestamp || item.creation) }}</span>
				</div>
				<p class="truncate text-[11px] text-gray-400">
					{{ item.gate_entry_id }}<span v-if="item.booking_code"> · {{ item.booking_code }}</span>
				</p>
			</div>
		</template>

		<template #detail="{ data }">
			<section class="oak-card space-y-3 p-4">
				<div class="flex items-start justify-between gap-2">
					<div class="min-w-0">
						<p class="font-mono text-xs text-gray-400">{{ data.gate_entry_id }}</p>
						<h2 class="truncate text-lg font-extrabold text-gray-900">{{ data.container_no }}</h2>
					</div>
					<span class="oak-chip shrink-0" :class="statusClass(data.status)">{{ statusText(data.status) }}</span>
				</div>
				<dl class="grid grid-cols-2 gap-x-3 gap-y-2 text-sm">
					<div v-for="c in cells(data)" :key="c.label" class="min-w-0">
						<dt class="text-xs text-gray-400">{{ c.label }}</dt>
						<dd class="truncate font-medium text-gray-800">{{ c.value || "—" }}</dd>
					</div>
				</dl>
			</section>
		</template>
	</HistoryPage>
</template>

<script setup>
import { computed } from "vue"
import { useRoute } from "vue-router"
import { labels } from "@/utils/labels"
import Icon from "@/components/Icon.vue"
import HistoryPage from "@/components/HistoryPage.vue"

// ?direction=in|out&day=today — saringan opsional dari tautan mana pun, diteruskan apa adanya
// ke server (gate.list_gate_history yang memutuskan cap waktu mana
// yang dipakai). Tanpa query, halaman ini tetap riwayat gate yang penuh.
const route = useRoute()
const dir = computed(() => (route.query.direction === "in" || route.query.direction === "out" ? route.query.direction : ""))
const listParams = computed(() => (dir.value ? { direction: dir.value, day: route.query.day || undefined } : {}))
const filterNote = computed(() => {
	if (!dir.value) return ""
	const what = dir.value === "in" ? labels.homeTileGateIn : labels.homeTileGateOut
	return route.query.day === "today" ? `${what} · ${labels.gateHistoryToday}` : what
})

const fmtDate = (v) => (v ? String(v).slice(0, 10) : "—")
const fmtDateTime = (v) => (v ? String(v).slice(0, 16).replace("T", " ") : "")

function statusText(s) {
	return labels.gateStatus?.[s] || s || "—"
}
function statusClass(s) {
	if (s === "Gate_Out_Completed") return "bg-gray-200 text-gray-600"
	if (s === "Cancelled") return "bg-red-100 text-red-700"
	if (s === "EIR_Completed" || s === "Gate_In_Completed") return "bg-leaf-100 text-leaf-800"
	return "bg-amber-100 text-amber-800"
}
function cells(d) {
	return [
		{ label: labels.gateTruck, value: d.truck_plate },
		{ label: labels.gateDriver, value: d.driver_name },
		{ label: labels.gateBooking, value: d.booking_code },
		{ label: labels.depotLabel, value: d.depot },
		{ label: labels.gateInTime, value: fmtDateTime(d.gate_in_timestamp) },
		{ label: labels.gateOutTime, value: fmtDateTime(d.gate_out_timestamp) },
		{ label: labels.gateOrder, value: d.order_ref },
		{ label: labels.gateEir, value: d.eir_reference },
	]
}
</script>
