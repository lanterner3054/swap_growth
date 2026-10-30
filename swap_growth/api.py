"""运营指挥大屏、流失预警的接口。所有接口都按当前用户的区域权限取数。"""

import random
from collections import Counter, defaultdict

import frappe
from frappe.utils import add_days, add_months, get_first_day, getdate, today

from swap_growth.constants import EVENT_CHURN, EVENT_NEW, EVENT_RENEW, ROLE_DIRECTOR
from swap_growth.metrics import (
	Replayer,
	build_periods,
	churn_reason_breakdown,
	complete_rows,
	group_flows,
	load_events,
	period_table,
	quick_ratio,
	resolve_districts,
	snapshot,
)
from swap_growth.risk import score_riders

CACHE_SECONDS = 60


def _pct(a, b):
	return round((a - b) * 100.0 / b, 1) if b else None


@frappe.whitelist()
def get_dashboard_data(district=None):
	districts = resolve_districts(district)
	key = f"swap_growth:dashboard:{'|'.join(districts)}"
	cached = frappe.cache.get_value(key)
	if cached:
		return cached
	data = build_dashboard(districts)
	frappe.cache.set_value(key, data, expires_in_sec=CACHE_SECONDS)
	return data


def build_dashboard(districts):
	today_d = getdate(today())
	tomorrow = add_days(today_d, 1)
	month_start = getdate(get_first_day(today_d))
	prev_month_start = getdate(add_months(month_start, -1))
	prev_same_day = getdate(add_months(tomorrow, -1))
	events = load_events(districts)

	rep = Replayer(events)
	start_snap = snapshot(rep.advance(month_start).active_riders())
	day30_snap = snapshot(rep.advance(add_days(tomorrow, -30)).active_riders())
	now_riders = rep.advance(tomorrow).active_riders()
	now_snap = snapshot(now_riders)

	def count(etype, since, until):
		return sum(1 for e in events if e.event_type == etype and since <= e.event_date < until)

	mtd_new, mtd_churn = count(EVENT_NEW, month_start, tomorrow), count(EVENT_CHURN, month_start, tomorrow)
	prev_new, prev_churn = (
		count(EVENT_NEW, prev_month_start, prev_same_day),
		count(EVENT_CHURN, prev_month_start, prev_same_day),
	)
	mtd_renew = count(EVENT_RENEW, month_start, tomorrow)

	stations = frappe.get_all(
		"Swap Station",
		filters={"district": ("in", districts), "status": "运营中"},
		fields=["name", "station_name", "district", "slots", "longitude", "latitude"],
	)
	total_slots = sum(s.slots or 0 for s in stations)

	kpis = {
		"active": now_snap["active"],
		"active_change": _pct(now_snap["active"], day30_snap["active"]),
		"paused": now_snap["paused"],
		"today_new": count(EVENT_NEW, today_d, tomorrow),
		"today_churn": count(EVENT_CHURN, today_d, tomorrow),
		"mtd_new": mtd_new,
		"mtd_new_change": _pct(mtd_new, prev_new),
		"mtd_churn": mtd_churn,
		"mtd_churn_change": _pct(mtd_churn, prev_churn),
		"churn_rate": round(mtd_churn * 100.0 / start_snap["active"], 2) if start_snap["active"] else 0,
		"renew_rate": round(mtd_renew * 100.0 / (mtd_renew + mtd_churn), 1) if (mtd_renew + mtd_churn) else 0,
		"mrr": now_snap["mrr"],
		"mrr_change": _pct(now_snap["mrr"], start_snap["mrr"]),
		"deposit": now_snap["deposit"],
		"stations": len(stations),
		"slots": total_slots,
		"riders_per_slot": round(now_snap["active"] / total_slots, 2) if total_slots else 0,
	}

	# 近 12 个月趋势
	periods = build_periods(add_months(month_start, -11), today_d, "月")
	trend_rows = period_table(events, periods)
	trend = [
		{k: r[k] for k in ("period", "new", "churn", "net", "closing", "churn_rate", "mrr", "partial")}
		for r in trend_rows
	]
	# 增长质量比取最近 3 个完整月，避免当月未结束带来的波动
	kpis["quick_ratio"] = quick_ratio(complete_rows(trend_rows)[-3:])

	# 区域排名与地图
	flows30 = group_flows(events, add_days(today_d, -29), "district")
	by_district = defaultdict(list)
	for s in now_riders:
		by_district[s.get("district")].append(s)
	slots_by_district = Counter()
	for s in stations:
		slots_by_district[s.district] += s.slots or 0
	district_rows = []
	for d in districts:
		riders = by_district.get(d, [])
		snap = snapshot(riders)
		f = flows30.get(d, {"new": 0, "churn": 0})
		district_rows.append(
			{
				"district": d,
				"active": snap["active"],
				"mrr": snap["mrr"],
				"new30": f["new"],
				"churn30": f["churn"],
				"net30": f["new"] - f["churn"],
				"churn_rate30": round(f["churn"] * 100.0 / (snap["active"] + f["churn"]), 1)
				if (snap["active"] + f["churn"])
				else 0,
				"slots": slots_by_district[d],
				"riders_per_slot": round(snap["active"] / slots_by_district[d], 2)
				if slots_by_district[d]
				else None,
			}
		)
	district_rows.sort(key=lambda r: -r["active"])

	station_active = Counter(s.get("station") for s in now_riders)
	station_points = [
		{
			"name": s.station_name,
			"district": s.district,
			"value": [s.longitude, s.latitude, station_active.get(s.name, 0)],
			"slots": s.slots,
			"riders_per_slot": round(station_active.get(s.name, 0) / s.slots, 2) if s.slots else None,
		}
		for s in stations
	]

	def share(field):
		c = Counter(s.get(field) or "未填写" for s in now_riders)
		return [{"name": k, "value": v} for k, v in c.most_common()]

	channel90 = group_flows(events, add_days(today_d, -89), "channel")

	risk_list, _ = score_riders(events, districts)
	risk_counts = Counter(r["level"] for r in risk_list)
	assigned = set(
		frappe.get_all(
			"ToDo",
			filters={
				"reference_type": "Rider Service Record",
				"status": "Open",
				"reference_name": ("in", [r["last_record"] for r in risk_list[:10]] or [""]),
			},
			pluck="reference_name",
		)
	)
	for r in risk_list[:10]:
		r["assigned"] = r["last_record"] in assigned

	station_names = {s.name: s.station_name for s in stations}
	feed = []
	# 实时动态只展示关键事件（开通、升级、暂停、退租），常规续费量大且信息量低
	key_events = [e for e in reversed(events[-400:]) if e.event_type != EVENT_RENEW][:20]
	for e in key_events:
		feed.append(
			{
				"name": e.name,
				"event_type": e.event_type,
				"event_date": str(e.event_date),
				"rider_name": (e.rider_name or "")[:1] + "**",
				"district": e.district,
				"station": station_names.get(e.station, e.station),
				"package": e.package,
				"churn_reason": e.churn_reason,
				"returning": e.is_returning,
			}
		)

	return {
		"as_of": str(today_d),
		"scope": districts,
		"kpis": kpis,
		"trend": trend,
		"districts": district_rows,
		"stations": station_points,
		"platform_share": share("platform"),
		"package_share": share("package"),
		"user_type_share": share("user_type"),
		"channel_90d": [
			{"name": k, "new": v["new"], "churn": v["churn"]}
			for k, v in sorted(channel90.items(), key=lambda x: -x[1]["new"])
		],
		"churn_reasons_90d": churn_reason_breakdown(events, add_days(today_d, -89)),
		"risk": {"high": risk_counts.get("高", 0), "medium": risk_counts.get("中", 0), "top": risk_list[:10]},
		"feed": feed,
	}


