<template>
	<div class="mx-auto w-full max-w-lg space-y-4 md:max-w-2xl">
		<div class="flex items-center justify-between gap-2">
			<div class="flex min-w-0 items-center gap-2">
				<!-- The tile follows the loaded booking: a log-in badge over a gate-OUT screen
				     is the kind of small lie that gets a tank waved through the wrong way. -->
				<span class="oak-icon-tile h-9 w-9" :class="valid ? dirMeta.tile : 'bg-brand-50 text-brand-600'">
					<Icon :name="valid ? dirMeta.icon : 'truck'" :size="20" />
				</span>
				<div class="min-w-0">
					<h1 class="flex items-center gap-2 text-lg font-extrabold leading-tight tracking-tight">
						{{ labels.gate }}
						<span
							v-if="valid"
							class="oak-chip shrink-0 text-[10px] font-extrabold tracking-wide"
							:class="dirMeta.chip"
						>
							{{ dirMeta.label }}
						</span>
					</h1>
					<p class="truncate text-xs text-gray-500">{{ valid ? dirMeta.desc : labels.gateDesc }}</p>
				</div>
			</div>
			<router-link to="/gate/history" class="oak-btn oak-btn-secondary shrink-0 px-3 py-2">
				<Icon name="clock" :size="16" /> {{ labels.navHistory }}
			</router-link>
		</div>

		<!-- The one screen in the app that genuinely cannot work offline, so it says so up
		     front instead of letting the operator scan and fail. Explained rather than just
		     flagged: "no internet" invites a retry, "the booking's payment status has to be
		     checked live" tells them to go and find signal. -->
		<section
			v-if="!outbox.online"
			class="oak-card flex items-start gap-3 border-amber-200 bg-amber-50 p-4"
		>
			<Icon name="cloud-off" :size="20" class="mt-0.5 shrink-0 text-amber-600" />
			<div>
				<p class="font-bold text-amber-900">{{ labels.gateNeedsOnline }}</p>
				<p class="mt-0.5 text-xs leading-relaxed text-amber-800">{{ labels.gateNeedsOnlineHint }}</p>
			</div>
		</section>

		<!-- Scan/type a Booking Code (OAK-…) or an Order code (ORD-…) -->
		<section class="oak-section space-y-3">
			<div>
				<label class="oak-label">{{ labels.gateScanTitle }}</label>
				<div class="flex gap-2">
					<input
						ref="scanInput"
						v-model.trim="code"
						type="text"
						autocapitalize="characters"
						autocorrect="off"
						autocomplete="off"
						spellcheck="false"
						enterkeyhint="search"
						:placeholder="labels.gateScanPlaceholder"
						class="oak-input uppercase"
						@keyup.enter="doLookup"
					/>
					<button
						class="oak-btn oak-btn-primary shrink-0 px-4"
						:disabled="!code || lookupRes.loading"
						@click="doLookup"
					>
						<Icon v-if="!lookupRes.loading" name="search" :size="16" />
						{{ lookupRes.loading ? "…" : labels.gateLookup }}
					</button>
				</div>
			</div>
			<button class="oak-btn oak-btn-secondary w-full" @click="startScan">
				<Icon name="camera" :size="18" />
				{{ labels.gateScan }}
			</button>
			<p v-if="scanErr" class="flex items-center gap-1.5 text-sm text-amber-600">
				<Icon name="alert-triangle" :size="15" /> {{ scanErr }}
			</p>
			<p v-if="lookupRes.error" class="flex items-center gap-1.5 text-sm text-red-600">
				<Icon name="alert-circle" :size="15" /> {{ lookupError }}
			</p>
			<p v-else-if="detail && !detail.valid" class="flex items-center gap-1.5 text-sm text-red-600">
				<Icon name="alert-circle" :size="15" /> {{ detail.error }}
			</p>
		</section>

		<!-- Container matched more than one active booking — let the operator choose. -->
		<section v-if="choices" class="oak-card animate-slide-up overflow-hidden">
			<div class="flex items-center gap-3 border-b border-gray-100 bg-gray-50/70 px-4 py-3">
				<span class="oak-icon-tile h-9 w-9 bg-amber-50 text-amber-600"><Icon name="layers" :size="18" /></span>
				<p class="text-sm font-bold text-gray-900">{{ labels.gateChoicesTitle }}</p>
			</div>
			<ul class="divide-y divide-gray-100">
				<li v-for="c in choices" :key="c.booking">
					<button
						class="flex w-full items-center justify-between gap-3 px-4 py-3 text-left hover:bg-gray-50"
						:disabled="lookupRes.loading"
						@click="pickChoice(c.booking)"
					>
						<span class="min-w-0">
							<span class="mb-0.5 flex items-center gap-1.5">
								<span
									class="oak-chip shrink-0 text-[10px] font-extrabold tracking-wide"
									:class="gateDirection(c.direction).chip"
								>
									<Icon :name="gateDirection(c.direction).icon" :size="11" />
									{{ gateDirection(c.direction).label }}
								</span>
								<span class="truncate text-sm font-bold text-gray-900">{{ c.booking }}</span>
							</span>
							<span class="block truncate text-xs text-gray-500">
								{{ c.container_no }} · {{ c.customer_name || c.customer }}
							</span>
						</span>
						<Icon name="chevron-right" :size="18" class="shrink-0 text-gray-400" />
					</button>
				</li>
			</ul>
		</section>

		<!-- The booking panel is what the operator is waiting on with a truck at the barrier,
		     so it says it is coming rather than leaving the screen unchanged after a scan. -->
		<SkeletonDetail v-if="lookupRes.loading" :cells="4" :sections="2" :delay="180" />

		<template v-if="valid">
			<!-- Booking detail panel. The direction leads: an operator at the gate needs to
			     know which way this tank is moving before anything else on the screen. -->
			<section class="oak-card animate-slide-up overflow-hidden">
				<div class="h-1.5 w-full" :class="dirMeta.bar"></div>
				<div class="flex items-center gap-3 border-b border-gray-100 bg-gray-50/70 px-4 py-3">
					<span class="oak-icon-tile h-10 w-10 shrink-0" :class="dirMeta.tile">
						<Icon :name="dirMeta.icon" :size="20" />
					</span>
					<div class="min-w-0 flex-1">
						<p class="truncate text-sm font-bold text-gray-900">{{ detail.booking }}</p>
						<p class="truncate text-xs text-gray-500">{{ dirMeta.desc }}</p>
					</div>
					<span class="oak-chip shrink-0 text-xs font-extrabold tracking-wide" :class="dirMeta.chip">
						{{ dirMeta.label }}
					</span>
				</div>
				<dl class="text-sm">
					<template v-for="g in panelGroups" :key="g.title">
						<dt class="bg-gray-50/60 px-4 py-1.5 text-[11px] font-bold uppercase tracking-wide text-gray-400">
							{{ g.title }}
						</dt>
						<dd
							v-for="row in g.rows"
							:key="row.k"
							class="flex justify-between gap-3 border-t border-gray-100 px-4 py-2"
						>
							<span class="shrink-0 text-gray-500">{{ row.k }}</span>
							<span class="text-right font-semibold text-gray-800">{{ row.v }}</span>
						</dd>
					</template>
				</dl>
			</section>

			<!-- Gate blocked: booking not yet confirmed. Reason-specific guidance. -->
			<section
				v-if="detail.block_reason"
				class="animate-slide-up rounded-2xl border border-red-200 bg-red-50 p-4"
			>
				<p class="flex items-center gap-2 font-semibold text-red-800">
					<Icon name="alert-triangle" :size="18" /> {{ labels.gateBlockedTitle }}
				</p>
				<p class="mt-1 pl-7 text-sm text-red-700">
					{{ detail.block_reason === "cash_unpaid" ? labels.gatePayBlocked : labels.gateNotSubmitted }}
				</p>
				<p v-if="detail.block_reason === 'cash_unpaid' && detail.sales_invoice" class="mt-1 pl-7 text-sm text-red-700">
					{{ labels.gateInvoiceNo }}: <span class="font-semibold">{{ detail.sales_invoice }}</span>
				</p>
			</section>

			<!-- Container list: existing bon shown per container; else selectable (max 2).
			     Hidden entirely while the gate is blocked — only the keterangan shows. -->
			<section v-if="!detail.block_reason" class="animate-slide-up space-y-2">
				<div class="flex items-center justify-between">
					<p class="oak-section-title">{{ labels.gateContainers }}</p>
					<span class="oak-chip bg-gray-100 text-gray-600">{{ detail.containers.length }}</span>
				</div>
				<p v-if="!detail.containers.length" class="oak-card p-6 text-center text-sm text-gray-400">
					{{ labels.gateNoContainers }}
				</p>
				<ul v-else class="oak-card divide-y divide-gray-100 overflow-hidden">
					<li v-for="c in detail.containers" :key="c.booking_code" class="px-4 py-3">
						<div class="flex items-center gap-3">
							<input
								v-if="selectable(c) && !detail.block_reason"
								type="checkbox"
								class="h-5 w-5 shrink-0 accent-brand-600"
								:checked="selected.includes(c.booking_code)"
								:disabled="!selected.includes(c.booking_code) && selected.length >= 2"
								@change="toggle(c)"
							/>
							<span v-else class="oak-icon-tile h-8 w-8 shrink-0 bg-gray-100 text-gray-400">
								<Icon name="package" :size="16" />
							</span>
							<div class="min-w-0 flex-1">
								<p class="truncate font-semibold text-gray-900">{{ c.container_no || c.container }}</p>
								<p class="text-xs text-gray-500">{{ c.code_state }}</p>
							</div>
							<!-- Gate-out readiness. Only meaningful on the way out: on the way IN the
							     tank isn't in the yard yet, so open work is not this gate's business. -->
							<span
								v-if="isOut && !c.order && holds(c).length"
								class="oak-chip shrink-0 bg-red-100 text-red-800"
							>
								<Icon name="alert-triangle" :size="12" /> {{ labels.gateHeldBy }}
							</span>
							<span
								v-else-if="isOut && !c.order"
								class="oak-chip shrink-0 bg-leaf-100 text-leaf-800"
							>
								<Icon name="check-circle" :size="12" /> {{ labels.gateReadyOut }}
							</span>
							<span
								v-if="c.order"
								class="oak-chip shrink-0"
								:class="c.order.docstatus === 1 ? 'bg-blue-100 text-blue-800' : 'bg-amber-100 text-amber-800'"
							>
								<Icon name="file-text" :size="12" /> {{ c.order.name }}
							</span>
						</div>
						<!-- Naming the blockers beats a bare "not ready": the operator can go and
						     close them, or tell the driver exactly what is outstanding. -->
						<div v-if="isOut && !c.order && holds(c).length" class="mt-2 rounded-xl bg-red-50 px-3 py-2">
							<p class="text-xs text-red-700">{{ labels.gateHeldHint }}</p>
							<ul class="mt-1 space-y-0.5">
								<li v-for="o in holds(c)" :key="o.name" class="flex items-center gap-1.5 text-xs text-red-800">
									<Icon name="alert-circle" :size="12" class="shrink-0" />
									<span class="font-semibold">{{ o.label }}</span>
									<span class="truncate">{{ o.name }}</span>
									<span class="oak-chip bg-white/70 text-[10px] text-red-700">{{ o.status }}</span>
								</li>
							</ul>
						</div>
					</li>
				</ul>

				<button
					v-if="!detail.block_reason"
					class="oak-btn oak-btn-primary w-full"
					:disabled="!selected.length"
					@click="openGenerate"
				>
					<Icon name="file-plus" :size="18" />
					{{ labels.gateGenerate + (selected.length ? ` (${selected.length})` : "") }}
				</button>
				<p v-if="!detail.block_reason" class="text-xs text-gray-400">{{ labels.gateSelectMax2 }}</p>
				<p v-if="generateError" class="flex items-center gap-1.5 text-sm text-red-600">
					<Icon name="alert-circle" :size="15" /> {{ generateError }}
				</p>
			</section>

			<button class="oak-link inline-flex items-center gap-1 text-sm" @click="reset">
				<Icon name="rotate-ccw" :size="14" /> {{ labels.reset }}
			</button>
		</template>

		<!-- Vehicle / driver form (bottom sheet) — mirrors the Desk Generate dialog -->
		<div
			v-if="showVehicleForm"
			class="fixed inset-0 z-50 flex items-end justify-center bg-black/40 md:items-center md:p-4"
			@click.self="closeVehicleForm"
		>
			<div
				class="flex max-h-[90vh] w-full max-w-lg flex-col overflow-hidden rounded-t-2xl bg-white shadow-soft animate-slide-up md:max-w-xl md:rounded-2xl"
			>
				<div class="flex items-center justify-between border-b border-gray-100 px-4 py-3">
					<div class="flex min-w-0 items-center gap-2">
						<span class="oak-icon-tile h-8 w-8 shrink-0 bg-brand-50 text-brand-600"><Icon name="truck" :size="16" /></span>
						<div class="min-w-0">
							<p class="font-bold leading-tight text-gray-900">{{ labels.gateVehicleTitle }}</p>
							<p class="truncate text-xs text-gray-500">{{ selectedLabels }}</p>
						</div>
					</div>
					<button class="rounded-lg p-1.5 text-gray-400 transition hover:bg-gray-100" @click="closeVehicleForm">
						<Icon name="x" :size="18" />
					</button>
				</div>
				<div class="flex-1 space-y-3 overflow-y-auto px-4 py-4">
					<p class="text-xs text-gray-500">{{ labels.gateVehicleHint }}</p>
					<div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
						<div v-for="f in vehicleFields" :key="f.key" :class="f.type === 'textarea' ? 'sm:col-span-2' : ''">
							<label class="oak-label">
								{{ f.label }}
								<span v-if="f.required" class="text-red-500">*</span>
								<span v-else class="font-normal normal-case text-gray-400">({{ labels.optional }})</span>
							</label>
							<SearchSelect
								v-if="f.type === 'select'"
								v-model="vehicle[f.key]"
								:options="f.options"
								:option-value="f.optionValue || null"
								:option-label="f.optionLabel || null"
								:group-by="f.groupBy || null"
								:empty-label="f.emptyLabel"
								:placeholder="labels.selectPlaceholder"
								:search-placeholder="labels.selectSearch"
							/>
							<textarea v-else-if="f.type === 'textarea'" v-model.trim="vehicle[f.key]" rows="2" class="oak-input"></textarea>
							<template v-else-if="f.type === 'datalist'">
								<input v-model.trim="vehicle[f.key]" :list="`dl-${f.key}`" class="oak-input" autocomplete="off" />
								<datalist :id="`dl-${f.key}`">
									<option v-for="o in f.options" :key="o" :value="o" />
								</datalist>
							</template>
							<input v-else v-model.trim="vehicle[f.key]" :type="f.inputType || 'text'" class="oak-input" />
						</div>
					</div>
					<p v-if="generateError" class="flex items-center gap-1.5 text-sm text-red-600">
						<Icon name="alert-circle" :size="15" /> {{ generateError }}
					</p>
				</div>
				<div class="flex gap-2 border-t border-gray-100 px-4 py-3 pb-safe-bottom">
					<button class="oak-btn oak-btn-secondary flex-1" @click="closeVehicleForm">{{ labels.cancelBtn }}</button>
					<button class="oak-btn oak-btn-primary flex-[2]" :disabled="generateRes.loading" @click="doGenerate">
						<Icon v-if="!generateRes.loading" name="file-plus" :size="18" />
						{{ generateRes.loading ? "…" : labels.gateGenerate }}
					</button>
				</div>
			</div>
		</div>

		<!-- Camera QR scanner overlay -->
		<div
			v-if="scanning"
			class="fixed inset-0 z-50 flex flex-col items-center justify-center gap-5 bg-black/90 p-5 pb-safe-bottom"
		>
			<p class="flex items-center gap-2 text-sm font-medium text-white">
				<Icon name="camera" :size="18" /> {{ labels.gateScanHint }}
			</p>
			<div id="gate-reader" class="w-full max-w-sm overflow-hidden rounded-2xl bg-black ring-4 ring-white/10"></div>
			<button class="oak-btn oak-btn-secondary px-8" @click="stopScan">
				<Icon name="x" :size="18" /> {{ labels.gateScanClose }}
			</button>
		</div>
	</div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref } from "vue"
