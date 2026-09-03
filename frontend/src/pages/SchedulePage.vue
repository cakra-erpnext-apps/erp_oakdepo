<template>
	<div class="mx-auto w-full max-w-lg space-y-4 md:max-w-2xl">
		<div class="flex items-center justify-between">
			<div class="min-w-0">
				<h1 class="truncate text-xl font-extrabold tracking-tight text-gray-900">
					{{ labels.scheduleTitle }}
				</h1>
				<p class="text-sm text-gray-500">{{ labels.scheduleHint }}</p>
			</div>
			<button class="oak-btn oak-btn-secondary shrink-0 px-3 py-2" :disabled="calRes.loading" @click="reload">
				<Icon name="refresh-cw" :size="16" />
			</button>
		</div>

		<!-- =================== KIND FILTER ===================
		     Built from what the SERVER says this account can read, never from a fixed list:
		     offering Team Cleaning a "Perbaikan" chip that can only ever return nothing is a
		     worse lie than not offering it. One source and the row collapses to nothing worth
		     tapping, so it is hidden entirely. -->
		<section v-if="sources.length > 1" class="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1">
			<button
				type="button"
				class="oak-chip shrink-0 px-3 py-1.5"
				:class="!active.size ? 'bg-brand-600 text-white' : 'bg-gray-100 text-gray-600'"
				@click="active.clear()"
			>
				{{ labels.scheduleFilterAll }}
			</button>
			<button
				v-for="s in sources"
				:key="s.kind"
				type="button"
				class="oak-chip shrink-0 gap-1 px-3 py-1.5"
				:class="active.has(s.kind) ? KIND[s.kind].chipOn : 'bg-gray-100 text-gray-600'"
				@click="toggle(s.kind)"
			>
				<Icon :name="KIND[s.kind].icon" :size="12" />
				{{ KIND[s.kind].label }}
			</button>
		</section>

		<!-- =================== CALENDAR ===================
		     The dot answers "which days have work", which is the only question a month grid can
		     usefully answer at 40px. Amber while anything on the day is still open, green once
		     the whole day is done — the split is about whether somebody still has to go out,
		     not about how much there is. -->
		<section class="oak-section space-y-3">
			<div class="flex items-center justify-between">
				<button class="oak-btn oak-btn-ghost px-2 py-1.5" @click="shiftMonth(-1)">
					<Icon name="chevron-left" :size="18" />
				</button>
				<p class="font-bold tracking-tight text-gray-900">{{ monthLabel }}</p>
				<button class="oak-btn oak-btn-ghost px-2 py-1.5" @click="shiftMonth(1)">
					<Icon name="chevron-right" :size="18" />
				</button>
			</div>

			<div class="grid grid-cols-7 gap-1 text-center text-[11px] font-semibold text-gray-400">
				<span v-for="d in DOW" :key="d">{{ d }}</span>
			</div>
			<div class="grid grid-cols-7 gap-1">
				<span v-for="n in leadingBlanks" :key="`b${n}`" />
				<button
					v-for="cell in cells"
					:key="cell.date"
					class="oak-press relative flex h-10 flex-col items-center justify-center rounded-lg text-sm"
					:class="dayClass(cell)"
					@click="selected = cell.date"
				>
					{{ cell.day }}
					<span
						v-if="cell.stats"
						class="absolute bottom-1 h-1 w-1 rounded-full"
						:class="cell.stats.open ? 'bg-amber-500' : 'bg-leaf-500'"
					/>
				</button>
			</div>

			<button v-if="selected !== todayIso" class="oak-btn oak-btn-secondary w-full py-2" @click="selected = todayIso">
				<Icon name="calendar" :size="15" /> {{ labels.scheduleToday }}
			</button>
		</section>

		<!-- =================== THE SELECTED DAY ===================
		     Four kinds of document, one card shape — the normalising happens on the server
		     (schedule._card) so the four never drift into four layouts. -->
		<section class="oak-section space-y-3">
			<div class="flex items-center justify-between gap-2">
				<div class="flex min-w-0 items-center gap-2">
					<Icon name="calendar" :size="16" class="text-brand-500" />
					<p class="oak-section-title truncate">{{ fmtDate(selected) }}</p>
				</div>
				<span v-if="items.length" class="oak-chip bg-brand-50 text-brand-700">
					{{ items.length }} {{ labels.scheduleCount }}
				</span>
			</div>

			<SkeletonList v-if="dayRes.loading && !items.length" :action="false" />
			<section v-else-if="dayFailed" class="oak-card space-y-3 p-6 text-center">
				<span class="oak-icon-tile mx-auto h-12 w-12 bg-red-50 text-red-500">
					<Icon name="cloud-off" :size="24" />
				</span>
				<p class="text-sm text-gray-600">{{ labels.scheduleError }}</p>
				<button class="oak-btn oak-btn-primary w-full" @click="reload">{{ labels.retry }}</button>
			</section>
			<p v-else-if="!items.length" class="py-6 text-center text-sm text-gray-400">
				{{ labels.scheduleEmptyDay }}
			</p>

			<ul v-else class="space-y-2">
				<li v-for="it in items" :key="`${it.kind}:${it.name}`">
					<!-- A booking has no screen of its own in the PWA, so its card is a plain
					     div with no chevron. Rendering it as a link that goes nowhere would
					     teach the crew that half the calendar is broken. -->
					<component
						:is="it.route ? 'router-link' : 'div'"
						v-bind="it.route ? { to: it.route } : {}"
						class="oak-card flex items-center gap-3 p-3"
						:class="[it.route ? 'oak-press' : '', it.done ? 'opacity-60' : '']"
					>
						<span class="oak-icon-tile h-10 w-10 shrink-0" :class="KIND[it.kind].tile">
							<Icon :name="KIND[it.kind].icon" :size="18" />
						</span>
						<div class="min-w-0 flex-1 space-y-0.5">
							<div class="flex items-center gap-1.5">
								<span class="oak-chip shrink-0 px-1.5 py-0 text-[10px]" :class="KIND[it.kind].chipOn">
									{{ KIND[it.kind].label }}
								</span>
								<p class="truncate font-bold text-gray-900">{{ it.title || it.name }}</p>
							</div>
							<p v-if="it.subtitle" class="truncate text-[11px] text-gray-500">{{ it.subtitle }}</p>
							<p class="truncate text-[11px] text-gray-400">
								<span v-if="it.meta">{{ it.meta }} · </span>{{ it.status }}
							</p>
						</div>
						<div class="shrink-0 space-y-0.5 text-right">
							<p v-if="it.count" class="text-sm font-extrabold text-gray-900">
								{{ it.count }} {{ labels.surveyOrderTankUnit }}
							</p>
							<p v-if="it.count && it.count_done < it.count" class="text-[11px] font-semibold text-amber-600">
								{{ it.count - it.count_done }} {{ labels.scheduleOpen }}
							</p>
							<p v-if="!it.route" class="text-[10px] text-gray-300">{{ labels.scheduleInfoOnly }}</p>
						</div>
						<Icon v-if="it.route" name="chevron-right" :size="16" class="shrink-0 text-gray-300" />
					</component>
				</li>
			</ul>
		</section>
	</div>
