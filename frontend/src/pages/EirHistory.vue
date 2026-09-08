<template>
	<HistoryPage
		:title="labels.eirHistoryTitle"
		icon="clipboard"
		back-to="/eir"
		:back-label="labels.eirTitle"
		list-url="container_depot.ess.inspections.eir_history"
		detail-url="container_depot.ess.inspections.eir_view"
		detail-param="inspection"
		:search-placeholder="labels.eirHistorySearch"
		:count-label="labels.eirHistoryCount"
	>
		<!-- Three lines, and which fact sits on which line is the whole design. A phone row is
		     ~250 px wide once the tile and the chevron are paid for; the old layout put the
		     tank number and a chip reading "Menunggu Review" on that one line, so the number —
		     the only thing anybody scans this list for — was the half that got the ellipsis.
		     Now the number owns its line with just the date beside it, and the status chip
		     drops to the bottom where it has room to say what it means. The tile carries the
		     direction (masuk / keluar) instead of a clipboard that was the same on every row. -->
		<template #row="{ item }">
			<span class="oak-icon-tile h-10 w-10 shrink-0" :class="typeTile(item)">
				<Icon :name="item.inspection_type === 'EIR-Out' ? 'log-out' : 'log-in'" :size="18" />
			</span>
			<div class="min-w-0 flex-1">
				<div class="flex items-baseline justify-between gap-2">
					<p class="truncate text-[15px] font-extrabold tracking-tight text-gray-900">{{ item.container_no || item.container }}</p>
					<span class="shrink-0 text-[11px] font-medium text-gray-400">{{ fmtDateShort(item.eir_date || item.creation) }}</span>
				</div>
				<p class="mt-0.5 truncate text-xs text-gray-500">
					{{ item.inspection_type }}<span v-if="item.tank_status"> · {{ item.tank_status }}</span>
				</p>
				<div class="mt-1.5 flex items-center gap-1.5">
					<span class="oak-chip shrink-0" :class="statusClass(item)">{{ statusText(item) }}</span>
					<span class="min-w-0 truncate font-mono text-[10px] text-gray-400">{{ item.inspection_id || item.name }}</span>
				</div>
			</div>
		</template>

		<template #detail="{ data }">
			<section class="oak-card space-y-3 p-4">
				<div class="flex items-start gap-3">
					<span class="oak-icon-tile h-11 w-11 shrink-0" :class="typeTile(data)">
						<Icon :name="data.inspection_type === 'EIR-Out' ? 'log-out' : 'log-in'" :size="20" />
					</span>
					<div class="min-w-0 flex-1">
						<h2 class="truncate text-lg font-extrabold leading-tight text-gray-900">{{ data.container_no }}</h2>
						<p class="truncate font-mono text-[11px] text-gray-400">{{ data.inspection_id || data.name }}</p>
						<span class="oak-chip mt-1.5" :class="statusClass(data)">{{ statusText(data) }}</span>
					</div>
				</div>
				<!-- Only the fields this EIR actually carries. A phone shows eight rows in the
				     space a desk shows two, so eight labels over em-dashes is most of the
				     screen spent saying nothing — and it buries the four that do say
				     something. `break-words`, not `truncate`: an EMKL name cut off with no
				     way to see the rest is a field that is not really on the screen. -->
				<dl v-if="cells(data).length" class="grid grid-cols-2 gap-x-3 gap-y-2.5 text-sm">
					<div v-for="c in cells(data)" :key="c.label" class="min-w-0">
						<dt class="text-[11px] uppercase tracking-wide text-gray-400">{{ c.label }}</dt>
						<dd class="break-words font-medium text-gray-800">{{ c.value }}</dd>
					</div>
				</dl>
				<p v-if="data.remarks" class="rounded-lg bg-gray-50 p-2.5 text-xs leading-relaxed text-gray-600">{{ data.remarks }}</p>
			</section>

			<section class="oak-card space-y-2 p-4">
				<p class="oak-section-title">
					{{ labels.eirChecklistDamage }} ({{ data.damage_count || 0 }})
					<span v-if="data.finding_count" class="ml-1 text-xs font-normal text-amber-600">
						· {{ data.finding_count }} {{ labels.eirDamages.toLowerCase() }}
					</span>
				</p>
				<p v-if="!(data.damages || []).length" class="text-sm text-gray-400">{{ labels.eirNoDamage }}</p>
				<ul v-else class="space-y-3 text-sm">
					<!-- Kartu yang kembali "Acceptable" tetap dilist — itu bagian yang benar-benar
					     didatangi dan difoto — tapi ikonnya beda supaya temuan nyata tetap menonjol. -->
					<li v-for="(d, i) in data.damages" :key="i" class="flex items-start gap-2 text-gray-800">
						<Icon
							:name="d.is_finding ? 'alert-triangle' : 'check'"
							:size="14"
							class="mt-0.5 shrink-0"
							:class="d.is_finding ? 'text-amber-500' : 'text-leaf-500'"
						/>
						<div class="min-w-0 flex-1">
							<span class="font-medium">{{ d.item_name || d.item }}</span>
							<span v-if="d.damage_type" class="text-gray-500"> · {{ d.damage_label || d.damage_type }}</span>
							<span v-if="d.repair_code" class="text-gray-500"> / {{ d.repair_label || d.repair_code }}</span>
							<span v-if="d.damage_description" class="block text-xs text-gray-400">{{ d.damage_description }}</span>
							<!-- Bukti temuan ini, sejajar dengan yang ada di form Desk. -->
							<div v-if="(d.photos || []).length" class="mt-1.5 flex flex-wrap gap-1.5">
								<button
									v-for="(url, pi) in d.photos"
									:key="url"
									type="button"
									class="oak-press"
									@click="openLightbox(d.photos.map(photoSrc), pi)"
								>
									<img :src="photoSrc(url)" class="h-16 w-16 rounded-lg border border-gray-200 object-cover" />
								</button>
							</div>
						</div>
					</li>
				</ul>
			</section>

			<!-- Kelengkapan tank: kotak isian form EIR cetak. Hanya yang benar-benar diisi —
			     slot kosong berarti tidak diperiksa, bukan nol.
			     Dibentuk seperti blok isiannya di form (TankFittings.vue): kepala dengan
			     jumlah, kompartemen sebagai pemisah, satu garis per baris. Dua puluh empat
			     baris "label ... angka" tanpa garis dan tanpa kompartemen adalah dinding teks
			     — mata kehilangan jejak barisnya di tengah lompatan ke kolom angka, dan tank
			     dua kompartemen menyebut slot yang sama dua kali tanpa keterangan ujung mana.
			     No. cetaknya ikut ditampilkan supaya baris di layar bisa dicocokkan dengan
			     kotak di kertas yang dipegang. -->
			<section v-if="(data.fittings || []).length" class="oak-card overflow-hidden">
				<div class="flex items-center justify-between gap-2 border-b border-gray-100 px-4 py-3">
					<div class="flex min-w-0 items-center gap-2">
						<Icon name="clipboard" :size="16" class="shrink-0 text-gray-400" />
						<p class="oak-section-title truncate">{{ labels.fittingsTitle }}</p>
					</div>
					<span class="oak-chip shrink-0 bg-gray-100 text-gray-600">{{ data.fittings.length }}</span>
				</div>
				<template v-for="g in groupByCompartment(data.fittings)" :key="g.compartment">
					<p v-if="g.compartment" class="bg-gray-50 px-4 py-1 text-[11px] font-bold uppercase tracking-wide text-gray-500">
						{{ g.compartment }}
					</p>
					<div
						v-for="(f, i) in g.items"
						:key="i"
						class="flex items-baseline justify-between gap-3 border-t border-gray-100 px-4 py-2"
					>
						<p class="min-w-0 text-sm text-gray-700">
							<span v-if="f.printed_no" class="mr-1 font-mono text-[10px] text-gray-400">{{ f.printed_no }}</span>
							{{ f.item_label }}<span v-if="f.slot_label" class="text-gray-400"> · {{ f.slot_label }}</span>
						</p>
						<p class="shrink-0 text-sm font-bold tabular-nums text-gray-900">
							{{ f.value }}<span v-if="f.uom" class="ml-0.5 text-xs font-normal text-gray-400">{{ f.uom }}</span>
						</p>
					</div>
				</template>
			</section>

			<!-- Album inspeksi: foto keliling tank dan foto bagian yang diperiksa tapi tidak
			     rusak — sama seperti tabel Foto per Item di Desk. -->
			<section class="oak-card space-y-2 p-4">
				<p class="oak-section-title">{{ labels.eirPhotosTitle }} ({{ data.photo_count || 0 }})</p>
				<p v-if="!(data.photos || []).length" class="text-sm text-gray-400">{{ labels.eirNoPhotos }}</p>
				<!-- A grid, not wrapped fixed-width tiles: 104 px squares leave a ragged strip of
				     dead space down the right of a 360 px screen and go to two-per-row anyway.
				     Three equal columns fill whatever width the phone has. -->
				<div v-else class="grid grid-cols-3 gap-2">
					<button
						v-for="(p, i) in data.photos"
						:key="p.photo"
						type="button"
						class="oak-press min-w-0 text-left"
						@click="openLightbox((data.photos || []).map((x) => photoSrc(x.photo)), i)"
					>
						<img :src="photoSrc(p.photo)" class="aspect-square w-full rounded-lg border border-gray-200 object-cover" />
						<span class="mt-0.5 block truncate text-[11px]" :class="p.item_name ? 'text-gray-500' : 'text-gray-400'">
							{{ p.item_name || labels.eirPhotoUnsorted }}
						</span>
					</button>
				</div>
			</section>

			<!-- Full width on a phone (`flex-1`), natural width from `sm:` up: these are the
			     only two actions on the screen, and a 120 px button in the corner of a handset
			     is a target the operator has to aim at with a glove on. -->
			<div class="flex flex-wrap items-center gap-2">
				<button
					v-if="data.docstatus === 1 && revisionFor !== data.name"
					type="button"
					class="oak-btn oak-btn-secondary flex-1 px-3 py-2.5 sm:flex-none"
					@click="openRevision(data.name)"
				>
					<Icon name="rotate-ccw" :size="16" /> {{ labels.eirReqRevision }}
				</button>
				<!-- Awaiting review → the operator can pull it back to Draft and fix it (no
				     Admin Ops needed). Jumps straight into the editable form on success. -->
				<button
					v-if="data.docstatus === 0 && data.status === 'Pending Review'"
					type="button"
					class="oak-btn oak-btn-primary flex-1 px-3 py-2.5 sm:flex-none"
					:disabled="withdrawRes.loading"
					@click="withdrawReview(data)"
				>
					<Icon name="edit-3" :size="16" /> {{ withdrawRes.loading ? "…" : labels.eirWithdrawReview }}
				</button>
			</div>
			<p v-if="data.docstatus === 0 && data.status === 'Pending Review'" class="px-1 text-xs text-gray-400">
				{{ labels.eirWithdrawReviewHint }}
			</p>

			<!-- Revision request: reason (optional) + send; notifies Admin Ops server-side. -->
			<section v-if="revisionFor === data.name" class="oak-card space-y-2 p-4">
				<p class="oak-section-title">{{ labels.eirReqRevision }}</p>
				<p class="text-xs text-gray-400">{{ labels.eirReqRevisionHint }}</p>
				<textarea v-model.trim="revisionReason" rows="2" :placeholder="labels.eirReqRevisionReason" class="oak-input"></textarea>
				<div class="flex items-center gap-2">
					<button type="button" class="oak-btn oak-btn-primary px-3 py-2" :disabled="revisionRes.loading" @click="sendRevision(data.name)">
						<Icon v-if="!revisionRes.loading" name="send" :size="16" />
						{{ revisionRes.loading ? "…" : labels.eirReqRevisionSend }}
					</button>
					<button type="button" class="oak-btn oak-btn-secondary px-3 py-2" :disabled="revisionRes.loading" @click="revisionFor = ''">
						{{ labels.confirmCancel }}
					</button>
				</div>
			</section>
		</template>
	</HistoryPage>
