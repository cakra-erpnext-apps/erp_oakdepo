"""Connections tab on Order Bongkar — the work each container's arrival raised."""


def get_data():
	return {
		"fieldname": "order_bongkar",
		"non_standard_fieldnames": {"Inspection": "referred_voucher"},
		"transactions": [{"label": "Pekerjaan Depo", "items": ["Inspection", "Leak Check"]}],
	}
