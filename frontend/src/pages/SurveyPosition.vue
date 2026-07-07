<template>
	<div class="mx-auto w-full max-w-lg space-y-4 md:max-w-2xl">
		<!-- Header -->
		<div class="flex flex-wrap items-center justify-between gap-2">
			<div class="flex items-center gap-2">
				<button v-if="mode === 'detail'" class="oak-btn oak-btn-secondary px-2 py-2" @click="backToList">
					<Icon name="arrow-left" :size="18" />
				</button>
				<span class="oak-icon-tile h-9 w-9 bg-brand-50 text-brand-600"><Icon name="map-pin" :size="20" /></span>
				<div class="min-w-0">
					<h1 class="text-lg font-extrabold tracking-tight">{{ labels.surveyPosTitle }}</h1>
					<p class="truncate text-xs text-gray-500">{{ mode === 'detail' ? (detail?.container_no || '') : labels.surveyPosDesc }}</p>
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
				<span class="oak-icon-tile h-12 w-12 bg-gray-100 text-gray-300"><Icon name="map-pin" :size="24" /></span>
				<p class="text-sm text-gray-400">{{ labels.surveyPosEmpty }}</p>
			</div>

			<ul v-else class="oak-card divide-y divide-gray-100 overflow-hidden">
				<li v-for="r in items" :key="r.name">
					<button class="flex w-full items-center gap-3 px-4 py-3 text-left transition hover:bg-gray-50" @click="openItem(r)">
						<span class="oak-icon-tile h-9 w-9 shrink-0 bg-amber-50 text-amber-600"><Icon name="package" :size="16" /></span>
						<div class="min-w-0 flex-1">
							<p class="truncate font-semibold text-gray-900">{{ r.container_no || r.container }}</p>
							<p class="mt-0.5 truncate text-xs text-gray-500"><span class="font-mono">{{ r.name }}</span><span v-if="r.depot"> · {{ r.depot }}</span></p>
						</div>
						<Icon name="chevron-right" :size="16" class="shrink-0 text-gray-300" />
					</button>
				</li>
			</ul>
			<p v-if="items.length" class="text-center text-xs text-gray-400">{{ total }} {{ labels.surveyPosCount }}</p>
		</template>

		<!-- =================== DETAIL =================== -->
		<template v-else-if="mode === 'detail' && detail">
			<!-- Container + current recorded position -->
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
					<p class="text-[11px] uppercase tracking-wide text-gray-400">{{ labels.surveyPosCurrent }}</p>
					<p class="text-sm font-semibold text-gray-800">{{ currentPositionText }}</p>
				</div>
			</section>

			<!-- Yard position inputs -->
			<section class="oak-section space-y-3">
				<div class="flex items-center gap-2">
					<Icon name="map-pin" :size="16" class="text-brand-500" />
					<p class="oak-section-title">{{ labels.surveyPosSection }}</p>
				</div>
				<div>
					<label class="oak-label">{{ labels.surveyPosZone }}</label>
					<SearchSelect
						v-model="form.yard_zone"
						:options="detail.zones || []"
						:option-value="(z) => z.name"
						:option-label="(z) => `${z.zone_name || z.name}${z.category ? ' · ' + z.category : ''}`"
						:group-by="(z) => z.category || '—'"
						:placeholder="labels.surveyPosZonePick"
						:search-placeholder="labels.selectSearch"
					/>
					<p v-if="detail.recommended_zone" class="mt-1 text-xs text-leaf-600">
						<Icon name="check" :size="12" /> {{ labels.surveyPosRecommend }}: {{ zoneName(detail.recommended_zone) }}
					</p>
				</div>
				<div class="grid grid-cols-3 gap-2">
					<div>
						<label class="oak-label">{{ labels.surveyPosRow }}</label>
						<input v-model.trim="form.row" type="text" class="oak-input px-2.5 py-2" inputmode="numeric" />
					</div>
					<div>
						<label class="oak-label">{{ labels.surveyPosBay }}</label>
						<input v-model.trim="form.bay" type="text" class="oak-input px-2.5 py-2" />
					</div>
					<div>
						<label class="oak-label">{{ labels.surveyPosTier }}</label>
						<input v-model.number="form.tier" type="number" min="1" class="oak-input px-2.5 py-2" inputmode="numeric" />
					</div>
				</div>
			</section>

			<!-- Photos -->
			<section class="oak-section space-y-3">
				<div class="flex items-center gap-2">
					<Icon name="camera" :size="16" class="text-brand-500" />
					<p class="oak-section-title">{{ labels.surveyPosPhotos }}</p>
				</div>
				<div class="flex flex-wrap items-center gap-2">
					<div v-for="(url, idx) in photos" :key="url" class="relative">
						<button type="button" class="oak-press block" @click="openLightbox(photos, idx)">
							<img :src="url" class="h-20 w-20 rounded-lg border border-gray-200 object-cover" />
						</button>
						<button type="button" class="absolute -right-1.5 -top-1.5 flex h-5 w-5 items-center justify-center rounded-full bg-gray-900 text-white shadow" @click="photos.splice(idx, 1)">
							<Icon name="x" :size="12" />
						</button>
					</div>
					<label class="flex h-20 w-20 cursor-pointer flex-col items-center justify-center gap-0.5 rounded-lg border border-dashed border-gray-300 text-gray-400 transition hover:border-brand-400 hover:text-brand-500">
						<input type="file" accept="image/*" capture="environment" multiple class="hidden" :disabled="uploading" @change="onPhotoPick($event)" />
						<span v-if="uploading" class="text-xs">…</span>
						<template v-else><Icon name="camera" :size="20" /><span class="text-[9px] font-medium">{{ labels.photo }}</span></template>
					</label>
				</div>
				<p v-if="photoErr" class="text-xs text-red-600">{{ photoErr }}</p>
			</section>

			<!-- Notes -->
			<section class="oak-section space-y-2">
				<label class="oak-label">{{ labels.surveyPosNotes }}</label>
				<textarea v-model.trim="form.notes" rows="2" class="oak-input"></textarea>
			</section>

			<!-- Save -->
			<section class="space-y-2">
				<p v-if="saveError" class="text-xs text-red-600">{{ saveError }}</p>
				<button class="oak-btn oak-btn-primary w-full py-3" :disabled="recordRes.loading || !form.yard_zone" @click="save">
					<Icon v-if="!recordRes.loading" name="check-circle" :size="18" />
					{{ recordRes.loading ? "…" : labels.surveyPosSave }}
				</button>
			</section>
		</template>
	</div>
