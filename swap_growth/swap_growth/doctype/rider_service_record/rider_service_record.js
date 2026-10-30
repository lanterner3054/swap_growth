// Copyright (c) 2026, Adrian Ding and contributors
// For license information, please see license.txt

const SR_METHOD = "swap_growth.swap_growth.doctype.rider_service_record.rider_service_record";

frappe.ui.form.on("Rider Service Record", {
	setup(frm) {
		frm.set_query("station", () => ({ filters: { status: "运营中" } }));
	},

	refresh(frm) {
		if (frm.is_new() && frm.doc.event_type === "新开通" && !frm.doc.rider_id) {
			frm.trigger("assign_rider_id");
		}
		if (!frm.is_new() && frm.doc.rider_id) {
			frm.add_custom_button("该骑手全部记录", () => {
				frappe.set_route("List", "Rider Service Record", { rider_id: frm.doc.rider_id });
			});
		}
		frm.set_intro(
			frm.is_new() ? "录入骑手编号后，系统会自动带出该骑手最近一次的画像信息。" : "",
			"blue"
		);
	},

	assign_rider_id(frm) {
		frappe.call(`${SR_METHOD}.next_rider_id`).then((r) => {
			if (r.message && !frm.doc.rider_id) frm.set_value("rider_id", r.message);
		});
	},

	event_type(frm) {
		if (frm.doc.event_type === "新开通" && !frm.doc.rider_id) frm.trigger("assign_rider_id");
		if (frm.doc.event_type !== "退租") frm.set_value("churn_reason", "");
	},

	rider_id(frm) {
		if (!frm.doc.rider_id || !frm.is_new()) return;
		frappe.call(`${SR_METHOD}.get_rider_profile`, { rider_id: frm.doc.rider_id }).then((r) => {
			const p = r.message;
			if (!p) return;
			const keep = ["rider_name", "phone", "user_type", "team_name", "platform", "package",
				"deposit_mode", "station", "channel", "account_manager"];
			keep.forEach((f) => p[f] && frm.set_value(f, p[f]));
			if (p.in_service && frm.doc.event_type === "新开通") {
				frm.set_value("event_type", "续费");
				frappe.show_alert({ message: `该骑手在租中（最近：${p.event_type}），已切换为续费`, indicator: "orange" });
			} else if (!p.in_service && frm.doc.event_type !== "新开通") {
				frm.set_value("event_type", "新开通");
				frappe.show_alert({ message: "该骑手已退租，再次开通将记为回流骑手", indicator: "blue" });
			}
		});
	},
});