</template>

<script setup>
import { computed, reactive, ref, watch } from "vue"
import { labels } from "@/utils/labels"
import Icon from "@/components/Icon.vue"
import SkeletonList from "@/components/SkeletonList.vue"
import { cachedResource } from "@/data/cache"

// Presentation for the four kinds the server may return. Keyed by the SERVER's kind string
// (container_depot.schedule.SOURCES) so a kind added there needs exactly one entry here.
const KIND = {
	survey: { label: labels.kindSurvey, icon: "clipboard", tile: "bg-amber-50 text-amber-600", chipOn: "bg-amber-100 text-amber-800" },
	cleaning: { label: labels.kindCleaning, icon: "droplet", tile: "bg-brand-50 text-brand-600", chipOn: "bg-brand-100 text-brand-700" },
	repair: { label: labels.kindRepair, icon: "tool", tile: "bg-leaf-50 text-leaf-600", chipOn: "bg-leaf-100 text-leaf-700" },
	booking: { label: labels.kindBooking, icon: "truck", tile: "bg-gray-100 text-gray-500", chipOn: "bg-gray-200 text-gray-700" },
}

const DOW = ["Sn", "Sl", "Rb", "Km", "Jm", "Sb", "Mg"]
const MONTHS = [
	"Januari", "Februari", "Maret", "April", "Mei", "Juni",
	"Juli", "Agustus", "September", "Oktober", "November", "Desember",
]

