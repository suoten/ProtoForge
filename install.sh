#!/usr/bin/env bash
set -e

# ProtoForge 一键安装脚本 (Linux / macOS)
# 物联网协议仿真与测试平台

trap 'echo ""; echo -e "\033[0;31m  [错误] 安装过程出现意外错误，脚本已终止。\033[0m"; echo "  请检查上方的错误信息，或尝试手动安装。"; echo ""; echo -n "按 Enter 键退出..."; read _' ERR

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

echo ""
echo -e "${BLUE}  ╔══════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}  ║        ProtoForge 一键安装脚本 (Linux/macOS)     ║${NC}"
echo -e "${BLUE}  ║         物联网协议仿真与测试平台                    ║${NC}"
echo -e "${BLUE}  ╚══════════════════════════════════════════════════╝${NC}"
echo ""

# Step 1: 检查 Python
echo -e "${YELLOW}[1/5] 检查 Python ...${NC}"
PYTHON_CMD=""
for cmd in python3 python; do
    if command -v "$cmd" &> /dev/null; then
        PYTHON_CMD="$cmd"
        break
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    echo ""
    echo -e "${RED}  [错误] 没有找到 Python，请先安装 Python 3.10+${NC}"
    echo "  下载地址：https://www.python.org/downloads/"
    echo ""
    exit 1
fi

PYVER=$($PYTHON_CMD --version 2>&1 | awk '{print $2}')
echo "        已找到 Python $PYVER"

$PYTHON_CMD -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" 2>/dev/null
if [ $? -ne 0 ]; then
    echo ""
    echo -e "${RED}  [错误] Python 版本太低，需要 3.10 或更高${NC}"
    echo "  当前版本：$PYVER"
    echo "  Ubuntu/Debian: sudo apt install python3.12 python3.12-venv"
    echo "  CentOS/Rocky: sudo dnf install python3.12"
    echo "  macOS: brew install python@3.12"
    echo ""
    exit 1
fi

# Step 2: 创建虚拟环境
echo ""
echo -e "${YELLOW}[2/5] 创建 Python 虚拟环境 ...${NC}"
if [ -d "venv" ]; then
    echo "        虚拟环境已存在，跳过创建"
else
    $PYTHON_CMD -m venv venv
    if [ $? -ne 0 ]; then
        echo ""
        echo -e "${RED}  [错误] 创建虚拟环境失败${NC}"
        echo "  Ubuntu/Debian: sudo apt install python3-venv"
        echo ""
        exit 1
    fi
    echo "        虚拟环境创建成功"
fi

# Step 3: 激活并安装 Python 依赖
echo ""
echo -e "${YELLOW}[3/5] 安装 Python 依赖（可能需要几分钟）...${NC}"
source venv/bin/activate 2>/dev/null || true

venv/bin/python -m pip install --quiet --upgrade pip 2>/dev/null

venv/bin/pip install -e ".[all]" 2>/dev/null || {
    echo ""
    echo -e "${YELLOW}  [警告] 全部协议安装失败，尝试安装核心依赖...${NC}"
    venv/bin/pip install -e .
    if [ $? -ne 0 ]; then
        echo ""
        echo -e "${RED}  [错误] Python 依赖安装失败${NC}"
        echo "  请检查网络连接，或尝试设置国内镜像："
        echo "  pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/"
        echo ""
        exit 1
    fi
}

# Step 4: 检查 Node.js 并构建前端
echo ""
echo -e "${YELLOW}[4/5] 构建前端页面 ...${NC}"

if command -v node &> /dev/null; then
    NODEVER=$(node --version 2>&1)
    echo "        已找到 Node.js $NODEVER"

    if [ -d "web" ]; then
        cd web
        echo "        安装前端依赖..."
        npm install --quiet 2>/dev/null || {
            echo ""
            echo -e "${YELLOW}  [警告] npm install 失败，将使用仓库中已有的前端文件${NC}"
            echo "  网络慢可设置国内镜像："
            echo "  npm config set registry https://registry.npmmirror.com"
            echo ""
        }

        npm run build 2>/dev/null && {
            echo "        前端构建成功"
        } || {
            echo ""
            echo -e "${YELLOW}  [警告] 前端构建失败，将使用仓库中已有的前端文件${NC}"
            echo ""
        }
        cd ..
    fi
else
    echo ""
    echo -e "${YELLOW}  [提示] 没有找到 Node.js，将使用仓库中预构建的前端${NC}"
    echo "  如需修改前端代码，请安装 Node.js 18+："
    echo "  https://nodejs.org/"
    echo ""
fi

# 确保 data 目录存在
mkdir -p data

# Step 5: 完成
echo ""
echo -e "${YELLOW}[5/5] 初始化配置 ...${NC}"
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo "        配置文件已从 .env.example 复制到 .env"
    else
        echo "        未找到 .env.example，将使用默认配置"
    fi
else
    echo "        配置文件 .env 已存在，跳过"
fi

echo ""
echo -e "${YELLOW}[5/5] 安装完成！${NC}"
echo ""
echo -e "${GREEN}  ╔══════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}  ║                                                  ║${NC}"
echo -e "${GREEN}  ║   安装成功！现在可以启动 ProtoForge 了：           ║${NC}"
echo -e "${GREEN}  ║                                                  ║${NC}"
echo -e "${GREEN}  ║   方式一：演示模式（推荐新手）                      ║${NC}"
echo -e "${GREEN}  ║     source venv/bin/activate                     ║${NC}"
echo -e "${GREEN}  ║     protoforge demo                              ║${NC}"
echo -e "${GREEN}  ║     浏览器打开 http://localhost:8000               ║${NC}"
echo -e "${GREEN}  ║     登录：admin / admin                           ║${NC}"
echo -e "${GREEN}  ║                                                  ║${NC}"
echo -e "${GREEN}  ║   方式二：普通模式                                 ║${NC}"
echo -e "${GREEN}  ║     source venv/bin/activate                     ║${NC}"
echo -e "${GREEN}  ║     protoforge run                               ║${NC}"
echo -e "${GREEN}  ║     浏览器打开 http://localhost:8000               ║${NC}"
echo -e "${GREEN}  ║     登录：admin / admin                           ║${NC}"
echo -e "${GREEN}  ║                                                  ║${NC}"
echo -e "${GREEN}  ╚══════════════════════════════════════════════════╝${NC}"
echo ""
echo -n "按 Enter 键退出..."
read _