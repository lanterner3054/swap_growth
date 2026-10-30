// Copyright (c) 2026, Adrian Ding and contributors
// For license information, please see license.txt

frappe.query_reports["Rider Churn Risk"] = {
	filters: [
		{ fieldname: "district", label: "所在区", fieldtype: "Link", options: "Swap District" },
		{ fieldname: "level", label: "风险等级", fieldtype: "Select", options: "\n高\n中", default: "高" },
		{ fieldname: "platform", label: "配送平台", fieldtype: "Select",
			options: "\n美团\n饿了么\n顺丰同城\n达达\n其他配送\n无（民用）" },
		{ fieldname: "package", label: "套餐", fieldtype: "Select", options: "\n单电月卡\n双电月卡\n车电一体月卡" },
	],

	get_datatable_options(options) {
		return Object.assign(options, { checkboxColumn: true });
	},

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;
		if (column.fieldname === "level" || column.fieldname === "score") {
			const color = data.level === "高" ? "var(--red-600)" : "var(--orange-600)";
			return `<span style="color:${color};font-weight:600">${value}</span>`;
		}
		if (column.fieldname === "follow_up" && data.follow_up) {
			return `<span class="indicator-pill green">${value}</span>`;
		}
		return value;
	},

	onload(report) {
		report.page.add_inner_button("指派跟进（勾选的骑手）", () => {
			const rows = report.datatable.rowmanager.getCheckedRows().map((i) => report.data[i]);
			const todo = rows.filter((r) => r && !r.follow_up);
			if (!todo.length) return frappe.msgprint("请先勾选尚未指派的骑手");
			frappe.confirm(`将 ${todo.length} 名骑手的跟进任务指派给所在区的区域经理？`, async () => {
				let ok = 0;
				for (const r of todo) {
					await frappe.call("swap_growth.api.assign_follow_up", { rider_id: r.rider_id }).then(() => ok++);
				}
				frappe.show_alert({ message: `已指派 ${ok} 名骑手的跟进任务`, indicator: "green" });
				report.refresh();
			});
		});
		report.page.set_indicator("评分规则", "blue");
		report.page.indicator.css("cursor", "pointer").on("click", () => {
			frappe.msgprint({
				title: "流失风险评分规则（满分 100）",
				message: `<ul style="line-height:1.9">
					<li>换电频次骤降 ≥50%：+40；下降 30%~50%：+25（近 2 周 vs 前 4 周日均，来自换电柜 IoT 数据）</li>
					<li>当前暂停：+20</li>
					<li>常用站点近 90 天 ≥3 人因柜点少/缺电退租：+15</li>
					<li>近 150 天经"平台合作"补贴渠道开通：+15</li>
					<li>所在区近 90 天流失率高于全市 1.3 倍：+10</li>
					<li>月卡 7 天内到期：+10</li>
				</ul>≥55 分为高风险，35~54 分为中风险。`,
			});
		});
	},
};
