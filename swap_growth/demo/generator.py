"""演示数据生成器。

生成最近 12 个月杭州 10 个区的换电业务数据，并埋入四条可被报表、大屏和数据分析识别出来的业务剧情：

1. 春节返乡：1~2 月退租与暂停明显上升（原因集中在"不再跑单"），3 月出现回流骑手；
2. 萧山民用推广：自 3 月起，萧山区"政企合作"渠道的民用用户开通持续增长；
3. 钱塘区柜点不足：骑手密度高但站点少，流失率长期偏高，原因集中在"附近柜点少/常缺满电电池"；
4. 平台补贴：7~8 月"平台合作"渠道开通激增，9~10 月补贴结束后该批骑手退租上升（原因集中在"价格偏高"）。

所有数据均为虚构，用 random.Random(seed) 保证可复现。
"""

import random
from collections import defaultdict
from datetime import datetime, time, timedelta

import frappe
from frappe.utils import add_months, get_first_day, getdate, now_datetime, today

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

STATIONS = {
	"上城区": ["湖滨", "南星桥", "四季青", "九堡", "笕桥", "采荷", "丁桥"],
	"拱墅区": ["武林", "和平", "大关", "申花", "半山", "祥符", "朝晖", "石桥"],
	"西湖区": ["文三路", "古荡", "留下", "转塘", "三墩", "蒋村", "西溪"],
	"滨江区": ["江南大道", "长河", "浦沿", "物联网街", "星光大道", "西兴", "网商路", "奥体"],
	"萧山区": ["市心路", "金城路", "钱江世纪城", "宁围", "北干", "新塘", "城厢", "瓜沥", "闻堰", "所前"],
	"余杭区": ["未来科技城", "良渚", "仓前", "闲林", "五常", "瓶窑", "中泰", "文一西路"],
	"临平区": ["临平新城", "乔司", "星桥", "东湖"],
	"钱塘区": ["下沙", "白杨", "义蓬"],
	"富阳区": ["富春", "银湖", "东洲"],
	"临安区": ["锦城", "青山湖"],
}
DISTRICT_WEIGHT = {
	"上城区": 12,
	"拱墅区": 13,
	"西湖区": 11,
	"滨江区": 12,
	"萧山区": 17,
	"余杭区": 13,
	"临平区": 6,
	"钱塘区": 10,
	"富阳区": 4,
	"临安区": 2,
}
OUTER = {"萧山区", "余杭区", "临平区", "钱塘区", "富阳区", "临安区"}

# 新开通的月度季节系数（按自然月）
NEW_SEASON = {
	11: 1.0,
	12: 1.1,
	1: 0.65,
	2: 0.35,
	3: 1.45,
	4: 1.1,
	5: 1.0,
	6: 1.1,
	7: 1.2,
	8: 1.25,
	9: 0.85,
	10: 0.95,
}
BASE_NEW_PER_MONTH = 170
OPENING_RIDERS = 850

SURNAMES = list("王李张刘陈杨黄赵吴周徐孙马朱胡郭何高林罗郑梁谢宋唐许韩冯邓曹彭曾肖田董袁潘")
GIVEN = list("伟强磊军洋勇杰涛明超辉鹏华飞斌宇浩凯健俊帆帅旭宁龙林波晨阳峰亮成刚平东海")

PLATFORM_WEIGHT = {"美团": 44, "饿了么": 31, "顺丰同城": 10, "达达": 8, "其他配送": 7}
CHANNEL_WEIGHT = {"站点地推": 36, "平台合作": 14, "老带新": 22, "线上自助": 18, "政企合作": 10}
PACKAGE_WEIGHT = {"单电月卡": 62, "双电月卡": 26, "车电一体月卡": 12}
DEFAULT_REASON_WEIGHT = {
	"附近柜点少": 13,
	"常缺满电电池": 15,
	"价格偏高": 20,
	"转用其他品牌": 19,
	"不再跑单（返乡/转行）": 23,
	"车辆不兼容": 6,
	"其他": 4,
}


