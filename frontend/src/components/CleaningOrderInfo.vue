<template>
	<!-- Judul = Reff Doc milik order ini sendiri (per dokumen — tidak mewarisi booking), atau
	     nomor ordernya. Nomor tank di meta: satu order = satu tank. -->
	<OrderInfo
		:title="o.reff_doc || o.name"
		:principal="o.container_principal"
		:meta="[
			o.container_no || o.container,
			o.depot,
			o.cleaning_type,
			o.service_count ? `${o.service_count} ${labels.cleaningServicesCount}` : '',
			o.last_cargo ? `ex ${o.last_cargo}` : '',
		]"
		:parties="[{ k: labels.mrPlanDate, v: o.plan_date && fmtDate(o.plan_date) }, { k: labels.svWorkedBy, v: o.assigned_to_name }]"
		:ids="[o.order_id !== o.name && o.order_id, o.reff_doc && o.name]"
	>
		<slot />
	</OrderInfo>
</template>

<script setup>
import { labels } from "@/utils/labels"
import { fmtDate } from "@/utils/surveyStatus"
import OrderInfo from "@/components/list/OrderInfo.vue"

defineProps({ o: { type: Object, required: true } })
</script>
