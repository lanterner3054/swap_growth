root_element.querySelectorAll("[data-route]").forEach((el) => {
	el.addEventListener("click", (e) => {
		e.preventDefault();
		frappe.set_route(el.dataset.route);
	});
});
const set = (sel, text) => {
	const el = root_element.querySelector(sel);
	if (el) el.textContent = text;
};
frappe.xcall("swap_growth.api.card_active_riders").then((r) => set('[data-k="active"]', (r.value || 0).toLocaleString("zh-CN")));
frappe.xcall("swap_growth.api.card_high_risk").then((r) => set('[data-k="risk"]', (r.value || 0).toLocaleString("zh-CN")));
frappe.xcall("swap_growth.analysis.get_latest_brief").then((b) => {
	if (!b) {
		set(".headline", "尚未生成分析，点击进入后自动生成");
		return;
	}
	set(".headline", b.headline || "查看最新分析结论");
	set(".tag.engine", b.source === "大模型" ? "大模型" : "规则引擎");
	set(".meta", `${b.scope} · ${b.source === "大模型" ? b.model : "内置规则引擎"} · ${(b.generated_at || "").slice(5, 16)} 生成${b.expired ? "（已过期，进入后自动更新）" : ""}`);
});
