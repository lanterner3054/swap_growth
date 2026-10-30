"""数据分析：基于聚合指标生成结论、原因与行动建议。

- 结果按"分析范围（全杭州/某区）"缓存，默认 3 小时内重复打开直接复用，不重复调用模型；
- 超过有效期或用户点击"重新分析"时才重新生成；
- 每次分析都存档到《数据分析记录》，可追溯；
- 大模型（DeepSeek / 智谱 GLM，均为 OpenAI 兼容接口）未配置或调用失败时，自动降级为规则引擎。
"""

import json
from collections import Counter

import frappe
import requests
from frappe.utils import (
	add_days,
	add_months,
	add_to_date,
	get_datetime,
	get_first_day,
	getdate,
	now_datetime,
	today,
)

from swap_growth.constants import EVENT_CHURN, EVENT_NEW, SUPPLY_REASONS
from swap_growth.metrics import (
	Replayer,
	build_periods,
	churn_reason_breakdown,
	group_flows,
	load_events,
	period_table,
	resolve_districts,
	summarize,
)
from swap_growth.risk import score_riders

SYSTEM_PROMPT = """你是一家杭州两轮电动车换电运营公司的资深经营分析师，服务对象是运营总监和区域经理。
业务背景：骑手（以外卖、快递、同城配送为主，另有少量民用用户）按月购买换电套餐，在换电柜扫码换电；
公司收入来自月卡，成本主要是换电柜与电池等重资产，因此骑手留存和单柜利用率是经营核心。

请严格基于用户提供的 JSON 指标进行分析：
1. 每条结论都必须引用数据中的具体数字（人数、百分比、月份、区域或站点名称），不得编造数据中没有的信息；
2. 优先指出对经营影响最大的问题，其次是值得放大的积极信号；
3. 行动建议要具体到对象（哪个区、站点、渠道或人群）和动作，并说明预期效果；
4. 语言简洁专业，使用中文。

只输出一个 JSON 对象，结构如下：
{
  "headline": "一句话结论，不超过 40 字",
  "summary": "100~160 字的整体判断",
  "findings": [{"title": "发现标题，不超过 16 字", "detail": "含具体数字的说明，不超过 80 字", "level": "风险 或 关注 或 积极"}],
  "causes": ["流失或增长的主要原因，每条不超过 60 字"],
  "actions": [{"action": "具体行动", "target": "针对的区域/站点/渠道/人群", "priority": "高 或 中 或 低", "expected": "预期效果"}],
  "site_suggestions": [{"station": "站点或片区名称", "suggestion": "补柜/扩容/调拨电池等建议", "reason": "数据依据"}]
}
findings 3~4 条，causes 2~4 条，actions 3~4 条，site_suggestions 0~3 条。"""


# ---------------------------------------------------------------- 对外接口


def resolve_scope(district):
	"""权限校验并确定分析范围。区域经理没有全市视角：默认分析其负责的第一个区，避免与全市缓存混用。"""
	district = district or ""
	allowed = resolve_districts(district or None)
	if not district and len(allowed) < frappe.db.count("Swap District"):
		district = allowed[0] if allowed else frappe.throw("没有可分析的区域", frappe.PermissionError)
	return district


def lock_key(district):
	return frappe.cache.make_key(f"swap_growth:analysis_lock:{district or 'all'}")


@frappe.whitelist()
def get_analysis(district=None, force=0):
	"""有有效缓存直接返回；否则在后台队列生成并立即返回 running，由前端轮询 poll_analysis。

	生成（尤其是调用大模型）可能需要几十秒，放在后台执行，不占用网页进程，
	大屏和分析页同时打开、或多人同时点击时，同一范围只生成一次，大家等待同一份结果。
	"""
	district = resolve_scope(district)
	if not frappe.utils.cint(force):
		cached = find_cached(district)
		if cached:
			return to_payload(cached, cached_hit=True)

	key = lock_key(district)
	started = now_datetime()
	if frappe.cache.set(key, str(started), nx=True, ex=600):
		try:
			frappe.enqueue(
				"swap_growth.analysis.generate",
				queue="long",
				timeout=600,
				district=district,
			)
		except Exception:
			# 队列不可用时退回同步生成，保证功能可用
			try:
				return to_payload(run_analysis(district, frappe.get_single("Swap Growth Settings")), False)
			finally:
				frappe.cache.delete(key)
	else:
		# 已有人在生成：等待同一份结果
		running = frappe.cache.get(key)
		started = get_datetime(running.decode() if isinstance(running, bytes) else running) or started
	return {"status": "running", "district": district, "since": str(started)}


