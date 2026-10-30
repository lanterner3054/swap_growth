// Copyright (c) 2026, Adrian Ding and contributors
// For license information, please see license.txt

frappe.pages["swap-data-analysis"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: "数据分析", single_column: true });
	wrapper.analysis = new SwapDataAnalysis(page);
};

frappe.pages["swap-data-analysis"].on_page_show = function (wrapper) {
	const district = frappe.route_options?.district;
	if (wrapper.analysis && district !== undefined) {
		frappe.route_options = null;
		wrapper.analysis.set_scope(district);
	}
};

// 数据分析在后台生成：先请求，若正在生成则每 3 秒轮询一次，最多等 4 分钟
window.swap_growth_fetch_analysis = async function (district, force, on_wait) {
	let r = (await frappe.call({ method: "swap_growth.analysis.get_analysis", args: { district, force: force ? 1 : 0 } })).message;
	const deadline = Date.now() + 4 * 60 * 1000;
	while (r.status === "running") {
		on_wait && on_wait();
		if (Date.now() > deadline) throw new Error("分析生成超时，请稍后重试");
		await new Promise((resolve) => setTimeout(resolve, 3000));
		r = (await frappe.call({ method: "swap_growth.analysis.poll_analysis", args: { district: r.district, since: r.since } })).message;
	}
	if (r.status !== "done") throw new Error("分析生成失败，请稍后重试");
	return r;
};

class SwapDataAnalysis {
	constructor(page) {
		this.page = page;
		this.district = frappe.route_options?.district || "";
		frappe.route_options = null;
		this.charts = {};
		this.$body = $(`<div class="sga"></div>`).appendTo(page.main);
		this.make_toolbar();
		frappe.require(["/assets/swap_growth/js/lib/echarts.min.js", "/assets/swap_growth/css/data_analysis.css"], () =>
			this.init()
		);
	}

	make_toolbar() {
		this.scope_field = this.page.add_field({
			fieldname: "scope",
			label: "分析区域",
			fieldtype: "Select",
			options: [],
			change: () => {
				const value = this.scope_field.get_value() || "";
				if (value !== this.district) {
					this.district = value;
					this.load(false);
				}
			},
		});
		this.page.set_primary_action("重新分析", () => this.load(true), "refresh");
		this.page.add_inner_button("历史分析记录", () => frappe.set_route("List", "Data Analysis Record"));
		this.page.add_inner_button("运营指挥大屏", () => frappe.set_route("swap-command-center"));
		if (frappe.user.has_role(["System Manager", "运营总监"])) {
			this.page.add_menu_item("模型设置", () => frappe.set_route("Form", "Swap Growth Settings"));
		}
	}

	async init() {
		const scopes = (await frappe.call("swap_growth.analysis.get_analysis_scopes")).message || [];
		this.scope_field.df.options = scopes.map((s) => ({ value: s.value, label: s.label }));
		if (!scopes.some((s) => s.value === this.district)) this.district = scopes[0]?.value || "";
		this.scope_field.refresh();
		this.scope_field.set_value(this.district);
		this.load(false);
		$(window).on("resize.sga", frappe.utils.debounce(() => Object.values(this.charts).forEach((c) => c.resize()), 150));
	}

	set_scope(district) {
		if (!this.scope_field.df.options.length || district === this.district) return;
		this.scope_field.set_value(district);
	}

	async load(force) {
		const district = this.district;
		const token = (this.load_token = (this.load_token || 0) + 1);
		const scope_label = frappe.utils.escape_html(district || "全杭州");
		const waiting = (text) =>
			this.$body.html(`<div class="sga-loading"><div class="spinner"></div>${text}<br>
				<small>若调用大模型，通常需要 15~40 秒，期间可正常浏览其他页面；3 小时内再次打开会直接复用结果。</small></div>`);
		waiting(`正在读取 ${scope_label} 的数据分析…`);
		try {
			const a = await swap_growth_fetch_analysis(district, force, () =>
				waiting(`${force ? "正在重新分析" : "正在生成"} ${scope_label} 的数据分析…`)
			);
			if (token === this.load_token) this.render(a);
		} catch (e) {
			if (token !== this.load_token) return;
			this.$body.html(`<div class="sga-loading">${frappe.utils.escape_html(e.message || "分析失败，请稍后重试。")}
				<br><button class="btn btn-default btn-sm" style="margin-top:12px">重试</button></div>`);
			this.$body.find("button").on("click", () => this.load(force));
		}
	}

