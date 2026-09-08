<template>
	<!-- One column while the operator is still picking containers, two once the truck form
	     opens — a permanently split screen would leave half of it empty for the half of the
	     job that is just scanning. -->
	<div class="mx-auto w-full max-w-lg" :class="step === 'container' ? '' : 'md:max-w-5xl'">
		<!-- Page header. The direction chip is READ, never chosen: a booking already knows
		     whether its tank is coming in or going out, and the operator scanning it is
		     reporting a truck at the barrier, not deciding what the truck is doing. The old
		     in/out switch could only ever disagree with the booking. -->
		<div class="mb-4 flex items-center justify-between gap-2">
			<div class="flex min-w-0 items-center gap-2">
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

		<div class="grid gap-4 md:items-start" :class="step === 'container' ? '' : 'md:grid-cols-2'">
			<!-- LEFT — step 1. On a handset only one pane is on screen at a time; on a desk
			     monitor the booking stays visible next to the form, which is how the operator
			     checks the plate against the container they just ticked. -->
			<div class="space-y-4" :class="step === 'container' ? '' : 'hidden md:block'">
				<!-- The one screen in the app that genuinely cannot work offline, so it says so up
				     front instead of letting the operator scan and fail. Explained rather than just
				     flagged: "no internet" invites a retry, "the booking's payment status has to be
				     checked live" tells them to go and find signal. -->
				<section
					v-if="!link.online"
					class="oak-card flex items-start gap-3 border-amber-200 bg-amber-50 p-4"
				>
					<Icon name="cloud-off" :size="20" class="mt-0.5 shrink-0 text-amber-600" />
					<div>
						<p class="font-bold text-amber-900">{{ labels.gateNeedsOnline }}</p>
						<p class="mt-0.5 text-xs leading-relaxed text-amber-800">{{ labels.gateNeedsOnlineHint }}</p>
					</div>
				</section>

				<!-- Nothing looked up yet: the scan box is the whole screen. Once a booking is on
				     screen it shrinks to the one line that still matters — which code this is, and
				     how to get back out of it. -->
				<section v-if="!valid" class="oak-section space-y-3">
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

				<section v-else class="oak-card flex items-center gap-2 px-3.5 py-2.5">
					<Icon name="maximize" :size="16" class="shrink-0 text-gray-400" />
					<p class="min-w-0 flex-1 truncate text-sm font-bold text-gray-900">{{ detail.booking }}</p>
					<button class="oak-link inline-flex shrink-0 items-center gap-1 text-xs" @click="reset">
						<Icon name="rotate-ccw" :size="13" /> {{ labels.gateRescan }}
					</button>
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
					<!-- Whose booking this is, in four facts. The eleven-row table this replaced was
					     read by nobody: the gate needs the customer, the cargo and the day, and the
					     rest is one tap away under "Rincian booking". -->
					<section class="oak-card animate-slide-up overflow-hidden">
						<div class="h-1.5 w-full" :class="dirMeta.bar"></div>
						<div class="p-4">
							<div class="flex items-start justify-between gap-3">
								<p class="min-w-0 truncate text-base font-extrabold text-gray-900">
									{{ detail.customer_name || detail.customer }}
								</p>
								<span class="oak-chip shrink-0" :class="statusChip">
									<Icon name="check-circle" :size="12" />{{ detail.booking_status }}
								</span>
							</div>
							<dl class="mt-3 grid grid-cols-2 gap-x-3 gap-y-3 text-sm">
								<div v-for="f in bookingFacts" :key="f.k" class="min-w-0">
									<dt class="text-[11px] uppercase tracking-wide text-gray-400">{{ f.k }}</dt>
									<dd class="truncate font-semibold text-gray-800">{{ f.v }}</dd>
								</div>
							</dl>
							<button
								class="oak-link mt-3 inline-flex items-center gap-1 text-xs"
								@click="detailsOpen = !detailsOpen"
							>
								<Icon :name="detailsOpen ? 'chevron-up' : 'chevron-down'" :size="14" />
								{{ labels.gateSectionBooking }}
							</button>
							<dl v-if="detailsOpen" class="mt-2 space-y-1.5 border-t border-gray-100 pt-2 text-sm">
								<div v-for="row in panelRows" :key="row.k" class="flex justify-between gap-3">
									<dt class="shrink-0 text-gray-500">{{ row.k }}</dt>
									<dd class="text-right font-semibold text-gray-800">{{ row.v }}</dd>
								</div>
							</dl>
						</div>
					</section>

					<!-- Gate blocked. Each reason sends the operator to a different person — a single
					     "tidak bisa" would send every one of them to the same wrong one. -->
					<section
						v-if="detail.block_reason"
						class="animate-slide-up rounded-2xl border border-red-200 bg-red-50 p-4"
					>
						<p class="flex items-center gap-2 font-semibold text-red-800">
							<Icon name="alert-triangle" :size="18" /> {{ labels.gateBlockedTitle }}
						</p>
						<p class="mt-1 pl-7 text-sm text-red-700">
							{{ BLOCK_TEXT[detail.block_reason] || labels.gateNotSubmitted }}
						</p>
						<p v-if="detail.payment_blocked && detail.sales_invoice" class="mt-1 pl-7 text-sm text-red-700">
							{{ labels.gateInvoiceNo }}: <span class="font-semibold">{{ detail.sales_invoice }}</span>
						</p>
					</section>

					<!-- Container list: existing bon shown per container; else selectable (max 2).
					     Hidden entirely while the gate is blocked — only the keterangan shows. -->
					<section v-if="!detail.block_reason" class="animate-slide-up space-y-2">
						<div class="flex items-end justify-between gap-2">
							<div class="min-w-0">
								<p class="oak-section-title">{{ labels.gateContainers }}</p>
								<p class="text-xs text-gray-400">{{ labels.gateSelectMax2 }}</p>
							</div>
							<span class="shrink-0 text-xs font-semibold" :class="selected.length ? 'text-brand-600' : 'text-gray-400'">
								{{ fill(labels.gateSelectedCount, { n: selected.length, max: MAX_PER_BON }) }}
							</span>
						</div>
						<p v-if="!detail.containers.length" class="oak-card p-6 text-center text-sm text-gray-400">
							{{ labels.gateNoContainers }}
						</p>
						<!-- Outbound, nothing free to load: the container list is five disabled rows and
						     the answer is underneath them. Lead with the work instead. -->
						<div v-else-if="outAllHeld" class="oak-card overflow-hidden">
							<div class="bg-red-50 px-4 py-3">
								<p class="flex items-center gap-1.5 text-sm font-semibold text-red-800">
									<Icon name="alert-triangle" :size="14" /> {{ labels.gateOutNoneReady }}
								</p>
								<p class="mt-1 text-xs text-red-700">{{ labels.gateOutNoneReadyHint }}</p>
							</div>
							<ul class="divide-y divide-gray-100">
								<li v-for="c in outHeld" :key="c.booking_code" class="px-4 py-3">
									<p class="truncate font-semibold text-gray-900">{{ c.container_no || c.container }}</p>
									<ul class="mt-1 space-y-0.5">
										<li v-for="o in holds(c)" :key="o.name" class="flex items-center gap-1.5 text-xs text-red-800">
											<Icon name="alert-circle" :size="12" class="shrink-0" />
											<span class="font-semibold">{{ o.label }}</span>
											<span class="truncate">{{ o.name }}</span>
											<span class="oak-chip bg-paper/70 text-[10px] text-red-700">{{ o.status }}</span>
										</li>
									</ul>
								</li>
							</ul>
						</div>
						<template v-else>
							<!-- Some are free, some are not: the count says so up front, and each held row
							     is disabled and marked rather than quietly unticked. -->
							<p
								v-if="isOut && outHeld.length"
								class="oak-card flex items-center gap-1.5 px-4 py-2 text-xs text-amber-800"
							>
								<Icon name="alert-triangle" :size="14" class="shrink-0" />
								<span><b>{{ outReady.length }}</b> dari <b>{{ detail.containers.length }}</b> {{ labels.gateOutReadyCount }}</span>
							</p>
							<!-- One tappable card per container rather than a checkbox in a list row: this
							     is pressed with a glove on, in daylight, against the number painted on the
							     tank — and the whole card being the target is the difference between one
							     tap and three. -->
							<ul class="space-y-2">
								<li v-for="c in detail.containers" :key="c.booking_code">
									<component
										:is="pickable(c) ? 'button' : 'div'"
										class="oak-card block w-full p-3 text-left transition"
										:class="[
											selected.includes(c.booking_code)
												? 'border-brand-500 bg-brand-50 ring-1 ring-brand-500'
												: '',
											pickable(c) ? 'oak-press' : 'opacity-90',
										]"
										@click="pickable(c) && toggle(c)"
									>
										<div class="flex items-center gap-3">
											<span
												v-if="selectable(c)"
												class="oak-icon-tile h-5 w-5 shrink-0 rounded-md border-2 transition"
												:class="
													selected.includes(c.booking_code)
														? 'border-brand-600 bg-brand-600 text-white'
														: 'border-gray-300 text-transparent'
												"
											>
												<Icon name="check" :size="13" :stroke="3" />
											</span>
											<span v-else class="oak-icon-tile h-8 w-8 shrink-0 bg-gray-100 text-gray-400">
												<Icon name="package" :size="16" />
											</span>
											<div class="min-w-0 flex-1">
												<p
													class="truncate font-semibold"
													:class="c.container_no || c.container ? 'text-gray-900' : 'text-gray-400'"
												>
													{{ c.container_no || c.container || labels.gateNoNumber }}
												</p>
												<p class="truncate text-xs text-gray-500">
													{{ c.container_no || c.container ? c.code_state : labels.gateNoNumberHint }}
												</p>
											</div>
											<!-- Gate-out readiness. Only meaningful on the way out: on the way IN the
											     tank isn't in the yard yet, so open work is not this gate's business. -->
											<span
												v-if="!c.container_no && !c.container"
												class="oak-chip shrink-0 bg-amber-100 text-amber-800"
											>
												{{ labels.gateNoNumberChip }}
											</span>
											<span
												v-else-if="isOut && !c.order && holds(c).length"
												class="oak-chip shrink-0 bg-red-100 text-red-800"
											>
												<Icon name="alert-triangle" :size="12" /> {{ labels.gateOutUnready }}
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
													<span class="oak-chip bg-paper/70 text-[10px] text-red-700">{{ o.status }}</span>
												</li>
											</ul>
										</div>
									</component>
								</li>
							</ul>
						</template>

						<button
							v-if="!outAllHeld"
							class="oak-btn oak-btn-primary w-full"
							:disabled="!selected.length"
							@click="openGenerate"
						>
							{{ labels.gateNext }}
							<Icon name="arrow-right" :size="18" />
						</button>
						<p v-if="generateError" class="flex items-center gap-1.5 text-sm text-red-600">
							<Icon name="alert-circle" :size="15" /> {{ generateError }}
						</p>
					</section>
				</template>
			</div>

			<!-- RIGHT — step 2 (the truck) and step 3 (the bon). Same column, because they are
			     the same conversation with the same driver. -->
			<div v-if="step !== 'container'" class="oak-card animate-slide-up overflow-hidden md:sticky md:top-[calc(var(--oak-header-h,56px)+1rem)]">
				<div class="flex items-center gap-2 border-b border-gray-100 px-3 py-2.5">
					<button
						v-if="step === 'vehicle'"
						class="rounded-lg p-1.5 text-gray-500 transition hover:bg-gray-100"
						:aria-label="labels.backBtn || labels.cancelBtn"
						@click="closeVehicleForm"
					>
						<Icon name="arrow-left" :size="18" />
					</button>
					<p class="min-w-0 flex-1 truncate font-bold text-gray-900">
						{{ step === "vehicle" ? labels.gateStepVehicle : labels.gateDoneTitle }}
					</p>
					<p class="shrink-0 truncate text-xs font-semibold text-gray-500">{{ selectedLabels }}</p>
				</div>

				<!-- Where the operator is in the flow. Three steps, and the one thing it must never
				     do is let them think the bon exists before it does — so step 3 only lights up
				     once the server has answered with a number. -->
				<ol class="flex items-center gap-2 border-b border-gray-100 px-3 py-2.5 text-[11px] font-semibold">
					<li v-for="(s, i) in steps" :key="s.key" class="flex min-w-0 items-center gap-2">
						<span
							class="oak-icon-tile h-5 w-5 shrink-0 rounded-full text-[10px]"
							:class="
								s.state === 'done'
									? 'bg-leaf-600 text-white'
									: s.state === 'active'
										? 'bg-brand-600 text-white'
										: 'bg-gray-100 text-gray-400'
							"
						>
							<Icon v-if="s.state === 'done'" name="check" :size="12" :stroke="3" />
							<template v-else>{{ i + 1 }}</template>
						</span>
						<span class="truncate" :class="s.state === 'upcoming' ? 'text-gray-400' : 'text-gray-700'">
							{{ s.label }}
						</span>
						<span v-if="i < steps.length - 1" class="h-px w-3 shrink-0 bg-gray-200"></span>
					</li>
				</ol>

				<!-- Step 2 — the truck and its driver -->
				<div v-if="step === 'vehicle'" class="space-y-3 p-3">
					<p
						v-if="prefilled.length"
						class="flex items-start gap-2 rounded-xl bg-blue-50 px-3 py-2 text-xs font-semibold text-blue-700"
					>
						<Icon name="zap" :size="14" class="mt-px shrink-0" />
						{{ labels.gateAutofill }}
					</p>

					<div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
						<div v-for="f in primaryFields" :key="f.key" :class="f.wide ? 'sm:col-span-2' : ''">
							<label class="oak-label flex items-center justify-between gap-2">
								<span>
									{{ f.label }}
									<span v-if="f.required" class="text-red-500">*</span>
								</span>
								<!-- Says WHERE a filled-in value came from. A plate that arrived from the
								     booking looks exactly like one the operator typed, and the two need
								     different amounts of checking before the bon is issued. -->
								<span
									v-if="prefilled.includes(f.key)"
									class="inline-flex items-center gap-1 font-normal normal-case text-gray-400"
								>
									<Icon name="clock" :size="11" />{{ labels.gateFromBooking }}
								</span>
							</label>
							<GateField :field="f" v-model="vehicle[f.key]" />
						</div>
					</div>

					<!-- Everything the bon can carry but the barrier does not need typed. Collapsed by
					     default and showing its VALUES while collapsed: most of it arrives from the
					     booking already, so the operator's job is to notice a wrong one, not to fill
					     them in. -->
					<div class="rounded-xl border border-gray-200">
						<button
							class="flex w-full items-center gap-2 px-3 py-2.5 text-left"
							@click="extraOpen = !extraOpen"
						>
							<Icon :name="extraOpen ? 'chevron-down' : 'chevron-right'" :size="16" class="shrink-0 text-gray-400" />
							<span class="flex-1 text-sm font-semibold text-gray-800">{{ labels.gateExtra }}</span>
							<span class="oak-chip shrink-0 bg-gray-100 text-gray-500">{{ labels.optional }}</span>
						</button>
						<div v-if="extraOpen" class="grid grid-cols-1 gap-3 border-t border-gray-100 p-3 sm:grid-cols-2">
							<div v-for="f in extraFields" :key="f.key" :class="f.wide ? 'sm:col-span-2' : ''">
								<label class="oak-label">{{ f.label }}</label>
								<GateField :field="f" v-model="vehicle[f.key]" />
							</div>
						</div>
						<dl v-else class="grid grid-cols-2 gap-x-3 gap-y-2 border-t border-gray-100 p-3 text-sm">
							<div v-for="f in extraSummary" :key="f.k" class="min-w-0">
								<dt class="text-[11px] uppercase tracking-wide text-gray-400">{{ f.k }}</dt>
								<dd class="truncate font-semibold text-gray-800">{{ f.v }}</dd>
							</div>
						</dl>
					</div>

					<p v-if="generateError" class="flex items-center gap-1.5 text-sm text-red-600">
						<Icon name="alert-circle" :size="15" /> {{ generateError }}
					</p>

					<div class="flex gap-2 pt-1">
						<button class="oak-btn oak-btn-secondary flex-1" @click="closeVehicleForm">
							{{ labels.backBtn || labels.cancelBtn }}
						</button>
						<button class="oak-btn oak-btn-primary flex-[2]" :disabled="generateRes.loading" @click="doGenerate">
							<Icon v-if="!generateRes.loading" name="file-plus" :size="18" />
							{{ generateRes.loading ? "…" : labels.gateGenerate }}
						</button>
					</div>
				</div>

				<!-- Step 3 — the bon exists. Its number stays on screen instead of riding out on a
				     toast: it is what the operator reads back to the driver and what they search
				     for when the printer jams. -->
				<div v-else class="space-y-3 p-4 text-center">
					<span class="oak-icon-tile mx-auto h-12 w-12 bg-leaf-50 text-leaf-600">
						<Icon name="check-circle" :size="26" />
					</span>
					<div>
						<p class="font-bold text-gray-900">{{ labels.gateGenerated }}</p>
						<p class="mt-1 text-xl font-extrabold tracking-tight text-gray-900">{{ lastOrder }}</p>
						<p class="mt-1 text-xs text-gray-500">{{ labels.gateDoneHint }}</p>
					</div>
					<div class="flex gap-2 pt-1">
						<router-link to="/gate/history" class="oak-btn oak-btn-secondary flex-1">
							<Icon name="clock" :size="16" /> {{ labels.navHistory }}
						</router-link>
						<button class="oak-btn oak-btn-primary flex-[2]" @click="reset">
							<Icon name="maximize" :size="16" /> {{ labels.gateDoneNext }}
						</button>
					</div>
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
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue"
import { useRoute } from "vue-router"
import { createResource } from "frappe-ui"
import { Html5Qrcode } from "html5-qrcode"
import { labels, gateDirection } from "@/utils/labels"
import { toast } from "@/utils/toast"
import Icon from "@/components/Icon.vue"
import GateField from "@/components/GateField.vue"
import SkeletonDetail from "@/components/SkeletonDetail.vue"
import { link } from "@/data/link"
import { uid } from "@/utils/idb"
import { useDismissOnBack } from "@/utils/backstack"
import { fmtDateShort } from "@/utils/surveyStatus"

