<template>
	<div class="mx-auto w-full max-w-lg space-y-4 md:max-w-2xl">
		<!-- Header — same shape as /depot/eir, /depot/cleaning and /depot/mr. Riwayat is
		     offered only to an account that also holds the survey menu: the history feed is
		     `surveyPos`, so for a Kalmar-only operator the link would 403 on tap. -->
		<div class="flex items-center justify-between">
			<div class="min-w-0">
				<h1 class="truncate text-xl font-extrabold tracking-tight text-gray-900">
					{{ labels.posFixTitle }}
				</h1>
				<p v-if="detail" class="truncate font-mono text-[11px] text-gray-500">
					{{ detail.name }} · {{ detail.container_no || detail.container }}
				</p>
				<p v-else class="text-sm text-gray-500">{{ labels.posFixHint }}</p>
			</div>
			<div class="flex shrink-0 items-center gap-2">
				<router-link
					v-if="!detail && menu.has('surveyPos')"
					to="/survey-position/history"
					class="oak-btn oak-btn-secondary px-3 py-2"
				>
					<Icon name="clock" :size="16" /> {{ labels.navHistory }}
				</router-link>
				<button v-if="detail" class="oak-btn oak-btn-secondary px-3 py-2" @click="backToList">
					<Icon name="arrow-left" :size="16" /> {{ labels.surveyPosBack }}
				</button>
			</div>
		</div>

		<!-- OPENING A SURVEY — placeholder while its detail is fetched. Without this the
		     worklist just sat there unchanged after a tap, which reads as a dead button. -->
		<SkeletonDetail v-if="detailPending" :cells="4" :sections="2" />

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
		     Same shape as the cleaning and M&R worklists: search, then a capped scroller of
		     fixed-height rows. No status toggles — everything here is in one state (Surveyed),
		     waiting for the one decision this screen exists to take. -->
		<section v-else-if="!detail" class="oak-section space-y-3">
			<div class="flex items-center gap-2">
				<Icon name="check-circle" :size="16" class="text-brand-500" />
				<p class="oak-section-title">{{ labels.posFixList }}</p>
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

			<SkeletonList v-if="listRes.loading && !items.length" :action="false" />
			<p v-else-if="!items.length" class="py-4 text-center text-sm text-gray-400">
				{{ labels.posFixEmpty }}
			</p>
			<!-- The scroller reveals about 5 rows (fixed 60px each); the rest scroll, so a
			     long queue never runs far down the page. -->
			<div v-else class="max-h-[300px] overflow-y-auto overscroll-contain">
				<ul class="divide-y divide-gray-100">
					<li v-for="r in items" :key="r.name">
						<button
							class="oak-press flex h-[60px] w-full items-center gap-3 text-left"
							@click="openItem(r)"
						>
							<span class="oak-icon-tile h-9 w-9 shrink-0 bg-brand-50 text-brand-600">
								<Icon name="package" :size="16" />
							</span>
							<div class="min-w-0 flex-1">
								<p class="truncate font-semibold text-gray-900">{{ r.container_no || r.container }}</p>
								<!-- The surveyor's note leads the subtitle: it is what decides which
								     stack the operator walks to, and reading it here saves the tap. -->
								<p class="truncate text-[11px] text-gray-400">
									<span v-if="r.location_note" class="text-gray-600">{{ r.location_note }}</span>
									<template v-else>{{ r.name }}</template>
								</p>
							</div>
							<Icon name="chevron-right" :size="18" class="shrink-0 text-gray-300" />
						</button>
					</li>
				</ul>
			</div>
			<p v-if="items.length" class="text-center text-xs text-gray-400">
				{{ total }} {{ labels.posFixCount }}
			</p>
		</section>

		<!-- =================== DETAIL =================== -->
		<template v-else>
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
					<p class="whitespace-pre-line text-sm font-semibold text-gray-800">{{ detail.location_note || "—" }}</p>
					<p v-if="detail.surveyed_by" class="text-xs text-gray-400">{{ detail.surveyed_by }}<span v-if="detail.surveyed_on"> · {{ detail.surveyed_on }}</span></p>
				</div>
				<div v-if="detail.survey_notes" class="col-span-2">
					<p class="text-[11px] uppercase tracking-wide text-gray-400">{{ labels.surveyPosNotes }}</p>
					<p class="text-sm text-gray-700">{{ detail.survey_notes }}</p>
				</div>
			</section>

			<!-- Photos -->
			<section v-if="detail.photos && detail.photos.length" class="oak-section space-y-2">
				<div class="flex items-center gap-2">
					<Icon name="camera" :size="16" class="text-brand-500" />
					<p class="oak-section-title">{{ labels.surveyPosPhotos }}</p>
				</div>
				<div class="flex flex-wrap gap-2">
					<button v-for="(url, i) in detail.photos" :key="i" type="button" class="oak-press" @click="openLightbox(detail.photos, i)">
						<img :src="url" class="h-20 w-20 rounded-lg border border-gray-200 object-cover" />
					</button>
				</div>
			</section>

			<!-- Approve -->
			<section class="oak-section space-y-3">
				<div class="flex items-center gap-2">
					<Icon name="check-circle" :size="16" class="text-brand-500" />
					<p class="oak-section-title">{{ labels.posFixApprove }}</p>
				</div>
				<div>
					<label class="oak-label">{{ labels.posFixNote }}</label>
					<textarea v-model.trim="note" rows="2" class="oak-input" :placeholder="labels.posFixNoteHint"></textarea>
				</div>
				<p v-if="approveError" class="text-xs text-red-600">{{ approveError }}</p>
				<button class="oak-btn oak-btn-accent w-full py-3" :disabled="approving" @click="confirmApprove">
					<Icon v-if="!approving" name="check-circle" :size="18" />
					{{ approving ? "…" : labels.posFixApprove }}
				</button>
			</section>
		</template>
	</div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue"
