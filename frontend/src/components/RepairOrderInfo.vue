<template>
	<!-- Info satu M&R / Periodic Test — sama di kartu besar, baris ringkas, dan kepala detail.
	     Judulnya Reff Doc milik order ini sendiri (per dokumen, tidak mewarisi booking), kalau
	     kosong nomor order. -->
	<OrderInfo
		:title="o.reff_doc || o.name"
		:principal="o.principal"
		:meta="[o.depot, o.container_no || o.container, jobLabel, fill(labels.mrItemsN, { n: o.item_count || 0 })]"
		:parties="[{ k: labels.mrPlanDate, v: o.plan_date && fmtDate(o.plan_date) }, { k: labels.mrFlowApproved, v: o.decided_by_name }]"
		:ids="[o.reff_doc && o.name, o.repair_order_id, o.inspection]"
	>
		<slot />
	</OrderInfo>
</template>

<script setup>
import { computed } from "vue"
import { labels } from "@/utils/labels"
import { fmtDate } from "@/utils/surveyStatus"
import { fill } from "@/utils/listKit"
import OrderInfo from "@/components/list/OrderInfo.vue"

const props = defineProps({ o: { type: Object, required: true } })

// Uji berkala menyebut jenis ujinya (2,5Y / 5Y); perbaikan cukup "M&R".
const jobLabel = computed(() =>
	props.o.job_type === "Periodic Test"
		? props.o.pt_type ? `PT ${props.o.pt_type}` : labels.navPeriodic
		: labels.navMr
)
</script>
