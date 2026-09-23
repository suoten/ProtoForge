# Changelog

## v1.3.0 — 2026-09-16

**Feature — 工业标杆级升级：新增 4 个协议 + 设备/场景克隆 + 北向平台预设 + DAG 规则链编排引擎**

- **新增协议 DLT/T 645-2007**：多功能电能表通信协议，中国电力行业标准，BCD 编码 + 0x33 传输加密，支持有功/无功电能、电压/电流/功率数据读取，端口 37120
- **新增协议 CJ/T 188-2004**：户用计量仪表数据传输协议，中国城建行业标准，支持水表/气表/热量表，BCD 编码、类型码寻址，端口 37121
- **新增协议 Custom TCP/UDP**：自定义帧格式仿真，支持十六进制模板解析、变长帧、校验和计算、灵活数据映射，端口 38000/38001
- **新增协议 S7Comm-Plus**：西门子 S7-1200/1500 新一代通信协议，基于 TPKT/COTP，支持优化块访问、SZL 读取、符号寻址，端口 10202
- **设备克隆 API**：`POST /devices/{device_id}/clone`，一键复制设备配置（协议、测点、生成器、协议配置）
- **场景克隆 API**：`POST /scenarios/{scenario_id}/clone`，一键复制场景（设备绑定、运行参数）
- **北向平台预设**：ThingsBoard / 阿里云 IoT / EMQX 三大平台一键配置数据转发
- **DAG 规则链编排引擎**：`source -> filter -> transform -> action` 链式执行，支持 JSON DSL 定义规则链
- **设备模板扩充至 131 个**：新增 dlt645（单相/三相电表）、cjt188（水/气/热表）、custom_tcp/udp（传感器）、s7plus（S7-1500）模板
- **i18n 修复**：补全 9 个协议（iec104/iec61850/coap/dds/dlt645/cjt188/custom_tcp/custom_udp/s7plus）的中英文描述与端口号，修复协议服务页面描述显示为 i18n key 及端口显示为 8000 的问题

**Improvement — 客户端连接注意事项推广到全协议（由 MQTT 3.1.1 协议版本坑泛化）：**

- 设备弹窗（快速创建 / 高级创建 / 编辑）的连接注意事项改为数据驱动（`web/src/protocolNotes.js`，双语），选中协议即展示对应条目，新增 15 个协议的已知连接坑：Modbus TCP（Unit ID）、Modbus RTU（串口三要素）、S7（rack/slot 与 PUT/GET）、OPC-UA（Security=None + Anonymous）、IEC 104（CA/IOA）、DL/T 645（表地址与 0x33）、CJ/T 188、FINS（UDP/TCP 端口）、MC（3E/4E 帧）、BACnet（UDP 47808 / BBMD）、FANUC（8192 端口）、OPC DA（DCOM 权限）、AB（CIP 槽号）、GB28181（SIP 注册三元组）、自定义 TCP/UDP（帧格式）
- 文档新增「其他协议的数据外送」说明：除 MQTT（设备级自定义 broker）与 GB28181（设备主动注册平台）外，其余协议为服务端模型，数据外送统一走数据转发功能

**Bug Fix — 仿真测试"可视化编辑"无法选择操作（下拉空白 + 控制台 `Cannot read properties of undefined (reading 'forEach')`）：**

- 根因：测试步骤的"操作"下拉用 naive-ui n-select 构造分组选项时，把 `{type:'group'}` 分组与选项**平铺**在同一层且分组缺少必需的 `children` 数组，n-select 渲染分组时对 `undefined.forEach` 抛 TypeError，整个下拉组件渲染成空壳——表现为"操作下拉点不开/选不上、设备/测点参数框出不来"，执行测试必然失败
- 修复：分组选项改为标准嵌套结构（`{type:'group', label, key, children:[...]}`），与导航菜单的写法一致
- 验证：真实服务 + 浏览器端到端复现（修复前：下拉空壳 + 控制台 TypeError；修复后：下拉正常打开、8 个操作全部可见、选择"读取测点"后设备/测点参数框正常联动出现、无控制台错误）

**Bug Fix — `.env` 编码被改坏导致服务启动崩溃 `UnicodeDecodeError: 'utf-8' codec can't decode`：**

- 根因：`.env.example` 的注释含中文，安装时复制为 `.env`；清理工具或系统自带记事本一旦把 `.env` 重新编码为 GBK/ANSI，服务启动读 `.env`（固定按 UTF-8）即崩溃，且重新安装也无法自愈（安装器保留已存在的 `.env`）
- 修复：`.env.example` 注释全部改为纯 ASCII（中文文档指向 README），从源头消除该故障类别；安装器新增 `_read_env_text()` 编码自愈——读 `.env` 遇到非 UTF-8 时按 GBK 解码并自动重写回 UTF-8（覆盖 `_ensure_env_key` 与端口/密码读取两处），重新运行 install.bat 即可修复被改坏的 `.env`
- 用户临时修复：删除项目根目录的 `.env` 后重新运行 install.bat

**Improvement — MQTT 外部 broker 发布在协议调试日志中可见（external_publish 事件）：**