// Keyed by the server's `block_reason` (container_depot.order_generation.payment_block_reason
// plus the gate's own "not_submitted"). A map rather than a ternary because each reason sends
// the operator to a different person: the cashier, or the admin who confirms the booking.
// `not_invoiced` (TOP belum ditagih) was a third one until 2026-09-07 — the server does not
// hold a credit booking for its invoice any more, so it can no longer arrive.
const BLOCK_TEXT = {
	cash_unpaid: labels.gatePayBlocked,
	not_submitted: labels.gateNotSubmitted,
}

const code = ref("")
const scanInput = ref(null)
const detail = ref(null)
const selected = ref([])
// Where the operator is: picking containers, filling the truck in, or looking at the bon
// that came back. One ref rather than a modal flag, because step 3 is a screen of its own
// now — the bon number used to ride out on a toast, which is unreadable from a driver's
// window and gone by the time anyone needs it.
const step = ref("container") // "container" | "vehicle" | "done"
const lastOrder = ref("")
const vehicle = ref({})
// Which keys openGenerate() filled from the booking. Shown per field, because a plate the
// booking supplied and one the operator typed look identical and need different amounts of
// checking before a bon is issued.
const prefilled = ref([])
const extraOpen = ref(false)
const detailsOpen = ref(false)

// Two per bon is the server's rule (api.gate_generate_order), repeated here only so the
// counter and the disabled state can say so before the operator finds out on submit.
const MAX_PER_BON = 2

