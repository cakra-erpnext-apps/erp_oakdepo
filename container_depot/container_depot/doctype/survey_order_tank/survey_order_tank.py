# Copyright (c) 2026, Oak Depot Team and contributors
# For license information, please see license.txt

"""One outbound tank on a Survey Order — its lowering and its survey, and nothing else.

**The tank's LOCATION is deliberately not a field here.** Where a tank stands is a fact about
the tank, recorded whenever anyone in the yard checks it (``Container Position``), and it goes
on living long after this booking is over. Copying it onto this row would freeze it: the row
would keep showing where the tank was when the schedule was written, while the master had
since been corrected twice. So the screens read ``Container.current_location`` and
``location_updated_on`` live, which also lets them say how old that answer is.

What DOES belong here is per-booking: this pickup's lowering and this pickup's survey. A tank
collected twice has two of them, on two schedules, and neither is a fact about the tank.
"""

from frappe.model.document import Document


class SurveyOrderTank(Document):
	pass