	render(a) {
		const esc = (s) => frappe.utils.escape_html(s == null ? "" : String(s));
		const res = a.result || {};
		const m = a.metrics || {};
		const ov = m.overview || {};
		const t = (s) => (s || "").slice(5, 16);
		const engine = a.source === "大模型" ? esc(a.model) : "内置规则引擎";
		const error_note =
			a.error && typeof a.error === "string"
				? `<span class="text-danger">大模型调用失败，已降级：${esc(a.error).slice(0, 80)}</span>`
				: a.error
				? `<span class="text-danger">大模型暂不可用，已使用规则引擎</span>`
				: "";

		const kpi = (label, value) => `<div class="sga-kpi"><div class="v">${value}</div><div class="l">${label}</div></div>`;
		const money = (v) => `¥${Math.round(v || 0).toLocaleString("zh-CN")}`;

		const findings = (res.findings || [])
			.map((f) => `<div class="sga-finding ${esc(f.level)}"><div class="t"><span class="sga-pill ${esc(f.level)}">${esc(f.level)}</span>${esc(f.title)}</div>
				<div class="d">${esc(f.detail)}</div></div>`)
			.join("");
		const causes = (res.causes || []).map((c) => `<li>${esc(c)}</li>`).join("");
		const actions = (res.actions || [])
			.map((x) => `<tr><td><span class="sga-pill ${esc(x.priority)}">${esc(x.priority)}</span></td><td><b>${esc(x.action)}</b>
				<div class="text-muted small">对象：${esc(x.target)}</div></td><td>${esc(x.expected)}</td></tr>`)
			.join("");
		const sites = (res.site_suggestions || [])
			.map((s) => `<div class="sga-site"><div class="n">📍 ${esc(s.station)}</div><div>${esc(s.suggestion)}</div>
				<div class="text-muted small">${esc(s.reason)}</div></div>`)
			.join("");

		this.$body.html(`
			<div class="sga-status">
				<span class="sga-tag ${a.cached ? "cached" : "fresh"}">${a.cached ? "缓存结果" : "最新生成"}</span>
				<span>范围：<b>${esc(a.scope)}</b></span><span>引擎：${engine}</span>
				<span>生成于 ${t(a.generated_at)}，有效至 ${t(a.expires_at)}</span>
				<span>有效期内重复打开不会重新分析；点击右上角"重新分析"可立即更新</span>${error_note}
			</div>
			<div class="sga-card sga-hero">
				<div class="sga-headline">${esc(res.headline)}</div>
				<div class="sga-summary">${esc(res.summary)}</div>
				<div class="sga-kpis">
					${kpi("当前活跃骑手", (ov["当前活跃骑手"] || 0).toLocaleString("zh-CN"))}
					${kpi("12 个月新开通", (ov["12个月累计新开通"] || 0).toLocaleString("zh-CN"))}
					${kpi("12 个月退租", (ov["12个月累计退租"] || 0).toLocaleString("zh-CN"))}
					${kpi("平均月流失率", `${ov["平均月流失率%"] ?? "-"}%`)}
					${kpi("平均续费率", `${ov["平均续费率%"] ?? "-"}%`)}
					${kpi("当前月流水", money(ov["当前月流水"]))}
					${kpi("12 个月增长质量比", ov["12个月增长质量比"] ?? "-")}
					${kpi("高风险骑手", m.risk ? m.risk["高风险"] : "-")}
				</div>
			</div>
			<div class="sga-charts">
				<div class="sga-card"><h4>近 12 个月新开通、退租与流失率</h4><div class="sga-chart" data-chart="trend"></div></div>
				<div class="sga-card"><h4>近 90 天退租原因</h4><div class="sga-chart" data-chart="reasons"></div></div>
			</div>
			<div class="sga-card"><h4>关键发现</h4><div class="sga-grid">${findings}</div></div>
			<div class="sga-two">
				<div class="sga-card"><h4>原因分析</h4><ul class="sga-causes">${causes}</ul></div>
				<div class="sga-card"><h4>行动建议</h4><table class="sga-table"><thead><tr><th width="54">优先级</th><th>行动</th><th width="30%">预期效果</th></tr></thead>
					<tbody>${actions}</tbody></table></div>
			</div>
			${sites ? `<div class="sga-card"><h4>补柜 / 选址建议</h4><div class="sga-sites">${sites}</div></div>` : ""}
			<div class="sga-note">分析仅使用聚合后的经营指标，不向模型发送任何骑手个人信息。每次分析均存档于《数据分析记录》。</div>
		`);
		this.render_charts(m.chart || {});
	}

	render_charts(c) {
		Object.values(this.charts).forEach((ch) => ch.dispose());
		this.charts = {};
		const dark = document.documentElement.getAttribute("data-theme") === "dark";
		const text = dark ? "#c0c6cc" : "#525252";
		const grid_line = dark ? "#333" : "#ededed";
		const trend = echarts.init(this.$body.find('[data-chart="trend"]')[0]);
		trend.setOption({
			color: ["#30a46c", "#e5484d", "#f5a524"],
			tooltip: { trigger: "axis" },
			legend: { top: 0, textStyle: { color: text } },
			grid: { left: 44, right: 50, top: 36, bottom: 28 },
			xAxis: { type: "category", data: (c.months || []).map((m) => m.slice(2).replace("-", "/")), axisLabel: { color: text } },
			yAxis: [
				{ type: "value", name: "人", axisLabel: { color: text }, splitLine: { lineStyle: { color: grid_line } } },
				{ type: "value", name: "流失率%", axisLabel: { color: text, formatter: "{value}%" }, splitLine: { show: false } },
			],
			series: [
				{ name: "新开通", type: "bar", data: c.new, barMaxWidth: 18, itemStyle: { borderRadius: [3, 3, 0, 0] } },
				{ name: "退租", type: "bar", data: c.churn, barMaxWidth: 18, itemStyle: { borderRadius: [3, 3, 0, 0] } },
				{
					name: "流失率",
					type: "line",
					yAxisIndex: 1,
					smooth: true,
					data: c.churn_rate,
					symbolSize: 7,
					lineStyle: { width: 3 },
					markPoint: { data: [{ type: "max", name: "最高" }], label: { formatter: "{c}%" } },
				},
			],
		});
		const reasons = echarts.init(this.$body.find('[data-chart="reasons"]')[0]);
		reasons.setOption({
			color: ["#e5484d", "#f5a524", "#0b6bcb", "#7c66dc", "#30a46c", "#12a594", "#8b8d98"],
			tooltip: { trigger: "item", formatter: "{b}：{c} 人（{d}%）" },
			legend: { bottom: 0, left: "center", itemWidth: 10, itemHeight: 10, itemGap: 8, textStyle: { color: text, fontSize: 11 } },
			series: [
				{
					type: "pie",
					radius: ["34%", "56%"],
					center: ["50%", "38%"],
					label: { color: text, formatter: "{d}%" },
					data: c.reasons || [],
				},
			],
		});
		this.charts = { trend, reasons };
	}
}
