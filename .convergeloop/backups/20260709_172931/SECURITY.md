# ProtoForge 安全指南

本文档描述 ProtoForge 的安全机制以及生产环境部署前的安全加固建议。

## 内置安全机制

### 1. 密码安全

- **bcrypt 哈希**：所有用户密码使用 bcrypt 算法存储，自动加盐，计算成本因子为 12
- **密码强度策略**：新密码必须满足：
  - 至少 8 位字符
  - 包含至少 1 个大写字母
  - 包含至少 1 个小写字母
  - 包含至少 1 个数字
- **禁止弱密码**：系统会拒绝常见弱密码（如 `123456`、`password`、`admin` 等）

### 2. JWT 认证

- **访问令牌**：有效期 30 分钟，包含用户 ID、角色和权限信息
- **刷新令牌**：有效期 7 天，用于在访问令牌过期后获取新的访问令牌
- **算法**：使用 HS256 对称签名算法
- **密钥管理**：
  - 优先从环境变量 `PROTOFORGE_JWT_SECRET` 读取
  - 未配置时自动生成 32 字节随机密钥
  - **注意**：自动生成密钥在每次重启后会变化，导致所有已登录用户需要重新登录

### 3. 登录保护

- **失败锁定**：连续 5 次登录失败后，账户自动锁定 5 分钟
- **锁定时长**：300 秒（5 分钟），期间任何登录尝试都会返回 "account_locked" 错误
- **计数器重置**：成功登录后，失败计数器清零

### 4. API 限流

- **普通接口**：100 次请求 / 分钟（按客户端 IP 统计）
- **认证接口**（登录、注册）：10 次请求 / 分钟（按客户端 IP 统计）
- **超限响应**：HTTP 429 Too Many Requests，响应头包含 `Retry-After` 提示等待秒数

### 5. 数据库安全

- **SQLite**：数据库文件权限自动设置为仅所有者可读写（Unix 系统）
- **PostgreSQL**：支持通过连接字符串配置 SSL/TLS 加密连接
- **SQL 注入防护**：所有数据库操作使用参数化查询，禁止字符串拼接 SQL

## 生产环境安全加固清单

在将 ProtoForge 部署到生产环境前，请完成以下检查：

### ✅ 必做项

- [ ] **修改默认密码**：删除或修改 `admin` / `admin` 默认账户
- [ ] **配置 JWT 密钥**：在 `.env` 中设置强随机字符串作为 `PROTOFORGE_JWT_SECRET`
  ```bash
  # 生成随机密钥（Linux/macOS）
  openssl rand -base64 32
  
  # 或 Python
  python -c "import secrets; print(secrets.token_urlsafe(32))"
  ```
- [ ] **使用 PostgreSQL**：生产环境请使用 PostgreSQL 替代 SQLite
  ```bash
  PROTOFORGE_DB_PATH=postgresql://user:password@localhost:5432/protoforge
  ```
- [ ] **启用 HTTPS**：通过 Nginx 或 Traefik 配置 TLS/SSL 证书
- [ ] **配置防火墙**：仅开放必要的端口（Web 端口、协议端口）

### ✅ 建议项

- [ ] **反向代理**：使用 Nginx 或 Caddy 作为反向代理，隐藏后端服务
- [ ] **日志审计**：定期检查 `logs/` 目录下的访问日志和错误日志
- [ ] **备份策略**：定期备份数据库文件或 PostgreSQL 数据
- [ ] **监控告警**：配置 Prometheus + Grafana 监控异常登录和请求
- [ ] **容器安全**：如使用 Docker，以非 root 用户运行容器

## 安全更新策略

- 关注 Python 依赖的安全更新，定期运行 `pip audit`（如已安装）
- 关注 FastAPI、Starlette、Pydantic 等核心依赖的安全公告
- 在升级前在测试环境验证兼容性

## 漏洞报告

如发现安全漏洞，请通过以下方式报告：

1. 不要公开披露漏洞细节
2. 发送邮件至项目维护者（替换为实际邮箱）
3. 提供复现步骤和影响范围
4. 等待修复后再公开讨论

## 安全相关配置参考

```bash
# .env 生产环境安全配置示例

# 必须设置强随机密钥
PROTOFORGE_JWT_SECRET=your-256-bit-secret-key-here-change-me

# 使用 PostgreSQL
PROTOFORGE_DB_PATH=postgresql://protoforge:strong_password@db:5432/protoforge

# 关闭演示模式
PROTOFORGE_DEMO_MODE=false

# 设置合适的日志级别
PROTOFORGE_LOG_LEVEL=warning
```

## 相关文档

- [README.md](README.md) — 项目概述和快速开始
- [DEPLOYMENT.md](DEPLOYMENT.md) — 详细部署指南
