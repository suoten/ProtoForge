# 实测兼容性列表（Compatibility Matrix）

> 每一行都来自真实用户的真实联调，不是 PPT 兼容性。
> **没有实测依据的一律标"待实测"，不做承诺。** 每修一个兼容性问题，此表新增一行。
> 所有兼容性修复进入黄金用例（Golden Test Gate）回归，随版本发布——修过的坑永不再犯。

图例：✅ 实测通过 · ⚠️ 待实测（原理可行但无真实客户端验证）· 🚧 规划中 · ❌ 不支持

## EtherNet/IP (CIP)

| 客户端 | 能力范围 | 状态 | 验证来源 |
|---|---|---|---|
| 汇川 InoTouchPad / 汇川 Demo（PCCC 0x4B/0x4C） | 按标签名读写、扫描、Class3 连接 | ✅ | v1.6.34–v1.6.39 真实联调（2026-10） |
| 汇川 InoProShop / 组态软件 EIP 驱动 | CIP 符号化标签读写 | ✅ | 同上 |
| 欧姆龙 NJ501（Sysmac Studio 全局变量） | CIP 符号化标签（与 AB 同套机制） | ✅ | 2026-10 真实联调 |
| Kepware（EIP 驱动） | 显式报文读写 | ✅ | 早期版本迭代验证 |
| 中文标签 | 标签名/标签值 UTF-8 读写 | ✅ | v1.6.34+ 实测 |
| EtherNet/IP 隐式 I/O（Assembly 实例，如 `20 04 24 78 2C 64…` 路径） | 周期性 I/O 数据生产 | 🚧 | 待主站真实报文，欢迎提 Issue 附帧日志 |

## Modbus TCP / RTU / RTU over TCP

| 客户端 | 能力范围 | 状态 | 验证来源 |
|---|---|---|---|
| MCGS 组态 | Modbus TCP 读写、轮询 | ✅ | 2026-10 真实联调（含死值检测规避） |
| pymodbus（`framer=RTU` over TCP） | RTU 帧+CRC 直走 TCP | ✅ | v1.16.2 发布验证 |
| 通用组态软件 TCP 驱动 / Modbus Poll 等 | MBAP 读写（FC01-06/15/16） | ✅ | README 常规场景 |
| 汇川 PLC/HMI（H5U/AM/MD 系列） | Modbus RTU/TCP 主从互连 | ✅ | 2026-10/11 真实联调 |

## S7 / OPC-UA / HTTP / FOCAS / MTConnect

| 客户端 | 能力范围 | 状态 | 验证来源 |
|---|---|---|---|
| snap7 / Kepware S7 驱动 | DB 号+偏移绝对地址读写 | ✅ | 标准客户端常规场景 |
| UaExpert | OPC-UA 匿名连接、浏览、订阅 | ✅ | 常规场景 |
| 自定义节点/多级命名空间 | `ns=2;s=…`、地址含 `/` 自动分层（v1.6.23+） | ✅ | 真实联调 |
| HslCommunication | HTTP REST GET/PUT（JSON body & URL 参数） | ✅ | v1.6.28 修复后验证 |
| EdgeLite Go 采集客户端 | FOCAS (Ethernet) 帧级协议 | ✅ | 自研驱动实测 |
| FANUC 官方 fwlib32 客户端 | FOCAS | ⚠️ 待实测 | 线协议为 FANUC 私有，各家实现有差异，欢迎提供真实客户端验证 |
| 哈斯 NGC 采集端 | MTConnect (`/current` `/sample` `/probe`) | ⚠️ 待实测 | 已提供对接步骤，等真实客户端回报 |

## 明确不支持

| 场景 | 原因 |
|---|---|
| EtherCAT 实时总线主从（真实网段） | 平台定位为 TCP 帧级仿真，非实时总线栈 |
| CANlink（汇川） | 同上 |
| S7-1500 优化块符号访问（S7Comm-Plus + 博途） | 需博途离线符号表，第三方客户端通用路径是绝对地址 |

## 贡献你的验证结果

你的客户端不在表里？两条路：
1. 直接试：协议起服务 → 客户端连 → 通了/不通都欢迎在 [Issues](https://github.com/suoten/ProtoForge/issues) 回报（附客户端名称版本 + 现象）；
2. 连不上：开 `raw_frames` 导出帧日志发 Issue——**我们按真实报文实现兼容，这是惯例**。