- 背景：用户对接 ThingsBoard 时连接成功（external_connect）但无法确认数据是否在上传——外部发布路径此前没有调试日志事件，只有连接/失败事件，观测存在盲区
- 实现：每次向外部 broker 发布成功记录 `tx/external_publish` 事件，含主题、QoS、Retain、字节数与 payload 预览（超 200 字节截断并标注，避免日志膨胀）

**Bug Fix — 安装器第 4 步"构建前端页面"崩溃：`FileNotFoundError: [WinError 2] 系统找不到指定的文件`：**

- 根因：安装器用裸字符串 `"npm"` 调 `subprocess.run`，Windows 的 `CreateProcess` 只能直接解析 `.exe`，而 npm 是 `npm.cmd`；且 Windows 版 Node.js 发行包里同时带一个无扩展名的 Unix sh 脚本 `npm`，`shutil.which("npm")` 可能命中它导致 `WinError 193`（不是有效的 Win32 应用程序）。两种情况都会让源码安装在第 4 步直接抛异常中断
- 修复：新增 `_find_npm()`——Windows 下显式优先解析 `npm.cmd` 完整路径（次选 `npm`，最后兜底 Unix 的 `npm`），`npm install` / `npm run build` 全部使用解析出的完整路径；npm 启动异常（`OSError`）不再中断安装，降级为"使用仓库中预构建的前端"并给出提示；前端构建失败时打印 stderr 末尾 3 行辅助定位
- 验证：`npm --version` 经解析路径调用成功（rc=0）；安装器语法编译通过

**Bug Fix — 编辑设备/模板"添加测点"后保存报"更新失败"（默认地址与既有点位重叠被 400 拦截）：**

- 根因："添加测点"的默认地址取 `points.length`（如第 5 个点位默认地址 4），而默认类型 float32 占 2 个寄存器（4~5）。设备中只要存在相邻的多字节点位（如内置温湿度传感器模板的报警位@5、或连续排列的 float32），默认地址必然与既有点位地址范围重叠——v1.2.7 起后端会拦截重叠并返回 400"检测到同设备点位地址重叠"，界面表现为"更新失败"，用户无从得知是默认地址撞车
- 修复：默认地址改为自动计算下一个不重叠的空闲寄存器地址——按数据类型寄存器占用数（bool/int16 占 1、float32/int32 占 2、float64 占 4、string 占 32，与后端一致）、区分线圈/保持寄存器存储区、兼容 C/HR/IR/DI 前缀与 6 位 PLC 记法（40001→地址 0）；默认点名同步避让重名。覆盖设备编辑弹窗与模板新建/编辑弹窗共 3 处入口
- 说明：若设备**既有**点位本身已重叠（历史数据），保存仍会被拦截，错误信息中会列出冲突点位名与地址范围，按提示调整即可；新增点位的默认地址不会再引发冲突
- 校验脚本 `web/scripts/validate-point-address.mjs`（22 例）：地址解析（纯数字/前缀/PLC 记法/非法输入）、空闲地址分配（模板场景/连续多字节/混合前缀/线圈区独立分配/空列表）、点名避让；`node scripts/validate-point-address.mjs` 可独立运行

**Bug Fix — AB/EtherNet-IP pylogix Forward Open 永远失败（四处帧格式错误叠加）：**

- Null Address Item：SendRRData 应答中 Null Address Item 写了 Length=4 并多跟 4 字节零（标准要求 Length=0 无数据），CIP 数据整体偏移 +4，客户端在 offset 42 读 GeneralStatus 读到错位字节
- Priority/TimeoutTicks：Forward Open 请求解析只跳过 1 字节，实际 Priority(1) 与 TimeoutTicks(1) 是两个独立字节，后续所有字段（连接 ID/参数）错位 1 字节，echo 回客户端的值错误
- Large Forward Open：pylogix>=1.1 在 ConnectionSize>511 时发送 0x5B Large Forward Open，原实现不识别直接返回错误帧；现按大格式解析（Params 为 4 字节，响应 Service=0xDB）
- SendUnitData：item_count 原来读在 offset 16（EIP header 内部），导致 Read/Write Tag 全部走错误分支，已连接模式读写永远失败；现按标准布局解析（header(24)+InterfaceHandle(4)+Timeout(2)+ItemCount(2)+Address Item+Data Item）
- 补充 CIP Get_Attributes_All (0x01)：pylogix 的 GetDeviceProperties()/连接 ping 依赖 Identity Object 查询，缺失时连接验证永远失败；现返回标准属性集（VendorID/DeviceType/ProductCode/Revision/Status/SerialNumber/ProductName，名称取自协议配置 device_name）
- 读标签支持 `@cpu` / `@identity` 探针标签：EdgeLite/上位机常用该标签做连接健康检查，现返回设备名字符串（STRING 类型码 0xD0）
- 回归测试 `tests/test_ab_forward_open.py`（11 例）：Null Address Item 结构（Length=0 无数据）、CIP 数据固定 offset 40、总长无额外填充、Forward Open echo 字段固定偏移、session/context 回显、0x5B 大格式响应 0xDB 与 4 字节 Params、SendRRData 路由 0x5B、Get_Attributes_All 属性集结构与默认名称、`@cpu` 探针返回设备名、端到端请求-应答 Item 解析往返

