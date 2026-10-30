# Copyright (c) 2026, Adrian Ding and contributors
# For license information, please see license.txt

"""骑手增长分析：按周/月/季统计新开通、退租、净增、活跃骑手、流失率、续费率与月流水。"""

import frappe
from frappe.utils import flt, fmt_money

from swap_growth.metrics import (
	build_periods,
	default_range,
	load_events,
	period_table,
	resolve_districts,
	summarize,
)


def execute(filters=None):
	filters = frappe._dict(filters or {})
	start, end = default_range()
	from_date = filters.get("from_date") or start
	to_date = filters.get("to_date") or end
	granularity = filters.get("granularity") or "月"

	districts = resolve_districts(filters.get("district"))
	events = load_events(districts, upto=to_date)
	rows = period_table(events, build_periods(from_date, to_date, granularity), filters)

	return (
		get_columns(),
		rows,
		None,
		get_chart(rows, filters.get("chart_view") or "新开通与退租"),
		get_summary(rows),
	)


def get_columns():
	return [
		{"label": "统计周期", "fieldname": "period", "fieldtype": "Data", "width": 110},
		{"label": "期初活跃", "fieldname": "opening", "fieldtype": "Int", "width": 95},
		{"label": "新开通", "fieldname": "new", "fieldtype": "Int", "width": 85},
		{"label": "其中回流", "fieldname": "returning", "fieldtype": "Int", "width": 85},
		{"label": "续费", "fieldname": "renew", "fieldtype": "Int", "width": 80},
		{"label": "升级", "fieldname": "upgrade", "fieldtype": "Int", "width": 70},
		{"label": "暂停", "fieldname": "pause", "fieldtype": "Int", "width": 70},
		{"label": "退租", "fieldname": "churn", "fieldtype": "Int", "width": 80},
		{"label": "净增", "fieldname": "net", "fieldtype": "Int", "width": 80},
		{"label": "期末活跃", "fieldname": "closing", "fieldtype": "Int", "width": 95},
		{"label": "流失率", "fieldname": "churn_rate", "fieldtype": "Percent", "width": 90},
		{"label": "续费率", "fieldname": "renew_rate", "fieldtype": "Percent", "width": 90},
		{"label": "月流水(MRR)", "fieldname": "mrr", "fieldtype": "Currency", "options": "CNY", "width": 130},
		{
			"label": "押金沉淀",
			"fieldname": "deposit",
			"fieldtype": "Currency",
			"options": "CNY",
			"width": 120,
		},
	]


def get_chart(rows, view):
	labels = [r["period"] for r in rows]
	if view == "活跃骑手趋势":
		datasets = [{"name": "期末活跃骑手", "values": [r["closing"] for r in rows], "chartType": "line"}]
		colors = ["#0b6bcb"]
	elif view == "流失率与续费率":
		datasets = [
			{"name": "流失率%", "values": [r["churn_rate"] for r in rows], "chartType": "line"},
			{"name": "续费率%", "values": [r["renew_rate"] for r in rows], "chartType": "line"},
		]
		colors = ["#e5484d", "#30a46c"]
	elif view == "月流水":
		datasets = [{"name": "月流水(元)", "values": [r["mrr"] for r in rows], "chartType": "bar"}]
		colors = ["#7c66dc"]
	else:
		datasets = [
			{"name": "新开通", "values": [r["new"] for r in rows], "chartType": "bar"},
			{"name": "退租", "values": [r["churn"] for r in rows], "chartType": "bar"},
			{"name": "净增", "values": [r["net"] for r in rows], "chartType": "line"},
		]
		colors = ["#30a46c", "#e5484d", "#0b6bcb"]
	return {
		"data": {"labels": labels, "datasets": datasets},
		"type": "axis-mixed",
		"colors": colors,
		"height": 280,
		"axisOptions": {"xIsSeries": 1},
		"lineOptions": {"regionFill": 0, "dotSize": 4},
	}


def get_summary(rows):
	s = summarize(rows)
	if not s:
		return []
	return [
		{"value": s["closing"], "label": "期末活跃骑手", "datatype": "Int", "indicator": "Blue"},
		{
			"value": s["new"],
			"label": f"新开通（含回流 {s['returning']}）",
			"datatype": "Int",
			"indicator": "Green",
		},
		{"value": s["churn"], "label": "退租", "datatype": "Int", "indicator": "Red"},
		{
			"value": s["net"],
			"label": "净增",
			"datatype": "Int",
			"indicator": "Green" if s["net"] >= 0 else "Red",
		},
		{
			"value": f"{s['avg_churn_rate']}%",
			"label": "平均流失率",
			"datatype": "Data",
			"indicator": "Orange",
		},
		{"value": f"{s['avg_renew_rate']}%", "label": "平均续费率", "datatype": "Data", "indicator": "Green"},
		{
			"value": fmt_money(flt(s["mrr"]), currency="CNY", precision=0),
			"label": "期末月流水",
			"datatype": "Data",
			"indicator": "Purple",
		},
	]
