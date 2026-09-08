<template>
	<!-- One line of the day's timeline. A router-link where the kind has a screen that owns
	     the document, a plain div where it does not — Container Booking has no PWA screen, and
	     a row that looks tappable and goes nowhere teaches the crew that half the calendar is
	     broken. -->
	<component
		:is="item.route ? 'router-link' : 'div'"
		v-bind="item.route ? { to: item.route } : {}"
		class="flex items-stretch gap-3 px-3 py-3 transition"
		:class="[item.route ? 'active:bg-gray-50' : '', item.done ? 'opacity-60' : '']"
	>
		<!-- The clock reading, where one exists. Nothing in the depot is planned to the hour
		     (every source carries a date and no time), so this is the moment work actually
		     STARTED — and a dash means "not started", not "unscheduled". -->
		<span class="w-11 shrink-0 pt-0.5 text-right text-xs font-bold tabular-nums text-gray-500">
			{{ item.time || labels.scheduleNoTime }}
		</span>
		<span class="w-1 shrink-0 rounded-full" :class="KIND[item.kind]?.bar || 'bg-gray-300'"></span>
		<div class="min-w-0 flex-1">
			<p class="flex items-baseline gap-2">
				<span class="shrink-0 text-[11px] font-bold" :class="KIND[item.kind]?.text">
					{{ kindLabel(item) }}
				</span>
				<span class="truncate text-sm font-bold text-gray-900">{{ item.title || item.name }}</span>
			</p>
			<p v-if="item.subtitle" class="truncate text-[11px] leading-relaxed text-gray-500">
				{{ item.subtitle }}
			</p>
			<!-- Only the overdue list turns this on: on its own day the date is the heading
			     above the list, and repeating it on every row would be noise. -->
			<p v-if="showDate && item.date" class="text-[11px] font-semibold text-amber-600">
				{{ fmtDateShort(item.date) }}
			</p>
			<p v-if="item.count" class="text-[11px] text-gray-400">
				{{ item.count_done }}/{{ item.count }} {{ labels.surveyOrderTankUnit }}
			</p>
		</div>
		<div class="flex shrink-0 items-start gap-1">
			<span class="oak-chip" :class="chip.tone">{{ chip.label }}</span>
			<Icon v-if="item.route" name="chevron-right" :size="15" class="mt-1 text-gray-300" />
		</div>
	</component>
</template>

<script setup>
import { computed } from "vue"
import Icon from "@/components/Icon.vue"
import { KIND, kindLabel, statusChip } from "@/utils/scheduleKind"
import { fmtDateShort } from "@/utils/surveyStatus"
import { labels } from "@/utils/labels"

const props = defineProps({
	item: { type: Object, required: true },
	// The overdue banner reuses this row and needs each line to say which day it slipped from.
	showDate: { type: Boolean, default: false },
})

const chip = computed(() => statusChip(props.item))
</script>
