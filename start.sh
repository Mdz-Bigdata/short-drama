#!/bin/bash

# ==================================================================================
# AI 短剧 8-Agent 工业化成片系统一键启动脚本
# ==================================================================================

# 主工作目录取脚本自身所在位置：项目放在任何路径、任何机器上都能直接启动
WORKSPACE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
BACKEND_DIR="$WORKSPACE_DIR/backend"
FRONTEND_DIR="$WORKSPACE_DIR/frontend"

# 炫酷的终端彩色配置
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # 无颜色

# 子服务日志同时打印到当前终端并写入日志文件；前缀便于并发输出时快速定位来源。
stream_log() {
    local prefix="$1"
    local log_file="$2"
    while IFS= read -r line; do
        printf '%s %s\n' "$prefix" "$line"
    done | tee -a "$log_file"
}

# 读取 .env 里的单个配置项 (去掉行尾注释与引号)；文件或配置项不存在时输出为空。
env_file_value() {
    local key="$1"
    local file="$2"
    [ -f "$file" ] || return 0
    sed -n "s/^[[:space:]]*$key[[:space:]]*=[[:space:]]*//p" "$file" | tail -n 1 \
        | sed -e 's/[[:space:]]#.*$//' -e 's/[[:space:]]*$//' -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'$/\1/"
}

# 前端的 .env 系列文件是否已经配置了某一项
frontend_env_defines() {
    grep -qsE "^[[:space:]]*$1=" \
        "$FRONTEND_DIR/.env" "$FRONTEND_DIR/.env.local" \
        "$FRONTEND_DIR/.env.development" "$FRONTEND_DIR/.env.development.local"
}

# 端口优先级：当前 shell 环境变量 > backend/.env > 默认值。前后端共用同一份端口配置，
# 后端据此推导默认的跨域白名单与媒体访问地址，前端据此连接后端。
BACKEND_PORT="${BACKEND_PORT:-$(env_file_value BACKEND_PORT "$BACKEND_DIR/.env")}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-$(env_file_value FRONTEND_PORT "$BACKEND_DIR/.env")}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
export BACKEND_PORT FRONTEND_PORT

BACKEND_URL="http://localhost:$BACKEND_PORT"
FRONTEND_URL="http://localhost:$FRONTEND_PORT"

# 前端默认连接本次启动的后端；若已在环境变量或前端 .env 文件里显式配置则保持不动。
if [ -z "${VITE_API_BASE_URL+x}" ] && ! frontend_env_defines VITE_API_BASE_URL; then
    export VITE_API_BASE_URL="$BACKEND_URL"
fi

# 当前监听指定端口的进程号
port_listeners() {
    lsof -nP -t -iTCP:"$1" -sTCP:LISTEN 2>/dev/null
}

# 只回收本项目自己留下的进程：按端口找到监听者，再核对它的工作目录。
# 端口被别的程序占用时不去动它，直接报错，避免误杀其他项目的 Python / Vite 服务。
release_port() {
    local port="$1"
    local owner_dir
    local port_variable="$3"
    local pid cwd
    # lsof 报告的是物理路径，这里同样解析掉符号链接再比较
    owner_dir="$(cd "$2" 2>/dev/null && pwd -P)"
    for pid in $(port_listeners "$port"); do
        cwd=$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p')
        if [ "$cwd" = "$owner_dir" ]; then
            kill "$pid" 2>/dev/null
        else
            echo -e "${RED}✘ 端口 $port 已被其他程序占用 (PID: $pid)。请先关闭它，或用 $port_variable 换一个端口后重试。${NC}"
            return 1
        fi
    done
    # 等旧进程真正让出端口，避免新服务启动时撞上「地址已被占用」
    local attempt
    for attempt in $(seq 1 40); do
        [ -z "$(port_listeners "$port")" ] && return 0
        sleep 0.25
    done
    echo -e "${RED}✘ 端口 $port 上的旧进程未能退出，请手动处理后重试。${NC}"
    return 1
}

# 轮询等待服务就绪；服务进程中途退出则立即判定失败，不必等满超时。
wait_for_http() {
    local url="$1"
    local pid="$2"
    local deadline=$(( $(date +%s) + $3 ))
    while [ "$(date +%s)" -lt "$deadline" ]; do
        LAST_HTTP_CODE=$(curl -s -o /dev/null -m 2 --noproxy '*' -w "%{http_code}" "$url")
        [ "$LAST_HTTP_CODE" = "200" ] && return 0
        kill -0 "$pid" 2>/dev/null || return 1
        sleep 0.5
    done
    return 1
}

echo -e "${CYAN}==================================================================${NC}"
echo -e "${CYAN}        AI SHORT DRAMA 8-AGENT FACTORY - 一键启动管理引擎          ${NC}"
echo -e "${CYAN}==================================================================${NC}"