def pick(rng, weights):
	keys = list(weights)
	return rng.choices(keys, weights=[weights[k] for k in keys])[0]


class DemoGenerator:
	def __init__(self, seed=2026, end_date=None):
		self.rng = random.Random(seed)
		self.end = getdate(end_date or today())
		self.window_start = getdate(add_months(get_first_day(self.end), -11))
		self.stations = defaultdict(list)
		self.records = []
		self.riders = []
		self.teams = defaultdict(list)
		self.rider_seq = 0
		self.year_seq = defaultdict(int)

	# ------------------------------------------------------------ 主数据
	def build_master(self):
		managers = {d["name"]: frappe.db.get_value("Swap District", d["name"], "manager") for d in DISTRICTS}
		self.managers = managers
		station_rows = []
		for d in DISTRICTS:
			spread = 0.05 if d["name"] in OUTER else 0.028
			for i, area in enumerate(STATIONS[d["name"]], start=1):
				code = f"HZ-{d['code']}-{i:02d}"
				slots = self.rng.choice([12, 16, 24]) * (1 if d["name"] != "钱塘区" else 1)
				if d["name"] == "钱塘区":
					slots = 12
				row = {
					"name": code,
					"station_code": code,
					"station_name": f"{area}站",
					"district": d["name"],
					"address": f"杭州市{d['name']}{area}片区",
					"status": "运营中",
					"slots": slots,
					"launch_date": self.window_start - timedelta(days=self.rng.randint(90, 600)),
					"longitude": round(d["lng"] + self.rng.uniform(-spread, spread), 6),
					"latitude": round(d["lat"] + self.rng.uniform(-spread * 0.8, spread * 0.8), 6),
				}
				station_rows.append(row)
				self.stations[d["name"]].append(code)
		self.station_rows = station_rows

		# 配送团队：以站点为单位的团队批量开通
		for d in DISTRICTS:
			for k in range(2 if d["name"] in DISTRICT_WEIGHT and DISTRICT_WEIGHT[d["name"]] >= 10 else 1):
				station = self.rng.choice(self.stations[d["name"]])
				platform = self.rng.choice(["美团", "饿了么", "顺丰同城"])
				area = STATIONS[d["name"]][self.stations[d["name"]].index(station)]
				self.teams[d["name"]].append((f"{area}{platform}配送站", station, platform))

	# ------------------------------------------------------------ 骑手
	def new_rider(self, open_date, district=None, channel=None, platform=None, user_type=None, package=None):
		rng = self.rng
		self.rider_seq += 1
		district = district or pick(rng, DISTRICT_WEIGHT)
		user_type = user_type or ("配送团队" if rng.random() < 0.14 else "个人骑手")
		team_name = None
		if user_type == "配送团队" and self.teams[district]:
			team_name, station, platform = rng.choice(self.teams[district])
		else:
			station = rng.choice(self.stations[district])
		if user_type == "民用用户":
			platform = "无（民用）"
		platform = platform or pick(rng, PLATFORM_WEIGHT)
		channel = channel or ("政企合作" if user_type == "民用用户" else pick(rng, CHANNEL_WEIGHT))
		if channel == "政企合作" and user_type != "民用用户":
			channel = "站点地推"
		rider = {
			"rider_id": f"R{self.rider_seq:06d}",
			"rider_name": rng.choice(SURNAMES) + "".join(rng.choices(GIVEN, k=rng.choice([1, 2]))),
			"phone": f"1{rng.choice(['3', '5', '7', '8', '9'])}{rng.randint(0, 9)}****{rng.randint(0, 9999):04d}",
			"user_type": user_type,
			"team_name": team_name,
			"platform": platform,
			"district": district,
			"station": station,
			"channel": channel,
			"package": package or pick(rng, PACKAGE_WEIGHT),
			"deposit_mode": "押金" if rng.random() < 0.38 else "信用免押",
			"open_date": open_date,
			"subsidy": channel == "平台合作" and open_date.month in (7, 8) and open_date >= self.window_start,
		}
		self.riders.append(rider)
		return rider

	def add_event(self, rider, event_type, event_date, **extra):
		if event_date > self.end:
			return False
		self.year_seq[event_date.year] += 1
		name = f"SR-{event_date.year}-{self.year_seq[event_date.year]:05d}"
		rec = {
			"name": name,
			"naming_series": "SR-.YYYY.-",
			"event_type": event_type,
			"event_date": event_date,
			"rider_id": rider["rider_id"],
			"rider_name": rider["rider_name"],
			"phone": rider["phone"],
			"user_type": rider["user_type"],
			"team_name": rider["team_name"],
			"platform": rider["platform"],
			"package": rider["package"],
			"previous_package": extra.get("previous_package"),
			"monthly_fee": PACKAGES[rider["package"]],
			"deposit_mode": rider["deposit_mode"],
			"deposit_amount": DEPOSIT_AMOUNT if rider["deposit_mode"] == "押金" else 0,
			"deposit_status": self.deposit_status(rider, event_type, event_date),
			"station": rider["station"],
			"district": rider["district"],
			"channel": rider["channel"],
			"is_returning": extra.get("is_returning", 0),
			"churn_reason": extra.get("churn_reason"),
			"account_manager": self.managers.get(rider["district"]),
		}
		self.records.append(rec)
		return True

	def deposit_status(self, rider, event_type, event_date):
		if rider["deposit_mode"] == "信用免押":
			return "已免押"
		if event_type == EVENT_CHURN:
			return "已退还" if (self.end - event_date).days > 7 else "待退还"
		return "已缴纳"

	# ------------------------------------------------------------ 生命周期模拟
	def churn_probability(self, rider, decision_date, tenure):
		p = 0.052
		m = decision_date.month
		p *= {1: 1.5, 2: 2.4, 12: 0.8, 7: 0.85, 8: 0.85}.get(m, 1.0)
		p *= {"钱塘区": 1.9, "临平区": 1.15, "富阳区": 1.2, "临安区": 1.2}.get(rider["district"], 1.0)
		p *= {"配送团队": 0.55, "民用用户": 0.75}.get(rider["user_type"], 1.0)
		p *= {"车电一体月卡": 0.7, "双电月卡": 0.85}.get(rider["package"], 1.0)
		if rider["subsidy"] and m in (9, 10):
			p *= 3.2
		if tenure == 1:
			p *= 1.3
		return min(p, 0.6)

	def churn_reason(self, rider, d):
		rng = self.rng
		if d.month in (1, 2) and rng.random() < 0.62:
			return "不再跑单（返乡/转行）"
		if rider["subsidy"] and d.month in (9, 10) and rng.random() < 0.7:
			return rng.choices(["价格偏高", "转用其他品牌"], weights=[72, 28])[0]
		if rider["district"] == "钱塘区" and rng.random() < 0.68:
			return rng.choices(["附近柜点少", "常缺满电电池"], weights=[52, 48])[0]
		return pick(rng, DEFAULT_REASON_WEIGHT)

	def simulate(self, rider, start):
		"""从开通日起，每 30 天做一次续费/升级/暂停/退租决策。"""
		rng = self.rng
		self.add_event(rider, EVENT_NEW, start, is_returning=rider.get("returning", 0))
		bill = start
		tenure = 0
		paused = False
		while True:
			decision = bill + timedelta(days=CARD_DAYS + rng.randint(0, 2))
			if decision > self.end:
				return None
			tenure += 1
			m = decision.month
			if paused:
				paused = False
				if rng.random() < 0.62:
					bill = decision
					self.add_event(rider, EVENT_RENEW, bill)
					continue
				reason = (
					"不再跑单（返乡/转行）"
					if m in (2, 3) and rng.random() < 0.6
					else self.churn_reason(rider, decision)
				)
				self.add_event(rider, EVENT_CHURN, decision, churn_reason=reason)
				return (decision, reason)
			p_churn = self.churn_probability(rider, decision, tenure)
			p_pause = {1: 0.07, 2: 0.11}.get(m, 0.02)
			r = rng.random()
			if r < p_churn:
				reason = self.churn_reason(rider, decision)
				self.add_event(rider, EVENT_CHURN, decision, churn_reason=reason)
				return (decision, reason)
			if r < p_churn + p_pause and rider["user_type"] != "配送团队":
				paused = True
				self.add_event(rider, EVENT_PAUSE, decision)
				bill = decision
				continue
			bill = decision
			if rider["package"] != "车电一体月卡" and r > 0.975:
				prev = rider["package"]
				rider["package"] = "双电月卡" if prev == "单电月卡" and rng.random() < 0.7 else "车电一体月卡"
				self.add_event(rider, EVENT_UPGRADE, bill, previous_package=prev)
			else:
				self.add_event(rider, EVENT_RENEW, bill)

	def run(self):
		rng = self.rng
		self.build_master()
		# 期初存量：窗口开始前 60 天内开通的骑手
		spring_churners = []
		for _ in range(OPENING_RIDERS):
			d = self.window_start - timedelta(days=rng.randint(1, 60))
			rider = self.new_rider(d)
			result = self.simulate(rider, d)
			if result and result[1] == "不再跑单（返乡/转行）" and result[0].month in (1, 2):
				spring_churners.append(rider)

		month = self.window_start
		while month <= self.end:
			mult = NEW_SEASON[month.month]
			count = int(BASE_NEW_PER_MONTH * mult * rng.uniform(0.93, 1.07))
			days = (getdate(add_months(month, 1)) - month).days
			for _ in range(count):
				d = month + timedelta(days=rng.randint(0, days - 1))
				if d <= self.end:
					rider = self.new_rider(d)
					result = self.simulate(rider, d)
					if result and result[1] == "不再跑单（返乡/转行）" and result[0].month in (1, 2):
						spring_churners.append(rider)
			# 剧情 2：萧山民用推广（3 月起逐月放量）
			if month.month >= 3 and month.month <= 10 and month.year == self.end.year:
				for _ in range(18 + (month.month - 3) * 6):
					d = month + timedelta(days=rng.randint(0, days - 1))
					if d <= self.end:
						rider = self.new_rider(d, district="萧山区", user_type="民用用户", package="单电月卡")
						self.simulate(rider, d)
			# 剧情 4：平台补贴（7~8 月）
			if month.month in (7, 8):
				for _ in range(95):
					d = month + timedelta(days=rng.randint(0, days - 1))
					if d <= self.end:
						rider = self.new_rider(d, channel="平台合作", platform="美团", user_type="个人骑手")
						self.simulate(rider, d)
			month = getdate(add_months(month, 1))

		# 剧情 1：春节后回流（3 月）
		for rider in self.records_churners_for_return(spring_churners):
			d = getdate(f"{self.end.year}-03-01") + timedelta(days=rng.randint(0, 24))
			if d <= self.end:
				returning = dict(rider)
				returning["returning"] = 1
				returning["channel"] = "线上自助"
				returning["subsidy"] = False
				self.simulate(returning, d)
		# 按发生日期重新编号，保证单据号与时间顺序一致
		self.records.sort(key=lambda r: (r["event_date"], r["name"]))
		self.year_seq = defaultdict(int)
		for rec in self.records:
			year = rec["event_date"].year
			self.year_seq[year] += 1
			rec["name"] = f"SR-{year}-{self.year_seq[year]:05d}"
		return self

	def records_churners_for_return(self, churners):
		return [r for r in churners if self.rng.random() < 0.55]

	# ------------------------------------------------------------ IoT 周换电
	def weekly_swaps(self):
		"""为当前活跃骑手生成最近 8 周的换电次数，部分骑手呈下降趋势（流失前兆）。"""
		rng = self.rng
		last = {}
		for rec in self.records:
			last[rec["rider_id"]] = rec
		monday = self.end - timedelta(days=self.end.weekday())
		weeks = [monday - timedelta(days=7 * k) for k in range(8, 0, -1)]
		by_id = {r["rider_id"]: r for r in self.riders}
		rows = []
		for rid, rec in last.items():
			if rec["event_type"] == EVENT_CHURN:
				continue
			rider = by_id.get(rid, rec)
			base = {"双电月卡": 2.1}.get(rec["package"], 3.1)
			if rec["user_type"] == "民用用户":
				base = 0.7
			base *= rng.uniform(0.75, 1.25)
			risk = 0.07
			if rec["district"] == "钱塘区":
				risk += 0.12
			if rider.get("subsidy"):
				risk += 0.15
			if rec["event_type"] == EVENT_PAUSE:
				risk += 0.6
			declining = rng.random() < risk
			drop = rng.uniform(0.3, 0.6)
			for i, w in enumerate(weeks):
				factor = 1.0
				if declining and i >= 5:
					factor = drop if i >= 6 else (1 + drop) / 2
				if rec["event_type"] == EVENT_PAUSE and i >= 6:
					factor = 0.05
				count = max(0, int(round(base * 7 * factor * rng.uniform(0.85, 1.15))))
				rows.append((rid, w, count, rec["station"], rec["district"]))
		return rows


