"""演示数据每日续写。

安装时生成的演示数据截止于安装当天。为了让在线演示在之后的日子里依然"像在运营"，
调度器每天按与生成器相同的业务规律补写：到期骑手续费/暂停/退租、暂停到期恢复或退租、
新骑手开通，以及上一完整周的换电柜 IoT 周汇总。可在《换电增长设置》中关闭。
"""

import random
import time as _time
from collections import defaultdict
from datetime import datetime, time, timedelta

import frappe
from frappe.model.naming import getseries
from frappe.utils import cint, getdate, now_datetime, today

from swap_growth.constants import (
	CARD_DAYS,
	DEPOSIT_AMOUNT,
	DISTRICTS,
	EVENT_CHURN,
	EVENT_NEW,
	EVENT_PAUSE,
	EVENT_RENEW,
	EVENT_UPGRADE,
	PACKAGES,
)
from swap_growth.demo.generator import BASE_NEW_PER_MONTH, NEW_SEASON, DemoGenerator
from swap_growth.metrics import Replayer, load_events

REC_FIELDS = [
	"name", "naming_series", "event_type", "event_date", "rider_id", "rider_name", "phone", "user_type",
	"team_name", "platform", "package", "previous_package", "monthly_fee", "deposit_mode", "deposit_amount",
	"deposit_status", "station", "district", "channel", "is_returning", "churn_reason", "account_manager",
]  # fmt: skip


def daily_tick(upto=None):
	# 未设置过（旧站点新增字段）视为开启
	enabled = frappe.db.sql(
		"select value from `tabSingles` where doctype='Swap Growth Settings' and field='demo_auto_refresh'"
	)
	if enabled and not cint(enabled[0][0]):
		return None
	frappe.set_user("Administrator")
	end = getdate(upto or today())
	last = frappe.db.sql("select max(event_date) from `tabRider Service Record` where docstatus=1")[0][0]
	if not last:
		return None
	last = getdate(last)

	districts = [d["name"] for d in DISTRICTS]
	events = load_events(districts)
	rep = Replayer(events).advance(last + timedelta(days=1))
	gen = _load_generator(int(_time.time()))
	rng = gen.rng
	records = []

	day = last + timedelta(days=1)
	while day <= end:
		todays = []
		for s in list(rep.state.values()):
			status = s.get("status")
			if status == "在租" and s.get("last_bill") and s["last_bill"] + timedelta(days=CARD_DAYS) <= day:
				todays.append(_decide(gen, s, day))
			elif status == "暂停" and s["last_event_date"] + timedelta(days=CARD_DAYS) <= day:
				if rng.random() < 0.62:
					todays.append(_record(s, EVENT_RENEW, day))
				else:
					todays.append(
						_record(s, EVENT_CHURN, day, churn_reason=gen.churn_reason(_profile(s), day))
					)
		for _ in range(_new_count(rng, day)):
			rider = gen.new_rider(day)
			todays.append(_record(_rider_state(rider, gen.managers), EVENT_NEW, day))
		for rec in todays:
			rec["name"] = f"SR-{day.year}-" + getseries(f"SR-{day.year}-", 5)
			records.append(rec)
			rep.apply(frappe._dict(rec))
		day += timedelta(days=1)

	_insert_records(records, rng)
	swaps = _weekly_swaps(rep, end, rng)
	frappe.db.commit()
	frappe.cache.delete_keys("swap_growth:dashboard")
	return {
		"from": str(last + timedelta(days=1)),
		"to": str(end),
		"records": len(records),
		"weekly_swaps": swaps,
	}


# ---------------------------------------------------------------- 内部


def _load_generator(seed):
	gen = DemoGenerator(seed=seed)
	gen.managers = {d.name: d.manager for d in frappe.get_all("Swap District", fields=["name", "manager"])}
	for s in frappe.get_all(
		"Swap Station", filters={"status": "运营中"}, fields=["name", "district"], order_by="name"
	):
		gen.stations[s.district].append(s.name)
	for t in frappe.db.sql(
		"""select distinct team_name, station, platform, district from `tabRider Service Record`
		where team_name is not null and team_name != ''""",
		as_dict=True,
	):
		gen.teams[t.district].append((t.team_name, t.station, t.platform))
	gen.rider_seq = cint(
		frappe.db.sql(
			"select max(cast(substring(rider_id, 2) as unsigned)) from `tabRider Service Record` where rider_id like 'R%%'"
		)[0][0]
	)
	return gen


def _profile(s):
	"""把回放出的骑手状态转换成生成器使用的画像。"""
	open_date = s.get("open_date")
	return {
		"district": s.get("district"),
		"user_type": s.get("user_type"),
		"package": s.get("package"),
		"subsidy": s.get("open_channel") == "平台合作"
		and open_date is not None
		and open_date.month in (7, 8),
	}


def _rider_state(rider, managers):
	return {
		**rider,
		"monthly_fee": PACKAGES[rider["package"]],
		"account_manager": managers.get(rider["district"]),
	}