**Bug Fix — 系统代理劫持集成层出站请求（502）+ EdgeLite Modbus 点位读取存储区错位：**

- 系统代理：所有出站 `httpx.AsyncClient`（failover 对端健康检查、数据转发 InfluxDB/HTTP、webhook 推送、集成管理器/认证/HTTP 通道、EdgeLite 对接）补齐 `trust_env=False`——开启系统代理时回环/内网地址请求被代理劫持导致 502。回归测试 `tests/test_http_client_trust_env.py`（4 例）
- EdgeLite 点位地址：地址翻译此前输出裸数字地址 + register_type，但 EdgeLite 的 modbus 驱动仅从地址前缀判定存储区（不读 register_type），input/coil/discrete 区会被错误当作 holding 读取。现输出带前缀地址（HR/IR/C/DI），register_type 作为冗余信息保留；FINS 地址按点位 data_type 附加驱动类型后缀（",r"/",i"/",dw" 等，原默认按 word 解析拿到原始字节）。测试 `tests/test_edgelite_point_translation.py` 更新至新语义并扩展至 42 例（含 FINS 后缀、OPC-UA 设备前缀）

**Feature — FANUC 协议原始报文日志（raw_frames）：协议调试日志可查看底层 16 进制收发帧（协议研究场景）：**

- 背景：用户学习研究 FANUC 协议底层 16 进制报文，协议调试日志此前只有应用层抽象事件（连接/请求/响应），看不到通信过程中的原始字节流
- 实现：FANUC 协议新增 `raw_frames` 高级配置项（默认关闭，boolean；兼容 UI 文本输入 "true"/"1"/"on"/"yes"）。开启后每次 TCP 收发在协议调试日志中记录 `frame_rx` / `frame_tx` 事件，含完整 16 进制 dump、对端地址与字节长度；超过 256 字节的报文截断展示并标注总长，防止日志膨胀
- 使用：协议服务页 → FANUC「高级配置」→ 添加 `raw_frames: true` → 点「启动」；默认关闭，不影响正常性能
- 回归测试 `tests/test_fanuc_raw_frames.py`（5 例）：开启后 rx/tx 事件与 16 进制内容逐字节校验、默认关闭、字符串 "false"/"true" 兼容、256 字节截断保护；真实 TCP 连接端到端验证

**Bug Fix — 布尔量点位读写异常：UI 显示 true/11 而协议寄存器为 0/1（用户实测）：**

- 根因：写入链路不按 data_type 归一值。bool 点位写数字 11 → 原样入库，UI 显示 11、线圈却编码为 1；数值点位写字符串 "true" → int("true") 转换失败被静默吞掉，原始字符串入库，UI 显示 true、寄存器保持 0 —— 界面值与协议线上的值不一致，用户侧无从排查
- 修复：新增共享归一函数 `normalize_point_value()`（`protoforge/models/device.py`），写入三处入口（API 层 `PUT /devices/{id}/points/{name}`、Modbus 协议层 `server.write_point`、DeviceInstance `write_point`）统一归一：bool 接受 "true"/"1"/"on"/"yes"（→True）、"false"/"0"/"off"/"no"（→False）、数字非零→True（与 Modbus 线圈语义一致）；数值类型字符串自动转换并钳制到类型范围；不可表示的值拒绝写入，API 返回 400 并给出点位名、数据类型与原因
- 排查确认的另一要点：**bool 点位自动落在线圈区（0xxxxx）**，主站须用 FC01 读、FC05 写，FC03 读保持寄存器看不到布尔量点位；数值型点位才在保持寄存器区（4xxxxx）。已在 README 地址表与设备弹窗连接注意事项中标注
- 回归测试 `tests/test_bool_value_normalization.py`（16 例）：归一函数单元测试（bool/数值/字符串/拒绝/钳制）+ API 层复现用户场景（写 "true"/11 到 bool 点位归一为 True、写 "true" 到 uint16 返回 400、写 "42" 正常转换）；诊断脚本 `scripts/diag_bool_write.py` 端到端验证线圈编码与寄存器值一致

**Bug Fix — Windows 后台启动（start /B）后 `protoforge stop` 无法停止服务（Issue #12）：**

