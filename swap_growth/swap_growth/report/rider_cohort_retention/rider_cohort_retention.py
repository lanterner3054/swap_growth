# Copyright (c) 2026, Adrian Ding and contributors
# For license information, please see license.txt

"""同期群留存：按骑手首次开通月份分组，观察第 N 个月末仍在服务的比例。"""

import frappe

from swap_growth.metrics import cohort_table, default_range, load_events, resolve_districts

MAX_OFFSET = 11


def execute(filters=None):
	filters = frappe._dict(filters or {})
	start, end = default_range()
	from_date = filters.get("from_date") or start
	to_date = filters.get("to_date") or end
	districts = resolve_districts(filters.get("district"))
	rows = cohort_table(load_events(districts), from_date, to_date, filters, MAX_OFFSET)
	return get_columns(), rows, None, get_chart(rows), get_summary(rows)


def get_columns():
	cols = [
		{"label": "开通月份", "fieldname": "cohort", "fieldtype": "Data", "width": 100},
		{"label": "开通人数", "fieldname": "size", "fieldtype": "Int", "width": 90},
	]
	for k in range(MAX_OFFSET + 1):
		cols.append(
			{
				"label": "当月末" if k == 0 else f"第{k}月",
				"fieldname": f"m{k}",
				"fieldtype": "Percent",
				"width": 78,
			}
		)
	return cols


def weighted_curve(rows):
	curve = []
	for k in range(MAX_OFFSET + 1):
		num = den = 0
		for r in rows:
			if r.get(f"m{k}") is not None and r["size"]:
				num += r[f"m{k}"] * r["size"]
				den += r["size"]
		curve.append(round(num / den, 1) if den else None)
	return curve


def get_chart(rows):
	curve = weighted_curve(rows)
	points = [(f"第{k}月" if k else "当月末", v) for k, v in enumerate(curve) if v is not None]
	return {
		"data": {
			"labels": [p[0] for p in points],
			"datasets": [{"name": "加权平均留存率%", "values": [p[1] for p in points]}],
		},
		"type": "line",
		"colors": ["#0b6bcb"],
		"height": 240,
		"lineOptions": {"regionFill": 1, "dotSize": 4},
	}


def get_summary(rows):
	curve = weighted_curve(rows)

	def pick(k):
		return f"{curve[k]}%" if k < len(curve) and curve[k] is not None else "-"

	return [
		{
			"value": sum(r["size"] for r in rows),
			"label": "新开通骑手（首次）",
			"datatype": "Int",
			"indicator": "Blue",
		},
		{"value": pick(1), "label": "第 1 月留存", "datatype": "Data", "indicator": "Green"},
		{"value": pick(3), "label": "第 3 月留存", "datatype": "Data", "indicator": "Green"},
		{"value": pick(6), "label": "第 6 月留存", "datatype": "Data", "indicator": "Orange"},
	]
