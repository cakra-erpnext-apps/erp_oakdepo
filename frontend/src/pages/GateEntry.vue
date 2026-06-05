<template>
	<div class="mx-auto w-full max-w-lg space-y-4">
		<h1 class="text-lg font-semibold">{{ labels.gate }}</h1>

		<!-- Step 1 — validate the booking code (reuses /api/.../validate_qr) -->
		<section class="space-y-2 rounded-lg border bg-white p-4">
			<label class="text-sm font-medium">{{ labels.bookingCode }}</label>
			<div class="flex gap-2">
				<input
					v-model.trim="code"
					type="text"
					autocapitalize="characters"
					:placeholder="labels.bookingCodePlaceholder"
					class="w-full rounded-md border px-3 py-2 text-sm uppercase"
					@keyup.enter="doValidate"
				/>
				<button
					class="shrink-0 rounded-md bg-gray-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
					:disabled="!code || validateRes.loading"
					@click="doValidate"
				>
					{{ validateRes.loading ? "…" : labels.validate }}
				</button>
			</div>
			<p v-if="validateRes.error" class="text-sm text-red-600">{{ labels.error }}</p>
			<p v-else-if="booking && !booking.valid" class="text-sm text-red-600">
				{{ labels.codeInvalid }} ({{ booking.state }})
			</p>
		</section>

		<!-- Step 2 — confirm container vs booking + capture truck/driver -->
		<section v-if="booking && booking.valid" class="space-y-3 rounded-lg border bg-white p-4">
			<dl class="divide-y text-sm">
				<div class="flex justify-between py-1.5">
					<dt class="text-gray-500">{{ labels.bookingCode }}</dt>
					<dd class="font-medium">{{ booking.booking_code }}</dd>
				</div>
				<div class="flex justify-between py-1.5">
					<dt class="text-gray-500">{{ labels.direction }}</dt>
					<dd class="font-medium">{{ directionLabel(booking.direction) }}</dd>
				</div>
			</dl>

			<div>
				<label class="text-sm font-medium">{{ labels.type }} / No. Tank</label>
				<input
					v-model.trim="containerNo"
					type="text"
					class="mt-1 w-full rounded-md border px-3 py-2 text-sm uppercase"
				/>
			</div>
			<div class="grid grid-cols-2 gap-2">
				<div>
					<label class="text-sm font-medium">{{ labels.truckPlate }}</label>
					<input v-model.trim="truckPlate" type="text" class="mt-1 w-full rounded-md border px-3 py-2 text-sm uppercase" />
				</div>
				<div>
					<label class="text-sm font-medium">{{ labels.driverName }}</label>
					<input v-model.trim="driverName" type="text" class="mt-1 w-full rounded-md border px-3 py-2 text-sm" />
				</div>
			</div>

			<button
				class="w-full rounded-md bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50"
				:disabled="!containerNo || registerRes.loading"
				@click="doRegister"
			>
				{{ registerRes.loading ? "…" : labels.registerGate }}
			</button>

			<!-- Mismatch / failure surfaced from the server; nothing is written. -->
			<p v-if="registerError" class="text-sm text-red-600">{{ registerError }}</p>
		</section>

		<!-- Result -->
		<section v-if="result && result.success" class="rounded-lg border border-green-200 bg-green-50 p-4">
			<p class="font-medium text-green-800">✓ {{ labels.gateOk }}</p>
			<p class="mt-1 text-sm text-gray-700">
				{{ result.container_no }} · {{ result.gate_entry_id }} · {{ result.container_status }}
			</p>
			<button class="mt-2 text-sm text-blue-600 underline" @click="reset">{{ labels.reset }}</button>
		</section>
	</div>
</template>

<script setup>
import { computed, ref } from "vue"
import { createResource } from "frappe-ui"
import { labels, directionLabel } from "@/utils/labels"

const code = ref("")
const booking = ref(null)
const containerNo = ref("")
const truckPlate = ref("")
const driverName = ref("")
const result = ref(null)

// Reuse the existing gate endpoints — no new backend (PRD §F4 reuse).
const validateRes = createResource({
	url: "container_depot.api.validate_qr",
	method: "POST",
	onSuccess(data) {
		booking.value = data
		result.value = null
		if (data?.valid) containerNo.value = data.container_no || ""
	},
})

const registerRes = createResource({
	url: "container_depot.api.register_gate_entry",
	method: "POST",
	onSuccess(data) {
		result.value = data
	},
})

const registerError = computed(() => {
	// register_gate_entry returns {success:false, error} on a mismatch/bad state.
	if (result.value && result.value.success === false) return result.value.error
	if (registerRes.error) return registerRes.error.messages?.[0] || registerRes.error.message
	return null
})

function doValidate() {
	if (!code.value) return
	result.value = null
	validateRes.submit({ qr_data: code.value })
}

function doRegister() {
	if (!containerNo.value) return
	registerRes.submit({
		booking_code: booking.value.booking_code,
		container_no: containerNo.value,
		truck_plate: truckPlate.value || undefined,
		driver_name: driverName.value || undefined,
	})
}

function reset() {
	code.value = ""
	booking.value = null
	containerNo.value = ""
	truckPlate.value = ""
	driverName.value = ""
	result.value = null
}
</script>