import { createResource } from "frappe-ui"
import { Html5Qrcode } from "html5-qrcode"
import { labels, gateDirection } from "@/utils/labels"
import { toast } from "@/utils/toast"
import Icon from "@/components/Icon.vue"
import SearchSelect from "@/components/SearchSelect.vue"
import SkeletonDetail from "@/components/SkeletonDetail.vue"
import { outbox } from "@/data/outbox"
import { uid } from "@/utils/idb"
import { useDismissOnBack } from "@/utils/backstack"

const code = ref("")
const scanInput = ref(null)
const detail = ref(null)
const selected = ref([])
const showVehicleForm = ref(false)
const vehicle = ref({})
const requestId = ref(null)
const scanning = ref(false)
const scanErr = ref("")
let qrScanner = null

// Three layers stack up on this page, and Back has to peel them one at a time instead of
// walking off the screen: the camera overlay, the vehicle sheet, then the looked-up booking
// itself. Each hands Back the same function its own close button calls.
useDismissOnBack(
	() => scanning.value,
	() => stopScan()
)
useDismissOnBack(
	() => showVehicleForm.value,
	() => closeVehicleForm()
)
useDismissOnBack(
	() => !!detail.value,
	() => reset()
)

const lookupRes = createResource({
	url: "container_depot.api.gate_lookup",
	method: "POST",
	onSuccess(data) {
		detail.value = data
		selected.value = []
	},
})

