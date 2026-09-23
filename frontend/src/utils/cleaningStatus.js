import { labels } from "@/utils/labels"

// Chip satu Cleaning Order — teksnya ikut, supaya tetap terbaca walau warnanya pudar di bawah matahari.
const CHIPS = {
	In_Progress: { label: labels.cleaningInProgress, cls: "bg-amber-100 text-amber-800" },
	"Pending Review": { label: labels.cleaningStatusPendingReview, cls: "bg-sky-100 text-sky-800" },
	Completed: { label: labels.cleaningStatusCompleted, cls: "bg-leaf-100 text-leaf-800" },
	Cancelled: { label: labels.cleaningStatusCancelled, cls: "bg-red-100 text-red-700" },
}
export function cleaningChip(o) {
	return CHIPS[o?.status] || { label: labels.cleaningNotStarted, cls: "bg-gray-100 text-gray-600" }
}
