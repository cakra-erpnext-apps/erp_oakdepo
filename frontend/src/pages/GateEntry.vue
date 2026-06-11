<template>
	<div class="mx-auto w-full max-w-lg space-y-4">
		<h1 class="text-lg font-semibold">{{ labels.gate }}</h1>

		<!-- Scan/type a Booking Code (OAK-…) or an Order code (ORD-…) -->
		<section class="space-y-2 rounded-lg border bg-white p-4">
			<label class="text-sm font-medium">{{ labels.gateScanTitle }}</label>
			<div class="flex gap-2">
				<input
					ref="scanInput"
					v-model.trim="code"
					type="text"
					autocapitalize="characters"
					:placeholder="labels.gateScanPlaceholder"
					class="w-full rounded-md border px-3 py-2 text-sm uppercase"
					@keyup.enter="doLookup"
				/>
				<button
					class="shrink-0 rounded-md bg-gray-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
					:disabled="!code || lookupRes.loading"
					@click="doLookup"
				>
					{{ lookupRes.loading ? "…" : labels.gateLookup }}
				</button>
			</div>
			<p v-if="lookupRes.error" class="text-sm text-red-600">{{ lookupError }}</p>
			<p v-else-if="detail && !detail.valid" class="text-sm text-red-600">{{ detail.error }}</p>
		</section>

		<template v-if="valid">
			<!-- Booking detail panel -->
			<section class="rounded-lg border bg-white">
				<div class="border-b px-3 py-2 text-sm font-semibold">{{ detail.booking }}</div>
				<dl class="divide-y text-sm">
					<div v-for="row in panelRows" :key="row.k" class="flex justify-between gap-3 px-3 py-1.5">
						<dt class="shrink-0 text-gray-500">{{ row.k }}</dt>
						<dd class="text-right font-medium">{{ row.v }}</dd>
					</div>
				</dl>
			</section>

			<!-- Cash unpaid → block generation, point to the cashier -->
			<section v-if="detail.payment_blocked" class="rounded-lg border border-red-200 bg-red-50 p-3 text-sm">
				<p class="font-medium text-red-800">⚠ {{ labels.gatePayBlocked }}</p>
				<p v-if="detail.sales_invoice" class="mt-1 text-red-700">
					{{ labels.gateInvoiceNo }}: <span class="font-medium">{{ detail.sales_invoice }}</span>
				</p>
			</section>

			<!-- Container list: existing bon shown per container; else selectable (max 2) -->
			<section class="space-y-2">
				<p class="text-sm font-medium">{{ labels.gateContainers }}</p>
				<p v-if="!detail.containers.length" class="rounded-lg border bg-white p-4 text-center text-sm text-gray-400">
					{{ labels.gateNoContainers }}
				</p>
				<ul v-else class="divide-y rounded-lg border bg-white">
					<li v-for="c in detail.containers" :key="c.booking_code" class="flex items-center gap-3 px-3 py-2.5">
						<input
							v-if="selectable(c) && !detail.payment_blocked"
							type="checkbox"
							class="h-4 w-4 shrink-0"
							:checked="selected.includes(c.booking_code)"
							:disabled="!selected.includes(c.booking_code) && selected.length >= 2"
							@change="toggle(c)"
						/>
						<span v-else class="h-4 w-4 shrink-0"></span>
						<div class="min-w-0 flex-1">
							<p class="truncate font-medium">{{ c.container_no || c.container }}</p>
							<p class="text-xs text-gray-500">{{ c.code_state }}</p>
						</div>
						<span
							v-if="c.order"
							class="shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium"
							:class="c.order.docstatus === 1 ? 'bg-blue-100 text-blue-800' : 'bg-amber-100 text-amber-800'"
						>
							{{ labels.gateBon }}: {{ c.order.name }}
						</span>
					</li>
				</ul>

				<button
					v-if="!detail.payment_blocked"
					class="w-full rounded-md bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50"
					:disabled="!selected.length || generateRes.loading"
					@click="doGenerate"
				>
					{{ generateRes.loading ? "…" : labels.gateGenerate + (selected.length ? ` (${selected.length})` : "") }}
				</button>
				<p v-if="!detail.payment_blocked" class="text-xs text-gray-400">{{ labels.gateSelectMax2 }}</p>
				<p v-if="generateError" class="text-sm text-red-600">{{ generateError }}</p>
				<p v-if="genResult && genResult.success" class="text-sm font-medium text-green-700">
					✓ {{ labels.gateGenerated }}: {{ genResult.order_name }}
				</p>
			</section>

			<button class="text-sm text-blue-600 underline" @click="reset">{{ labels.reset }}</button>
		</template>
	</div>
</template>

<script setup>
import { computed, nextTick, ref } from "vue"
import { createResource } from "frappe-ui"
import { labels, directionLabel } from "@/utils/labels"

const code = ref("")
const scanInput = ref(null)
const detail = ref(null)
const selected = ref([])
const genResult = ref(null)

const lookupRes = createResource({
	url: "container_depot.api.gate_lookup",
	method: "POST",
	onSuccess(data) {
		detail.value = data
		selected.value = []
		genResult.value = null
	},
})

const generateRes = createResource({
	url: "container_depot.api.gate_generate_order",
	method: "POST",
	onSuccess() {
		// genResult set in doGenerate's then(); refresh the panel so the new bon shows.
		if (detail.value && detail.value.booking) lookupRes.submit({ code: detail.value.booking })
	},
})

const valid = computed(() => detail.value && detail.value.valid)

const panelRows = computed(() => {
	if (!valid.value) return []
	const d = detail.value
	return [
		{ k: labels.branch, v: d.branch },
		{ k: labels.depot, v: d.depot },
		{ k: labels.bookingStatus, v: d.booking_status },
		{ k: labels.direction, v: directionLabel(d.direction) },
		{ k: labels.customer, v: d.customer_name || d.customer },
		{ k: labels.principal, v: d.principal_name || d.principal },
		{ k: labels.liftService, v: d.lift_item },
		{ k: labels.paymentType, v: d.payment_type },
		{ k: labels.paymentStatus, v: d.payment_status },
		{ k: labels.doReference, v: d.do_reference },
		{ k: labels.eirRemarks, v: d.remarks },
	].filter((r) => r.v != null && r.v !== "")
})

const lookupError = computed(
	() => lookupRes.error?.messages?.[0] || lookupRes.error?.message || labels.error,
)
const generateError = computed(
	() => generateRes.error?.messages?.[0] || generateRes.error?.message || null,
)

// A container is selectable for a new bon when its code is still pending (Active)
// and it isn't already on a bon.
function selectable(c) {
	return c.code_state === "Active" && !c.order
}

function toggle(c) {
	const i = selected.value.indexOf(c.booking_code)
	if (i >= 0) selected.value.splice(i, 1)
	else if (selected.value.length < 2) selected.value.push(c.booking_code)
}

function doLookup() {
	if (!code.value) return
	lookupRes.submit({ code: code.value })
}

function doGenerate() {
	if (!selected.value.length || detail.value.payment_blocked) return
	generateRes
		.submit({ booking: detail.value.booking, selected_codes: JSON.stringify(selected.value) })
		.then((data) => {
			genResult.value = data
		})
}

function reset() {
	code.value = ""
	detail.value = null
	selected.value = []
	genResult.value = null
	nextTick(() => scanInput.value && scanInput.value.focus())
}
</script>
