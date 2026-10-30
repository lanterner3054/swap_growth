#!/usr/bin/env bash
# =============================================================================
# swap_growth 一键部署（生产模式：nginx + supervisor）
# 适用：Ubuntu 22.04 / 24.04，root 执行，建议 2 核 4G 以上
#
# 用法：
#   curl -fsSL https://raw.githubusercontent.com/lanterner3054/swap_growth/main/deploy/deploy.sh -o deploy.sh
#   sudo SITE=demo.example.com bash deploy.sh
#
# 可选环境变量：
#   SITE              站点名（域名或任意名称，默认 swap-demo）
#   ADMIN_PASSWORD    Administrator 密码（默认随机生成）
#   DB_ROOT_PASSWORD  MariaDB root 密码（默认随机生成）
#   MIRROR            cn（默认，使用国内镜像）| global
#   APP_REPO          应用仓库地址（默认 GitHub）
#   FRAPPE_REPO       Frappe 仓库地址（默认 GitHub，可改为国内镜像）
#   GITHUB_PROXY      GitHub 加速前缀（可选，如 https://ghfast.top），GitHub 访问超时时使用
#   LLM_PROVIDER      DeepSeek | 智谱GLM（可选）
#   LLM_API_KEY       大模型 API Key（可选，填写后自动启用数据分析大模型）
# =============================================================================
set -euo pipefail

