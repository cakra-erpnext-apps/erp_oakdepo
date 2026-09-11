<template>
	<div class="mx-auto w-full max-w-lg space-y-4 md:max-w-2xl">
		<!-- Header -->
		<div class="flex items-center justify-between gap-2">
			<div class="min-w-0">
				<h1 class="truncate text-xl font-extrabold tracking-tight text-gray-900">
					{{ labels.cleaningTitle }}
				</h1>
				<p v-if="order" class="truncate font-mono text-[11px] text-gray-500">
					{{ order.order_id }} · {{ order.container_no }}
				</p>
				<p v-else class="text-sm text-gray-500">{{ labels.cleaningOrdersHint }}</p>
			</div>
			<div class="flex shrink-0 items-center gap-2">
				<router-link v-if="!order" to="/cleaning/history" class="oak-btn oak-btn-secondary px-3 py-2">
					<Icon name="clock" :size="16" /> {{ labels.navHistory }}
				</router-link>
				<button v-if="order" class="oak-btn oak-btn-secondary px-3 py-2" @click="backToList">
					<Icon name="arrow-left" :size="16" /> {{ labels.cleaningBack }}
				</button>
			</div>
		</div>

		<!-- Submitted confirmation -->
		<section v-if="submitted" class="oak-card space-y-2 border-leaf-200 bg-leaf-50 p-4">
			<p class="font-bold text-leaf-700">
				<Icon name="check-circle" :size="18" /> {{ labels.cleaningSubmitted }}
			</p>
			<p class="font-mono text-sm text-gray-700">{{ submitted.order_id || submitted.name }}</p>
		</section>

		<!-- OPENING AN ORDER — placeholder while its detail is fetched. Without this the
		     worklist just sat there unchanged after a tap, which reads as a dead button. -->
		<SkeletonDetail v-if="detailPending" :cells="8" :sections="3" />

		<!-- The detail could not be fetched and there is no cached copy to fall back on. -->
		<section v-else-if="detailFailed" class="oak-card space-y-3 p-6 text-center">
			<span class="oak-icon-tile mx-auto h-12 w-12 bg-red-50 text-red-500">
				<Icon name="alert-triangle" :size="24" />
			</span>
			<p class="text-sm text-gray-600">{{ detailError }}</p>
			<div class="flex gap-2">
				<button class="oak-btn oak-btn-secondary flex-1" @click="backToList">{{ labels.cleaningBack }}</button>
				<button class="oak-btn oak-btn-primary flex-1" @click="retryDetail">{{ labels.retry }}</button>
			</div>
		</section>

		<!-- =================== WORKLIST ===================
		     Search, then Semua / Belum / Dikerjakan with counts, then one card per order.
		     The whole card is the tap target and it leads to the order's own screen — the
		     row used to carry its own "Mulai" shortcut, which started a wash from a list
		     where the tank's cargo history and services were not yet on screen. -->
		<template v-else-if="!order && !submitted">
			<div class="relative">
				<Icon
					name="search"
					:size="18"
					class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-gray-400"
				/>
				<input
					v-model="search"
					class="oak-input h-11 pl-10 uppercase"
					:placeholder="labels.cleaningOrdersSearch"
					autocapitalize="characters"
					autocorrect="off"
					autocomplete="off"
					spellcheck="false"
					enterkeyhint="search"
					@input="onSearchInput"
					@keyup.enter="reloadOrders"
				/>
			</div>

			<!-- Belum / Dikerjakan split: a Pending order is "belum" until Mulai moves it to
			     In_Progress; a completed one leaves the worklist entirely (Riwayat). -->
			<div class="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1">
				<button
					v-for="f in FILTERS"
					:key="f.key"
					class="oak-chip shrink-0 gap-1.5 px-3 py-1.5"
					:class="filter === f.key ? 'bg-brand-600 text-white' : 'bg-gray-100 text-gray-600'"
					@click="filter = f.key"
				>
					{{ f.label }}<span class="font-extrabold">{{ f.count }}</span>
				</button>
			</div>

			<SkeletonList v-if="ordersRes.loading && !orders.length" />
			<p v-else-if="!visibleOrders.length" class="oak-card py-8 text-center text-sm text-gray-400">
				{{ emptyText }}
			</p>
			<ul v-else class="space-y-2">
				<li v-for="o in visibleOrders" :key="o.name">
					<button class="oak-card oak-press flex w-full items-center gap-3 p-3 text-left" @click="openOrder(o)">
						<span
							class="oak-icon-tile h-9 w-9 shrink-0"
							:class="o.status === 'In_Progress' ? 'bg-amber-50 text-amber-600' : 'bg-brand-50 text-brand-600'"
						>
							<Icon name="droplet" :size="16" />
						</span>
						<div class="min-w-0 flex-1">
							<div class="flex items-center justify-between gap-2">
								<p class="truncate font-bold text-gray-900">{{ o.container_no || o.container }}</p>
								<span
									class="oak-chip shrink-0"
									:class="o.status === 'In_Progress' ? 'bg-amber-100 text-amber-800' : 'bg-gray-100 text-gray-600'"
								>
									{{ o.status === "In_Progress" ? labels.cleaningInProgress : labels.cleaningFilterTodo }}
								</span>
							</div>
							<!-- What it is and what it last carried: the two things the operator reads
							     before deciding which tank to take next. -->
							<p class="truncate text-[11px] text-gray-500">
								<span v-if="o.container_principal">{{ o.container_principal }} · </span>
								<template v-if="o.cleaning_type">{{ o.cleaning_type }} · </template>
								<template v-if="o.service_count">{{ o.service_count }} {{ labels.cleaningServicesCount }}</template>
								<template v-if="o.service_count && o.last_cargo"> · </template>
								<template v-if="o.last_cargo">ex {{ o.last_cargo }}</template>
							</p>
							<div class="mt-1 flex items-center gap-1.5">
								<LiftOnBadge :survey="o.target_survey_on" :target="o.target_lift_on" :urgent="o.target_urgent_on" />
							</div>
							<!-- Siapa yang sudah mencucinya. Cucian yang sudah dimulai tidak lagi
							     hilang dari daftar rekan, jadi "sedang dikerjakan" harus menyebut
							     oleh siapa — kalau tidak, orang kedua masuk ke form yang sama
							     tanpa tahu. -->
							<p v-if="o.assigned_to_name" class="mt-1 flex items-center gap-1 truncate text-[11px] text-gray-400">
								<Icon name="user" :size="11" class="shrink-0" />
								{{ labels.eirWorkedBy.replace("{name}", o.assigned_to_name) }}
							</p>
						</div>
						<Icon name="chevron-right" :size="16" class="shrink-0 text-gray-300" />
					</button>
				</li>
			</ul>

			<!-- Sent for review (Pending Review) — the field is done, Admin Ops still has to
			     check and Submit on the Desk. An order sitting here is work nobody is doing. -->
			<section v-if="reviewRes.loading || reviewItems.length" class="space-y-2">
				<div class="flex items-center gap-2 px-1">
					<Icon name="clock" :size="15" class="text-sky-500" />
					<p class="oak-section-title">{{ labels.cleaningReviewList }}</p>
					<span v-if="reviewItems.length" class="oak-chip bg-sky-100 text-sky-700">{{ reviewItems.length }}</span>
				</div>
				<ul v-if="reviewRes.loading && !reviewItems.length" class="space-y-2">
					<li v-for="n in 2" :key="n" class="oak-skeleton h-14 rounded-2xl"></li>
				</ul>
				<ul v-else class="space-y-2">
					<li v-for="r in reviewItems" :key="r.name">
						<div class="oak-card flex items-center gap-3 p-3">
							<button type="button" class="oak-press flex min-w-0 flex-1 items-center gap-3 text-left" @click="goFinished(r)">
								<span class="oak-icon-tile h-9 w-9 shrink-0 bg-sky-50 text-sky-600"><Icon name="clock" :size="16" /></span>
								<div class="min-w-0 flex-1">
									<p class="truncate font-bold text-gray-900">{{ r.container_no || r.container }}</p>
									<p class="truncate text-[11px] text-gray-500">
										<span v-if="r.container_principal">{{ r.container_principal }} · </span>{{ r.order_id || r.name }}
									</p>
								</div>
								<span class="oak-chip shrink-0 bg-sky-100 text-sky-800">{{ labels.cleaningStatusPendingReview }}</span>
							</button>
							<!-- Pulling it back is the operator's own fix — no Admin Ops needed — so it
							     stays on the row rather than only behind the detail. -->
							<button
								type="button"
								class="oak-btn oak-btn-secondary shrink-0 px-2.5 py-1.5 text-xs"
								:disabled="withdrawRes.loading"
								@click.stop="withdrawReview(r)"
							>
								{{ labels.cleaningWithdrawReview }}
							</button>
						</div>
					</li>
				</ul>
			</section>

			<!-- Finished (Completed / Cancelled) — the last few, with the full log behind Riwayat. -->
			<section class="space-y-2">
				<div class="flex items-center justify-between gap-2 px-1">
					<div class="flex items-center gap-2">
						<Icon name="check-circle" :size="15" class="text-leaf-600" />
						<p class="oak-section-title">{{ labels.cleaningCompleteList }}</p>
					</div>
					<router-link to="/cleaning/history" class="oak-link text-xs">{{ labels.cleaningListMore }}</router-link>
				</div>
				<ul v-if="doneRes.loading && !doneItems.length" class="space-y-2">
					<li v-for="n in 2" :key="n" class="oak-skeleton h-14 rounded-2xl"></li>
				</ul>
				<p v-else-if="!doneItems.length" class="oak-card py-4 text-center text-sm text-gray-400">
					{{ labels.cleaningCompleteEmpty }}
				</p>
				<ul v-else class="space-y-2">
					<li v-for="r in doneItems" :key="r.name">
						<button type="button" class="oak-card oak-press flex w-full items-center gap-3 p-3 text-left" @click="goFinished(r)">
							<span class="oak-icon-tile h-9 w-9 shrink-0 bg-leaf-50 text-leaf-600"><Icon name="droplet" :size="16" /></span>
							<div class="min-w-0 flex-1">
								<p class="truncate font-bold text-gray-900">{{ r.container_no || r.container }}</p>
								<p class="truncate text-[11px] text-gray-500">
									<span v-if="r.container_principal">{{ r.container_principal }} · </span>{{ r.order_id
									}}<span v-if="r.cleaning_end"> · {{ fmtDate(r.cleaning_end) }}</span>
								</p>
							</div>
							<span v-if="r.revision_requested" class="oak-chip shrink-0 bg-orange-100 text-orange-800">{{ labels.cleaningStatusRevision }}</span>
							<span
								class="oak-chip shrink-0"
								:class="r.status === 'Cancelled' ? 'bg-red-100 text-red-700' : 'bg-leaf-100 text-leaf-800'"
							>
								{{ r.status === "Cancelled" ? labels.cleaningStatusCancelled : labels.cleaningStatusCompleted }}
							</span>
							<Icon name="chevron-right" :size="16" class="shrink-0 text-gray-300" />
						</button>
					</li>
				</ul>
			</section>
		</template>

		<!-- =================== ONE ORDER ===================
		     The same screen before and after Mulai. What the tank IS — its spec, what it last
		     carried, which services were asked for — does not depend on whether the wash has
		     started, and it is exactly what the operator reads to decide whether to take the
		     job. Only the action at the bottom changes. -->
		<template v-if="order && !submitted">
			<!-- Rekan yang menyentuhnya terakhir — di atas kartu, sebelum apa pun diisi. -->
			<EditedBy :by="order.updated_by" :name="order.updated_by_name" :at="order.updated_on" />
			<section class="oak-card p-4">
				<div class="flex items-start justify-between gap-2">
					<div class="min-w-0">
						<p class="truncate text-lg font-extrabold text-gray-900">
							{{ order.container_no || order.container }}
						</p>
						<p class="truncate text-xs text-gray-500">
							<span v-if="order.client">{{ order.client }} · </span>{{ order.tank_type
							}}<template v-if="order.previous_cargo"> · ex {{ order.previous_cargo }}</template>
						</p>
					</div>
					<span class="oak-chip shrink-0" :class="orderChip.tone">{{ orderChip.label }}</span>
				</div>
				<p v-if="order.inspection" class="mt-1 font-mono text-[11px] text-gray-400">
					{{ labels.cleaningRefEir }}: {{ order.inspection }}
				</p>
				<p v-if="order.reff_doc" class="font-mono text-[11px] text-gray-400">
					{{ labels.reffDoc }}: {{ order.reff_doc }}
				</p>

				<!-- Where the filling-in stands. All three parts already existed; the chips only
				     say which one is still empty without scrolling to the bottom to find out. -->
				<div v-if="started" class="mt-3 flex flex-wrap gap-1.5 border-t border-gray-100 pt-3">
					<span
						v-for="s in steps"
						:key="s.label"
						class="oak-chip"
						:class="s.done ? 'bg-leaf-50 text-leaf-700' : 'bg-gray-100 text-gray-500'"
					>
						<Icon :name="s.done ? 'check-circle' : 'circle'" :size="12" />{{ s.label }}
					</span>
				</div>
			</section>

			<!-- What Admin Ops asked for. Read-only on purpose: the services are what the owner
			     is billed for, and the operator washing the tank does not price the job. -->
			<section class="oak-card space-y-2 p-4">
				<p class="oak-section-title">{{ labels.cleaningRequested }}</p>
				<div v-if="order.cleaning_services && order.cleaning_services.length" class="flex flex-wrap gap-1.5">
					<span v-for="s in order.cleaning_services" :key="s.item_code" class="oak-chip bg-brand-100 text-brand-700">
						{{ s.item_name || s.item_code }}
					</span>
				</div>
				<p v-else class="text-sm text-gray-400">{{ labels.cleaningNoMethod }}</p>
				<p class="text-[11px] text-gray-400">
					<template v-if="order.cleaning_type">{{ order.cleaning_type }} · </template>
					{{ (order.cleaning_services || []).length }} {{ labels.cleaningServicesCount }}
				</p>
			</section>

			<!-- Instruksi Cleaning — free text Admin Ops left on the order (read-only). -->
			<section v-if="order.cleaning_instructions" class="oak-card space-y-2 p-4">
				<p class="oak-section-title">{{ labels.cleaningInstructions }}</p>
				<p class="whitespace-pre-line text-sm text-gray-800">{{ order.cleaning_instructions }}</p>
			</section>

			<!-- Tank spec -->
			<section class="oak-card p-4">
				<p class="oak-section-title mb-2">{{ labels.cleaningTankDetails }}</p>
				<dl class="grid grid-cols-2 gap-x-3 gap-y-3 text-sm">
					<div v-for="cell in headerCells" :key="cell.label" class="min-w-0">
						<dt class="text-[11px] uppercase tracking-wide text-gray-400">{{ cell.label }}</dt>
						<dd class="truncate font-semibold text-gray-800">{{ cell.value || "—" }}</dd>
					</div>
					<!-- Satu-satunya sel yang bisa ditulis: tanggal uji tank, milik master. -->
					<LastTestField
						v-model="order.last_test_date"
						:container="order.container"
					/>
				</dl>
			</section>

			<!-- Cargo history -->
			<section class="oak-card p-4">
				<p class="oak-section-title mb-2">{{ labels.cleaningCargoHistory }}</p>
				<ul v-if="order.cargo_history && order.cargo_history.length" class="divide-y divide-gray-100 text-sm">
					<li v-for="(h, i) in order.cargo_history" :key="i" class="flex justify-between gap-2 py-1.5">
						<span class="truncate font-semibold text-gray-800">{{ h.cargo }}</span>
						<span class="shrink-0 text-xs text-gray-400">{{ h.date }}</span>
					</li>
				</ul>
				<p v-else class="text-sm text-gray-400">{{ labels.cleaningNoCargoHistory }}</p>
			</section>

			<!-- NOT STARTED: one action, and what pressing it records. -->
			<template v-if="!started">
				<template v-if="canStart">
					<button class="oak-btn oak-btn-primary w-full py-3 text-base" @click="startCurrent">
						<Icon name="play" :size="18" /> {{ labels.cleaningStartFull }}
					</button>
					<p class="text-center text-xs text-gray-400">{{ labels.cleaningStartAuto }}</p>
				</template>
				<!-- Already sent for review, or already finished. The server refuses a second
				     start (cleaning.start_cleaning), so offering the button here would only ever
				     produce an error message; the record is what the operator wants instead. -->
				<button
					v-else
					type="button"
					class="oak-card oak-press flex w-full items-center gap-3 p-4 text-left"
					@click="goFinished(order)"
				>
					<span class="oak-icon-tile h-9 w-9 shrink-0 bg-sky-50 text-sky-600">
						<Icon name="clock" :size="16" />
					</span>
					<span class="min-w-0 flex-1 text-sm font-semibold text-gray-800">
						{{ order.status === "Pending Review" ? labels.cleaningStatusPendingReview : labels.cleaningStatusCompleted }}
					</span>
					<Icon name="chevron-right" :size="16" class="shrink-0 text-gray-300" />
				</button>
			</template>

			<!-- STARTED: the three things the operator fills in. -->
			<template v-else>
				<!-- Foto QC -->
				<section class="oak-card space-y-3 p-4">
					<p class="oak-section-title">{{ labels.cleaningQcPhotos }}</p>

					<!-- Thumbnails (3-up, square tap-friendly tiles) + inline "add" tile -->
					<div class="grid grid-cols-3 gap-2">
						<div v-for="(p, i) in qcPhotos" :key="i" class="relative aspect-square">
							<img :src="photoSrc(p.photo)" class="h-full w-full rounded-lg border border-gray-200 object-cover" />
							<button
								type="button"
								class="absolute right-1 top-1 flex h-8 w-8 items-center justify-center rounded-full bg-black/70 text-white shadow active:bg-black"
								:aria-label="labels.remove || 'Hapus'"
								@click="removeQcPhoto(i)"
							>
								<Icon name="x" :size="16" />
							</button>
							<PhotoMark :photo="p.photo" />
						</div>
						<PhotoTile v-for="it in photoQueue.items" :key="it.id" :item="it" tile="aspect-square w-full" />

						<!-- Two add tiles — the camera straight away, or the gallery for several at once -->
						<!-- The phone's own camera app, only ever reached as the fallback — see
						     utils/camera.js. -->
						<input
							ref="camInput"
							type="file"
							accept="image/*"
							capture="environment"
							multiple
							class="hidden"
							@change="onQcPhotos"
						/>
						<button
							type="button"
							class="flex aspect-square flex-col items-center justify-center gap-1 rounded-lg border-2 border-dashed border-brand-300 bg-brand-50 text-brand-600 active:bg-brand-100"
							:disabled="photoUploading"
							@click="openCameraOrFallback"
						>
							<Icon v-if="photoUploading" name="loader" :size="22" class="animate-spin" />
							<template v-else>
								<Icon name="camera" :size="22" />
								<span class="text-xs font-medium">{{ labels.photoCamera }}</span>
							</template>
						</button>
						<label
							class="flex aspect-square cursor-pointer flex-col items-center justify-center gap-1 rounded-lg border-2 border-dashed border-brand-300 bg-brand-50 text-brand-600 active:bg-brand-100"
						>
							<Icon v-if="photoUploading" name="loader" :size="22" class="animate-spin" />
							<template v-else>
								<Icon name="image" :size="22" />
								<span class="text-xs font-medium">{{ labels.photoGallery }}</span>
							</template>
							<input
								type="file"
								accept="image/*"
								multiple
								class="hidden"
								:disabled="photoUploading"
								@change="onQcPhotos"
							/>
						</label>
					</div>
					<p v-if="!qcPhotos.length && !photoUploading" class="text-xs text-gray-400">{{ labels.cleaningQcPhotoEmpty }}</p>
				</section>

				<!-- Catatan -->
				<section class="oak-card space-y-2 p-4">
					<label class="oak-label flex items-center justify-between gap-2">
						{{ labels.cleaningRemarks }}
						<span class="font-normal normal-case text-gray-400">{{ labels.optional }}</span>
					</label>
					<textarea v-model="remarks" rows="3" class="oak-input"></textarea>
				</section>

				<!-- Tanda Tangan -->
				<section class="oak-card space-y-2 p-4">
					<div class="flex items-center justify-between">
						<p class="oak-section-title">{{ labels.cleaningSignature }}</p>
						<button v-if="signatureUrl" type="button" class="oak-link text-sm" @click="startResign">
							{{ labels.cleaningResign }}
						</button>
					</div>
					<div v-if="signatureUrl && !signing">
						<img :src="photoSrc(signatureUrl)" class="h-28 w-full rounded-xl oak-sign-paper object-contain" />
					</div>
					<div v-else>
						<canvas
							ref="sigCanvas"
							class="h-28 w-full touch-none rounded-xl oak-sign-paper border-dashed border-gray-300"
							@pointerdown="sigDown"
							@pointermove="sigMove"
							@pointerup="sigUp"
							@pointerleave="sigUp"
						></canvas>
						<div class="mt-1 flex items-center justify-between text-xs text-gray-400">
							<span v-if="sigUploading">{{ labels.cleaningUploading }}</span>
							<span v-else-if="sigErr" class="text-red-600">{{ sigErr }}</span>
							<span v-else>{{ labels.signHint }}</span>
							<button type="button" class="text-gray-600 underline underline-offset-2" @click="clearSignature">
								{{ labels.clear }}
							</button>
						</div>
					</div>
				</section>

				<!-- Auto-save status (Catatan + Tanda Tangan persist on every edit) -->
				<p class="flex items-center gap-1.5 text-xs">
					<span v-if="saveRes.loading" class="text-gray-400">{{ labels.savingDraft }}</span>
					<span v-else-if="savedOk" class="inline-flex items-center gap-1 text-leaf-600">
						<Icon name="check" :size="13" /> {{ labels.draftSaved }}
					</span>
					<span v-else class="text-gray-400">{{ labels.autosaveHint }}</span>
				</p>

				<!-- Finalize — the order is already In_Progress inside this branch. -->
				<!-- Not gated on `saveRes.loading` — see EirInForm.vue: the finalise sends the whole
				     payload, so a slow autosave must never hold the button hostage. -->
				<button class="oak-btn oak-btn-primary w-full py-3" :disabled="submitting" @click="confirmComplete">
					<Icon v-if="submitting" name="loader" :size="18" class="animate-spin" />
					<span v-else>{{ labels.cleaningComplete }}</span>
				</button>
				<p class="text-center text-xs text-gray-400">{{ labels.cleaningCompleteHint }}</p>
			</template>
		</template>
	</div>
