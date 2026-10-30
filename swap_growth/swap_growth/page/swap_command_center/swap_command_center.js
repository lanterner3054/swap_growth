// Copyright (c) 2026, Adrian Ding and contributors
// For license information, please see license.txt

frappe.pages["swap-command-center"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: "换电运营指挥中心", single_column: true });
	wrapper.command_center = new SwapCommandCenter(page, wrapper);
};

frappe.pages["swap-command-center"].on_page_show = function (wrapper) {
	wrapper.command_center && wrapper.command_center.on_show();
};

const SGC = {
	W: 1920,
	H: 1080,
	REFRESH_MS: 60 * 1000,
	GEO_SOURCES: [
		"/assets/swap_growth/geo/hangzhou.json", // 部署时可放置最新区划
		"https://geo.datav.aliyun.com/areas_v3/bound/330100_full.json",
		"/assets/swap_growth/geo/hangzhou_legacy.json", // 离线兜底（旧区划）
	],
	color: {
		cyan: "#3fd0ff", green: "#3ee39b", red: "#ff5b6e", orange: "#ffb547",
		purple: "#a78bfa", text: "#d9e8ff", muted: "#7f9bc4", line: "rgba(63,160,255,0.18)",
	},
	fmt(n) {
		return (n || 0).toLocaleString("zh-CN");
	},
	money(n) {
		n = n || 0;
		return n >= 10000 ? (n / 10000).toFixed(1) : n.toLocaleString("zh-CN");
	},
	esc(s) {
		return frappe.utils.escape_html(s == null ? "" : String(s));
	},
};

class SwapCommandCenter {
	constructor(page, wrapper) {
		this.page = page;
		this.wrapper = wrapper;
		this.district = frappe.route_options?.district || "";
		this.charts = {};
		this.map_name = null;
		this.make_toolbar();
		this.make_layout();
		frappe.require(["/assets/swap_growth/js/lib/echarts.min.js", "/assets/swap_growth/css/command_center.css"], () =>
			this.init()
		);
	}

	// ------------------------------------------------------------ 布局
	make_toolbar() {
		this.scope_field = this.page.add_field({
			fieldname: "scope",
			label: "区域",
			fieldtype: "Select",
			options: [],
			change: () => {
				this.district = this.scope_field.get_value() || "";
				this.refresh(true);
				this.load_analysis();
			},
		});
		this.page.set_primary_action("全屏展示", () => this.toggle_fullscreen(), "es-line-expand");
		this.page.add_inner_button("增长分析报表", () => frappe.set_route("query-report", "Rider Growth Analysis"));
		this.page.add_inner_button("流失预警名单", () => frappe.set_route("query-report", "Rider Churn Risk"));
		if (frappe.user.has_role(["System Manager", "运营总监"])) {
			this.page.add_menu_item("演示：模拟录入一张新单据", () => {
				frappe.call("swap_growth.api.simulate_event").then((r) =>
					frappe.show_alert({ message: `已提交 ${r.message}，大屏将实时推送`, indicator: "green" })
				);
			});
		}
		this.page.add_menu_item("刷新数据", () => this.refresh(true));
	}

