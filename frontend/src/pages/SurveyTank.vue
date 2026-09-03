<template>
	<div class="mx-auto w-full max-w-lg space-y-4 md:max-w-2xl">
		<div class="flex items-center justify-between">
			<div class="min-w-0">
				<h1 class="truncate text-xl font-extrabold tracking-tight text-gray-900">
					{{ labels.tankDetailTitle }}
				</h1>
				<p v-if="tank" class="truncate font-mono text-[11px] text-gray-500">{{ tank.name }}</p>
			</div>
			<button class="oak-btn oak-btn-secondary shrink-0 px-3 py-2" @click="goBack">
				<Icon name="arrow-left" :size="16" /> {{ labels.surveyPosBack }}
			</button>
		</div>

		<SkeletonDetail v-if="pending" :cells="4" :sections="3" />

		<section v-else-if="failed" class="oak-card space-y-3 p-6 text-center">
			<span class="oak-icon-tile mx-auto h-12 w-12 bg-red-50 text-red-500">
				<Icon name="alert-triangle" :size="24" />
			</span>
			<p class="text-sm text-gray-600">{{ error }}</p>
			<div class="flex gap-2">
				<button class="oak-btn oak-btn-secondary flex-1" @click="goBack">{{ labels.surveyPosBack }}</button>
				<button class="oak-btn oak-btn-primary flex-1" @click="load">{{ labels.retry }}</button>
			</div>
		</section>

		<template v-else-if="tank">
			<!-- Identity + status, together at the top: the operator is holding the phone next
			     to the tank and has to confirm they are at the right one before anything else. -->
			<section class="oak-card space-y-2 p-4">
				<div class="flex items-start justify-between gap-2">
					<p class="min-w-0 truncate text-2xl font-extrabold tracking-tight text-gray-900">
						{{ tank.container_no || tank.container }}
					</p>
					<span class="oak-chip shrink-0" :class="chipClass(tank.status)">{{ statusLabel(tank.status) }}</span>
				</div>
				<p v-if="tank.schedule" class="truncate text-sm font-semibold text-gray-600">
					{{ tank.schedule.principal || tank.booking }}
				</p>
			</section>

			<!-- Sent back for a redo. First thing on the page after the identity, because it
			     changes what the operator is here to do. -->
			<section v-if="tank.reopen_note" class="oak-card space-y-1 border-orange-200 bg-orange-50 p-4">
				<p class="flex items-center gap-1.5 text-sm font-bold text-orange-800">
					<Icon name="rotate-ccw" :size="15" /> {{ labels.posReopenNote }}
				</p>
				<p class="whitespace-pre-line text-sm text-orange-900">{{ tank.reopen_note }}</p>
			</section>

			<!-- The location is READ from the Container master, never stored on this row — it is
			     a fact about the tank, kept current by the Letak Tank menu that anyone in the
			     yard can use. The age comes with it, because "blok kanan, 20 menit lalu" and
			     "blok kanan, 3 bulan lalu" are not the same instruction. -->
			<section class="oak-card space-y-2 p-4" :class="tank.located ? '' : 'border-red-200 bg-red-50'">
				<div class="flex items-center justify-between gap-2">
					<p class="text-[11px] uppercase tracking-wide text-gray-400">{{ labels.tankDetailLocation }}</p>
					<router-link :to="`/tank-position?c=${tank.container}`" class="oak-link text-[11px]">
						{{ labels.tankPosUpdate }}
					</router-link>
				</div>
				<template v-if="tank.located">
					<p class="flex items-start gap-1.5 whitespace-pre-line text-base font-bold text-gray-900">
						<Icon name="map-pin" :size="16" class="mt-1 shrink-0 text-brand-500" />
						{{ tank.location_note }}
					</p>
					<p class="text-xs" :class="tank.fresh ? 'text-gray-500' : 'text-amber-700'">
						{{ since(tank.location_updated_on) }}
						<template v-if="tank.location_updated_by">
							· {{ labels.tankPosBy }} {{ tank.location_updated_by }}
						</template>
					</p>
				</template>
				<template v-else>
					<p class="flex items-center gap-1.5 text-sm font-bold text-red-700">
						<Icon name="alert-triangle" :size="15" /> {{ labels.tankPosUnlocated }}
					</p>
				</template>
			</section>

			<section class="oak-card grid grid-cols-2 gap-x-3 gap-y-2 p-4">
				<div v-if="tank.schedule">
					<p class="text-[11px] uppercase tracking-wide text-gray-400">{{ labels.surveyOrderSurveyor }}</p>
					<p class="truncate text-sm font-semibold text-gray-800">{{ tank.schedule.surveyor || "—" }}</p>
				</div>
				<div v-if="tank.schedule?.plan_date">
					<p class="text-[11px] uppercase tracking-wide text-gray-400">{{ labels.surveyOrderPickup }}</p>
					<p class="text-sm font-semibold text-gray-800">{{ fmtDate(tank.schedule.plan_date) }}</p>
				</div>
			</section>

			<!-- Where the tank is in the two-step flow, said in a sentence rather than as a
			     chip alone: "Lowered" tells an operator nothing about whose turn it is. -->
			<section class="oak-card space-y-2 p-4" :class="statusCardClass">
				<p class="text-[11px] uppercase tracking-wide text-gray-400">{{ labels.tankDetailStatus }}</p>
				<p class="flex items-center gap-1.5 text-sm font-bold" :class="statusTextClass">
					<Icon :name="statusIcon(tank.status)" :size="16" /> {{ statusLabel(tank.status) }}
				</p>
				<p class="text-sm text-gray-600">{{ statusMessage }}</p>
				<!-- The lowering stamp sits with the status, not only down in the audit trail:
				     once a tank is down, WHEN it came down is the fact the surveyor and the
				     Kalmar operator are both working off — it dates the yard position they are
				     about to trust, and it is what a stale row is spotted by. -->
				<p v-if="tank.lowered_on" class="flex items-center gap-1.5 border-t border-gray-100 pt-2 text-xs text-gray-500">
					<Icon name="arrow-down-circle" :size="13" class="shrink-0 text-leaf-600" />
					<span class="truncate">
						<span class="text-gray-400">{{ labels.posLoweredOn }}:</span>
						<span class="font-semibold text-gray-700"> {{ stamp(tank.lowered_on) }}</span>
					</span>
				</p>
			</section>

			<!-- =============== STEP 1 — TANDAI LOWERED ===============
			     Open to both field menus: normally the Kalmar operator on the reachstacker,
			     but a surveyor already standing at a tank that is plainly on the ground
			     should not have to wait for somebody else before the day can start. -->
			<section v-if="canLower" class="oak-section space-y-3">
				<div class="flex items-center gap-2">
					<Icon name="arrow-down-circle" :size="16" class="text-amber-500" />
					<p class="oak-section-title">{{ labels.posLoweredAction }}</p>
				</div>
				<div>
					<label class="oak-label">
						{{ tank.located ? labels.posLocationLabel : labels.posLocationRequired }}
					</label>
					<textarea
						v-model.trim="form.location_note"
						rows="2"
						class="oak-input"
						:placeholder="labels.posLocationHint"
					/>
					<p class="mt-1 text-[11px] text-gray-400">{{ labels.posLocationWrites }}</p>
				</div>
				<div>
					<label class="oak-label">{{ labels.posLoweredNote }}</label>
					<textarea
						v-model.trim="form.lowering_note"
						rows="2"
						class="oak-input"
						:placeholder="labels.posLoweredNoteHint"
					/>
				</div>
				<p v-if="lowerError" class="text-xs text-red-600">{{ lowerError }}</p>
				<button
					class="oak-btn oak-btn-accent w-full py-3 text-base"
					:disabled="lowering || (!tank.located && !form.location_note)"
					@click="markLowered"
				>
					<Icon v-if="!lowering" name="check-circle" :size="18" />
					{{ lowering ? "…" : labels.posLoweredAction }}
				</button>
			</section>

			<!-- =============== STEP 2 — SELESAI SURVEY ===============
			     The surveyor's alone, and the only press on this screen that submits
			     anything. Notes are optional on purpose — demanding evidence for
			     "I have looked at this tank" only teaches the crew to type a full stop. -->
			<section v-if="canFinish" class="oak-section space-y-3">
				<div class="flex items-center gap-2">
					<Icon name="clipboard" :size="16" class="text-brand-500" />
					<p class="oak-section-title">{{ labels.surveyFinishAction }}</p>
				</div>
				<div>
					<label class="oak-label">{{ labels.surveyPosNotes }}</label>
					<textarea
						v-model.trim="form.notes"
						rows="2"
						class="oak-input"
						:placeholder="labels.surveyPosNotesHint"
					/>
				</div>
				<p v-if="finishError" class="text-xs text-red-600">{{ finishError }}</p>
				<button
					class="oak-btn oak-btn-primary w-full py-3 text-base"
					:disabled="finishing"
					@click="finishSurvey"
				>
					<Icon v-if="!finishing" name="check-circle" :size="18" />
					{{ finishing ? "…" : labels.surveyFinishConfirmYes }}
				</button>
				<p class="text-center text-xs text-gray-400">{{ labels.surveyFinishEirHint }}</p>
			</section>

			<!-- The surveyor's own gate: the tank is theirs to close, but it is still up. -->
			<section v-else-if="menu.has('surveyPos') && tank.status === WAITING" class="oak-card p-4 text-center">
				<p class="text-sm text-gray-500">{{ labels.surveyFinishGate }}</p>
			</section>

			<!-- The last few readings of where this tank is, so the operator can see whether it
			     has been reported in three different blocks this morning — which is what a tank
			     nobody has actually found looks like. -->
			<section v-if="(tank.position_history || []).length" class="oak-section space-y-2">
				<div class="flex items-center justify-between gap-2">
					<div class="flex items-center gap-2">
						<Icon name="map-pin" :size="16" class="text-brand-500" />
						<p class="oak-section-title">{{ labels.tankPosHistory }}</p>
					</div>
					<router-link :to="`/tank-position?c=${tank.container}`" class="oak-link text-[11px]">
						{{ labels.tankPosOpenFinder }}
					</router-link>
				</div>
				<ul class="space-y-2 text-[13px]">
					<li v-for="(h, i) in tank.position_history" :key="h.name" class="flex items-start gap-2">
						<span class="mt-1.5 h-2 w-2 shrink-0 rounded-full" :class="i === 0 ? 'bg-brand-500' : 'bg-gray-300'" />
						<div class="min-w-0 flex-1">
							<p class="whitespace-pre-line font-medium text-gray-800">{{ h.location_note }}</p>
							<p class="text-xs text-gray-400">
								{{ fmtDateTime(h.recorded_on) }}
								<template v-if="h.recorded_by"> · {{ h.recorded_by }}</template>
							</p>
							<!-- The picture of the stack, on the screen where somebody is deciding
							     which stack to walk to. Same readings, same photos as Letak Tank —
							     one source (container_position._attach_photos), never a copy. -->
							<div v-if="h.photos && h.photos.length" class="mt-1.5 flex flex-wrap gap-1.5">
								<img
									v-for="(url, j) in h.photos"
									:key="url"
									:src="url"
									class="h-14 w-14 cursor-pointer rounded-md border border-gray-200 object-cover"
									loading="lazy"
									@click="openLightbox(h.photos, j)"
								/>
							</div>
						</div>
					</li>
				</ul>
			</section>

			<!-- Who did what, when — the audit trail the two teams read to settle "I already
			     dropped that one". -->
			<section class="oak-section space-y-2">
				<div class="flex items-center gap-2">
					<Icon name="clock" :size="16" class="text-gray-400" />
					<p class="oak-section-title">{{ labels.tankDetailHistory }}</p>
				</div>
				<ul class="space-y-2 text-[13px]">
					<li v-if="tank.lowered_by" class="flex items-start gap-2">
						<span class="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-leaf-500" />
						<div class="min-w-0">
							<p class="font-semibold text-gray-800">{{ labels.posLoweredBy }} {{ tank.lowered_by }}</p>
							<p class="text-xs text-gray-400">{{ stamp(tank.lowered_on) }}</p>
						</div>
					</li>
					<li v-if="tank.surveyed_by" class="flex items-start gap-2">
						<span class="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-brand-500" />
						<div class="min-w-0">
							<p class="font-semibold text-gray-800">{{ labels.surveyPosSurveyedBy }} {{ tank.surveyed_by }}</p>
							<p class="text-xs text-gray-400">{{ stamp(tank.surveyed_on) }}</p>
						</div>
					</li>
					<li v-if="tank.eir_out" class="flex items-start gap-2">
						<span class="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-amber-500" />
						<div class="min-w-0">
							<p class="font-semibold text-gray-800">{{ labels.tankDetailEirOut }}</p>
							<p class="font-mono text-xs text-gray-400">{{ tank.eir_out }}</p>
						</div>
					</li>
					<li v-if="!tank.lowered_by && !tank.surveyed_by" class="text-gray-400">—</li>
				</ul>
			</section>

			<!-- The undo. Only ever offered for a step that was actually taken, and each one
			     says plainly what it costs — see position_survey.reopen_* on the server. -->
			<section v-if="canReopen" class="oak-section space-y-3">
				<div class="flex items-center gap-2">
					<Icon name="rotate-ccw" :size="16" class="text-orange-500" />
					<p class="oak-section-title">{{ labels.posReopenSend }}</p>
				</div>
				<textarea
					v-model.trim="reopenNote"
					rows="2"
					class="oak-input"
					:placeholder="labels.posReopenReason"
				/>
				<button
					v-if="tank.status === DONE && menu.has('surveyPos')"
					class="oak-btn oak-btn-secondary w-full py-2.5"
					:disabled="reopening"
					@click="doReopen('survey')"
				>
					<Icon name="corner-up-left" :size="16" /> {{ labels.posReopenSurvey }}
				</button>
				<p v-if="tank.status === DONE && menu.has('surveyPos')" class="text-xs text-gray-400">
					{{ labels.posReopenSurveyHint }}
				</p>
				<button
					class="oak-btn oak-btn-secondary w-full py-2.5"
					:disabled="reopening"
					@click="doReopen('lowering')"
				>
					<Icon name="corner-up-left" :size="16" /> {{ labels.posReopenLowering }}
				</button>
				<p class="text-xs text-gray-400">{{ labels.posReopenLoweringHint }}</p>
			</section>
		</template>
	</div>
