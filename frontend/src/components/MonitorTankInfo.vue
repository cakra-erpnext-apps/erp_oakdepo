<template>
	<!-- Satu tank — sama di baris Monitor dan di kepala detailnya. Daftar ini per TANK, bukan
	     per order: judulnya nomor tank, lalu di mana ia sekarang dan pekerjaan yang menahannya. -->
	<OrderInfo
		:title="c.container_no || labels.monitorNoNumber"
		:principal="c.principal"
		:meta="[
			[c.container_type, c.size].filter(Boolean).join(' '),
			c.depot,
			c.in_depot_days == null ? '' : fill(labels.monitorDays, { n: c.in_depot_days }),
		]"
		:parties="[
			{ k: labels.monitorLocationWord, v: c.location },
			{ k: labels.monitorWork, v: c.order ? `${c.order.kind} · ${c.order.name}` : '' },
			{ k: labels.monitorLast, v: c.last_activity ? [c.last_activity.summary || c.last_activity.type, since(c.last_activity.time), c.last_activity.by].filter(Boolean).join(' · ') : '' },
		]"
		:ids="[c.order_bongkar, c.serial_no]"
	>
		<slot />
	</OrderInfo>
</template>

<script setup>
import { labels } from "@/utils/labels"
import { fill } from "@/utils/listKit"
import { since } from "@/utils/surveyStatus"
import OrderInfo from "@/components/list/OrderInfo.vue"


defineProps({ c: { type: Object, required: true } })
</script>