function fill(tpl, vars) {
	return Object.entries(vars).reduce((acc, [k, v]) => acc.replace(`{${k}}`, v), tpl)
}
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
	() => step.value === "vehicle",
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

// EMKL / Angkutan and Shipper pickers. Both are Links to Customer on both bon doctypes,
// so a typed name that isn't in the master is refused at insert — the gate picks from the
// master instead. One request feeds both: they name different parties (the EMKL trucks the
// tank, the Shipper is the factory that ordered it) but choose from the same Customer list,
// and EMKL-flagged customers are grouped first so the two are easy to tell apart.
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
const partyField = (key, label) => ({
	key,
	label,
	type: "select",
	options: shipperOptions.value,
	optionValue: shipperValue,
	optionLabel: shipperLabel,
	groupBy: shipperGroup,
	emptyLabel: labels.gateShipperEmpty,
})
const emklField = computed(() => partyField("emkl", labels.vEmkl))
const shipperField = computed(() => partyField("shipper", labels.vShipper))

const vehicleFields = computed(() => {
	if (!detail.value) return []
	if (detail.value.direction === "Tank In")
		return [
			{ key: "truck_plate", label: labels.truckNo, inputType: "text", required: true, wide: true },
			{ key: "driver", label: labels.driverName, inputType: "text", required: true, wide: true },
			{ key: "driver_phone", label: labels.driverPhone, inputType: "tel", required: true },
			{ key: "ro", label: labels.vRo, inputType: "text" },
			{ key: "condition", label: labels.vCondition, type: "select", options: ["EMPTY CLEAN", "EMPTY DIRTY", "LADEN"], required: true },
			{ key: "cargo", label: labels.cargo, type: "datalist", options: cargoOptions.value },
			{ key: "tanggal_bongkar_actual", label: labels.vDateBongkar, inputType: "date" },
			emklField.value,
			shipperField.value,
			{ key: "ex_vessel", label: labels.exVessel, inputType: "text" },
			{ key: "remarks", label: labels.eirRemarks, type: "textarea", wide: true },
		]
	return [
		{ key: "truck_plate", label: labels.truckNo, inputType: "text", required: true, wide: true },
		{ key: "driver_name", label: labels.driverName, inputType: "text", required: true, wide: true },
		{ key: "driver_phone", label: labels.driverPhone, inputType: "tel", required: true },
		{ key: "ro", label: labels.vRo, inputType: "text" },
		{ key: "destination", label: labels.vDestination, inputType: "text" },
		{ key: "tanggal_muat", label: labels.vDateMuat, inputType: "date" },
		emklField.value,
		shipperField.value,
		{ key: "remarks", label: labels.eirRemarks, type: "textarea", wide: true },
	]
})

