"""点表导入引擎（v1.7.0）：厂商地址风格自动识别 + 协议兼容校验 + 冲突检测。

国内项目的起点几乎都是客户给的点表 Excel：西门子 DB 块、三菱 D 寄存器、
Modbus 4xxxx 偏移寻址、IEC 104 IOA、DL/T 645 数据标识……本模块把这些
"厂商方言"识别出来，校验与目标协议的兼容性，标记地址冲突与类型疑点，
让导入从逐行手敲变成"粘贴 → 预览 → 确认"。

设计原则：
  - 识别 ≠ 改写：识别出的地址原样传给协议服务器自己的解析器（它们才是
    权威，如 parse_modbus_address/_parse_s7_address），本模块只做
    风格判定、兼容性校验和冲突标记，不做有损转换；
  - Excel 支持可选：openpyxl 是 lazy import 的可选依赖（缺了 CSV 照用），
    避免给核心安装加重量级依赖。
"""

from __future__ import annotations

import base64
import io
import re
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# 地址风格识别
# ---------------------------------------------------------------------------

_STYLES = [
    # (style_id, 说明, 正则列表)  顺序即优先级（先specific后generic）
    ("siemens_db", "西门子 DB 块（DB1.DBD0 / DBX0.1 / DBB4 / DBW2）",
     [re.compile(r"^DB\d+\.DB[XBWD]\d+(\.\d+)?$", re.I)]),
    ("siemens_m", "西门子 M 区（M0.0 / MB0 / MW2 / MD4）",
     [re.compile(r"^M(\d+\.\d+|[BWD]\d+)$", re.I)]),
    ("siemens_i", "西门子输入区（I0.0 / IB0 / IW4 / ID8，E 同义）",
     [re.compile(r"^[IE](\d+\.\d+|[BWD]\d+)$", re.I)]),
    ("siemens_q", "西门子输出区（Q0.0 / QB0 / QW4 / QD8，A 同义）",
     [re.compile(r"^[QA](\d+\.\d+|[BWD]\d+)$", re.I)]),
    ("mitsubishi_xy", "三菱 X/Y（八进制/十六进制软元件，如 X10 / Y20）",
     [re.compile(r"^[XY][0-9A-Fa-f]+$")]),
    ("mitsubishi_dwr", "三菱 D/R/ZR/SD 数据寄存器（如 D100 / R50 / ZR10；W 区与欧姆龙歧义请用风格指定）",
     [re.compile(r"^(D|R|ZR|SD)\d+$", re.I)]),
    ("omron_cio", "欧姆龙 CIO 区（CIO0.00 / CIO10）",
     [re.compile(r"^CIO\d+(\.\d+)?$", re.I)]),
    ("omron_w", "欧姆龙 W/HR/AR 区（W10 / HR0.05）",
     [re.compile(r"^(W|HR|AR)\d+(\.\d+)?$", re.I)]),
    ("omron_dm", "欧姆龙 DM 区（DM100 / D100）",
     [re.compile(r"^(DM|D)\d+$", re.I)]),
    ("dlt645_di", "DL/T 645 数据标识（8 位 hex，如 00010000）",
     [re.compile(r"^(0x)?[0-9A-Fa-f]{8}$")]),
    ("modbus_prefix", "Modbus 前缀寻址（0x/1x/3x/4x + 序号）",
     [re.compile(r"^[0134]x\d+$", re.I)]),
    ("modbus_5digit", "Modbus 5 位 PLC 编址（40001-49999 等）",
     [re.compile(r"^[0-9]{5}$")]),
    ("modbus_6digit", "Modbus 6 位 PLC 编址（400001 起）",
     [re.compile(r"^[0-9]{6}$")]),
    ("iec104_ioa", "IEC 60870-5-104 信息对象地址（纯数字 IOA）",
     [re.compile(r"^[0-9]{1,8}$")]),
    ("generic_number", "通用数字地址（无前缀语义）",
     [re.compile(r"^[0-9]+$")]),
]