	make_layout() {
		const kpi = (key, label, accent) =>
			`<div class="sgc-kpi" style="--accent:${accent}"><div class="label">${label}</div>
			<div class="value sgc-num" data-kpi="${key}">--</div><div class="delta" data-delta="${key}">&nbsp;</div></div>`;
		const panel = (cls, title, body, extra = "", style = "") =>
			`<div class="sgc-panel ${cls}" style="${style}"><div class="sgc-ptitle"><span>${title}</span><em>${extra}</em></div>${body}</div>`;

		this.$outer = $(`<div class="sgc-outer"><div class="sgc-screen">
			<div class="sgc-header">
				<div class="sgc-hside"><span class="sgc-clock sgc-num"></span><span class="sgc-date"></span></div>
				<div class="sgc-title"><h1>杭州换电运营指挥中心</h1><small>RIDER GROWTH · BATTERY SWAP OPERATIONS</small></div>
				<div class="sgc-hside right"><span class="sgc-badge sgc-scope">全杭州</span><span class="sgc-badge sgc-live">实时</span>
					<span class="sgc-asof"></span></div>
			</div>
			<div class="sgc-kpis">
				${kpi("active", "活跃骑手", SGC.color.cyan)}
				${kpi("mtd_new", "本月新开通", SGC.color.green)}
				${kpi("mtd_churn", "本月退租", SGC.color.red)}
				${kpi("churn_rate", "本月流失率", SGC.color.orange)}
				${kpi("mrr", "月流水 MRR", SGC.color.purple)}
				${kpi("riders_per_slot", "柜均骑手", SGC.color.cyan)}
			</div>
			<div class="sgc-body">
				<div class="sgc-col">
					${panel("", "区域排名", `<div class="sgc-rank-row sgc-rank-head"><span></span><span>区域</span><span>活跃骑手</span><span style="text-align:right">30天净增</span><span style="text-align:right">流失率</span></div><div class="sgc-rank"></div>`, "点击区域可下钻", "flex:0 0 400px")}
					${panel("", "退租原因", `<div class="sgc-chart" data-chart="reasons"></div>`, "近 90 天")}
					${panel("", "骑手构成", `<div class="sgc-chart" data-chart="platform"></div>`, "按配送平台")}
				</div>
				<div class="sgc-col">
					${panel("", "骑手分布与柜点压力", `<div class="sgc-map-wrap"><div class="sgc-chart" data-chart="map" style="height:100%"></div>
						<div class="sgc-map-legend"><div><span class="sgc-dot" style="background:${SGC.color.green}"></span>柜均骑手 &lt; 2.5</div>
						<div><span class="sgc-dot" style="background:${SGC.color.orange}"></span>2.5 ~ 3.5</div>
						<div><span class="sgc-dot" style="background:${SGC.color.red}"></span>≥ 3.5 供给紧张</div></div>
						<div class="sgc-map-note"></div></div>`, "区块颜色 = 活跃骑手数 · 圆点 = 换电站点", "flex:1")}
					${panel("", "近 12 个月增长趋势", `<div class="sgc-chart" data-chart="trend"></div>`, "新开通 / 退租 / 活跃骑手", "flex:0 0 300px")}
				</div>
				<div class="sgc-col">
					${panel("sgc-ai", "数据分析", `<div class="sgc-ai-body sgc-loading">正在读取分析结果…</div>`, `<a class="sgc-link sgc-ai-more">完整分析 ›</a>`)}
					${panel("sgc-risk", "流失预警", `<div class="sgc-risk-list"></div>`, `<a class="sgc-link sgc-risk-more">全部名单 ›</a>`)}
					${panel("sgc-feed", "实时动态", `<div class="sgc-feed-list"></div>`, "新单据提交即推送")}
				</div>
			</div>
			<div class="sgc-toast"></div>
		</div></div>`).appendTo(this.page.main);
		this.$screen = this.$outer.find(".sgc-screen");
		this.$outer.find(".sgc-ai-more").on("click", () => {
			frappe.route_options = { district: this.district };
			frappe.set_route("swap-data-analysis");
		});
		this.$outer.find(".sgc-risk-more").on("click", () => {
			frappe.route_options = { district: this.district };
			frappe.set_route("query-report", "Rider Churn Risk");
		});
		this.page.main.css({ padding: "12px 0" });
	}

	// ------------------------------------------------------------ 初始化
	async init() {
		this.fit();
		$(window).on("resize.sgc", frappe.utils.debounce(() => this.fit(), 150));
		document.addEventListener("fullscreenchange", () => {
			this.$outer.toggleClass("sgc-full", !!document.fullscreenElement);
			setTimeout(() => this.fit(), 100);
		});
		this.tick();
		setInterval(() => this.tick(), 1000);

		const scopes = (await frappe.call("swap_growth.analysis.get_analysis_scopes")).message || [];
		this.scope_field.df.options = scopes.map((s) => ({ value: s.value, label: s.label }));
		if (!scopes.some((s) => s.value === this.district)) this.district = scopes[0]?.value || "";
		this.scope_field.refresh();
		this.scope_field.set_value(this.district);

		["reasons", "platform", "map", "trend"].forEach((key) => {
			this.charts[key] = echarts.init(this.$outer.find(`[data-chart="${key}"]`)[0], null, { renderer: "canvas" });
		});
		await this.load_geo();
		await this.refresh(true);
		this.load_analysis();
		this.timer = setInterval(() => this.refresh(), SGC.REFRESH_MS);

		frappe.realtime.on("swap_growth_feed", (data) => this.on_realtime(data));
	}

	on_show() {
		if (this.data) {
			this.fit();
			this.refresh();
		}
	}

