# Copyright (c) 2026, Adrian Ding and contributors
# For license information, please see license.txt

"""流失预警名单：对当前活跃骑手按规则打分，输出风险原因，支持一键指派跟进。"""

import frappe

from swap_growth.metrics import clean_filters, load_events, resolve_districts
from swap_growth.risk import score_riders


def execute(filters=None):
	filters = frappe._dict(filters or {})
	districts = resolve_districts(filters.get("district"))
	riders, active = score_riders(load_events(districts), districts, clean_filters(filters))
	high = sum(1 for r in riders if r["level"] == "高")
	medium = len(riders) - high
	if filters.get("level"):
		riders = [r for r in riders if r["level"] == filters.level]

	open_todos = {
		t.reference_name: t.allocated_to
		for t in frappe.get_all(
			"ToDo",
			filters={"reference_type": "Rider Service Record", "status": "Open"},
			fields=["reference_name", "allocated_to"],
		)
	}
	data = []
	for r in riders:
		data.append(
			{
				**r,
				"reasons_text": "；".join(r["reasons"]),
				"follow_up": open_todos.get(r["last_record"]) or "",
			}
		)

	summary = [
		{"value": active, "label": "当前活跃骑手", "datatype": "Int", "indicator": "Blue"},
		{"value": high, "label": "高风险", "datatype": "Int", "indicator": "Red"},
		{"value": medium, "label": "中风险", "datatype": "Int", "indicator": "Orange"},
		{
			"value": sum(1 for d in data if d["follow_up"]),
			"label": "已指派跟进",
			"datatype": "Int",
			"indicator": "Green",
		},
	]
	return get_columns(), data, None, None, summary


def get_columns():
	return [
		{"label": "风险分", "fieldname": "score", "fieldtype": "Int", "width": 80},
		{"label": "等级", "fieldname": "level", "fieldtype": "Data", "width": 70},
		{"label": "骑手编号", "fieldname": "rider_id", "fieldtype": "Data", "width": 95},
		{"label": "骑手", "fieldname": "rider_name", "fieldtype": "Data", "width": 85},
		{
			"label": "所在区",
			"fieldname": "district",
			"fieldtype": "Link",
			"options": "Swap District",
			"width": 85,
		},
		{"label": "常用站点", "fieldname": "station_name", "fieldtype": "Data", "width": 110},
		{"label": "套餐", "fieldname": "package", "fieldtype": "Data", "width": 105},
		{"label": "平台", "fieldname": "platform", "fieldtype": "Data", "width": 80},
		{"label": "状态", "fieldname": "status", "fieldtype": "Data", "width": 70},
		{
			"label": "近2周日均换电",
			"fieldname": "recent_swaps",
			"fieldtype": "Float",
			"precision": 1,
			"width": 110,
		},
		{"label": "风险信号", "fieldname": "reasons_text", "fieldtype": "Data", "width": 420},
		{"label": "跟进人", "fieldname": "follow_up", "fieldtype": "Data", "width": 170},
		{
			"label": "最近单据",
			"fieldname": "last_record",
			"fieldtype": "Link",
			"options": "Rider Service Record",
			"width": 130,
		},
	]
