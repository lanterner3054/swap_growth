// Copyright (c) 2026, Adrian Ding and contributors
// For license information, please see license.txt

const SETTINGS_METHOD = "swap_growth.swap_growth.doctype.swap_growth_settings.swap_growth_settings";

frappe.ui.form.on("Swap Growth Settings", {
	onload(frm) {
		frm.trigger("hide_password_strength");
	},
	hide_password_strength(frm) {
		// API Key 不是登录密码，不需要"密码强度"提示
		const field = frm.get_field("api_key");
		field.disable_password_checks?.();
		field.$wrapper.find(".password-strength-indicator").addClass("hidden");
	},
	refresh(frm) {
		frm.trigger("hide_password_strength");
		frm.add_custom_button("测试模型连接", () => {
			if (frm.is_dirty()) return frappe.msgprint("请先保存设置");
			frappe.call({ method: `${SETTINGS_METHOD}.test_connection`, freeze: true, freeze_message: "正在按正式分析的参数调用模型…" })
				.then((r) => {
					const m = r.message || {};
					const esc = frappe.utils.escape_html;
					if (m.ok) {
						frappe.msgprint({ title: "测试通过", indicator: "green",
							message: `模型：${esc(m.model)}，耗时 ${m.seconds} 秒，能按要求返回 JSON。<br>返回：<code>${esc(m.reply)}</code>` });
					} else {
						frappe.msgprint({ title: "测试未通过", indicator: "red",
							message: `模型：${esc(m.model)}<br><b>${esc(m.error)}</b><br><span class="text-muted small">${esc(m.detail || "")}</span>` });
					}
				});
		});
		frm.add_custom_button("重新生成演示数据", () => {
			frappe.confirm("将清空并重新生成站点、服务单、周换电和分析记录，确定继续？", () => {
				frappe.call({ method: `${SETTINGS_METHOD}.regenerate_demo_data`, freeze: true, freeze_message: "正在生成演示数据…" })
					.then((r) => { frappe.show_alert({ message: "演示数据已重新生成", indicator: "green" }); frm.trigger("render_demo_info"); });
			});
		}, "演示数据");
		frm.trigger("render_demo_info");
	},
	provider(frm) {
		const defaults = { DeepSeek: "deepseek-v4-flash", 智谱GLM: "glm-4.7-flash" };
		frm.set_df_property("model", "placeholder", defaults[frm.doc.provider] || "");
	},
	render_demo_info(frm) {
		frappe.call(`${SETTINGS_METHOD}.demo_stats`).then((r) => {
			const s = r.message || {};
			const range = s.range || [];
			frm.get_field("demo_info").$wrapper.html(`
				<div class="text-muted" style="line-height:1.9">
					当前数据：<b>${s.stations || 0}</b> 个换电站点，<b>${s.riders || 0}</b> 名骑手，
					<b>${s.records || 0}</b> 张已提交服务单，<b>${s.analyses || 0}</b> 条分析记录；
					时间范围 ${range[0] || "-"} 至 ${range[1] || "-"}。<br>
					演示数据为虚构，内置春节返乡、萧山民用推广、钱塘柜点不足、平台补贴四条业务剧情。
				</div>`);
		});
	},
});