const generateRes = createResource({
	url: "container_depot.api.gate_generate_order",
	method: "POST",
})

// Active cargo master for the "Generate Bon" cargo picker (datalist suggestions).
const cargoRes = createResource({
	url: "container_depot.api.gate_cargo_options",
	method: "GET",
	auto: true,
})
const cargoOptions = computed(() => cargoRes.data?.cargos || [])

// Shipper / Angkutan / EMKL picker. `shipper` is a Link to Customer on both bon
// doctypes, so a typed name that isn't in the master is refused at insert — the gate
// picks from the master instead. EMKL-flagged customers are grouped first.
const shipperRes = createResource({
	url: "container_depot.api.gate_shipper_options",
	method: "GET",
	auto: true,
})
const shipperOptions = computed(() => shipperRes.data?.shippers || [])
const shipperValue = (o) => o.name
const shipperLabel = (o) => (o.customer_name && o.customer_name !== o.name ? `${o.customer_name} (${o.name})` : o.name)
const shipperGroup = (o) => (o.is_transporter ? labels.gateShipperEmkl : labels.gateShipperOther)

// A real booking detail (has containers) vs. a multi-booking picker response.
const valid = computed(() => detail.value && detail.value.valid && !!detail.value.booking)
const choices = computed(() =>
	detail.value && detail.value.valid && detail.value.choices ? detail.value.choices : null,
)

