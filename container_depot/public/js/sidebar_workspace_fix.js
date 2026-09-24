// Sidebar Desk terpental (atau hilang) begitu halaman di-refresh.
//
// Dua hal digabung di file ini karena sumbernya sama: cara Frappe menebak "sidebar mana yang
// harus dipasang untuk rute ini". Tebakan itu dijalankan ulang dari nol tiap kali halaman
// dimuat dingin (refresh / paste URL / redirect), dan pada bench ini tebakannya sering meleset:
//
//   1. /desk/container-inventory → sidebar KOSONG. Ini bug Frappe.
//      `set_workspace_sidebar` mencari sidebar lewat `get_workspace_sidebars(<entitas>)`, yaitu
//      mengumpulkan tiap item sidebar yang `link_to`-nya sama dengan nama entitas. Sidebar
//      "Container Depot" punya DUA item yang menunjuk ke "Container Inventory" — item
//      "Dashboard" (Workspace) dan item laporan "Container Inventory" (Report) — jadi nama
//      sidebar yang sama masuk dua kali. Daftar dua elemen itu dibaca sebagai "ambigu", lalu
//      jatuh ke cabang yang butuh `router.meta.module`; pada rute workspace module itu tidak
//      ada, sehingga `setup()` tak pernah dipanggil dan sidebar tak pernah dirender. Upstream
//      sudah menulis ulang bagian ini (`resolve_sidebar`) dan rilis di v16.2x; bench ini masih
//      16.18.3, jadi bagian intinya di-backport: daftar kandidat dibuat unik.
//
//   2. /desk/communication, /desk/customer, /desk/item, /desk/sales-invoice, … → pindah ke
//      sidebar Email / Selling / Stock / Invoicing. Ini bukan bug Frappe, tapi kebijakan
//      defaultnya: doctype yang dipakai bareng memang milik banyak sidebar, dan tanpa konteks
//      Frappe memilih sidebar modul asalnya. Untuk depo ini Container Depot adalah rumahnya —
//      begitu sebuah menu terdaftar di sidebar Container Depot, membukanya harus tetap di
//      Container Depot, bukan melempar user ke modul ERPNext. Aturannya ditegakkan di sini
//      supaya berlaku untuk SEMUA item sidebar, termasuk yang ditambahkan nanti; tidak perlu
//      menduplikat menu atau bikin rute khusus per doctype.
//
// Keduanya menempel di prototype, jadi ikut berlaku untuk instance sidebar yang sudah dibuat.

(function () {
	const Sidebar = frappe.ui?.Sidebar;
	if (!Sidebar) return;

	const APP = "container_depot";

	// --- 1. Backport: kandidat sidebar tidak boleh dobel -------------------------------------
	// Feature-detect, bukan bandingkan versi: `resolve_sidebar` lahir di commit yang menulis
	// ulang pemilihan sidebar, jadi kehadirannya penanda paling jujur bahwa Frappe di bench ini
	// sudah tahan duplikat.
	if (!Sidebar.prototype.resolve_sidebar) {
		const get_workspace_sidebars = Sidebar.prototype.get_workspace_sidebars;
		Sidebar.prototype.get_workspace_sidebars = function (link_to) {
			return [...new Set(get_workspace_sidebars.call(this, link_to))];
		};
	}

	// --- 2. Kebijakan: sidebar app ini jadi tuan rumah untuk menunya sendiri -----------------
	// Nama entitas rute, memakai pemetaan yang sama dengan Frappe:
	//   ["Container Depot"]                     → "Container Depot"   (page)
	//   ["List", "Customer"] / ["query-report", "X"] / ["Workspaces", "X"] → elemen kedua
	//   ["Workspaces", "private", "X"]          → "X"
	function entity_from_route(route) {
		if (!route || !route.length) return null;
		if (route.length === 1) return route[0];
		if (route.length === 3 && route[0] === "Workspaces" && route[1] === "private") {
			return route[2];
		}
		return route[1];
	}

	function is_own_sidebar(name) {
		return frappe.boot.workspace_sidebar_item[name.toLowerCase()]?.app === APP;
	}

	const set_workspace_sidebar = Sidebar.prototype.set_workspace_sidebar;
	Sidebar.prototype.set_workspace_sidebar = function (router) {
		try {
			const entity = entity_from_route(frappe.get_route());
			const candidates = entity ? this.get_workspace_sidebars(entity) : [];

			// Dipakai `show_sidebar_for_module` — dipanggil belakangan oleh halaman report/page
			// untuk memindahkan sidebar ke modul dokumennya. Tanpa daftar ini halaman seperti
			// /desk/query-report/Stock Balance akan menarik sidebar ke "Stock" sesudah kita
			// memasang yang benar.
			this.preferred_sidebars = candidates;

			// Sidebar yang sedang terpasang sudah memuat rute ini → jangan diganggu. Ini yang
			// menjaga user yang memang sedang bekerja di sidebar ERPNext (Selling, Stock, …)
			// tetap di sana saat berpindah halaman.
			let target =
				this.sidebar_title && candidates.includes(this.sidebar_title)
					? this.sidebar_title
					: candidates.find(is_own_sidebar);

			if (target) {
				if (target === this.sidebar_title) {
					this.set_active_workspace_item();
				} else {
					this.setup(target);
				}
				return;
			}
		} catch (e) {
			console.log(e);
		}

		// Bukan menu app ini (atau ada yang tidak beres di atas) → serahkan ke Frappe.
		return set_workspace_sidebar.call(this, router);
	};

	// --- 3. Dua menu, satu doctype, dibedakan route_options ----------------------------------
	// "M&R" dan "Periodic Test" sama-sama Repair Order (lihat mr_scope.py), bedanya cuma
	// ?job_type=. `is_route_in_sidebar` Frappe mencocokkan path saja (query dibuang), jadi
	// dua item itu kembar dan yang terakhir — Periodic Test — selalu menyala, di menu mana pun
	// user berada. Untuk doctype yang punya item ber-query, pilih item yang query-nya cocok
	// dengan filter list / isi dokumen yang sedang dibuka. Filter list baru terpasang sesudah
	// rute berganti, jadi list/form doctype itu memanggil `set_active_workspace_item()` lagi
	// di `refresh`-nya.
	function current_values(doctype) {
		const view = frappe.get_route()[0];
		if (view === "List" && window.cur_list?.doctype === doctype) {
			const eq = cur_list.filters.filter((f) => f[2] === "=");
			return Object.fromEntries(eq.map((f) => [f[1], f[3]]));
		}
		if (view === "Form" && window.cur_frm?.doctype === doctype) return cur_frm.doc;
		return {};
	}

	const is_route_in_sidebar = Sidebar.prototype.is_route_in_sidebar;
	Sidebar.prototype.is_route_in_sidebar = function () {
		const [view, doctype] = frappe.get_route();
		const base = ["List", "Form"].includes(view) && `/desk/${frappe.router.slug(doctype)}`;
		const twins = $(".item-anchor")
			.toArray()
			.filter((a) => {
				const [path, query] = (a.getAttribute("href") || "").split("?");
				return base && query && path.replace(/\/view\/list$/, "") === base;
			});
		if (!twins.length) return is_route_in_sidebar.call(this);

		const values = current_values(doctype);
		const hit = twins.find((a) =>
			[...new URLSearchParams(a.getAttribute("href").split("?")[1])].every(
				([k, v]) => String(values[k] ?? "") === v
			)
		);
		if (this.active_item) this.active_item.removeClass("active-sidebar");
		this.active_item = hit ? $(hit).parent() : null;
		return !!hit;
	};
})();