</template>

<script setup>
import { ref } from "vue"
import { useRouter } from "vue-router"
import { createResource } from "frappe-ui"
import { labels } from "@/utils/labels"
import { toast } from "@/utils/toast"
import { openLightbox } from "@/utils/lightbox"
import { photoSrc } from "@/data/send"
import { groupByCompartment } from "@/utils/fittings"
import { fmtDate, fmtDateShort } from "@/utils/surveyStatus"
import Icon from "@/components/Icon.vue"
import HistoryPage from "@/components/HistoryPage.vue"

const router = useRouter()

// EIR-In arrives, EIR-Out leaves — the one fact a row of otherwise identical clipboard tiles
// never carried. Sky for in / brand for out, matching the direction pills used elsewhere.
function typeTile(r) {
	return r?.inspection_type === "EIR-Out" ? "bg-brand-50 text-brand-600" : "bg-sky-50 text-sky-600"
}

// Withdraw a "Pending Review" EIR back to an editable Draft, then open the form so the
// operator can fix it and re-send for review.
const withdrawRes = createResource({
	url: "container_depot.ess.inspections.eir_withdraw_review",
	method: "POST",
	onSuccess(data) {
		toast.success(labels.eirWithdrawReviewDone)
		const t = data?.inspection_type === "EIR-Out" ? "out" : "in"
		router.push({ path: "/eir", query: { e: data?.inspection, t } })
	},
	onError(err) {
		toast.error(err?.messages?.[0] || err?.message || labels.error)
	},
})
function withdrawReview(data) {
	withdrawRes.submit({ inspection: data.name })
}

