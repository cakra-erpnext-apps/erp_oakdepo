<template>
	<div class="mx-auto w-full max-w-lg space-y-4 md:max-w-2xl">
		<div class="flex items-center gap-2">
			<router-link
				to="/survey-orders"
				class="oak-press flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-gray-500"
				:aria-label="labels.surveyListTitle"
			>
				<Icon name="chevron-left" :size="22" />
			</router-link>
			<div class="min-w-0">
				<h1 class="truncate text-lg font-extrabold tracking-tight text-gray-900">{{ labels.svHistoryTitle }}</h1>
				<p class="truncate text-xs text-gray-500">{{ labels.svHistoryHint }}</p>
			</div>
		</div>

		<div class="relative">
			<Icon name="search" :size="18" class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
			<input
				v-model="search"
				type="search"
				class="oak-input pl-10"
				:placeholder="labels.svListSearch"
				autocorrect="off"
				spellcheck="false"
				@input="onSearchInput"
			/>
		</div>

		<SkeletonList v-if="res.loading && !items.length" :action="false" />
		<p v-else-if="!items.length" class="oak-card p-8 text-center text-sm text-gray-400">{{ labels.svEmpty }}</p>
		<template v-else>
			<!-- Kartu yang sama dengan list jadwal, ditambah tanggal survey-nya — riwayat dibaca
			     mundur dari hari ini, jadi tanggal adalah pegangan pertama. -->
			<ul class="oak-card divide-y divide-gray-100 overflow-hidden">
				<li v-for="o in items" :key="o.name">
					<router-link :to="`/survey-orders/order/${o.name}`" class="oak-press block px-4 py-3">
						<SurveyOrderInfo :o="o">
							<span class="oak-chip shrink-0" :class="CHIP[o.status]">{{ LABEL[o.status] || o.status }}</span>
						</SurveyOrderInfo>
						<span class="mt-0.5 block text-[11px] text-gray-500">{{ labels.svScheduleDate }} · {{ fmtDate(o.survey_date) }}</span>
					</router-link>
				</li>
			</ul>
			<button
				v-if="items.length < total"
				class="oak-btn oak-btn-secondary min-h-[48px] w-full"
				:disabled="res.loading"
				@click="loadMore"
			>
				{{ res.loading ? "…" : `${labels.svMore} (${items.length}/${total})` }}
			</button>
		</template>
	</div>
</template>

<script setup>
import { onBeforeUnmount, ref } from "vue"
import { labels } from "@/utils/labels"
import { cachedResource } from "@/data/cache"
import { fmtDate } from "@/utils/surveyStatus"
import Icon from "@/components/Icon.vue"
import SkeletonList from "@/components/SkeletonList.vue"
import SurveyOrderInfo from "@/components/SurveyOrderInfo.vue"

const PAGE = 20
const CHIP = { Completed: "bg-leaf-100 text-leaf-700", Cancelled: "bg-red-100 text-red-700" }
const LABEL = { Completed: labels.svStatDone, Cancelled: labels.svCancelledGroup }

const search = ref("")
const items = ref([])
const total = ref(0)
const start = ref(0)

const res = cachedResource({
	url: "container_depot.ess.tank_survey.survey_order_list",
	method: "GET",
	makeParams: () => ({
		history: 1,
		sort: "newest",
		search: search.value || undefined,
		start: start.value,
		page_length: PAGE,
	}),
	auto: true,
	onSuccess(data) {
		items.value = start.value ? [...items.value, ...(data?.items || [])] : data?.items || []
		total.value = data?.total || 0
	},
})

function reload() {
	start.value = 0
	res.reload()
}
function loadMore() {
	start.value = items.value.length
	res.reload()
}
let timer = null
function onSearchInput() {
	clearTimeout(timer)
	timer = setTimeout(reload, 300)
}
onBeforeUnmount(() => clearTimeout(timer))
</script>
