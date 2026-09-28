import { labels, statusLabels } from "@/utils/labels"
import { STEP_COUNT, hasStep, getStep } from "@/utils/eirBatch"
import { tone } from "@/utils/statusPill"

// Warna bucket mengikuti aturan status Desk (statusPill.js / container_list.js).
const COLOUR = {
	available: "green",
	draft: "gray",
	pending: "orange",
	in_progress: "yellow",
	gate_out: "blue",
}

// Chip status satu tank — sama di baris daftar dan di kepala detail. EIR yang sedang
// dikerjakan diberi kalimatnya sendiri: "Draft" saja akan dibaca sebagai M&R draft, dan
// kedua pekerjaan itu dipegang orang yang berbeda.
export function tankChip(c) {
	if (c.order?.kind === "EIR") {
		const step = hasStep(c.order.name) ? ` ${getStep(c.order.name) + 1}/${STEP_COUNT}` : ""
		return { label: `${labels.monitorDraftEir}${step}`, cls: tone("yellow") }
	}
	return { label: statusLabels[c.status] || c.status || "—", cls: tone(COLOUR[c.status]) }
}
