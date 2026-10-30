# 业务常量：换电业务的主数据口径集中在这里，单据、报表、大屏、演示数据共用一份定义。

EVENT_NEW = "新开通"
EVENT_RENEW = "续费"
EVENT_UPGRADE = "升级套餐"
EVENT_PAUSE = "暂停"
EVENT_CHURN = "退租"
EVENT_TYPES = [EVENT_NEW, EVENT_RENEW, EVENT_UPGRADE, EVENT_PAUSE, EVENT_CHURN]

# 计费事件：发生后月卡有效期顺延 30 天
BILLING_EVENTS = (EVENT_NEW, EVENT_RENEW, EVENT_UPGRADE)
CARD_DAYS = 30

# 套餐定价参考杭州两轮换电市场常见区间（单电 230~350 元/月，车电组合 500 元以上）
PACKAGES = {
	"单电月卡": 269,
	"双电月卡": 429,
	"车电一体月卡": 539,
}
PACKAGE_RANK = {"单电月卡": 1, "双电月卡": 2, "车电一体月卡": 3}
DEPOSIT_AMOUNT = 300

USER_TYPES = ["个人骑手", "配送团队", "民用用户"]
PLATFORMS = ["美团", "饿了么", "顺丰同城", "达达", "其他配送", "无（民用）"]
CHANNELS = ["站点地推", "平台合作", "老带新", "线上自助", "政企合作"]
CHURN_REASONS = [
	"附近柜点少",
	"常缺满电电池",
	"价格偏高",
	"转用其他品牌",
	"不再跑单（返乡/转行）",
	"车辆不兼容",
	"其他",
]
# 与"补柜/扩容"直接相关的流失原因
SUPPLY_REASONS = ("附近柜点少", "常缺满电电池")

# 杭州 10 个主城区（2021 年区划调整后口径）：名称、行政区划代码、地图中心点、站点编码前缀
DISTRICTS = [
	{"name": "上城区", "adcode": "330102", "lng": 120.190, "lat": 30.262, "code": "SC", "order": 1},
	{"name": "拱墅区", "adcode": "330105", "lng": 120.150, "lat": 30.320, "code": "GS", "order": 2},
	{"name": "西湖区", "adcode": "330106", "lng": 120.120, "lat": 30.262, "code": "XH", "order": 3},
	{"name": "滨江区", "adcode": "330108", "lng": 120.205, "lat": 30.200, "code": "BJ", "order": 4},
	{"name": "萧山区", "adcode": "330109", "lng": 120.270, "lat": 30.170, "code": "XS", "order": 5},
	{"name": "余杭区", "adcode": "330110", "lng": 120.030, "lat": 30.330, "code": "YH", "order": 6},
	{"name": "临平区", "adcode": "330113", "lng": 120.300, "lat": 30.420, "code": "LP", "order": 7},
	{"name": "钱塘区", "adcode": "330114", "lng": 120.380, "lat": 30.300, "code": "QT", "order": 8},
	{"name": "富阳区", "adcode": "330111", "lng": 119.960, "lat": 30.050, "code": "FY", "order": 9},
	{"name": "临安区", "adcode": "330112", "lng": 119.720, "lat": 30.240, "code": "LA", "order": 10},
]

ROLE_OPERATOR = "换电运营专员"
ROLE_MANAGER = "区域经理"
ROLE_DIRECTOR = "运营总监"
APP_ROLES = [ROLE_OPERATOR, ROLE_MANAGER, ROLE_DIRECTOR]

REALTIME_EVENT = "swap_growth_feed"
