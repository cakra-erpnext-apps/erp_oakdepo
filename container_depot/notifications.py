"""What counts as "open" for the depot's work orders.

Frappe puts two numbers on every Connections link: the total, and — for doctypes that
declare an open filter — how many of those are still outstanding. ERPNext supplies that
filter for every submittable doctype in the system, ours included, as a blanket
``{"docstatus": 0}`` (see ``erpnext/startup/notifications.py``). That rule is wrong here in
both directions:

* **Cleaning Order** is submittable, so it inherited "open = draft". But a cleaning job's
  life is in its ``status`` (Service Setup → Pending → In_Progress → Completed), and
  submitting is a separate act — a Completed order left unsubmitted counted as open, a
  Cancelled one too.
* **Repair Order** and **Periodic Test Order** are NOT submittable, so they got no filter at
  all and never showed the badge — a booking with two repairs in progress looked as quiet
  as one with none.

Declaring them here fixes both: the badge now means "work not finished", the same thing on
all three. This hook is merged after ERPNext's (config[key].update, app install order), so
these entries replace the blanket rule rather than fighting it.

Inspection is deliberately left alone: a draft EIR *is* the unfinished work, so the
inherited docstatus rule already says the right thing.
"""

# Terminal states, per doctype. Anything else is work someone still has to finish.
_CLEANING_DONE = ("Completed", "Cancelled")
_WORK_ORDER_DONE = ("Completed", "Cancelled", "Rejected")


def get_notification_config():
	return {
		"for_doctype": {
			"Cleaning Order": {"status": ("not in", _CLEANING_DONE)},
			"Repair Order": {"status": ("not in", _WORK_ORDER_DONE)},
			"Periodic Test Order": {"status": ("not in", _WORK_ORDER_DONE)},
		}
	}
