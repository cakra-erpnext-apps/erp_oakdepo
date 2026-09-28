// How the four kinds of planned work look on Jadwal, and what their status says in one word.
//
// Kept out of the page because three surfaces read it — the week/month dots, the filter
// chips, and the timeline rows — and a kind whose colour differed between the dot and the
// row it belongs to would make the dots unreadable.
//
// Keys are the SERVER's kind strings (container_depot.schedule.SOURCES), so a source added
// there needs exactly one entry here.

import { labels, repairStatusLabels } from "@/utils/labels"
import { STAGE, tone } from "@/utils/statusPill"

export const KIND = {
	// Colours follow the rest of the app rather than the calendar's own taste: a droplet is
	// green wherever cleaning appears, a wrench is amber, a truck is brand orange. Survey
	// takes sky, the one family nothing else in the PWA claims.
	survey: { label: labels.kindSurvey, icon: "list", dot: "bg-sky-500", bar: "bg-sky-500", text: "text-sky-600", chip: "bg-sky-100 text-sky-800" },
	cleaning: { label: labels.kindCleaning, icon: "sparkles", dot: "bg-leaf-500", bar: "bg-leaf-500", text: "text-leaf-600", chip: "bg-leaf-100 text-leaf-800" },
	repair: { label: labels.kindRepair, icon: "wrench", dot: "bg-amber-500", bar: "bg-amber-500", text: "text-amber-600", chip: "bg-amber-100 text-amber-800" },
	booking: { label: labels.kindBooking, icon: "truck", dot: "bg-brand-500", bar: "bg-brand-500", text: "text-brand-600", chip: "bg-brand-100 text-brand-700" },
}

/** Kind order for dots and chips — the order a day is actually worked. */
export const KIND_ORDER = ["survey", "cleaning", "repair", "booking"]

/** "Booking in" / "Booking out" where the direction is the instruction; the kind name otherwise. */
export function kindLabel(item) {
	if (item.kind !== "booking") return KIND[item.kind]?.label || item.kind
	if (item.meta === "Tank In") return labels.kindBookingIn
	if (item.meta === "Tank Out") return labels.kindBookingOut
	return labels.kindBooking
}

// Survey and cleaning read exactly as their Desk lists do (utils/statusPill.js).
const SURVEY = {
	Scheduled: STAGE.ready.label,
	"In Progress": STAGE.doing.label,
	Completed: STAGE.done.label,
	Cancelled: STAGE.cancelled.label,
}
const CLEANING = {
	"Service Setup": labels.cleaningNotStarted,
	Pending: STAGE.ready.label,
	In_Progress: STAGE.doing.label,
	"Pending Review": STAGE.review.label,
	Completed: STAGE.done.label,
	Cancelled: STAGE.cancelled.label,
}
const BOOKING = {
	Draft: labels.statusPlanned,
	"Pending Payment": labels.statusUnpaid,
	"Pending Confirmation": labels.statusQueued,
	Confirmed: labels.statusPlanned,
	Completed: labels.scheduleDone,
	Cancelled: STAGE.cancelled.label,
}

// The chip's colour per word, by the Desk colour rule — the colour, not the text, is what a
// crew reads across a list of five. Keyed by the translated label, so two statuses that read
// the same always paint the same.
const COLOUR = new Map([
	...Object.values(STAGE).map((s) => [s.label, s.colour]),
	[labels.statusQueued, "orange"],
	[labels.statusNoBon, "orange"],
	[labels.statusUnpaid, "orange"],
	[repairStatusLabels["Pending Approval"], "orange"],
	[repairStatusLabels.Approved, "green"],
	[repairStatusLabels.Rejected, "red"],
])

/**
 * The one-word state of a card, plus the tone to paint it.
 *
 * A booking is the one kind whose headline status is not the useful one. "Confirmed" is true
 * of every booking on the grid and says nothing; what the yard acts on is whether the tanks
 * have moved (done) and whether a bon exists yet (the thing that has to happen before a truck
 * can be turned around at the barrier).
 */
export function statusChip(item) {
	let label
	if (item.kind === "booking") {
		const moved = Number(item.per_fulfilled) >= 100
		label = moved
			? item.meta === "Tank Out" ? labels.statusLeft : labels.statusArrived
			: item.bon_status === "Belum Dibon"
				? labels.statusNoBon
				: BOOKING[item.status] || item.status
	} else if (item.kind === "survey") {
		label = SURVEY[item.status] || item.status
	} else if (item.kind === "cleaning") {
		label = CLEANING[item.status] || item.status
	} else {
		label = repairStatusLabels[item.status] || item.status
	}
	return { label: label || "—", tone: tone(item.done ? "blue" : COLOUR.get(label)) }
}
