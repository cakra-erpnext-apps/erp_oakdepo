<template>
	<div class="mx-auto w-full max-w-lg space-y-4 md:max-w-2xl">
		<!-- Header -->
		<div class="flex flex-wrap items-center justify-between gap-2">
			<div class="flex items-center gap-2">
				<button v-if="mode === 'detail'" class="oak-btn oak-btn-secondary px-2 py-2" @click="backToList">
					<Icon name="arrow-left" :size="18" />
				</button>
				<span class="oak-icon-tile h-9 w-9 bg-leaf-50 text-leaf-600"><Icon name="check-circle" :size="20" /></span>
				<div class="min-w-0">
					<h1 class="text-lg font-extrabold tracking-tight">{{ labels.posFixTitle }}</h1>
					<p class="truncate text-xs text-gray-500">{{ mode === 'detail' ? (detail?.container_no || '') : labels.posFixDesc }}</p>
				</div>
			</div>
		</div>

		<!-- =================== WORKLIST =================== -->
		<template v-if="mode === 'list'">
			<div class="relative">
				<Icon name="search" :size="18" class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
				<input v-model="search" type="search" :placeholder="labels.surveyPosSearch" class="oak-input pl-10 uppercase" @input="onSearchInput" />
			</div>

			<ul v-if="listRes.loading && !items.length" class="oak-card divide-y divide-gray-100 overflow-hidden">
				<li v-for="n in 5" :key="n" class="flex items-center gap-3 px-4 py-3.5">
					<div class="oak-skeleton h-9 w-9 rounded-xl"></div>
					<div class="flex-1 space-y-2"><div class="oak-skeleton h-3.5 w-1/2"></div><div class="oak-skeleton h-3 w-3/4"></div></div>
				</li>
			</ul>

			<div v-else-if="!items.length" class="oak-card flex flex-col items-center gap-2 p-8 text-center">
				<span class="oak-icon-tile h-12 w-12 bg-leaf-50 text-leaf-500"><Icon name="check-circle" :size="24" /></span>
				<p class="text-sm text-gray-400">{{ labels.posFixEmpty }}</p>
			</div>

			<ul v-else class="oak-card divide-y divide-gray-100 overflow-hidden">
				<li v-for="r in items" :key="r.name">
					<button class="flex w-full items-center gap-3 px-4 py-3 text-left transition hover:bg-gray-50" @click="openItem(r)">
						<span class="oak-icon-tile h-9 w-9 shrink-0 bg-brand-50 text-brand-500"><Icon name="package" :size="16" /></span>
						<div class="min-w-0 flex-1">
							<p class="truncate font-semibold text-gray-900">{{ r.container_no || r.container }}</p>
							<p class="mt-0.5 truncate text-xs text-gray-500">
								<span class="font-mono">{{ r.name }}</span>
								<span v-if="r.yard_zone"> · {{ r.yard_zone }}</span>
							</p>
						</div>
						<Icon name="chevron-right" :size="16" class="shrink-0 text-gray-300" />
					</button>
				</li>
			</ul>
			<p v-if="items.length" class="text-center text-xs text-gray-400">{{ total }} {{ labels.surveyPosCount }}</p>
		</template>

		<!-- =================== DETAIL =================== -->
		<template v-else-if="mode === 'detail' && detail">
			<section class="oak-card grid grid-cols-2 gap-x-3 gap-y-2 p-4">
				<div>
					<p class="text-[11px] uppercase tracking-wide text-gray-400">{{ labels.containerNumber }}</p>
					<p class="truncate text-sm font-semibold text-gray-800">{{ detail.container_no || detail.container }}</p>
				</div>
				<div>
					<p class="text-[11px] uppercase tracking-wide text-gray-400">{{ labels.depot }}</p>
					<p class="truncate text-sm font-semibold text-gray-800">{{ detail.depot || "—" }}</p>
				</div>
				<div class="col-span-2">
					<p class="text-[11px] uppercase tracking-wide text-gray-400">{{ labels.posFixSurveyed }}</p>
					<p class="text-sm font-semibold text-gray-800">{{ surveyedPositionText }}</p>
					<p v-if="detail.surveyed_by" class="text-xs text-gray-400">{{ detail.surveyed_by }}<span v-if="detail.surveyed_on"> · {{ detail.surveyed_on }}</span></p>
				</div>
				<div v-if="detail.survey_notes" class="col-span-2">
					<p class="text-[11px] uppercase tracking-wide text-gray-400">{{ labels.surveyPosNotes }}</p>
					<p class="text-sm text-gray-700">{{ detail.survey_notes }}</p>
				</div>
			</section>

			<!-- Photos -->
			<section v-if="detail.photos && detail.photos.length" class="oak-section space-y-2">
				<p class="oak-section-title">{{ labels.surveyPosPhotos }}</p>
				<div class="flex flex-wrap gap-2">
					<button v-for="(url, i) in detail.photos" :key="i" type="button" class="oak-press" @click="openLightbox(detail.photos, i)">
						<img :src="url" class="h-20 w-20 rounded-lg border border-gray-200 object-cover" />
					</button>
				</div>
			</section>

			<!-- Approve -->
			<section class="oak-section space-y-3">
				<label class="oak-label">{{ labels.posFixNote }}</label>
				<textarea v-model.trim="note" rows="2" class="oak-input" :placeholder="labels.posFixNoteHint"></textarea>
				<p v-if="approveError" class="text-xs text-red-600">{{ approveError }}</p>
				<button class="oak-btn oak-btn-accent w-full py-3" :disabled="approveRes.loading" @click="confirmApprove">
					<Icon v-if="!approveRes.loading" name="check-circle" :size="18" />
					{{ approveRes.loading ? "…" : labels.posFixApprove }}
				</button>
			</section>
		</template>
	</div>