// Picking a booking from the container-search list re-runs the lookup by booking name,
// which hits the exact-match branch and returns the full detail panel.
function pickChoice(booking) {
	lookupRes.submit({ code: booking })
}

// Vehicle/driver form fields — mirrors the Desk "Generate" dialog, adapted to the
// booking direction. Keys are the exact make_order vehicle_data keys.
const shipperField = computed(() => ({
	key: "shipper",
	label: labels.vShipper,
	type: "select",
	options: shipperOptions.value,
	optionValue: shipperValue,
	optionLabel: shipperLabel,
	groupBy: shipperGroup,
	emptyLabel: labels.gateShipperEmpty,
}))

const vehicleFields = computed(() => {
	if (!detail.value) return []
	if (detail.value.direction === "Tank In")
		return [
			{ key: "truck_plate", label: labels.truckNo, inputType: "text", required: true },
			{ key: "driver", label: labels.driverName, inputType: "text", required: true },
			{ key: "driver_phone", label: labels.driverPhone, inputType: "tel", required: true },
			{ key: "ro", label: labels.vRo, inputType: "text" },
			{ key: "condition", label: labels.vCondition, type: "select", options: ["EMPTY CLEAN", "EMPTY DIRTY", "LADEN"], required: true },
			{ key: "cargo", label: labels.cargo, type: "datalist", options: cargoOptions.value },
			{ key: "tanggal_bongkar_actual", label: labels.vDateBongkar, inputType: "date" },
			shipperField.value,
			{ key: "ex_vessel", label: labels.exVessel, inputType: "text" },
			{ key: "remarks", label: labels.eirRemarks, type: "textarea" },
		]
	return [
		{ key: "truck_plate", label: labels.truckNo, inputType: "text", required: true },
		{ key: "driver_name", label: labels.driverName, inputType: "text", required: true },
		{ key: "driver_phone", label: labels.driverPhone, inputType: "tel", required: true },
		{ key: "ro", label: labels.vRo, inputType: "text" },
		{ key: "destination", label: labels.vDestination, inputType: "text" },
		{ key: "tanggal_muat", label: labels.vDateMuat, inputType: "date" },
		shipperField.value,
		{ key: "remarks", label: labels.eirRemarks, type: "textarea" },
	]
})

