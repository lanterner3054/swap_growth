# Copyright (c) 2026, Adrian Ding and contributors
# For license information, please see license.txt

"""骑手增长分析：按周/月/季统计新开通、退租、净增、活跃骑手、流失率、续费率、月流水与 MRR 变动。"""

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
	summary = get_summary(rows)
	for r in rows:
		if r["partial"]:
			r["period"] += "（进行中）"

	return (
		get_columns(),
		rows,
		None,
		get_chart(rows, filters.get("chart_view") or "新开通与退租"),
		summary,
	)


def money_col(label, fieldname, width=110):
	return {"label": label, "fieldname": fieldname, "fieldtype": "Currency", "options": "CNY", "width": width}


def get_columns():
	return [
		{"label": "统计周期", "fieldname": "period", "fieldtype": "Data", "width": 130},
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
		money_col("月流水(MRR)", "mrr", 130),
		money_col("新增MRR", "mrr_new"),
		money_col("扩张MRR", "mrr_expansion", 105),
		money_col("恢复MRR", "mrr_reactivation", 105),
		money_col("收缩MRR", "mrr_contraction", 105),
		money_col("流失MRR", "mrr_churn"),
		money_col("净新增MRR", "mrr_net", 115),
		{
			"label": "增长质量比",
			"fieldname": "quick_ratio",
			"fieldtype": "Float",
			"precision": 2,
			"width": 100,
		},
		money_col("押金沉淀", "deposit", 120),
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
	elif view == "MRR 变动":
		datasets = [
			{"name": "新增", "values": [r["mrr_new"] for r in rows], "chartType": "bar"},
			{
				"name": "扩张+恢复",
				"values": [r["mrr_expansion"] + r["mrr_reactivation"] for r in rows],
				"chartType": "bar",
			},
			{
				"name": "流失+收缩",
				"values": [-(r["mrr_churn"] + r["mrr_contraction"]) for r in rows],
				"chartType": "bar",
			},
			{"name": "净新增", "values": [r["mrr_net"] for r in rows], "chartType": "line"},
		]
		colors = ["#30a46c", "#12a594", "#e5484d", "#0b6bcb"]
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
	qr = s["quick_ratio"]
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
			"label": "平均流失率（已结束周期）",
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
		{
			"value": qr if qr is not None else "-",
			"label": "增长质量比（MRR 得 ÷ 失）",
			"datatype": "Data",
			"indicator": "Green" if (qr or 0) >= 1 else "Red",
		},
	]