@frappe.whitelist()
def poll_analysis(district=None, since=None):
	district = resolve_scope(district)
	done = find_cached(district, since=get_datetime(since) if since else None)
	if done:
		return to_payload(done, cached_hit=False)
	if frappe.cache.get(lock_key(district)):
		return {"status": "running", "district": district, "since": since}
	return {"status": "failed", "district": district}


def generate(district):
	"""后台任务：生成分析并释放锁。"""
	try:
		run_analysis(district, frappe.get_single("Swap Growth Settings"))
	finally:
		frappe.cache.delete(lock_key(district))


@frappe.whitelist()
def get_analysis_scopes():
	"""分析范围选项：区域经理只看到自己负责的区。"""
	allowed = resolve_districts()
	total = frappe.db.count("Swap District")
	scopes = []
	if len(allowed) == total:
		scopes.append({"value": "", "label": "全杭州"})
	scopes += [{"value": d, "label": d} for d in allowed]
	return scopes


def find_cached(district, since=None):
	filters = {"expires_at": (">", now_datetime())}
	if since:
		filters["generated_at"] = (">=", since)
	if district:
		filters["district"] = district
	else:
		filters["district"] = ("is", "not set")
	rows = frappe.get_all(
		"Data Analysis Record", filters=filters, order_by="generated_at desc", limit=1, pluck="name"
	)
	return frappe.get_doc("Data Analysis Record", rows[0]) if rows else None


def to_payload(doc, cached_hit):
	return {
		"status": "done",
		"name": doc.name,
		"scope": doc.scope_label,
		"district": doc.district or "",
		"source": doc.source,
		"model": doc.model,
		"generated_at": str(doc.generated_at),
		"expires_at": str(doc.expires_at),
		"cached": cached_hit,
		"error": doc.error_message
		if "System Manager" in frappe.get_roles()
		else (bool(doc.error_message) or None),
		"result": json.loads(doc.result_json or "{}"),
		"metrics": json.loads(doc.metrics_json or "{}"),
	}


def run_analysis(district, settings):
	metrics = build_metrics(district or None)
	result, source, model, error = None, "规则引擎", None, None
	if settings.enable_llm and settings.get_password("api_key", raise_exception=False):
		try:
			result = llm_analysis(settings, metrics)
			source, model = "大模型", f"{settings.provider} · {settings.resolved_model()}"
		except Exception as e:
			error = str(e)[:500]
			frappe.log_error(title="换电数据分析：大模型调用失败", message=frappe.get_traceback())
	if not result:
		result = rule_analysis(metrics)
	now = now_datetime()
	doc = frappe.get_doc(
		{
			"doctype": "Data Analysis Record",
			"scope_label": metrics["scope"],
			"district": district or None,
			"source": source,
			"model": model,
			"generated_at": now,
			"expires_at": add_to_date(now, hours=float(settings.cache_hours or 3)),
			"requested_by": frappe.session.user,
			"headline": (result.get("headline") or "")[:140],
			"summary": result.get("summary"),
			"error_message": error,
			"result_json": json.dumps(result, ensure_ascii=False, indent=1),
			"metrics_json": json.dumps(metrics, ensure_ascii=False, default=str),
		}
	)
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return doc


# ---------------------------------------------------------------- 指标准备


