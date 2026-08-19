// Do we currently have a working link to the server?
//
// Not `navigator.onLine`: that only says whether the device is attached to a network, and on
// depot wifi it is regularly true while nothing can actually be reached. So the flag means
// "no evidence the link is down", and every part of the app that touches the network reports
// what it saw — the read cache when a GET goes unanswered, the sender when a save does or
// does not land.
//
// It exists for two screens and nothing else now that nothing is queued:
//
//   * the app-wide banner, because the read cache (data/cache.js) may be showing worklists
//     from the last connection and the operator has to know that is what they are reading;
//   * the gate, which genuinely cannot work without a live answer (payment + block status).
//
// It no longer gates saving. Deciding in advance whether a save would work is what parked a
// day of sign-offs on a handset; a save now simply tries and reports what happened.

import { reactive } from "vue"

const state = reactive({
	online: navigator.onLine !== false,
	sessionExpired: false,
})

export const link = state

/** A request found nothing at the other end. */
export function noteLinkDown() {
	state.online = false
}

/** Something got through. Any success clears the flag, whoever observed it. */
export function noteLinkUp() {
	if (navigator.onLine !== false) {
		state.online = true
		state.sessionExpired = false
	}
}

/** The server refused us for being logged out — worth saying differently from "offline". */
export function noteSessionExpired() {
	state.sessionExpired = true
}

window.addEventListener("online", noteLinkUp)
window.addEventListener("offline", noteLinkDown)