	fit() {
		const full = !!document.fullscreenElement;
		const width = full ? window.innerWidth : this.$outer.width();
		const height = full ? window.innerHeight : null;
		const scale = full ? Math.min(width / SGC.W, height / SGC.H) : width / SGC.W;
		this.$screen.css({
			transform: `scale(${scale})`,
			left: full ? (width - SGC.W * scale) / 2 : 0,
			top: full ? (height - SGC.H * scale) / 2 : 0,
		});
		if (!full) this.$outer.css("height", SGC.H * scale);
		Object.values(this.charts).forEach((c) => c.resize());
	}

	toggle_fullscreen() {
		if (document.fullscreenElement) document.exitFullscreen();
		else this.$outer[0].requestFullscreen?.();
	}

	tick() {
		const now = new Date();
		const pad = (n) => String(n).padStart(2, "0");
		this.$outer.find(".sgc-clock").text(`${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`);
		const week = "日一二三四五六"[now.getDay()];
		this.$outer.find(".sgc-date").text(`${now.getFullYear()}年${now.getMonth() + 1}月${now.getDate()}日 星期${week}`);
	}

	async load_geo() {
		for (const url of SGC.GEO_SOURCES) {
			try {
				const ctrl = new AbortController();
				const timer = setTimeout(() => ctrl.abort(), 4000);
				const resp = await fetch(url, { signal: ctrl.signal });
				clearTimeout(timer);
				if (!resp.ok) continue;
				const geo = await resp.json();
				echarts.registerMap("hangzhou", geo);
				this.map_name = "hangzhou";
				if (url.includes("legacy")) {
					this.$outer.find(".sgc-map-note").text("离线底图为 2021 年区划调整前版本，临平、钱塘以站点展示");
				}
				return;
			} catch (e) {
				// 尝试下一个地图源
			}
		}
	}

	// ------------------------------------------------------------ 数据
	async refresh(show_loading) {
		const r = await frappe.call({
			method: "swap_growth.api.get_dashboard_data",
			args: { district: this.district || null },
			freeze: false,
		});
		this.data = r.message;
		this.render();
	}

	render() {
		const d = this.data;
		if (!d) return;
		this.$outer.find(".sgc-scope").text(this.district || (d.scope.length >= 10 ? "全杭州" : d.scope.join("、")));
		this.$outer.find(".sgc-asof").text(`数据截至 ${d.as_of}`);
		this.render_kpis(d.kpis);
		this.render_rank(d.districts);
		this.render_reasons(d.churn_reasons_90d);
		this.render_platform(d.platform_share);
		this.render_map(d);
		this.render_trend(d.trend);
		this.render_risk(d.risk);
		this.render_feed(d.feed);
	}

	render_kpis(k) {
		const set = (key, value, delta) => {
			this.$outer.find(`[data-kpi="${key}"]`).html(value);
			this.$outer.find(`[data-delta="${key}"]`).html(delta || "&nbsp;");
		};
		const arrow = (v, good_up = true, label = "") => {
			if (v === null || v === undefined) return label || "&nbsp;";
			const up = v >= 0;
			const cls = up === good_up ? "sgc-up" : "sgc-down";
			return `${label}<span class="${cls}">${up ? "▲" : "▼"} ${Math.abs(v)}%</span>`;
		};
		set("active", SGC.fmt(k.active), arrow(k.active_change, true, `较 30 天前 `) + ` · 暂停 ${k.paused}`);
		set("mtd_new", `${SGC.fmt(k.mtd_new)}<small>人</small>`, arrow(k.mtd_new_change, true, "较上月同期 ") + ` · 今日 +${k.today_new}`);
		set("mtd_churn", `${SGC.fmt(k.mtd_churn)}<small>人</small>`, arrow(k.mtd_churn_change, false, "较上月同期 ") + ` · 今日 ${k.today_churn}`);
		set("churn_rate", `${k.churn_rate}<small>%</small>`, `月卡续费率 <span class="sgc-up">${k.renew_rate}%</span>`);
		set("mrr", `${SGC.money(k.mrr)}<small>${k.mrr >= 10000 ? "万元" : "元"}</small>`,
			arrow(k.mrr_change, true, "较月初 ") + ` · 押金 ${SGC.money(k.deposit)}万`);
		set("riders_per_slot", `${k.riders_per_slot}<small>人/格口</small>`, `${k.stations} 个站点 · ${SGC.fmt(k.slots)} 个格口`);
	}

