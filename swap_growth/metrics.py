"""指标计算引擎。

报表、同期群、大屏、数据分析共用同一套口径：
- 以已提交的《骑手服务单》为唯一事实来源，按时间顺序"回放"每位骑手的状态；
- 活跃骑手 = 当前状态为"在租"或"暂停"（仍保有服务关系、押金未退）；
- 月流水（MRR）= 在租骑手当前套餐月费之和（暂停骑手不计）；
- 押金沉淀 = 活跃且以押金方式开通的骑手押金之和。
"""

from collections import Counter, defaultdict
from datetime import date, timedelta

import frappe
from frappe.utils import add_months, get_first_day, getdate, today

from swap_growth.constants import (
	BILLING_EVENTS,
	EVENT_CHURN,
	EVENT_NEW,
	EVENT_PAUSE,
	EVENT_RENEW,
	EVENT_UPGRADE,
)

DIMENSIONS = ("district", "station", "platform", "channel", "package", "user_type")
ACTIVE_STATUSES = ("在租", "暂停")

EVENT_FIELDS = [
	"name",
	"rider_id",
	"rider_name",
	"event_type",
	"event_date",
	"district",
	"station",
	"platform",
	"channel",
	"package",
	"user_type",
	"team_name",
	"monthly_fee",
	"deposit_mode",
	"deposit_amount",
	"churn_reason",
	"is_returning",
	"account_manager",
	"creation",
]


# ---------------------------------------------------------------- 权限与取数


def allowed_districts():
	"""当前用户可见的行政区（自动应用 User Permission，区域经理只能看到本区）。"""
	return frappe.get_list("Swap District", pluck="name", order_by="sort_order asc", limit_page_length=0)


def resolve_districts(district=None):
	allowed = allowed_districts()
	if district:
		if district not in allowed:
			frappe.throw(f"您没有查看 {district} 数据的权限", frappe.PermissionError)
		return [district]
	return allowed


def load_events(districts=None, upto=None):
	"""读取已提交的服务单，按发生时间排序。"""
	if districts is None:
		districts = allowed_districts()
	if not districts:
		return []
	conditions = ["docstatus = 1", "district in %(districts)s"]
	params = {"districts": tuple(districts)}
	if upto:
		conditions.append("event_date <= %(upto)s")
		params["upto"] = upto
	rows = frappe.db.sql(
		f"""select {", ".join(EVENT_FIELDS)} from `tabRider Service Record`
		where {" and ".join(conditions)} order by event_date asc, creation asc""",
		params,
		as_dict=True,
	)
	for r in rows:
		r.event_date = getdate(r.event_date)
	return rows


def clean_filters(filters):
	return {k: v for k, v in (filters or {}).items() if k in DIMENSIONS and v}


def matches(obj, filters):
	for key, value in filters.items():
		if obj.get(key) != value:
			return False
	return True


# ---------------------------------------------------------------- 状态回放


class Replayer:
	"""按时间推进事件，维护每位骑手的最新状态。"""

	def __init__(self, events):
		self.events = events
		self.pos = 0
		self.state = {}

	def advance(self, until):
		"""应用所有 event_date < until 的事件。"""
		until = getdate(until)
		events = self.events
		while self.pos < len(events) and events[self.pos].event_date < until:
			self.apply(events[self.pos])
			self.pos += 1
		return self

	def apply(self, ev):
		s = self.state.get(ev.rider_id)
		if s is None:
			s = self.state[ev.rider_id] = {"rider_id": ev.rider_id, "first_open": None, "events": 0}
		s["events"] += 1
		for key in DIMENSIONS + ("rider_name", "team_name", "account_manager"):
			if ev.get(key):
				s[key] = ev.get(key)
		s["last_record"] = ev.name
		s["last_event"] = ev.event_type
		s["last_event_date"] = ev.event_date
		etype = ev.event_type
		if etype == EVENT_NEW:
			s["status"] = "在租"
			s["first_open"] = s["first_open"] or ev.event_date
			s["open_date"] = ev.event_date
			s["open_channel"] = ev.channel
			s["deposit_mode"] = ev.deposit_mode
			s["deposit_amount"] = ev.deposit_amount or 0
		elif etype in (EVENT_RENEW, EVENT_UPGRADE):
			s["status"] = "在租"
		elif etype == EVENT_PAUSE:
			s["status"] = "暂停"
		elif etype == EVENT_CHURN:
			s["status"] = "退租"
			s["churn_date"] = ev.event_date
			s["churn_reason"] = ev.churn_reason
		if etype in BILLING_EVENTS:
			s["last_bill"] = ev.event_date
			s["monthly_fee"] = ev.monthly_fee or 0

	def active_riders(self, filters=None):
		filters = filters or {}
		return [s for s in self.state.values() if s.get("status") in ACTIVE_STATUSES and matches(s, filters)]


