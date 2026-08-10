<template>
	<!-- Nothing queued and a working link: say nothing. A permanent "all good" indicator is
	     noise that teaches people to stop reading the header. -->
	<div v-if="visible" class="relative">
		<button
			type="button"
			class="oak-btn oak-btn-ghost h-9 gap-1.5 px-2.5 text-xs"
			:class="tone"
			@click="open = !open"
		>
			<Icon :name="icon" :size="16" />
			<span v-if="outbox.pending" class="font-bold">{{ outbox.pending }}</span>
			<span v-else-if="!outbox.online">{{ labels.queueOffline }}</span>
		</button>

		<div
			v-if="open"
			class="absolute right-0 z-30 mt-1 w-72 rounded-xl border border-gray-200 bg-white p-3 shadow-lg"
		>
			<p class="text-sm font-bold text-gray-900">{{ labels.queueTitle }}</p>
			<p v-if="outbox.sessionExpired" class="mt-1 text-xs font-semibold text-red-600">
				{{ labels.queueSessionExpired }}
			</p>
			<p v-else-if="!outbox.online" class="mt-1 text-xs text-gray-500">{{ labels.queueOffline }}</p>
			<p v-else-if="outbox.sending" class="mt-1 text-xs text-gray-500">{{ labels.queueSending }}</p>

			<ul v-if="outbox.rows.length" class="mt-2 space-y-2">
				<li v-for="row in outbox.rows" :key="row.id" class="rounded-lg bg-gray-50 p-2">
					<div class="flex items-center justify-between gap-2">
						<span class="truncate text-xs font-semibold text-gray-700">{{ row.kind }}</span>
						<span
							class="shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold"
							:class="row.state === 'failed' ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-700'"
						>
							{{ row.state === "failed" ? labels.queueFailedOne : labels.queuePhotoPending }}
						</span>
					</div>
					<p v-if="row.error" class="mt-1 break-words text-[11px] text-gray-500">{{ row.error }}</p>
					<!-- A failed row is the operator's call: nothing here throws work away on
					     its own, and nothing retries a doomed row for ever behind their back. -->
					<div v-if="row.state === 'failed'" class="mt-1.5 flex gap-2">
						<button class="oak-link text-[11px]" @click="retryRow(row.id)">{{ labels.queueRetry }}</button>
						<button class="text-[11px] text-red-600 underline-offset-2 hover:underline" @click="drop(row.id)">
							{{ labels.queueDiscard }}
						</button>
					</div>
				</li>
			</ul>
			<p v-else class="mt-2 text-xs text-gray-400">{{ labels.queueEmpty }}</p>
		</div>
	</div>
</template>

<script setup>
import { computed, ref } from "vue"

import { confirm } from "@/utils/confirm"
import { labels } from "@/utils/labels"
import { discardRow, outbox, retryRow } from "@/data/outbox"
import Icon from "@/components/Icon.vue"

const open = ref(false)

const visible = computed(() => outbox.pending > 0 || outbox.failed > 0 || !outbox.online)

const icon = computed(() => {
	if (outbox.failed) return "alert-triangle"
	if (!outbox.online) return "cloud-off"
	return "upload-cloud"
})

const tone = computed(() => {
	if (outbox.failed) return "text-red-600"
	if (!outbox.online) return "text-gray-500"
	return "text-amber-600"
})

async function drop(id) {
	// Discarding destroys work that was never sent anywhere, so it asks first.
	const ok = await confirm({
		title: labels.queueDiscard,
		message: labels.queueDiscardConfirm,
		confirmLabel: labels.queueDiscard,
		cancelLabel: labels.confirmCancel,
	})
	if (ok) discardRow(id)
}
</script>
