// "10%" or "50000" boxes (Sales Invoice, Payment Entry). Mirrors invoicing.parse_smart.
frappe.provide("container_depot");

// "11%" -> ["pct", 11]; "50.000" -> ["amt", 50000]; blank -> [null, 0]. Same reading as the
// server's invoicing.parse_smart: with both separators the last one is the decimal point, a
// strict thousands pattern is grouping, anything else is a decimal.
container_depot.parse_smart = function (raw) {
	const str = (raw == null ? "" : String(raw)).trim();
	if (!str) return [null, 0];
	const s = str.replace(/[^\d.,-]/g, "");
	const ld = s.lastIndexOf(".");
	const lc = s.lastIndexOf(",");
	let dec = null;
	if (ld !== -1 && lc !== -1) dec = ld > lc ? "." : ",";
	else if (lc !== -1) dec = /^-?\d{1,3}(,\d{3})+$/.test(s) ? null : ",";
	else if (ld !== -1) dec = /^-?\d{1,3}(\.\d{3})+$/.test(s) ? null : ".";
	const int = dec ? s.slice(0, s.lastIndexOf(dec)) : s;
	const frac = dec ? s.slice(s.lastIndexOf(dec) + 1) : "";
	const num = parseFloat(int.replace(/[.,]/g, "") + (frac ? "." + frac.replace(/[.,]/g, "") : "")) || 0;
	return [str.includes("%") ? "pct" : "amt", num];
};
