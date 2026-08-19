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
				<input v-model="search" type="search" autocapitalize="characters" autocorrect="off" autocomplete="off" spellcheck="false" enterkeyhint="search" :placeholder="labels.surveyPosSearch" class="oak-input pl-10 uppercase" @input="onSearchInput" />
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
			<!-- Container header -->
			<section class="oak-card grid grid-cols-2 gap-x-3 gap-y-2 p-4">
				<div>
					<p class="text-[11px] uppercase tracking-wide text-gray-400">{{ labels.containerNumber }}</p>
					<p class="truncate text-sm font-semibold text-gray-800">{{ detail.container_no || detail.container }}</p>
				</div>
				<div>
					<p class="text-[11px] uppercase tracking-wide text-gray-400">{{ labels.depot }}</p>
					<p class="truncate text-sm font-semibold text-gray-800">{{ detail.depot || "—" }}</p>
				</div>
			</section>

			<!-- Location note (free text — "letak container di mana") -->
			<section class="oak-section space-y-3">
				<div class="flex items-center gap-2">
					<Icon name="map-pin" :size="16" class="text-brand-500" />
					<p class="oak-section-title">{{ labels.surveyPosSection }}</p>
				</div>
				<div>
					<label class="oak-label">{{ labels.surveyPosLocation }}</label>
					<textarea v-model.trim="form.location_note" rows="3" class="oak-input" :placeholder="labels.surveyPosLocationHint"></textarea>
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
						<button type="button" class="oak-press block" @click="openLightbox(photos.map(photoSrc), idx)">
							<img :src="photoSrc(url)" class="h-20 w-20 rounded-lg border border-gray-200 object-cover" />
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
				<p class="flex items-center gap-1.5 text-xs">
					<span v-if="saveRes.loading" class="text-gray-400">{{ labels.savingDraft }}</span>
					<span v-else-if="draftError" class="text-red-600">{{ draftError }}</span>
					<span v-else-if="savedOk" class="inline-flex items-center gap-1 text-leaf-600"><Icon name="check" :size="13" /> {{ labels.draftSaved }}</span>
					<span v-else class="text-gray-400">{{ labels.autosaveHint }}</span>
				</p>
				<p v-if="saveError" class="text-xs text-red-600">{{ saveError }}</p>
				<button class="oak-btn oak-btn-primary w-full py-3" :disabled="saving || !form.location_note" @click="save">
					<Icon v-if="!saving" name="check-circle" :size="18" />
					{{ saving ? "…" : labels.surveyPosSave }}
				</button>
			</section>
		</template>
	</div>
</template>

<script setup>
import { computed, nextTick, reactive, ref, watch } from "vue"
import { labels } from "@/utils/labels"
import { toast } from "@/utils/toast"
import { openLightbox } from "@/utils/lightbox"
import Icon from "@/components/Icon.vue"
import { createResource } from "frappe-ui"
import { cachedResource } from "@/data/cache"
import { compressPhoto } from "@/utils/photo"
import { isLocalRef, photoSrc, send, stashPhoto } from "@/data/send"
import { useDetailView } from "@/utils/backstack"

const mode = ref("list") // list | detail

// Back closes the detail instead of leaving the page, and opening one starts at the top.
useDetailView(
	() => mode.value === "detail",
	() => backToList()
)

// ---- worklist ----
const allItems = ref([]) // what the server (or the offline cache) last said
const total = ref(0)
const search = ref("")
const listRes = cachedResource({
	url: "container_depot.ess.position_survey.position_pending",
	method: "GET",
	makeParams: () => ({ search: search.value || "", page_length: 50 }),
	auto: true,
	onSuccess(data) {
		allItems.value = data.items || []
		total.value = data.total || 0
	},
})

const items = computed(() => allItems.value)
let searchTimer = null
function onSearchInput() {
	clearTimeout(searchTimer)
	searchTimer = setTimeout(() => listRes.reload(), 300)
}

// ---- detail ----
const detail = ref(null)
const form = reactive({ location_note: "", notes: "" })
const photos = ref([])
const uploading = ref(false)
const photoErr = ref("")

const detailRes = cachedResource({
	url: "container_depot.ess.position_survey.position_detail",
	method: "GET",
	onSuccess(data) {
		// Muted while the fields are being filled from the server, or the assignments below
		// would each look like an edit and bounce the same values straight back.
		suppressSave.value = true
		savedOk.value = false
		detail.value = data
		form.location_note = data.location_note || ""
		form.notes = data.survey_notes || ""
		photos.value = data.photos || []
		mode.value = "detail"
		nextTick(() => {
			suppressSave.value = false
		})
	},
	onError(err) {
		toast.error(err?.messages?.[0] || err?.message || labels.error)
	},
})
function openItem(r) {
	detailRes.submit({ name: r.name })
}