</template>

<script setup>
import { computed, ref } from "vue"
import { createResource } from "frappe-ui"
import { labels } from "@/utils/labels"
import { toast } from "@/utils/toast"
import { confirm } from "@/utils/confirm"
import { openLightbox } from "@/utils/lightbox"
import Icon from "@/components/Icon.vue"

const mode = ref("list") // list | detail

// ---- worklist ----
const items = ref([])
const total = ref(0)
const search = ref("")
const listRes = createResource({
	url: "container_depot.ess.position_survey.position_surveyed",
	method: "GET",
	makeParams: () => ({ search: search.value || "", page_length: 50 }),
	auto: true,
	onSuccess(data) {
		items.value = data.items || []
		total.value = data.total || 0
	},
})
let searchTimer = null
function onSearchInput() {
	clearTimeout(searchTimer)
	searchTimer = setTimeout(() => listRes.reload(), 300)
}

// ---- detail ----
const detail = ref(null)
const note = ref("")
const detailRes = createResource({
	url: "container_depot.ess.position_survey.position_detail",
	method: "GET",
	onSuccess(data) {
		detail.value = data
		note.value = ""
		mode.value = "detail"
	},
	onError(err) {
		toast.error(err?.messages?.[0] || err?.message || labels.error)
	},
})
function openItem(r) {
	detailRes.submit({ name: r.name })
}

const surveyedPositionText = computed(() => {
	const d = detail.value
	if (!d) return "—"
	const parts = [d.yard_zone, d.row && `Baris ${d.row}`, d.bay && `Bay ${d.bay}`, d.tier && `Tier ${d.tier}`].filter(Boolean)
	return parts.length ? parts.join(" · ") : "—"
})

// ---- approve ----
const approveRes = createResource({
	url: "container_depot.ess.position_survey.position_approve",
	method: "POST",
	onSuccess(data) {
		toast.success(labels.posFixApproved, { title: data.name })
		backToList()
	},
	onError(err) {
		toast.error(err?.messages?.[0] || err?.message || labels.error)
	},
})
const approveError = computed(() => (approveRes.error ? approveRes.error.messages?.[0] || approveRes.error.message : null))

async function confirmApprove() {
	const ok = await confirm({
		title: labels.posFixConfirmTitle,
		message: labels.posFixConfirmMsg,
		confirmLabel: labels.posFixApprove,
		cancelLabel: labels.confirmCancel,
	})
	if (ok) approveRes.submit({ name: detail.value.name, note: note.value || undefined })
}

function backToList() {
	mode.value = "list"
	detail.value = null
	listRes.reload()
}
</script>
