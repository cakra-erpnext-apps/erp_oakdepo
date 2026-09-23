<template>
	<!-- Tata letak = Jadwal Survey (SurveyOrderList): judul, cari, saringan, grup per tanggal,
	     baris ringkas, "lihat semua". Isi baris + detail tetap milik halaman pemanggil. -->
	<div class="mx-auto w-full max-w-lg space-y-4 md:max-w-2xl">
		<div class="flex items-start justify-between gap-3">
			<div class="min-w-0">
				<h1 class="truncate text-xl font-extrabold tracking-tight text-gray-900">{{ title }}</h1>
				<p v-if="view === 'list' && total" class="mt-0.5 truncate text-xs text-gray-500">{{ total }} {{ countLabel }}</p>
			</div>
			<button v-if="view === 'detail'" class="oak-btn oak-btn-secondary min-h-[44px] shrink-0 px-3" @click="closeDetail">
				<Icon name="arrow-left" :size="15" /> {{ labels.cleaningBack }}
			</button>
			<router-link v-else-if="backTo" :to="backTo" class="oak-btn oak-btn-secondary min-h-[44px] shrink-0 px-3">
				<Icon name="arrow-left" :size="15" /> {{ backLabel || labels.cleaningBack }}
			</router-link>
		</div>

		<!-- DETAIL -->
		<template v-if="view === 'detail'">
			<div v-if="detailRes.loading" class="oak-card p-8 text-center text-gray-400">
				<Icon name="loader" :size="22" class="animate-spin" />
			</div>
			<p v-else-if="detailRes.error" class="flex items-center gap-2 text-sm text-red-600">
				<Icon name="alert-circle" :size="16" /> {{ labels.error }}
				<button class="oak-link" @click="reloadDetail">{{ labels.retry }}</button>
			</p>
			<slot v-else name="detail" :data="detailData" :item="selectedItem" />
		</template>

		<!-- LIST -->
		<template v-else>
			<ListSearch v-model="search" :placeholder="searchPlaceholder" @search="reload" />

			<!-- Saringan milik halaman pemanggil (FilterBar + FilterSheet, mis. arah/tanggal
			     Gate dari Beranda) — di atas daftar: daftar yang tersaring tanpa mengaku
			     tersaring terbaca sebagai riwayat yang hilang. -->
			<slot name="filters" />

			<SkeletonList v-if="listRes.loading && !items.length" :action="false" />

			<div v-else-if="failed" class="oak-card flex flex-col items-center gap-2 p-8 text-center">
				<span class="oak-icon-tile h-12 w-12 bg-red-50 text-red-500"><Icon name="alert-circle" :size="24" /></span>
				<p class="text-sm font-bold text-gray-900">{{ labels.monitorErrorTitle }}</p>
				<button class="oak-btn oak-btn-primary mt-1 min-h-[44px] px-4" @click="reload">{{ labels.monitorRetry }}</button>
			</div>

			<div v-else-if="!items.length" class="oak-card flex flex-col items-center gap-2 p-8 text-center">
				<span class="oak-icon-tile h-12 w-12 bg-gray-100 text-gray-300"><Icon :name="icon" :size="24" /></span>
				<p class="text-sm text-gray-400">{{ emptyText || labels.empty }}</p>
			</div>

			<div v-else class="space-y-4">
				<section v-for="(g, gi) in days" :key="gi" class="space-y-2">
					<div class="flex items-center justify-between gap-2 px-1">
						<p class="flex min-w-0 items-center gap-1.5 truncate text-xs font-bold text-gray-600">
							<span class="h-2 w-2 shrink-0 rounded-full bg-gray-400"></span>
							{{ g.label }}
						</p>
						<p class="shrink-0 text-[11px] text-gray-400">{{ g.rows.length }} {{ countLabel }}</p>
					</div>
					<ul class="oak-card divide-y divide-gray-100 overflow-hidden">
						<li v-for="r in g.rows" :key="r[rowKey]">
							<button type="button" class="oak-press flex min-h-[64px] w-full items-center gap-3 px-4 py-3 text-left" @click="openDetail(r)">
								<slot name="row" :item="r" />
								<Icon name="chevron-right" :size="18" class="shrink-0 text-gray-300" />
							</button>
						</li>
					</ul>
				</section>

				<button
					v-if="items.length < total"
					class="oak-btn oak-btn-secondary min-h-[48px] w-full"
					:disabled="listRes.loading"
					@click="loadMore"
				>
					{{ listRes.loading ? "…" : `${labels.svMore} (${items.length}/${total})` }}
				</button>
			</div>
		</template>
	</div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from "vue"
