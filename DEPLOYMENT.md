# ProtoForge 部署指南

本文档提供 ProtoForge 在不同环境下的详细部署步骤。

## 目录

- [系统要求](#系统要求)
- [单机部署](#单机部署)
- [Docker 部署](#docker-部署)
- [生产环境部署](#生产环境部署)
- [数据库迁移](#数据库迁移)
- [故障排查](#故障排查)

## 系统要求

### 最低配置

- CPU: 2 核
- 内存: 4 GB
- 磁盘: 10 GB 可用空间
- Python: 3.10 或更高版本

### 推荐配置

- CPU: 4 核+
- 内存: 8 GB+
- 磁盘: 50 GB+ SSD
- PostgreSQL 14+

## 单机部署

### 1. 安装 Python 依赖

```bash
# 克隆仓库
git clone https://github.com/suoten/ProtoForge.git
cd ProtoForge

# 创建虚拟环境（推荐）
python -m venv venv
source venv/bin/activate  # Linux/macOS
# 或 venv\Scripts\activate  # Windows

# 安装核心依赖
pip install -e ".[all]"

# 如需 PostgreSQL 支持
pip install -e ".[postgres]"
```

### 2. 构建前端

```bash
cd web
npm install
npm run build
cd ..
```

> 如果 `web/dist/` 已存在且未修改前端代码，可跳过此步骤。

### 3. 配置环境变量

```bash
# 复制示例配置文件
cp .env.example .env

# 编辑 .env 文件，至少修改以下项：
# - PROTOFORGE_JWT_SECRET（生产环境必须设置）
# - PROTOFORGE_DB_PATH（如需使用 PostgreSQL）
```

### 4. 初始化数据库

如果使用 SQLite（默认），系统会在首次启动时自动创建数据库。

如果使用 PostgreSQL：

```bash
# 1. 创建数据库和用户
sudo -u postgres psql -c "CREATE DATABASE protoforge;"
sudo -u postgres psql -c "CREATE USER protoforge WITH PASSWORD 'your_password';"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE protoforge TO protoforge;"

# 2. 运行数据库迁移
alembic upgrade head
```

### 5. 启动服务

```bash
# 生产模式启动（无演示数据）
protoforge run

# 或使用 Python 直接启动
python -m protoforge.main
```

服务启动后，访问 http://localhost:8000 。

## Docker 部署

### 使用 Docker Compose（推荐）

```bash
# 克隆仓库
git clone https://github.com/suoten/ProtoForge.git
cd ProtoForge

# 启动服务
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止服务
docker-compose down
```

### Docker 单机运行

```bash
# 构建镜像
docker build -t protoforge:latest .

# 运行容器
docker run -d \
  --name protoforge \
  -p 8000:8000 \
  -v $(pwd)/data:/app/data \
  -e PROTOFORGE_JWT_SECRET=$(openssl rand -base64 32) \
  protoforge:latest
```

## 生产环境部署

### 使用 Nginx 反向代理

```nginx
server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name your-domain.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    ssl_protocols TLSv1.2 TLSv1.3;

    # 前端静态文件
    location / {
        root /path/to/ProtoForge/web/dist;
        try_files $uri $uri/ /index.html;
        expires 1d;
    }

    # API 代理
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }

    # WebSocket 代理
    location /api/v1/ws/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400s;
    }
}
```

### 使用 systemd 管理（Linux）

创建 `/etc/systemd/system/protoforge.service`：

```ini
[Unit]
Description=ProtoForge IoT Protocol Simulator
After=network.target

[Service]
Type=simple
User=protoforge
Group=protoforge
WorkingDirectory=/opt/ProtoForge
Environment=PYTHONPATH=/opt/ProtoForge
EnvironmentFile=/opt/ProtoForge/.env
ExecStart=/opt/ProtoForge/venv/bin/python -m protoforge.main
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

启用并启动服务：

```bash
sudo systemctl daemon-reload
sudo systemctl enable protoforge
sudo systemctl start protoforge
sudo systemctl status protoforge
```

### 使用 Supervisor（可选）

创建 `/etc/supervisor/conf.d/protoforge.conf`：

```ini
[program:protoforge]
directory=/opt/ProtoForge
command=/opt/ProtoForge/venv/bin/python -m protoforge.main
autostart=true
autorestart=true
user=protoforge
environment=PYTHONPATH="/opt/ProtoForge"
stderr_logfile=/var/log/protoforge.err.log
stdout_logfile=/var/log/protoforge.out.log
```

## 数据库迁移

ProtoForge 使用 Alembic 管理数据库迁移。

### 首次迁移

```bash
# 自动生成迁移脚本（基于模型变更）
alembic revision --autogenerate -m "add new feature"

# 应用迁移
alembic upgrade head
```

### 常用命令

```bash
# 查看当前版本
alembic current

# 查看历史版本
alembic history

# 回滚到上一个版本
alembic downgrade -1

# 回滚到指定版本
alembic downgrade <revision_id>

# 升级到最新版本
alembic upgrade head
```

### 从 SQLite 迁移到 PostgreSQL

```bash
# 1. 导出 SQLite 数据
sqlite3 data/protoforge.db .dump > protoforge_backup.sql

# 2. 配置 PostgreSQL 连接
# 编辑 .env: PROTOFORGE_DB_PATH=postgresql://...

# 3. 创建表结构
alembic upgrade head

# 4. 导入数据（需要手动调整 SQL 语法差异）
# 建议使用 pgloader 或自定义脚本迁移
```

## 故障排查

### 服务无法启动

```bash
# 检查端口占用
lsof -i :8000

# 检查日志
tail -f logs/protoforge.log

# 验证配置
python -c "from protoforge.config import get_settings; print(get_settings().model_dump())"
```

### 数据库连接失败

- SQLite：检查 `data/` 目录是否有写入权限
- PostgreSQL：检查连接字符串、网络连通性、防火墙规则

### 协议端口冲突

```bash
# 查看端口占用
netstat -tlnp | grep 5020

# 修改 .env 中的端口配置后重启服务
```

### 性能问题

- 检查日志级别是否为 `debug`，生产环境建议设置为 `warning`
- 使用 PostgreSQL 替代 SQLite
- 增加连接池大小（PostgreSQL 模式下自动配置）
- 考虑使用多 worker 部署（配合 Gunicorn）

```bash
# 使用 Gunicorn 多 worker 部署
gunicorn protoforge.main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

## 相关文档

- [README.md](README.md) — 项目概述
- [SECURITY.md](SECURITY.md) — 安全加固指南
- [CONTRIBUTING.md](CONTRIBUTING.md) — 开发贡献指南