// The barrier needs four answers — plate, driver, phone, and (inbound) the tank's
// condition. Everything else the bon can carry is real but not urgent, and most of it
// arrives from the booking already, so it goes behind one disclosure instead of turning
// step 2 into a ten-field wall between the driver and the barrier.
const primaryFields = computed(() => vehicleFields.value.filter((f) => f.required))
const extraFields = computed(() => vehicleFields.value.filter((f) => !f.required))

// What the collapsed disclosure shows: the optional values as they stand, so the operator
// can spot a wrong one without opening anything. Empty ones read as "—" rather than being
// dropped — a missing Ex vessel is information too.
const extraSummary = computed(() =>
	extraFields.value.map((f) => ({
		k: f.label,
		v: f.inputType === "date" ? fmtDateShort(vehicle.value[f.key]) : vehicle.value[f.key] || "—",
	}))
)

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
// Cargo is a property of each booking LINE, not of the booking — one voucher can carry two
// tanks of different product. So the card shows what is actually on this booking, joined,
// rather than picking the first line's cargo and calling it the booking's.
const bookingCargo = computed(() =>
	[...new Set((detail.value?.containers || []).map((c) => c.line?.cargo).filter(Boolean))].join(", ")
)

// The four facts the barrier actually reads off the booking, in the order they are read:
// whose tank, which depot it belongs to, what is in it, and which day it was planned for.
// Everything else moved behind "Rincian booking" — an eleven-row table on the first screen
// of a two-minute job is a table nobody reads.
const bookingFacts = computed(() => {
	if (!valid.value) return []
	const d = detail.value
	return [
		{ k: labels.principal, v: d.principal_name || d.principal || "—" },
		{ k: `${labels.branch} / ${labels.depot}`, v: [d.branch, d.depot].filter(Boolean).join(" · ") || "—" },
		{ k: labels.cargo, v: bookingCargo.value || "—" },
		{ k: isOut.value ? labels.vDateMuat : labels.vDateBongkar, v: fmtDateShort(d.plan_date) },
	]
})