SITE=${SITE:-swap-demo}
# 密码保存在 /root/.swap_growth.env，重复执行脚本时复用
STATE_FILE=/root/.swap_growth.env
[ -f "$STATE_FILE" ] && . "$STATE_FILE"
ADMIN_PASSWORD=${ADMIN_PASSWORD:-$(openssl rand -hex 6)}
DB_ROOT_PASSWORD=${DB_ROOT_PASSWORD:-$(openssl rand -hex 10)}
MIRROR=${MIRROR:-cn}
APP_REPO=${APP_REPO:-https://github.com/lanterner3054/swap_growth}
FRAPPE_REPO=${FRAPPE_REPO:-https://github.com/frappe/frappe}
FRAPPE_BRANCH=${FRAPPE_BRANCH:-version-15}
NODE_VERSION=${NODE_VERSION:-20.18.1}
LLM_PROVIDER=${LLM_PROVIDER:-DeepSeek}
LLM_API_KEY=${LLM_API_KEY:-}
GITHUB_PROXY=${GITHUB_PROXY:-}
FRAPPE_USER=frappe
BENCH_DIR=/home/${FRAPPE_USER}/frappe-bench

log() { echo -e "\n\033[1;36m==> $*\033[0m"; }
die() { echo -e "\033[1;31m错误：$*\033[0m" >&2; exit 1; }
as_frappe() { sudo -u "$FRAPPE_USER" -H bash -lc "cd ~ && $*"; }

[ "$(id -u)" -eq 0 ] || die "请使用 root 执行"
cd /tmp
umask 077; printf 'ADMIN_PASSWORD=%s\nDB_ROOT_PASSWORD=%s\n' "$ADMIN_PASSWORD" "$DB_ROOT_PASSWORD" > "$STATE_FILE"; umask 022
. /etc/os-release
[[ "$ID" == "ubuntu" ]] || echo "提示：脚本针对 Ubuntu 编写，当前为 $PRETTY_NAME，继续尝试…"

# ---------------------------------------------------------------- 0. 内存
MEM_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
if [ "$MEM_MB" -lt 3800 ] && ! swapon --show | grep -q .; then
	log "内存 ${MEM_MB}MB，创建 4G 交换分区以保证前端构建成功"
	fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
	grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# ---------------------------------------------------------------- 1. 系统依赖
log "安装系统依赖"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y git curl wget xz-utils sudo cron pkg-config build-essential \
	python3-dev python3-venv python3-pip \
	mariadb-server mariadb-client libmariadb-dev \
	redis-server nginx supervisor xvfb libfontconfig1 fontconfig fonts-noto-cjk

# ---------------------------------------------------------------- 2. Node.js
NODE_MAJOR=$(node -v 2>/dev/null | sed 's/v\([0-9]*\).*/\1/' || echo 0)
if [ "${NODE_MAJOR:-0}" -lt 18 ]; then
	log "安装 Node.js ${NODE_VERSION}"
	if [ "$MIRROR" = "cn" ]; then NODE_BASE=https://npmmirror.com/mirrors/node; else NODE_BASE=https://nodejs.org/dist; fi
	curl -fsSL "${NODE_BASE}/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz" -o /tmp/node.tar.xz
	tar -xJf /tmp/node.tar.xz -C /usr/local --strip-components=1
fi
if [ "$MIRROR" = "cn" ]; then npm config set registry https://registry.npmmirror.com -g; fi
npm install -g yarn

# ---------------------------------------------------------------- 3. 镜像源
if [ "$MIRROR" = "cn" ]; then
	log "配置国内镜像（pip / npm / yarn）"
	mkdir -p /etc/pip && cat > /etc/pip.conf <<'EOF'
[global]
index-url = https://mirrors.aliyun.com/pypi/simple/
trusted-host = mirrors.aliyun.com
EOF
	# bench 使用 uv 安装 Python 依赖，uv 不读取 pip.conf
	cat > /etc/profile.d/swap_growth_mirror.sh <<'EOF'
export UV_DEFAULT_INDEX=https://mirrors.aliyun.com/pypi/simple/
export UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
export UV_HTTP_TIMEOUT=120
EOF
fi

# ---------------------------------------------------------------- 4. MariaDB
log "配置 MariaDB（utf8mb4）"
cat > /etc/mysql/mariadb.conf.d/99-frappe.cnf <<'EOF'
[mysqld]
character-set-client-handshake = FALSE
character-set-server = utf8mb4
collation-server = utf8mb4_unicode_ci
[mysql]
default-character-set = utf8mb4
EOF
systemctl restart mariadb
SET_ROOT_SQL="ALTER USER 'root'@'localhost' IDENTIFIED VIA mysql_native_password USING PASSWORD('${DB_ROOT_PASSWORD}') OR unix_socket; FLUSH PRIVILEGES;"
if mysql -uroot -p"${DB_ROOT_PASSWORD}" -e "select 1" >/dev/null 2>&1; then
	:
elif mysql -uroot -e "select 1" >/dev/null 2>&1; then
	mysql -uroot -e "$SET_ROOT_SQL"
else
	# root 密码未知（例如上次执行中断）：以跳过权限模式启动并重置
	log "重置 MariaDB root 密码"
	systemctl stop mariadb
	mkdir -p /run/mysqld && chown mysql: /run/mysqld
	mysqld_safe --skip-grant-tables --skip-networking >/dev/null 2>&1 &
	for i in $(seq 1 30); do mysql -uroot -e "select 1" >/dev/null 2>&1 && break; sleep 1; done
	mysql -uroot -e "FLUSH PRIVILEGES; $SET_ROOT_SQL"
	mysqladmin -uroot -p"${DB_ROOT_PASSWORD}" shutdown || pkill -f mysqld
	sleep 3
	systemctl start mariadb
fi
mysql -uroot -p"${DB_ROOT_PASSWORD}" -e "select 1" >/dev/null || die "MariaDB root 密码设置失败"
systemctl enable --now redis-server

# ---------------------------------------------------------------- 5. bench
log "安装 frappe-bench"
id "$FRAPPE_USER" >/dev/null 2>&1 || useradd -m -s /bin/bash "$FRAPPE_USER"
chmod o+rx /home/${FRAPPE_USER}
python3 -m pip install --break-system-packages frappe-bench 2>/dev/null || python3 -m pip install frappe-bench
if [ "$MIRROR" = "cn" ]; then
	as_frappe "npm config set registry https://registry.npmmirror.com; yarn config set registry https://registry.npmmirror.com"
fi

# GitHub 网络：慢速连接自动中断重试；可选加速前缀
as_frappe "git config --global http.lowSpeedLimit 1000 && git config --global http.lowSpeedTime 60"
if [ -n "$GITHUB_PROXY" ]; then
	log "GitHub 走加速前缀 ${GITHUB_PROXY}"
	as_frappe "git config --global url.${GITHUB_PROXY%/}/https://github.com/.insteadOf https://github.com/"
fi
retry() { local n=0; until "$@"; do n=$((n+1)); [ $n -ge 4 ] && return 1; echo "  第 $n 次失败，15 秒后重试…"; sleep 15; done; }

if [ ! -d "$BENCH_DIR/apps/frappe" ]; then
	log "初始化 Frappe ${FRAPPE_BRANCH}（首次约 10~20 分钟）"
	rm -rf "$BENCH_DIR"
	as_frappe "cd ~ && yes N | bench init --frappe-path ${FRAPPE_REPO} --frappe-branch ${FRAPPE_BRANCH} frappe-bench" || true
fi
[ -d "$BENCH_DIR/apps/frappe" ] || die "Frappe 源码获取失败（GitHub 连接超时）。可重试，或设置 GITHUB_PROXY=https://ghfast.top 后重试"

# 兜底 1：Frappe 依赖两个 GitHub 上的 Python 包（gunicorn、PyPika），uv 只尝试一次，
# 国内网络常超时。改为先用 git 按提交号预取（自动重试），再从本地目录安装。
if ! as_frappe "cd $BENCH_DIR && env/bin/python -c 'import frappe'" >/dev/null 2>&1; then
	log "安装 Frappe Python 依赖（GitHub 依赖改为本地预取）"
	cat > /home/${FRAPPE_USER}/.vendor_git_deps.py <<'PYEOF'
"""把 Frappe pyproject.toml 中的 GitHub git 依赖改为本地预取目录。

国内服务器访问 GitHub 时常超时，而 uv/pip 安装 git 依赖时只尝试一次。
这里先用 git 按提交号拉取（失败自动重试），再把依赖指向本地目录。
用法：在 bench 目录下执行  python3 vendor_git_deps.py apps/frappe/pyproject.toml
"""

import pathlib
import re
import shutil
import subprocess
import sys
import time

PATTERN = re.compile(r'"([A-Za-z0-9_.-]+) @ git\+(https://github\.com/[^@"]+?)(?:\.git)?@([0-9a-f]{7,40})"')
VENDOR = pathlib.Path.home() / "vendor"


def head(d):
	r = subprocess.run(["git", "-C", str(d), "rev-parse", "HEAD"], capture_output=True, text=True)
	return r.stdout.strip()


def fetch(name, url, sha, attempts=6):
	d = VENDOR / name.lower()
	if (d / ".git").exists() and head(d).startswith(sha):
		return d
	for i in range(attempts):
		shutil.rmtree(d, ignore_errors=True)
		d.mkdir(parents=True)
		steps = [
			["git", "init", "-q"],
			["git", "fetch", "-q", "--depth", "1", url, sha],
			["git", "checkout", "-q", "FETCH_HEAD"],
		]
		if all(subprocess.run(s, cwd=d).returncode == 0 for s in steps):
			return d
		print(f"  拉取 {url} 失败（第 {i + 1}/{attempts} 次），15 秒后重试…", flush=True)
		time.sleep(15)
	sys.exit(f"无法从 GitHub 拉取 {url}。可设置 GITHUB_PROXY 环境变量后重新执行部署脚本。")


def main(path):
	p = pathlib.Path(path)
	text = p.read_text()

	def repl(m):
		name, url, sha = m.groups()
		print(f"  预取 {name} @ {sha[:8]}", flush=True)
		return f'"{name} @ file://{fetch(name, url, sha)}"'

	new = PATTERN.sub(repl, text)
	if new != text:
		p.write_text(new)
		print("  已改为本地依赖", flush=True)


if __name__ == "__main__":
	main(sys.argv[1])
PYEOF
	chown ${FRAPPE_USER}: /home/${FRAPPE_USER}/.vendor_git_deps.py
	as_frappe "cd $BENCH_DIR && [ -x env/bin/python ] || uv venv env --seed --python python3"
	as_frappe "cd $BENCH_DIR && python3 ~/.vendor_git_deps.py apps/frappe/pyproject.toml && cd apps/frappe && git update-index --assume-unchanged pyproject.toml"
	retry as_frappe "cd $BENCH_DIR && uv pip install --quiet -e apps/frappe --python env/bin/python" \
		|| die "Frappe Python 依赖安装失败，请检查网络后重新执行脚本（已完成的步骤会自动跳过）"
fi

# 兜底 2：部分网络无法下载 GitHub tarball（frappe 依赖 air-datepicker），改用 git 克隆
if [ ! -d "$BENCH_DIR/apps/frappe/node_modules/air-datepicker" ]; then
	log "使用 git 方式补装前端依赖"
	as_frappe "cd ~ && [ -d vendor-air-datepicker ] || git clone --depth 1 https://github.com/frappe/air-datepicker vendor-air-datepicker"
	as_frappe "cd $BENCH_DIR/apps/frappe && sed -i 's#\"air-datepicker\": \"github:frappe/air-datepicker\"#\"air-datepicker\": \"file:/home/${FRAPPE_USER}/vendor-air-datepicker\"#' package.json && git update-index --assume-unchanged package.json yarn.lock && yarn install --check-files"
fi

# 补齐 bench init 中断时未完成的步骤（均可重复执行，已完成的自动跳过）
log "检查 bench 基础配置与前端资源"
as_frappe "cd $BENCH_DIR && (grep -qx frappe sites/apps.txt 2>/dev/null || echo frappe >> sites/apps.txt) \
	&& ([ -f config/redis_cache.conf ] || bench setup redis) \
	&& ([ -f Procfile ] || bench setup procfile) \
	&& ([ -f sites/assets/assets.json ] || bench build --app frappe)"

# ---------------------------------------------------------------- 6. 应用与站点
log "获取 swap_growth"
if [ ! -d "$BENCH_DIR/apps/swap_growth" ]; then
	retry as_frappe "cd $BENCH_DIR && rm -rf apps/swap_growth && bench get-app --skip-assets ${APP_REPO}" \
		|| die "拉取 swap_growth 失败，可设置 GITHUB_PROXY=https://ghfast.top 后重试"
else
	as_frappe "cd $BENCH_DIR/apps/swap_growth && git pull --ff-only || true"
fi
if ! as_frappe "cd $BENCH_DIR && env/bin/python -c 'import swap_growth'" >/dev/null 2>&1; then
	as_frappe "cd $BENCH_DIR && uv pip install --quiet -e apps/swap_growth --python env/bin/python"
fi
as_frappe "cd $BENCH_DIR && (grep -qx swap_growth sites/apps.txt || echo swap_growth >> sites/apps.txt)"

log "下载最新杭州区划地图（含临平区、钱塘区）"
GEO_DIR="$BENCH_DIR/apps/swap_growth/swap_growth/public/geo"
curl -fsSL -m 30 https://geo.datav.aliyun.com/areas_v3/bound/330100_full.json -o "$GEO_DIR/hangzhou.json" \
	&& chown ${FRAPPE_USER}: "$GEO_DIR/hangzhou.json" \
	|| echo "地图下载失败，大屏将尝试在线加载或使用离线旧版区划"

if [ ! -d "$BENCH_DIR/sites/$SITE" ]; then
	log "创建站点 $SITE 并安装应用（含演示数据）"
	as_frappe "cd $BENCH_DIR && bench new-site ${SITE} --admin-password '${ADMIN_PASSWORD}' --db-root-password '${DB_ROOT_PASSWORD}' --mariadb-user-host-login-scope=localhost --install-app swap_growth"
else
	as_frappe "cd $BENCH_DIR && bench --site ${SITE} install-app swap_growth || bench --site ${SITE} migrate"
fi
as_frappe "cd $BENCH_DIR && bench use ${SITE} && bench build --app swap_growth && bench --site ${SITE} enable-scheduler && bench --site ${SITE} clear-cache"

if [ -n "$LLM_API_KEY" ]; then
	log "配置数据分析大模型：${LLM_PROVIDER}"
	as_frappe "cd $BENCH_DIR && bench --site ${SITE} execute swap_growth.setup_tools.configure_llm --kwargs \"{'provider': '${LLM_PROVIDER}', 'api_key': '${LLM_API_KEY}'}\""
fi

# ---------------------------------------------------------------- 7. 生产模式
log "配置 nginx + supervisor"
if [ "$MEM_MB" -lt 3800 ]; then as_frappe "cd $BENCH_DIR && bench set-config -g gunicorn_workers 2"; fi
cd "$BENCH_DIR"
bench setup production "$FRAPPE_USER" --yes
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
supervisorctl reread && supervisorctl update && supervisorctl restart all || true

IP=$(curl -fsSL -m 5 https://ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')
cat <<EOF

=====================================================================
 部署完成
 访问地址：http://${IP}/  （若 SITE 为域名，请将域名解析到本机后访问 http://${SITE}/）
 管理员：Administrator / ${ADMIN_PASSWORD}
 演示账号（密码均为 Swap@2026）：
   director@example.com       运营总监（全市）
   xiaoshan.mgr@example.com   区域经理（萧山区、滨江区）
   qiantang.mgr@example.com   区域经理（钱塘区、临平区）
   operator@example.com       运营专员（录单）
 MariaDB root 密码：${DB_ROOT_PASSWORD}
 请在云服务器安全组中放行 80 端口。
=====================================================================
EOF
