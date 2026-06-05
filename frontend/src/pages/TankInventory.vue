<template>
	<div class="mx-auto w-full max-w-3xl space-y-4">
		<h1 class="text-lg font-semibold">{{ labels.inventory }}</h1>

		<!-- Status-count header cards -->
		<section
			v-if="summary.loading && !summary.data"
			class="text-sm text-gray-500"
		>
			{{ labels.loading }}
		</section>
		<section v-else-if="summary.error" class="text-sm text-red-600">
			{{ labels.error }}
			<button class="underline" @click="summary.reload()">
				{{ labels.retry }}
			</button>
		</section>
		<section v-else-if="summary.data" class="grid grid-cols-3 gap-2 sm:grid-cols-5">
			<div
				v-for="b in BUCKETS"
				:key="b"
				class="rounded-lg border bg-white p-3 text-center"
			>
				<p class="text-xl font-semibold">{{ summary.data.counts[b] }}</p>
				<p class="mt-0.5 text-[11px] leading-tight text-gray-500">
					{{ statusLabel(b) }}
				</p>
			</div>
			<div
				class="col-span-3 rounded-lg border bg-amber-50 p-3 text-center sm:col-span-5"
			>
				<span class="text-sm font-medium text-amber-800">
					{{ labels.ptDue }}: {{ summary.data.periodic_test_due }}
				</span>
				<span class="ml-2 text-xs text-gray-500">
					/ {{ summary.data.total }} tank
				</span>
			</div>
		</section>

		<!-- Search + filters -->
		<section class="space-y-2">
			<input
				v-model="search"
				type="search"
				:placeholder="labels.search"
				class="w-full rounded-md border px-3 py-2 text-sm"
				@input="onSearchInput"
			/>
			<div class="grid grid-cols-2 gap-2 sm:grid-cols-4">
				<select v-model="statusFilter" class="rounded-md border px-2 py-2 text-sm" @change="applyFilters">
					<option value="">{{ labels.status }}: {{ labels.all }}</option>
					<option v-for="b in BUCKETS" :key="b" :value="b">{{ statusLabel(b) }}</option>
				</select>
				<select v-model="zoneFilter" class="rounded-md border px-2 py-2 text-sm" @change="applyFilters">
					<option value="">{{ labels.yardZone }}: {{ labels.all }}</option>
					<option v-for="z in YARD_ZONES" :key="z" :value="z">{{ z.replace(/_/g, " ") }}</option>
				</select>
				<select v-model="depotFilter" class="rounded-md border px-2 py-2 text-sm" @change="applyFilters">
					<option value="">{{ labels.depot }}: {{ labels.all }}</option>
					<option v-for="d in depots.data || []" :key="d.name" :value="d.name">
						{{ d.depot_name || d.name }}
					</option>
				</select>
				<select v-model="principalFilter" class="rounded-md border px-2 py-2 text-sm" @change="applyFilters">
					<option value="">{{ labels.principal }}: {{ labels.all }}</option>
					<option v-for="c in principals.data || []" :key="c.name" :value="c.name">
						{{ c.customer_name || c.name }}
					</option>
				</select>
			</div>
		</section>

		<!-- List -->
		<section>
			<p v-if="tanks.loading && start === 0" class="text-sm text-gray-500">
				{{ labels.loading }}
			</p>
			<p v-else-if="tanks.error" class="text-sm text-red-600">
				{{ labels.error }}
				<button class="underline" @click="tanks.reload()">{{ labels.retry }}</button>
			</p>
			<p v-else-if="!items.length" class="text-sm text-gray-500">
				{{ labels.empty }}
			</p>
			<ul v-else class="divide-y rounded-lg border bg-white">
				<li v-for="t in items" :key="t.name">
					<router-link
						:to="{ name: 'TankDetail', params: { name: t.name } }"
						class="flex items-center justify-between gap-3 px-3 py-3 hover:bg-gray-50"
					>
						<div class="min-w-0">
							<p class="truncate font-medium">{{ t.container_no }}</p>
							<p class="truncate text-xs text-gray-500">
								{{ t.container_type }}
								<span v-if="t.principal"> · {{ t.principal }}</span>
								<span v-if="t.yard_zone"> · {{ t.yard_zone.replace(/_/g, " ") }}</span>
							</p>
						</div>
						<div class="flex shrink-0 items-center gap-2">
							<span
								v-if="t.pt_due"
								class="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-medium text-amber-800"
								:title="labels.ptDue"
							>
								{{ labels.ptDueFlag }}
							</span>
							<StatusChip :bucket="t.status" />
						</div>
					</router-link>
				</li>
			</ul>

			<div v-if="hasMore" class="mt-3 text-center">
				<button
					class="rounded-md border bg-white px-4 py-2 text-sm hover:bg-gray-50"
					:disabled="tanks.loading"
					@click="loadMore"
				>
					{{ tanks.loading ? labels.loading : "Muat lebih banyak" }}
				</button>
			</div>
		</section>
	</div>
</template>

<script setup>
import { computed, ref } from "vue"
import { createResource, createListResource } from "frappe-ui"
import StatusChip from "@/components/StatusChip.vue"
import { labels, statusLabel } from "@/utils/labels"

const BUCKETS = ["in_depot", "cleaning", "repair_survey", "ready", "gate_out"]
const YARD_ZONES = [
	"Storage_Yard_A",
	"Storage_Yard_B",
	"Cleaning_Bay_C",
	"Workshop_D",
	"Survey_Lane_E",
	"Gate_F",
	"PreClean_Buffer",
]
const PAGE = 50

const search = ref("")
const statusFilter = ref("")
const zoneFilter = ref("")
const depotFilter = ref("")
const principalFilter = ref("")

const items = ref([])
const start = ref(0)
const total = ref(0)

// frappe-ui serializes GET params via URLSearchParams.append, which turns an
// `undefined` value into the literal string "undefined". So only include keys
// that actually have a value.
function cleanParams(obj) {
	const out = {}
	for (const k in obj) {
		const v = obj[k]
		if (v !== undefined && v !== null && v !== "") out[k] = v
	}
	return out
}

// Status counts — depot-scoped server-side; refetched when the depot changes.
const summary = createResource({
	url: "container_depot.ess.inventory.get_inventory_summary",
	method: "GET",
	makeParams: () => cleanParams({ depot: depotFilter.value }),
	auto: true,
})

// Filter option sources (small, read-only lookups).
const depots = createListResource({
	doctype: "Depot",
	fields: ["name", "depot_name"],
	filters: { is_active: 1 },
	pageLength: 0,
	auto: true,
})
const principals = createListResource({
	doctype: "Customer",
	fields: ["name", "customer_name"],
	pageLength: 0,
	auto: true,
})

const tanks = createResource({
	url: "container_depot.ess.inventory.get_tank_list",
	method: "GET",
	makeParams: () =>
		cleanParams({
			search: search.value,
			status: statusFilter.value,
			yard_zone: zoneFilter.value,
			depot: depotFilter.value,
			principal: principalFilter.value,
			start: start.value,
			page_length: PAGE,
		}),
	auto: true,
	onSuccess(data) {
		total.value = data.total
		items.value = start.value === 0 ? data.items : items.value.concat(data.items)
	},
})

const hasMore = computed(() => items.value.length < total.value)

function applyFilters() {
	start.value = 0
	summary.reload()
	tanks.reload()
}

function loadMore() {
	start.value += PAGE
	tanks.reload()
}

let searchTimer = null
function onSearchInput() {
	clearTimeout(searchTimer)
	searchTimer = setTimeout(applyFilters, 300)
}
</script>
