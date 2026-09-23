<template>
	<!-- Info satu order — sama persis di kartu besar, di baris ringkas, dan di kepala detail.
	     Yang dicocokkan dengan kertas (Reff Doc, Prinsipal, Shipper, EMKL) di atas dan tebal;
	     nomor sistem paling bawah, kecil: dibaca hanya saat mencocokkan ke Desk. -->
	<span class="block min-w-0">
		<!-- Slot di kanan judul (chip status) — di baris judul saja, supaya baris-baris di
		     bawahnya dapat lebar penuh dan nomor panjang tidak terpotong. -->
		<span class="flex items-start justify-between gap-2">
			<span class="min-w-0 truncate font-mono text-sm font-extrabold text-gray-900">{{ title }}</span>
			<slot />
		</span>
		<span class="block truncate text-xs">
			<span :class="principal ? 'font-semibold text-gray-700' : 'text-amber-600'">
				{{ principal || labels.svNoPrincipal }}
			</span>
			<span class="text-gray-500"><template v-for="m in meta.filter(Boolean)" :key="m"> · {{ m }}</template></span>
		</span>
		<span v-for="x in parties.filter((p) => p.v)" :key="x.k" class="block truncate text-xs">
			<span class="text-gray-400">{{ x.k }}</span> <span class="font-semibold text-gray-700">{{ x.v }}</span>
		</span>
		<span v-if="ids.filter(Boolean).length" class="mt-0.5 block truncate text-[11px] tabular-nums text-gray-400">
			{{ ids.filter(Boolean).join(" · ") }}
		</span>
	</span>
</template>

<script setup>
import { labels } from "@/utils/labels"

defineProps({
	title: { type: String, required: true },
	principal: { type: String, default: "" },
	meta: { type: Array, default: () => [] }, // teks setelah prinsipal
	parties: { type: Array, default: () => [] }, // [{ k, v }]
	ids: { type: Array, default: () => [] }, // nomor sistem
})
</script>