import { useRoute, useRouter } from "vue-router"
import { labels } from "@/utils/labels"
import { menu } from "@/data/menu"
import { send } from "@/data/send"
import { toast } from "@/utils/toast"
import { confirm } from "@/utils/confirm"
import { openLightbox } from "@/utils/lightbox"
import Icon from "@/components/Icon.vue"
import SkeletonList from "@/components/SkeletonList.vue"
import SkeletonDetail from "@/components/SkeletonDetail.vue"
import { cachedResource } from "@/data/cache"
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
	url: "container_depot.ess.position_survey.position_surveyed",
	method: "GET",
	makeParams: () => ({ search: search.value || "", page_length: 50 }),
	auto: true,
	onSuccess(data) {
		allItems.value = data.items || []
		total.value = data.total || 0
	},
})

// An approval already queued is done; the server just has not heard yet.
const items = computed(() => allItems.value)
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
//
// A tap has to change the screen at once, or it reads as a dead button — the worklist is
// replaced by a skeleton while the survey is fetched, and by an error card with a retry if
// it never arrives. Same three states as the cleaning and M&R forms.
const note = ref("")
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
		detail.value = data
		note.value = ""
	},
	// The error stays on the page rather than in a toast: a toast disappears, and the
	// operator would be left staring at a worklist wondering why their tap did nothing.
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

// Deep link from the bell: `/position-fix?s=CPS-0001` opens that survey straight away
// (ess/notification_routes._survey). The query is dropped once consumed so Back leaves the
// page instead of re-opening the same record for ever.
onMounted(() => {
	const s = route.query.s
	if (!s) return
	router.replace({ query: {} })
	fetchDetail(String(s))
})

// ---- approve ----
//
// The Kalmar operator is standing at the stack when they confirm the
// tank is down, which is the worst place in the yard for signal — and the confirmation is
// worth no less for arriving a few minutes late.
const approving = ref(false)
const approveError = ref(null)

async function confirmApprove() {
	if (approving.value) return
	const ok = await confirm({
		message: labels.posFixConfirmMsg,
		confirmLabel: labels.posFixApprove,
		cancelLabel: labels.confirmCancel,
	})
	if (!ok) return
	approving.value = true
	approveError.value = null
	const d = detail.value
	try {
		await send({
			url: "container_depot.ess.position_survey.position_approve",
			payload: { name: d.name, note: note.value || undefined },
		})
		toast.success(labels.posFixApproved, { title: d.name })
		backToList()
	} catch (e) {
		approveError.value = e?.message || labels.error
		toast.error(approveError.value)
	} finally {
		approving.value = false
	}
}

function backToList() {
	detail.value = null
	detailPending.value = false
	detailFailed.value = false
	openingName = null
	approveError.value = null
	listRes.reload()
}
</script>
