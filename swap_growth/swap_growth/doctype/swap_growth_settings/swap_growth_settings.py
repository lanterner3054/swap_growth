# Copyright (c) 2026, Adrian Ding and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

DEFAULT_MODELS = {"DeepSeek": "deepseek-chat", "智谱GLM": "glm-4-flash"}
DEFAULT_BASE_URLS = {
	"DeepSeek": "https://api.deepseek.com",
	"智谱GLM": "https://open.bigmodel.cn/api/paas/v4",
}


class SwapGrowthSettings(Document):
	def validate(self):
		if not self.cache_hours or self.cache_hours <= 0:
			self.cache_hours = 3
		if not self.timeout or self.timeout < 10:
			self.timeout = 90

	def resolved_model(self):
		return (self.model or "").strip() or DEFAULT_MODELS.get(self.provider, "deepseek-chat")

	def resolved_base_url(self):
		return ((self.base_url or "").strip() or DEFAULT_BASE_URLS.get(self.provider, "")).rstrip("/")


@frappe.whitelist()
def test_connection():
	frappe.only_for(("System Manager", "运营总监"))
	from swap_growth.analysis import call_llm

	settings = frappe.get_single("Swap Growth Settings")
	reply = call_llm(
		settings,
		[{"role": "user", "content": '请只回复 JSON：{"ok": true, "message": "连接成功"}'}],
		max_tokens=50,
	)
	return {"model": settings.resolved_model(), "reply": reply}


@frappe.whitelist()
def regenerate_demo_data():
	from swap_growth.demo.generator import reset_demo_data

	return reset_demo_data()


@frappe.whitelist()
def demo_stats():
	frappe.has_permission("Swap Growth Settings", "read", throw=True)
	return {
		"stations": frappe.db.count("Swap Station"),
		"records": frappe.db.count("Rider Service Record", {"docstatus": 1}),
		"riders": frappe.db.sql(
			"select count(distinct rider_id) from `tabRider Service Record` where docstatus=1"
		)[0][0],
		"analyses": frappe.db.count("Data Analysis Record"),
		"range": frappe.db.sql(
			"select min(event_date), max(event_date) from `tabRider Service Record` where docstatus=1"
		)[0],
	}
