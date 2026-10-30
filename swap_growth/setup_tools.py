"""部署辅助：命令行配置大模型。

bench --site <站点> execute swap_growth.setup_tools.configure_llm \
	--kwargs "{'provider': 'DeepSeek', 'api_key': 'sk-...'}"
"""

import frappe


def configure_llm(provider="DeepSeek", api_key=None, model=None, cache_hours=3):
	if provider not in ("DeepSeek", "智谱GLM"):
		frappe.throw("provider 仅支持 DeepSeek 或 智谱GLM")
	settings = frappe.get_single("Swap Growth Settings")
	settings.provider = provider
	settings.model = model or ""
	settings.cache_hours = cache_hours
	if api_key:
		settings.api_key = api_key
		settings.enable_llm = 1
	settings.save(ignore_permissions=True)
	frappe.db.delete("Data Analysis Record")  # 切换模型后清空旧缓存
	frappe.db.commit()
	print(f"已启用 {provider} · {settings.resolved_model()}")
