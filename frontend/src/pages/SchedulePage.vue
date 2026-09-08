<template>
	<div class="mx-auto w-full max-w-lg space-y-4 md:max-w-2xl">
		<div class="flex items-start justify-between gap-2">
			<div class="min-w-0">
				<h1 class="truncate text-xl font-extrabold tracking-tight text-gray-900">
					{{ labels.scheduleTitle }}
				</h1>
				<!-- Month AND week number: the depot plans in weeks ("minggu 37" is what a
				     shipping instruction says), and a calendar that only names the month leaves
				     the operator counting rows to find out which week they are looking at. -->
				<p class="truncate text-sm text-gray-500">{{ periodLabel }}</p>
			</div>
			<div class="flex shrink-0 gap-2">
				<button
					v-if="selected !== todayIso"
					class="oak-btn oak-btn-secondary px-3 py-2"
					@click="goToday"
				>
					<Icon name="calendar" :size="15" /> {{ labels.scheduleToday }}
				</button>
				<button class="oak-btn oak-btn-secondary px-3 py-2" :disabled="calRes.loading" @click="reload">
					<Icon name="refresh-cw" :size="16" />
				</button>
			</div>
		</div>

		<!-- =================== THE STRIP ===================
		     A week, not a month, by default: the yard works this week, and a 6×7 grid spends
		     most of its height on days nobody is going to tap. The month is one tap away for
		     the times somebody is planning ahead, and picking a day there drops straight back
		     to the week that day sits in.

		     Dots are per KIND, not one dot per day: "there is something on Thursday" is worth
		     much less than "Thursday is two washes and a truck", and at this size colour is
		     the only channel that can carry it. -->
		<section class="oak-section space-y-2 p-3">
			<div class="grid grid-cols-7 gap-1 text-center text-[11px] font-semibold text-gray-400">
				<span v-for="d in DOW" :key="d">{{ d }}</span>
			</div>

			<div v-if="!monthOpen" class="grid grid-cols-7 gap-1">
				<button
					v-for="cell in weekCells"
					:key="cell.date"
					class="oak-press flex flex-col items-center gap-1 rounded-xl py-1.5"
					:class="dayClass(cell)"
					@click="selected = cell.date"
				>
					<span class="text-sm font-bold">{{ cell.day }}</span>
					<span class="flex h-1.5 items-center gap-0.5">
						<!-- On the selected day the pill is brand orange, and a brand-coloured dot on
						     it is invisible — so the dots there go plain white and the kinds are read
						     off the chips underneath instead. -->
						<span
							v-for="(dot, i) in cell.dots"
							:key="i"
							class="h-1.5 w-1.5 rounded-full"
							:class="cell.date === selected ? 'bg-white/85' : dot"
						/>
					</span>
				</button>
			</div>

			<template v-else>
				<div class="grid grid-cols-7 gap-1">
					<span v-for="n in leadingBlanks" :key="`b${n}`" />
					<button
						v-for="cell in monthCells"
						:key="cell.date"
						class="oak-press flex flex-col items-center gap-1 rounded-xl py-1.5"
						:class="dayClass(cell)"
						@click="pickFromMonth(cell.date)"
					>
						<span class="text-sm font-semibold">{{ cell.day }}</span>
						<span class="flex h-1.5 items-center gap-0.5">
							<span
								v-for="(dot, i) in cell.dots"
								:key="i"
								class="h-1 w-1 rounded-full"
								:class="cell.date === selected ? 'bg-white/85' : dot"
							/>
						</span>
					</button>
				</div>
				<div class="flex items-center justify-between pt-1">
					<button class="oak-btn oak-btn-ghost px-2 py-1.5" @click="shiftMonth(-1)">
						<Icon name="chevron-left" :size="18" />
					</button>
					<p class="text-sm font-bold tracking-tight text-gray-900">{{ monthLabel }}</p>
					<button class="oak-btn oak-btn-ghost px-2 py-1.5" @click="shiftMonth(1)">
						<Icon name="chevron-right" :size="18" />
					</button>
				</div>
			</template>

			<button
				class="flex w-full items-center justify-center gap-1 pt-1 text-xs font-semibold text-gray-500"
				@click="monthOpen = !monthOpen"
			>
				<Icon :name="monthOpen ? 'chevron-up' : 'chevron-down'" :size="14" />
				{{ monthOpen ? labels.scheduleMonthClose : labels.scheduleMonthOpen }}
			</button>
		</section>

		<!-- =================== KIND FILTER ===================
		     Chips carry their COUNT for the selected day, and only kinds that actually have
		     something on it are offered — a "Perbaikan 0" chip is a tap that empties the
		     screen. Filtering happens here rather than on the server precisely so the counts
		     stay honest: asking the server for one kind would leave nothing to count the
		     others with. -->
		<section v-if="chips.length > 1" class="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1">
			<button
				v-for="c in chips"
				:key="c.kind || 'all'"
				type="button"
				class="oak-chip shrink-0 gap-1.5 px-3 py-1.5"
				:class="c.on ? c.toneOn : 'bg-gray-100 text-gray-600'"
				@click="c.kind ? toggle(c.kind) : active.clear()"
			>
				<span v-if="c.kind" class="h-1.5 w-1.5 rounded-full" :class="c.dot"></span>
				{{ c.label }}
				<span class="font-extrabold">{{ c.count }}</span>
			</button>
		</section>

		<!-- =================== THE DAY =================== -->
		<div class="flex items-end justify-between gap-2 px-1">
			<p class="min-w-0 truncate font-bold tracking-tight text-gray-900">{{ dayLabel }}</p>
			<p v-if="visible.length" class="shrink-0 text-xs text-gray-400">
				{{ visible.length }} {{ labels.scheduleCount }}
				<template v-if="doneCount"> · {{ doneCount }} {{ labels.scheduleDone }}</template>
			</p>
		</div>

		<!-- What the day view cannot say on its own: the truck that never came yesterday is
		     still not here, and nothing on today's list mentions it. Tapping opens the list
		     rather than navigating away — the operator is deciding whether to chase it, and
		     that decision is made against today's plan, not instead of it. -->
		<template v-if="overdueVisible.count">
			<button
				class="oak-card flex w-full items-center gap-2 border-amber-200 bg-amber-50 px-3 py-2.5 text-left"
				@click="overdueOpen = !overdueOpen"
			>
				<Icon name="alert-triangle" :size="16" class="shrink-0 text-amber-600" />
				<span class="min-w-0 flex-1 text-sm font-semibold text-amber-900">{{ overdueText }}</span>
				<Icon :name="overdueOpen ? 'chevron-up' : 'chevron-right'" :size="16" class="shrink-0 text-amber-600" />
			</button>
			<div v-if="overdueOpen" class="oak-card divide-y divide-gray-100 overflow-hidden">
				<ScheduleRow v-for="it in overdueVisible.items" :key="`o:${it.kind}:${it.name}`" :item="it" show-date />
				<p v-if="overdueVisible.hidden" class="px-3 py-2 text-center text-[11px] text-gray-400">
					{{ fill(labels.scheduleOverdueMore, { n: overdueVisible.hidden }) }}
				</p>
			</div>
		</template>

		<SkeletonList v-if="dayRes.loading && !items.length" :action="false" />
		<section v-else-if="dayFailed" class="oak-card space-y-3 p-6 text-center">
			<span class="oak-icon-tile mx-auto h-12 w-12 bg-red-50 text-red-500">
				<Icon name="cloud-off" :size="24" />
			</span>
			<p class="text-sm text-gray-600">{{ labels.scheduleError }}</p>
			<button class="oak-btn oak-btn-primary w-full" @click="reload">{{ labels.retry }}</button>
		</section>
		<p v-else-if="!visible.length" class="oak-card py-8 text-center text-sm text-gray-400">
			{{ labels.scheduleEmptyDay }}
		</p>
		<ul v-else class="oak-card divide-y divide-gray-100 overflow-hidden">
			<li v-for="it in visible" :key="`${it.kind}:${it.name}`">
				<ScheduleRow :item="it" />
			</li>
		</ul>
	</div>