# ---------------------------------------------------------------- 写库


def _ts(d, rng):
	return datetime.combine(d, time(rng.randint(7, 21), rng.randint(0, 59), rng.randint(0, 59)))


def reset_demo_data(seed=2026):
	"""清空并重新生成演示数据（站点、服务单、周换电、分析记录）。"""
	frappe.only_for(("System Manager", "运营总监"))
	return generate(seed=seed)


def generate(seed=2026):
	for dt in ("Rider Service Record", "Rider Weekly Swap", "Data Analysis Record", "Swap Station"):
		frappe.db.delete(dt)
	frappe.db.delete("ToDo", {"reference_type": "Rider Service Record"})
	gen = DemoGenerator(seed=seed).run()
	user = frappe.session.user or "Administrator"
	now = now_datetime()
	rng = random.Random(seed + 1)

	station_fields = [
		"name",
		"station_code",
		"station_name",
		"district",
		"address",
		"status",
		"slots",
		"launch_date",
		"longitude",
		"latitude",
		"owner",
		"modified_by",
		"creation",
		"modified",
		"docstatus",
	]
	frappe.db.bulk_insert(
		"Swap Station",
		station_fields,
		[[s[f] for f in station_fields[:10]] + [user, user, now, now, 0] for s in gen.station_rows],
	)

	rec_fields = [
		"name",
		"naming_series",
		"event_type",
		"event_date",
		"rider_id",
		"rider_name",
		"phone",
		"user_type",
		"team_name",
		"platform",
		"package",
		"previous_package",
		"monthly_fee",
		"deposit_mode",
		"deposit_amount",
		"deposit_status",
		"station",
		"district",
		"channel",
		"is_returning",
		"churn_reason",
		"account_manager",
	]
	values = []
	for rec in gen.records:
		ts = _ts(rec["event_date"], rng)
		values.append([rec[f] for f in rec_fields] + [user, user, ts, ts, 1])
	frappe.db.bulk_insert(
		"Rider Service Record",
		rec_fields + ["owner", "modified_by", "creation", "modified", "docstatus"],
		values,
		chunk_size=2000,
	)

	swap_rows = gen.weekly_swaps()
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
		],
		[[frappe.generate_hash(length=10), *row, user, user, now, now, 0] for row in swap_rows],
		chunk_size=4000,
	)

	# 同步编号规则计数器，保证界面新建的单据编号不冲突
	for year, seq in gen.year_seq.items():
		key = f"SR-{year}-"
		if frappe.db.exists("Series", key):
			frappe.db.sql("update `tabSeries` set current=%s where name=%s", (seq, key))
		else:
			frappe.db.sql("insert into `tabSeries` (name, current) values (%s, %s)", (key, seq))

	frappe.db.commit()
	frappe.cache.delete_keys("swap_growth:")
	return {
		"stations": len(gen.station_rows),
		"riders": gen.rider_seq,
		"records": len(gen.records),
		"weekly_swaps": len(swap_rows),
		"from": str(gen.window_start),
		"to": str(gen.end),
	}
