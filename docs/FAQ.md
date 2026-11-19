# ProtoForge 常见问题手册（FAQ）

> 收录自 QQ 群高频问答与现场排查实录，按"连不上 / 数据读写 / 部署与数据 / 协议能力"分组。
> README 的[常见问题排查](../README.md#-常见问题排查)收录最高频条目，本文件是完整版。

## 一、连不上类

**Q1：Docker 里启动了，为什么工具连不到模拟设备？**

容器内协议服务正常监听，但宿主机没有映射端口。用 `docker port protoforge` 检查；推荐用官方 `docker-compose.simple.yml`，常用协议端口（Modbus 5020、OPC-UA 4840、MQTT 1883、S7 102、EIP 44818 等）已全部映射。

**Q2：S7 启动报错 "Port 102 is a privileged port"？**

Linux/Docker 绑定 <1024 特权端口需要权限，三选一：

```bash
# 方案一（推荐）：放行特权端口
sudo sysctl -w net.ipv4.ip_unprivileged_port_start=0
# 永久生效：
echo 'net.ipv4.ip_unprivileged_port_start=0' | sudo tee /etc/sysctl.d/99-unprivileged-ports.conf
sudo sysctl --system

# 方案二：改端口 + socat 转发回 102
# 设备高级配置把 S7 端口改为 1102，然后：
sudo apt install socat
socat TCP-LISTEN:102,fork,reuseaddr TCP:127.0.0.1:1102 &

# 方案三：Docker 加 --cap-add NET_BIND_SERVICE
```

**Q3：同一台电脑上，客户端工具连不上 44818？**

先 `netstat -ano | findstr :44818`（Windows）确认监听存在，再确认客户端填的 IP 是本机。最稳做法：**客户端直接填 `127.0.0.1`**——回环不经过任何网卡和防火墙。局域网连不通九成是防火墙把网络归为"公用"拦截了入站，给 ProtoForge 的 python/进程放行入站即可。

**Q4：HMI 仿真和 ProtoForge 在同一台机器，轮询一直掉线？**

优先换 Modbus TCP 走 `127.0.0.1:5020`——RTU 与 TCP 数据区完全同源，点表不用改。必须用串口仿真时：检查虚拟串口对（com0com 等）配对与缓冲；轮询周期放大到 500ms 以上、超时 3 秒（HMI 模拟器轮询比真屏激进）。还掉线就开 `raw_frames` 看报文定位是谁先断。

**Q5：EIP 客户端"开启失败"，怎么换端口？**

AB 协议高级配置改 host/port（如 44819），**停止再启动**协议生效；客户端侧同步修改。客户端协议栈绑定了特定网卡 IP 时，把监听地址改成同一网段网卡，或干脆换两台机器。

**Q6：怎么确认跑的是新版、修复有没有生效？**

网页界面看版本号（便携包/源码均显示）；Docker 确认镜像 tag；拿不准就开 `raw_frames` 导出帧日志，对照该版本修复点逐条验证。

## 二、数据读写类

**Q7：外部写值成功但读回不对？**

三个常见坑：① 点位是只读（r）会返回 Modbus 异常，改回 rw；② float32/int32 占 2 个寄存器且大端序，用 FC16 一次写两个寄存器，只写一个或字序反了值就不对；③ 客户端显示缓冲没清空（残留旧值是客户端显示问题，以设备页"值"列为准，重启客户端验证）。

**Q8：写入的值过一会儿又变回去了？**

点位开了随机/正弦等动态生成器，外部写入只保持约 30 秒后被覆盖。要固定就把生成方式改"固定值"；要更像真实传感器就把范围设小让它轻微波动（顺带解决组态软件死值报警误报，见 [死值检测一文](articles/scada-dead-value-detection.md)）。

**Q9：布尔点位永远读到 1？**

布尔配了 min/max 的随机生成器（非零恒为真）。v1.8.6 起布尔动态生成器改为随机 0/1 翻转；布尔点位不需要 min/max 参数。

**Q10：S7 能按标签名（符号）访问吗？**

不能。经典 S7 走绝对地址（DB 号 + 字节偏移，如 `DB1.DBX0.0`）；符号是编程软件离线解析的，线上报文里从来没有 tag 名。要"按名字读写"用 OPC-UA（节点名即标签）或 AB/EtherNet-IP（CIP Tag）。S7-1500 优化块的符号访问走 S7Comm-Plus，需要博途配合，第三方客户端基本都用绝对地址。

**Q11：AB/EIP 标签能用中文吗？**

标签值可以（UTF-8 实测，一个中文字 3 字节）；标签名模拟器侧支持，但对接真实 PLC 建议标签名用英文（罗克韦尔/欧姆龙都有限制），值用中文没问题。

**Q12：一台电脑能建多个同协议设备吗？**

能，数量不限。但单协议服务只有一个监听端口，客户端按标签名/地址区分——**标签名不能重复**，重名永远命中先建的。建议按 `PLC1_xxx`/`PLC2_xxx` 前缀区分；要模拟不同 IP 需再起一个实例换端口（如 44819）。

**Q13：报文哪里看？出问题怎么给开发者定位？**

协议高级配置 `raw_frames` 填 `true`（小写；该字段为文本框，非空即开启）→ **先停止再启动协议**（启动参数才生效）→ 复现操作 → 日志页筛 `frame_rx`/`frame_tx` 导出。单帧排查可用 `/api/v1/compliance/decode-frame` 接口逐字段展开（modbus_tcp/modbus_rtu 已支持）。给开发者报问题时务必带上：版本号、复现步骤、建连那一刻起的完整帧日志。

## 三、部署与数据类

**Q14：管理界面端口和数据端口是一回事吗？**

不是。便携包管理界面默认 18080（exe 旁 `.env` 的 `PROTOFORGE_HOST`/`PROTOFORGE_PORT` 控制）；HTTP REST 协议数据接口默认 8080（该协议高级配置的 port）。各管各的，防火墙都放行才能局域网访问。

**Q15：局域网访问不了管理界面？**

便携包 v1.6.19+：exe 旁 `.env` 加 `PROTOFORGE_HOST=0.0.0.0` 重启；或命令行 `ProtoForge.exe desktop --host 0.0.0.0`。数据接口默认已监听 0.0.0.0，连不通查防火墙入站规则（放行 18080/8080 或放行程序）。

**Q16：admin 密码是什么？**

demo 模式默认 admin/admin；正式模式首次启动随机生成，存 `data/.admin_password`（记事本打开即见）；或用环境变量 `PROTOFORGE_ADMIN_PASSWORD` 固定。备份接口不含密码哈希，恢复后需重设密码。

**Q17：重启后设备没了？**

按部署形态对号：① Docker 没挂卷——用官方 compose（自带 `protoforge-data` 卷）或 `docker run` 加 `-v protoforge-data:/app/data`；② 便携包有多个解压目录——每个目录各有一套 data，认准一个目录，迁移拷整个 `data` 文件夹（含 `-wal`/`-shm`）；③ 双实例并存——源码模式 8000 与便携包 18080 数据完全独立。备份统一走 `/api/v1/backup` 接口（先登录拿 JWT）或直接备份数据库文件。

**Q18：换电脑怎么迁移？**

装好 Python 3.10+，拷贝项目文件夹，**删掉 venv**（记录了旧机器的绝对路径，不可复用）再跑 `quickstart.bat` 重建；或直接用便携包，旧机 `data` 文件夹拷到 exe 旁。源码版与便携包数据库格式通用。

**Q19：1883 等端口和其他应用冲突？**

Docker 端口映射建容器时固定：编辑 compose 把 `- "1883:1883"` 注释或改 `- "18830:1883"`，再 `docker compose -f docker-compose.simple.yml up -d` 重建（数据在卷里不丢）。容器内部功能不受影响。

## 四、协议能力类

**Q20：支持 RTU over TCP 吗？**

支持（v1.16.2+）。设备高级配置 Link Mode 三选：

| 客户端形态 | 模式 | 地址 |
|---|---|---|
| Modbus TCP/MBAP 客户端（Kepware/组态 TCP 驱动） | `tcp_bridge` | 默认 5021 |
| RTU 帧+CRC 直走 TCP（pymodbus framer=RTU、NPort/USR-TCP232 透传） | `rtu_over_tcp` | 默认 5022 |
| 真/虚拟串口（com0com） | `serial` | COM 口 |

原理与坑详见 [RTU over TCP 一文](articles/rtu-over-tcp-two-framers.md)。

**Q21：哈斯 CNC 有模拟吗？**

走 NGC 的 MTConnect 输出（HTTP XML，默认端口 7878）：点位名按哈斯 DataItem 命名，服务自动归组件（execution/program/mode/status → Controller；spindle → 主轴；Xact/Yact/Zact → Axes）；最稳做法是抓真机 `/probe` 输出照抄 DataItem 清单。FOCAS 是发那科的，哈斯别往那边对。老款哈斯（Classic Haas）串口专有协议需定制开发。

**Q22：汇川设备支持吗？**

Modbus RTU/TCP 全支持（主站模式可直连真实汇川设备按扫描周期轮询）；EtherNet/IP 走 AB(CIP) 从站，已实测对接汇川 HMI/PLC/编程软件；EtherCAT 实时总线主从、CANlink 不在仿真平台范围内。

**Q23：冷门/专有协议能加吗？**

有真机能抓包、或有协议文档即可评估定制开发，交付后与内置协议同等待遇（界面启停、黄金用例回归、随版本发布）。欢迎先在 GitHub/Gitee 提 Issue 写清型号、协议和对接端。

---

*本手册持续更新，来源是群里每一个真实排查案例。更多协议对接实战见 [articles/](articles/)。*