# 协议 → 兼容的地址风格（不在此列表 = 有疑点，dry_run 里可见）
_STYLE_COMPAT: dict[str, tuple[str, ...]] = {
    "modbus_tcp": ("modbus_prefix", "modbus_5digit", "modbus_6digit",
                   "generic_number", "siemens_m", "siemens_db"),
    "modbus_rtu": ("modbus_prefix", "modbus_5digit", "modbus_6digit",
                   "generic_number", "siemens_m", "siemens_db"),
    "s7": ("siemens_db", "siemens_m", "siemens_i", "siemens_q", "generic_number"),
    "s7plus": ("siemens_db", "siemens_m", "siemens_i", "siemens_q", "generic_number"),
    "mc": ("mitsubishi_dwr", "mitsubishi_xy", "generic_number"),
    "fins": ("omron_cio", "omron_w", "omron_dm", "generic_number"),
    "iec104": ("iec104_ioa", "generic_number"),
    "dlt645": ("dlt645_di", "generic_number"),
    "cjt188": ("generic_number",),
    "bacnet": ("generic_number",),
    "http": ("generic_number",),
    "mqtt": ("generic_number",),
}
_DEFAULT_COMPAT = ("generic_number",) + tuple(s for s, _, _ in _STYLES)

# 数据类型归一化：点表常见写法 → PointConfig.data_type
_DT_ALIASES: dict[str, str] = {
    "bool": "bool", "bit": "bool", "boolean": "bool", "开关": "bool", "布尔": "bool",
    "int16": "int16", "int": "int16", "short": "int16", "有符号": "int16",
    "uint16": "uint16", "uint": "uint16", "word": "uint16", "ushort": "uint16",
    "int32": "int32", "dint": "int32", "long": "int32",
    "uint32": "uint32", "dword": "uint32", "udint": "uint32",
    "float32": "float32", "float": "float32", "real": "float32", "single": "float32",
    "float64": "float64", "double": "float64", "lreal": "float64",
    "string": "string", "str": "string", "文本": "string", "字符串": "string",
}
_VALID_DT = {"bool", "int16", "uint16", "int32", "uint32", "float32", "float64", "string"}


def detect_address_style(address: str) -> str:
    """识别单个地址的厂商风格，返回 style_id；识别不出返回 "unknown"。"""
    addr = (address or "").strip()
    if not addr:
        return "unknown"
    for style_id, _desc, patterns in _STYLES:
        if any(p.match(addr) for p in patterns):
            return style_id
    return "unknown"


def style_display(style_id: str) -> str:
    for sid, desc, _ in _STYLES:
        if sid == style_id:
            return f"{style_id}（{desc}）"
    return style_id


def normalize_data_type(raw: str) -> tuple[str | None, str | None]:
    """归一化数据类型写法。返回 (规范类型, 警告)；无法识别返回 (None, 警告)。"""
    key = (raw or "").strip().lower()
    if not key:
        return None, "数据类型为空，默认按 float32 处理"
    if key in _DT_ALIASES:
        return _DT_ALIASES[key], None
    if key in _VALID_DT:
        return key, None
    # 容错：VB/组态常见写法
    if "float" in key or "real" in key:
        return "float32", f"数据类型 '{raw}' 按浮点(float32)处理"
    if "int" in key or key.isdigit():
        return "int16", f"数据类型 '{raw}' 按整型(int16)处理"
    return "float32", f"无法识别的数据类型 '{raw}'，已降级为 float32——请在预览中确认"


def is_style_compatible(style_id: str, protocol: str) -> bool:
    compat = _STYLE_COMPAT.get(protocol, _DEFAULT_COMPAT)
    return style_id in compat


# ---------------------------------------------------------------------------
# 点表解析
# ---------------------------------------------------------------------------

@dataclass
class ParsedPoint:
    """一行点表的解析结果。"""
    row: int
    name: str
    address: str
    data_type: str
    unit: str = ""
    description: str = ""
    access: str = "rw"
    style: str = "unknown"
    warnings: list[str] = field(default_factory=list)


@dataclass
class PointTableParseResult:
    """整张点表的解析结果（预览数据即此结构）。"""
    style_counts: dict[str, int] = field(default_factory=dict)
    points: list[ParsedPoint] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)       # 致命：该行丢弃
    warnings: list[str] = field(default_factory=list)     # 非致命：带行号提示
    conflicts: list[str] = field(default_factory=list)    # 地址冲突（同协议语义）
    duplicate_names: list[str] = field(default_factory=list)
    detected_styles: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors and not self.conflicts and bool(self.points)


