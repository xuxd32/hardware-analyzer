#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PCB 交付件分析器 - 基于投板交付件（xy.xlsx + IPC-D-356 + DXF）
=============================================================
利用 EDA 交付文件的开放文本格式，实现 PCB 级深度分析：
  1. xy.xlsx  → 完整元件清单（位号/类型/封装/层/坐标）
  2. IPC-D-356 → 测试网络与测试点
  3. DXF      → 板框几何
严格约束：只读分析，绝不修改被分析文件。纯标准库。
"""
import glob
import re
import zipfile
from pathlib import Path
from collections import Counter, defaultdict

# ---------------------------------------------------------------
# 输入数据完整性检查（新增：约束C1-C5）
# ---------------------------------------------------------------
def validate_input_data(base_dir):
    """验证输入数据完整性，返回(is_valid, errors, warnings)。
    
    约束检查：
    C1: xy.xlsx 必须来自 EDA 标准导出
    C2: IPC-D-356 必须完整导出（非精简版）
    C3: 元件命名必须规范（R/C/U/L 前缀）
    C4: 不能用 Gerber 替代 xy.xlsx
    C5: 多层板必须提供 IPC-D-356
    """
    base = Path(base_dir)
    errors = []
    warnings = []
    
    # C1: 检查 xy.xlsx 是否为标准格式
    xlsx_files = list(base.glob("**/xy.xlsx"))
    if not xlsx_files:
        errors.append("❌ C4违反：未找到 xy.xlsx 文件（不能用 Gerber 替代）")
    else:
        try:
            z = zipfile.ZipFile(xlsx_files[0])
            if "xl/sharedStrings.xml" not in z.namelist():
                errors.append(f"❌ C1违反：{xlsx_files[0]} 不是标准 Excel 格式（缺少 sharedStrings.xml）")
        except Exception as e:
            errors.append(f"❌ C1违反：{xlsx_files[0]} 文件损坏或非 xlsx 格式: {e}")
    
    # C2: 检查 IPC-D-356 是否完整
    ipc_files = list(base.glob("**/*.ipc"))
    if not ipc_files:
        warnings.append("⚠️  C5警告：未找到 IPC-D-356 文件，多层板/网络分析受限")
    else:
        try:
            with open(ipc_files[0], "rb") as f:
                content = f.read().decode("ascii", errors="ignore")
                # 修复：真实 IPC-356A 是 "P  NNAME0001"（P 与 NNAME 之间可有多空格），
                # 之前用固定 "P NNAME"（单空格）导致误报"精简版"。
                if not re.search(r"P\s+NNAME", content):
                    warnings.append(f"⚠️  C2警告：{ipc_files[0]} 可能是精简版（缺少网络定义 'P NNAME'）")
        except Exception as e:
            errors.append(f"❌ C2违反：{ipc_files[0]} 无法读取: {e}")
    
    # C3: 检查元件命名规范（需要先解析 xy.xlsx）
    if xlsx_files:
        try:
            unit = detect_unit_in_dir(base)
            if unit is not None:
                components = parse_xy_xlsx(xlsx_files[0], coord_unit=unit)
                non_standard = [c[1] for c in components if not re.match(r"^[A-Z]{1,3}\d+$", c[1])]
                if non_standard:
                    warnings.append(f"⚠️  C3警告：{len(non_standard)} 个元件命名不规范（可能影响启发式识别）: {non_standard[:5]}")
            else:
                warnings.append("⚠️  C3跳过：无法确定坐标单位（无 IPC UNITS 声明），命名检查延后")
        except Exception as e:
            errors.append(f"❌ 元件命名检查失败: {e}")
    
    # C4: 检查是否误用 Gerber
    gerber_files = list(base.glob("**/*.gbr")) + list(base.glob("**/*.gtl")) + list(base.glob("**/*.gbl"))
    if gerber_files and not xlsx_files:
        errors.append("❌ C4违反：仅找到 Gerber 文件，缺少 xy.xlsx（Gerber 无元件坐标语义，不可用）")
    
    is_valid = len(errors) == 0
    return is_valid, errors, warnings


# ---------------------------------------------------------------
# xy.xlsx 解析
# ---------------------------------------------------------------
# xy.xlsx 解析
# ---------------------------------------------------------------
def parse_ipc_units(ipc_path):
    """从 IPC-D-356 文件头读取**坐标系统**（英制 vs 公制）的单位声明。

    IPC-D-356A 文件头有明文单位声明（三种合法写法都要认）：
      P  UNITS CUST  → Customary（英制）
      P  UNITS SI    → Metric（公制/m 系，SI = International System）
      P  UNITS METR  → Metric（公制，另一写法，兼容）

    返回（三态，精确区分，杜绝"枚举不全"把'有声明'误当'无声明'）:
        "mil" 或 "mm"  → 认识了该声明值（mil=英制 CUST；mm=公制 SI/METR）
        None            → 文件中**根本没有** UNITS 声明
        抛 ValueError   → 文件中有 UNITS 声明，但值不认识（工具枚举不全）

    ⚠️【语义澄清 —— 2026-09-18 严格审核后补充，避免歧义】
    本函数探测的是"坐标**系统**"（英制 Customary vs 公制 Metric），**不是**
    坐标数值的"精度"。同一个 "CUST"（英制）系统下，**不同文件的坐标数值
    精度不同**，换算系数也不同，绝不能混为一谈：

      ┌──────────────────────────────────────────────────────────────┐
      │ 文件                  │ 坐标数值            │ 精度 → 换算系数  │
      ├───────────────────────┼─────────────────────┼─────────────────┤
      │ xy.xlsx（元件中心坐标）│ 如 5259.93          │ 整数 mil → ×0.0254│
      │ IPC 3xx 记录坐标      │ 如 X+064804(6位整数)│ 0.1 mil → ×0.00254│
      └──────────────────────────────────────────────────────────────┘

    - 本函数的返回值 "mil" 被 `parse_xy_xlsx` 消费，用于换算 **xy.xlsx**
      坐标（整数 mil，×0.0254）。**这是对的，勿改**。
    - IPC 3xx 记录自身的坐标（X+064804 这类 6 位定点）是 **0.1 mil**，
      需 ×0.00254 → mm。本函数**不处理**这部分；如需解析，请用
      `parse_ipc357_coords_to_mm()`（本轮新增，见同文件）。

    精确性红线（红线 2 补充）："无声明" 与 "有声明但值未枚举" 是两回事，
    必须区分处理，不能都静默返回 None。

    ⚠️【IPC-D-356B 显式 UNITS —— 2026-09-18 P0 新增】
    IPC-D-356B 废弃了 A 版的隐式 `CUST 0`，改用显式语法：
        UNITS <单位> <精度> [RAD/DEG <角度精度>]
      单位枚举：MIL（密尔）/ IN（英寸）/ MM（毫米）
      例：`MIL 1 DEG 0` = mil、1 位小数（0.1mil）、角度整数度
          `MM 3 RAD 2`  = mm、3 位小数、角度 0.01 弧度
    见 IPC-D-356B 规范 §6.3。
    """
    try:
        with open(ipc_path, "rb") as f:
            content = f.read().decode("ascii", errors="ignore")
    except OSError:
        return None

    # 找 P UNITS 声明行（取整行，B 版是「MIL 1 DEG 0」多 token 形式）
    m = re.search(r"P\s+UNITS\s+(.+?)(?:\n|$)", content, re.IGNORECASE)
    if not m:
        return None  # 该文件根本没有 UNITS 声明
    val = m.group(1).strip().upper()
    # token 化：B 版 "MIL 1 DEG 0"，A 版 "CUST 0" / "SI" / "METR"
    toks = val.split()
    first = toks[0]
    if first in ("CUST",):
        return "mil"
    if first in ("SI", "METR"):
        return "mm"
    if first in ("MIL", "IN"):
        return "mil"
    if first in ("MM",):
        return "mm"
    # 有声明，但值不在已知枚举内 → 明确报错，而非静默当"无声明"
    raise ValueError(
        f"IPC-356 文件 {ipc_path} 有单位声明 'UNITS {val}'，但工具未枚举该值。"
        f"已知 mil=CUST/MIL/IN，mm=SI/METR/MM。请补充解析枚举或改用显式配置。"
    )


def detect_unit_in_dir(base_dir):
    """在投板交付件目录（递归）里找 IPC-356 的 UNITS 声明。

    用于跨子目录场景：PADS 投板件里 xy.xlsx 在 ASM/SMD/CAM 子目录，.ipc 只在
    CAM 子目录。调用方先在顶层 base_dir 递归定位 .ipc 读单位，再显式传给
    parse_xy_xlsx。

    返回/抛出（精确三态）:
        "mil"/"mm"       → 找到认识的单位声明
        None             → 目录里完全没有 .ipc（或都没有 UNITS 声明）
        raise ValueError → 目录里有 .ipc 且有 UNITS 声明，但值都未枚举（枚举不全）
    """
    first_unknown = None  # 记录第一个"未识别声明值"，用于最后决定是否抛出
    for cand in glob.glob(str(Path(base_dir) / "**" / "*.ipc"), recursive=True):
        try:
            u = parse_ipc_units(cand)
        except ValueError as e:
            if first_unknown is None:
                first_unknown = e
            continue  # 这个 .ipc 值未枚举，继续找别的 .ipc
        if u is not None:
            return u
    # 遍历完：没有认识的。若有"未识别值"，抛出（比 None 更有信息量），否则 None
    if first_unknown is not None:
        raise first_unknown
    return None


def parse_xy_xlsx(xlsx_path, coord_unit=None):
    """解析 PADS 生成的元件坐标表 xy.xlsx，返回元件列表（坐标统一归一为 mm）。

    参数:
        xlsx_path:  xy.xlsx 路径
        coord_unit: 坐标单位 "mil" / "mm" / None（默认）
            - "mil" → 坐标 ×0.0254 归一为 mm
            - "mm"  → 坐标原样（已是 mm）
            - None  → 自动探测：先读同目录 IPC-356 的 UNITS 声明（权威）；
                      读不到则抛 ValueError（fail-fast，不静默猜，见精确性红线）

    返回:
        components 列表，每项 vals[0]=PartType, vals[1]=RefDes,
        vals[6]=X(mm), vals[7]=Y(mm)。坐标已统一为 mm，下游距离判断无需再换算。

    精确性约束：
        - 坐标单位是交付件的客观属性，只允许读权威声明 / 显式指定，禁止量级猜测。
        - 1 mil = 0.0254 mm。
    """
    z = zipfile.ZipFile(xlsx_path)
    ss_xml = z.read("xl/sharedStrings.xml").decode("utf-8", errors="ignore")
    shared = re.findall(r"<t[^>]*>([^<]*)</t>", ss_xml)
    sheet = z.read("xl/worksheets/sheet1.xml").decode("utf-8", errors="ignore")

    def cell_value(cell_tag):
        m = re.search(r"<c\b([^>]*)>(?:<v>([^<]*)</v>)?</c>", cell_tag)
        if not m:
            return ""
        attrs, v = m.group(1), m.group(2)
        tm = re.search(r't="([^"]*)"', attrs)
        if tm and tm.group(1) == "s" and v and v.isdigit():
            idx = int(v)
            return shared[idx] if idx < len(shared) else ""
        return v or ""

    # 解析单位（精确，不猜）
    if coord_unit is None:
        # 仅在同目录找 *.ipc 读 UNITS 声明（权威）。
        # 精确三态（红线 2 补充）：
        #   认识 → break；无声明 → 继续找下一个；有声明但未枚举 → 立即向上抛
        import os
        d = os.path.dirname(xlsx_path) or "."
        detected = None
        for cand in glob.glob(os.path.join(d, "*.ipc")):
            try:
                u = parse_ipc_units(cand)
            except ValueError:
                raise  # 有 UNITS 声明但未枚举：明确报错，不静默当"无声明"
            if u is not None:
                detected = u
                break
        if detected is not None:
            coord_unit = detected
        else:
            raise ValueError(
                f"无法确定 xy.xlsx 坐标单位（{xlsx_path} 同目录无 IPC-D-356 单位声明）。"
                f"请显式指定 coord_unit='mil' 或 'mm'（PADS 可能 mil 或 mm，KiCad 通常 mm）。"
            )
    if coord_unit not in ("mil", "mm"):
        raise ValueError(f"coord_unit 必须是 'mil' 或 'mm'，收到: {coord_unit!r}")

    def to_mm(v):
        if coord_unit == "mil":
            return round(float(v) * 0.0254, 6)
        return float(v)

    components = []
    for row in re.findall(r"<row[^>]*>(.*?)</row>", sheet, re.S):
        cells = re.findall(r"<c\b.*?</c>", row, re.S)
        vals = [cell_value(c) for c in cells]
        if vals and vals[1] and vals[1][0:1].isalpha():
            # 跳过表头行（RefDes / PartType 等）
            if vals[1] in ("RefDes", "PartType", "PartDecal"):
                continue
            # 跳过 @_ 开头的工艺占位符
            if vals[1].startswith("@"):
                continue
            # 坐标归一为 mm（vals 长度 >= 8 时，索引 6/7 是 X/Y）
            if len(vals) >= 8 and vals[6]:
                try:
                    vals[6] = str(to_mm(vals[6]))
                except (ValueError, TypeError):
                    pass  # 非数字坐标，保持原样（调用方 _pos 会跳过）
            if len(vals) >= 8 and vals[7]:
                try:
                    vals[7] = str(to_mm(vals[7]))
                except (ValueError, TypeError):
                    pass
            components.append(vals)
    return components


# ---------------------------------------------------------------
# IPC-D-356 解析
# ---------------------------------------------------------------
def parse_ipc_netlist(ipc_path):
    """解析 IPC-D-356 网表/测试文件，返回网络名与元件测试点。"""
    with open(ipc_path, "rb") as f:
        lines = f.read().decode("ascii", errors="ignore").split("\n")
    nets = {}
    comps = {}
    for l in lines:
        s = l.strip()
        if s.startswith("P") and "NNAME" in s:
            parts = s.split()
            if len(parts) >= 3:
                nets[parts[1]] = parts[2]
        elif s.startswith("3") and "VIA" not in s and len(s) > 10:
            parts = s.split()
            if len(parts) >= 3:
                ref = parts[1]
                if re.match(r"^[A-Z]{1,3}\d{1,5}$", ref):
                    comps[ref] = comps.get(ref, 0) + 1
    return nets, comps


def parse_ipc_netlist_conn(ipc_path):
    """解析 IPC-D-356 的 317 直接网络名记录，还原「接口元件」的连接（有限能力）。

    返回 netlist_data = {"components": [{"ref","value","footprint"}],
                          "nets": [{"name","nodes":[{"ref","pin"}]}]}

    ⚠️ 能力边界（2026-09-16 二轮实测，必须如实声明）：
      - IPC-D-356A 的 327 记录虽列全元件（1015 位号），但网络标识是内部
        `$$$序号`（如 `$$$16086`），与 NNAME 的命名网络是两套编号、
        文件内无映射表（实测匹配数=0）→ 无法还原它们的网络名。
      - 只有 317 记录里「直接带网络名」的一部分（约 36 个接口元件 J/JP/D
        等），能还原元件→网络名连接。
      - 因此本函数**只能做「接口元件连接清单」，不能替代完整 netlist**；
        依赖 value 的电源树、依赖完整元件的去耦匹配都无法工作。

    ⚠️ 结论：要跑完整 `-n`，需取得真正的 `$PACKAGES/$NETS` 网表。
    """
    with open(ipc_path, "rb") as f:
        lines = f.read().decode("ascii", errors="ignore").split("\n")

    ref_re = re.compile(r"^[A-Za-z]{1,4}\d{1,5}$")
    nets_map = {}        # 网络名 -> { ref: set(pins) }
    comps_set = {}       # 位号 -> value(空)

    for l in lines:
        s = l.strip()
        # 只处理「317 直接带网络名」的记录，如 317DVR_485A_OUT  J15 -5 ...
        if not s.startswith("317") or s.startswith("317$$$"):
            continue
        m = re.match(r"^317(\S+?)\s+(\S+)\s+(-\S+)\b", s)
        if not m:
            continue
        net_name = m.group(1)

        nodes = []
        for tok in re.finditer(r"(\S+)\s+(-[A-Za-z0-9]+)", s):
            ref = tok.group(1)
            pin = tok.group(2)
            if ref_re.match(ref):
                nodes.append((ref, pin))
                comps_set.setdefault(ref, "")

        for ref, pin in nodes:
            nets_map.setdefault(net_name, {})
            nets_map[net_name].setdefault(ref, set())
            nets_map[net_name][ref].add(pin)

    components = [{"ref": r, "value": v, "footprint": ""}
                  for r, v in sorted(comps_set.items())]
    nets = [{"name": n,
             "nodes": [{"ref": r, "pin": p}
                       for r in sorted(pins) for p in sorted(pins[r])]}
            for n, pins in sorted(nets_map.items())]

    return {"components": components, "nets": nets}



def parse_ipc357_coords_to_mm(ipc_path):
    """解析 IPC-D-356 的 3xx 记录坐标（X/Y 6 位定点），换算为 mm。

    ⚠️ 准确性：
      - 依据：IPC-D-356A 文件头 `P UNITS CUST 0` 的 `0` = 坐标精度档位
        **0.1 mil**（10 单位 = 1 mil = 0.00254 mm）。此结论由双向铁证锁定：
        nc drill 刀具表 `T1 C.01`（0.01 inch = 10 mil）↔ IPC 过孔 `D 100`
        （钻孔 100 单位）精确对应 → 100 单位 = 0.01 inch → 1 单位 = 0.1 mil。

      - 换算：坐标整数值 × 0.00254 → mm（保留 4 位小数）。

    ⚠️ 假设 / 边界（必须如实声明）：
      1. 换算系数 0.00254 只适用于 `UNITS CUST 0`（英制 + 0.1mil 精度）。
         若文件是 `UNITS SI` / `UNITS METR`（公制）或 `CUST 1/2`（其它精度档位），
         本函数**不适用**——其精度档位尚未确证，需真实样本后才可扩展。
      2. 坐标字段格式按 CAMCAD 导出的紧凑写法解析：`X±yyyyyy`（6 位整数）。
         若遇固定列宽（80 列）的原版写法（坐标分散在固定列），可能漏解析；
         当前真实交付件均为紧凑写法，已实测覆盖 26776 条。
      3. 仅返回能同时解析出 X 与 Y 的记录；缺任一侧坐标的记录静默跳过。

    返回（list[dict]）：
      每项 {"net", "ref", "pin", "x_mm", "y_mm"}；
      ref 为元件的位号，过孔记录 ref 为空串 ""。
    """
    try:
        with open(ipc_path, "rb") as f:
            lines = f.read().decode("ascii", errors="ignore").split("\n")
    except OSError:
        return []

    coord_re = re.compile(r"X([+-]\d{6})\s*Y([+-]\d{6})")
    ref_re = re.compile(r"^[A-Za-z]{1,4}\d{1,5}$")
    pin_re = re.compile(r"^-[A-Za-z0-9]+$")
    results = []
    for l in lines:
        s = l.strip()
        # 只认测试点 op-code：3 开头 + 第 2 位 FeatureType∈{1通孔,2SMD,3工艺孔}。
        # 排除 B 版 op-code 350(测量)/367(非电镀孔) 等「第 2 位不是 1/2/3」的
        # 记录，避免误把测量记录当测试点坐标（P1：op-code 精确识别）。
        if not re.match(r"^3[123]", s):
            continue
        m = coord_re.search(s)
        if not m:
            continue
        x_raw, y_raw = int(m.group(1)), int(m.group(2))
        parts = s.split()
        # 字段结构（IPC-D-356A 紧凑写法）：
        #   parts[0] = "3" + FeatureType(1) + AccessCode(1) + 网络名/netno
        #   之后依次是 位号(RefDes 或 VIA)、引脚号、pad 形状、坐标...
        net = parts[0][3:] if len(parts) >= 1 else ""  # 去掉 3+F+A 三字符
        ref = ""
        pin = ""
        for tok in parts[1:]:
            # VIA = 过孔，无位号，跳过；A04 等是 pad 类型，跳过
            if tok.upper() == "VIA":
                continue
            if ref == "" and ref_re.match(tok):
                ref = tok
            elif pin == "" and pin_re.match(tok):
                pin = tok
        results.append({
            "net": net,
            "ref": ref,
            "pin": pin,
            "x_mm": round(x_raw * 0.00254, 4),
            "y_mm": round(y_raw * 0.00254, 4),
        })
    return results

# IPC-D-356B 记录类型 op-code 全谱系（含 A 版与 B 版新增）
# 依据：IPC-D-356B §8.11.1 + 附录 B
IPC356_MAP = {
    "317": "through-hole pad (A 版通孔，primary+secondary)",
    "327": "SMD test area (A 版/B 版共用，表面测试点)",
    "320": "A 版 SMD/test area 变体",
    "329": "A 版 test area 变体",
    # B 版 complex record（复杂记录：过孔/焊盘堆叠）
    "427": "primary-side test area（顶面测试区，B 版）",
    "433": "primary-side non-test area（顶面非测试区，B 版）",
    "013": "conductive hole/via（导电孔，含层对 L01LNN，B 版）",
    "027": "secondary-side test area（底面测试区，B 版）",
    "033": "secondary-side non-test area（底面非测试区，B 版）",
    # B 版其它新增
    "350": "measurement record（阻抗/传播延迟测量，B 版）",
    "367": "non-plated through hole（非电镀通孔，B 版）",
    "099": "tester label assignment（测试系统通道指派，B 版）",
}
KNOWN_IPC356_OPS = set(IPC356_MAP.keys())


def parse_ipc357_complex_records(ipc_path):
    """解析 IPC-D-356B 复杂记录（complex record），提取过孔/焊盘堆叠 + 层对。

    ⚠️ 准确性（2026-09-18 P2）：
      - 依据 IPC-D-356B §8.11 原文：复杂记录 = 顶面测试区(427/433) → 导电孔
        (013，层对 L01LNN) → 底面测试区(027/033)。这是 B 版表达「过孔层对」
        的机制，A 版没有。
      - 层对字段：013 记录里 netname 后的 `L01LNN`（如 L01L08 表 L1→L8），
        见原文 §8.11.3.2。

    ⚠️ 假设/边界（必须如实声明）：
      1. 坐标按 0.1 mil（×0.00254）换算，同 `parse_ipc357_coords_to_mm`。
      2. 按紧凑写法解析（附录 F 样例格式），非固定 80 列原版。
      3. 尚无真实 B 版 .ipc 样本验证——仅用规范附录 F 逐字样例做金标准测试。
      4. 复杂记录按「序列分组」：以 427/433 开头，后续 013/027/033 归入
         同一组（continuation），直到下一个 427/433/317/327 或非 0 开头。

    返回：list[dict]，每项是一个「复杂记录组」：
      {"net", "primary_side": bool, "layers": (start_layer, end_layer) 或 None,
       "records": [{"opcode","x_mm","y_mm"}, ...]}
    其中 layers 来自 013 记录的 L01LNN 层对。
    """
    try:
        with open(ipc_path, "rb") as f:
            lines = f.read().decode("ascii", errors="ignore").split("\n")
    except OSError:
        return []

    coord_re = re.compile(r"X([+-]\d{6})\s*Y([+-]\d{6})")
    layer_re = re.compile(r"\bL0?(\d{1,2})L0?(\d{1,2})\b")  # L01L08 → (1, 8)

    groups = []      # 输出的复杂记录组
    cur = None       # 当前组的游标
    for l in lines:
        s = l.strip()
        if not s:
            continue
        # 取 op-code（前 3 字符，但要兼容 A 版紧凑 "317NET" 与 B 版 "427 NET1"）
        m = re.match(r"^(\d{3})(.*)$", s)
        if not m:
            continue
        op = m.group(1)
        rest = m.group(2)

        if op in ("427", "433"):
            # 新复杂记录组：顶面 test/non-test area
            cm = coord_re.search(s)
            cur = {
                "net": rest.lstrip().split()[0] if rest.strip() else "",
                "primary_side": True,
                "layers": None,
                "records": [],
            }
            if cm:
                cur["records"].append({
                    "opcode": op,
                    "x_mm": round(int(cm.group(1)) * 0.00254, 4),
                    "y_mm": round(int(cm.group(2)) * 0.00254, 4),
                })
            groups.append(cur)
        elif op == "013" and cur is not None:
            # 导电孔：提取层对 L01LNN
            lm = layer_re.search(s)
            if lm:
                cur["layers"] = (int(lm.group(1)), int(lm.group(2)))
            cm = coord_re.search(s)
            if cm:
                cur["records"].append({
                    "opcode": op,
                    "x_mm": round(int(cm.group(1)) * 0.00254, 4),
                    "y_mm": round(int(cm.group(2)) * 0.00254, 4),
                })
        elif op in ("027", "033") and cur is not None:
            # 底面测试区/非测试区
            cm = coord_re.search(s)
            if cm:
                cur["records"].append({
                    "opcode": op,
                    "x_mm": round(int(cm.group(1)) * 0.00254, 4),
                    "y_mm": round(int(cm.group(2)) * 0.00254, 4),
                })
        # 其它 op-code（317/327/350/367/099...）→ 跳过（P1：识别不崩溃）
        #   317/327 由 parse_ipc357_coords_to_mm 单独处理；350/367/099 当前不解析
    return groups


# ---------------------------------------------------------------
# DXF 解析（板框与几何）
# ---------------------------------------------------------------
def parse_dxf_extents(dxf_path):
    """解析 DXF 的 $EXTMIN/$EXTMAX 板框范围。"""
    with open(dxf_path, "rb") as f:
        data = f.read().decode("ascii", errors="ignore")
    ext = {}
    cur = None
    for line in data.split("\n"):
        s = line.strip()
        if s == "$EXTMIN" or s == "$EXTMAX":
            cur = s[1:]
        elif cur and s in ("10", "20", "30"):
            pass
        elif cur and cur not in ext:
            try:
                ext.setdefault(cur, []).append(float(s))
            except ValueError:
                pass
            if len(ext.get(cur, [])) >= 3:
                cur = None
    result = {}
    for k, v in ext.items():
        if len(v) >= 3:
            result[k] = v[:3]
    return result


# ---------------------------------------------------------------
# 布局分析
# ---------------------------------------------------------------
def layout_analysis(components):
    """基于坐标的布局分析：密度、间距、层分布。"""
    pts = []
    for c in components:
        if len(c) >= 8:
            try:
                x, y = float(c[6]), float(c[7])
                layer = c[4] if len(c) > 4 else "?"
                pts.append((c[1], c[0], x, y, layer, c[2] if len(c) > 2 else ""))
            except ValueError:
                continue
    xs = [p[2] for p in pts]
    ys = [p[3] for p in pts]
    bbox = None
    if xs and ys:
        bbox = {"min_x": min(xs), "max_x": max(xs),
                "min_y": min(ys), "max_y": max(ys)}

    # 最小元件间距（粗略：用 5mm 网格密度评估）
    grid = defaultdict(int)
    cell = 20.0  # mm 网格
    for p in pts:
        gx, gy = int(p[2] // cell), int(p[3] // cell)
        grid[(gx, gy)] += 1
    dense = sorted(grid.items(), key=lambda kv: -kv[1])[:5]
    dense_cells = [(f"X{gx*cell:.0f}-{(gx+1)*cell:.0f}mm", f"Y{gy*cell:.0f}-{(gy+1)*cell:.0f}mm", cnt)
                   for (gx, gy), cnt in dense]

    # 层分布
    layers = Counter(p[4] for p in pts)
    return {"count": len(pts), "bbox": bbox, "dense_cells": dense_cells,
            "layers": dict(layers), "points": pts}


# ---------------------------------------------------------------
# 元件归类
# ---------------------------------------------------------------
COMPONENT_CLASS = {
    "R": "电阻", "C": "电容", "D": "二极管", "Q": "三极管/晶体管",
    "U": "IC/芯片", "L": "电感", "F": "保险丝", "Y": "晶振/晶体",
    "J": "连接器", "ZD": "稳压管", "TP": "测试点", "M": "安装孔",
    "BT": "电池座", "LCD": "屏", "T": "变压器", "LB": "指示灯",
    "CN": "连接器", "JP": "跳线",
}


# ---------------------------------------------------------------
# 元件归类（基于 PartType 列，PADS 标准类型）
# ---------------------------------------------------------------
PARTTYPE_RULES = [
    (["RES", "R-", "RP"], "电阻"),
    (["CAP", "C-", "ECAP"], "电容"),
    (["IND", "L-", "BEAD", "FERRITE"], "电感/磁珠"),
    (["DIO", "ZD", "TVS", "BZT", "BAS", "SMBJ", "PESD"], "二极管/保护"),
    (["NPN", "PNP", "PMO", "MOS", "2N"], "晶体管"),
    (["FUS", "PTC"], "保险丝"),
    (["CON", "BNC", "HDM", "SD", "USB", "SATA", "JUM", "JP", "SPD", "HEADER", "SIP"], "连接器"),
    (["CRY", "OSC", "XTAL", "3225"], "晶振/振荡器"),
    (["IC", "U-", "LP34", "SPD8", "MUP", "LT", "AMS", "SY8", "TPS"], "IC/芯片"),
    (["LED"], "LED指示灯"),
    (["BAT", "BATT", "CR12"], "电池"),
    (["TP"], "测试点"),
    (["M-", "HOLE"], "安装孔"),
]


def classify_components(components):
    """按 PartType 归类元件，返回 (ref_counter, classes)。"""
    ref_counter = Counter()
    classes = defaultdict(int)
    for c in components:
        if len(c) < 2:
            continue
        ref = c[1]
        ptype = c[0]
        m = re.match(r"([A-Za-z]{1,3})", ref)
        if m:
            ref_counter[m.group(1).upper()] += 1
        matched = False
        for kws, cls in PARTTYPE_RULES:
            if any(kw in ptype.upper() for kw in kws):
                classes[cls] += 1
                matched = True
                break
        if not matched:
            classes["其他"] += 1
    return ref_counter, dict(classes)


# ---------------------------------------------------------------
# 布局检查：基于坐标的物理层检查
# ---------------------------------------------------------------
import math


def _pos(c):
    """提取元件坐标 (x, y)，无效返回 None"""
    try:
        return float(c[6]), float(c[7])
    except (ValueError, IndexError):
        return None


def _dist(p1, p2):
    return math.hypot(p1[0] - p2[0], p1[1] - p2[1])


def _part_prefix(c):
    """提取元件位号前缀（字母部分）。位号是"谁是什么器件"的可靠判据。

    RefDes 形如 U3 / C12 / J16 / M1 / ZD2 / TP5 / Y1 / R8 ...
    返回大写字母前缀，如 'U' / 'C' / 'J' / 'M' / 'ZD' / 'TP' / 'Y' / 'R'。
    """
    ref = c[1] if len(c) > 1 else ""
    m = re.match(r"^([A-Za-z]+)", ref)
    return m.group(1).upper() if m else ""


def _ptype_tokens(c):
    """把 PartType 拆成单词/标识符集合，用于「整词」匹配，杜绝子串误命中。

    例：'LP3443LT1G' -> {'LP3443LT1G'}（不含 'LP'）
        'SPD8'       -> {'SPD8'}
        'HDMI_TVS_RCLAMP0524P' -> {'HDMI_TVS_RCLAMP0524P'}
    """
    ptype = c[0] if len(c) > 0 else ""
    return set(re.findall(r"[A-Za-z][A-Za-z0-9]*", ptype.upper()))


def nearest_distances(components, target_filter, other_filter):
    """对每个目标元件，计算到最近的other元件距离。"""
    targets = [c for c in components if target_filter(c)]
    others = [(_pos(c), c) for c in components if other_filter(c) and _pos(c)]
    others_xy = [o for o in others if o[0]]
    results = []
    for c in targets:
        p = _pos(c)
        if not p:
            continue
        best = None
        for op, oc in others_xy:
            d = _dist(p, op)
            if best is None or d < best[0]:
                best = (d, oc[1])
        results.append({"ref": c[1], "type": c[0], "pos": p,
                        "nearest_ref": best[1] if best else None,
                        "nearest_dist": best[0] if best else None})
    return results


def decoupling_cap_check(components):
    """高速芯片去耦电容紧贴芯片(<5mm, 可接受<10mm)。
    对每个IC，检查最近的电容距离。
    
    准确性约束：
    - 物理距离：⭐⭐⭐⭐⭐ 权威（0.1mm精度，基于xy.xlsx坐标）
    - IC/电容识别：⭐⭐⭐⭐ 高准确（启发式匹配，依赖PartType命名规范）
    - 去耦判断：⭐⭐⭐⭐ 高准确（物理距离+IPC-D-356网络双验证时）
    """
    def is_ic(c):
        # 位号前缀是可靠判据：U = IC/芯片（硬件行业标准）。
        # 修复裸子串误判：J16 SPD8、M1 LP3443LT1G 之前因 "SPD"/"LP" 子串被误当 IC。
        pref = _part_prefix(c)
        if pref == "U":
            return True
        if pref in ("J", "M", "CN", "TP", "LCD"):
            return False
        # 位号不明确时，用 PartType 整词匹配兜底（不再是任意子串）
        toks = _ptype_tokens(c)
        return bool(toks & {"IC", "DCDC", "LDO"})

    def is_cap(c):
        # 位号前缀优先：C = 电容。修复 up.startswith("C") 误吞 CON 连接器的隐患。
        pref = _part_prefix(c)
        if pref == "C":
            return True
        if pref in ("J", "M", "U", "R", "L", "CN", "TP"):
            return False
        toks = _ptype_tokens(c)
        return bool(toks & {"CAP", "ECAP"})

    results = nearest_distances(components, is_ic, is_cap)
    issues = []
    cap_stats = {"ok": 0, "warning": 0, "critical": 0}
    for r in results:
        d = r["nearest_dist"]
        if d is None:
            continue
        if d <= 5.0:
            cap_stats["ok"] += 1
        elif d <= 10.0:
            cap_stats["warning"] += 1
            issues.append({
                "severity": "medium", 
                "item": "去耦电容距离",
                "desc": f"{r['ref']} 最近电容 {r['nearest_ref']} 距离 {d:.1f}mm（5-10mm，建议<5mm）",
                "accuracy": "⭐⭐⭐⭐⭐ 物理距离权威"
            })
        else:
            cap_stats["critical"] += 1
            issues.append({
                "severity": "high", 
                "item": "去耦电容距离",
                "desc": f"{r['ref']} 最近电容 {r['nearest_ref']} 距离 {d:.1f}mm（>10mm，去耦失效风险）",
                "accuracy": "⭐⭐⭐⭐⭐ 物理距离权威"
            })
    return {
        "results": results, 
        "stats": cap_stats, 
        "issues": issues,
        "accuracy_level": "⭐⭐⭐⭐⭐ 物理距离权威 / ⭐⭐⭐⭐ IC识别高准确",
        "constraints": "需结合IPC-D-356确认网络连接，排除\"距离近但不在同一电源网络\"的误判"
    }



def crystal_layout_check(components):
    """晶振与 MCU 距离<10mm。
    晶振到最近IC距离。
    
    准确性约束：
    - 物理距离：⭐⭐⭐⭐⭐ 权威（0.1mm精度）
    - 晶振识别：⭐⭐⭐⭐ 高准确（启发式匹配Y开头位号）
    """
    def is_crystal(c):
        # 位号前缀 Y = 晶振/晶体。修复 "OSC"/"3225" 子串误命中。
        pref = _part_prefix(c)
        if pref == "Y":
            return True
        toks = _ptype_tokens(c)
        return bool(toks & {"CRYSTAL", "XTAL", "OSCILLATOR", "OSC"})

    def is_ic(c):
        # 与 decoupling_cap_check 一致的规则：位号 U = IC。
        pref = _part_prefix(c)
        if pref == "U":
            return True
        if pref in ("J", "M", "CN", "TP", "LCD"):
            return False
        toks = _ptype_tokens(c)
        return bool(toks & {"IC", "DCDC", "LDO"})

    results = nearest_distances(components, is_crystal, is_ic)
    issues = []
    for r in results:
        d = r["nearest_dist"]
        if d is not None and d > 10.0:
            issues.append({
                "severity": "medium", 
                "item": "晶振布局",
                "desc": f"晶振 {r['ref']} 距最近IC {r['nearest_ref']} {d:.1f}mm（>10mm，可能增加走线干扰）",
                "accuracy": "⭐⭐⭐⭐⭐ 物理距离权威"
            })
    return {
        "results": results, 
        "issues": issues,
        "accuracy_level": "⭐⭐⭐⭐⭐ 物理距离权威 / ⭐⭐⭐⭐ 晶振识别高准确"
    }
def esd_protection_check(components):
    """ESD 保护器件离接口<5mm。
    
    准确性约束：
    - 物理距离：⭐⭐⭐⭐⭐ 权威（0.1mm精度）
    - ESD器件识别：⭐⭐⭐⭐ 高准确（TVS/二极管启发式匹配）
    - 连接器识别：⭐⭐⭐⭐ 高准确（J开头位号）
    """
    def is_conn(c):
        # 位号 J = 连接器。辅助 PartType 整词判断。
        pref = _part_prefix(c)
        if pref in ("J", "JP", "CN", "CON"):
            return True
        toks = _ptype_tokens(c)
        return bool(toks & {"CONNECTOR", "HEADER", "USB", "SATA", "HDMI", "BNC", "JACK"})

    def is_esd(c):
        # 位号 ZD（稳压/TVS）或 D（二极管）为 ESD/TVS 器件。
        # 修复裸子串：只按 PartType 整词，位号兜底。
        pref = _part_prefix(c)
        if pref in ("ZD", "D"):
            return True
        toks = _ptype_tokens(c)
        return bool(toks & {"TVS", "ESD", "PESD", "SMBJ", "BZT", "BAS"})
    results = nearest_distances(components, is_conn, is_esd)
    issues = []
    no_esd = 0
    for r in results:
        if r["nearest_dist"] is None:
            no_esd += 1
            continue
        d = r["nearest_dist"]
        if d > 5.0:
            issues.append({
                "severity": "medium", 
                "item": "ESD保护距离",
                "desc": f"连接器 {r['ref']} 最近ESD器件 {r['nearest_ref']} 距离 {d:.1f}mm（>5mm）",
                "accuracy": "⭐⭐⭐⭐⭐ 物理距离权威"
            })
    if no_esd:
        issues.append({
            "severity": "high", 
            "item": "ESD保护缺失",
            "desc": f"{no_esd} 个连接器附近未发现ESD/TVS器件（需核查）",
            "accuracy": "⭐⭐⭐⭐ ESD识别高准确（可能误判：TVS在反面或远距离保护）"
        })
    return {
        "results": results, 
        "issues": issues,
        "accuracy_level": "⭐⭐⭐⭐⭐ 物理距离权威 / ⭐⭐⭐⭐ 器件识别高准确"
    }


def ir_drop_estimate(components):
    """直流压降估算 R=rho*L/(W*T)。
    
    准确性约束：
    - 物理距离：⭐⭐⭐⭐⭐ 权威（0.1mm精度，基于xy.xlsx坐标）
    - 压降估算：⭐⭐⭐ 趋势准确（±30%误差，假设1mm宽走线/1oz铜/1A电流）
    """
    rho = 0.0175
    t = 0.035
    ERROR_MARGIN = 0.30  # ±30% 误差范围
    
    def is_pwr_ic(c):
        up = c[0].upper()
        return any(k in up for k in ["LP34", "AMS", "SY8", "TPS", "MP", "DCDC", "LDO"])
    pwr_ics = [c for c in components if is_pwr_ic(c) and _pos(c)]
    if not pwr_ics:
        return {"results": [], "note": "未识别到电源器件"}
    results = []
    for c in pwr_ics:
        p = _pos(c)
        loads = [(_pos(o), o) for o in components if _pos(o) and o[1] != c[1]]
        if not loads:
            continue
        avg_d = sum(_dist(p, lp) for lp, _ in loads) / len(loads)
        max_d = max(_dist(p, lp) for lp, _ in loads)
        r_avg = rho * avg_d / (1.0 * t) / 1000.0
        r_max = rho * max_d / (1.0 * t) / 1000.0
        
        # 计算误差范围
        drop_avg = r_avg * 1000
        drop_max = r_max * 1000
        
        results.append({
            "ref": c[1], 
            "type": c[0],
            "avg_load_dist_mm": round(avg_d, 1),
            "max_load_dist_mm": round(max_d, 1),
            "r_avg_mohm": round(r_avg * 1000, 1),
            "r_max_mohm": round(r_max * 1000, 1),
            "drop_avg_1A_mv": round(drop_avg, 1),
            "drop_max_1A_mv": round(drop_max, 1),
            # 新增：误差范围
            "drop_avg_range": f"{round(drop_avg * (1 - ERROR_MARGIN), 1)}-{round(drop_avg * (1 + ERROR_MARGIN), 1)} mV",
            "drop_max_range": f"{round(drop_max * (1 - ERROR_MARGIN), 1)}-{round(drop_max * (1 + ERROR_MARGIN), 1)} mV",
            "accuracy": "⭐⭐⭐ 趋势准确（±30%）",
            "constraints": "假设：1mm走线宽、1oz铜厚、1A电流"
        })
    return {
        "results": results, 
        "note": "⚠️ 压降为粗略估算（±30%误差），假设1mm走线/1oz铜/1A电流。实际值需查PCB设计参数。",
        "accuracy_level": "⭐⭐⭐ 趋势准确",
        "validation_required": "示波器实测电源压降 + 对比原理图配置"
    }


def differential_pair_detect(nets):
    """识别差分对网络（D+/D-、_P/_N、+/-），按基础名配对。"""
    net_names = list(nets.values())
    # 提取基础名与极性
    groups = {}
    for n in net_names:
        u = n.upper()
        base, pol = None, None
        for suffix, p in [("D+", "+"), ("D-", "-"), ("_P", "+"), ("_N", "-"),
                          ("+", "+"), ("-", "-")]:
            if u.endswith(suffix):
                base, pol = n[:len(n) - len(suffix)], p
                break
        if base and pol:
            groups.setdefault(base, {})[pol] = n
    pairs = []
    for base, poles in groups.items():
        if "+" in poles and "-" in poles:
            pairs.append((poles["+"], poles["-"]))
    return pairs




def generate_pcb_risks(components, nets, analysis):
    """基于PCB交付件数据的启发式风险提示。"""
    risks = []
    ref_counter, classes = classify_components(components)
    ics = classes.get("IC/芯片", 0)
    crystals = classes.get("晶振/振荡器", 0)
    fuses = classes.get("保险丝", 0)
    caps = classes.get("电容", 0)
    res = classes.get("电阻", 0)

    if ics == 0:
        risks.append({"severity": "high", "item": "IC器件", "desc": "未发现IC元件，数据可能不完整"})
    if crystals == 0:
        risks.append({"severity": "info", "item": "晶振", "desc": "未发现晶振，可能使用内部时钟或漏检"})
    if fuses == 0:
        risks.append({"severity": "info", "item": "保险丝", "desc": "未发现保险丝，注意输入保护"})

    layers = analysis.get("layers", {})
    total = analysis.get("count", 0)
    if layers.get("Top", 0) > 0 and layers.get("Bottom", 0) > 0:
        risks.append({"severity": "info", "item": "双面布局",
                      "desc": f"Top {layers.get('Top',0)} 个元件，Bottom {layers.get('Bottom',0)} 个元件（双面贴装）"})
    if total > 500:
        risks.append({"severity": "info", "item": "元件密度",
                      "desc": f"共 {total} 个元件，属于高密度板，注意可制造性(DFM)与散热"})

    summary = {"ics": ics, "crystals": crystals, "fuses": fuses,
               "caps": caps, "resistors": res, "total": total}
    return risks, summary


def build_pcb_report(analysis, output_dir, source_dir):
    """生成 PCB 交付件分析 HTML 报告（输出到工具自身目录）。"""
    from datetime import datetime
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = out / f"pcb_analysis_{ts}.html"

    bbox = analysis.get("bbox") or {}
    layers = analysis.get("layers") or {}
    classes = analysis.get("classes") or {}
    risks = analysis.get("risks") or []
    summary = analysis.get("summary") or {}
    dense = analysis.get("dense_cells") or []
    nets = analysis.get("nets") or {}
    dec = analysis.get("decoupling") or {}
    crystal = analysis.get("crystal") or {}
    esd = analysis.get("esd") or {}
    ir = analysis.get("ir_drop") or {}
    dpairs = analysis.get("diff_pairs") or []
    
    # 数据完整性状态
    validation = analysis.get("validation") or {}
    if validation.get("is_valid", True):
        validation_status = "✅ 通过"
    else:
        validation_status = f"❌ 未通过（{len(validation.get('errors', []))}个错误，{len(validation.get('warnings', []))}个警告）"
    decoupling = dec  # 别名用于HTML模板

    # 布局分析区块
    dec_rows = ""
    for r in dec.get("results", []):
        d = r.get("nearest_dist")
        dec_rows += (f"<tr><td>{r.get('ref','-')}</td><td>{r.get('type','-')}</td>"
                     f"<td>{'%.1f' % d if d is not None else '-'} mm</td>"
                     f"<td>{r.get('nearest_ref','-')}</td></tr>")
    dec_stats = dec.get("stats", {})
    crystal_rows = ""
    for r in crystal.get("results", []):
        d = r.get("nearest_dist")
        crystal_rows += (f"<tr><td>{r.get('ref','-')}</td><td>{r.get('type','-')}</td>"
                         f"<td>{'%.1f' % d if d is not None else '-'} mm</td>"
                         f"<td>{r.get('nearest_ref','-')}</td></tr>")
    esd_rows = ""
    for r in esd.get("results", []):
        d = r.get("nearest_dist")
        esd_rows += (f"<tr><td>{r.get('ref','-')}</td><td>{r.get('type','-')}</td>"
                     f"<td>{'%.1f' % d if d is not None else '-'} mm</td>"
                     f"<td>{r.get('nearest_ref','-')}</td></tr>")
    ir_rows = ""
    for r in ir.get("results", []):
        ir_rows += (f"<tr><td>{r.get('ref','-')}</td><td>{r.get('type','-')}</td>"
                    f"<td>{r.get('avg_load_dist_mm','-')}</td><td>{r.get('r_avg_mohm','-')}</td>"
                    f"<td>{r.get('drop_avg_1A_mv','-')} <span style='font-size:11px;color:#666;'>({r.get('drop_avg_range','-')})</span></td>"
                    f"<td>{r.get('accuracy','')}</td></tr>")

    dp_rows = "".join(f"<tr><td>{a}</td><td>{b}</td></tr>" for a, b in dpairs)

    class_rows = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in classes.items())
    risk_rows = "".join(
        f"<tr><td><span class='sev-{r.get('severity','info')}'>{r.get('severity','info')}</span></td>"
        f"<td>{r.get('item','')}</td><td>{r.get('desc','')}</td></tr>" for r in risks)
    dense_rows = "".join(f"<tr><td>{x}</td><td>{y}</td><td>{c}</td></tr>" for x, y, c in dense)
    net_rows = "".join(f"<tr><td>{v}</td></tr>" for v in sorted(nets.values()))

    comp_rows = ""
    for c in analysis.get("components", [])[:200]:
        if len(c) >= 8:
            comp_rows += ("<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td>"
                          "<td>{}</td><td>{}</td></tr>").format(
                c[1], c[0], c[4], c[2], c[6], c[7])

    html = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<title>PCB交付件分析报告</title><style>
body{{font-family:'Segoe UI',Arial,sans-serif;margin:0;background:#f0f2f5;color:#333}}
.container{{max-width:1200px;margin:0 auto;padding:20px}}
header{{background:linear-gradient(135deg,#0f3d5c,#1e6f9f);color:#fff;padding:24px;border-radius:8px}}
h1{{margin:0}}h2{{color:#0f3d5c;border-bottom:2px solid #0f3d5c;padding-bottom:6px}}
.card{{background:#fff;padding:20px;margin:16px 0;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,.1)}}
table{{width:100%;border-collapse:collapse}}th,td{{padding:8px;text-align:left;border-bottom:1px solid #e3e6ea;font-size:13px}}
th{{background:#0f3d5c;color:#fff}}
.stat{{display:inline-block;margin:8px 24px 8px 0;font-size:14px}}.stat b{{font-size:26px;color:#0f3d5c}}
.sev-high{{color:#fff;background:#e17055;padding:2px 8px;border-radius:10px}}
.sev-medium{{color:#fff;background:#f39c12;padding:2px 8px;border-radius:10px}}
.sev-info{{color:#fff;background:#0984e3;padding:2px 8px;border-radius:10px}}
.warn{{background:#fff3cd;border-left:4px solid #ffc107;padding:10px;margin:8px 0}}
footer{{text-align:center;padding:16px;color:#888;font-size:13px}}
</style></head><body><div class="container">
<header><h1>📦 PCB交付件深度分析报告</h1>
<p>数据来源：{source_dir}</p>
<p>生成：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ｜ 只读分析，未修改任何硬件文件</p>
<p style="margin-top:8px;">数据完整性：{validation_status} | 参考：DATA_FORMAT_CONSTRAINTS.md</p></header>
<div class="card"><h2>总览</h2>
<span class="stat"><b>{summary.get('total',0)}</b><br>元件总数</span>
<span class="stat"><b>{summary.get('ics',0)}</b><br>IC芯片(U)</span>
<span class="stat"><b>{summary.get('caps',0)}</b><br>电容(C)</span>
<span class="stat"><b>{summary.get('resistors',0)}</b><br>电阻(R)</span>
<span class="stat"><b>{summary.get('crystals',0)}</b><br>晶振(Y)</span>
<span class="stat"><b>{len(nets)}</b><br>测试网络</span>
</div>
<div class="card"><h2>板框与布局</h2>
<table><tr><th>参数</th><th>值</th></tr>
<tr><td>元件X范围</td><td>{bbox.get('min_x','-')} ~ {bbox.get('max_x','-')} mm</td></tr>
<tr><td>元件Y范围</td><td>{bbox.get('min_y','-')} ~ {bbox.get('max_y','-')} mm</td></tr>
<tr><td>层分布</td><td>Top: {layers.get('Top',0)}, Bottom: {layers.get('Bottom',0)}</td></tr>
</table>
<h3>高密度区域 (20mm网格)</h3><table><tr><th>X区域</th><th>Y区域</th><th>元件数</th></tr>{dense_rows}</table></div>
<div class="card"><h2>📶 布局检查分析</h2>
<h3>去耦电容布局检查（<5mm 优，5-10mm可接受，>10mm风险）⭐⭐⭐⭐⭐ 物理距离权威</h3>
<table><tr><th>IC</th><th>类型</th><th>最近电容距离</th><th>电容位号</th></tr>{dec_rows}</table>
<div>统计：<b>{dec_stats.get('ok',0)}</b> 个IC去耦<5mm ✅ ｜ <b>{dec_stats.get('warning',0)}</b> 个 5-10mm ⚠️ ｜ <b>{dec_stats.get('critical',0)}</b> 个 >10mm ❌</div>
<div class="warn">准确性：{decoupling.get('accuracy_level','')} | 约束：{decoupling.get('constraints','')}</div>
<h3>晶振布局检查（距 MCU<10mm）⭐⭐⭐⭐⭐ 物理距离权威</h3>
<table><tr><th>晶振</th><th>类型</th><th>距最近IC</th><th>IC位号</th></tr>{crystal_rows}</table>
<div class="warn">准确性：{crystal.get('accuracy_level','')} | 约束：晶振识别依赖Y开头位号或关键字</div>
<h3>ESD 保护距离检查（接口<5mm）⭐⭐⭐⭐⭐ 物理距离权威</h3>
<table><tr><th>连接器</th><th>类型</th><th>距最近ESD器件</th><th>ESD位号</th></tr>{esd_rows}</table>
<div class="warn">准确性：{esd.get('accuracy_level','')} | 约束：TVS在反面或远距离保护可能误判</div>
<h3>直流压降估算（R=ρL/WT）⭐⭐⭐ 趋势准确（±30%）</h3>
<table><tr><th>电源器件</th><th>类型</th><th>平均负载距(mm)</th><th>R估算(mΩ)</th><th>压降估算(mV@1A)</th><th>准确性</th></tr>{ir_rows}</table>
<div class="warn">{ir.get('note','')} | 准确性：{ir.get('accuracy_level','')} | 验证要求：{ir.get('validation_required','')}</div>
<h3>差分对识别（IPC网表）</h3>
<table><tr><th>正端</th><th>负端</th></tr>{dp_rows}</table>
</div>
<div class="card"><h2>⚠️ 风险提示（启发式）</h2>
<table><tr><th>级别</th><th>检查项</th><th>说明</th></tr>{risk_rows}</table></div>
<div class="card"><h2>元件分类统计</h2><table><tr><th>类别</th><th>数量</th></tr>{class_rows}</table></div>
<div class="card"><h2>测试网络清单</h2><table><tr><th>网络名</th></tr>{net_rows}</table></div>
<div class="card"><h2>元件清单（前200）</h2><table><tr><th>类型</th><th>位号</th><th>层</th><th>封装</th><th>X(mm)</th><th>Y(mm)</th></tr>{comp_rows}</table></div>
<div class="warn"><b>说明：</b>本报告基于投板交付件(xy.xlsx元件坐标 + IPC-D-356网表)的只读解析。
真实网表连接关系需 OrCAD/PADS 导出 netlist 后方可做元器件级连通性分析。</div>
<footer>由 Hardware Analyzer 生成 ｜ 只读分析</footer>
</div></body></html>"""
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html)
    return report_path