def build_metrics(district=None):
	districts = resolve_districts(district)
	scope = district or "全杭州"
	today_d = getdate(today())
	month_start = getdate(get_first_day(today_d))
	events = load_events(districts)
	periods = build_periods(add_months(month_start, -11), today_d, "月")
	rows = period_table(events, periods)
	summary = summarize(rows)
	monthly = [
		{
			"月份": r["period"],
			"新开通": r["new"],
			"其中回流": r["returning"],
			"退租": r["churn"],
			"暂停": r["pause"],
			"净增": r["net"],
			"期末活跃": r["closing"],
			"流失率%": r["churn_rate"],
			"续费率%": r["renew_rate"],
			"月流水": r["mrr"],
			"新增MRR": r["mrr_new"],
			"扩张MRR": r["mrr_expansion"],
			"恢复MRR": r["mrr_reactivation"],
			"收缩MRR": r["mrr_contraction"],
			"流失MRR": r["mrr_churn"],
			"增长质量比": r["quick_ratio"],
			"主要退租原因": max(r["reasons"], key=r["reasons"].get) if r["reasons"] else None,
			"是否未满月": r["partial"],
		}
		for r in rows
	]

	since90 = add_days(today_d, -89)
	reasons = churn_reason_breakdown(events, since90)
	total_churn90 = sum(x["value"] for x in reasons) or 1

	# 渠道获客质量：近 6 个月各渠道开通的骑手，至今已退租的比例
	since180 = add_days(today_d, -180)
	opened = {}
	for e in events:
		if e.event_type == EVENT_NEW and e.event_date >= since180:
			opened[e.rider_id] = e
	state = Replayer(events).advance(add_days(today_d, 1)).state
	quality = Counter()
	lost = Counter()
	for rid, e in opened.items():
		key = f"{e.channel}（{e.event_date.month}月开通）" if e.channel == "平台合作" else e.channel
		quality[key] += 1
		if state.get(rid, {}).get("status") == "退租":
			lost[key] += 1
	channel_quality = [
		{"渠道": k, "开通人数": v, "已退租": lost[k], "退租占比%": round(lost[k] * 100.0 / v, 1)}
		for k, v in quality.most_common()
		if v >= 10
	]

	channel90 = group_flows(events, since90, "channel")
	platform90 = group_flows(events, since90, "platform")

	# 区域对比（全杭州范围时）
	district_cmp = []
	if len(districts) > 1:
		for d in districts:
			drows = period_table(events, periods[-3:], {"district": d})
			ds = summarize(drows)
			district_cmp.append(
				{
					"区域": d,
					"期末活跃": ds.get("closing", 0),
					"近3月新开通": ds.get("new", 0),
					"近3月退租": ds.get("churn", 0),
					"近3月平均流失率%": ds.get("avg_churn_rate", 0),
				}
			)
		district_cmp.sort(key=lambda x: -x["近3月平均流失率%"])

	# 站点供给压力
	stations = {
		s.name: s
		for s in frappe.get_all(
			"Swap Station",
			filters={"district": ("in", districts)},
			fields=["name", "station_name", "district", "slots"],
		)
	}
	supply = Counter(
		e.station
		for e in events
		if e.event_type == EVENT_CHURN and e.event_date >= since90 and e.churn_reason in SUPPLY_REASONS
	)
	active_by_station = Counter(
		s.get("station") for s in state.values() if s.get("status") in ("在租", "暂停")
	)
	station_pressure = []
	for code, n in supply.most_common(5):
		s = stations.get(code)
		if not s:
			continue
		station_pressure.append(
			{
				"站点": f"{s.district}·{s.station_name}",
				"近90天因柜点少/缺电退租": n,
				"当前活跃骑手": active_by_station.get(code, 0),
				"格口数": s.slots,
				"柜均骑手": round(active_by_station.get(code, 0) / s.slots, 2) if s.slots else None,
			}
		)

	risk, active_now = score_riders(events, districts)
	risk_levels = Counter(r["level"] for r in risk)
	risk_signals = Counter(reason.split("（")[0].split(" ")[0] for r in risk for reason in r["reasons"])

	return {
		"scope": scope,
		"as_of": str(today_d),
		"overview": {
			"当前活跃骑手": active_now,
			"12个月前期初活跃": summary.get("opening"),
			"12个月累计新开通": summary.get("new"),
			"其中回流骑手": summary.get("returning"),
			"12个月累计退租": summary.get("churn"),
			"平均月流失率%": summary.get("avg_churn_rate"),
			"平均续费率%": summary.get("avg_renew_rate"),
			"当前月流水": summary.get("mrr"),
			"12个月增长质量比": summary.get("quick_ratio"),
			"说明": "当月尚未结束（是否未满月=true）的数据不完整，比较趋势时请以已结束月份为准；"
			"增长质量比 =（新增+扩张+恢复 MRR）÷（流失+收缩 MRR），>1 表示收入在增长，约 4 为健康。",
			"押金沉淀": summary.get("deposit"),
		},
		"monthly": monthly,
		"churn_reasons_90d": [
			{"原因": x["name"], "人数": x["value"], "占比%": round(x["value"] * 100.0 / total_churn90, 1)}
			for x in reasons
		],
		"channel_90d": [{"渠道": k, "新开通": v["new"], "退租": v["churn"]} for k, v in channel90.items()],
		"platform_90d": [{"平台": k, "新开通": v["new"], "退租": v["churn"]} for k, v in platform90.items()],
		"channel_quality_6m": channel_quality,
		"district_compare": district_cmp,
		"station_pressure": station_pressure,
		"risk": {
			"高风险": risk_levels.get("高", 0),
			"中风险": risk_levels.get("中", 0),
			"主要信号": dict(risk_signals.most_common(5)),
		},
		"chart": {
			"months": [r["period"] for r in rows],
			"new": [r["new"] for r in rows],
			"churn": [r["churn"] for r in rows],
			"closing": [r["closing"] for r in rows],
			"churn_rate": [r["churn_rate"] for r in rows],
			"reasons": reasons,
		},
	}


