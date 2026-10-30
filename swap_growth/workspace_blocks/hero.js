root_element.querySelectorAll("[data-route]").forEach((el) => {
	el.addEventListener("click", (e) => {
		e.preventDefault();
		frappe.set_route(...el.dataset.route.split("/"));
	});
});
const set = (sel, text) => {
	const el = root_element.querySelector(sel);
	if (el) el.textContent = text;
};
const fmt = (n) => (n || 0).toLocaleString("zh-CN");
frappe.xcall("swap_growth.api.get_home_stats").then((s) => {
	set('[data-k="active"]', fmt(s.active));
	set('[data-k="mtd_new"]', fmt(s.mtd_new));
	set('[data-k="records"]', `预置演示数据：${fmt(s.riders)} 名骑手、${fmt(s.records)} 张单据、${s.stations} 个站点`);
});
frappe.xcall("swap_growth.api.card_high_risk").then((r) => set('[data-k="risk"]', fmt(r.value)));
frappe.xcall("swap_growth.analysis.get_latest_brief").then((b) => {
	if (!b) {
		set(".headline", "尚未生成分析，点击进入后自动生成");
		return;
	}
	set(".headline", b.headline || "查看最新分析结论");
	set(".tag.engine", b.source === "大模型" ? "大模型" : "规则引擎");
	set('[data-k="brief"]', `${b.scope} · ${b.source === "大模型" ? b.model : "内置规则引擎"} · ${(b.generated_at || "").slice(5, 16)} 生成${b.expired ? "（已过期，进入后自动更新）" : ""}`);
});