</template>

<script setup>
import { computed, reactive, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import { labels } from "@/utils/labels"
import { toast } from "@/utils/toast"
import { confirm } from "@/utils/confirm"
import { menu } from "@/data/menu"
import Icon from "@/components/Icon.vue"
import SkeletonDetail from "@/components/SkeletonDetail.vue"
import { cachedResource } from "@/data/cache"
import { send } from "@/data/send"
import { openLightbox } from "@/utils/lightbox"
import {
	DONE,
	LOWERED,
	WAITING,
	chipClass,
	fmtDate,
	fmtDateTime,
	since,
	stamp,
	statusIcon,
	statusLabel,
} from "@/utils/surveyStatus"

const route = useRoute()
const router = useRouter()

const tank = ref(null)
const pending = ref(true)
const failed = ref(false)
const error = ref("")

const form = reactive({ location_note: "", lowering_note: "", notes: "" })

const res = cachedResource({
	url: "container_depot.ess.tank_survey.survey_tank_detail",
	method: "GET",
	onSuccess(data) {
		pending.value = false
		failed.value = false
		tank.value = data
		// Blank on purpose when the tank already has a location: this box means "the tank moved
		// to HERE", and pre-filling it with the old place invites a re-confirmation of a
		// position nobody re-checked.
		form.location_note = ""
		form.lowering_note = data.lowering_note || ""
		form.notes = data.survey_notes || ""
	},
	onError(err) {
		pending.value = false
		failed.value = true
		error.value = err?.messages?.[0] || err?.message || labels.error
	},
})

function load() {
	pending.value = true
	failed.value = false
	res.submit({ name: route.params.name })
}
watch(() => route.params.name, load, { immediate: true })

// ---- what this user may press ----
//
// Both gates are also enforced server-side (ess/tank_survey.py). These only keep the
// screen honest: a button that would answer 403 is worse than no button.
const canLower = computed(
	() => tank.value?.status === WAITING && (menu.has("posFix") || menu.has("surveyPos"))
)
const canFinish = computed(() => tank.value?.status === LOWERED && menu.has("surveyPos"))
const canReopen = computed(
	() => tank.value && [LOWERED, DONE].includes(tank.value.status) && (menu.has("posFix") || menu.has("surveyPos"))
)

const statusMessage = computed(() => {
	return (
		{
			[WAITING]: labels.tankDetailWaitingMsg,
			[LOWERED]: labels.tankDetailLoweredMsg,
			[DONE]: labels.tankDetailDoneMsg,
		}[tank.value?.status] || ""
	)
})
const statusCardClass = computed(() =>
	({
		[WAITING]: "border-amber-200 bg-amber-50",
		[LOWERED]: "border-leaf-200 bg-leaf-50",
		[DONE]: "border-brand-200 bg-brand-50",
	}[tank.value?.status] || "")
)
const statusTextClass = computed(() =>
	({
		[WAITING]: "text-amber-800",
		[LOWERED]: "text-leaf-700",
		[DONE]: "text-brand-700",
	}[tank.value?.status] || "text-gray-700")
)

// ---- step 1: tandai lowered ----
const lowering = ref(false)
const lowerError = ref("")

async function markLowered() {
	if (lowering.value || !tank.value) return
	// Optional — unless nobody has ever located this tank. A tank that has just been put down
	// by definition has a position to record, and "sudah turun" with no place leaves the
	// surveyor nowhere to walk.
	if (!tank.value.located && !form.location_note) {
		lowerError.value = labels.posLocationRequired
		return
	}
	if (!(await confirm({
		title: labels.posLoweredConfirmYes,
		message: labels.posLoweredConfirmMsg,
		confirmLabel: labels.posLoweredConfirmYes,
		cancelLabel: labels.confirmCancel,
	}))) return

	lowering.value = true
	lowerError.value = ""
	try {
		await send({
			url: "container_depot.ess.tank_survey.survey_lowered",
			payload: {
				name: tank.value.name,
				location_note: form.location_note || undefined,
				note: form.lowering_note || undefined,
			},
		})
		toast.success(labels.posLoweredDone, { title: tank.value.name })
		load()
	} catch (e) {
		lowerError.value = e?.message || labels.error
		toast.error(lowerError.value)
	} finally {
		lowering.value = false
	}
}

// ---- step 2: selesai survey ----
const finishing = ref(false)
const finishError = ref("")
async function finishSurvey() {
	if (finishing.value || !tank.value) return
	if (!(await confirm({
		title: labels.surveyFinishConfirmTitle,
		message: labels.surveyFinishEirHint,
		confirmLabel: labels.surveyFinishConfirmYes,
		cancelLabel: labels.confirmCancel,
	}))) return

	finishing.value = true
	finishError.value = ""
	const d = tank.value
	try {
		await send({
			url: "container_depot.ess.tank_survey.survey_finish",
			payload: {
				name: d.name,
				notes: form.notes || undefined,
			},
		})
		toast.success(labels.surveyFinishDone, { title: d.name })
		load()
	} catch (e) {
		finishError.value = e?.message || labels.error
		toast.error(finishError.value)
	} finally {
		finishing.value = false
	}
}

// ---- undo ----
const reopenNote = ref("")
const reopening = ref(false)

async function doReopen(which) {
	if (reopening.value || !tank.value) return
	const hint = which === "survey" ? labels.posReopenSurveyHint : labels.posReopenLoweringHint
	if (!(await confirm({
		title: labels.posReopenSend,
		message: hint,
		confirmLabel: labels.posReopenSend,
		cancelLabel: labels.confirmCancel,
	}))) return

	reopening.value = true
	try {
		await send({
			url:
				which === "survey"
					? "container_depot.ess.tank_survey.survey_reopen_survey"
					: "container_depot.ess.tank_survey.survey_reopen_lowering",
			payload: { name: tank.value.name, note: reopenNote.value || undefined },
		})
		toast.success(labels.posReopenDone, { title: tank.value.name })
		reopenNote.value = ""
		load()
	} catch (e) {
		toast.error(e?.message || labels.error)
	} finally {
		reopening.value = false
	}
}

function goBack() {
	if (window.history.length > 1) router.back()
	else router.push("/survey-orders")
}
</script>
