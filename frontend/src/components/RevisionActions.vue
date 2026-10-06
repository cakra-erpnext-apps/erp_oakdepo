<template>
	<!-- Revisi Data di layar Riwayat — satu bentuk untuk EIR, Cleaning dan M&R
	     (container_depot/revision.py). Team mengajukan; yang berhak (Adm Ops) langsung
	     merevisi atau menolak. Tidak ada status "sedang direvisi": revisi adalah satu simpan,
	     jadi tombolnya hanya membuka form-nya. Order yang sudah diinvoice tidak menawarkan
	     apa pun, dan servernya pun menolak. -->
	<div v-if="state && Object.keys(state).length" class="space-y-2">
		<p v-if="state.locked" class="px-1 text-xs text-gray-500">
			{{ labels.revisionLocked.replace("{inv}", state.locked) }}
		</p>
		<template v-else>
			<p v-if="state.requested" class="oak-card border-pink-200 bg-pink-50 p-3 text-sm text-pink-800">
				{{ labels.revisionRequested }}{{ state.note ? ": " + state.note : "" }}
			</p>
			<!-- Full width on a phone, natural width from `sm:` up — the only actions here. -->
			<div v-if="box === ''" class="flex flex-wrap items-center gap-2">
				<button
					v-if="state.can_revise && editTo"
					type="button"
					class="oak-btn oak-btn-primary flex-1 px-3 py-2.5 sm:flex-none"
					@click="router.push(editTo)"
				>
					<Icon name="edit-3" :size="16" /> {{ labels.revisionEdit }}
				</button>
				<button
					v-if="state.can_revise && state.requested"
					type="button"
					class="oak-btn oak-btn-secondary flex-1 px-3 py-2.5 sm:flex-none"
					@click="openBox('reject')"
				>
					<Icon name="x" :size="16" /> {{ labels.revisionReject }}
				</button>
				<button
					v-if="!state.can_revise && !state.requested"
					type="button"
					class="oak-btn oak-btn-secondary flex-1 px-3 py-2.5 sm:flex-none"
					@click="openBox('request')"
				>
					<Icon name="rotate-ccw" :size="16" /> {{ labels.eirReqRevision }}
				</button>
			</div>

			<section v-else class="oak-card space-y-2 p-4">
				<p class="oak-section-title">{{ box === "reject" ? labels.revisionReject : labels.eirReqRevision }}</p>
				<p class="text-xs text-gray-400">{{ box === "reject" ? labels.revisionRejectHint : labels.eirReqRevisionHint }}</p>
				<textarea
					v-model.trim="reason"
					rows="2"
					:placeholder="box === 'reject' ? labels.revisionRejectReason : labels.eirReqRevisionReason"
					class="oak-input"
				></textarea>
				<div class="flex items-center gap-2">
					<button
						type="button"
						class="oak-btn oak-btn-primary px-3 py-2"
						:disabled="res.loading || (box === 'reject' && !reason)"
						@click="sendBox"
					>
						<Icon v-if="!res.loading" name="send" :size="16" />
						{{ res.loading ? "…" : box === "reject" ? labels.revisionRejectSend : labels.eirReqRevisionSend }}
					</button>
					<button type="button" class="oak-btn oak-btn-secondary px-3 py-2" :disabled="res.loading" @click="box = ''">
						{{ labels.confirmCancel }}
					</button>
				</div>
			</section>
		</template>
	</div>
</template>

<script setup>
import { ref } from "vue"
import { useRouter } from "vue-router"
import { createResource } from "frappe-ui"
import { labels } from "@/utils/labels"
import { toast } from "@/utils/toast"
import Icon from "@/components/Icon.vue"

const props = defineProps({
	// revision.state from the detail payload: {can_revise, locked, requested, note}.
	state: { type: Object, default: null },
	doctype: { type: String, required: true },
	name: { type: String, required: true },
	// The menu's own Ajukan Revisi endpoint (it rings that menu's desk) and its order param.
	requestUrl: { type: String, required: true },
	requestKey: { type: String, required: true },
	// Where Revisi Data opens the form, already carrying `revisi=1`.
	editTo: { type: [Object, String], default: null },
})
const emit = defineEmits(["changed"])
const router = useRouter()

const box = ref("") // "" | "request" | "reject"
const reason = ref("")
function openBox(kind) {
	box.value = kind
	reason.value = ""
}

const done = (msg) => () => {
	toast.success(msg)
	box.value = ""
	emit("changed")
}
const fail = (err) => toast.error(err?.messages?.[0] || err?.message || labels.error)
const requestRes = createResource({
	url: props.requestUrl,
	method: "POST",
	onSuccess: done(labels.eirReqRevisionSent),
	onError: fail,
})
const rejectRes = createResource({
	url: "container_depot.ess.revision.revision_reject",
	method: "POST",
	onSuccess: done(labels.revisionRejected),
	onError: fail,
})
const res = { get loading() { return requestRes.loading || rejectRes.loading } }
function sendBox() {
	if (box.value === "reject") rejectRes.submit({ doctype: props.doctype, name: props.name, reason: reason.value })
	else requestRes.submit({ [props.requestKey]: props.name, reason: reason.value || undefined })
}
</script>