def _extract_rows(content: str, file_format: str) -> tuple[list[dict[str, str]], list[str]]:
    """把 base64 Excel 解析为 {列名: 值} 行列表 + 警告（CSV 走 _rows_from_csv）。"""
    warnings: list[str] = []
    try:
        import openpyxl  # lazy：可选依赖
    except ImportError as e:
        raise ImportError(
            "Excel 解析需要 openpyxl：pip install 'protoforge[pointtable]'，"
            "或改用 CSV 粘贴导入") from e
    raw = base64.b64decode(content)
    wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    ws = wb.active
    rows_raw = [[("" if c is None else str(c)).strip() for c in row]
                for row in ws.iter_rows(values_only=True)]
    wb.close()
    if not rows_raw:
        return [], ["Excel 首个工作表为空"]
    header = [str(h or "").strip() for h in rows_raw[0]]
    rows = [dict(zip(header, r)) for r in rows_raw[1:] if any(v for v in r)]
    return rows, warnings


def _rows_from_csv(content: str) -> tuple[list[dict[str, str]], list[str]]:
    """CSV/TSV 文本 → 行字典列表（与 Excel 路径统一返回形态）。"""
    import csv as _csv
    warnings: list[str] = []
    text = content.replace("\r\n", "\n").replace("\r", "\n")
    sample = text[:4096]
    dialect = "excel-tab" if sample.count("\t") > sample.count(",") else "excel"
    rows: list[dict[str, str]] = []
    reader = _csv.DictReader(io.StringIO(text), dialect=dialect)
    for raw_row in reader:
        clean: dict[str, str] = {}
        for k, v in raw_row.items():
            if k is None:
                if any((v or []) if isinstance(v, list) else [v or ""]):
                    warnings.append(f"CSV 行含多余列（分隔符不匹配？）: {v}")
                continue
            clean[(k or "").strip()] = (v or "").strip()
        if any(clean.values()):
            rows.append(clean)
    return rows, warnings


# 列名别名（中英文点表常见表头 → 规范字段）
COLUMN_ALIASES: dict[str, list[str]] = {
    "name": ["name", "point_name", "点名", "名称", "位号", "变量名", "tag", "point", "数据项", "参数"],
    "address": ["address", "addr", "地址", "寄存器地址", "modbus地址", "偏移", "数据标识", "di"],
    "data_type": ["data_type", "type", "类型", "数据类型", " datatype"],
    "unit": ["unit", "单位", "工程单位"],
    "description": ["description", "desc", "描述", "说明", "备注", "注释"],
    "access": ["access", "读写", "访问", "权限", "rw"],
}


def _map_columns(rows: list[dict[str, str]]) -> tuple[dict[str, str], list[str]]:
    """把点表的表头映射到规范字段名。返回 (规范字段→实际表头, 未识别表头警告)。"""
    mapping: dict[str, str] = {}
    unknown: list[str] = []
    lower_rows_keys = set()
    for r in rows:
        lower_rows_keys.update(k.lower() for k in r)
    for field, aliases in COLUMN_ALIASES.items():
        for r_key in lower_rows_keys:
            if r_key in [a.lower() for a in aliases]:
                mapping[field] = r_key
                break
    # 未能映射的字段提示
    all_known = {k.lower() for aliases in COLUMN_ALIASES.values() for k in aliases}
    for r_key in sorted(lower_rows_keys):
        if r_key not in all_known:
            unknown.append(r_key)
    return mapping, unknown


