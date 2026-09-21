/**
 * 校验 web/src/utils.js 的 Modbus 默认地址分配逻辑（nextFreeModbusAddress 等）。
 *
 * 背景：编辑设备/模板"添加测点"的默认地址若与既有多字节点位重叠，
 * 后端保存时会被 400 "检测到同设备点位地址重叠" 拦截（表现为"更新失败"）。
 * 本脚本回归验证默认地址计算在各类典型场景下不产生重叠。
 *
 * 运行: node scripts/validate-point-address.mjs
 * 退出码: 0=全部通过, 1=存在失败
 */
import { nextFreeModbusAddress, nextPointName, parseModbusPointArea } from "../src/utils.js";

let failed = 0;

function check(label, actual, expected) {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  if (!ok) failed++;
  console.log(`${ok ? "PASS" : "FAIL"} ${label}: got=${JSON.stringify(actual)} expected=${JSON.stringify(expected)}`);
}

// --- parseModbusPointArea ---
check("parse plain numeric float32 -> holding", parseModbusPointArea("3", "float32"), { area: "holding", addr: 3 });
check("parse plain numeric bool -> coil", parseModbusPointArea("3", "bool"), { area: "coil", addr: 3 });
check("parse C prefix", parseModbusPointArea("C5", "bool"), { area: "coil", addr: 5 });
check("parse COIL prefix", parseModbusPointArea("COIL5", "bool"), { area: "coil", addr: 5 });
check("parse HR prefix", parseModbusPointArea("HR10", "float32"), { area: "holding", addr: 10 });
check("parse IR prefix", parseModbusPointArea("IR8", "float32"), { area: "input", addr: 8 });
check("parse DI prefix", parseModbusPointArea("DI3", "bool"), { area: "discrete", addr: 3 });
check("parse 4X prefix", parseModbusPointArea("4X100", "float32"), { area: "holding", addr: 100 });
check("parse 0X prefix", parseModbusPointArea("0X10", "bool"), { area: "coil", addr: 10 });
// 6 位 PLC 记法从 40001 起算（与后端 parse_modbus_address 一致：40001 → 0）
check("parse 6-digit 400100 -> 99", parseModbusPointArea("400100", "float32"), { area: "holding", addr: 99 });
check("parse 6-digit 300100 -> 99 input", parseModbusPointArea("300100", "float32"), { area: "input", addr: 99 });
check("parse garbage -> null", parseModbusPointArea("garbage", "float32"), null);
check("parse empty -> null", parseModbusPointArea("", "float32"), null);

// --- nextFreeModbusAddress ---
// 内置温湿度传感器模板 (0/2 float32, 4/5 bool)：bool 占线圈区，float32 落保持区 4
const tempTemplate = [
  { name: "temperature", address: "0", data_type: "float32" },
  { name: "humidity", address: "2", data_type: "float32" },
  { name: "alarm_temp_high", address: "4", data_type: "bool" },
  { name: "alarm_humidity_high", address: "5", data_type: "bool" },
];
check("temp template next float32 (expect 4)", nextFreeModbusAddress(tempTemplate, "float32"), "4");
check("temp template next bool (expect 0, coil 区 0~3 空闲)", nextFreeModbusAddress(tempTemplate, "bool"), "0");

// 连续 float32 0/2/4 → 下一个空闲 6（旧默认 points.length=3 会与 [2~3] 重叠）
check("consecutive float32 (expect 6)", nextFreeModbusAddress([
  { name: "a", address: "0", data_type: "float32" },
  { name: "b", address: "2", data_type: "float32" },
  { name: "c", address: "4", data_type: "float32" },
], "float32"), "6");

// 混合前缀: HR0[0~1] + 400002(->1)[1~2] → 空闲 3
check("mixed prefixes (expect 3)", nextFreeModbusAddress([
  { name: "m1", address: "HR0", data_type: "float32" },
  { name: "m2", address: "400002", data_type: "float32" },
  { name: "m3", address: "C10", data_type: "bool" },
], "float32"), "3");

// bool 点位走线圈区独立分配（C10 占 10，0~9 空闲 → 取 0）
check("bool in coil area (expect 0)", nextFreeModbusAddress([
  { name: "m3", address: "C10", data_type: "bool" },
], "bool"), "0");

// 空列表 / 无法解析的地址不参与
check("empty points (expect 0)", nextFreeModbusAddress([], "float32"), "0");
check("unparseable addresses ignored (expect 0)", nextFreeModbusAddress([
  { name: "x", address: "garbage", data_type: "float32" },
  { name: "y", address: "/sensor/temp", data_type: "float32" },
], "float32"), "0");

// --- nextPointName ---
check("next name (expect point_4)", nextPointName([{ name: "point_1" }, { name: "point_2" }, { name: "point_3" }]), "point_4");
check("name uses first free (expect point_4)", nextPointName([{ name: "point_1" }, { name: "point_5" }, { name: "point_2" }]), "point_4");

if (failed > 0) {
  console.error(`\n${failed} check(s) FAILED`);
  process.exit(1);
}
console.log("\nAll point-address checks passed");