# ---------------------------------------------------------------- 大模型


def call_llm(settings, messages, max_tokens=1800, json_mode=True):
	"""调用 OpenAI 兼容接口（DeepSeek / 智谱 GLM）。

	默认关闭思考模式（两家新模型默认开启，会显著增加耗时），并要求 JSON 输出；
	若服务商不支持这些可选参数返回 400，则去掉可选参数重试一次。
	"""
	api_key = settings.get_password("api_key", raise_exception=False)
	if not api_key:
		frappe.throw("请先在《换电增长设置》中填写 API Key")
	payload = {
		"model": settings.resolved_model(),
		"messages": messages,
		"temperature": 0.3,
		"max_tokens": max_tokens,
	}
	optional = {"thinking": {"type": "disabled"}}
	if json_mode:
		optional["response_format"] = {"type": "json_object"}
	url = f"{settings.resolved_base_url()}/chat/completions"
	headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
	timeout = int(settings.timeout or 90)
	resp = requests.post(url, headers=headers, json={**payload, **optional}, timeout=timeout)
	if resp.status_code == 400:
		resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
	if resp.status_code >= 400:
		raise Exception(f"模型接口返回 {resp.status_code}：{resp.text[:300]}")
	return resp.json()["choices"][0]["message"]["content"]


def llm_analysis(settings, metrics):
	data = {k: v for k, v in metrics.items() if k != "chart"}
	content = call_llm(
		settings,
		[
			{"role": "system", "content": SYSTEM_PROMPT},
			{
				"role": "user",
				"content": f"分析范围：{metrics['scope']}，数据截至 {metrics['as_of']}。指标如下：\n"
				+ json.dumps(data, ensure_ascii=False),
			},
		],
	)
	result = parse_json(content)
	if not result.get("headline") or not result.get("findings"):
		raise Exception("模型返回内容缺少必要字段")
	return normalize(result)


def parse_json(text):
	text = (text or "").strip()
	if text.startswith("```"):
		text = text.strip("`")
		text = text[text.find("{") :]
	start, end = text.find("{"), text.rfind("}")
	return json.loads(text[start : end + 1])


def normalize(result):
	result.setdefault("causes", [])
	result.setdefault("actions", [])
	result.setdefault("site_suggestions", [])
	for f in result.get("findings", []):
		if f.get("level") not in ("风险", "关注", "积极"):
			f["level"] = "关注"
	for a in result.get("actions", []):
		if a.get("priority") not in ("高", "中", "低"):
			a["priority"] = "中"
	return result


# ---------------------------------------------------------------- 规则引擎（降级方案）

REASON_ACTIONS = {
	"附近柜点少": ("在退租集中的片区加密柜点，优先选址配送站和商圈出口", "补柜后同片区退租下降"),
	"常缺满电电池": ("对高峰缺电站点增加电池调拨与格口扩容，设置满电率预警", "减少高峰排队与缺电流失"),
	"价格偏高": ("对价格敏感骑手推出季卡/阶梯价与续费优惠，补贴到期前提前触达", "提升补贴到期后的续费率"),
	"转用其他品牌": ("对标竞品柜点与价格，强化老客权益与推荐奖励", "降低被竞品挖角"),
	"不再跑单（返乡/转行）": ("推广暂停保号，节后定向召回返乡骑手", "提升回流比例"),
	"车辆不兼容": ("与车行合作提供适配改装或车电一体套餐", "减少因车型流失"),
	"其他": ("回访退租骑手，补充退租原因明细", "完善流失归因"),
}