	render_rank(rows) {
		const max = Math.max(...rows.map((r) => r.active), 1);
		const html = rows
			.map(
				(r, i) => `<div class="sgc-rank-row" data-district="${SGC.esc(r.district)}">
				<span class="no sgc-num">${i + 1}</span><span>${SGC.esc(r.district)}</span>
				<div class="sgc-rank-bar"><i style="width:${(r.active / max) * 100}%"></i><b class="sgc-num">${SGC.fmt(r.active)}</b></div>
				<span class="net sgc-num ${r.net30 >= 0 ? "sgc-up" : "sgc-down"}">${r.net30 >= 0 ? "+" : ""}${r.net30}</span>
				<span class="rate sgc-num" style="color:${r.churn_rate30 >= 7 ? SGC.color.red : SGC.color.text}">${r.churn_rate30}%</span>
			</div>`
			)
			.join("");
		const $rank = this.$outer.find(".sgc-rank").html(html);
		$rank.find(".sgc-rank-row").on("click", (e) => {
			const district = $(e.currentTarget).data("district");
			if (this.scope_field.df.options.some((o) => o.value === district)) this.scope_field.set_value(district);
		});
	}

	render_reasons(rows) {
		const data = rows.slice(0, 7).reverse();
		this.charts.reasons.setOption(
			{
				grid: { left: 6, right: 40, top: 4, bottom: 4, containLabel: true },
				xAxis: { type: "value", show: false },
				yAxis: {
					type: "category",
					data: data.map((r) => r.name),
					axisLine: { show: false },
					axisTick: { show: false },
					axisLabel: { color: SGC.color.text, fontSize: 12, interval: 0 },
				},
				tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
				series: [
					{
						type: "bar",
						data: data.map((r) => ({
							value: r.value,
							itemStyle: {
								color: ["附近柜点少", "常缺满电电池"].includes(r.name) ? SGC.color.orange : "#2f7fe0",
								borderRadius: [0, 4, 4, 0],
							},
						})),
						barWidth: 12,
						label: { show: true, position: "right", color: SGC.color.text, fontSize: 13 },
						showBackground: true,
						backgroundStyle: { color: "rgba(63,160,255,0.08)", borderRadius: [0, 4, 4, 0] },
					},
				],
			},
			true
		);
	}

	render_platform(rows) {
		const palette = ["#3fd0ff", "#2f7fe0", "#3ee39b", "#ffb547", "#a78bfa", "#ff8fab"];
		this.charts.platform.setOption(
			{
				color: palette,
				tooltip: { trigger: "item", formatter: "{b}：{c} 人（{d}%）" },
				legend: {
					orient: "vertical",
					right: 6,
					top: "middle",
					itemWidth: 10,
					itemHeight: 10,
					textStyle: { color: SGC.color.text, fontSize: 13 },
					formatter: (name) => {
						const r = rows.find((x) => x.name === name);
						return `${name}  ${r ? r.value : ""}`;
					},
				},
				series: [
					{
						type: "pie",
						radius: ["48%", "74%"],
						center: ["32%", "50%"],
						label: { show: false },
						itemStyle: { borderColor: "#071833", borderWidth: 2 },
						data: rows,
					},
				],
			},
			true
		);
	}

