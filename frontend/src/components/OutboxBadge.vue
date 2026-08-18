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
						<span class="truncate text-xs font-semibold text-gray-700">{{ row.title || row.kind }}</span>
						<span class="shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold" :class="chipTone(row)">
							{{ chipText(row) }}
						</span>
					</div>
					<!-- A settled row is not a breakage, so it gets the explanation instead of a
					     raw exception: the job was finished on the Desk while this handset was
					     out of signal, and no retry will change that. -->
					<template v-if="row.settled">
						<p class="mt-1 text-[11px] font-semibold text-gray-700">{{ labels.queueSettledTitle }}</p>
						<p class="mt-0.5 break-words text-[11px] text-gray-500">{{ labels.queueSettledHint }}</p>
					</template>
					<p v-else-if="row.error" class="mt-1 break-words text-[11px] text-gray-500">{{ row.error }}</p>

					<!-- A failed row is the operator's call: nothing here throws work away on
					     its own, and nothing retries a doomed row for ever behind their back. -->
					<div v-if="row.state === 'failed'" class="mt-1.5 flex gap-2">
						<!-- No retry on a settled row — the server will refuse it identically
						     for ever, and offering the button implies otherwise. -->
						<button v-if="!row.settled" class="oak-link text-[11px]" @click="retryRow(row.id)">
							{{ labels.queueRetry }}
						</button>
						<button class="oak-link text-[11px]" @click="toggle(row.id)">
							{{ expanded.has(row.id) ? labels.queueHidePayload : labels.queueShowPayload }}
						</button>
						<button class="text-[11px] text-red-600 underline-offset-2 hover:underline" @click="drop(row)">
							{{ labels.queueDiscard }}
						</button>
					</div>

					<!-- What the row is actually carrying. Discarding is permanent, so the
					     operator has to be able to READ the thing they are being asked to throw
					     away — and copy anything the Desk is missing into ERPNext by hand. -->
					<dl v-if="expanded.has(row.id)" class="mt-1.5 space-y-1 rounded-lg bg-white p-2">
						<div v-for="(line, i) in payloadLines(row)" :key="i" class="flex gap-1.5 text-[11px]">
							<dt class="shrink-0 font-semibold text-gray-500">{{ line.key }}</dt>
							<dd class="min-w-0 break-words text-gray-700">{{ line.value }}</dd>
						</div>
					</dl>
				</li>
			</ul>
			<p v-else class="mt-2 text-xs text-gray-400">{{ labels.queueEmpty }}</p>
		</div>
	</div>
</template>

<script setup>
import { computed, reactive, ref } from "vue"

import { confirm } from "@/utils/confirm"
import { labels } from "@/utils/labels"
import { discardRow, outbox, retryRow } from "@/data/outbox"
import Icon from "@/components/Icon.vue"

const open = ref(false)
// Rows whose contents the operator has opened. Collapsed by default: the panel is a header
// dropdown, and a queue of expanded EIRs would bury the actions under it.
const expanded = reactive(new Set())

const visible = computed(() => outbox.pending > 0 || outbox.failed > 0 || !outbox.online)

// A settled row needs to be SEEN, but it is not a breakage — nothing is broken, somebody
// else simply did the job first. Red is reserved for rows that genuinely did not go through.
const broken = computed(() => outbox.failed - outbox.settled)

const icon = computed(() => {
	if (broken.value) return "alert-triangle"
	if (outbox.settled) return "info"
	if (!outbox.online) return "cloud-off"
	return "upload-cloud"
})

const tone = computed(() => {
	if (broken.value) return "text-red-600"
	if (outbox.settled) return "text-gray-600"
	if (!outbox.online) return "text-gray-500"
	return "text-amber-600"
})

const chipText = (row) => {
	if (row.settled) return labels.queueSettledOne
	return row.state === "failed" ? labels.queueFailedOne : labels.queuePhotoPending
}

const chipTone = (row) => {
	if (row.settled) return "bg-gray-200 text-gray-700"
	return row.state === "failed" ? "bg-red-100 text-red-700" : "bg-amber-100 text-amber-700"
}

const toggle = (id) => (expanded.has(id) ? expanded.delete(id) : expanded.add(id))

/**
 * The row's payload, flattened into lines somebody can read off a phone and re-enter on the
 * Desk.
 *
 * Deliberately generic rather than per-`kind`: this is the last view of work that is about
 * to be thrown away, and a formatter that only knows about the four screens someone
 * remembered would silently hide the fifth. Photos become a count — the file itself cannot
 * be re-typed, and printing `local:8f3c…` helps nobody.
 */
function payloadLines(row) {
	const lines = []
	for (const [key, value] of Object.entries(row.payload || {})) {
		if (value === null || value === undefined || value === "") continue
		const text = describe(value)
		if (text) lines.push({ key, value: text })
	}
	return lines
}

function describe(value) {
	if (Array.isArray(value)) {
		if (!value.length) return ""
		const photos = value.filter(isPhoto).length
		if (photos === value.length) return `${photos} ${labels.queuePayloadPhotos}`
		return value.map(describe).filter(Boolean).join(" | ")
	}
	if (value && typeof value === "object") {
		// One finding, one line: "PANEL · DENT · penyok 10cm".
		return Object.entries(value)
			.filter(([k, v]) => v !== null && v !== undefined && v !== "" && !isPhoto(v) && k !== "photos")
			.map(([, v]) => describe(v))
			.filter(Boolean)
			.join(" · ")
	}
	if (isPhoto(value)) return `1 ${labels.queuePayloadPhotos}`
	return String(value)
}

// Both a stashed photo (`local:…`) and one already uploaded (`/files/…`) — either way it is
// a file, not something a human re-enters.
const isPhoto = (v) => typeof v === "string" && (v.startsWith("local:") || v.startsWith("/files/"))

async function drop(row) {
	// Discarding destroys work that was never sent anywhere, so it asks first — and says the
	// right thing for each case: a settled row's work IS recorded (by somebody else), an
	// ordinary failed row's is not recorded anywhere at all.
	const ok = await confirm({
		title: labels.queueDiscard,
		message: row.settled ? labels.queueSettledDiscardConfirm : labels.queueDiscardConfirm,
		confirmLabel: labels.queueDiscard,
		cancelLabel: labels.confirmCancel,
	})
	if (ok) {
		expanded.delete(row.id)
		discardRow(row.id)
	}
}
</script>