/** `YYYY-MM-DD` for a Date, in LOCAL time — never `toISOString`, which converts to UTC first
 *  and so turns every WIB morning before 07:00 into yesterday. */
function iso(d) {
	const p = (n) => String(n).padStart(2, "0")
	return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}
const todayIso = iso(new Date())

const anchor = ref(new Date())
const selected = ref(todayIso)
const active = reactive(new Set()) // empty = every kind this account may read

const monthLabel = computed(() => `${MONTHS[anchor.value.getMonth()]} ${anchor.value.getFullYear()}`)
const leadingBlanks = computed(() => {
	const first = new Date(anchor.value.getFullYear(), anchor.value.getMonth(), 1)
	return (first.getDay() + 6) % 7 // Monday = 0, because the depot's week starts on Monday
})

const cells = computed(() => {
	const y = anchor.value.getFullYear()
	const m = anchor.value.getMonth()
	const out = []
	for (let day = 1; day <= new Date(y, m + 1, 0).getDate(); day++) {
		const date = iso(new Date(y, m, day))
		out.push({ day, date, stats: calendar.value[date] || null })
	}
	return out
})

function dayClass(cell) {
	if (cell.date === selected.value) return "bg-brand-600 font-bold text-white"
	if (cell.date === todayIso) return "bg-brand-50 font-bold text-brand-700"
	return cell.stats ? "font-semibold text-gray-900" : "text-gray-400"
}

function shiftMonth(delta) {
	const d = new Date(anchor.value)
	// Pinned to the 1st first: adding a month to the 31st lands two months on, so ▶ from
	// 31 January would skip February.
	d.setDate(1)
	d.setMonth(d.getMonth() + delta)
	anchor.value = d
}

function fmtDate(v) {
	if (!v) return "—"
	const [y, m, d] = String(v).split("-").map(Number)
	return y ? `${d} ${MONTHS[m - 1]} ${y}` : String(v)
}

function toggle(kind) {
	if (active.has(kind)) active.delete(kind)
	else active.add(kind)
}

// Sent as a comma list, or omitted entirely when nothing is selected. Omitting rather than
// listing everything matters: the server then answers with what the ACCOUNT may read, which
// is also how `sources` gets populated in the first place.
const kindsParam = computed(() => (active.size ? [...active].join(",") : undefined))

// ---- month counts (the dots) ----
const calendar = ref({})
const sources = ref([])
const calRes = cachedResource({
	url: "container_depot.ess.schedule.schedule_calendar",
	method: "GET",
	makeParams: () => ({
		month: iso(new Date(anchor.value.getFullYear(), anchor.value.getMonth(), 1)),
		kinds: kindsParam.value,
	}),
	auto: true,
	onSuccess(data) {
		calendar.value = data?.days || {}
		// Only ever grows the chip row from an UNFILTERED answer: asking for one kind returns
		// one source, and letting that overwrite the list would delete the other chips the
		// moment one was tapped — leaving no way back.
		if (!active.size) sources.value = data?.sources || []
	},
})

// ---- the selected day ----
const items = ref([])
const dayFailed = ref(false)
const dayRes = cachedResource({
	url: "container_depot.ess.schedule.schedule_day",
	method: "GET",
	makeParams: () => ({ date: selected.value, kinds: kindsParam.value }),
	auto: true,
	onSuccess(data) {
		dayFailed.value = false
		items.value = data?.items || []
	},
	onError() {
		dayFailed.value = true
	},
})

// Three watches, kept apart on purpose: moving between days inside a month must not re-fetch
// a month of counts that has not changed, and changing the filter has to reload both.
watch(anchor, () => calRes.reload())
watch(selected, () => dayRes.reload())
watch(
	() => kindsParam.value,
	() => {
		calRes.reload()
		dayRes.reload()
	}
)

function reload() {
	calRes.reload()
	dayRes.reload()
}
</script>