- 根因一：PID 文件（`data/protoforge.pid`）仅在 Unix daemon 分支写入，Windows 上 `--daemon` 被禁用并引导用户用 `start /B` 启动——该路径永远不产生 PID 文件，`protoforge stop` 提示 "No background daemon found"
- 根因二（潜伏 Bug）：旧 stop 流程用 `os.kill(pid, 0)` 探测进程存活，但 Windows 上 `os.kill` 对非 CTRL_* 信号一律走 `TerminateProcess`——**探测本身就会把目标进程杀掉**（退出码 0），等待-超时-SIGKILL 逻辑全部失效
- 修复：所有启动方式（前台 / `start /B` 后台 / Unix daemon）统一写入 PID 文件，优雅退出时经 atexit 自动清理；`_process_alive()` 跨平台安全探测（Windows 用 `tasklist`，含重试防护，Unix 沿用 `os.kill(pid, 0)`）；Windows 停止改用 `taskkill /PID x /T /F`（杀进程树，含 uvicorn reload 子进程），超时/失败时兜底 `TerminateProcess`；无 PID 文件时按 `--port`（默认 8000）兜底查找监听中的 python 进程（`netstat -ano`），并校验进程镜像名防止 PID 复用误杀；Windows 下 `--daemon` 提示文案同步更新为可用的后台启动/停止流程
- Windows 真实环境端到端验证：`start /B` 等效方式后台启动 demo 服务 → PID 文件与实际进程一致 → `protoforge stop` 成功停止且端口关闭、PID 文件清理；删除 PID 文件后重启服务 → 按端口兜底成功停止
- 回归测试 `tests/test_cli_stop_windows.py`（9 例）：存活探测（含旧实现误杀回归）、PID 文件写入与清理、stop 杀死/残留清理/无目标提示、端口兜底查找

**Bug Fix — 服务运行中修改协议端口（高级配置→启动）被静默忽略（用户反馈"自定义 TCP 端口号改不了"）：**

- 根因：`engine.start_protocol` 对 RUNNING 状态一律静默跳过并返回成功。用户在协议服务"高级配置"弹窗把端口从 38000 改成其他值后点"启动"，界面提示启动成功，但服务仍监听旧端口——实际影响**所有协议**，不只 custom_tcp
- 修复：单协议启动端点（`POST /protocols/{name}/start`）改为 `restart=True` 语义——协议已运行时先停止再按提交的配置启动（改端口后点启动即生效）；"一键启动全部"已预先过滤运行中的协议、设备创建的协议自动启动、demo 模式、集成管理器均保持原有幂等跳过语义，不受影响
- 回归测试 `tests/test_protocol_restart_port.py`（3 例）：运行中带新端口重启 → 新端口监听旧端口释放、start-all 幂等性（不重启运行中协议）、设备自动启动路径语义不变；真实服务端到端验证（默认端口启动 → 改 38124 重启 → 38000 关闭 / 38124 监听 / 停止后端口释放）

## v1.2.7 — 2026-09-16

**Bug Fix — 同设备点位地址重叠导致固定值失效/乱值（FLOAT32 占 2 个寄存器互相覆盖）：**

- 根因：Modbus 多字节类型（float32/int32/uint32 占 2 个寄存器，float64 占 4 个，string 占 32 个）按起始地址向后占用多个寄存器。用户模板中 humidity@2（占 2-3）与 point_4@3（占 3-4）在寄存器 3 上重叠——两个点位的生成器各自按自己的节拍写寄存器 3，后写的字节序把先写的覆盖掉，导致"固定值=10"的 point_4 持续显示乱值（-1.86e-27 之类）且不断变动。用户侧完全无从排查
- 修复：新增共享校验 `find_overlapping_points()`（`_common.py`），按同一存储区（线圈/离散/输入/保持）内地址范围做区间相交检测；所有设备与模板写入入口统一拦截——创建设备、快速创建（含模板）、批量创建、克隆设备、更新设备、CSV 导入、创建模板、更新模板、导入模板、模板实例化共 10 处。命中重叠返回 400，错误信息含冲突点位名、存储区、地址范围与寄存器占用明细（如"点位 'humidity'(地址 2, 保持寄存器区(4区), 占2个寄存器) 与 'point_4'(地址 3, ...) 地址范围重叠 [2~3] 与 [3~4]"）
- 校验仅对 modbus 系协议生效；不同存储区同地址（如线圈@0 与保持寄存器@0）不冲突
- 前端：设备测点弹窗新增"地址"列，modbus 纯数字地址按后端 auto 规则展示 5 位规范地址（bool→线圈区 00001 起，其他→保持寄存器区 40001 起，如 `3 (40004)`），多字节点位占多个寄存器从界面上一眼可见；快速写入下拉同步展示点位地址
- 回归测试 `tests/test_point_overlap_validation.py`（7 例）：重叠拒绝/非重叠放行/跨存储区允许/更新拦截/快速创建模板拦截/批量创建记入 error 列表/非 modbus 不校验；既有 API 测试中本身含重叠数据的用例已修正地址

## v1.2.6 — 2026-09-16

**Bug Fix — Modbus 只读点位（access='r'）可被外部客户端写成功：**

