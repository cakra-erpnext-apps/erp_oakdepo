import { labels, statusLabels } from "@/utils/labels"
import { STEP_COUNT, hasStep, getStep } from "@/utils/eirBatch"

const CHIP = {
	available: "bg-leaf-100 text-leaf-800",
	draft: "bg-gray-100 text-gray-700",
	pending: "bg-amber-100 text-amber-800",
	in_progress: "bg-blue-100 text-blue-800",
	gate_out: "bg-gray-200 text-gray-700",
}

// Chip status satu tank — sama di baris daftar dan di kepala detail. EIR yang sedang
// dikerjakan diberi kalimatnya sendiri: "Draft" saja akan dibaca sebagai M&R draft, dan
// kedua pekerjaan itu dipegang orang yang berbeda.
export function tankChip(c) {
	if (c.order?.kind === "EIR") {
		const step = hasStep(c.order.name) ? ` ${getStep(c.order.name) + 1}/${STEP_COUNT}` : ""
		return { label: `${labels.monitorDraftEir}${step}`, cls: "bg-brand-100 text-brand-700" }
	}
	return { label: statusLabels[c.status] || c.status || "—", cls: CHIP[c.status] || "bg-gray-100 text-gray-600" }
}
