// Copyright (c) 2026, Adrian Ding and contributors
// For license information, please see license.txt

frappe.query_reports["Rider Cohort Retention"] = {
	filters: [
		{ fieldname: "from_date", label: "开始月份", fieldtype: "Date", reqd: 1,
			default: frappe.datetime.add_months(frappe.datetime.month_start(), -11) },
		{ fieldname: "to_date", label: "结束日期", fieldtype: "Date", reqd: 1, default: frappe.datetime.get_today() },
		{ fieldname: "district", label: "所在区", fieldtype: "Link", options: "Swap District" },
		{ fieldname: "platform", label: "配送平台", fieldtype: "Select",
			options: "\n美团\n饿了么\n顺丰同城\n达达\n其他配送\n无（民用）" },
		{ fieldname: "channel", label: "获客渠道", fieldtype: "Select", options: "\n站点地推\n平台合作\n老带新\n线上自助\n政企合作" },
		{ fieldname: "user_type", label: "用户类型", fieldtype: "Select", options: "\n个人骑手\n配送团队\n民用用户" },
	],

	formatter(value, row, column, data, default_formatter) {
		if (data && /^m\d+$/.test(column.fieldname)) {
			const v = data[column.fieldname];
			if (v === null || v === undefined) return "";
			// 留存率热力：越高越深
			const alpha = Math.max(0.08, Math.min(0.85, (v - 40) / 60));
			const color = v >= 75 ? "#fff" : "var(--text-color)";
			return `<div style="background:rgba(11,107,203,${alpha});color:${color};text-align:center;border-radius:4px;padding:0 4px">${v.toFixed(1)}%</div>`;
		}
		value = default_formatter(value, row, column, data);
		if (data && column.fieldname === "cohort" && data.partial) {
			return `${value} <span class="text-muted small">(进行中)</span>`;
		}
		return value;
	},

	after_datatable_render(datatable) {
		swap_growth.enhance_datatable(datatable);
	},

	onload(report) {
		report.page.add_inner_button("增长分析报表", () => frappe.set_route("query-report", "Rider Growth Analysis"));
		report.page.set_indicator("对比不同渠道的留存曲线，可识别补贴获客质量", "blue");
	},
};