# ---------------------------------------------------------------- 流失预警


@frappe.whitelist()
def get_risk_riders(district=None, level=None, limit=200):
	districts = resolve_districts(district)
	riders, active = score_riders(load_events(districts), districts)
	if level:
		riders = [r for r in riders if r["level"] == level]
	open_todos = set(
		frappe.get_all(
			"ToDo",
			filters={"reference_type": "Rider Service Record", "status": "Open"},
			pluck="reference_name",
		)
	)
	for r in riders:
		r["assigned"] = r["last_record"] in open_todos
	return {"active": active, "total": len(riders), "riders": riders[: int(limit)]}


@frappe.whitelist()
def assign_follow_up(rider_id, user=None):
	"""把高风险骑手的跟进任务指派给区域经理（使用 Frappe 原生的 ToDo 指派）。"""
	from frappe.desk.form.assign_to import add as assign

	last = frappe.get_list(
		"Rider Service Record",
		filters={"rider_id": rider_id, "docstatus": 1},
		fields=["name", "district", "rider_name", "event_type"],
		order_by="event_date desc, creation desc",
		limit=1,
	)
	if not last:
		frappe.throw("未找到该骑手的服务记录或无权限")
	last = last[0]
	if last.event_type == EVENT_CHURN:
		frappe.throw("该骑手已退租")
	user = user or frappe.db.get_value("Swap District", last.district, "manager") or frappe.session.user
	existing = frappe.db.exists(
		"ToDo",
		{
			"reference_type": "Rider Service Record",
			"reference_name": last.name,
			"allocated_to": user,
			"status": "Open",
		},
	)
	if existing:
		return {"user": user, "todo": existing, "existing": True}

	districts = resolve_districts(last.district)
	scored, _ = score_riders(load_events(districts), districts)
	info = next((r for r in scored if r["rider_id"] == rider_id), None)
	reasons = "；".join(info["reasons"]) if info else "人工发起跟进"
	assign(
		{
			"doctype": "Rider Service Record",
			"name": last.name,
			"assign_to": [user],
			"description": f"流失预警跟进：{last.rider_name}（{rider_id}）。风险信号：{reasons}",
			"priority": "High" if info and info["level"] == "高" else "Medium",
			"date": add_days(today(), 2),
		}
	)
	return {"user": user, "existing": False}


