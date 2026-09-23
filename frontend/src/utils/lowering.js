// Tandai Lowered dengan satu centang — dipakai list Kalmar, detail jadwal, dan detail tank.
//
// Tanpa letak, tanpa foto, tanpa konfirmasi: letak dicatat SEBELUM lowering di menu Letak
// Tank (supaya Kalmar tahu harus ke mana), dan salah centang dibatalkan dari Riwayat. Satu
// ketukan untuk satu tank yang sudah di tanah.

import { send } from "@/data/send"
import { labels } from "@/utils/labels"
import { toast } from "@/utils/toast"

export async function lowerTank(row) {
	try {
		await send({ url: "container_depot.ess.tank_survey.survey_lowered", payload: { name: row.name } })
		toast.success(labels.posLoweredDone, { title: row.container_no || row.container || row.name })
		return true
	} catch (e) {
		toast.error(e?.message || labels.error)
		return false
	}
}
