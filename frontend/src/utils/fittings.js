/**
 * Kelengkapan tank, dikelompokkan per kompartemen — untuk daftar yang HANYA dibaca.
 *
 * Sebuah tank dua kompartemen mengulang setiap slot yang sama untuk masing-masing bagian,
 * jadi daftar datar 24 baris menampilkan "Seal Manlid · Depan: 2" dua kali tanpa satu pun
 * petunjuk ujung mana yang mana. Pengelompokannya menjaga urutan baris apa adanya: barisnya
 * sudah diurut sesuai `sequence` master waktu EIR-nya ditulis (`_build_fitting_rows`), dan
 * urutan itu adalah urutan kotak isian di form EIR cetak — kertas yang dipegang surveyor
 * sambil membaca layar ini.
 *
 * Form isiannya sendiri TIDAK memakai ini (lihat TankFittings.vue): di sana satu item dengan
 * beberapa slot dijadikan satu baris berisi beberapa kotak, bentuk yang cuma masuk akal kalau
 * kotaknya bisa diisi.
 */
export function groupByCompartment(rows) {
	const groups = []
	for (const r of rows || []) {
		const compartment = r.compartment || ""
		const last = groups[groups.length - 1]
		if (last && last.compartment === compartment) last.items.push(r)
		else groups.push({ compartment, items: [r] })
	}
	return groups
}