// Revision request: which EIR's reason box is open, its text, and the POST resource.
const revisionFor = ref("")
const revisionReason = ref("")
function openRevision(name) {
	revisionFor.value = name
	revisionReason.value = ""
}
const revisionRes = createResource({
	url: "container_depot.ess.inspections.eir_request_revision",
	method: "POST",
	onSuccess() {
		toast.success(labels.eirReqRevisionSent)
		revisionFor.value = ""
		revisionReason.value = ""
	},
	onError(err) {
		toast.error(err?.messages?.[0] || err?.message || labels.error)
	},
})
function sendRevision(name) {
	revisionRes.submit({ inspection: name, reason: revisionReason.value || undefined })
}

// Single status vocabulary, identical to the Desk list (inspection_list.js) so the two
// surfaces never read differently: Batal / Revisi Diminta / Selesai / Menunggu Review / Draf.
function statusText(r) {
	if (r.docstatus === 2) return labels.eirStatusCancelled
	if (r.docstatus === 1 && r.revision_requested) return labels.eirStatusRevision
	if (r.docstatus === 1) return labels.eirStatusSubmitted
	if (r.status === "Pending Review") return labels.eirStatusPendingReview
	return labels.eirStatusDraft
}
function statusClass(r) {
	if (r.docstatus === 2) return "bg-gray-200 text-gray-600"
	if (r.docstatus === 1 && r.revision_requested) return "bg-orange-100 text-orange-800"
	if (r.docstatus === 1) return "bg-leaf-100 text-leaf-800"
	if (r.status === "Pending Review") return "bg-sky-100 text-sky-800"
	return "bg-amber-100 text-amber-800"
}
// Header facts, EMPTY ONES DROPPED — see the grid's own comment for why a phone cannot
// afford a row that only says "—".
function cells(d) {
	return [
		{ label: labels.eirType, value: d.inspection_type },
		{ label: labels.eirTankStatus, value: d.tank_status },
		{ label: labels.eirDate, value: d.eir_date ? fmtDate(d.eir_date) : "" },
		{ label: labels.depotLabel, value: d.depot },
		{ label: labels.eirVoucher, value: d.referred_voucher },
		{ label: labels.eirTruck, value: d.truck_no },
		{ label: labels.eirDriver, value: d.driver },
		{ label: labels.eirEmkl, value: d.emkl },
		{ label: labels.shipper, value: d.shipper },
	].filter((c) => c.value)
}
</script>