	render_map(d) {
		const pressure = (v) => (v >= 3.5 ? SGC.color.red : v >= 2.5 ? SGC.color.orange : SGC.color.green);
		const by_district = Object.fromEntries(d.districts.map((r) => [r.district, r]));
		const max = Math.max(...d.districts.map((r) => r.active), 1);
		const option = {
			tooltip: {
				trigger: "item",
				backgroundColor: "rgba(6,24,52,0.95)",
				borderColor: SGC.color.cyan,
				textStyle: { color: "#fff" },
				formatter: (p) => {
					if (p.seriesType === "map") {
						const r = by_district[p.name];
						if (!r) return p.name;
						return `<b>${p.name}</b><br>活跃骑手：${r.active} 人<br>近30天：新开通 ${r.new30} / 退租 ${r.churn30}
							<br>流失率：${r.churn_rate30}%<br>柜均骑手：${r.riders_per_slot ?? "-"}`;
					}
					const s = p.data;
					return `<b>${s.district} · ${s.name}</b><br>活跃骑手：${s.value[2]} 人<br>格口：${s.slots} · 柜均骑手 ${s.riders_per_slot}`;
				},
			},
			visualMap: {
				type: "continuous",
				min: 0,
				max,
				seriesIndex: 0,
				left: 18,
				top: 56,
				itemHeight: 110,
				text: ["骑手多", "少"],
				textStyle: { color: SGC.color.muted },
				inRange: { color: ["#0b2246", "#114a8a", "#1c7fd0", "#33b6f0"] },
				calculable: false,
			},
			geo: this.map_name
				? {
						map: this.map_name,
						roam: true,
						center: [120.08, 30.24],
						zoom: 1.9,
						scaleLimit: { min: 1, max: 8 },
						label: { show: true, color: "rgba(217,232,255,0.85)", fontSize: 13 },
						itemStyle: { areaColor: "#0b2246", borderColor: "rgba(63,208,255,0.6)", borderWidth: 1 },
						emphasis: { label: { color: "#fff" }, itemStyle: { areaColor: "#1f6fc4" } },
						select: { disabled: true },
				  }
				: undefined,
			series: [],
		};
		if (this.map_name) {
			option.series.push({
				type: "map",
				geoIndex: 0,
				data: d.districts.map((r) => ({ name: r.district, value: r.active })),
			});
		}
		const points = d.stations.map((s) => ({ ...s, itemStyle: { color: pressure(s.riders_per_slot || 0) } }));
		const size = (val) => 6 + Math.sqrt(val[2] || 0) * 1.6;
		option.series.push(
			{
				type: "scatter",
				coordinateSystem: this.map_name ? "geo" : undefined,
				data: points.filter((p) => (p.riders_per_slot || 0) < 3.5),
				symbolSize: size,
				zlevel: 2,
			},
			{
				type: "effectScatter",
				coordinateSystem: this.map_name ? "geo" : undefined,
				data: points.filter((p) => (p.riders_per_slot || 0) >= 3.5),
				symbolSize: size,
				rippleEffect: { scale: 3, brushType: "stroke" },
				zlevel: 3,
			}
		);
		if (!this.map_name) {
			option.xAxis = { type: "value", scale: true, show: false };
			option.yAxis = { type: "value", scale: true, show: false };
			option.grid = { left: 20, right: 20, top: 20, bottom: 20 };
			delete option.visualMap;
			this.$outer.find(".sgc-map-note").text("地图底图加载失败，仅展示站点相对位置");
		}
		if (option.geo && this.district && d.stations.length) {
			// 选中单个区时，地图聚焦到该区站点中心
			const lng = d.stations.reduce((a, s) => a + s.value[0], 0) / d.stations.length;
			const lat = d.stations.reduce((a, s) => a + s.value[1], 0) / d.stations.length;
			Object.assign(option.geo, { center: [lng, lat], zoom: 5 });
		}
		this.charts.map.setOption(option, true);
	}