- 根因：访问模式只在平台自身写入路径（UI 快速写入 / `PUT /devices/{id}/points/{name}` / `ModbusServer.write_point`）校验；外部 Modbus 客户端走原生帧处理器（FC05/06/0F/10/16/17）直接写 store，完全不校验 access——界面上标为"只读"的点位被外部写成功且经 `_notify_external_write` 反向传播回点位值，语义不一致
- 修复：TCP 与 RTU 两套 server 的全部外部写路径统一增加只读校验。命中 access='r' 点位（按地址范围匹配，含多寄存器点位跨度）→ 返回异常码 0x01（ILLEGAL FUNCTION），store 不变、不触发双向传播，并记 warning 日志 + `_log_debug`（事件 `modbus_write_rejected`）；广播写命中只读点位时按广播语义丢弃（无响应）
- 共享助手下沉 `_common.py`：`point_area()`（auto 按数据类型判定存储区，与写入规则一致）、`point_reg_count()`、`WRITE_FC_AREA_MAP`，TCP/RTU 同源校验避免两份逻辑漂移
- 回归测试 `tests/test_modbus_readonly_write_guard.py`（18 例）：TCP/RTU × 六种写功能码只读拒绝/放行、范围跨度拦截、广播静默丢弃、access='w' 可写、拒绝后不触发传播、rw 写传播不受影响
- 真实 socket 验证 `tests/test_e2e_modbus_real.py::test_real_modbus_write_to_readonly_point_rejected`：真实 pymodbus 客户端写只读点位收到异常码 0x01、寄存器值不变、相邻 rw 点位正常写

## v1.2.5 — 2026-09-16

**Feature — MQTT 仿真设备支持上报自定义 MQTT 服务器（设备仿真对齐真实设备行为）：**

- 设备协议配置新增 `server_host` / `server_port`（可选 `username` / `password` / `client_id`）：填入后仿真设备将以 MQTT 客户端身份连接用户自己的 broker（EMQX / Mosquitto / 阿里云 IoT 等）并上报数据，不再局限于内置 broker
- 发布按设备路由：配置了 `server_host` 的设备走外部 client 发布，未配置的继续走内置 broker；遗嘱消息同样路由
- 外部连接不可达时不会拖垮仿真：5s 重连限频 + 每 60s 限频告警 + 协议错误计数，恢复后自动重连
- UI：创建 / 快速创建 / 编辑设备弹窗新增 MQTT 连接注意事项醒目提示；连接引导同步更新

**Note — 内置 MQTT Broker 仅支持 MQTT 3.1.1：**

- amqtt 不支持 MQTT 5.0。MQTTX 等客户端连接时必须手动将 Protocol Version 设为 3.1.1，否则连接失败（用户实测 MQTTX 默认 5.0 连不上，排查半天发现切协议版本即可）。已在 README、连接引导、设备弹窗三处醒目标注

## v1.2.4 — 2026-09-16

**Bug Fix — MQTT 设备启动后外部订阅者（MQTTX 等）收不到数据：**

- 根因：点位 `address` 为单段值（官方 MQTT 模板即如此，如 GPS 模板 `address="latitude"`）时，发布主题被错误地当作**完整 topic** 使用，实际发到 `latitude`、`speed` 等顶层主题，`topic_prefix` 与 `device_id` 层级全部丢失，订阅 `protoforge/gps/#` 的客户端永远收不到数据
- 修复：新主题推导规则 —— address 含 `{device_id}` 占位符 → 替换后使用；address 含 `/`（多级路径）→ 视为显式完整 topic；address 为空或单段 → 走默认层级 `{topic_prefix}/{device_id}/{point.name}`
- 顺带验证：amqtt 0.11.3 `internal_message_broadcast` 内部广播路径本身可达（最小复现脚本确认），排除此前怀疑的 amqtt API 断裂
- 回归脚本 `scripts/diag_mqtt_publish.py`：完整复现用户场景（broker + GPS 设备 + 外部订阅者），修复后订阅 `protoforge/gps/#` 正常收到 `protoforge/gps/latitude` 等消息
- 注意：`topic_prefix` 在该版本起真正生效，使用官方模板创建的 MQTT 设备主题将变为 `{topic_prefix}/{device_id}/{point_name}`（如 `tracker/gps/<设备ID>/latitude`）

## v1.2.3 — 2026-09-15

**Bug Fix — 实时日志页高频流量下浏览器崩溃（含全站 WebSocket 推送排查）：**

- 后端 `/ws/logs` 改为批量下发：一次排干队列积压（最多 200 条/帧），循环内高频日志（多设备被持续轮询）从每秒上千个 WS 帧降为个位数大帧
- 后端 `/ws/devices` 加变化检测：设备列表仅在内容变化时发送，空闲期零重复推送（原实现每 0.1s 全量重发）；协议状态事件批量排干（最多 20 个/帧，帧型 `protocol_status_batch`）
- Dashboard 日志流适配批量帧并改为 200ms 批量刷入（原逐条 unshift 每 500 条触发全量重渲染；且只处理旧 `log` 帧型，批量改造后已失效）
- 前端 Logs 页改为 200ms 定时批量刷入：一次 flush 只触发一次列表重渲染和一次滚动，不再逐条全量重渲染 2000 行导致主线程饱和、内存飙升
- 前端列表改用稳定 key（自增 id），新增日志只追加/裁剪，避免全列表重渲染；搜索过滤改为预拼接搜索串
- 前端重连前先关闭残留 WebSocket，修复多连接叠加导致消息重复、负载倍增
- `LogBus.emit` 跨线程安全：工作线程中的协议服务通过 `call_soon_threadsafe` 投递
- 设备点位写入 API 拒绝 inf/-inf/nan（400），修复 JSON 序列化抛 "Out of range float values" 导致的 500
- 回归脚本 `scripts/diag_log_ws_stress.py`：真实 uvicorn + WebSocket 压测，覆盖跨线程投递、循环内突发（500 条仅 2 帧）、洪峰优雅降级、设备列表变化检测

