<template>
	<!-- Info satu jadwal survey — sama persis di kartu "Dikerjakan" dan di baris ringkas.
	     Yang dicocokkan dengan kertas order (Reff Doc, Prinsipal, Shipper, EMKL) di atas dan
	     tebal; nomor sistem (Booking, Survey Order) paling bawah, kecil: dibaca hanya saat
	     mencocokkan ke Desk, bukan di yard. -->
	<span class="block min-w-0">
		<!-- Slot di kanan judul (chip status) — di baris judul saja, supaya baris-baris di
		     bawahnya dapat lebar penuh dan nomor panjang tidak terpotong. -->
		<span class="flex items-start justify-between gap-2">
			<span class="min-w-0 truncate font-mono text-sm font-extrabold text-gray-900">{{ o.reff_doc || o.booking || o.name }}</span>
			<slot />
		</span>
		<span class="block truncate text-xs">
			<span :class="o.principal ? 'font-semibold text-gray-700' : 'text-amber-600'">
				{{ o.principal || labels.svNoPrincipal }}
			</span>
			<span class="text-gray-500"><template v-for="m in meta" :key="m"> · {{ m }}</template></span>
		</span>
		<span v-for="x in parties" :key="x.k" class="block truncate text-xs">
			<span class="text-gray-400">{{ x.k }}</span> <span class="font-semibold text-gray-700">{{ x.v }}</span>
		</span>
		<span class="mt-0.5 block truncate text-[11px] tabular-nums text-gray-400">{{ ids }}</span>
	</span>
</template>

<script setup>
import { computed } from "vue"
import { labels } from "@/utils/labels"

const props = defineProps({ o: { type: Object, required: true } })

const meta = computed(() =>
	[props.o.depot, labels.svTankCount.replace("{n}", props.o.tank_count || 0)].filter(Boolean)
)
const parties = computed(() =>
	[
		{ k: labels.svSurveyor, v: props.o.surveyor },
		{ k: labels.shipper, v: props.o.shipper },
		{ k: labels.svEmkl, v: props.o.emkl },
	].filter((x) => x.v)
)
// Booking hanya kalau judulnya sudah Reff Doc — kalau tidak, booking itulah judulnya.
const ids = computed(() => [props.o.reff_doc && props.o.booking, props.o.name].filter(Boolean).join(" · "))
</script>