</template>

<script setup>
import { computed, reactive, ref } from "vue"
import { createResource } from "frappe-ui"
import { labels } from "@/utils/labels"
import { toast } from "@/utils/toast"
import { openLightbox } from "@/utils/lightbox"
import Icon from "@/components/Icon.vue"
import SearchSelect from "@/components/SearchSelect.vue"

const mode = ref("list") // list | detail

// ---- worklist ----
const items = ref([])
const total = ref(0)
const search = ref("")
const listRes = createResource({
	url: "container_depot.ess.position_survey.position_pending",
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
const form = reactive({ yard_zone: "", row: "", bay: "", tier: null, notes: "" })
const photos = ref([])
const uploading = ref(false)
const photoErr = ref("")

const detailRes = createResource({
	url: "container_depot.ess.position_survey.position_detail",
	method: "GET",
	onSuccess(data) {
		detail.value = data
		form.yard_zone = data.recommended_zone || ""
		form.row = ""
		form.bay = ""
		form.tier = null
		form.notes = ""
		photos.value = []
		mode.value = "detail"
	},
	onError(err) {
		toast.error(err?.messages?.[0] || err?.message || labels.error)
	},
})
function openItem(r) {
	detailRes.submit({ name: r.name })
}

const currentPositionText = computed(() => {
	const c = detail.value?.current
	if (!c) return "—"
	const parts = [c.zone_name || c.zone, c.row && `Baris ${c.row}`, c.bay && `Bay ${c.bay}`, c.tier && `Tier ${c.tier}`].filter(Boolean)
	return parts.length ? parts.join(" · ") : "—"
})
function zoneName(name) {
	const z = (detail.value?.zones || []).find((x) => x.name === name)
	return z ? z.zone_name || z.name : name
}

// ---- photo upload (reuses the PWA upload_file pattern) ----
async function uploadFile(file) {
	const fd = new FormData()
	fd.append("file", file, file.name)
	fd.append("is_private", 1)
	fd.append("folder", "Home")
	const res = await fetch("/api/method/upload_file", {
		method: "POST",
		headers: { "X-Frappe-CSRF-Token": window.csrf_token || "" },
		body: fd,
	})
	if (!res.ok) throw new Error("upload failed")
	const data = await res.json()
	return data.message.file_url
}
async function onPhotoPick(event) {
	const files = Array.from(event.target.files || [])
	event.target.value = ""
	if (!files.length) return
	photoErr.value = ""
	uploading.value = true
	try {
		for (const f of files) photos.value.push(await uploadFile(f))
	} catch (e) {
		photoErr.value = labels.photoError
	} finally {
		uploading.value = false
	}
}

// ---- save ----
const recordRes = createResource({
	url: "container_depot.ess.position_survey.position_record",
	method: "POST",
	onSuccess(data) {
		toast.success(labels.surveyPosSaved, { title: data.name })
		backToList()
	},
	onError(err) {
		toast.error(err?.messages?.[0] || err?.message || labels.error)
	},
})
const saveError = computed(() => (recordRes.error ? recordRes.error.messages?.[0] || recordRes.error.message : null))

function save() {
	if (!detail.value || !form.yard_zone) return
	recordRes.submit({
		name: detail.value.name,
		yard_zone: form.yard_zone,
		row: form.row || undefined,
		bay: form.bay || undefined,
		tier: form.tier || undefined,
		photos: JSON.stringify(photos.value),
		notes: form.notes || undefined,
	})
}

function backToList() {
	mode.value = "list"
	detail.value = null
	listRes.reload()
}
</script>
