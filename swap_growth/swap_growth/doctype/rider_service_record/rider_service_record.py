# Copyright (c) 2026, Adrian Ding and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import getdate, today

from swap_growth.constants import (
	DEPOSIT_AMOUNT,
	EVENT_CHURN,
	EVENT_NEW,
	EVENT_PAUSE,
	EVENT_RENEW,
	EVENT_UPGRADE,
	PACKAGE_RANK,
	PACKAGES,
	REALTIME_EVENT,
)

PROFILE_FIELDS = [
	"rider_name",
	"phone",
	"user_type",
	"team_name",
	"platform",
	"package",
	"deposit_mode",
	"station",
	"district",
	"channel",
	"account_manager",
]


class RiderServiceRecord(Document):
	def validate(self):
		if getdate(self.event_date) > getdate(today()):
			frappe.throw("发生日期不能晚于今天")
		self.monthly_fee = PACKAGES.get(self.package, 0)
		last = get_last_event(self.rider_id, exclude=self.name)
		self.validate_lifecycle(last)
		self.set_deposit(last)
		if not self.account_manager and self.district:
			self.account_manager = frappe.db.get_value("Swap District", self.district, "manager")
		if self.event_type == EVENT_CHURN and not self.churn_reason:
			frappe.throw("退租单据必须填写退租原因，用于流失归因分析")
		if self.event_type != EVENT_CHURN:
			self.churn_reason = None

	def validate_lifecycle(self, last):
		"""校验骑手生命周期：未在租只能新开通，在租不能重复开通。"""
		in_service = bool(last and last.event_type != EVENT_CHURN)
		if self.event_type == EVENT_NEW:
			if in_service:
				frappe.throw(
					f"骑手 {self.rider_id} 当前仍在租（最近事件：{last.event_type}），请录入续费、升级或退租"
				)
			self.is_returning = 1 if last else 0
			return
		if not in_service:
			frappe.throw(f"骑手 {self.rider_id} 当前不在租，请先录入「新开通」")
		if getdate(self.event_date) < getdate(last.event_date):
			frappe.throw(f"发生日期不能早于该骑手上一次事件（{last.event_date}）")
		if self.event_type == EVENT_PAUSE and last.event_type == EVENT_PAUSE:
			frappe.throw("该骑手已处于暂停状态")
		if self.event_type == EVENT_UPGRADE:
			self.previous_package = last.package
			if PACKAGE_RANK.get(self.package, 0) <= PACKAGE_RANK.get(last.package, 0):
				frappe.throw(f"升级后的套餐需高于原套餐（{last.package}）")
		if self.event_type == EVENT_RENEW and last.package and not self.package:
			self.package = last.package

	def set_deposit(self, last):
		if self.event_type != EVENT_NEW and last and last.deposit_mode:
			# 押金方式以开通时为准，后续事件沿用
			self.deposit_mode = last.deposit_mode
		self.deposit_amount = DEPOSIT_AMOUNT if self.deposit_mode == "押金" else 0
		if self.deposit_mode == "信用免押":
			self.deposit_status = "已免押"
		elif self.event_type == EVENT_CHURN:
			if self.deposit_status != "已退还":
				self.deposit_status = "待退还"
		else:
			self.deposit_status = "已缴纳"

	def on_submit(self):
		frappe.publish_realtime(
			REALTIME_EVENT,
			{
				"name": self.name,
				"event_type": self.event_type,
				"rider_name": mask_name(self.rider_name),
				"district": self.district,
				"station": frappe.db.get_value("Swap Station", self.station, "station_name"),
				"package": self.package,
				"churn_reason": self.churn_reason,
				"event_date": str(self.event_date),
			},
			after_commit=True,
		)
		clear_dashboard_cache()

	def on_cancel(self):
		clear_dashboard_cache()


def get_last_event(rider_id, exclude=None):
	if not rider_id:
		return None
	filters = {"rider_id": rider_id, "docstatus": 1}
	if exclude:
		filters["name"] = ("!=", exclude)
	rows = frappe.get_all(
		"Rider Service Record",
		filters=filters,
		fields=["name", "event_type", "event_date", "package", "deposit_mode"],
		order_by="event_date desc, creation desc",
		limit=1,
	)
	return rows[0] if rows else None


def mask_name(name):
	if not name:
		return ""
	return name[0] + "*" * (len(name) - 1)


def clear_dashboard_cache():
	frappe.cache.delete_keys("swap_growth:dashboard")


@frappe.whitelist()
def get_rider_profile(rider_id):
	"""录单时根据骑手编号带出画像，减少重复录入。"""
	frappe.has_permission("Rider Service Record", "read", throw=True)
	rows = frappe.get_list(
		"Rider Service Record",
		filters={"rider_id": rider_id, "docstatus": 1},
		fields=PROFILE_FIELDS + ["event_type", "event_date"],
		order_by="event_date desc, creation desc",
		limit=1,
	)
	if not rows:
		return None
	profile = rows[0]
	profile["in_service"] = profile.event_type != EVENT_CHURN
	return profile


@frappe.whitelist()
def next_rider_id():
	frappe.has_permission("Rider Service Record", "create", throw=True)
	last = frappe.db.sql(
		"""select max(cast(substring(rider_id, 2) as unsigned)) from `tabRider Service Record`
		where rider_id like 'R%%'"""
	)[0][0]
	return f"R{(int(last or 0) + 1):06d}"