// Confirmed bookings are the normal case and get the quiet green; anything else is a state
// the operator may need to think about, so it is amber rather than pretending to be fine.
const statusChip = computed(() =>
	detail.value?.booking_status === "Confirmed"
		? "bg-leaf-50 text-leaf-700"
		: "bg-amber-50 text-amber-700"
)

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

// The full booking table, flattened: inside a disclosure the group headings cost a line
// each and separate nothing the operator is scanning for.
const panelRows = computed(() => panelGroups.value.flatMap((g) => g.rows))

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

// A booking is routinely collected a couple of tanks at a time, and an outbound booking may
// now be submitted while the yard is still working (the readiness gate moved to here and to
// the bon). So "5 di booking, 3 bisa jalan sekarang" is the normal case, not the exception —
// and it is the first thing the gate needs to know, before it starts ticking boxes.
const outHeld = computed(() =>
	isOut.value ? (detail.value?.containers || []).filter((c) => !c.order && holds(c).length) : [],
)
const outReady = computed(() =>
	isOut.value ? (detail.value?.containers || []).filter((c) => selectable(c)) : [],
)
// Nothing to tick: the checkbox list would be a list of disabled rows with the real answer
// buried under them. Show the work instead — that IS the answer.
const outAllHeld = computed(
    () => isOut.value && !!outHeld.value.length && !outReady.value.length,
)

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
	else if (selected.value.length < MAX_PER_BON) selected.value.push(c.booking_code)
}

