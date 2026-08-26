<template>
	<div class="mx-auto w-full max-w-lg space-y-4 md:max-w-2xl">
		<!-- Header — same shape as /depot/eir, /depot/cleaning and /depot/mr: the title on
		     the left, the one escape hatch on the right (Riwayat from the worklist, Kembali
		     from an open survey). -->
		<div class="flex items-center justify-between">
			<div class="min-w-0">
				<h1 class="truncate text-xl font-extrabold tracking-tight text-gray-900">
					{{ labels.surveyPosTitle }}
				</h1>
				<p v-if="detail" class="truncate font-mono text-[11px] text-gray-500">
					{{ detail.name }} · {{ detail.container_no || detail.container }}
				</p>
				<p v-else class="text-sm text-gray-500">{{ labels.surveyPosHint }}</p>
			</div>
			<div class="flex shrink-0 items-center gap-2">
				<router-link
					v-if="!detail"
					to="/survey-position/history"
					class="oak-btn oak-btn-secondary px-3 py-2"
				>
					<Icon name="clock" :size="16" /> {{ labels.navHistory }}
				</router-link>
				<button v-else class="oak-btn oak-btn-secondary px-3 py-2" @click="backToList">
					<Icon name="arrow-left" :size="16" /> {{ labels.surveyPosBack }}
				</button>
			</div>
		</div>

		<!-- OPENING A SURVEY — placeholder while its detail is fetched. Without this the
		     worklist just sat there unchanged after a tap, which reads as a dead button. -->
		<SkeletonDetail v-if="detailPending" :cells="4" :sections="3" />

		<!-- The detail could not be fetched and there is no cached copy to fall back on. -->
		<section v-else-if="detailFailed" class="oak-card space-y-3 p-6 text-center">
			<span class="oak-icon-tile mx-auto h-12 w-12 bg-red-50 text-red-500">
				<Icon name="alert-triangle" :size="24" />
			</span>
			<p class="text-sm text-gray-600">{{ detailError }}</p>
			<div class="flex gap-2">
				<button class="oak-btn oak-btn-secondary flex-1" @click="backToList">{{ labels.surveyPosBack }}</button>
				<button class="oak-btn oak-btn-primary flex-1" @click="retryDetail">{{ labels.retry }}</button>
			</div>
		</section>

		<!-- =================== WORKLIST ===================
		     Same shape as the cleaning and M&R worklists: search, Semua / Belum / Dikerjakan
		     toggles with counts, then a capped scroller of fixed-height rows. -->
		<section v-else-if="!detail" class="oak-section space-y-3">
			<div class="flex items-center gap-2">
				<Icon name="map-pin" :size="16" class="text-brand-500" />
				<p class="oak-section-title">{{ labels.surveyPosList }}</p>
			</div>
			<div class="flex gap-2">
				<input
					v-model="search"
					class="oak-input uppercase"
					:placeholder="labels.surveyPosSearch"
					autocapitalize="characters"
					autocorrect="off"
					autocomplete="off"
					spellcheck="false"
					enterkeyhint="search"
					@input="onSearchInput"
					@keyup.enter="reloadList"
				/>
				<button class="oak-btn oak-btn-secondary shrink-0 px-3" @click="reloadList">
					<Icon name="search" :size="16" />
				</button>
			</div>

			<!-- Belum / Dikerjakan split: a survey is "belum" until Mulai claims it; once
			     located it leaves this worklist for the Kalmar one. -->
			<div class="grid grid-cols-3 gap-2">
				<button
					v-for="f in FILTERS"
					:key="f.key"
					class="oak-toggle flex items-center justify-center gap-1.5"
					:class="filter === f.key ? 'oak-toggle-on' : 'oak-toggle-off'"
					@click="filter = f.key"
				>
					{{ f.label }}
					<span class="oak-chip" :class="filter === f.key ? 'bg-brand-100 text-brand-700' : 'bg-gray-100 text-gray-500'">{{ f.count }}</span>
				</button>
			</div>

			<SkeletonList v-if="listRes.loading && !allItems.length" :action="false" />
			<p v-else-if="!items.length" class="py-4 text-center text-sm text-gray-400">
				{{ emptyText }}
			</p>
			<!-- The scroller reveals about 5 rows (fixed 60px each); the rest scroll, so a
			     long queue never runs far down the page. -->
			<div v-else class="max-h-[300px] overflow-y-auto overscroll-contain">
				<ul class="divide-y divide-gray-100">
					<li v-for="r in items" :key="r.name">
						<div class="flex h-[60px] items-center gap-3">
							<button class="oak-press flex h-full min-w-0 flex-1 items-center gap-3 text-left" @click="openItem(r)">
								<span class="oak-icon-tile h-9 w-9 shrink-0 bg-brand-50 text-brand-600">
									<Icon name="map-pin" :size="16" />
								</span>
								<div class="min-w-0 flex-1">
									<p class="truncate font-semibold text-gray-900">{{ r.container_no || r.container }}</p>
									<!-- One subtitle line, ordered by urgency so truncation eats the
									     least important half: sent back for a redo, being worked, then
									     the depot and the id. -->
									<p class="flex items-center gap-1.5 text-[11px]">
										<span v-if="r.reopen_note" class="oak-chip shrink-0 bg-orange-100 text-orange-800">
											<Icon name="rotate-ccw" :size="11" /> {{ labels.posReopenNote }}
										</span>
										<span v-else-if="r.status === 'In Survey'" class="oak-chip shrink-0 bg-amber-100 text-amber-800">
											<Icon name="clock" :size="11" /> {{ labels.surveyPosInProgress }}
										</span>
										<span class="truncate text-gray-400">
											<template v-if="r.depot">{{ r.depot }} · </template>{{ r.name }}
										</span>
									</p>
								</div>
							</button>
							<button
								v-if="r.status !== 'In Survey'"
								class="oak-btn oak-btn-secondary shrink-0 px-3 py-1.5 text-xs"
								@click.stop="startRow(r)"
							>
								{{ labels.surveyPosStart }}
							</button>
						</div>
					</li>
				</ul>
			</div>
			<p v-if="items.length" class="text-center text-xs text-gray-400">
				{{ total }} {{ labels.surveyPosCount }}
			</p>
		</section>

		<!-- =================== DETAIL =================== -->
		<template v-else>
			<!-- GATE: the survey must be started before its form is accessible — same rule as
			     the cleaning form, and the press is what claims the tank. -->
			<section v-if="detail.status !== 'In Survey'" class="oak-card space-y-4 p-5 text-center">
				<span class="oak-icon-tile mx-auto h-14 w-14 bg-brand-50 text-brand-600"><Icon name="map-pin" :size="26" /></span>
				<div class="space-y-1">
					<p class="font-bold text-gray-900">{{ detail.container_no || detail.container }}</p>
					<p class="font-mono text-xs text-gray-400">{{ detail.name }}</p>
					<p class="text-sm text-gray-500">{{ labels.surveyPosStartGate }}</p>
				</div>
				<button class="oak-btn oak-btn-primary w-full py-3 text-base" :disabled="starting" @click="startCurrent">
					{{ starting ? "…" : labels.surveyPosStartFull }}
				</button>
			</section>

			<template v-else>
			<!-- Sent back for a redo: why, before anything else on the screen. -->
			<section v-if="detail.reopen_note" class="oak-card border-orange-200 bg-orange-50 space-y-1 p-4">
				<p class="flex items-center gap-1.5 text-sm font-bold text-orange-800">
					<Icon name="rotate-ccw" :size="15" /> {{ labels.posReopenNote }}
				</p>
				<p class="whitespace-pre-line text-sm text-orange-900">{{ detail.reopen_note }}</p>
			</section>

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
		</template>
	</div>