</template>

<script setup>
import { computed, nextTick, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import { createResource } from "frappe-ui"
import { labels } from "@/utils/labels"
import { saveToast, toast } from "@/utils/toast"
import { confirm } from "@/utils/confirm"
import { shootOrFallback } from "@/utils/camera"
import EditedBy from "@/components/EditedBy.vue"
import Icon from "@/components/Icon.vue"
import LastTestField from "@/components/LastTestField.vue"
import LiftOnBadge from "@/components/LiftOnBadge.vue"
import PhotoMark from "@/components/PhotoMark.vue"
import PhotoTile from "@/components/PhotoTile.vue"
import { usePhotoQueue } from "@/utils/photoQueue"
import SkeletonList from "@/components/SkeletonList.vue"
import SkeletonDetail from "@/components/SkeletonDetail.vue"
import { cachedResource } from "@/data/cache"
import { isLocalRef, photoSrc, send, uploadPhoto } from "@/data/send"

const route = useRoute()
const router = useRouter()

const fmtDate = (v) =>
	v
		? new Date(String(v).slice(0, 10) + "T00:00:00").toLocaleDateString("id-ID", {
				day: "numeric",
				month: "short",
				year: "numeric",
		  })
		: "—"

const search = ref("")
const allOrders = ref([]) // what the server (or the offline cache) last said
const order = ref(null)
const submitted = ref(null)

// Auto-save (mirrors the EIR flow): debounced draft save on every edit.
let saveTimer = null
const savedOk = ref(false) // last auto-save succeeded
const suppressSave = ref(false) // mute auto-save while a draft is being loaded

// The operator only signs off now: Catatan (remarks) + Tanda Tangan (signature). The cleaning
// method(s) are chosen upstream by Admin Ops and shown read-only.
const remarks = ref("")
// QC photo list (uploaded file_urls).
const qcPhotos = ref([])
const photoUploading = ref(false)

const ordersRes = cachedResource({
	url: "container_depot.ess.cleaning.cleaning_orders",
	method: "GET",
	auto: true,
	onSuccess: (data) => (allOrders.value = data.items || []),
})

// How many finished orders the landing shows before "Lihat semua" takes over.
const LANDING_LIMIT = 5

// "Diajukan Review" — orders finished in the field, waiting for Admin Ops to check and
// Submit on the Desk. Opened read-only like a finished one; withdrawable from the row.
const reviewItems = ref([])
const reviewRes = cachedResource({
	url: "container_depot.ess.cleaning.cleaning_pending_review",
	method: "GET",
	auto: true,
	onSuccess: (data) => (reviewItems.value = data.items || []),
})

const doneItems = ref([])
const doneRes = cachedResource({
	url: "container_depot.ess.cleaning.cleaning_history",
	method: "GET",
	makeParams: () => ({ page_length: LANDING_LIMIT }),
	auto: true,
	onSuccess: (data) => (doneItems.value = data.items || []),
})

// Finished (or field-done) work has no editable form to open — the Riwayat detail takes an
// ?open= deep link and fetches the order straight from the server.
function goFinished(r) {
	router.push({ path: "/cleaning/history", query: { open: r.name } })
}

const withdrawRes = createResource({
	url: "container_depot.ess.cleaning.cleaning_withdraw_review",
	method: "POST",
	onSuccess: () => {
		toast.success(labels.cleaningWithdrawReviewDone)
		reloadOrders()
		reviewRes.reload()
	},
	onError: (e) => toast.error(e?.messages?.[0] || e?.message || labels.error),
})
function withdrawReview(r) {
	withdrawRes.submit({ cleaning_order: r.name })
}

// An order whose sign-off is already queued is finished as far as the operator is concerned.
// Leaving it in the list — which it will be, because the server has not heard about it yet —
// invites them to do the whole job a second time.
const orders = computed(() => allOrders.value)

function reloadOrders() {
	const s = search.value.trim()
	ordersRes.fetch(s ? { search: s } : {})
}

// Typing searches on its own after a beat — same feel as the EIR worklist — while Enter and
// the button still fire it immediately.
let searchTimer = null
function onSearchInput() {
	clearTimeout(searchTimer)
	searchTimer = setTimeout(reloadOrders, 300)
}

// Worklist status filter. "Selesai" is not a choice here: a submitted cleaning leaves the
// worklist entirely and shows under Riwayat.
const filter = ref("all")
const startedOrders = computed(() => orders.value.filter((o) => o.status === "In_Progress"))
const todoOrders = computed(() => orders.value.filter((o) => o.status !== "In_Progress"))
const visibleOrders = computed(() => {
	if (filter.value === "started") return startedOrders.value
	if (filter.value === "todo") return todoOrders.value
	return orders.value
})
const FILTERS = computed(() => [
	{ key: "all", label: labels.cleaningFilterAll, count: orders.value.length },
	{ key: "todo", label: labels.cleaningFilterTodo, count: todoOrders.value.length },
	{ key: "started", label: labels.cleaningFilterStarted, count: startedOrders.value.length },
])
const emptyText = computed(() => {
	if (!orders.value.length) return labels.cleaningOrdersEmpty
	if (filter.value === "started") return labels.cleaningFilterEmptyStarted
	if (filter.value === "todo") return labels.cleaningFilterEmptyTodo
	return labels.cleaningOrdersEmpty
})


// Started = the wash is running and the form is open. Before that the same screen shows the
// same facts with one button instead of three inputs.
const started = computed(() => order.value?.status === "In_Progress")
// Only a wash nobody has finished can be started. The server says so too
// (cleaning.start_cleaning refuses Completed / Pending Review); this keeps the button from
// being offered in the first place.
const canStart = computed(() => ["Pending", "Service Setup"].includes(order.value?.status))

// The header chip says what the order IS, not merely whether the form is open: this screen
// can be reached by name for an order that is already in review or closed, and telling that
// one "Belum mulai" would be flatly wrong.
const ORDER_CHIPS = {
	In_Progress: { label: labels.cleaningInProgress, tone: "bg-amber-100 text-amber-800" },
	"Pending Review": { label: labels.cleaningStatusPendingReview, tone: "bg-sky-100 text-sky-800" },
	Completed: { label: labels.cleaningStatusCompleted, tone: "bg-leaf-100 text-leaf-800" },
	Cancelled: { label: labels.cleaningStatusCancelled, tone: "bg-red-100 text-red-700" },
}
const orderChip = computed(
	() =>
		ORDER_CHIPS[order.value?.status] || {
			label: labels.cleaningNotStarted,
			tone: "bg-gray-100 text-gray-600",
		}
)

const headerCells = computed(() => {
	const h = order.value || {}
	return [
		{ label: labels.cleaningTankType, value: h.tank_type },
		{ label: labels.equipmentType, value: h.equipment_type },
		// Owner and last cargo are not repeated here — they lead the header card above, and a
		// spec table that restates the heading is a table people stop reading.
		{ label: labels.cleaningCapacity, value: h.capacity },
		{ label: labels.cleaningTare, value: h.tare },
		{ label: labels.cleaningMgw, value: h.mgw },
		{ label: labels.cleaningMfgDate, value: h.date_of_manufacture },
		// Tgl. tes terakhir TIDAK di sini: ia satu-satunya baris kartu ini yang boleh
		// ditulis, dan tinggal di LastTestField tepat setelah deretan ini.
	]
})

// Whether a detail fetch is in flight, tracked explicitly rather than derived from
// `route.query.o && !order`. The derived version flickers: completing an order nulls `order`
// while the query is still set, and the screen would flash a skeleton on its way back to the
// worklist.
const detailPending = ref(false)
const detailFailed = ref(false)
const detailError = ref("")

const detailRes = cachedResource({
	url: "container_depot.ess.cleaning.cleaning_order_detail",
	method: "GET",
	onSuccess(data) {
		detailPending.value = false
		detailFailed.value = false
		// Mute auto-save while we populate the form from the loaded order.
		suppressSave.value = true
		savedOk.value = false
		order.value = data
		remarks.value = data.remarks || ""
		signatureUrl.value = data.signature || ""
		qcPhotos.value = (data.qc_photos || []).map((p) => ({ ...p }))
				nextTick(() => {
				suppressSave.value = false
			})
	},
	// The error stays on the page here rather than in a toast: a toast disappears, and the
	// operator would be left staring at a worklist wondering why their tap did nothing.
	onError(err) {
		detailPending.value = false
		detailFailed.value = true
		detailError.value = err?.messages?.[0] || err?.message || labels.error
	},
})

// The open order lives in the URL (?o=<name>) so a refresh restores the detail view
// instead of dropping back to the worklist. `pushedByTap` records whether *this* screen
// added that history entry: landing straight on ?o=… from a notification link added
// nothing, and popping then would walk the operator out of the app.
let pushedByTap = false
function openOrder(o) {
	pushedByTap = true
	router.push({ query: { o: o.name } })
}

function fetchDetail(name) {
	detailPending.value = true
	detailFailed.value = false
	detailRes.fetch({ cleaning_order: name })
}
function retryDetail() {
	if (route.query.o) fetchDetail(route.query.o)
}

watch(
	() => route.query.o,
	(o) => {
		if (o) {
			if (order.value?.name !== o) {
				submitted.value = null
				fetchDetail(o)
			}
		} else {
			order.value = null
			detailPending.value = false
			detailFailed.value = false
		}
	},
	{ immediate: true }
)

// Mulai Cleaning (worklist or in-form).
//
// The status is flipped locally rather than re-fetched. The
// response carried nothing the form needed except the new status, so there is no reason to
// wait for it — and waiting is what made "Mulai" impossible in a dead spot, which locked the
// operator out of the whole form.
//
// No `ref` on this row: starting is not finishing, and the order must stay in the worklist.
async function startCleaning(name) {
	try {
		await send({
			url: "container_depot.ess.cleaning.cleaning_start",
			payload: { cleaning_order: name },
		})
		toast.success(labels.cleaningStarted)
		return true
	} catch (e) {
		toast.error(e?.message || labels.error)
		return false
	}
}

async function startCurrent() {
	if (!order.value) return
	if (await startCleaning(order.value.name)) order.value = { ...order.value, status: "In_Progress" }
}

// Server-side autosave only. The finalise has its own call (see submitCleaning), so this
// resource never sees submit=1 and never has to deal with the finalized branch.
const saveRes = createResource({
	url: "container_depot.ess.cleaning.cleaning_order_save",
	method: "POST",
	onSuccess() {
		savedOk.value = true
		saveToast.done()
		flushPendingSave()
	},
	// An autosave that could not reach the server is not worth a red toast — the operator is
	// mid-form, the local draft has the data, and the finalise will carry it. Anything the
	// server actively refused, they do need to see.
	// The busy toast is cleared either way — `fail("")` just takes the slot back.
	onError(err) {
		saveToast.fail(err?.response ? err?.messages?.[0] || err?.message || labels.error : "")
		flushPendingSave()
	},
})

// Never two autosaves in flight at once. Each one writes the whole document, so on a slow
// link an earlier response landing after a later one restores stale text over what the
// operator has since typed. When the debounce fires mid-flight we remember the edit and
// re-arm from the response handler instead of stacking a second POST.
let resaveWanted = false

/** Called when a save settles: if edits arrived while it flew, start the debounce again. */
function flushPendingSave() {
	if (!resaveWanted) return
	resaveWanted = false
	scheduleSave()
}

// Debounced auto-save on every edit (mirrors EIR): only while an unfinished order is open.
function scheduleSave() {
	if (!order.value || order.value.docstatus === 1 || suppressSave.value) return
	savedOk.value = false
	if (saveTimer) clearTimeout(saveTimer)
	saveTimer = setTimeout(() => {
		saveTimer = null
		if (saveRes.loading) {
			resaveWanted = true
			return
		}
		save(false)
	}, 700)
}

// Finalize (Selesaikan) asks for an explicit confirmation first.
async function confirmComplete() {
	const ok = await confirm({
		title: labels.confirmSubmitTitle,
		message: labels.confirmSubmitMessage,
		confirmLabel: labels.confirmSubmitYes,
		cancelLabel: labels.confirmCancel,
	})
	if (ok) save(true)
}

function payload(submit) {
	return {
		cleaning_order: order.value.name,
		remarks: remarks.value || undefined,
		signature: signatureUrl.value || undefined,
		// An array, not a JSON string: `send` has to walk the payload to find the
		// `local:` photo references and swap them for real file_urls.
		qc_photos: qcPhotos.value.filter((p) => p.photo),
		submit: submit ? 1 : 0,
	}
}


function save(submit) {
	if (!order.value) return
	if (saveTimer) {
		clearTimeout(saveTimer)
		saveTimer = null
	}
	if (submit) {
		submitCleaning()
		return
	}
	const p = payload(false)
	saveToast.start()
	// Strip anything not yet uploaded: a `local:` string written into a QC photo
	// row would be a broken image for ever. Those travel with the finalise instead.
	saveRes.fetch({
		...p,
		signature: isLocalRef(p.signature) ? undefined : p.signature,
		qc_photos: JSON.stringify(p.qc_photos.filter((x) => !isLocalRef(x.photo))),
	})
}

// Held while the send is in flight. `send` waits for the server (and for
// any QC photos to upload), so the button is live for a real second or two — long enough for
// an impatient second tap to raise a second sign-off under a second request_id.
const submitting = ref(false)

/** Hand the finished sign-off to `send`: photos first, then the document, then wait. */
async function submitCleaning() {
	const o = order.value
	if (submitting.value) return
	submitting.value = true
	try {
		await send({
			// Cleared by the queue once the save has actually landed — not here. If this row
			// comes back refused (the order closed on the Desk meanwhile), the draft is what
			// still holds the photos and the remarks.
			url: "container_depot.ess.cleaning.cleaning_order_save",
			payload: payload(true),
		})
		toast.success(labels.cleaningSubmitted, {
			title: o.order_id || o.name,
		})
		submitted.value = null
		resetForm()
		order.value = null
		if (route.query.o) router.replace({ query: {} })
		reloadOrders()
		// It has left the worklist for the review queue — show it there rather than making
		// the operator wonder where their order went.
		reviewRes.reload()
	} catch (e) {
		toast.error(e?.message || labels.error)
	} finally {
		submitting.value = false
	}
}

// --- QC photo handlers ------------------------------------------------------
function removeQcPhoto(i) {
	qcPhotos.value.splice(i, 1)
}
async function onQcPhotos(e) {
	const files = Array.from(e.target.files || [])
	e.target.value = "" // allow re-picking the same file
	await addQcPhotos(files)
}

// In-app viewfinder: shutter -> upload, no camera-app confirm screen in between
// (utils/camera.js). QC evidence is shot in a run of several, so it stays open between them.
const camInput = ref(null)
function openCameraOrFallback() {
	return shootOrFallback(camInput, (file) => addQcPhotos([file]))
}

// Each photo shows itself while it goes up — see EirInForm for why.
const photoQueue = usePhotoQueue()

async function addQcPhotos(files) {
	if (!files.length) return false
	// `last` adalah jawaban untuk viewfinder: strip di dalam kamera menandai jepretan ini dari
	// nilai yang dikembalikan (lihat utils/camera.js), jadi kegagalan yang ditelan di sini akan
	// tampil sebagai "terkirim" pada foto yang tidak ke mana-mana.
	let last = false
	photoQueue.clearFailed()
	photoUploading.value = true
	try {
		for (const f of files) {
			const id = photoQueue.add(f)
			try {
				const url = await uploadFile(f)
				qcPhotos.value.push({ photo: url, caption: "" })
				last = url
				photoQueue.done(id)
			} catch (err) {
				last = false
				toast.error(labels.error)
				photoQueue.fail(id)
			}
		}
	} finally {
		photoUploading.value = false
	}
	return last
}

function backToList() {
	submitted.value = null
	resetForm()
	// A real Back, not another push: it drops the entry opening this order added (so the
	// phone's own Back does not walk straight back into it) and lets the router restore the
	// worklist to the row that was tapped.
	if (route.query.o) {
		if (pushedByTap) {
			pushedByTap = false
			router.back()
		} else router.replace({ query: {} })
	} else order.value = null
	reloadOrders()
}

function resetForm() {
	// Clearing the form must never trigger an auto-save of the emptied fields.
	if (saveTimer) {
		clearTimeout(saveTimer)
		saveTimer = null
	}
	suppressSave.value = true
	savedOk.value = false
	remarks.value = ""
	signatureUrl.value = ""
	signing.value = false
	qcPhotos.value = []
}

// --- file upload + virtual signature pad ------------------------------------

/**
 * Take a picked photo and hand back a reference the form can hold onto.
 *
 * It goes up straight away, so the autosave that follows puts a real file_url on the order
 * and the QC evidence survives a reload. When the link is down it is parked instead and the
 * `local:` reference travels through the form exactly like a URL, until `send` uploads it on
 * Selesaikan (see data/send.js).
 */
async function uploadFile(file) {
	return uploadPhoto(file)
}

const sigCanvas = ref(null)
const signatureUrl = ref("")

// The three parts of a sign-off, and which are filled. Nothing new is being asked for — the
// chips only save the operator scrolling to the bottom to find out what is still missing.
const steps = computed(() => [
	{ label: labels.cleaningStepMethod, done: !!(order.value?.cleaning_services || []).length },
	{ label: labels.cleaningQcPhotos, done: !!qcPhotos.value.length },
	{ label: labels.cleaningStepSign, done: !!signatureUrl.value },
])

const signing = ref(false)
const sigUploading = ref(false)
const sigErr = ref("")
let sigCtx = null
let sigDrawing = false
let sigHasInk = false
let sigTimer = null

function sigCtxInit() {
	const c = sigCanvas.value
	if (!c) return null
	if (sigCtx && sigCtx.canvas === c) return sigCtx
	const ratio = window.devicePixelRatio || 1
	c.width = c.clientWidth * ratio
	c.height = c.clientHeight * ratio
	const ctx = c.getContext("2d")
	ctx.scale(ratio, ratio)
	ctx.lineWidth = 2
	ctx.lineCap = "round"
	ctx.lineJoin = "round"
	ctx.strokeStyle = "#111827"
	sigCtx = ctx
	return ctx
}

function sigPos(e) {
	const r = sigCanvas.value.getBoundingClientRect()
	return { x: e.clientX - r.left, y: e.clientY - r.top }
}

function sigDown(e) {
	const ctx = sigCtxInit()
	if (!ctx) return
	sigDrawing = true
	const p = sigPos(e)
	ctx.beginPath()
	ctx.moveTo(p.x, p.y)
	sigCanvas.value.setPointerCapture?.(e.pointerId)
}

function sigMove(e) {
	if (!sigDrawing || !sigCtx) return
	const p = sigPos(e)
	sigCtx.lineTo(p.x, p.y)
	sigCtx.stroke()
	sigHasInk = true
}

function sigUp() {
	if (!sigDrawing) return
	sigDrawing = false
	if (!sigHasInk) return
	if (sigTimer) clearTimeout(sigTimer)
	sigTimer = setTimeout(uploadSignature, 600)
}

async function uploadSignature() {
	const c = sigCanvas.value
	if (!c || !sigHasInk) return
	sigErr.value = ""
	sigUploading.value = true
	try {
		const blob = await new Promise((res) => c.toBlob(res, "image/png"))
		signatureUrl.value = await uploadFile(new File([blob], "cleaning-signature.png", { type: "image/png" }))
		signing.value = false
	} catch (e) {
		sigErr.value = labels.signatureError
	} finally {
		sigUploading.value = false
	}
}

function clearSignature() {
	if (sigTimer) clearTimeout(sigTimer)
	const ctx = sigCtxInit()
	if (ctx && sigCanvas.value) ctx.clearRect(0, 0, sigCanvas.value.width, sigCanvas.value.height)
	sigHasInk = false
	signatureUrl.value = ""
}

function startResign() {
	signatureUrl.value = ""
	signing.value = true
	sigHasInk = false
	sigCtx = null
	nextTick(sigCtxInit)
}

// Auto-save on every edit: Catatan (remarks) + Tanda Tangan (signature) + QC/material.
watch([remarks, signatureUrl], scheduleSave)
watch(qcPhotos, scheduleSave, { deep: true })
</script>
