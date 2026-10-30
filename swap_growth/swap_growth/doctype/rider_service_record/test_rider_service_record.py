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

	def test_cancel_only_latest(self):
		self.make("新开通")
		renew = self.make("续费")
		opened = frappe.get_all(
			"Rider Service Record", filters={"rider_id": self.rider_id, "event_type": "新开通"}, pluck="name"
		)[0]
		self.assertRaises(frappe.ValidationError, frappe.get_doc("Rider Service Record", opened).cancel)
		renew.cancel()  # 最近一张可以作废
		self.assertEqual(renew.docstatus, 2)

	def test_reopen_not_before_churn(self):
		self.make("新开通", event_date=add_days(today(), -10))
		self.make("退租", event_date=add_days(today(), -2), churn_reason="价格偏高")
		self.assertRaises(frappe.ValidationError, self.make, "新开通", event_date=add_days(today(), -5))


class TestMetrics(FrappeTestCase):
	def test_mrr_movements_reconcile(self):
		"""期初 MRR + 新增 + 扩张 + 恢复 - 收缩 - 流失 = 期末 MRR。"""
		from swap_growth.metrics import build_periods, default_range, load_events, period_table

		start, end = default_range()
		for r in period_table(load_events(), build_periods(start, end, "月")):
			self.assertAlmostEqual(r["mrr_opening"] + r["mrr_net"], r["mrr"], places=2, msg=r["period"])
