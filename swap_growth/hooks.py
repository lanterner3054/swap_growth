app_name = "swap_growth"
app_title = "换电增长分析"
app_publisher = "Adrian Ding"
app_description = "基于 Frappe 的两轮换电用户增长分析：骑手服务单、增长与留存报表、运营指挥大屏、数据分析"
app_email = "ministerding@gmail.com"
app_license = "mit"
required_apps = ["frappe"]

add_to_apps_screen = [
	{
		"name": "swap_growth",
		"logo": "/assets/swap_growth/images/logo.svg",
		"title": "换电增长",
		"route": "/app/swap-growth",
	}
]

before_install = "swap_growth.install.before_install"
after_install = "swap_growth.install.after_install"
after_migrate = "swap_growth.install.after_migrate"

app_include_css = ["swap_growth.bundle.css"]
app_include_js = ["swap_growth.bundle.js"]

# 演示数据每日续写（可在《换电增长设置》中关闭）
scheduler_events = {"daily": ["swap_growth.demo.live.daily_tick"]}
