// Copyright (c) 2026, Adrian Ding and contributors
// For license information, please see license.txt

const SR_COLORS = {
	新开通: "green",
	续费: "blue",
	升级套餐: "purple",
	暂停: "orange",
	退租: "red",
};

frappe.listview_settings["Rider Service Record"] = {
	add_fields: ["event_type", "docstatus", "is_returning"],
	has_indicator_for_draft: true,
	get_indicator(doc) {
		if (doc.docstatus === 0) return ["草稿", "gray", "docstatus,=,0"];
		if (doc.docstatus === 2) return ["已作废", "darkgrey", "docstatus,=,2"];
		const label = doc.event_type === "新开通" && doc.is_returning ? "回流开通" : doc.event_type;
		return [label, SR_COLORS[doc.event_type] || "gray", `event_type,=,${doc.event_type}`];
	},
	onload(listview) {
		listview.page.add_inner_button("增长分析报表", () => frappe.set_route("query-report", "Rider Growth Analysis"));
		listview.page.add_inner_button("运营指挥大屏", () => frappe.set_route("swap-command-center"));
	},
};
