# PyPI 发布启用指南（一次性配置）

> v1.12.0 起 PyPI 分发名为 **`protoforge-sim`**（`protoforge` 被无关项目占用）。
> CI 已内置发布 job：**配置好下面的 secret 后，每次推送 `v*` 标签自动发布到 PyPI**；
> 未配置时该 job 自动降级为"仅构建验证"（绿色），不影响发版。

## 第 1 步：注册 PyPI 账号并创建 API Token

1. 打开 https://pypi.org/account/register/ 注册账号（邮箱建议用项目邮箱）
2. 登录后进入 **Account Settings → API tokens → Add API token**
3. Token name：`protoforge-github-actions`
4. **Scope：第一次发布请选 `Entire account (all projects)`**
   ——项目级（project-scoped）token 需要项目已存在才能创建，
   `protoforge-sim` 首次发布由这个 token 完成创建；发布成功后可换窄 scope
5. 复制生成的 token（`pypi-` 开头，只显示一次）

## 第 2 步：配置 GitHub Secret

1. 打开 https://github.com/suoten/ProtoForge/settings/secrets/actions
2. **New repository secret**：
   - Name：`PYPI_API_TOKEN`
   - Secret：粘贴第 1 步的 token

## 第 3 步：触发首次发布（两种方式任选）

**方式 A（推荐，不占用新版本号）**：重新运行已有 tag 的发布 job

1. 打开 https://github.com/suoten/ProtoForge/actions → 选 **Docker Build and Push**
2. 找到 tag `v1.13.2`（或最新 tag）的运行记录 → **Re-run all jobs**
3. `pypi-publish` job 这次会真正上传，PyPI 出现 `protoforge-sim` 项目

**方式 B**：等下一个版本 tag（如 v1.14.0）推送时自动发布

## 第 4 步：验证

```bash
pip install protoforge-sim           # 能装了
protoforge version                   # ProtoForge v1.13.x
```

发布成功后（可选）：到 PyPI 项目页 → Settings → Publishing 加
**Trusted Publisher**（GitHub OIDC），之后可去掉 token 改用无凭据发布。

## 常见问题

- **403 "Invalid or non-existent authentication"**：token 复制不完整或已过期
- **400 "File already exists"**：该版本号已发布过——PyPI 不允许同版本重传，
  bump 版本号再发
- 想换窄 scope token：项目创建后新建 `project: protoforge-sim` 的 token
  替换 secret 即可
