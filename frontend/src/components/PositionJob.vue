<template>
	<!-- Job yang membuat tank ini perlu dicari: prioritas, status baris survey-nya, dan nomor
	     job. Satu komponen karena empat daftar di papan Posisi Tank + layar satu tank
	     menampilkan hal yang sama. -->
	<span v-if="row.survey_order" class="block min-w-0">
		<span class="mt-1 flex flex-wrap items-center gap-1">
			<LiftOnBadge :survey="row.target_survey_on" :target="row.target_lift_on" :urgent="row.target_urgent_on" />
			<span v-if="row.survey_status" class="oak-chip shrink-0" :class="chipClass(row.survey_status)">
				{{ statusLabel(row.survey_status) }}
			</span>
		</span>
		<span class="mt-0.5 block truncate text-[11px] text-gray-500">{{ jobLine }}</span>
	</span>
</template>

<script setup>
import { computed } from "vue"
import { chipClass, statusLabel } from "@/utils/surveyStatus"
import LiftOnBadge from "@/components/LiftOnBadge.vue"

const props = defineProps({ row: { type: Object, required: true } })

const jobLine = computed(() => {
	const r = props.row
	return [r.survey_order, r.booking, r.reff_doc, r.customer]
		.filter(Boolean)
		.join(" · ")
})
</script>