// ---- autosave ----
//
// A survey is filled standing next to the tank: a location note typed one-handed, a few
// photos, sometimes a remark. Until now none of that existed anywhere but component state
// until Simpan was tapped, so a phone that slept or an app that was swiped away lost the
// walk out to the tank with it. The draft goes to the SERVER (still Pending Survey — the
// status and `surveyed_by` are untouched), so there is no local copy to go stale.
const savedOk = ref(false)
const suppressSave = ref(false)
let saveTimer = null

const saveRes = createResource({
	url: "container_depot.ess.position_survey.position_save_draft",
	method: "POST",
	onSuccess() {
		savedOk.value = true
		flushPendingSave()
	},
	// Reported inline via `draftError`, never as a toast: an autosave that could not land is
	// not worth interrupting a surveyor mid-form, and the Simpan below carries the data anyway.
	onError() {
		flushPendingSave()
	},
})
const draftError = computed(() => (saveRes.error ? saveRes.error.messages?.[0] || saveRes.error.message : null))

function saveDraft() {
	if (!detail.value) return
	saveRes.submit({
		name: detail.value.name,
		location_note: form.location_note || "",
		notes: form.notes || undefined,
		// Strip anything not uploaded yet — a `local:` string written into a photo row would
		// be a broken image for ever. Those travel with the final Simpan instead.
		photos: JSON.stringify(photos.value.filter((u) => !isLocalRef(u))),
	})
}

// Never two autosaves in flight at once. Each one rewrites the whole survey, so on a slow
// link an earlier response landing after a later one restores stale text over what the
// surveyor has since typed. When the debounce fires mid-flight we remember the edit and
// re-arm from the response handler instead of stacking a second POST.
let resaveWanted = false

function scheduleSave() {
	if (!detail.value || suppressSave.value) return
	savedOk.value = false
	if (saveTimer) clearTimeout(saveTimer)
	saveTimer = setTimeout(() => {
		saveTimer = null
		if (saveRes.loading) {
			resaveWanted = true
			return
		}
		saveDraft()
	}, 700)
}

/** Called when a save settles: if edits arrived while it flew, start the debounce again. */
function flushPendingSave() {
	if (!resaveWanted) return
	resaveWanted = false
	scheduleSave()
}

watch([() => form.location_note, () => form.notes], scheduleSave)
watch(photos, scheduleSave, { deep: true })

/**
 * Park a picked photo locally rather than uploading it now.
 *
 * A survey is taken at the far end of the yard, which is exactly where the signal is worst.
 * Uploading on pick meant the photo of where the tank actually stands was lost the moment
 * the POST failed. Now it is shrunk, kept in IndexedDB, and uploaded as part of the save.
 */
async function uploadFile(file) {
	return stashPhoto(await compressPhoto(file))
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
//
// Straight to the server, and the surveyor waits for the real answer. Nothing is held back
// locally, so a failure is reported here and now with the form still filled in.
const saving = ref(false)
const saveError = ref(null)

async function save() {
	if (!detail.value || !form.location_note || saving.value) return
	// The full payload below supersedes any draft still waiting on the debounce.
	if (saveTimer) {
		clearTimeout(saveTimer)
		saveTimer = null
	}
	resaveWanted = false
	saving.value = true
	saveError.value = null
	const d = detail.value
	try {
		await send({
			url: "container_depot.ess.position_survey.position_record",
			payload: {
				name: d.name,
				location_note: form.location_note,
				// An array, not a JSON string: `send` has to walk the payload to find the
				// `local:` photo references and swap them for real file_urls.
				photos: [...photos.value],
				notes: form.notes || undefined,
			},
		})
		toast.success(labels.surveyPosSaved, { title: d.name })
		backToList()
	} catch (e) {
		saveError.value = e?.message || labels.error
		toast.error(saveError.value)
	} finally {
		saving.value = false
	}
}

function backToList() {
	if (saveTimer) {
		clearTimeout(saveTimer)
		saveTimer = null
	}
	resaveWanted = false
	savedOk.value = false
	mode.value = "list"
	detail.value = null
	saveError.value = null
	listRes.reload()
}

</script>
