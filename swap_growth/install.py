"""安装钩子：角色、行政区、演示账号与权限、站点本地化、演示数据。"""

import frappe

from swap_growth.constants import APP_ROLES, DISTRICTS, ROLE_DIRECTOR, ROLE_MANAGER, ROLE_OPERATOR

DEMO_PASSWORD = "Swap@2026"
DEMO_USERS = [
	{
		"email": "director@example.com",
		"first_name": "运营总监",
		"avatar": "/assets/swap_growth/images/avatars/director.svg",
		"roles": [ROLE_DIRECTOR],
		"districts": [],
	},
	{
		"email": "xiaoshan.mgr@example.com",
		"first_name": "萧山滨江区域经理",
		"avatar": "/assets/swap_growth/images/avatars/xiaoshan.svg",
		"roles": [ROLE_MANAGER],
		"districts": ["萧山区", "滨江区"],
	},
	{
		"email": "qiantang.mgr@example.com",
		"first_name": "钱塘临平区域经理",
		"avatar": "/assets/swap_growth/images/avatars/qiantang.svg",
		"roles": [ROLE_MANAGER],
		"districts": ["钱塘区", "临平区"],
	},
	{
		"email": "operator@example.com",
		"first_name": "运营专员",
		"avatar": "/assets/swap_growth/images/avatars/operator.svg",
		"roles": [ROLE_OPERATOR],
		"districts": [],
	},
]


def before_install():
	ensure_roles()


def after_install():
	ensure_roles()
	localize_site()
	ensure_districts()
	ensure_demo_users()
	ensure_settings()
	from swap_growth.demo.generator import generate

	summary = generate()
	frappe.db.commit()
	print(f"[swap_growth] 演示数据已生成：{summary}")


def after_migrate():
	"""升级时同步演示账号的显示名与头像。"""
	if frappe.db.exists("User", DEMO_USERS[0]["email"]):
		ensure_demo_users()


def ensure_roles():
	for role in APP_ROLES:
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(
				ignore_permissions=True
			)


def localize_site():
	"""面向国内客户：中文界面、上海时区、人民币。已完成初始化的站点只补充缺失项。"""
	if not frappe.db.exists("Currency", "CNY"):
		frappe.get_doc(
			{
				"doctype": "Currency",
				"currency_name": "CNY",
				"symbol": "¥",
				"fraction": "分",
				"fraction_units": 100,
				"number_format": "#,###.##",
				"enabled": 1,
			}
		).insert(ignore_permissions=True)
	else:
		# Frappe 自带的 CNY 未设置货币符号，补齐为 ¥
		frappe.db.set_value(
			"Currency", "CNY", {"enabled": 1, "symbol": "¥", "fraction": "分", "fraction_units": 100}
		)

	settings = frappe.get_single("System Settings")
	fresh = not frappe.is_setup_complete()
	if fresh:
		settings.language = "zh"
		settings.time_zone = "Asia/Shanghai"
		settings.country = "China" if frappe.db.exists("Country", "China") else settings.country
		settings.date_format = "yyyy-mm-dd"
		settings.time_format = "HH:mm"
		settings.number_format = "#,###.##"
		settings.currency = "CNY"
		settings.first_day_of_the_week = "Monday"
		settings.flags.ignore_mandatory = True
		settings.save(ignore_permissions=True)
		frappe.db.set_default("currency", "CNY")
		frappe.db.set_default("lang", "zh")
		# 纯 Frappe 演示站点跳过初始化向导，直接进入应用
		frappe.db.set_single_value("System Settings", "setup_complete", 1)
		frappe.db.sql("update `tabInstalled Application` set is_setup_complete = 1")
		frappe.db.set_default("desktop:home_page", "workspace")


def ensure_districts():
	for d in DISTRICTS:
		if frappe.db.exists("Swap District", d["name"]):
			continue
		frappe.get_doc(
			{
				"doctype": "Swap District",
				"district_name": d["name"],
				"adcode": d["adcode"],
				"center_lng": d["lng"],
				"center_lat": d["lat"],
				"sort_order": d["order"],
			}
		).insert(ignore_permissions=True)


def ensure_demo_users():
	director = None
	for spec in DEMO_USERS:
		email = spec["email"]
		if not frappe.db.exists("User", email):
			user = frappe.get_doc(
				{
					"doctype": "User",
					"email": email,
					"first_name": spec["first_name"],
					"user_image": spec["avatar"],
					"language": "zh",
					"send_welcome_email": 0,
					"new_password": DEMO_PASSWORD,
					"roles": [{"role": r} for r in spec["roles"]],
				}
			)
			user.flags.ignore_password_policy = True
			user.insert(ignore_permissions=True)
		else:
			# 已有站点：同步显示名与头像（去掉"（演示）"后缀，使用彩色头像）
			frappe.db.set_value(
				"User",
				email,
				{
					"first_name": spec["first_name"],
					"last_name": "",
					"full_name": spec["first_name"],
					"user_image": spec["avatar"],
				},
				update_modified=False,
			)
		if ROLE_DIRECTOR in spec["roles"]:
			director = email
		for district in spec["districts"]:
			frappe.db.set_value("Swap District", district, "manager", email)
			if not frappe.db.exists(
				"User Permission", {"user": email, "allow": "Swap District", "for_value": district}
			):
				frappe.get_doc(
					{
						"doctype": "User Permission",
						"user": email,
						"allow": "Swap District",
						"for_value": district,
						"apply_to_all_doctypes": 1,
					}
				).insert(ignore_permissions=True)
	# 未分配区域经理的区，由运营总监兜底跟进
	if director:
		for d in DISTRICTS:
			if not frappe.db.get_value("Swap District", d["name"], "manager"):
				frappe.db.set_value("Swap District", d["name"], "manager", director)


def ensure_settings():
	settings = frappe.get_single("Swap Growth Settings")
	if not settings.cache_hours:
		settings.cache_hours = 3
	if not settings.timeout:
		settings.timeout = 90
	if not settings.provider:
		settings.provider = "DeepSeek"
	settings.demo_auto_refresh = 1
	settings.save(ignore_permissions=True)
