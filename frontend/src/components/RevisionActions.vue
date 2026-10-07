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
					v-if="state.can_revise && (editTo || fields)"
					type="button"
					class="oak-btn oak-btn-primary flex-1 px-3 py-2.5 sm:flex-none"
					@click="editTo ? router.push(editTo) : openEdit()"
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

			<!-- Menus without a form of their own (Survey, Leak Check, Gate) revise their few
			     text fields right here — the same one save (revision.save_fields). -->
			<section v-else-if="box === 'edit'" class="oak-card space-y-3 p-4">
				<p class="oak-section-title">{{ labels.revisionEdit }}</p>
				<p class="text-xs text-gray-400">{{ labels.revisionHint }}</p>
				<label v-for="f in fields" :key="f.key" class="block space-y-1">
					<span class="text-xs text-gray-500">{{ f.label }}</span>
					<textarea v-if="f.multiline" v-model="values[f.key]" rows="2" class="oak-input"></textarea>
					<input v-else v-model="values[f.key]" type="text" class="oak-input" />
				</label>
				<div class="flex items-center gap-2">
					<button type="button" class="oak-btn oak-btn-primary px-3 py-2" :disabled="saveRes.loading" @click="sendEdit">
						<Icon v-if="!saveRes.loading" name="check" :size="16" />
						{{ saveRes.loading ? "…" : labels.revisionSave }}
					</button>
					<button type="button" class="oak-btn oak-btn-secondary px-3 py-2" :disabled="saveRes.loading" @click="box = ''">
						{{ labels.confirmCancel }}
					</button>
				</div>
			</section>

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
import { reactive, ref } from "vue"
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
	// Default: the shared one (revision.request_generic), keyed by doctype + name.
	requestUrl: { type: String, default: "container_depot.ess.revision.revision_request" },
	requestKey: { type: String, default: "name" },
	// Where Revisi Data opens the form, already carrying `revisi=1`.
	editTo: { type: [Object, String], default: null },
	// ...or, without a form: [{key, label, value, multiline}] edited inline and saved through
	// revision_save; `row` = the Survey Order tank row those fields sit on.
	fields: { type: Array, default: null },
	row: { type: String, default: null },
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
	else requestRes.submit({ doctype: props.doctype, [props.requestKey]: props.name, reason: reason.value || undefined })
}

const values = reactive({})
function openEdit() {
	for (const f of props.fields) values[f.key] = f.value ?? ""
	box.value = "edit"
}
const saveRes = createResource({
	url: "container_depot.ess.revision.revision_save",
	method: "POST",
	onSuccess: done(labels.revisionSaved),
	onError: fail,
})
function sendEdit() {
	saveRes.submit({ doctype: props.doctype, name: props.name, row: props.row || undefined, values: JSON.stringify(values) })
}
</script>