# ---------------------------------------------------------------- 演示：模拟实时单据


@frappe.whitelist()
def simulate_event():
	"""演示用：随机生成并提交一张服务单，大屏会实时推送这条动态。"""
	frappe.only_for(("System Manager", ROLE_DIRECTOR))
	from swap_growth.swap_growth.doctype.rider_service_record.rider_service_record import next_rider_id

	rng = random.Random()
	stations = frappe.get_all("Swap Station", filters={"status": "运营中"}, fields=["name", "district"])
	if rng.random() < 0.6:
		station = rng.choice(stations)
		doc = frappe.get_doc(
			{
				"doctype": "Rider Service Record",
				"event_type": EVENT_NEW,
				"event_date": today(),
				"rider_id": next_rider_id(),
				"rider_name": rng.choice("王李张刘陈杨黄赵吴周") + rng.choice("伟强磊军洋勇杰涛明超"),
				"phone": f"13{rng.randint(0, 9)}****{rng.randint(0, 9999):04d}",
				"user_type": "个人骑手",
				"platform": rng.choice(["美团", "饿了么", "顺丰同城"]),
				"package": rng.choice(["单电月卡", "单电月卡", "双电月卡", "车电一体月卡"]),
				"deposit_mode": rng.choice(["押金", "信用免押"]),
				"station": station.name,
				"channel": rng.choice(["站点地推", "老带新", "线上自助"]),
			}
		)
	else:
		events = load_events(resolve_districts())
		state = Replayer(events).advance(add_days(today(), 1)).active_riders()
		rider = rng.choice([s for s in state if s.get("status") == "在租"])
		doc = frappe.get_doc(
			{
				"doctype": "Rider Service Record",
				"event_type": EVENT_CHURN,
				"event_date": today(),
				"rider_id": rider["rider_id"],
				"rider_name": rider["rider_name"],
				"user_type": rider.get("user_type"),
				"team_name": rider.get("team_name"),
				"platform": rider.get("platform"),
				"package": rider.get("package"),
				"deposit_mode": rider.get("deposit_mode") or "信用免押",
				"station": rider.get("station"),
				"channel": rider.get("channel"),
				"churn_reason": rng.choice(["价格偏高", "常缺满电电池", "转用其他品牌", "附近柜点少"]),
			}
		)
	doc.insert()
	doc.submit()
	return doc.name