## v1.2.2 — 2026-09-15

**Bug Fix — 按照说明文档手动部署后登录 401：**

- `protoforge demo` 未设置 `PROTOFORGE_ADMIN_PASSWORD` 时，默认密码改为 `admin`（与说明文档承诺一致）；此前会生成随机密码，导致按说明文档使用 `admin`/`admin` 登录的用户收到 401
- Demo 启动时自动设置 `PROTOFORGE_RESET_ADMIN_PASSWORD=1`，旧数据库（密码为历史随机值）也会同步为 demo 默认密码；显式设置 `PROTOFORGE_RESET_ADMIN_PASSWORD=0` 可关闭
- 非 demo 模式（`protoforge run`）行为不变：未配置时仍生成随机密码并在启动横幅打印，生产环境安全默认不受影响
- 同步修正文档：README.md / README_EN.md / DEPLOYMENT.md（Docker 段密码说明），明确 demo 与生产模式的密码规则

## v1.2.1 — 2026-09-14

**Documentation Enhancement:**

- Added comprehensive Modbus register type mapping section (Coil/Discrete Input/Input Register/Holding Register with function codes)
- Added data type & register usage table (bool/int16/int32/uint32/float32/float64/string/real with byte order)
- Added step-by-step tutorial: creating devices from real address tables (Modbus address table → ProtoForge config → verification code)
- Added Modbus RTU serial port configuration documentation (baudrate/databits/parity/stopbits)
- Added multi-device coexistence documentation (multiple slave_ids on same port)
- Added write behavior documentation (FC05/06/0F/10/16/17 response and read-back behavior)
- Added data generator documentation (fixed/random/sine/increment/ramp with update_frequency parameter)
- Added competitor comparison table (vs Modbus Slave/Poll, Kepware, Node-RED Mock, real PLC)
- Added protocol compliance documentation (standards followed + exception code mapping per protocol)
- Added ARM/Raspberry Pi deployment guide with resource consumption benchmarks
- Added open source vs enterprise feature comparison table
- Updated README_EN.md with all corresponding English documentation

## v1.2.0 — 2026-09-13

**IoT Industrial Device Testing Platform:**

- Added Test Plan Management: versioned test plans with CRUD operations, clone, status filtering (draft/active/archived). Backend: `protoforge/testing/plan.py` (TestPlan/TestRun data models + TestPlanManager). Frontend: `TestPlans.vue` with create/edit/delete/clone/run/history UI.
- Added Test Execution Engine: `protoforge/testing/runner.py` (PlanRunner class) orchestrates protocol/device startup, runs test suites, applies fault scenarios, generates JUnit XML / JSON / HTML reports.
- Added Protocol Compliance Checking: `protoforge/testing/compliance.py` with 5 protocol-specific checkers (Modbus TCP, S7, OPC-UA, IEC 104, MQTT). Each checker has defined rules and violation reporting. Compliance score (percentage) generated per check.
- Added REST API endpoints: `test_plan_routes.py` (CRUD + run + history + report download) and `compliance_routes.py` (protocols list + rules preview + check execution + reports history).
- Added database tables: `test_plans`, `test_runs`, `compliance_reports` with full CRUD in `db/session.py`.
- Added CLI command: `protoforge test run` for CI/CD integration.
- Added frontend pages: `TestPlans.vue` (plan management with modal forms, run result display, report download buttons) and `Compliance.vue` (protocol selector, rules preview, check execution, score display, history tab).
- Added i18n support for all new UI elements (Chinese + English).
- Added Playwright E2E tests: 31 browser tests covering page rendering, CRUD, execution, reports, compliance checking, navigation, error handling, i18n — all passing.

**E2E Test Results (31/31 passed):**

- Test Plans page rendering: title, menu, breadcrumb, create button, empty state ✅
- CRUD operations: create, edit, delete, clone, status filter ✅
- Run & reports: execute plan, view result modal, download JUnit/HTML/JSON, run history ✅
- Compliance page rendering: title, menu, tabs, protocol selector, run check button ✅
- Compliance interactive: select protocol, view rules, run check, view score, history tab ✅
- Error handling: empty name validation, disabled button without protocol, 404 responses ✅
- Navigation: menu navigation, direct URL access ✅
- i18n: Chinese default, English switch ✅

## v1.1.1 — 2026-09-11

**UI/UX fixes (deep testing):**

- Fixed i18n `directionLabels` keys not translating in Debug Logs page — `logs.directionLabels.system` showed as raw key instead of "系统"/"System". Root cause: `directionLabels` object existed in i18n.js but was outside the `logs` namespace. Fix: moved `directionLabels` into `logs` object in both zh and en.
- Fixed NDropdown menus not responding to click — language switcher, user menu, and device "更多" dropdown used default `hover` trigger which was unreliable. Fix: added `trigger="click"` to all NDropdown components in App.vue and Devices.vue for consistent click-to-open behavior.

