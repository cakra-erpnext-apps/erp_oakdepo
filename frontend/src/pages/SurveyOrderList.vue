<template>
	<div class="mx-auto w-full max-w-lg space-y-4 md:max-w-2xl">
		<div class="flex items-center justify-between">
			<div class="min-w-0">
				<h1 class="truncate text-xl font-extrabold tracking-tight text-gray-900">
					{{ labels.surveyListTitle }}
				</h1>
				<p class="text-sm text-gray-500">{{ labels.surveyListHint }}</p>
			</div>
			<div class="flex shrink-0 items-center gap-2">
				<router-link to="/survey-orders/history" class="oak-btn oak-btn-secondary px-3 py-2">
					<Icon name="clock" :size="16" /> {{ labels.navHistory }}
				</router-link>
				<button class="oak-btn oak-btn-secondary px-3 py-2" :disabled="listRes.loading" @click="reload">
					<Icon name="refresh-cw" :size="16" />
				</button>
			</div>
		</div>

		<!-- =================== SEARCH ===================
		     Searches the schedule's own identifiers AND its tank numbers (the server does a
		     child-table pass for that). A tank number is what somebody actually has to hand
		     when they ask "which day was that one on". -->
		<div class="flex gap-2">
			<input
				v-model="search"
				class="oak-input"
				:placeholder="labels.surveyListSearch"
				autocorrect="off"
				autocomplete="off"
				spellcheck="false"
				enterkeyhint="search"
				@input="onSearchInput"
				@keyup.enter="reload"
			/>
			<button class="oak-btn oak-btn-secondary shrink-0 px-3" @click="reload">
				<Icon name="search" :size="16" />
			</button>
		</div>

		<!-- =================== STATUS ===================
		     Counts come from an UNFILTERED count on the server, so the chips still say how much
		     is behind each one while a search is narrowing the list. Chips that all read 0 the
		     moment you type are chips nobody can navigate by. -->
		<section class="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1">
			<button
				v-for="f in FILTERS"
				:key="f.key || 'all'"
				type="button"
				class="oak-chip shrink-0 gap-1 px-3 py-1.5"
				:class="status === f.key ? f.on : 'bg-gray-100 text-gray-600'"
				@click="setStatus(f.key)"
			>
				{{ f.label }}
				<span v-if="f.key && counts[f.key]" class="opacity-70">{{ counts[f.key] }}</span>
			</button>
		</section>

		<!-- =================== DATE RANGE ===================
		     Collapsed by default. It is the filter that gets used once a month, and two date
		     inputs permanently on screen push the actual list below the fold on a handset. -->
		<section class="oak-section space-y-2">
			<button class="flex w-full items-center justify-between gap-2 text-left" @click="showDates = !showDates">
				<span class="oak-section-title flex items-center gap-1.5">
					<Icon name="calendar" :size="14" class="text-gray-400" /> {{ labels.surveyListFilterTitle }}
					<span v-if="fromDate || toDate" class="oak-chip bg-brand-100 px-1.5 py-0 text-[10px] text-brand-700">1</span>
				</span>
				<Icon :name="showDates ? 'chevron-up' : 'chevron-down'" :size="16" class="text-gray-400" />
			</button>
			<div v-if="showDates" class="grid grid-cols-2 gap-2">
				<div>
					<label class="oak-label">{{ labels.surveyListFrom }}</label>
					<input v-model="fromDate" type="date" class="oak-input" @change="reload" />
				</div>
				<div>
					<label class="oak-label">{{ labels.surveyListTo }}</label>
					<input v-model="toDate" type="date" class="oak-input" @change="reload" />
				</div>
				<button v-if="filtered" class="oak-btn oak-btn-secondary col-span-2 py-2" @click="resetFilters">
					<Icon name="x" :size="15" /> {{ labels.surveyListReset }}
				</button>
			</div>
		</section>

		<!-- =================== LIST =================== -->
		<section class="oak-section space-y-3">
			<SkeletonList v-if="listRes.loading && !items.length" :action="false" />
			<section v-else-if="failed" class="oak-card space-y-3 p-6 text-center">
				<span class="oak-icon-tile mx-auto h-12 w-12 bg-red-50 text-red-500">
					<Icon name="cloud-off" :size="24" />
				</span>
				<p class="text-sm text-gray-600">{{ labels.surveyCalError }}</p>
				<button class="oak-btn oak-btn-primary w-full" @click="reload">{{ labels.retry }}</button>
			</section>
			<p v-else-if="!items.length" class="py-6 text-center text-sm text-gray-400">
				{{ labels.surveyListEmpty }}
			</p>

			<ul v-else class="space-y-2">
				<li v-for="o in items" :key="o.name">
					<router-link
						:to="`/survey-orders/order/${o.name}`"
						class="oak-press oak-card flex items-center gap-3 p-3"
						:class="o.status === 'Cancelled' ? 'opacity-60' : ''"
					>
						<span class="oak-icon-tile h-10 w-10 shrink-0" :class="tile(o.status)">
							<Icon name="clipboard" :size="18" />
						</span>
						<div class="min-w-0 flex-1 space-y-0.5">
							<div class="flex items-center gap-1.5">
								<p class="truncate font-bold text-gray-900">{{ o.principal || o.booking }}</p>
							</div>
							<p class="truncate text-[11px] text-gray-500">
								<Icon name="calendar" :size="11" class="mr-0.5 inline-block align-[-1px]" />
								{{ fmtDate(o.survey_date) }}
								<template v-if="o.surveyor"> · {{ o.surveyor }}</template>
							</p>
							<p v-if="o.container_summary" class="truncate text-[11px] text-gray-400">
								{{ o.container_summary }}
							</p>
						</div>
						<div class="shrink-0 space-y-1 text-right">
							<span class="oak-chip" :class="chip(o.status)">{{ statusLabel(o.status) }}</span>
							<p class="text-[11px] font-semibold text-gray-700">
								{{ o.tank_count || 0 }} {{ labels.surveyOrderTankUnit }}
							</p>
							<p v-if="o.waiting_count" class="text-[11px] font-semibold text-amber-600">
								{{ o.waiting_count }} {{ labels.surveyPosStatusWaiting }}
							</p>
						</div>
						<Icon name="chevron-right" :size="16" class="shrink-0 text-gray-300" />
					</router-link>
				</li>
			</ul>

			<!-- Append rather than page: an operator scrolling a list has no page number in
			     their head, and a "page 2" that loses the scroll position loses their place. -->
			<button
				v-if="items.length && items.length < total"
				class="oak-btn oak-btn-secondary w-full py-2.5"
				:disabled="listRes.loading"
				@click="loadMore"
			>
				{{ listRes.loading ? "…" : labels.surveyListMore }}
			</button>
			<p v-if="items.length" class="text-center text-xs text-gray-400">
				{{ items.length }} / {{ total }} {{ labels.surveyListCount }}
			</p>
		</section>
	</div>
