#!/usr/bin/env bash
set -e

# ============================================
# ProtoForge 一键启动 (Linux / macOS)
# 用法: chmod +x quickstart.sh && ./quickstart.sh
# ============================================

cd "$(dirname "$0")"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

echo ""
echo -e "${BLUE}  ╔══════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}  ║       ProtoForge 一键启动 (Linux/macOS)          ║${NC}"
echo -e "${BLUE}  ║       物联网协议仿真与测试平台                     ║${NC}"
echo -e "${BLUE}  ╚══════════════════════════════════════════════════╝${NC}"
echo ""

# Step 1: 检查 Python
echo -e "${YELLOW}[1/4] 检查 Python ...${NC}"
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
    echo "  Ubuntu/Debian: sudo apt install python3 python3-venv"
    echo "  CentOS/Rocky:  sudo dnf install python3"
    echo "  macOS:         brew install python@3.12"
    echo ""
    exit 1
fi

PYVER=$($PYTHON_CMD --version 2>&1 | awk '{print $2}')
echo "       已找到 Python $PYVER"

$PYTHON_CMD -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" 2>/dev/null
if [ $? -ne 0 ]; then
    echo ""
    echo -e "${RED}  [错误] Python 版本太低，需要 3.10 或更高${NC}"
    echo "  当前版本: $PYVER"
    echo ""
    exit 1
fi
echo ""

# Step 2: 创建/检查虚拟环境
echo -e "${YELLOW}[2/4] 检查 Python 虚拟环境 ...${NC}"
if [ -f "venv/bin/python" ]; then
    echo "       虚拟环境已存在，跳过创建"
else
    echo "       创建虚拟环境 ..."
    $PYTHON_CMD -m venv venv
    if [ $? -ne 0 ]; then
        echo ""
        echo -e "${RED}  [错误] 创建虚拟环境失败${NC}"
        echo "  Ubuntu/Debian: sudo apt install python3-venv"
        echo ""
        exit 1
    fi
    echo "       虚拟环境创建成功"
fi
echo ""

# Step 3: 检查依赖是否已安装
echo -e "${YELLOW}[3/4] 检查 Python 依赖 ...${NC}"
if venv/bin/python -c "import protoforge" &>/dev/null; then
    echo "       依赖已安装，跳过"
else
    echo "       首次运行，正在安装依赖（可能需要几分钟）..."
    venv/bin/python -m pip install --quiet --upgrade pip
    if ! venv/bin/pip install -e ".[all]" &>/dev/null; then
        echo -e "${YELLOW}       全部协议安装失败，尝试安装核心依赖...${NC}"
        venv/bin/pip install -e .
        if [ $? -ne 0 ]; then
            echo ""
            echo -e "${RED}  [错误] 依赖安装失败${NC}"
            echo "  请检查网络连接，或尝试设置国内镜像："
            echo "  pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/"
            echo ""
            exit 1
        fi
    fi
    echo "       依赖安装成功"
fi
echo ""

# Step 4: 确保 .env 配置正确（关键：生成稳定的 JWT_SECRET）
echo -e "${YELLOW}[4/4] 检查配置文件 ...${NC}"

generate_jwt_secret() {
    venv/bin/python -c "import secrets; print(secrets.token_urlsafe(32))"
}

if [ ! -f ".env" ]; then
    echo "       首次运行，生成配置文件 ..."
    JWT_SECRET=$(generate_jwt_secret)
    cat > ".env" << EOF
# ProtoForge 配置文件（由 quickstart.sh 自动生成）
PROTOFORGE_HOST=0.0.0.0
PROTOFORGE_PORT=8000
PROTOFORGE_DB_PATH=data/protoforge.db
PROTOFORGE_JWT_SECRET=${JWT_SECRET}
PROTOFORGE_ADMIN_PASSWORD=admin
PROTOFORGE_DEMO_MODE=true
PROTOFORGE_LOG_LEVEL=info
PROTOFORGE_CORS_ORIGINS=http://localhost:8000,http://127.0.0.1:8000
EOF
    echo "       配置文件已生成"
else
    # 检查 JWT_SECRET 是否为空，为空则补填
    if grep -q "^PROTOFORGE_JWT_SECRET=$" .env 2>/dev/null; then
        echo "       检测到 JWT_SECRET 为空，正在修复 ..."
        JWT_SECRET=$(generate_jwt_secret)
        if [[ "$(uname)" == "Darwin" ]]; then
            # macOS sed 需要额外参数
            sed -i '' "s/^PROTOFORGE_JWT_SECRET=$/PROTOFORGE_JWT_SECRET=${JWT_SECRET}/" .env
        else
            sed -i "s/^PROTOFORGE_JWT_SECRET=$/PROTOFORGE_JWT_SECRET=${JWT_SECRET}/" .env
        fi
        echo "       JWT_SECRET 已修复"
    else
        echo "       配置文件正常"
    fi
fi
echo ""

# 确保 data 目录存在
mkdir -p data

# 显示启动信息
echo "════════════════════════════════════════════════════"
echo ""
echo -e "${GREEN}  ProtoForge 正在启动...${NC}"
echo ""
echo "  浏览器打开: http://localhost:8000"
echo "  登录账号:   admin"
echo "  登录密码:   admin"
echo ""
echo "  按 Ctrl+C 可停止服务"
echo ""
echo "════════════════════════════════════════════════════"
echo ""

# 启动服务（演示模式）
exec venv/bin/python -m protoforge.cli demo
