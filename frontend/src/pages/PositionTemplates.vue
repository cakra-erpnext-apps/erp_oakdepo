<template>
	<div class="mx-auto w-full max-w-lg space-y-3 md:max-w-2xl">
		<div class="flex items-center gap-2">
			<button
				class="oak-press flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-gray-500"
				:aria-label="labels.backBtn"
				@click="goBack"
			>
				<Icon name="chevron-left" :size="22" />
			</button>
			<h1 class="min-w-0 flex-1 truncate text-lg font-extrabold tracking-tight text-gray-900">
				{{ labels.tplTitle }}
			</h1>
			<span v-if="depot" class="oak-chip shrink-0 bg-gray-100 font-mono text-gray-600">{{ depot }}</span>
		</div>

		<!-- Halaman ini adalah jalan masuk "dari luar" — dibuka dari papan Posisi Tank, saat
		     yang dikerjakan memang daftar pilihannya. Dari DALAM form, panel yang sama muncul
		     sebagai sheet supaya isian yang sudah diketik tidak hilang (PositionTemplateChips). -->
		<PositionTemplatePanel :depot="depot" />
	</div>
</template>

<script setup>
import { computed } from "vue"
import { useRoute, useRouter } from "vue-router"
import { labels } from "@/utils/labels"
import Icon from "@/components/Icon.vue"
import PositionTemplatePanel from "@/components/PositionTemplatePanel.vue"

const route = useRoute()
const router = useRouter()
const depot = computed(() => String(route.query.depot || ""))

function goBack() {
	if (window.history.length > 1) router.back()
	else router.push("/tank-position")
}
</script>
