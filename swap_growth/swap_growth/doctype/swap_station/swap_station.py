# Copyright (c) 2026, Adrian Ding and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class SwapStation(Document):
	def validate(self):
		if self.slots is not None and self.slots < 0:
			frappe.throw("柜机格口数不能为负数")
		if not (self.longitude and self.latitude) and self.district:
			# 未填写坐标时，默认落在所在区中心点，保证大屏地图可展示
			center = frappe.db.get_value(
				"Swap District", self.district, ["center_lng", "center_lat"], as_dict=True
			)
			if center:
				self.longitude = self.longitude or center.center_lng
				self.latitude = self.latitude or center.center_lat