def parse_point_table(
    content: str,
    file_format: str = "csv",
    protocol: str = "modbus_tcp",
    style_hint: str = "",
) -> PointTableParseResult:
    """解析点表文本/Excel，产出预览结果（映射、告警、冲突）。

    :param content: CSV/TSV 文本，或 base64 编码的 xlsx（file_format="excel"）
    :param protocol: 目标协议（用于风格兼容性校验与冲突检测语义）
    :param style_hint: 强制指定地址风格（跳过自动识别），如 "siemens_db"
    """
    result = PointTableParseResult()

    if file_format == "excel":
        rows, warnings = _extract_rows(content, "excel")
        result.warnings.extend(warnings)
    else:
        rows, warnings = _rows_from_csv(content)
        result.warnings.extend(warnings)

    if not rows:
        result.errors.append("点表为空：未解析到任何数据行")
        return result

    mapping, unknown_cols = _map_columns(rows)
    if unknown_cols:
        result.warnings.append(f"未识别的表头列（已忽略）: {', '.join(unknown_cols)}")
    if "name" not in mapping or "address" not in mapping:
        result.errors.append(
            "点表缺少必需列：需要 点名(name) 与 地址(address) 列"
            f"，实际表头: {', '.join(sorted({k for r in rows for k in r}))}")
        return result

    # 逐行解析
    seen_names: dict[str, int] = {}
    style_of_row: list[tuple[int, str]] = []
    for idx, row in enumerate(rows, start=2):  # Excel/CSV 第 1 行是表头
        name = row.get(mapping["name"], "")
        address = row.get(mapping["address"], "")
        if not name or not address:
            result.warnings.append(f"第 {idx} 行：点名或地址为空，已跳过")
            continue

        pt = ParsedPoint(row=idx, name=name, address=address, data_type="float32")

        # 数据类型
        raw_dt_col = mapping.get("data_type")
        if raw_dt_col:
            dt, dt_warn = normalize_data_type(row.get(raw_dt_col, ""))
            if dt_warn:
                pt.warnings.append(dt_warn)
            if dt:
                pt.data_type = dt

        # 可选列
        if unit_col := mapping.get("unit"):
            pt.unit = row.get(unit_col, "")
        if desc_col := mapping.get("description"):
            pt.description = row.get(desc_col, "")
        if access_col := mapping.get("access"):
            raw_access = row.get(access_col, "rw").lower()
            pt.access = "r" if raw_access in ("r", "ro", "read", "只读", "读") else "rw"

        # 地址风格
        if style_hint:
            pt.style = style_hint
        else:
            pt.style = detect_address_style(address)
        style_of_row.append((idx, pt.style))
        result.style_counts[pt.style] = result.style_counts.get(pt.style, 0) + 1

        # 重复点名
        if name.lower() in seen_names:
            result.duplicate_names.append(f"第 {seen_names[name.lower()]} 行与第 {idx} 行点名重复: {name}")
        seen_names[name.lower()] = idx

        result.points.append(pt)

    # 主导风格 + 兼容性校验
    if result.points:
        dominant = max(result.style_counts, key=lambda s: result.style_counts[s])
        result.detected_styles = [s for s, c in result.style_counts.items() if c > 0]
        if not style_hint and len(result.detected_styles) > 1:
            result.warnings.append(
                "检测到多种地址风格混合: "
                + "; ".join(f"{s}×{c}" for s, c in sorted(result.style_counts.items()))
                + "——请确认是否为同一厂商点表")
        if not is_style_compatible(dominant, protocol):
            result.warnings.append(
                f"主导地址风格 {style_display(dominant)} 与目标协议 '{protocol}' 的"
                "常用寻址不一致——地址将原样传给协议解析器，请逐条确认解析结果")
        for pt in result.points:
            if pt.style != "unknown" and not is_style_compatible(pt.style, protocol):
                pt.warnings.append(f"地址风格 {pt.style} 与协议 '{protocol}' 常用寻址不一致")

    # 冲突检测
    result.conflicts = detect_conflicts(result.points, protocol)
    return result


def detect_conflicts(points: list[ParsedPoint], protocol: str) -> list[str]:
    """协议语义下的地址冲突检测。

    Modbus 复用 find_overlapping_points（寄存器范围重叠语义）；
    其余协议做"同地址多点"检测（同地址双点会互相覆盖）。
    """
    if protocol in ("modbus_tcp", "modbus_rtu"):
        from protoforge.models.device import PointConfig
        from protoforge.protocols.modbus._common import find_overlapping_points
        pc = [PointConfig(name=p.name, address=p.address, data_type=p.data_type)
              for p in points]
        return find_overlapping_points(pc)

    conflicts: list[str] = []
    by_addr: dict[str, list[str]] = {}
    display: dict[str, str] = {}
    for p in points:
        key = p.address.strip().lower()
        by_addr.setdefault(key, []).append(f"'{p.name}'(第{p.row}行)")
        display.setdefault(key, p.address.strip())
    for key, names in by_addr.items():
        if len(names) > 1:
            conflicts.append(f"地址 {display[key]} 被 {len(names)} 个点位使用: {', '.join(names)}"
                             "——同地址多点会互相覆盖")
    return conflicts


# ---------------------------------------------------------------------------
# 导入模板（解析规则复用）
# ---------------------------------------------------------------------------

def make_import_template(name: str, protocol: str, style_hint: str = "",
                         column_mapping: dict[str, str] | None = None) -> dict[str, Any]:
    """把一次成功的导入配置固化为可复用模板（同客户同格式二次导入零配置）。"""
    return {
        "name": name,
        "protocol": protocol,
        "style_hint": style_hint,
        "column_mapping": column_mapping or {},
    }
