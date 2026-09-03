<template>
	<HistoryPage
		:title="labels.surveyPosHistoryTitle"
		icon="map-pin"
		back-to="/survey-orders"
		:back-label="labels.surveyListTitle"
		list-url="container_depot.ess.tank_survey.survey_history"
		detail-url="container_depot.ess.tank_survey.survey_tank_detail"
		detail-param="name"
		:search-placeholder="labels.surveyPosSearch"
		:count-label="labels.surveyPosHistoryCount"
	>
		<template #row="{ item }">
			<span class="oak-icon-tile h-9 w-9 shrink-0 bg-brand-50 text-brand-600"><Icon name="map-pin" :size="16" /></span>
			<div class="min-w-0 flex-1">
				<div class="flex items-center justify-between gap-2">
					<p class="truncate font-semibold text-gray-900">{{ item.container_no || item.container }}</p>
					<span class="oak-chip shrink-0" :class="chipClass(item.status)">{{ statusLabel(item.status) }}</span>
				</div>
				<div class="mt-0.5 flex items-center justify-between gap-2 text-xs text-gray-500">
					<span class="truncate">{{ item.location_note || labels.tankPosUnlocated }}</span>
					<span class="shrink-0">{{ shortDate(item.surveyed_on || item.lowered_on || item.creation) }}</span>
				</div>
			</div>
		</template>

		<template #detail="{ data }">
			<section class="oak-card space-y-3 p-4">
				<div class="flex items-start justify-between gap-2">
					<div class="min-w-0">
						<p class="font-mono text-xs text-gray-400">{{ data.name }}</p>
						<h2 class="truncate text-lg font-extrabold text-gray-900">{{ data.container_no || data.container }}</h2>
					</div>
					<span class="oak-chip shrink-0" :class="chipClass(data.status)">{{ statusLabel(data.status) }}</span>
				</div>
				<dl class="grid grid-cols-2 gap-x-3 gap-y-2 text-sm">
					<div v-for="c in cells(data)" :key="c.label" class="min-w-0">
						<dt class="text-xs text-gray-400">{{ c.label }}</dt>
						<!-- Wraps rather than truncates: the timestamp cells below carry a date, a
						     clock time and an age, and a clipped one is worse than a two-line one. -->
						<dd class="break-words font-medium text-gray-800">{{ c.value || "—" }}</dd>
					</div>
				</dl>
			</section>

			<section class="oak-card space-y-2 p-4">
				<p class="oak-section-title">{{ labels.tankDetailLocation }}</p>
				<!-- The tank's CURRENT place, not where it was when this survey closed — the
				     location belongs to the tank (Container Position) and has gone on being
				     corrected since. Showing the frozen one would make Riwayat argue with every
				     other screen. -->
				<p class="whitespace-pre-line text-sm text-gray-800">
					{{ data.location_note || labels.tankPosUnlocated }}
				</p>
				<p v-if="data.location_updated_on" class="text-xs text-gray-400">
					{{ since(data.location_updated_on) }}
					<template v-if="data.location_updated_by"> · {{ data.location_updated_by }}</template>
				</p>
				<p v-if="data.lowering_note" class="text-xs text-leaf-600">
					<Icon name="arrow-down-circle" :size="11" /> {{ data.lowering_note }}
				</p>
				<p v-if="data.survey_notes" class="text-xs text-gray-500">{{ data.survey_notes }}</p>
			</section>

			<!-- BUKA LAGI — the undo this workflow has instead of a review step.
			     Two doors, and they do different amounts of damage: sending the tank back to
			     LOWERING says it was never really down (both steps are redone), while
			     reopening only the SURVEY keeps the lowering and the location note. Each is
			     shown only to the menu that owns it. A cancelled survey has nothing to
			     reopen. See position_survey.reopen_* for what each one clears. -->
			<section v-if="data.status === 'Survey Done' && reopenable.length" class="oak-card space-y-3 p-4">
				<p class="oak-section-title">{{ labels.posReopenNote }}</p>
				<textarea v-model.trim="reason" rows="2" class="oak-input" :placeholder="labels.posReopenReason"></textarea>
				<div class="space-y-2">
					<button
						v-for="a in reopenable"
						:key="a.url"
						type="button"
						class="oak-btn oak-btn-secondary w-full py-2.5"
						:disabled="busy"
						@click="reopen(a, data)"
					>
						<Icon v-if="!busy" name="rotate-ccw" :size="16" />
						<span class="min-w-0 text-left">
							<span class="block font-semibold">{{ a.label }}</span>
							<span class="block text-[11px] font-normal text-gray-500">{{ a.hint }}</span>
						</span>
					</button>
				</div>
			</section>
		</template>
	</HistoryPage>
</template>

<script setup>
import { computed, ref } from "vue"
import { useRouter } from "vue-router"
import { labels } from "@/utils/labels"
import { menu } from "@/data/menu"
import { send } from "@/data/send"
import { toast } from "@/utils/toast"
import Icon from "@/components/Icon.vue"
import HistoryPage from "@/components/HistoryPage.vue"
import { chipClass, fmtDate, since, stamp, statusLabel } from "@/utils/surveyStatus"

const shortDate = (v) => (v ? fmtDate(String(v).slice(0, 10)) : "—")

// Which undo this account may press. Riwayat is open to both menus (position_history), so
// the buttons — not the page — are what the permission decides.
const REOPEN_ACTIONS = [
	{
		key: "surveyPos",
		url: "container_depot.ess.tank_survey.survey_reopen_survey",
		label: labels.posReopenSurvey,
		hint: labels.posReopenSurveyHint,
		// Back to the tank, not to a list: reopening the survey leaves it Lowered, which is
		// a state the surveyor can act on immediately — and the tank screen is where they do.
		to: (d) => `/survey-orders/tank/${d.name}`,
	},
	{
		key: "posFix",
		url: "container_depot.ess.tank_survey.survey_reopen_lowering",
		label: labels.posReopenLowering,
		hint: labels.posReopenLoweringHint,
		// This one puts the tank back at the top of the lowering queue, which is where the
		// work now is — and it may not be this account's to do next.
		to: () => "/position-fix",
	},
]
const reopenable = computed(() => REOPEN_ACTIONS.filter((a) => menu.has(a.key)))
const router = useRouter()
const reason = ref("")
const busy = ref(false)

async function reopen(action, data) {
	if (busy.value) return
	busy.value = true
	try {
		await send({ url: action.url, payload: { name: data.name, note: reason.value || undefined } })
		toast.success(labels.posReopenDone, { title: data.name })
		reason.value = ""
		// The survey is open work again, so it no longer belongs in Riwayat — and the queue
		// it just landed in is where the operator is going next anyway. Each action carries
		// its own destination, and it is always a menu this account holds (that is the same
		// test that put the button on screen).
		router.push(action.to(data))
	} catch (e) {
		toast.error(e?.message || labels.error)
	} finally {
		busy.value = false
	}
}

function cells(d) {
	// Each actor next to the moment they acted — the pair is what settles "when did that
	// tank actually come down", which is the question this screen gets opened for.
	return [
		{ label: labels.depot, value: d.depot },
		{ label: labels.tankDetailEirOut, value: d.eir_out },
		{ label: labels.posLoweredBy, value: d.lowered_by },
		{ label: labels.posLoweredOn, value: d.lowered_on && stamp(d.lowered_on) },
		{ label: labels.surveyPosSurveyedBy, value: d.surveyed_by },
		{ label: labels.surveyPosSurveyedOn, value: d.surveyed_on && stamp(d.surveyed_on) },
	]
}
</script>
