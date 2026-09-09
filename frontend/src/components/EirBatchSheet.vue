<template>
	<teleport to="body">
		<div
			v-if="open"
			class="fixed inset-0 z-40 animate-fade-in bg-gray-900/40 backdrop-blur-[1px]"
			@click="close"
		></div>
		<section
			v-if="open"
			class="fixed inset-x-0 bottom-0 z-50 max-h-[86vh] animate-slide-up overflow-y-auto rounded-t-3xl bg-paper pb-safe-bottom shadow-soft"
			role="dialog"
			aria-modal="true"
		>
			<button class="w-full pb-1 pt-2.5" :aria-label="labels.moreClose" @click="close">
				<span class="mx-auto block h-1 w-10 rounded-full bg-gray-300"></span>
			</button>

			<div class="space-y-4 px-4 pb-5 pt-1">
				<div>
					<p class="text-base font-extrabold leading-tight text-gray-900">
						{{ labels.eirBatchTitle }} <span v-if="voucher" class="font-mono">{{ voucher }}</span>
					</p>
					<p class="mt-0.5 text-xs text-gray-500">{{ countLine }}</p>
				</div>

				<!-- Satu baris per EIR, bernomor seperti urutan kerjanya. Baris yang sedang
				     dibuka diberi pita oranye di tepi kiri: sheet ini dibuka justru untuk
				     menjawab "saya sedang di mana", jadi jawabannya harus terlihat sebelum
				     satu baris pun dibaca. -->
				<ul class="oak-card divide-y divide-gray-100 overflow-hidden">
					<li v-for="(r, i) in rows" :key="r.name">
						<button
							type="button"
							class="relative flex w-full items-center gap-3 py-3 pl-4 pr-3 text-left transition active:bg-gray-50"
							:class="r.name === activeName ? 'bg-brand-50/60' : ''"
							:disabled="Boolean(r.sent)"
							@click="pick(r)"
						>
							<span
								v-if="r.name === activeName"
								class="absolute inset-y-0 left-0 w-1 bg-brand-500"
							></span>
							<span
								class="oak-icon-tile h-6 w-6 shrink-0 text-[11px] font-extrabold"
								:class="r.sent ? 'bg-leaf-100 text-leaf-700' : r.name === activeName ? 'bg-brand-500 text-white' : 'bg-gray-100 text-gray-500'"
							>
								<Icon v-if="r.sent" name="check" :size="13" />
								<template v-else>{{ i + 1 }}</template>
							</span>
							<span class="min-w-0 flex-1">
								<span class="flex items-baseline gap-1.5">
									<span class="truncate font-mono text-sm font-bold text-gray-900">{{ r.container_no || r.container }}</span>
									<span v-if="r.container_principal" class="truncate text-xs text-gray-500">· {{ r.container_principal }}</span>
								</span>
								<span class="block truncate text-[11px] text-gray-500">{{ stateLine(r) }}</span>
							</span>
							<span class="oak-chip shrink-0" :class="stateChip(r).tone">{{ stateChip(r).label }}</span>
						</button>
					</li>
				</ul>

				<div class="flex items-center gap-2">
					<button class="oak-btn oak-btn-secondary flex-1 py-2.5" @click="emit('leave')">
						{{ labels.eirBatchExit }}
					</button>
					<button v-if="nextRow" class="oak-btn oak-btn-primary flex-1 py-2.5" @click="pick(nextRow)">
						{{ labels.eirBatchOpenOne }} {{ nextRow.container_no || nextRow.container }}
					</button>
				</div>
			</div>
		</section>
	</teleport>
</template>

<script setup>
import { computed } from "vue"
import { labels } from "@/utils/labels"
import { useDismissOnBack } from "@/utils/backstack"
import { STEP_COUNT, getStep } from "@/utils/eirBatch"
import Icon from "@/components/Icon.vue"

const props = defineProps({
	open: { type: Boolean, default: false },
	// Sama dengan yang dipakai bar batch: baris worklist + `sent` untuk yang sudah dikirim.
	rows: { type: Array, default: () => [] },
	activeName: { type: String, default: "" },
	voucher: { type: String, default: "" },
})
const emit = defineEmits(["close", "leave", "pick"])

function close() {
	emit("close")
}
useDismissOnBack(
	computed(() => props.open),
	close
)

function pick(r) {
	if (r.sent) return
	emit("pick", r)
	close()
}

// EIR berikutnya yang masih bisa dikerjakan setelah yang sedang dibuka — melingkar, sama
// seperti tombol ▶ di bar.
const nextRow = computed(() => {
	const list = props.rows.filter((r) => !r.sent)
	if (list.length < 2) return null
	const i = list.findIndex((r) => r.name === props.activeName)
	return list[(i + 1) % list.length] || null
})

const countLine = computed(() => {
	const n = props.rows.length
	const draft = props.rows.filter((r) => !r.sent && r.work_started_on).length
	const todo = props.rows.filter((r) => !r.sent && !r.work_started_on).length
	const sent = props.rows.filter((r) => r.sent).length
	const parts = [`${n} ${labels.eirBadge}`]
	if (draft) parts.push(`${draft} ${labels.eirStatusDraft.toLowerCase()}`)
	if (todo) parts.push(`${todo} ${labels.eirBatchNotStarted.toLowerCase()}`)
	if (sent) parts.push(`${sent} ${labels.eirBatchSentWord.toLowerCase()}`)
	return parts.join(" · ")
})

function stateLine(r) {
	if (r.sent) return `${labels.eirBatchSentAt} ${clock(r.sent.at)}`
	if (r.name === props.activeName)
		return `${labels.eirBatchOpenNow} · ${labels.eirStepWord} ${getStep(r.name) + 1} ${labels.eirBatchOf} ${STEP_COUNT}`
	if (r.work_started_on) return `${labels.eirStepWord} ${getStep(r.name) + 1} ${labels.eirBatchOf} ${STEP_COUNT}`
	return labels.eirBatchNotStarted
}

function stateChip(r) {
	if (r.sent) return { label: labels.eirBatchSentWord, tone: "bg-leaf-100 text-leaf-700" }
	if (r.work_started_on) return { label: labels.eirStatusDraft, tone: "bg-brand-100 text-brand-700" }
	return { label: labels.eirBatchTodoWord, tone: "bg-gray-100 text-gray-500" }
}

function clock(ms) {
	const d = new Date(ms)
	return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`
}
</script>