</template>

<script setup>
import { computed, onBeforeUnmount, ref } from "vue"
import { labels } from "@/utils/labels"
import Icon from "@/components/Icon.vue"
import SkeletonList from "@/components/SkeletonList.vue"
import { cachedResource } from "@/data/cache"
import { fmtDate } from "@/utils/surveyStatus"

const PAGE = 20

// The four schedule statuses, plus an "everything" chip. These are the SCHEDULE's statuses
// (Survey Order), not a tank's — `utils/surveyStatus.js` owns those three and they are a
// different vocabulary on purpose.
const FILTERS = [
	{ key: "", label: labels.surveyListFilterAll, on: "bg-brand-600 text-white" },
	{ key: "Scheduled", label: labels.surveyOrderStatusScheduled, on: "bg-gray-700 text-white" },
	{ key: "In Progress", label: labels.surveyOrderStatusProgress, on: "bg-amber-500 text-white" },
	{ key: "Completed", label: labels.surveyOrderStatusCompleted, on: "bg-leaf-600 text-white" },
	{ key: "Cancelled", label: labels.surveyOrderStatusCancelled, on: "bg-red-600 text-white" },
]

const STATUS_STYLE = {
	Scheduled: { chip: "bg-gray-100 text-gray-600", tile: "bg-gray-100 text-gray-500" },
	"In Progress": { chip: "bg-amber-100 text-amber-800", tile: "bg-amber-50 text-amber-600" },
	Completed: { chip: "bg-leaf-100 text-leaf-700", tile: "bg-leaf-50 text-leaf-600" },
	Cancelled: { chip: "bg-red-100 text-red-700", tile: "bg-red-50 text-red-500" },
}
const chip = (s) => STATUS_STYLE[s]?.chip || "bg-gray-100 text-gray-600"
const tile = (s) => STATUS_STYLE[s]?.tile || "bg-gray-100 text-gray-400"
const statusLabel = (s) =>
	FILTERS.find((f) => f.key === s)?.label || s || "—"

const search = ref("")
const status = ref("")
const fromDate = ref("")
const toDate = ref("")
const showDates = ref(false)
const items = ref([])
const total = ref(0)
const counts = ref({})
const failed = ref(false)
const start = ref(0)

const filtered = computed(() => !!(fromDate.value || toDate.value))

const listRes = cachedResource({
	url: "container_depot.ess.tank_survey.survey_order_list",
	method: "GET",
	makeParams: () => ({
		status: status.value || undefined,
		from_date: fromDate.value || undefined,
		to_date: toDate.value || undefined,
		search: search.value || undefined,
		start: start.value,
		page_length: PAGE,
	}),
	auto: true,
	onSuccess(data) {
		failed.value = false
		// `start > 0` is the only signal that this was a "load more" rather than a fresh
		// query — the resource itself does not distinguish them.
		items.value = start.value ? [...items.value, ...(data?.items || [])] : data?.items || []
		total.value = data?.total || 0
		counts.value = data?.counts || {}
	},
	onError() {
		failed.value = true
	},
})

function reload() {
	start.value = 0
	listRes.reload()
}

function loadMore() {
	start.value = items.value.length
	listRes.reload()
}

function setStatus(key) {
	status.value = key
	reload()
}

function resetFilters() {
	fromDate.value = ""
	toDate.value = ""
	reload()
}

// Debounced so a tank number typed a character at a time is one query, not twelve.
let searchTimer = null
function onSearchInput() {
	clearTimeout(searchTimer)
	searchTimer = setTimeout(reload, 300)
}
onBeforeUnmount(() => clearTimeout(searchTimer))
</script>
