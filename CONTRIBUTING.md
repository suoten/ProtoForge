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

### 代码规范

- **Python**: 遵循 PEP 8，使用 type hints
- **Vue**: 遵循 Vue 3 Composition API 风格
- **提交信息**: 使用清晰简洁的中文或英文描述

### 开发环境

```bash
# 后端
pip install -e ".[dev]"
python -m pytest tests/ -v

# 前端
cd web
npm install
npm run build
```

### 项目结构

```
protoforge/
├── api/v1/          # REST API 端点
├── core/            # 核心业务逻辑
│   ├── engine.py    # 仿真引擎
│   ├── device.py    # 设备实例
│   ├── scenario.py  # 场景规则引擎
│   ├── testing.py   # 测试框架
│   ├── forward.py   # 数据转发
│   ├── recorder.py  # 协议录制
│   └── ...
├── models/          # Pydantic 数据模型
├── protocols/       # 协议服务端实现
├── db/              # 数据库层
├── sdk/             # Python SDK
└── templates/       # 设备模板
```

## 许可证

提交代码即表示你同意在 MIT 许可证下发布你的贡献。
