<template>
	<div class="mx-auto w-full max-w-lg space-y-4 md:max-w-2xl">
		<!-- Header — same shape as every other worklist page. -->
		<div class="flex items-center justify-between">
			<div class="min-w-0">
				<h1 class="truncate text-xl font-extrabold tracking-tight text-gray-900">
					{{ labels.posFixTitle }}
				</h1>
				<p class="text-sm text-gray-500">{{ labels.posFixHint }}</p>
			</div>
			<div class="flex shrink-0 items-center gap-2">
				<router-link to="/survey-orders/history" class="oak-btn oak-btn-secondary px-3 py-2">
					<Icon name="clock" :size="16" /> {{ labels.navHistory }}
				</router-link>
			</div>
		</div>

		<!-- =================== THE LOWERING QUEUE ===================
		     A flat list, not a calendar. The surveyor plans a day; the Kalmar operator works
		     a queue — "what do I bring down next" — and the answer is whatever the truck is
		     coming for soonest, which is exactly the order the server sends (worklist.
		     sort_by_priority). So there are no tabs here and nothing to filter: one list,
		     already in the right order. -->
		<section class="oak-section space-y-3">
			<div class="flex items-center justify-between">
				<div class="flex items-center gap-2">
					<Icon name="arrow-down-circle" :size="16" class="text-amber-500" />
					<p class="oak-section-title">{{ labels.posFixList }}</p>
				</div>
				<span v-if="total" class="oak-chip bg-amber-100 text-amber-800">{{ total }}</span>
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
			<p v-else-if="!items.length" class="py-6 text-center text-sm text-gray-400">
				{{ labels.posFixEmpty }}
			</p>
			<ul v-else class="divide-y divide-gray-100">
				<li v-for="r in items" :key="r.name">
					<router-link :to="`/survey-orders/tank/${r.name}`" class="oak-press flex h-[60px] items-center gap-3">
						<span class="oak-icon-tile h-9 w-9 shrink-0 bg-amber-50 text-amber-600">
							<Icon name="arrow-down-circle" :size="16" />
						</span>
						<div class="min-w-0 flex-1">
							<p class="truncate font-semibold text-gray-900">{{ r.container_no || r.container }}</p>
							<!-- One subtitle line, ordered by urgency so truncation eats the least
							     important half: sent back for a redo, the lift-on countdown, then
							     the day it is scheduled for. -->
							<p class="flex items-center gap-1.5 text-[11px]">
								<span v-if="r.reopen_note" class="oak-chip shrink-0 bg-orange-100 text-orange-800">
									<Icon name="rotate-ccw" :size="11" /> {{ labels.posReopenNote }}
								</span>
								<span v-if="r.target_lift_on" class="shrink-0 font-semibold" :class="liftClass(r.target_lift_on)">
									Lift-on {{ hMinus(r.target_lift_on) }}
								</span>
								<!-- Where to walk, and how stale that answer is. The operator picking
								     the next tank needs both — see utils/surveyStatus.since(). -->
								<span class="truncate" :class="r.located ? 'text-gray-500' : 'text-red-500'">
									{{ r.located ? r.location_note : labels.tankPosUnlocated }}
								</span>
								<span v-if="r.located" class="shrink-0" :class="r.fresh ? 'text-gray-400' : 'text-amber-600 font-semibold'">
									{{ since(r.location_updated_on) }}
								</span>
							</p>
						</div>
						<Icon name="chevron-right" :size="16" class="shrink-0 text-gray-300" />
					</router-link>
				</li>
			</ul>
			<p v-if="items.length" class="text-center text-xs text-gray-400">
				{{ total }} {{ labels.posFixCount }}
			</p>
		</section>
	</div>
</template>

<script setup>
import { onMounted, ref } from "vue"
import { useRoute, useRouter } from "vue-router"
import { labels } from "@/utils/labels"
import { hMinus, liftClass } from "@/utils/liftOn"
import { since } from "@/utils/surveyStatus"
import Icon from "@/components/Icon.vue"
import SkeletonList from "@/components/SkeletonList.vue"
import { cachedResource } from "@/data/cache"

const route = useRoute()
const router = useRouter()

const items = ref([])
const total = ref(0)
const search = ref("")

const listRes = cachedResource({
	url: "container_depot.ess.tank_survey.survey_waiting",
	method: "GET",
	makeParams: () => ({ search: search.value || "", page_length: 50 }),
	auto: true,
	onSuccess(data) {
		items.value = data.items || []
		total.value = data.total || 0
	},
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

// Deep link from the bell: `/position-fix?s=CPS-0001` goes straight to that tank
// (ess/notification_routes._survey). Redirected rather than opened in place — the tank
// screen is one page now, shared by both teams, so there is nothing here to open into.
onMounted(() => {
	const s = route.query.s
	if (s) router.replace(`/survey-orders/tank/${String(s)}`)
})
</script>
