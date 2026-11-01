# 飞牛 OS（fnOS）Docker 部署指南

> 适用：飞牛私有云 fnOS 及其他带 Docker 图形界面的 NAS（群晖/威联通/Unraid
> 思路相同）。**不需要上传代码文件夹**——直接使用 DockerHub 上的预构建镜像
> `suoten/protoforge`（支持 amd64 / arm64，x86 与 ARM 架构 NAS 均可）。

## 方式一：飞牛 Docker 图形界面（推荐，全程鼠标操作）

### 第 1 步：拉取镜像

1. 打开飞牛 OS 的 **Docker → 镜像（仓库）**，搜索或直接下载：
   ```
   suoten/protoforge:latest
   ```
2. 等待拉取完成（镜像约 300~500MB，含全部协议依赖）。

### 第 2 步：创建容器

点"创建容器"，按下表配置（对应 `docker run` 的参数）：

| 配置项 | 值 | 说明 |
|---|---|---|
| 镜像 | suoten/protoforge:latest | |
| 端口映射 | `8000 → 8000` (TCP) | Web 管理界面，**必填** |
| 端口映射（可选） | `5020→5020` `4840→4840` `1883→1883` `102→102` `8080→8080` 等 | 要从 NAS 外部访问仿真协议时才映射（完整端口表见仓库 `docker-compose.simple.yml` 注释） |
| 环境变量 | `PROTOFORGE_ADMIN_PASSWORD=你的密码` | **务必改掉默认密码** |
| 环境变量 | `PROTOFORGE_DEMO_MODE=1` | 预置演示设备（可选） |
| 挂载目录（卷） | NAS 共享文件夹（如 `docker/protoforge`）→ `/app/data` | **必填**——数据库/配置/基线/基准结果都在 `/app/data`，不挂载则容器重建数据丢失 |
| 重启策略 | 容器自启动（unless-stopped） | NAS 重启后自动拉起 |

### 第 3 步：访问

浏览器打开：

```
http://<NAS的IP>:8000
```

用 `admin` / 你设置的密码登录。Web 界面由后端直接托管，**不需要**额外装
Nginx 或前端服务。

## 方式二：SSH 终端一条命令

适合喜欢命令行的用户，SSH 登录飞牛后执行：

```bash
docker run -d --name protoforge \
  -p 8000:8000 \
  -e PROTOFORGE_ADMIN_PASSWORD=你的密码 \
  -v /vol1/docker/protoforge-data:/app/data \
  --restart unless-stopped \
  suoten/protoforge:latest
```

> `-v` 前半段换成你 NAS 上真实存在的目录路径（飞牛默认存储池一般是
> `/vol1/...`），目录不存在会自动创建。

## 方式三：docker compose（进阶，推荐要映射协议端口的用户）

1. 在 NAS 上建目录，如 `/vol1/docker/protoforge`；
2. 把仓库里的 [`docker-compose.simple.yml`](../docker-compose.simple.yml)
   内容保存为该目录下的 `docker-compose.yml`（也可在电脑上下载后通过飞牛
   文件管理上传）——该文件已默认映射全部常用协议端口；
3. SSH 到该目录执行：

```bash
cd /vol1/docker/protoforge
docker compose up -d
```

> 修改密码：编辑 `docker-compose.yml` 里 `PROTOFORGE_ADMIN_PASSWORD`
> 后 `docker compose up -d` 重建生效。
>
> YAML 对缩进极其敏感：增删端口映射时列表项 `- ` 必须与其他行保持完全
> 相同的空格缩进（不要用 Tab）。

## 升级

```bash
docker pull suoten/protoforge:latest
docker rm -f protoforge
# 再用与最初相同的 docker run / docker compose up -d 命令启动
# 数据在挂载卷里，升级不丢
```

## 常见问题

**Q：需要把 GitHub 的代码文件夹传到 NAS 吗？**
不需要。镜像已包含全部代码与依赖。只有方式三会用到仓库里的一个
`docker-compose.yml` 文件（一个文件，不是整个代码库）。

**Q：为什么我的 NAS 是 ARM 芯片也能用？**
镜像多架构发布（linux/amd64 + linux/arm64），`docker pull` 自动匹配。

**Q：Modbus/S7 等协议连不上？**
Web 端口 8000 之外，仿真协议端口也要映射（方式一第 2 步的"端口映射
（可选）"）。S7 的 102 是特权端口，compose 方式已通过 `NET_BIND_SERVICE`
处理；`docker run` 方式需追加 `--cap-add NET_BIND_SERVICE`。

**Q：数据存在哪？怎么备份？**
全部在挂载卷 `/app/data`（SQLite 数据库 + 日志 + 基线/基准结果）。
备份 = 备份这个 NAS 文件夹。

**Q：怎么改密码 / 开启鉴权细节？**
见仓库 README 的「安全与鉴权」章节；生产环境务必设置
`PROTOFORGE_ADMIN_PASSWORD` 与 `PROTOFORGE_JWT_SECRET`。
