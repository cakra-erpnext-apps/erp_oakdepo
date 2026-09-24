// Jenis notifikasi yang dimatikan operator di HP ini — bel dan push sama-sama diam untuknya.
//
// Disimpan di localStorage (dikunci per user, lihat userPicks.js), jadi per perangkat: HP
// gate boleh diam soal M&R sementara HP kantor orang yang sama tetap berbunyi. Server ikut
// memegang salinannya di baris Depot Push Subscription perangkat ini (dikirim tiap
// subscribe, data/push.js) karena push dikirim saat aplikasi tertutup.

import { createPicks } from "@/utils/userPicks"

const picks = createPicks("oak-notif-muted")

/** event_key yang dimatikan — `[]` kalau belum pernah diatur. */
export const mutedEvents = (user) => picks.picked(user) || []
export const setMuted = picks.set
