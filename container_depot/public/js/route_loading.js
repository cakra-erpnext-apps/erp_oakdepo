// Skeleton Desk selama pindah menu.
//
// Klik sidebar → `frappe.router.route()` → factory menunggu meta doctype (`with_doctype`) dan,
// untuk form, dokumennya (`with_doc`) sebelum `frappe.container.change_to()` menukar halaman.
// Selama itu halaman LAMA tetap di layar tanpa tanda apa pun; di server yang lambat itu bisa
// beberapa detik dan terlihat seperti klik yang tidak jalan.
//
// Jadi: begitu route mulai, halaman lama disembunyikan dan skeleton dipasang di #body, sampai
// `page-change` (dipicu `change_to`, satu-satunya pintu semua jenis halaman). Setelah itu
// skeleton milik halaman sendiri yang ambil alih (list-skeleton di List, loader di Report).
//
// Ditunda SHOW_DELAY_MS supaya pindah ke halaman yang sudah pernah dibuka (instan, tanpa
// request) tidak berkedip. Jalan buntu — 403/404 saat memuat meta atau dokumen, yang tidak
// pernah berakhir di `change_to` — ditutup oleh error request itu sendiri dan batas GIVE_UP_MS.
// Error request LAIN (polling notifikasi dsb.) sengaja tidak dihitung: menutup skeleton lebih
// awal justru memunculkan lagi halaman lama di bawah URL baru.
//
// Route basi: `route()` menunggu `parse()` (meta doctype dari server) lalu tetap merender
// hasilnya walau URL sudah pindah. Klik menu A (meta belum ada, lambat), lalu klik B (meta
// sudah ada, instan): B tampil, lalu A menyusul dan menimpanya — URL B, isi A. Frappe
// 16.27.1 pun belum menjaganya, jadi `parse()` dibungkus: kalau URL berubah selama menunggu,
// route lama tidak pernah selesai (promise yang tidak pernah resolve), yang baru yang render.
(function () {
	const SHOW_DELAY_MS = 150;
	const GIVE_UP_MS = 60000;
	const ROUTE_LOAD_CMDS = ["frappe.desk.form.load.getdoctype", "frappe.desk.form.load.getdoc"];
	const router = frappe.router;
	if (!router || typeof router.route !== "function") return;

	let show_timer = null;
	let give_up_timer = null;
	let $skeleton = null;

	function skeleton_html() {
		const rows = Array.from({ length: 8 }, () => '<div class="cd-sk cd-sk-row"></div>').join("");
		return `<div class="cd-route-skeleton container" aria-busy="true" aria-label="${__("Loading...")}">
			<div class="cd-sk-head">
				<div class="cd-sk cd-sk-title"></div>
				<div class="cd-sk cd-sk-btn"></div>
			</div>
			<div class="cd-sk-card">${rows}</div>
		</div>`;
	}

	function show() {
		if (!$skeleton) $skeleton = $(skeleton_html()).appendTo("#body");
		document.body.classList.add("cd-route-loading");
	}

	function hide() {
		clearTimeout(show_timer);
		clearTimeout(give_up_timer);
		show_timer = give_up_timer = null;
		document.body.classList.remove("cd-route-loading");
		$skeleton?.remove();
		$skeleton = null;
	}

	const route = router.route;
	router.route = function () {
		hide();
		show_timer = setTimeout(show, SHOW_DELAY_MS);
		give_up_timer = setTimeout(hide, GIVE_UP_MS);
		return route.apply(this, arguments);
	};

	const parse = router.parse;
	router.parse = async function (route) {
		const sub_path = this.get_sub_path();
		const parsed = await parse.apply(this, arguments);
		// Hanya panggilan dari route() (tanpa argumen) yang membaca URL saat ini.
		if (route === undefined && this.get_sub_path() !== sub_path) return new Promise(() => {});
		return parsed;
	};

	$(document).on("page-change", hide);
	$(document).ajaxError((e, xhr, settings) => {
		if (ROUTE_LOAD_CMDS.some((cmd) => (settings?.url || "").includes(cmd))) hide();
	});
})();