def snapshot(riders):
	"""对一组活跃骑手做汇总。"""
	active = len(riders)
	mrr = sum(s.get("monthly_fee") or 0 for s in riders if s.get("status") == "在租")
	deposit = sum(s.get("deposit_amount") or 0 for s in riders if s.get("deposit_mode") == "押金")
	paused = sum(1 for s in riders if s.get("status") == "暂停")
	return {"active": active, "mrr": mrr, "deposit": deposit, "paused": paused}


# ---------------------------------------------------------------- 周期


def build_periods(from_date, to_date, granularity="月"):
	"""返回 [(标签, 开始日, 结束日(不含))]。"""
	from_date, to_date = getdate(from_date), getdate(to_date)
	periods = []
	if granularity == "周":
		start = from_date - timedelta(days=from_date.weekday())
		while start <= to_date:
			end = start + timedelta(days=7)
			iso = start.isocalendar()
			periods.append((f"{iso[0]}-W{iso[1]:02d}", start, end))
			start = end
	elif granularity == "季":
		start = date(from_date.year, (from_date.month - 1) // 3 * 3 + 1, 1)
		while start <= to_date:
			end = getdate(add_months(start, 3))
			periods.append((f"{start.year}Q{(start.month - 1) // 3 + 1}", start, end))
			start = end
	else:
		start = getdate(get_first_day(from_date))
		while start <= to_date:
			end = getdate(add_months(start, 1))
			periods.append((start.strftime("%Y-%m"), start, end))
			start = end
	return periods


def default_range():
	"""默认统计区间：最近 12 个自然月（含本月）。"""
	end = getdate(today())
	start = getdate(add_months(get_first_day(end), -11))
	return start, end


# ---------------------------------------------------------------- 周期指标


def period_table(events, periods, filters=None):
	filters = clean_filters(filters)
	rep = Replayer(events)
	idx = 0
	rows = []
	for label, start, end in periods:
		rep.advance(start)
		opening = snapshot(rep.active_riders(filters))
		flows = Counter()
		returning = 0
		reasons = Counter()
		while idx < len(events) and events[idx].event_date < start:
			idx += 1
		j = idx
		while j < len(events) and events[j].event_date < end:
			ev = events[j]
			if matches(ev, filters):
				flows[ev.event_type] += 1
				if ev.event_type == EVENT_NEW and ev.is_returning:
					returning += 1
				if ev.event_type == EVENT_CHURN:
					reasons[ev.churn_reason or "其他"] += 1
			j += 1
		idx = j
		rep.advance(end)
		closing = snapshot(rep.active_riders(filters))
		new, churn, renew, pause = (
			flows[EVENT_NEW],
			flows[EVENT_CHURN],
			flows[EVENT_RENEW],
			flows[EVENT_PAUSE],
		)
		base = opening["active"] or new
		decisions = renew + churn + pause
		rows.append(
			{
				"period": label,
				"start": start,
				"end": end - timedelta(days=1),
				"opening": opening["active"],
				"new": new,
				"returning": returning,
				"renew": renew,
				"upgrade": flows[EVENT_UPGRADE],
				"pause": pause,
				"churn": churn,
				"net": new - churn,
				"closing": closing["active"],
				"paused": closing["paused"],
				"churn_rate": round(churn * 100.0 / base, 2) if base else 0,
				"renew_rate": round(renew * 100.0 / decisions, 2) if decisions else 0,
				"mrr": closing["mrr"],
				"deposit": closing["deposit"],
				"reasons": dict(reasons),
			}
		)
	return rows


def summarize(rows):
	if not rows:
		return {}
	total_new = sum(r["new"] for r in rows)
	total_churn = sum(r["churn"] for r in rows)
	rates = [r["churn_rate"] for r in rows if r["opening"]]
	renew_rates = [r["renew_rate"] for r in rows if r["renew"] or r["churn"]]
	return {
		"closing": rows[-1]["closing"],
		"opening": rows[0]["opening"],
		"new": total_new,
		"churn": total_churn,
		"net": total_new - total_churn,
		"returning": sum(r["returning"] for r in rows),
		"avg_churn_rate": round(sum(rates) / len(rates), 2) if rates else 0,
		"avg_renew_rate": round(sum(renew_rates) / len(renew_rates), 2) if renew_rates else 0,
		"mrr": rows[-1]["mrr"],
		"deposit": rows[-1]["deposit"],
	}


# ---------------------------------------------------------------- 同期群


def cohort_table(events, from_date, to_date, filters=None, max_offset=11):
	"""按首次开通月份分组，统计第 N 个月末仍活跃的比例。"""
	filters = clean_filters(filters)
	months = build_periods(from_date, to_date, "月")
	month_index = {label: i for i, (label, _, _) in enumerate(months)}
	cohorts = defaultdict(set)
	first_open = {}
	for ev in events:
		if ev.event_type == EVENT_NEW and ev.rider_id not in first_open:
			first_open[ev.rider_id] = ev
	for rid, ev in first_open.items():
		label = ev.event_date.strftime("%Y-%m")
		if label in month_index and matches(ev, filters):
			cohorts[label].add(rid)

	rep = Replayer(events)
	active_at_end = []
	for _, _, end in months:
		rep.advance(end)
		active_at_end.append({s["rider_id"] for s in rep.active_riders()})

	today_date = getdate(today())
	rows = []
	for label, start, end in months:
		members = cohorts.get(label, set())
		i = month_index[label]
		row = {"cohort": label, "size": len(members)}
		for k in range(0, max_offset + 1):
			j = i + k
			if j >= len(months) or not members:
				row[f"m{k}"] = None
				continue
			# 当月尚未结束时，以截至今天的状态计算
			row[f"m{k}"] = round(len(members & active_at_end[j]) * 100.0 / len(members), 1)
		row["partial"] = getdate(end) > today_date
		rows.append(row)
	return rows


# ---------------------------------------------------------------- 常用聚合


def churn_reason_breakdown(events, since, filters=None):
	filters = clean_filters(filters)
	since = getdate(since)
	counter = Counter()
	for ev in events:
		if ev.event_type == EVENT_CHURN and ev.event_date >= since and matches(ev, filters):
			counter[ev.churn_reason or "其他"] += 1
	return [{"name": k, "value": v} for k, v in counter.most_common()]


def group_flows(events, since, key, filters=None, until=None):
	"""按维度统计区间内的新开通、退租。"""
	filters = clean_filters(filters)
	since = getdate(since)
	until = getdate(until) if until else None
	data = defaultdict(lambda: {"new": 0, "churn": 0})
	for ev in events:
		if ev.event_date < since or (until and ev.event_date > until) or not matches(ev, filters):
			continue
		if ev.event_type == EVENT_NEW:
			data[ev.get(key) or "未填写"]["new"] += 1
		elif ev.event_type == EVENT_CHURN:
			data[ev.get(key) or "未填写"]["churn"] += 1
	return data