def rule_analysis(m):
	monthly = m["monthly"]
	ov = m["overview"]
	findings, causes, actions, sites = [], [], [], []
	if not monthly:
		return {
			"headline": "暂无数据",
			"summary": "所选范围暂无服务单数据。",
			"findings": [],
			"causes": [],
			"actions": [],
			"site_suggestions": [],
		}

	opening = ov.get("12个月前期初活跃") or 0
	growth = round((ov["当前活跃骑手"] - opening) * 100.0 / opening, 1) if opening else None
	# 趋势判断只用已结束的月份，避免月初数据不全造成"流失率骤降"的误判
	complete = [x for x in monthly if not x.get("是否未满月")] or monthly
	worst = max(complete, key=lambda x: x["流失率%"])
	best_new = max(complete, key=lambda x: x["新开通"])
	recent = complete[-3:]
	recent_rate = round(sum(x["流失率%"] for x in recent) / len(recent), 2)
	recent_label = f"{recent[0]['月份']}~{recent[-1]['月份']}"

	findings.append(
		{
			"title": "活跃骑手持续增长" if (growth or 0) > 0 else "活跃骑手规模下滑",
			"detail": f"活跃骑手由 {opening} 人变为 {ov['当前活跃骑手']} 人（{'+' if (growth or 0) >= 0 else ''}{growth}%），"
			f"12 个月累计新开通 {ov['12个月累计新开通']} 人、退租 {ov['12个月累计退租']} 人。",
			"level": "积极" if (growth or 0) > 0 else "风险",
		}
	)
	findings.append(
		{
			"title": f"{worst['月份']} 流失率最高",
			"detail": f"{worst['月份']} 退租 {worst['退租']} 人，流失率 {worst['流失率%']}%（月均 {ov['平均月流失率%']}%），"
			f"主要原因为“{worst['主要退租原因']}”。",
			"level": "风险",
		}
	)
	if m["district_compare"]:
		top = m["district_compare"][0]
		findings.append(
			{
				"title": f"{top['区域']}流失率领先全市",
				"detail": f"{top['区域']}近 3 个月平均流失率 {top['近3月平均流失率%']}%，"
				f"退租 {top['近3月退租']} 人，高于全市月均 {ov['平均月流失率%']}%。",
				"level": "风险",
			}
		)
	weak = sorted([c for c in m["channel_quality_6m"] if c["开通人数"] >= 30], key=lambda c: -c["退租占比%"])
	if weak:
		w = weak[0]
		findings.append(
			{
				"title": f"{w['渠道'][:10]}获客质量偏弱",
				"detail": f"近 6 个月经{w['渠道']}开通 {w['开通人数']} 人，已退租 {w['已退租']} 人（{w['退租占比%']}%），为各渠道最高。",
				"level": "关注",
			}
		)
	if best_new["新开通"] and len(findings) < 4:
		findings.append(
			{
				"title": f"{best_new['月份']} 获客峰值",
				"detail": f"{best_new['月份']} 新开通 {best_new['新开通']} 人，净增 {best_new['净增']} 人。",
				"level": "积极",
			}
		)

	for r in m["churn_reasons_90d"][:3]:
		causes.append(f"近 90 天“{r['原因']}”导致退租 {r['人数']} 人，占 {r['占比%']}%。")
		act, expected = REASON_ACTIONS.get(r["原因"], REASON_ACTIONS["其他"])
		actions.append(
			{
				"action": act,
				"target": f"因“{r['原因']}”退租的人群",
				"priority": "高" if len(actions) == 0 else "中",
				"expected": expected,
			}
		)
	risk = m["risk"]
	if risk["高风险"]:
		actions.append(
			{
				"action": f"区域经理本周完成 {risk['高风险']} 名高风险骑手的电话回访，并在系统中一键指派跟进",
				"target": "流失预警名单中的高风险骑手",
				"priority": "高",
				"expected": "提前挽留，降低下月退租",
			}
		)
	for s in m["station_pressure"][:3]:
		sites.append(
			{
				"station": s["站点"],
				"suggestion": "增加格口或调拨满电电池"
				if (s["柜均骑手"] or 0) >= 1.5
				else "排查高峰缺电时段，优化电池调度",
				"reason": f"近 90 天 {s['近90天因柜点少/缺电退租']} 人因柜点少/缺电退租，柜均骑手 {s['柜均骑手']}。",
			}
		)

	trend_word = "回升" if recent_rate > ov["平均月流失率%"] else "回落"
	qr = ov.get("12个月增长质量比")
	headline = (
		f"{m['scope']}活跃骑手 {ov['当前活跃骑手']} 人，近 3 个完整月流失率{trend_word}至 {recent_rate}%"
	)
	summary = (
		f"{m['scope']}当前活跃骑手 {ov['当前活跃骑手']} 人，月流水 {int(ov['当前月流水'] or 0):,} 元。"
		f"{recent_label} 平均流失率 {recent_rate}%，{'高于' if recent_rate > ov['平均月流失率%'] else '低于'}全年均值 {ov['平均月流失率%']}%"
		f"{f'，12 个月增长质量比 {qr}' if qr else ''}。"
		f"近 90 天退租主因是“{m['churn_reasons_90d'][0]['原因'] if m['churn_reasons_90d'] else '-'}”，"
		f"当前识别出高风险骑手 {risk['高风险']} 人、中风险 {risk['中风险']} 人，建议优先处理供给不足站点并跟进高风险名单。"
	)
	return normalize(
		{
			"headline": headline,
			"summary": summary,
			"findings": findings[:4],
			"causes": causes,
			"actions": actions[:4],
			"site_suggestions": sites,
		}
	)
