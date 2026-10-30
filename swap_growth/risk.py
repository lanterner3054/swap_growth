"""骑手流失预警：透明的规则评分，每一分都能解释来源。"""

from collections import Counter, defaultdict
from datetime import timedelta

import frappe
from frappe.utils import add_days, getdate, today

from swap_growth.constants import CARD_DAYS, EVENT_CHURN, SUPPLY_REASONS
from swap_growth.metrics import Replayer

HIGH = 55
MEDIUM = 35


def swap_trends(districts):
	"""最近 2 周日均换电 vs 之前 4 周日均换电。"""
	if not districts:
		return {}
	rows = frappe.db.sql(
		"""select rider_id, week_start, swap_count from `tabRider Weekly Swap`
		where district in %(d)s order by week_start""",
		{"d": tuple(districts)},
		as_dict=True,
	)
	weeks = sorted({r.week_start for r in rows})
	if len(weeks) < 4:
		return {}
	recent, previous = set(weeks[-2:]), set(weeks[-6:-2])
	acc = defaultdict(lambda: [0, 0])
	for r in rows:
		if r.week_start in recent:
			acc[r.rider_id][0] += r.swap_count
		elif r.week_start in previous:
			acc[r.rider_id][1] += r.swap_count
	trends = {}
	for rid, (rec, prev) in acc.items():
		rec_avg = rec / (7.0 * len(recent))
		prev_avg = prev / (7.0 * len(previous)) if previous else 0
		change = (rec_avg - prev_avg) / prev_avg if prev_avg else 0
		trends[rid] = {"recent": round(rec_avg, 1), "previous": round(prev_avg, 1), "change": change}
	return trends


def supply_stations(events, since):
	"""近期因"柜点少/缺电"退租较多的站点。"""
	since = getdate(since)
	counter = Counter()
	for ev in events:
		if ev.event_type == EVENT_CHURN and ev.event_date >= since and ev.churn_reason in SUPPLY_REASONS:
			counter[ev.station] += 1
	return counter


def district_churn_rates(events, since, state_now):
	since = getdate(since)
	churn = Counter(ev.district for ev in events if ev.event_type == EVENT_CHURN and ev.event_date >= since)
	active = Counter(s.get("district") for s in state_now)
	rates = {
		d: churn[d] / float(active[d] + churn[d]) for d in set(churn) | set(active) if (active[d] + churn[d])
	}
	total = sum(churn.values()) / float(sum(active.values()) + sum(churn.values()) or 1)
	return rates, total


def score_riders(events, districts, filters=None):
	today_d = getdate(today())
	rep = Replayer(events).advance(add_days(today_d, 1))
	active = rep.active_riders(filters or {})
	trends = swap_trends(districts)
	supply = supply_stations(events, add_days(today_d, -90))
	rates, overall = district_churn_rates(events, add_days(today_d, -90), rep.active_riders())
	stations = {
		s.name: s.station_name for s in frappe.get_all("Swap Station", fields=["name", "station_name"])
	}

	scored = []
	for s in active:
		score, reasons = 0, []
		t = trends.get(s["rider_id"])
		if t and t["change"] <= -0.5:
			score += 40
			reasons.append(
				f"换电频次骤降 {abs(t['change']) * 100:.0f}%（日均 {t['previous']}→{t['recent']} 次）"
			)
		elif t and t["change"] <= -0.3:
			score += 25
			reasons.append(
				f"换电频次下降 {abs(t['change']) * 100:.0f}%（日均 {t['previous']}→{t['recent']} 次）"
			)
		if s.get("status") == "暂停":
			score += 20
			reasons.append("当前处于暂停状态")
		expiry = s.get("last_bill") and s["last_bill"] + timedelta(days=CARD_DAYS)
		if expiry and 0 <= (expiry - today_d).days <= 7:
			score += 10
			reasons.append(f"月卡 {expiry.strftime('%m-%d')} 到期")
		if supply.get(s.get("station"), 0) >= 3:
			score += 15
			reasons.append(f"常用站点近 90 天有 {supply[s['station']]} 人因柜点少/缺电退租")
		if rates.get(s.get("district"), 0) > overall * 1.3:
			score += 10
			reasons.append(f"{s.get('district')}近 90 天流失率偏高")
		if (
			s.get("open_channel") == "平台合作"
			and s.get("open_date")
			and s["open_date"] >= add_days(today_d, -150)
		):
			score += 15
			reasons.append("补贴渠道获客，补贴结束后价格敏感")
		if score < MEDIUM:
			continue
		scored.append(
			{
				"rider_id": s["rider_id"],
				"rider_name": s.get("rider_name"),
				"district": s.get("district"),
				"station": s.get("station"),
				"station_name": stations.get(s.get("station"), s.get("station")),
				"package": s.get("package"),
				"platform": s.get("platform"),
				"status": s.get("status"),
				"last_record": s.get("last_record"),
				"account_manager": s.get("account_manager"),
				"score": min(score, 100),
				"level": "高" if score >= HIGH else "中",
				"reasons": reasons,
				"recent_swaps": t["recent"] if t else None,
			}
		)
	scored.sort(key=lambda x: -x["score"])
	return scored, len(active)
