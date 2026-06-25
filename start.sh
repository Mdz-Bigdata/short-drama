#!/bin/bash

# ==================================================================================
# AI 短剧 8-Agent 工业化成片系统一键启动脚本
# ==================================================================================

# 设置主工作目录
WORKSPACE_DIR="/Users/mindezhi/short-drama"
BACKEND_DIR="$WORKSPACE_DIR/backend"
FRONTEND_DIR="$WORKSPACE_DIR/frontend"

# 炫酷的终端彩色配置
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # 无颜色

echo -e "${CYAN}==================================================================${NC}"
echo -e "${CYAN}        AI SHORT DRAMA 8-AGENT FACTORY - 一键启动管理引擎          ${NC}"
echo -e "${CYAN}==================================================================${NC}"

# 清理过往未退出的残留进程
echo -e "${YELLOW}[1/4] 清除可能冲突的历史后台进程...${NC}"
pkill -f "main.py" 2>/dev/null
pkill -f "vite" 2>/dev/null

# 启动后端服务
echo -e "${YELLOW}[2/4] 启动 FastAPI 后端服务...${NC}"
if [ -d "$BACKEND_DIR/.venv" ]; then
    cd "$BACKEND_DIR"
    source .venv/bin/activate
    # 后端服务挂载在后台，并将日志写出到 backend.log
    python main.py > "$WORKSPACE_DIR/backend.log" 2>&1 &
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
    # 前端服务挂载在后台，并将日志写出到 frontend.log
    npm run dev > "$WORKSPACE_DIR/frontend.log" 2>&1 &
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
sleep 2

# 探测后端接口状态
CURL_RES=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/)
if [ "$CURL_RES" == "200" ]; then
    echo -e "${GREEN}✔ 前后端联调成功！系统处于完美在线状态。${NC}"
else
    echo -e "${RED}⚠ 后端就绪校验异常 (HTTP CODE: $CURL_RES)，请查看 backend.log 日志核实。${NC}"
fi

# 提示访问地址
echo -e "${CYAN}==================================================================${NC}"
echo -e "${GREEN}   🚀 前端控制台访问地址: http://localhost:5173/${NC}"
echo -e "${GREEN}   📡 后端接口访问地址:   http://localhost:8000/docs (Swagger)${NC}"
echo -e "${CYAN}==================================================================${NC}"
echo -e "${YELLOW}提示: 脚本将在后台维持服务。按下 [Enter] 键或 [Ctrl+C] 将自动优雅关闭所有关联服务。${NC}"

# 捕获退出信号，优雅清理子进程
cleanup() {
    echo -e "\n${RED}停止所有服务...${NC}"
    kill $BACKEND_PID 2>/dev/null
    kill $FRONTEND_PID 2>/dev/null
    echo -e "${GREEN}✔ FastAPI 服务与 Vite 前端服务已全部优雅退出。感谢使用！${NC}"
    exit 0
}

trap cleanup SIGINT SIGTERM

# 阻塞等待用户按回车键退出
read -p ""
cleanup