</template>

<script setup>
import { computed, reactive, ref, watch } from "vue"
import { labels } from "@/utils/labels"
import Icon from "@/components/Icon.vue"
import SkeletonList from "@/components/SkeletonList.vue"
import ScheduleRow from "@/components/ScheduleRow.vue"
import { KIND, KIND_ORDER } from "@/utils/scheduleKind"
import { cachedResource } from "@/data/cache"

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
function parse(v) {
	const [y, m, d] = String(v).split("-").map(Number)
	return new Date(y, m - 1, d)
}
function fill(tpl, vars) {
	return Object.entries(vars).reduce((acc, [k, v]) => acc.replace(`{${k}}`, v), tpl)
}

const todayIso = iso(new Date())
const selected = ref(todayIso)
const anchor = ref(new Date()) // which month the grid is showing
const monthOpen = ref(false)
const overdueOpen = ref(false)
const active = reactive(new Set()) // empty = every kind this account may read

// --- the strip -------------------------------------------------------------------
const weekStart = computed(() => {
	const d = parse(selected.value)
	d.setDate(d.getDate() - ((d.getDay() + 6) % 7)) // Monday, because the depot's week does
	return d
})

/** ISO-8601 week number — the one every shipping instruction and plan sheet counts in. */
function isoWeek(d) {
	const t = new Date(d.getFullYear(), d.getMonth(), d.getDate())
	// Thursday of this week decides the year the week belongs to.
	t.setDate(t.getDate() + 3 - ((t.getDay() + 6) % 7))
	const first = new Date(t.getFullYear(), 0, 4)
	return 1 + Math.round(((t - first) / 86400000 - 3 + ((first.getDay() + 6) % 7)) / 7)
}

