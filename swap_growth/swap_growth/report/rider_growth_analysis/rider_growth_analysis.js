// Copyright (c) 2026, Adrian Ding and contributors
// For license information, please see license.txt

frappe.query_reports["Rider Growth Analysis"] = {
	filters: [
		{ fieldname: "from_date", label: "开始日期", fieldtype: "Date", reqd: 1,
			default: frappe.datetime.add_months(frappe.datetime.month_start(), -11) },
		{ fieldname: "to_date", label: "结束日期", fieldtype: "Date", reqd: 1, default: frappe.datetime.get_today() },
		{ fieldname: "granularity", label: "统计粒度", fieldtype: "Select", options: "周\n月\n季", default: "月", reqd: 1 },
		{ fieldname: "chart_view", label: "图表视图", fieldtype: "Select",
			options: "新开通与退租\n活跃骑手趋势\n流失率与续费率\nMRR 变动\n月流水", default: "新开通与退租" },
		{ fieldname: "district", label: "所在区", fieldtype: "Link", options: "Swap District" },
		{ fieldname: "station", label: "换电站点", fieldtype: "Link", options: "Swap Station",
			get_query: () => {
				const district = frappe.query_report.get_filter_value("district");
				return district ? { filters: { district } } : {};
			} },
		{ fieldname: "platform", label: "配送平台", fieldtype: "Select",
			options: "\n美团\n饿了么\n顺丰同城\n达达\n其他配送\n无（民用）" },
		{ fieldname: "channel", label: "获客渠道", fieldtype: "Select", options: "\n站点地推\n平台合作\n老带新\n线上自助\n政企合作" },
		{ fieldname: "package", label: "套餐", fieldtype: "Select", options: "\n单电月卡\n双电月卡\n车电一体月卡" },
		{ fieldname: "user_type", label: "用户类型", fieldtype: "Select", options: "\n个人骑手\n配送团队\n民用用户" },
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;
		if (column.fieldname === "net") {
			const color = data.net < 0 ? "var(--red-600)" : "var(--green-600)";
			return `<div style="text-align:right;color:${color};font-weight:600">${data.net > 0 ? "+" : ""}${data.net}</div>`;
		}
		if (column.fieldname === "churn_rate" && data.churn_rate >= 8) {
			return `<span style="color:var(--red-600);font-weight:600">${value}</span>`;
		}
		if (column.fieldname === "quick_ratio" && data.quick_ratio != null) {
			const color = data.quick_ratio >= 1 ? "var(--green-600)" : "var(--red-600)";
			return `<div style="text-align:right;color:${color};font-weight:600">${data.quick_ratio.toFixed(2)}</div>`;
		}
		if (column.fieldname === "returning" && data.returning > 0) {
			return `<span style="color:var(--blue-600);font-weight:600">${value}</span>`;
		}
		return value;
	},

	after_datatable_render(datatable) {
		swap_growth.enhance_datatable(datatable);
	},

	onload(report) {
		report.page.add_inner_button("数据分析", () => {
			frappe.route_options = { district: report.get_filter_value("district") || "" };
			frappe.set_route("swap-data-analysis");
		});
		report.page.add_inner_button("同期群留存", () => frappe.set_route("query-report", "Rider Cohort Retention"));
		report.page.add_inner_button("运营指挥大屏", () => frappe.set_route("swap-command-center"));
		report.page.set_indicator("指标口径", "blue");
		report.page.indicator.css("cursor", "pointer").on("click", () => {
			frappe.msgprint({
				title: "指标口径",
				message: `<ul style="line-height:1.9">
					<li><b>活跃骑手</b>：当前状态为在租或暂停（仍保有服务关系）的骑手</li>
					<li><b>流失率</b> = 本期退租 ÷ 期初活跃骑手（期初为 0 时以本期新开通为分母）</li>
					<li><b>续费率</b> = 本期续费 ÷（续费 + 退租 + 暂停），即到期骑手中选择续费的比例</li>
					<li><b>回流</b>：曾退租后再次开通的骑手</li>
					<li><b>月流水(MRR)</b> = 期末在租骑手当前套餐月费之和（暂停骑手不计）</li>
					<li><b>押金沉淀</b> = 期末活跃且以押金方式开通的骑手押金合计</li>
					<li><b>MRR 变动</b>：新增（首次开通）、扩张（升级差额）、恢复（回流开通、暂停后恢复）、收缩（暂停）、流失（在租退租）</li>
					<li><b>增长质量比</b> =（新增 + 扩张 + 恢复 MRR）÷（流失 + 收缩 MRR）。大于 1 表示收入在增长，订阅行业通常以约 4 为健康水平</li>
					<li>标注"进行中"的周期尚未结束，平均流失率只统计已结束的周期</li>
				</ul>`,
			});
		});
	},
};
