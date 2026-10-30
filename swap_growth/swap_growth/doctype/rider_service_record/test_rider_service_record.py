# Copyright (c) 2026, Adrian Ding and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from swap_growth.swap_growth.doctype.rider_service_record.rider_service_record import next_rider_id


class TestRiderServiceRecord(FrappeTestCase):
	def setUp(self):
		self.station = frappe.get_all("Swap Station", limit=1, pluck="name")[0]
		self.rider_id = next_rider_id()

	def make(self, event_type, submit=True, **kw):
		doc = frappe.get_doc(
			{
				"doctype": "Rider Service Record",
				"event_type": event_type,
				"event_date": today(),
				"rider_id": self.rider_id,
				"rider_name": "单测骑手",
				"user_type": "个人骑手",
				"platform": "美团",
				"package": "单电月卡",
				"deposit_mode": "押金",
				"station": self.station,
				"channel": "站点地推",
				**kw,
			}
		).insert()
		if submit:
			doc.submit()
		return doc

	def test_lifecycle(self):
		opened = self.make("新开通")
		self.assertEqual(opened.monthly_fee, 269)
		self.assertEqual(opened.deposit_amount, 300)
		self.assertTrue(opened.district)
		self.assertRaises(frappe.ValidationError, self.make, "新开通")
		self.assertRaises(frappe.ValidationError, self.make, "退租")  # 缺少退租原因
		self.assertRaises(frappe.ValidationError, self.make, "升级套餐", package="单电月卡")

		upgraded = self.make("升级套餐", package="双电月卡")
		self.assertEqual(upgraded.previous_package, "单电月卡")

		churned = self.make("退租", churn_reason="价格偏高")
		self.assertEqual(churned.deposit_status, "待退还")
		self.assertRaises(frappe.ValidationError, self.make, "续费")

		returned = self.make("新开通")
		self.assertEqual(returned.is_returning, 1)

	def test_future_date(self):
		self.assertRaises(frappe.ValidationError, self.make, "新开通", event_date=add_days(today(), 1))
