// 换电增长分析：报表表格增强（全部报表共用）
frappe.provide("swap_growth");

swap_growth.enhance_datatable = function (datatable) {
	const wrapper = datatable && datatable.wrapper;
	if (!wrapper) return;
	const $w = $(wrapper);

	// 表头下方的列筛选框加上提示文字，避免被误认为是空行
	$w.find(".dt-filter").each(function () {
		if ($(this).outerWidth() > 50) $(this).attr("placeholder", "筛选…");
	});

	// 单元格内容被截断时，点击展开显示全文，鼠标移开即恢复
	const $pop = swap_growth.cell_popover();
	$w.off("click.sgpop").on("click.sgpop", ".dt-scrollable .dt-cell__content", (e) => {
		const el = e.currentTarget;
		const text = (el.innerText || "").trim();
		if (!text || el.scrollWidth <= el.clientWidth + 1) return;
		const rect = el.getBoundingClientRect();
		const width = Math.max(rect.width, Math.min(420, window.innerWidth - 32));
		const left = Math.min(rect.left, window.innerWidth - width - 16);
		$pop.text(text).css({ top: rect.top - 1, left: Math.max(8, left), width, display: "block" });
		swap_growth.cell_pop_shown_at = Date.now();
	});
	// 点击单元格时表格会自动滚动对齐，忽略紧随其后的滚动事件
	const hide_on_scroll = () => {
		if (Date.now() - (swap_growth.cell_pop_shown_at || 0) > 400) $pop.hide();
	};
	$(window).off("scroll.sgpop").on("scroll.sgpop", hide_on_scroll);
	$w.find(".dt-scrollable").off("scroll.sgpop").on("scroll.sgpop", hide_on_scroll);
};

swap_growth.cell_popover = function () {
	if (!swap_growth.$cell_pop) {
		swap_growth.$cell_pop = $(`<div class="sg-cell-pop"></div>`)
			.appendTo(document.body)
			.on("mouseleave", function () {
				$(this).hide();
			});
		frappe.router?.on?.("change", () => swap_growth.$cell_pop.hide());
	}
	return swap_growth.$cell_pop;
};