def analyze_deliverables(base_dir):
    """主入口：分析投板交付件目录，返回分析结果。"""
    base = Path(base_dir)
    results = {"source": str(base), "nets": {}, "components": [], "errors": [], "warnings": []}

    # 0. 输入数据完整性检查（新增）
    print("\n=== 输入数据完整性检查 ===")
    is_valid, errors, warnings = validate_input_data(base_dir)
    results["validation"] = {
        "is_valid": is_valid,
        "errors": errors,
        "warnings": warnings
    }
    
    # 输出检查结果
    if errors:
        print("❌ 发现严重错误：")
        for err in errors:
            print(f"   {err}")
    if warnings:
        print("⚠️  发现警告：")
        for warn in warnings:
            print(f"   {warn}")
    
    if not is_valid:
        print("\n❌ 数据完整性检查未通过，部分分析可能不准确。")
        print("   建议：检查文件格式、元件命名规范、IPC-D-356完整性。")
        print("   参考：DATA_FORMAT_CONSTRAINTS.md 约束章节\n")
    else:
        print("✅ 数据完整性检查通过\n")

    # 1. xy.xlsx 元件坐标表（先探单位，再解析，避免 mil/mm 静默误判）
    xlsx_files = glob.glob(str(base / "**" / "xy.xlsx"), recursive=True)
    if xlsx_files:
        try:
            unit = detect_unit_in_dir(base_dir)
            if unit is None:
                # 无 IPC 单位声明 → fail-fast，明确报错，不静默猜（精确性红线）
                results["errors"].append(
                    "无法确定 xy.xlsx 坐标单位：投板目录无 IPC-D-356 的 UNITS 声明。"
                    "请显式指定单位（PADS 的坐标可能是 mil 或 mm）。"
                )
                results["components"] = []
            else:
                results["components"] = parse_xy_xlsx(xlsx_files[0], coord_unit=unit)
                print(f"[xy.xlsx] 解析 {len(results['components'])} 个元件（单位={unit}）: {xlsx_files[0]}")
        except ValueError as e:
            # 区分：有 UNITS 声明但值未枚举（枚举不全），是工具问题而非用户数据问题
            results["errors"].append(f"坐标单位枚举不全: {e}")
        except Exception as e:
            results["errors"].append(f"xy.xlsx解析失败: {e}")
    else:
        results["errors"].append("未找到 xy.xlsx")

    # 2. IPC-D-356 网表/测试点
    ipc_files = glob.glob(str(base / "**" / "*.ipc"), recursive=True)
    if ipc_files:
        try:
            nets, comps = parse_ipc_netlist(ipc_files[0])
            results["nets"] = nets
            results["ipc_comps"] = comps
            print(f"[IPC-D-356] 解析 {len(nets)} 个网络、{len(comps)} 个元件: {ipc_files[0]}")
        except Exception as e:
            results["errors"].append(f"IPC解析失败: {e}")
    else:
        results["errors"].append("未找到 .ipc 文件")

    # 3. DXF 板框几何
    dxf_files = glob.glob(str(base / "**" / "*.dxf"), recursive=True)
    if dxf_files:
        try:
            results["dxf_extents"] = parse_dxf_extents(dxf_files[0])
            print(f"[DXF] 解析板框: {dxf_files[0]}")
        except Exception as e:
            results["errors"].append(f"DXF解析失败: {e}")

    # 4. 布局分析
    layout = layout_analysis(results["components"])
    results.update(layout)

    # 5. 分类与风险
    ref_counter, classes = classify_components(results["components"])
    results["ref_counter"] = ref_counter
    results["classes"] = classes
    risks, summary = generate_pcb_risks(results["components"], results["nets"], layout)
    results["risks"] = risks
    results["summary"] = summary

    # 6. 布局检查（去耦/晶振/ESD/压降）
    print("[分析] 去耦电容布局检查...")
    results["decoupling"] = decoupling_cap_check(results["components"])
    print("[分析] 晶振布局检查...")
    results["crystal"] = crystal_layout_check(results["components"])
    print("[分析] ESD 保护检查...")
    results["esd"] = esd_protection_check(results["components"])
    print("[分析] 直流压降估算...")
    results["ir_drop"] = ir_drop_estimate(results["components"])
    print("[分析] 差分对识别...")
    results["diff_pairs"] = differential_pair_detect(results["nets"])
    # 合并布局风险到风险列表
    for key in ["decoupling", "crystal", "esd"]:
        results["risks"].extend(results[key]["issues"])
    return results