def _decide(gen, s, day):
	rng = gen.rng
	profile = _profile(s)
	p_churn = gen.churn_probability(profile, day, max(1, s.get("events", 1)))
	p_pause = {1: 0.07, 2: 0.11}.get(day.month, 0.02)
	r = rng.random()
	if r < p_churn:
		return _record(s, EVENT_CHURN, day, churn_reason=gen.churn_reason(profile, day))
	if r < p_churn + p_pause and s.get("user_type") != "配送团队":
		return _record(s, EVENT_PAUSE, day)
	if s.get("package") != "车电一体月卡" and r > 0.975:
		prev = s.get("package")
		new_pkg = "双电月卡" if prev == "单电月卡" and rng.random() < 0.7 else "车电一体月卡"
		return _record({**s, "package": new_pkg}, EVENT_UPGRADE, day, previous_package=prev)
	return _record(s, EVENT_RENEW, day)


def _record(s, event_type, day, churn_reason=None, previous_package=None):
	deposit_mode = s.get("deposit_mode") or "信用免押"
	if deposit_mode == "信用免押":
		deposit_status = "已免押"
	elif event_type == EVENT_CHURN:
		deposit_status = "待退还"
	else:
		deposit_status = "已缴纳"
	package = s.get("package")
	return {
		"name": None,
		"naming_series": "SR-.YYYY.-",
		"event_type": event_type,
		"event_date": day,
		"rider_id": s.get("rider_id"),
		"rider_name": s.get("rider_name"),
		"phone": s.get("phone") or f"13{random.randint(0, 9)}****{random.randint(0, 9999):04d}",
		"user_type": s.get("user_type"),
		"team_name": s.get("team_name"),
		"platform": s.get("platform"),
		"package": package,
		"previous_package": previous_package,
		"monthly_fee": PACKAGES.get(package, 0),
		"deposit_mode": deposit_mode,
		"deposit_amount": DEPOSIT_AMOUNT if deposit_mode == "押金" else 0,
		"deposit_status": deposit_status,
		"station": s.get("station"),
		"district": s.get("district"),
		"channel": s.get("channel"),
		"is_returning": 0,
		"churn_reason": churn_reason,
		"account_manager": s.get("account_manager"),
	}


def _new_count(rng, day):
	expected = BASE_NEW_PER_MONTH * NEW_SEASON[day.month] / 30.0
	if day.month >= 3 and day.month <= 10:
		expected += (18 + (day.month - 3) * 6) / 30.0  # 萧山民用推广持续
	return max(0, int(round(expected * rng.uniform(0.6, 1.4))))


def _insert_records(records, rng):
	if not records:
		return
	now = now_datetime()
	values = []
	for rec in records:
		ts = datetime.combine(
			rec["event_date"], time(rng.randint(7, 21), rng.randint(0, 59), rng.randint(0, 59))
		)
		ts = min(ts, now)
		values.append([rec[f] for f in REC_FIELDS] + ["Administrator", "Administrator", ts, ts, 1])
	frappe.db.bulk_insert(
		"Rider Service Record",
		REC_FIELDS + ["owner", "modified_by", "creation", "modified", "docstatus"],
		values,
		chunk_size=2000,
	)


def _weekly_swaps(rep, end, rng):
	"""补写缺失的完整周换电汇总：沿用每位骑手近 4 周的平均水平，暂停骑手几乎不换电。"""
	last_week = frappe.db.sql("select max(week_start) from `tabRider Weekly Swap`")[0][0]
	this_monday = end - timedelta(days=end.weekday())
	week = getdate(last_week) + timedelta(days=7) if last_week else this_monday - timedelta(days=7)
	if week >= this_monday:
		return 0
	history = defaultdict(list)
	for r in frappe.db.sql(
		"""select rider_id, swap_count from `tabRider Weekly Swap`
		where week_start >= %s order by week_start""",
		getdate(last_week) - timedelta(days=21) if last_week else this_monday,
		as_dict=True,
	):
		history[r.rider_id].append(r.swap_count)
	now = now_datetime()
	rows = []
	while week < this_monday:
		for s in rep.state.values():
			if s.get("status") not in ("在租", "暂停"):
				continue
			past = history.get(s["rider_id"])
			base = sum(past) / len(past) if past else (14.7 if s.get("package") == "双电月卡" else 21.7)
			count = 0 if s.get("status") == "暂停" else int(round(base * rng.uniform(0.85, 1.15)))
			rows.append(
				[
					frappe.generate_hash(length=10),
					s["rider_id"],
					week,
					count,
					s.get("station"),
					s.get("district"),
					"Administrator",
					"Administrator",
					now,
					now,
					0,
				]  # fmt: skip
			)
		week += timedelta(days=7)
	frappe.db.bulk_insert(
		"Rider Weekly Swap",
		[
			"name",
			"rider_id",
			"week_start",
			"swap_count",
			"station",
			"district",
			"owner",
			"modified_by",
			"creation",
			"modified",
			"docstatus",
		],  # fmt: skip
		rows,
		chunk_size=4000,
	)
	return len(rows)