const periodLabel = computed(() => {
	const d = parse(selected.value)
	return `${MONTHS[d.getMonth()]} ${d.getFullYear()} · ${fill(labels.scheduleWeek, { n: isoWeek(d) })}`
})
const monthLabel = computed(() => `${MONTHS[anchor.value.getMonth()]} ${anchor.value.getFullYear()}`)
const DAY_NAMES = ["Minggu", "Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu"]
const dayLabel = computed(() => {
	const d = parse(selected.value)
	return `${DAY_NAMES[d.getDay()]}, ${d.getDate()} ${MONTHS[d.getMonth()]}`
})

/** Up to four dots for one day, one per kind that has something on it, in work order. */
function dotsFor(date) {
	const day = calendar.value[date]
	if (!day) return []
	return KIND_ORDER.filter(
		(k) => day.kinds?.[k] && (!active.size || active.has(k))
	).map((k) => KIND[k].dot)
}

const weekCells = computed(() =>
	Array.from({ length: 7 }, (_, i) => {
		const d = new Date(weekStart.value)
		d.setDate(d.getDate() + i)
		const date = iso(d)
		return { day: d.getDate(), date, dots: dotsFor(date) }
	})
)

const leadingBlanks = computed(() => {
	const first = new Date(anchor.value.getFullYear(), anchor.value.getMonth(), 1)
	return (first.getDay() + 6) % 7
})
const monthCells = computed(() => {
	const y = anchor.value.getFullYear()
	const m = anchor.value.getMonth()
	return Array.from({ length: new Date(y, m + 1, 0).getDate() }, (_, i) => {
		const date = iso(new Date(y, m, i + 1))
		return { day: i + 1, date, dots: dotsFor(date) }
	})
})

function dayClass(cell) {
	if (cell.date === selected.value) return "bg-brand-600 text-white"
	if (cell.date === todayIso) return "bg-brand-50 text-brand-700"
	return cell.dots.length ? "text-gray-900" : "text-gray-400"
}

function shiftMonth(delta) {
	const d = new Date(anchor.value)
	// Pinned to the 1st first: adding a month to the 31st lands two months on, so ▶ from
	// 31 January would skip February.
	d.setDate(1)
	d.setMonth(d.getMonth() + delta)
	anchor.value = d
}
function pickFromMonth(date) {
	selected.value = date
	// Collapse back to the week the picked day sits in: the month grid is for FINDING a day,
	// and once one is found the list underneath is what the operator came for.
	monthOpen.value = false
}
function goToday() {
	selected.value = todayIso
	anchor.value = new Date()
}

// --- filter ----------------------------------------------------------------------
function toggle(kind) {
	if (active.has(kind)) active.delete(kind)
	else active.add(kind)
}

