// Gate Out Plan target lift-on → the countdown badge every worklist shows.
//
// One definition for every worklist (EIR, Cleaning, M&R, Survey Posisi, Fix Posisi): the
// badge is a vocabulary an operator learns once — "H-3" is three days to pickup, "Hari-H" is
// today, "Lewat 2 hr" is two days overdue — and a second copy of it would eventually
// disagree about the colour of urgency, which is the one thing the badge exists to say.
//
// The stamp is a plain date, so it is compared date-to-date in local time: parsing it as
// "YYYY-MM-DDT00:00:00" (rather than letting Date treat a bare date as UTC) keeps H-0 on the
// day the customer actually comes, in Jakarta rather than in London.
export const liftDays = (v) => {
	if (!v) return null
	const target = new Date(String(v).slice(0, 10) + "T00:00:00")
	const today = new Date(new Date().toDateString())
	return Math.round((target - today) / 86400000)
}

export const hMinus = (v) => {
	const d = liftDays(v)
	if (d === null) return ""
	if (d < 0) return `Lewat ${-d} hr`
	if (d === 0) return "Hari-H"
	return `H-${d}`
}

export const liftClass = (v) => {
	const d = liftDays(v)
	if (d === null) return ""
	if (d <= 1) return "text-red-600"
	if (d <= 3) return "text-amber-600"
	return "text-brand-600"
}
