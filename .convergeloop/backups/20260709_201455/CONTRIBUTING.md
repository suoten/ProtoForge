# 贡献指南 | Contributing Guide

感谢你对 ProtoForge 的关注！欢迎通过以下方式参与贡献。

## 如何贡献

### 报告 Bug

1. 在 [GitHub Issues](../../issues) 或 [Gitee Issues](../../issues) 中搜索是否已有相同问题
2. 如果没有，创建新 Issue，包含：
   - 问题描述
   - 复现步骤
   - 期望行为 vs 实际行为
   - 运行环境（Python 版本、操作系统等）

### 提交代码

1. Fork 本仓库
2. 创建功能分支：`git checkout -b feature/your-feature`
3. 提交更改：`git commit -m 'Add some feature'`
4. 推送分支：`git push origin feature/your-feature`
5. 提交 Pull Request

## 代码规范

### Python

- **类型注解**：所有函数必须添加类型注解，使用 `mypy` 检查
- **代码风格**：使用 `ruff` 进行代码格式化和检查
- **文档字符串**：公共函数和类必须包含 docstring
- **异常处理**：禁止裸 `except:`，必须捕获具体异常类型
- **日志记录**：使用 `logging` 模块，禁止 `print()` 输出调试信息

```bash
# 运行代码检查
ruff check protoforge/

# 运行类型检查
mypy protoforge/

# 自动修复格式问题
ruff check --fix protoforge/
```

### Vue / 前端

- 遵循 Vue 3 Composition API 风格
- 使用 TypeScript（推荐）
- 组件命名使用 PascalCase

### 提交信息规范

使用清晰简洁的中文或英文描述，建议格式：

```
<type>: <subject>

<body>
```

类型说明：

- `feat`: 新功能
- `fix`: 修复 Bug
- `docs`: 文档更新
- `style`: 代码格式调整（不影响功能）
- `refactor`: 重构
- `test`: 测试相关
- `chore`: 构建/工具链相关

## 开发环境

### 安装开发依赖

```bash
# 克隆仓库
git clone https://github.com/suoten/ProtoForge.git
cd ProtoForge

# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/macOS
# 或 venv\Scripts\activate  # Windows

# 安装开发依赖（包含测试、类型检查、代码格式化工具）
pip install -e ".[dev]"

# 如需 PostgreSQL 支持
pip install -e ".[postgres]"
```

### 运行测试

```bash
# 运行全部单元测试
python -m pytest tests/ -v

# 运行测试并生成覆盖率报告
python -m pytest tests/ -v --cov=protoforge --cov-report=html

# 运行特定测试文件
python -m pytest tests/test_api.py -v
```

> 提交代码前，确保所有测试通过且覆盖率不降低。

### 数据库迁移

如果修改了数据模型，需要生成迁移脚本：

```bash
# 自动生成迁移
alembic revision --autogenerate -m "describe your change"

# 验证迁移可正常升级/降级
alembic upgrade head
alembic downgrade -1
alembic upgrade head
```

### 前端开发

```bash
cd web
npm install
npm run dev     # 开发服务器
npm run build   # 生产构建
npm run lint    # 代码检查
```

## 项目结构

```
protoforge/
├── api/v1/               # REST API 端点
│   ├── common.py         # 统一响应格式和异常处理
│   └── rate_limit.py     # API 限流中间件
├── core/                 # 核心业务逻辑
│   ├── engine.py         # 仿真引擎
│   ├── auth.py           # JWT 认证与密码哈希
│   ├── device.py         # 设备实例
│   ├── scenario.py       # 场景规则引擎
│   ├── testing.py        # 测试框架
│   ├── forward.py        # 数据转发
│   ├── recorder.py       # 协议录制
│   └── ...
├── models/               # Pydantic 数据模型
├── protocols/            # 协议服务端实现
├── db/                   # 数据库层（SQLite + PostgreSQL）
├── sdk/                  # Python SDK
└── templates/            # 设备模板
```

## 安全规范

- **禁止提交密钥**：任何密钥、密码、Token 不得提交到代码仓库
- **依赖安全**：新增依赖需经过安全评估，优先选择维护活跃、社区认可的库
- **输入校验**：所有外部输入必须进行校验和消毒

## Pull Request 检查清单

提交 PR 前，请确认：

- [ ] 代码通过 `ruff` 检查
- [ ] 类型检查通过 `mypy`
- [ ] 所有测试通过 `pytest`
- [ ] 新增功能包含测试用例
- [ ] 文档已更新（README、API 文档等）
- [ ] 提交信息符合规范

## 许可证

提交代码即表示你同意在 MIT 许可证下发布你的贡献。