	render_trend(rows) {
		const axis = { color: SGC.color.muted, fontSize: 13 };
		this.charts.trend.setOption(
			{
				tooltip: { trigger: "axis" },
				legend: { top: 0, right: 10, textStyle: { color: SGC.color.text }, itemWidth: 12, itemHeight: 8 },
				grid: { left: 48, right: 56, top: 34, bottom: 26 },
				xAxis: {
					type: "category",
					data: rows.map((r) => r.period.slice(2).replace("-", "/")),
					axisLabel: axis,
					axisLine: { lineStyle: { color: SGC.color.line } },
				},
				yAxis: [
					{ type: "value", name: "人", nameTextStyle: axis, axisLabel: axis, splitLine: { lineStyle: { color: SGC.color.line } } },
					{ type: "value", name: "活跃", nameTextStyle: axis, axisLabel: axis, splitLine: { show: false } },
				],
				series: [
					{ name: "新开通", type: "bar", data: rows.map((r) => r.new), barWidth: 12,
						itemStyle: { color: SGC.color.green, borderRadius: [3, 3, 0, 0] } },
					{ name: "退租", type: "bar", data: rows.map((r) => r.churn), barWidth: 12,
						itemStyle: { color: SGC.color.red, borderRadius: [3, 3, 0, 0] } },
					{ name: "活跃骑手", type: "line", yAxisIndex: 1, data: rows.map((r) => r.closing), smooth: true,
						symbolSize: 6, lineStyle: { width: 3, color: SGC.color.cyan }, itemStyle: { color: SGC.color.cyan },
						areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
							{ offset: 0, color: "rgba(63,208,255,0.35)" }, { offset: 1, color: "rgba(63,208,255,0)" }]) } },
				],
			},
			true
		);
	}

	render_risk(risk) {
		this.$outer.find(".sgc-risk .sgc-ptitle em").html(
			`高风险 <b style="color:${SGC.color.red}">${risk.high}</b> · 中风险 <b style="color:${SGC.color.orange}">${risk.medium}</b>　<a class="sgc-link sgc-risk-more">全部名单 ›</a>`
		);
		this.$outer.find(".sgc-risk-more").off("click").on("click", () => {
			frappe.route_options = { district: this.district };
			frappe.set_route("query-report", "Rider Churn Risk");
		});
		const html = risk.top
			.slice(0, 4)
			.map(
				(r) => `<div class="sgc-risk-row">
				<div class="sgc-score sgc-num ${r.level === "高" ? "" : "mid"}">${r.score}</div>
				<div><div class="who">${SGC.esc(r.rider_name?.[0] || "")}** · ${SGC.esc(r.district)} · ${SGC.esc(r.station_name)}</div>
				<div class="why" title="${SGC.esc(r.reasons.join("；"))}">${SGC.esc(r.reasons[0] || "")}</div></div>
				<button class="sgc-btn" data-rider="${SGC.esc(r.rider_id)}">指派</button></div>`
			)
			.join("");
		const $list = this.$outer.find(".sgc-risk-list").html(html || `<div class="sgc-loading">暂无高风险骑手</div>`);
		$list.find(".sgc-btn").on("click", (e) => {
			const $btn = $(e.currentTarget);
			frappe.call("swap_growth.api.assign_follow_up", { rider_id: $btn.data("rider") }).then((r) => {
				$btn.text("已指派").prop("disabled", true);
				this.toast(`已指派给 ${r.message.user} 跟进`);
			});
		});
	}

	render_feed(rows) {
		this.$outer.find(".sgc-feed-list").html(rows.slice(0, 14).map((r) => this.feed_row(r)).join(""));
	}

	feed_row(r, flash) {
		const label = r.event_type === "新开通" && r.returning ? "回流" : r.event_type;
		const detail =
			r.event_type === "退租"
				? `${SGC.esc(r.rider_name)} · ${SGC.esc(r.station)} · ${SGC.esc(r.churn_reason || "")}`
				: `${SGC.esc(r.rider_name)} · ${SGC.esc(r.station)} · ${SGC.esc(r.package || "")}`;
		return `<div class="sgc-feed-row ${flash ? "flash" : ""}"><span class="t t-${r.event_type}">${label}</span>
			<span>${SGC.esc(r.district)} · ${detail}</span><span class="d">${(r.event_date || "").slice(5)}</span></div>`;
	}

	on_realtime(data) {
		if (this.district && data.district !== this.district) return;
		data.rider_name = data.rider_name || "";
		this.$outer.find(".sgc-feed-list").prepend(this.feed_row(data, true));
		this.$outer.find(".sgc-feed-row").slice(14).remove();
		this.toast(`${data.district} ${data.station}：${data.event_type === "退租" ? "骑手退租" : "骑手" + data.event_type}`);
		clearTimeout(this.rt_refresh);
		this.rt_refresh = setTimeout(() => this.refresh(), 3000);
	}

	toast(msg) {
		const $t = this.$outer.find(".sgc-toast").text(msg).addClass("show");
		clearTimeout(this.toast_timer);
		this.toast_timer = setTimeout(() => $t.removeClass("show"), 3000);
	}

	// ------------------------------------------------------------ 数据分析摘要
	async load_analysis() {
		const $body = this.$outer.find(".sgc-ai-body").addClass("sgc-loading").html("正在读取分析结果…");
		try {
			const r = await frappe.call({ method: "swap_growth.analysis.get_analysis", args: { district: this.district } });
			const a = r.message;
			const res = a.result || {};
			const items = (res.findings || [])
				.slice(0, 3)
				.map((f) => `<div class="sgc-ai-item"><span class="sgc-lv ${f.level}">${f.level}</span><b>${SGC.esc(f.title)}</b>${SGC.esc(f.detail)}</div>`)
				.join("");
			const t = (s) => (s || "").slice(5, 16);
			$body.removeClass("sgc-loading").css({ display: "flex", "flex-direction": "column", flex: 1, "min-height": 0 }).html(`
				<div class="sgc-ai-head">${SGC.esc(res.headline || "")}</div>
				<div class="sgc-ai-list">${items}</div>
				<div class="sgc-ai-foot"><span>${SGC.esc(a.scope)} · ${a.source === "大模型" ? SGC.esc(a.model) : "规则引擎"}</span>
				<span>${t(a.generated_at)} 生成 · 有效至 ${t(a.expires_at)}</span></div>`);
		} catch (e) {
			$body.html("分析暂不可用");
		}
	}
}
