<template>
	<!-- Nomor tank = judulnya: yang dicari surveyor di yard adalah tanknya. -->
	<OrderInfo
		:title="o.container_no || o.container"
		:principal="o.principal"
		:meta="[o.depot, o.status === 'Completed' ? fill(labels.leakPhotoCount, { n: o.photo_count || 0 }) : '']"
		:parties="[
			{ k: labels.reffDoc, v: o.reff_doc },
			{ k: labels.shipper, v: o.shipper },
			{ k: labels.svEmkl, v: o.emkl },
		]"
		:ids="[o.booking, o.order_bongkar, o.name]"
	>
		<slot />
	</OrderInfo>
</template>

<script setup>
import { labels } from "@/utils/labels"
import { fill } from "@/utils/listKit"
import OrderInfo from "@/components/list/OrderInfo.vue"

defineProps({ o: { type: Object, required: true } })
</script>