import { useRoute } from "vue-router"
import { cachedResource } from "@/data/cache"
import { labels } from "@/utils/labels"
import { groupByDay } from "@/utils/listKit"
import Icon from "@/components/Icon.vue"
import SkeletonList from "@/components/SkeletonList.vue"
import ListSearch from "@/components/list/ListSearch.vue"

const props = defineProps({
	title: { type: String, required: true },
	// Ikon kotak kosong.
	icon: { type: String, default: "clock" },
	backTo: { type: String, default: "" },
	backLabel: { type: String, default: "" },
	listUrl: { type: String, required: true },
	listParams: { type: Object, default: () => ({}) },
	searchPlaceholder: { type: String, default: "" },
	emptyText: { type: String, default: "" },
	detailUrl: { type: String, required: true },
	detailParam: { type: String, default: "name" },
	rowKey: { type: String, default: "name" },
	pageLength: { type: Number, default: 20 },
	countLabel: { type: String, default: "" },
	// Tanggal grup sebuah baris. HARUS kolom yang sama dengan urutan server, supaya baris
	// bertanggal sama berurutan (groupByDay).
	dateOf: { type: Function, default: (r) => r.creation },
})

const search = ref("")
const start = ref(0)
const items = ref([])
const total = ref(0)
const failed = ref(false)

const view = ref("list")
const selectedItem = ref(null)
const detailData = ref(null)

// frappe-ui serializes GET params via URLSearchParams, turning `undefined` into the
// string "undefined" — only include keys that actually have a value.
function cleanParams(obj) {
	const out = {}
	for (const k in obj) {
		const v = obj[k]
		if (v !== undefined && v !== null && v !== "") out[k] = v
	}
	return out
}

const listRes = cachedResource({
	url: props.listUrl,
	method: "GET",
	makeParams: () =>
		cleanParams({
			...props.listParams,
			search: search.value,
			start: start.value,
			page_length: props.pageLength,
		}),
	auto: true,
	onSuccess(data) {
		failed.value = false
		// `start > 0` = "lihat semua" (tambah), selain itu query baru.
		items.value = start.value ? [...items.value, ...(data?.items || [])] : data?.items || []
		total.value = data?.total || 0
	},
	onError() {
		failed.value = true
	},
})

const days = computed(() => groupByDay(items.value, (r) => String(props.dateOf(r) || "").slice(0, 10)))

function reload() {
	start.value = 0
	listRes.reload()
}
function loadMore() {
	start.value = items.value.length
	listRes.reload()
}

const detailRes = cachedResource({
	url: props.detailUrl,
	method: "GET",
	onSuccess(data) {
		detailData.value = data
	},
})

function openDetail(item) {
	selectedItem.value = item
	detailData.value = null
	view.value = "detail"
	detailRes.fetch({ [props.detailParam]: item[props.rowKey] })
}
function reloadDetail() {
	if (selectedItem.value) detailRes.fetch({ [props.detailParam]: selectedItem.value[props.rowKey] })
}
function closeDetail() {
	view.value = "list"
	selectedItem.value = null
	detailData.value = null
}

// Deep link: ?open=<rowKey> opens that item's detail straight away (used by the EIR
// landing's "Selesai" list so a tap jumps to the read-only detail + revision button).
const route = useRoute()
onMounted(() => {
	const open = route.query.open
	if (open) openDetail({ [props.rowKey]: String(open) })
})

// Saringan berganti tanpa halaman ini di-mount ulang (mis. chip saringan Gate yang cuma
// mengubah query) — tanpa ini daftarnya tetap memakai hasil saringan yang lama.
watch(() => props.listParams, reload, { deep: true })

defineExpose({ closeDetail, reload })
</script>