// The whole card is the tap target, so it has to know when a tap would do nothing: a
// container that cannot go on a bon at all, or the third tick on a two-container bon.
function pickable(c) {
	return (
		selectable(c) &&
		!detail.value?.block_reason &&
		(selected.value.includes(c.booking_code) || selected.value.length < MAX_PER_BON)
	)
}

function doLookup() {
	if (!code.value) return
	lookupRes.submit({ code: code.value })
}

// Beranda's search box hands its code over as `?q=`, and its scan button as `?scan=1`.
// Everything an operator types on the home screen — a booking code, an order code, a tank
// number — is a gate lookup, so the box there is a shortcut into this screen rather than a
// search of its own: it arrives here already typed, and the answer appears where the buttons
// that act on it live.
const route = useRoute()
onMounted(() => {
	const q = String(route.query.q || "").trim()
	if (q) {
		code.value = q.toUpperCase()
		doLookup()
		return
	}
	if (route.query.scan) startScan()
})

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
		// Only the EMKL falls back to the booking's Customer (Bill To). The Shipper is the
		// factory that ordered the haul — a different party, so it comes from the booking
		// line or stays blank rather than inheriting the payer's name.
		emkl: line.emkl || detail.value.customer || "",
		shipper: line.shipper || "",
		// The booking's own Plan Date wins over today, in both directions: a booking prepared
		// a week ahead already says which day it is for, and the gate is where that day
		// arrives — not where it is decided again. Read off the booking, not the line: the
		// line carries the realisation, which is the date this bon is about to produce.
		tanggal_bongkar_actual: detail.value.plan_date || today,
		tanggal_muat: detail.value.plan_date || today,
		remarks: "",
	}
	// One id per intended bon, minted when the form opens rather than when Generate is
	// pressed. That is the whole point: on a slow link the operator presses Generate, sees
	// nothing happen, and presses it again — and the second press has to be recognised as the
	// same bon. An id minted per click would issue two. See ess/idempotency.py.
	requestId.value = uid()
	// Everything that arrived from the booking rather than from the operator, recorded once
	// here so the form can label those fields. Read after the object above is built, so a
	// field the booking left empty is correctly NOT claimed as prefilled.
	prefilled.value = Object.keys(vehicle.value).filter((k) => {
		const v = vehicle.value[k]
		return v != null && String(v).trim() !== ""
	})
	extraOpen.value = false
	step.value = "vehicle"
}