const counts = computed(() => {
	const out = {}
	for (const it of items.value) out[it.kind] = (out[it.kind] || 0) + 1
	return out
})
const chips = computed(() => {
	const present = KIND_ORDER.filter((k) => counts.value[k])
	if (present.length < 2) return []
	return [
		{ kind: null, label: labels.scheduleFilterAll, count: items.value.length, on: !active.size, toneOn: "bg-brand-600 text-white" },
		...present.map((k) => ({
			kind: k,
			label: KIND[k].label,
			count: counts.value[k],
			dot: KIND[k].dot,
			on: active.has(k),
			toneOn: KIND[k].chip,
		})),
	]
})

const visible = computed(() =>
	active.size ? items.value.filter((it) => active.has(it.kind)) : items.value
)
const doneCount = computed(() => visible.value.filter((it) => it.done).length)

// --- overdue ---------------------------------------------------------------------
const overdueVisible = computed(() => {
	const o = overdue.value
	if (!o?.count) return { count: 0, items: [], hidden: 0 }
	// The filter applies here too, and the COUNT has to follow it: "3 belum selesai" over a
	// list showing one is the kind of small lie that makes a banner stop being read.
	if (!active.size) {
		return { count: o.count, items: o.items || [], hidden: o.count - (o.items || []).length }
	}
	const shown = (o.items || []).filter((it) => active.has(it.kind))
	const count = [...active].reduce((n, k) => n + (o.kinds?.[k] || 0), 0)
	return { count, items: shown, hidden: Math.max(0, count - shown.length) }
})

const overdueText = computed(() => {
	const o = overdueVisible.value
	const kindsIn = Object.keys(overdue.value?.kinds || {}).filter((k) => !active.size || active.has(k))
	// "dari kemarin" reads very differently from "dari 2 Sep" — and only one of them is
	// something the operator can picture without doing arithmetic.
	const since = overdue.value?.since
	const yesterday = iso(new Date(parse(selected.value).getTime() - 86400000))
	const when = since === yesterday ? labels.scheduleOverdueYesterday : fmtSince(since)
	if (kindsIn.length === 1) {
		return fill(labels.scheduleOverdueOne, { n: o.count, kind: KIND[kindsIn[0]].label.toLowerCase(), when })
	}
	return fill(labels.scheduleOverdueMixed, { n: o.count, when })
})
function fmtSince(v) {
	if (!v) return "—"
	const d = parse(v)
	return `${d.getDate()} ${MONTHS[d.getMonth()].slice(0, 3)}`
}

// --- data ------------------------------------------------------------------------
// Neither call is filtered server-side any more: one unfiltered answer per day feeds the
// list, the chip counts AND the dots, where a filtered one could only feed the first.
const calendar = ref({})
const calRes = cachedResource({
	url: "container_depot.ess.schedule.schedule_calendar",
	method: "GET",
	makeParams: () => ({ month: iso(new Date(anchor.value.getFullYear(), anchor.value.getMonth(), 1)) }),
	auto: true,
	onSuccess(data) {
		calendar.value = data?.days || {}
	},
})

const items = ref([])
const overdue = ref(null)
const dayFailed = ref(false)
const dayRes = cachedResource({
	url: "container_depot.ess.schedule.schedule_day",
	method: "GET",
	makeParams: () => ({ date: selected.value }),
	auto: true,
	onSuccess(data) {
		dayFailed.value = false
		items.value = data?.items || []
		overdue.value = data?.overdue || null
		overdueOpen.value = false
	},
	onError() {
		dayFailed.value = true
	},
})

// The week strip can walk into a month the dots were never fetched for; follow it, so a day
// in next month is not silently drawn as empty.
watch(selected, (v) => {
	const d = parse(v)
	if (d.getMonth() !== anchor.value.getMonth() || d.getFullYear() !== anchor.value.getFullYear()) {
		anchor.value = d
	}
	dayRes.reload()
})
watch(anchor, () => calRes.reload())
// A kind that had rows yesterday may have none today, and leaving it selected would show an
// empty day that is not actually empty.
watch(items, () => {
	for (const k of [...active]) if (!counts.value[k]) active.delete(k)
})

function reload() {
	calRes.reload()
	dayRes.reload()
}
</script>