// Container numbers picked for this bon — shown in the form header.
const selectedLabels = computed(() =>
	!detail.value
		? ""
		: detail.value.containers
				.filter((c) => selected.value.includes(c.booking_code))
				.map((c) => c.container_no || c.container)
				.join(", "),
)

// Direction drives the whole panel's colour + wording — GATE IN vs GATE OUT.
const dirMeta = computed(() => gateDirection(detail.value && detail.value.direction))
const isOut = computed(() => !!detail.value && detail.value.direction === "Tank Out")

// Grouped so the panel reads as three answers — whose booking, what it costs, what to
// watch out for — instead of eleven undifferentiated rows. Payment disappears entirely
// when finance is off: there is no invoice, so "Unpaid" would be a lie.
const panelGroups = computed(() => {
	if (!valid.value) return []
	const d = detail.value
	const groups = [
		{
			title: labels.gateSectionBooking,
			rows: [
				{ k: labels.bookingStatus, v: d.booking_status },
				{ k: labels.customer, v: d.customer_name || d.customer },
				{ k: labels.principal, v: d.principal_name || d.principal },
				{ k: labels.branch, v: d.branch },
				{ k: labels.depot, v: d.depot },
			],
		},
		{
			title: labels.gateSectionPayment,
			rows:
				d.finance_enabled === false
					? []
					: [
							{ k: labels.liftService, v: d.lift_item },
							{ k: labels.paymentType, v: d.payment_type },
							{ k: labels.paymentStatus, v: d.payment_status },
						],
		},
		{
			title: labels.gateSectionNote,
			rows: [
				{ k: labels.doReference, v: d.do_reference },
				{ k: labels.eirRemarks, v: d.remarks },
			],
		},
	]
	return groups
		.map((g) => ({ ...g, rows: g.rows.filter((r) => r.v != null && r.v !== "") }))
		.filter((g) => g.rows.length)
})