# 清理过往未退出的残留进程
echo -e "${YELLOW}[1/4] 清除可能冲突的历史后台进程...${NC}"
release_port "$BACKEND_PORT" "$BACKEND_DIR" "BACKEND_PORT" || exit 1
release_port "$FRONTEND_PORT" "$FRONTEND_DIR" "FRONTEND_PORT" || exit 1

# 启动后端服务
echo -e "${YELLOW}[2/4] 启动 FastAPI 后端服务...${NC}"
if [ -d "$BACKEND_DIR/.venv" ]; then
    cd "$BACKEND_DIR"
    source .venv/bin/activate
    # Python 使用无缓冲模式，任务阶段、模型调用和异常日志会实时双写终端与 backend.log。
    : > "$WORKSPACE_DIR/backend.log"
    python -u main.py > >(stream_log "[BACKEND]" "$WORKSPACE_DIR/backend.log") 2>&1 &
    BACKEND_PID=$!
    echo -e "${GREEN}✔ 后端服务已在后台启动 (PID: $BACKEND_PID)。日志位置: backend.log${NC}"
else
    echo -e "${RED}✘ 找不到后端虚拟环境 .venv，请确认依赖已正确安装。${NC}"
    exit 1
fi

# 启动前端服务
echo -e "${YELLOW}[3/4] 启动 Vite 前端服务...${NC}"
if [ -d "$FRONTEND_DIR/node_modules" ]; then
    cd "$FRONTEND_DIR"
    # Vite 日志同样实时双写，并使用独立前缀避免与后端输出混淆。
    # --strictPort：端口被占时直接报错，而不是悄悄换端口导致后端跨域校验拒绝所有写请求。
    : > "$WORKSPACE_DIR/frontend.log"
    npm run dev -- --port "$FRONTEND_PORT" --strictPort > >(stream_log "[FRONTEND]" "$WORKSPACE_DIR/frontend.log") 2>&1 &
    FRONTEND_PID=$!
    echo -e "${GREEN}✔ 前端服务已在后台启动 (PID: $FRONTEND_PID)。日志位置: frontend.log${NC}"
else
    echo -e "${RED}✘ 找不到前端 node_modules，请确认依赖已正确安装。${NC}"
    # 杀掉刚刚启动的后端进程
    kill $BACKEND_PID 2>/dev/null
    exit 1
fi

# 等待端口就绪并做健康检查
echo -e "${YELLOW}[4/4] 正在执行服务联调与就绪度校验...${NC}"

# 探测后端接口状态 (启动含数据库初始化与模型配置装载，轮询等待而不是固定睡眠)
if wait_for_http "$BACKEND_URL/" "$BACKEND_PID" 60; then
    if wait_for_http "$FRONTEND_URL/" "$FRONTEND_PID" 30; then
        echo -e "${GREEN}✔ 前后端联调成功！系统处于完美在线状态。${NC}"
    else
        echo -e "${RED}⚠ 前端就绪校验异常 (HTTP CODE: $LAST_HTTP_CODE)，请查看 frontend.log 日志核实。${NC}"
    fi
else
    echo -e "${RED}⚠ 后端就绪校验异常 (HTTP CODE: $LAST_HTTP_CODE)，请查看 backend.log 日志核实。${NC}"
fi

# 提示访问地址
echo -e "${CYAN}==================================================================${NC}"
echo -e "${GREEN}   🚀 前端控制台访问地址: $FRONTEND_URL/${NC}"
echo -e "${GREEN}   📡 后端接口访问地址:   $BACKEND_URL/docs (Swagger)${NC}"
echo -e "${CYAN}==================================================================${NC}"
echo -e "${YELLOW}提示: 脚本将在后台维持服务。按下 [Enter] 键或 [Ctrl+C] 将自动优雅关闭所有关联服务。${NC}"

# 捕获退出信号，优雅清理子进程
cleanup() {
    echo -e "\n${RED}停止所有服务...${NC}"
    kill $BACKEND_PID 2>/dev/null
    kill $FRONTEND_PID 2>/dev/null
    # 热重载子进程与 npm 拉起的 node 进程不一定随父进程退出，按端口再收一次
    release_port "$BACKEND_PORT" "$BACKEND_DIR" "BACKEND_PORT" >/dev/null 2>&1
    release_port "$FRONTEND_PORT" "$FRONTEND_DIR" "FRONTEND_PORT" >/dev/null 2>&1
    echo -e "${GREEN}✔ FastAPI 服务与 Vite 前端服务已全部优雅退出。感谢使用！${NC}"
    exit 0
}

trap cleanup SIGINT SIGTERM

# 阻塞等待用户按回车键退出；没有终端时 (被其他工具拉起) 改为等待服务进程本身结束
if [ -t 0 ]; then
    read -r -p ""
else
    wait $BACKEND_PID $FRONTEND_PID
fi
cleanup
