<template>
	<!-- Judul = Reff Doc EIR ini kalau ada (yang tertulis di kertas), nomor tank kalau belum;
	     nomor tank tetap ikut di baris kedua. Nomor sistem (booking, bon, EIR) kecil di bawah. -->
	<OrderInfo
		:title="o.reff_doc || o.container_no || o.container"
		:principal="o.container_principal"
		:meta="[
			o.reff_doc ? o.container_no || o.container : '',
			o.inspection_type === 'EIR-Out' ? `EIR ${labels.eirBadgeOut}` : `EIR ${labels.eirBadgeIn}`,
			o.depot,
			o.tank_status,
		]"
		:parties="[
			{ k: labels.shipper, v: o.shipper },
			{ k: labels.svEmkl, v: o.emkl },
		]"
		:ids="[o.container_booking, o.referred_voucher, o.inspection_id || o.name]"
	>
		<slot />
	</OrderInfo>
</template>

<script setup>
import { labels } from "@/utils/labels"
import OrderInfo from "@/components/list/OrderInfo.vue"

defineProps({ o: { type: Object, required: true } })
</script>