function closeVehicleForm() {
	step.value = "container"
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
			// Step 3, not a toast and not a reset. The bon number is what the operator reads
			// back to the driver and what they search for when the printer jams, so it stays
			// on screen until they say they are done with it — and the next truck is one tap
			// ("Scan truk berikutnya") away, which is the same single press the reset was.
			lastOrder.value = data.order_name || data.order || ""
			step.value = "done"
		})
		.catch((err) => {
			toast.error(err?.messages?.[0] || err?.message || labels.error)
		})
}

// The three dots at the top of the right pane. Step 3 is only ever "done" once the server
// has answered with a bon number — a stepper that lights up on submit tells the operator a
// bon exists while the request is still in the air.
const steps = computed(() => {
	const order = ["container", "vehicle", "done"]
	const at = order.indexOf(step.value)
	return [
		{ key: "container", label: labels.gateStepContainer },
		{ key: "vehicle", label: labels.gateStepVehicle },
		{ key: "done", label: labels.gateStepDone },
	].map((s, i) => ({ ...s, state: i < at ? "done" : i === at ? "active" : "upcoming" }))
})

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
	step.value = "container"
	lastOrder.value = ""
	prefilled.value = []
	code.value = ""
	detail.value = null
	selected.value = []
	nextTick(() => scanInput.value && scanInput.value.focus())
}
</script>