const lookupError = computed(
	() => lookupRes.error?.messages?.[0] || lookupRes.error?.message || labels.error,
)
const generateError = computed(
	() => generateRes.error?.messages?.[0] || generateRes.error?.message || null,
)

// Unfinished work still holding this tank — only a gate-OUT concern. On the way in the
// tank isn't in the yard yet, so anything open belongs to a previous stay.
function holds(c) {
	return isOut.value ? c.open_orders || [] : []
}

// A container is selectable for a new bon when its code is still pending (Active), it
// isn't already on a bon, and nothing is holding it. Order Muat refuses a held tank
// server-side anyway — blocking it here means the operator learns that before filling
// in the whole vehicle form, not after.
function selectable(c) {
	return c.code_state === "Active" && !c.order && !holds(c).length
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

// Open the vehicle/driver form, pre-filled from the FIRST selected container's
// booking line (the same auto-fill the Desk Generate dialog does).
function openGenerate() {
	if (!selected.value.length || detail.value.block_reason) return
	const first = detail.value.containers.find((x) => x.booking_code === selected.value[0])
	const line = (first && first.line) || {}
	const today = new Date().toISOString().slice(0, 10)
	vehicle.value = {
		truck_plate: line.truck_plate || "",
		driver: line.driver || "",
		driver_name: line.driver || "",
		driver_phone: line.driver_phone || "",
		ro: line.ro || "",
		condition: line.condition || "",
		cargo: line.cargo || "",
		destination: "",
		ex_vessel: "",
		shipper: detail.value.customer || "",
		tanggal_bongkar_actual: line.tanggal_bongkar || today,
		tanggal_muat: today,
		remarks: "",
	}
	// One id per intended bon, minted when the form opens rather than when Generate is
	// pressed. That is the whole point: on a slow link the operator presses Generate, sees
	// nothing happen, and presses it again — and the second press has to be recognised as the
	// same bon. An id minted per click would issue two. See ess/idempotency.py.
	requestId.value = uid()
	showVehicleForm.value = true
}

function closeVehicleForm() {
	showVehicleForm.value = false
}

function doGenerate() {
	if (!selected.value.length || detail.value.block_reason) return
	const vd = {}
	const missing = []
	for (const f of vehicleFields.value) {
		const v = vehicle.value[f.key]
		const filled = v != null && String(v).trim() !== ""
		if (filled) vd[f.key] = v
		else if (f.required) missing.push(f.label)
	}
	if (missing.length) {
		toast.error(`${labels.gateRequiredMissing}: ${missing.join(", ")}`)
		return
	}
	generateRes
		.submit({
			booking: detail.value.booking,
			selected_codes: JSON.stringify(selected.value),
			vehicle_data: JSON.stringify(vd),
			request_id: requestId.value,
		})
		.then((data) => {
			// Next truck is already at the barrier: drop straight back to the scan box and
			// let the toast — held a beat longer, since the panel it replaces is gone —
			// carry the confirmation and the bon number.
			reset()
			toast.success(data.order_name || data.order || labels.gateGenerated, {
				title: labels.gateGenerated,
				duration: 5000,
			})
		})
		.catch((err) => {
			toast.error(err?.messages?.[0] || err?.message || labels.error)
		})
}

// --- Camera QR scanner (html5-qrcode) ---
async function startScan() {
	scanErr.value = ""
	scanning.value = true
	await nextTick()
	try {
		qrScanner = new Html5Qrcode("gate-reader")
		await qrScanner.start(
			{ facingMode: "environment" },
			{ fps: 10, qrbox: { width: 240, height: 240 } },
			onScanDetected,
			() => {}, // per-frame decode miss — ignore
		)
	} catch (e) {
		scanErr.value = labels.gateScanError
		stopScan()
	}
}

function onScanDetected(text) {
	if (!qrScanner) return // guard against repeat success callbacks
	stopScan() // nulls qrScanner synchronously so this fires exactly once
	code.value = (text || "").trim()
	doLookup()
}

async function stopScan() {
	const scanner = qrScanner
	qrScanner = null
	scanning.value = false
	if (scanner) {
		try {
			await scanner.stop()
			scanner.clear()
		} catch (e) {
			/* already stopped */
		}
	}
}

onBeforeUnmount(stopScan)

function reset() {
	stopScan()
	showVehicleForm.value = false
	code.value = ""
	detail.value = null
	selected.value = []
	nextTick(() => scanInput.value && scanInput.value.focus())
}
</script>