**Deep testing results (all passed):**

- Dashboard: 7 devices, 4 running protocols, 122 templates, 22 protocol categories ✅
- Device Management: batch start/stop, edit, data points, quick create, CSV import/export ✅
- Protocol Services: 22 protocols with start/stop/configure/detail ✅
- Template Marketplace: 122 templates with category filter and search ✅
- Simulation Testing: single device test passed (100% pass rate, 0.02s), test case editor ✅
- Debug Logs: real-time WebSocket logs, protocol/direction filter, search, export ✅
- Recorder: start/stop recording, recording list with detail/replay/export/delete ✅
- Integration: EdgeLite connection config, per-device push/start-collect/read-points/verify ✅
- Data Forward: add target, start/stop forward ✅
- Webhook: CRUD, test webhook ✅
- Settings: EdgeLite URL, CORS config, save ✅
- Audit Log: search, delete, clear ✅
- Backup & Restore: export backup, restore from file ✅
- Scenario Editor: drag-and-drop canvas, save layout, add device ✅
- i18n: Chinese/English switch works correctly ✅
- Fault Injection API: sensor_drift, sensor_stuck, comm_loss, etc. (9 types) ✅
- CSV Export API: returns valid CSV with all device points ✅

## v1.1.0 — 2026-09-11

**New Protocols (17 → 21):**

- Added IEC 60870-5-104: Power telecontrol protocol (SCADA). Pure Python TCP server with APDU/ASDU parsing, U/S/I-format frames, spontaneous data transmission, command control (single/double/set-point commands). 7 device templates (BMS, CT/PT, microgrid, protection relay, solar plant, substation RTU, transformer).
- Added IEC 61850: Substation automation standard with MMS TCP mapping. BER-encoded PDU parsing, Initiate/Conclude/Read/Write/GetNameList services, Logical Device → Logical Node → Data Object model, CDC types (SPS, MV, SPC, DPC). 3 device templates (bay controller, protection IED, solar IED).
- Added CoAP (RFC 7252): Constrained Application Protocol for low-power IoT. Pure Python UDP server with CON/NON messages, GET/POST/PUT/DELETE, Uri-Path option parsing, Observe (RFC 7641) push, /.well-known/core discovery. 4 device templates (air quality, env sensor, gateway, smart meter).
- Added DDS (Data Distribution Service): OMG standard pub/sub middleware with simplified RTPS wire protocol over TCP/UDP. Topic-based data distribution, subscribe/publish actions, QoS policies. 3 device templates (power grid, robot fleet, wind turbine).
- All 4 new protocols are pure Python — no third-party dependencies required, included in core package.

**Template expansion (90+ → 122):**

- Added 32 new device templates across 4 new protocols (17 templates) and 2 existing protocols (energy meter, PV inverter for Modbus).
- Fixed 6 duplicate template IDs that caused silent template overwriting during loading.
- Total: 122 templates across 21 protocol categories.

**CSV batch import/export:**

- Added `GET /api/v1/devices/export-csv` endpoint — export all devices as CSV with one click.
- Added `POST /api/v1/devices/import-csv` endpoint — batch import devices from CSV content.
- Frontend CSV import/export buttons in Devices page.
- Fixed route conflict: `/devices/export-csv` was incorrectly matched as `/{device_id}` — moved export route before parameterized route.
- Fixed `AttributeError: 'DeviceInfo' object has no attribute 'get'` — export logic now handles both Pydantic models and dicts.

**Recording compression:**

- Recorder `export_compressed` method now uses gzip compression for storage optimization.
- Reduced disk space usage for recorded protocol traces.

**i18n fixes:**

- Fixed i18n key display issue where `devices.importCSV` and `devices.exportCSV` showed as raw keys instead of translated text.
- Added missing i18n keys (`importCSV`, `exportCSV`, `create`, `created`, `csvEmpty`, `csvExported`, `csvExportFailed`, `csvImported`, `csvImportFailed`) in both zh and en.
- Removed incorrectly placed i18n keys from `common` namespace.
- Fixed Vue component `t()` function calls — removed incorrect fallback parameters.

**Documentation:**

- Updated README.md: protocol count 17 → 21, template count 90+ → 122, added new protocols in feature list, protocol table, port table, and architecture diagram.
- Updated version numbers across `pyproject.toml`, `protoforge/__init__.py`, and `web/package.json`.
- Updated keywords in `pyproject.toml` to include new protocols.
- Updated protocol optional-dependencies documentation in `pyproject.toml`.

**OPC-DA:**

- Real protocol implementation improvements (server.py modified).

## v1.0.0 — 2026-08-31

**Architecture refactor (core split):**

- Split the former `protoforge/core` catch-all namespace into four domain packages:
  `protoforge/engine` (simulation engine, devices, registry, event bus),
  `protoforge/simulation` (scenarios, fault injection, behavior models, time series),
  `protoforge/integrations` (EdgeLite, forward, webhook), and
  `protoforge/observability` (log bus, metrics, audit, error monitor). `protoforge/core` now only contains `auth` plus backward-compatible re-exports.