</template>

<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import { labels } from "@/utils/labels"
import { saveToast, toast } from "@/utils/toast"
import { openLightbox } from "@/utils/lightbox"
import Icon from "@/components/Icon.vue"
import SkeletonList from "@/components/SkeletonList.vue"
import SkeletonDetail from "@/components/SkeletonDetail.vue"
import { createResource } from "frappe-ui"
import { cachedResource } from "@/data/cache"
import { isLocalRef, photoSrc, send, uploadPhoto } from "@/data/send"
import { useDetailView } from "@/utils/backstack"

const route = useRoute()
const router = useRouter()

// The open survey, or null for the worklist. Declared up here because the back-stack watch
// below reads it on the spot; `detail` IS the mode, and a second ref saying the same thing
// would only be a second thing to get wrong.
const detail = ref(null)

// Back closes the detail instead of leaving the page, and opening one starts at the top.
useDetailView(
	() => !!detail.value,
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

// Belum / Dikerjakan, exactly as the cleaning worklist splits them. "Dikerjakan" can only
// ever hold this surveyor's own jobs: a survey claimed by somebody else never reaches the
// list (work_claim filters it server-side).
const filter = ref("all")
const startedItems = computed(() => allItems.value.filter((r) => r.status === "In Survey"))
const todoItems = computed(() => allItems.value.filter((r) => r.status !== "In Survey"))
const items = computed(() => {
	if (filter.value === "started") return startedItems.value
	if (filter.value === "todo") return todoItems.value
	return allItems.value
})
const FILTERS = computed(() => [
	{ key: "all", label: labels.surveyPosFilterAll, count: allItems.value.length },
	{ key: "todo", label: labels.surveyPosFilterTodo, count: todoItems.value.length },
	{ key: "started", label: labels.surveyPosFilterStarted, count: startedItems.value.length },
])
const emptyText = computed(() => {
	if (!allItems.value.length) return labels.surveyPosEmpty
	if (filter.value === "started") return labels.surveyPosFilterEmptyStarted
	if (filter.value === "todo") return labels.surveyPosFilterEmptyTodo
	return labels.surveyPosEmpty
})

let searchTimer = null
function reloadList() {
	clearTimeout(searchTimer)
	listRes.reload()
}
function onSearchInput() {
	clearTimeout(searchTimer)
	searchTimer = setTimeout(() => listRes.reload(), 300)
}

// ---- detail ----
const form = reactive({ location_note: "", notes: "" })
const photos = ref([])
const uploading = ref(false)
const photoErr = ref("")

// A tap has to change the screen at once, or it reads as a dead button — the worklist is
// replaced by a skeleton while the survey is fetched, and by an error card with a retry if
// it never arrives. Same three states as the cleaning and M&R forms.
const detailPending = ref(false)
const detailFailed = ref(false)
const detailError = ref("")
let openingName = null

const detailRes = cachedResource({
	url: "container_depot.ess.position_survey.position_detail",
	method: "GET",
	onSuccess(data) {
		detailPending.value = false
		detailFailed.value = false
		// Muted while the fields are being filled from the server, or the assignments below
		// would each look like an edit and bounce the same values straight back.
		suppressSave.value = true
		savedOk.value = false
		detail.value = data
		form.location_note = data.location_note || ""
		form.notes = data.survey_notes || ""
		photos.value = data.photos || []
		nextTick(() => {
			suppressSave.value = false
		})
	},
	// The error stays on the page rather than in a toast: a toast disappears, and the
	// surveyor would be left staring at a worklist wondering why their tap did nothing.
	onError(err) {
		detailPending.value = false
		detailFailed.value = true
		detailError.value = err?.messages?.[0] || err?.message || labels.error
	},
})
function fetchDetail(name) {
	openingName = name
	detailPending.value = true
	detailFailed.value = false
	detailRes.submit({ name })
}
function openItem(r) {
	fetchDetail(r.name)
}
function retryDetail() {
	if (openingName) fetchDetail(openingName)
}

// ---- Mulai ----
//
// The press that claims the tank: from that moment the survey is gone from every other
// surveyor's worklist. The status is flipped locally rather than re-fetched — the response
// carries nothing the screen needs beyond it, and waiting is what would make "Mulai"
// impossible in a dead spot, which is exactly where a surveyor stands.
const starting = ref(false)

async function startSurvey(name) {
	try {
		await send({
			url: "container_depot.ess.position_survey.position_start",
			payload: { name },
		})
		toast.success(labels.surveyPosStarted)
		return true
	} catch (e) {
		toast.error(e?.message || labels.error)
		return false
	}
}

async function startRow(r) {
	if (await startSurvey(r.name)) r.status = "In Survey"
}

async function startCurrent() {
	if (starting.value || !detail.value) return
	starting.value = true
	try {
		if (await startSurvey(detail.value.name)) {
			detail.value = { ...detail.value, status: "In Survey" }
		}
	} finally {
		starting.value = false
	}
}

// Deep link from the bell: `/survey-position?s=CPS-0001` opens that survey straight away
// (ess/notification_routes._survey). The query is dropped once consumed so Back leaves the
// page instead of re-opening the same record for ever.
onMounted(() => {
	const s = route.query.s
	if (!s) return
	router.replace({ query: {} })
	fetchDetail(String(s))
})

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
		saveToast.done()
		flushPendingSave()
	},
	// Reported inline via `draftError`, never as a red toast: an autosave that could not land
	// is not worth interrupting a surveyor mid-form, and the Simpan below carries the data
	// anyway. The "Menyimpan…" toast still has to go, so the slot is simply taken back.
	onError() {
		saveToast.fail("")
		flushPendingSave()
	},
})
const draftError = computed(() => (saveRes.error ? saveRes.error.messages?.[0] || saveRes.error.message : null))

function saveDraft() {
	if (!detail.value) return
	saveToast.start()
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
 * Shrink a picked photo and upload it now, so the draft save that follows records it.
 *
 * A survey is taken at the far end of the yard, which is exactly where the signal is worst —
 * so an upload that cannot land parks the photo on the handset instead of failing, and it
 * leaves with the final Simpan (see data/send.js).
 */
async function uploadFile(file) {
	return uploadPhoto(file)
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
	detail.value = null
	detailPending.value = false
	detailFailed.value = false
	openingName = null
	saveError.value = null
	listRes.reload()
}

</script>