- Updated all 376 internal imports (90 files) to the new layout; ruff per-file-ignores updated accordingly.

**Protocol layer hardening:**

- Fixed silent MQTT data loss with amqtt >= 0.11: `Broker.internal_publish()` was renamed to `internal_message_broadcast()` (without a retain parameter), and the old `hasattr(internal_publish)` guard silently skipped every publish — broker connections worked but subscribers never received data. Added a version-tolerant `_broker_publish()` shim (uses `internal_message_broadcast` + public `retain_message()` on amqtt >= 0.11, falls back to `internal_publish` on older versions) and made a missing broker API log an ERROR plus a protocol-error metric instead of failing silently. Verified end-to-end on amqtt 0.11.3 (real broker + real client subscribe, retain stored).
- Fixed Modbus TCP server wrongly rejecting reads on stopped devices: removed the stale `"stop" → 0x04` exception mapping so stopped devices respond with last-known values (matches real PLC behaviour and the EdgeLite collection path); updated outdated adversarial unit tests accordingly.
- Added concurrency contract documentation to `ProtocolServer` base class (event-loop discipline, lifecycle idempotency, connection-handler robustness, write propagation, error reporting).
- Added `ProtocolErrorCategory` enum and `record_protocol_error()` hook; wired all 13 protocol servers' fallback exception handlers to emit `protoforge_protocol_errors_total{protocol, category}` metrics (NETWORK vs INTERNAL), exposed via `/metrics` in Prometheus format.

**CI & contract gating:**

- Removed `|| true` soft-fail from OpenAPI export/validation steps; added an OpenAPI drift gate that fails CI when `openapi.json` is not regenerated after API changes.
- Fixed all remaining ruff findings (bare except, SIM105/SIM108, B027, E402/E722/F841/E712); `ruff check protoforge/ tests/ scripts/` now passes clean.

**Housekeeping & storage:**

- Version aligned to 1.0.0 across `pyproject.toml`, `protoforge.__version__`, and `web/package.json`.
- Root directory cleaned: test outputs, coverage artifacts, screenshots, and OCR experiment files removed; `.gitignore` hardened against re-entry.
- `scripts/` triaged: 68 one-off debug/verification scripts removed; 35 operational tools retained (protocol `diag_*`, acceptance tests, CI-referenced scripts).
- Verified storage is already consolidated on a single SQLite database (`data/protoforge.db`) with Alembic migrations; archived 15 stale integration-test databases (43 files) from `data/` to `data/backups/stale-dbs/`.
- Confirmed `k8s/secrets.yaml` / Helm secrets contain only `CHANGE_ME` placeholders (no real credentials in repo).

## v0.1.7 — 2026-05-10

**Protocol startup port conflict fix:**

- Fixed protocol servers (OPC UA/S7/MC/HTTP) using `asyncio.create_task()` for background startup, where port binding failure still returned 200 OK. Now `start_protocol()` waits 0.3s to check server status, returning 503 if ERROR state detected immediately.
- Added configuration logging during protocol startup for easier port configuration troubleshooting.

**Protocol management UI fix:**

- Fixed missing "Stop All" button on protocol management page. Added `stopAll` function and `stoppingAll` state for one-click stop of all running protocols.

**i18n interpolation fix:**

- Fixed `{n}` not being replaced with actual numbers in confirmation dialogs (e.g., "Will start {n} protocols" showing raw template instead of "Will start 3 protocols"), unified to `{count}` with correct parameter passing.

**Health check fix:**

- Fixed Dashboard health check showing "Database: Operation Failed" / "Engine: Operation Failed", changed to more accurate "Error" label.

**Device recovery fix:**

- Fixed `create_device()` throwing `ValueError` when device already exists during startup recovery, added `allow_update` parameter for recovery scenarios.

## v0.2.0 — 2026-05-11

**P0 Security Fixes:**

- Replaced hardcoded default admin password "admin" with auto-generated random password when `PROTOFORGE_ADMIN_PASSWORD` is not set
- Fixed `_notifyUser()` parameter order error in api.js persistence warning
- Changed no-auth mode identity from admin to anonymous/viewer
- Fixed device point reading to prioritize protocol server data over memory simulation
- Fixed scenario rule actions not propagating to protocol server layer
- Fixed test report restoration from DB losing step details

**P1 Reliability Fixes:**

- Added ProtocolStatusEvent + WebSocket push for real-time protocol status updates
- Unified device creation behavior: all creation methods now auto-start devices
- Fixed ScenarioEditor rule data bidirectional mapping (edge double-click editing)
- Added device re-registration when protocol starts after device creation
- Replaced `dict[str, Any]` with Pydantic models in auth_routes.py
- Changed CORS default from `*` to `localhost:5173,localhost:3000`
- Added logging for silent exception fallbacks in auth.py, failover.py, rate_limit.py
- Added try/except for database connection failures with clear error messages
- Replaced Chinese error message matching in frontend with error_type/error_code matching
- Unified protocol port definitions: edgelite.py and constants.js now read from config
- Removed Chinese error messages from rate_limit.py 429 response
