#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hardware Analyzer - 硬件分析工具
=============================================
纯 Python 标准库实现，无第三方强制依赖。

功能：
  1. 格式自动检测（KiCad文本 / OrCAD二进制）
  2. 二进制原理图只读扫描分析
  3. **Netlist真实连接分析（KiCad/Allegro格式）** ← 新增
  4. 网络分类（电源/地/USB/显示/存储/通信/时钟/控制）
  5. 电源电压域分组 + PDN目标阻抗估算
  6. 元件值统计 + 关键器件识别（LDO/DCDC/晶振/ESD/保险丝）
  7. 风险提示引擎（通用设计检查表启发式）
  8. 多模式分析 + HTML报告生成

严格约束：本工具只读分析硬件文件，绝不修改被分析文件。
"""
import sys
import glob
import json
import re
import argparse
from pathlib import Path
from datetime import datetime

# 导入netlist解析器
try:
    from kicad_netlist_parser import (
        parse_kicad_netlist, build_component_pin_map, 
        find_power_nets, find_ground_nets, find_decoupling_caps
    )
    from allegro_netlist_parser import (
        parse_allegro_netlist, auto_detect_netlist_format
    )
    from orcad_expanded_parser import parse_orcad_expanded, auto_detect_expanded
    from pads_netlist_parser import parse_pads2000_netlist, detect_pads2000
    from power_tree import build_power_tree, generate_mermaid_power_tree
    NETLIST_SUPPORT = True
except ImportError:
    NETLIST_SUPPORT = False
    print("[警告] Netlist解析器未找到，--netlist功能不可用")

# 导入计算公式库（母线掉压 + 电源/信号完整性估算）
try:
    from calculators import (
        bus_droop, parse_capacitance, parse_capacitance_code,
        lookup_cap_esr_esl, parallel_esr_esl, loop_esl_from_distance,
        pdn_target_impedance, decoupling_capacitor_value,
        trace_inductance, via_inductance,
        propagation_delay, microstrip_impedance, differential_impedance,
        max_trace_length_no_termination, emi_radiation_estimate,
        trace_resistance, voltage_drop, trace_width_for_current,
        temperature_rise, pcb_capacitance,
        crystal_load_capacitance, crystal_capacitor_value,
    )
    CALC_SUPPORT = True
except ImportError:
    CALC_SUPPORT = False
    print("[警告] calculators 公式库未找到，估算功能不可用")

# 导入 Gerber / IPC-2581 解析器
try:
    from gerber_parser import parse_gerber_traces
    from ipc2581_parser import parse_ipc2581
    GERBER_IPC_SUPPORT = True
except ImportError:
    GERBER_IPC_SUPPORT = False
    print("[警告] Gerber/IPC-2581 解析器未找到，相关功能不可用")

# 导入方向分析器
try:
    import sys
    sys.path.insert(0, str(Path(__file__).parent / 'analyzers'))
    from direction_analyzer import DirectionAnalyzer, format_direction_report
    DIRECTION_ANALYZER_AVAILABLE = True
except ImportError:
    DIRECTION_ANALYZER_AVAILABLE = False
    print("[警告] 方向分析器未找到")


# ------------------------------------------------------------------
# 内置默认规则（对应 config/rules.yaml 的纯标准库版本）
# ------------------------------------------------------------------
DEFAULT_RULES = {
    "power_rules": {
        "decoupling": {"standard_caps": [
            {"value": "100nF", "proximity_max_mm": 5},
            {"value": "10uF", "proximity_max_mm": 10}]},
        "voltage_drop": {
            "tolerance_percent": 3,
            "copper_resistivity_1oz": 0.0175,
            "copper_thickness_1oz_mm": 0.035,
            "safety_factor": 1.3},
        "pdn_impedance": {"default_ripple_mv": 50}
    }
}

# 网络分类关键词表
NET_KEYWORDS = {
    "power":    ["VCC", "VDD", "VBAT", "PWR", "3V3", "5V", "12V", "1.8V",
                 "2.5V", "3.8V", "1.2V", "0.9V", "VIN", "VOUT", "VSYS"],
    "gnd":      ["GND", "AGND", "DGND", "PGND"],
    "usb":      ["USB", "DP", "DM", "VBUS", "ID"],
    "display":  ["LCD", "HDMI", "MIPI", "LVDS", "EDID", "CEC", "BL_", "PWM"],
    "storage":  ["SATA", "SD", "MMC", "EMMC", "NAND", "SDRAM", "DDR"],
    "comm":     ["UART", "SPI", "I2C", "CAN", "GSM", "GPS", "RF", "SIM",
                 "TXD", "RXD", "SCL", "SDA", "MISO", "MOSI", "CSI", "DSI"],
    "clock":    ["CLK", "OSC", "XTAL", "SYSCLK", "HSE", "LSE"],
    "control":  ["EN", "RST", "RESET", "PWR_KEY", "WAKE", "IRQ", "GPIO", "BOOT"],
}

# 关键器件识别规则
DEVICE_RULES = {
    "LDO":       ["LDO", "AMS1117", "SE5218", "TLV", "LP29", "REG1117"],
    "DCDC":      ["DCDC", "BUCK", "BOOST", "TPS5", "TPS6", "SY8", "MP14", "MP2"],
    "Crystal":   ["CRYSTAL", "XTAL", "OSCILLATOR", "OSC-", "HSE", "LSE"],
    "ESD":       ["ESD", "PESD", "TVS", "SMBJ", "SLVU"],
    "Fuse":      ["FUSE", "FUSIBLE", "PTC"],
    "Connector": ["CON", "CN_", "USB", "SATA", "HDMI", "POWER_JACK", "HEADER"],
    "Battery":   ["BAT", "RTC", "CR2032"],
    "Ethernet":  ["ETH", "RJ45", "PHY", "LAN"],
}

# 电压域识别（用于电源分组）
VOLTAGE_PATTERNS = [
    (r"1\.8V|1800|1V8|V18", "1.8V域"),
    (r"2\.5V|2V5|V25",      "2.5V域"),
    (r"3\.3V|3V3|V33|3300", "3.3V域"),
    (r"3\.8V|3V8|V38",      "3.8V域"),
    (r"5V\b|5VA|5V0|V50",   "5V域"),
    (r"12V|V12",            "12V域"),
    (r"VBAT|V_BAT|BATTERY", "电池域"),
    (r"CORE|VDD_CORE|VCC_CORE", "核心域"),
]


# 电源网络识别关键词 + 排除的"信号后缀"（精确性：只排除语义无歧义的使能/复位/按键）
POWER_NET_KEYWORDS = ["VCC", "VDD", "VIN", "VBAT", "V3V3", "V5V", "V12V", "V1V8", "PWR"]
SIGNAL_SUFFIXES = ("_EN", "_RST", "_KEY")


def is_power_net(name):
    """判断网络名是否为「电源主干」（排除使能/复位/按键等信号）。

    规则（精确，避免伪电源网络混入母线掉压/环路 ESL 的统计）：
      1. 必须含 POWER_NET_KEYWORDS 之一（VCC/VDD/VIN/VBAT/V3V3/.../PWR）
      2. 且不以 SIGNAL_SUFFIXES 结尾（_EN=使能、_RST=复位、_KEY=按键）

    例：PWR_IN → True（电源输入）；ST32_GSM_PWR_EN → False（使能信号）；
        PWR_KEY_RST → False（复位）；SC_VBAT_V38 → True（电池电源）。
    """
    if not isinstance(name, str):
        return False
    u = name.upper()
    if not any(kw in u for kw in POWER_NET_KEYWORDS):
        return False
    if u.endswith(SIGNAL_SUFFIXES):
        return False
    return True


def analyze_netlist(filepath):
    """
    解析并分析netlist文件（KiCad或Allegro格式）
    返回包含真实连接关系的分析结果
    """
    if not NETLIST_SUPPORT:
        return {"error": "Netlist解析器不可用"}
    
    print(f"\n[Netlist] 解析文件: {filepath}")
    
    # 自动检测格式（优先 OrCAD EXPANDED，再 PADS2000，再走原有检测）
    if auto_detect_expanded(filepath):
        netlist_format = 'orcad_expanded'
    elif detect_pads2000(filepath):
        netlist_format = 'pads2000'
    else:
        netlist_format = auto_detect_netlist_format(filepath)
    print(f"[Netlist] 检测格式: {netlist_format}")
    
    # 解析netlist
    if netlist_format == 'kicad':
        netlist_data = parse_kicad_netlist(filepath)
    elif netlist_format == 'allegro':
        netlist_data = parse_allegro_netlist(filepath)
    elif netlist_format == 'orcad_expanded':
        netlist_data = parse_orcad_expanded(filepath)
    elif netlist_format == 'pads2000':
        netlist_data = parse_pads2000_netlist(filepath)
    else:
        return {"error": f"未知的netlist格式: {netlist_format}"}
    
    # 统计信息
    total_components = len(netlist_data["components"])
    total_nets = len(netlist_data["nets"])
    print(f"[Netlist] 元件: {total_components} | 网络: {total_nets}")
    
    # 识别电源和地网络
    power_nets = find_power_nets(netlist_data)
    gnd_nets = find_ground_nets(netlist_data)
    print(f"[Netlist] 电源网络: {len(power_nets)} | 地网络: {len(gnd_nets)}")
    
    # 建立引脚映射
    pin_map = build_component_pin_map(netlist_data)
    
    # 查找所有IC的去耦电容
    decoupling_analysis = {}
    ic_refs = [c["ref"] for c in netlist_data["components"] if c["ref"].startswith("U")]
    
    for ic_ref in ic_refs[:20]:  # 限制前20个IC，避免过长
        caps = find_decoupling_caps(netlist_data, ic_ref)
        if caps:
            decoupling_analysis[ic_ref] = caps
    
    print(f"[Netlist] 去耦分析: {len(decoupling_analysis)} 个IC")
    
    # 分析差分对
    differential_pairs = []
    net_names = [net["name"] for net in netlist_data["nets"]]
    for net_name in net_names:
        if any(suffix in net_name for suffix in ["_P", "_N", "+", "-"]):
            base = net_name.replace("_P", "").replace("_N", "").replace("+", "").replace("-", "")
            pair_p = base + "_P" if base + "_P" in net_names else base + "+"
            pair_n = base + "_N" if base + "_N" in net_names else base + "-"
            if pair_p in net_names and pair_n in net_names:
                if not any(p["pair"] == base for p in differential_pairs):
                    differential_pairs.append({"pair": base, "p": pair_p, "n": pair_n})
    
    print(f"[Netlist] 差分对: {len(differential_pairs)} 对")
    
    # 构建电源树拓扑
    power_tree = build_power_tree(netlist_data)
    print(f"[Netlist] 电源树: {power_tree['statistics']['total_converters']} 个转换器 | "
          f"{power_tree['statistics']['total_power_rails']} 个电源轨")
    
    # 生成Mermaid图表
    mermaid_power_tree = generate_mermaid_power_tree(power_tree)
    
    return {
        "format": netlist_format,
        "netlist_data": netlist_data,
        "total_components": total_components,
        "total_nets": total_nets,
        "power_nets": power_nets,
        "gnd_nets": gnd_nets,
        "pin_map": pin_map,
        "decoupling_analysis": decoupling_analysis,
        "differential_pairs": differential_pairs,
        "power_tree": power_tree,
        "mermaid_power_tree": mermaid_power_tree
    }


def load_config():
    """加载配置：优先 JSON 配置文件，否则内置默认。只读。"""
    cfg = Path(__file__).resolve().parent.parent / "config" / "rules.json"
    if cfg.exists():
        try:
            with open(cfg, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[配置] {cfg} 读取失败({e})，使用内置默认规则")
    return DEFAULT_RULES


def resolve_schematic_paths(pattern):
    """展开通配符路径，返回匹配文件列表。仅只读 glob。"""
    matches = sorted(glob.glob(pattern, recursive=False))
    if not matches:
        p = Path(pattern)
        if p.exists() and p.is_file():
            return [str(p)]
    return matches


def detect_format(filepath):
    """检测原理图格式。只读文件头。返回格式名。"""
    with open(filepath, "rb") as f:
        head = f.read(4096)
    null_count = head.count(b"\x00")
    text_ratio = sum(1 for b in head if 32 <= b <= 126) / max(len(head), 1)
    if null_count < 10 and text_ratio > 0.7:  # 文本格式
        head_text = head[:512].decode("ascii", errors="ignore")
        if head_text.lstrip().startswith("EESchema") or b"$Comp" in head:
            return "kicad5"
        if head_text.lstrip().startswith("(kicad_sch") or b"(lib_symbols)" in head:
            return "kicad6"
        return "text_other"
    return "orcad_binary" if null_count > 0 else "binary_other"


def read_strings(filepath):
    """只读提取文件中的可打印 ASCII 字符串（长度>=4）。"""
    with open(filepath, "rb") as f:
        data = f.read()
    strings = []
    current = []
    for byte in data:
        if 32 <= byte <= 126:
            current.append(chr(byte))
        else:
            if len(current) >= 4:
                strings.append("".join(current))
            current = []
    if len(current) >= 4:
        strings.append("".join(current))
    return strings, len(data)


def extract_components(strings):
    """从字符串中提取元件引用号与元件值。纯只读。"""
    ref_pattern = re.compile(r"\b([URCLDQYJFX]\d{1,5})\b")
    comp_refs = {}
    for s in strings:
        for m in ref_pattern.finditer(s):
            comp_refs[m.group(1)] = comp_refs.get(m.group(1), 0) + 1

    # 元件值提取（电容/电感/电阻）
    cap_pat = re.compile(r"(\d+(?:\.\d+)?)\s*(uF|nF|pF)", re.IGNORECASE)
    ind_pat = re.compile(r"(\d+(?:\.\d+)?)\s*(uH|nH)", re.IGNORECASE)
    res_pat = re.compile(r"\b(\d+\.?\d*)\s*([KMR]?)(?:Ω|OHM|OHMS)\b|\b(\d+\.?\d*)([KMR])\b", re.IGNORECASE)
    values = {"电容": {}, "电感": {}, "电阻": {}}
    for s in strings:
        for m in cap_pat.finditer(s):
            v = f"{m.group(1)}{m.group(2).upper()}"
            values["电容"][v] = values["电容"].get(v, 0) + 1
        for m in ind_pat.finditer(s):
            v = f"{m.group(1)}{m.group(2).upper()}"
            values["电感"][v] = values["电感"].get(v, 0) + 1
        for m in res_pat.finditer(s):
            # res_pat 是「分支一 | 分支二」，只有命中的那个分支的捕获组有值，
            # 另一个分支的捕获组全是 None。旧代码只判 group(2) 真假就 .upper()，
            # 命中分支二时会 None.upper() → AttributeError 直接崩溃。
            #
            # 崩溃现场（实测某扫描件 .dsn，字符串 "100 ohm resister"）：
            #   分支一命中：group(1)="100"  group(2)=""（无倍率）
            #                group(3)=None   group(4)=None
            #
            # 注意 group(2) 是空串 != 没有值！"100 ohm" 的合法值就是 "100"，
            # 不能因为 group(2) 为空就跳过，否则会漏掉所有无倍率电阻。
            if m.group(1) is not None:          # 分支一：显式单位 "10K OHM" / "100 ohm"
                v = f"{m.group(1)}{(m.group(2) or '').upper()}"
            elif m.group(3) is not None:        # 分支二：后缀单位 "4.7K"
                v = f"{m.group(3)}{(m.group(4) or '').upper()}"
            else:                               # 两层都没命中，理论上不会发生
                continue
            values["电阻"][v] = values["电阻"].get(v, 0) + 1
    return comp_refs, values


def classify_nets(strings):
    """将扫描到的字符串分类为网络（电源/地/信号等）。"""
    classified = {cat: {} for cat in NET_KEYWORDS}
    classified["other"] = {}
    for s in strings:
        key = s.strip()
        if not (2 <= len(key) <= 40):
            continue
        up = key.upper()
        matched = False
        for cat, kws in NET_KEYWORDS.items():
            if any(kw in up for kw in kws):
                classified[cat][key] = classified[cat].get(key, 0) + 1
                matched = True
                break  # 按优先级取第一个匹配类别
        if not matched:
            classified["other"][key] = classified["other"].get(key, 0) + 1
    # 剔除明显非网络的词（常见噪声）
    noise = {"PART NUMBER", "DESCRIPTION", "PCB DECAL", "Source Path",
             "Drawn By", "Checked By", "Released By", "COMPANY"}
    for cat in classified:
        for n in noise:
            classified[cat].pop(n, None)
    return classified


def identify_devices(strings):
    """识别关键器件与设计工具。只读。"""
    devices = {cat: 0 for cat in DEVICE_RULES}
    device_names = {cat: set() for cat in DEVICE_RULES}
    tools = set()
    for s in strings:
        up = s.upper()
        for cat, kws in DEVICE_RULES.items():
            if any(kw in up for kw in kws):
                devices[cat] += 1
                device_names[cat].add(s.strip()[:40])
        if "ORCAD" in up:
            tools.add("OrCAD Capture")
        elif "PADS" in up:
            tools.add("PADS")
        elif "ALLEGRO" in up:
            tools.add("Allegro")
        elif "KICAD" in up:
            tools.add("KiCad")
    return devices, device_names, sorted(tools)


def group_voltage_domains(classified):
    """按电压关键词对电源网络分组，形成电压域。只读。"""
    domains = {name: {"nets": {}, "count": 0} for _, name in VOLTAGE_PATTERNS}
    domains["未归类"] = {"nets": {}, "count": 0}
    for net, cnt in classified.get("power", {}).items():
        matched = False
        for pat, name in VOLTAGE_PATTERNS:
            if re.search(pat, net, re.IGNORECASE):
                domains[name]["nets"][net] = cnt
                domains[name]["count"] += cnt
                matched = True
                break
        if not matched:
            domains["未归类"]["nets"][net] = cnt
            domains["未归类"]["count"] += cnt
    # 去掉空域
    return {k: v for k, v in domains.items() if v["nets"]}


def analyze_power(classified, config):
    """电源链路分析：电压域分组 + PDN目标阻抗估算。"""
    rules = config.get("power_rules", {})
    ripple = rules.get("pdn_impedance", {}).get("default_ripple_mv", 50) / 1000.0
    domains = group_voltage_domains(classified)
    power_nets = classified.get("power", {})
    gnd_count = sum(classified.get("gnd", {}).values())

    # 每个电源网络估算 PDN 目标阻抗（默认1A，标注需校正）
    pdn = {}
    for net in list(power_nets)[:25]:
        pdn[net] = {
            "target_impedance_mohm": round((ripple / 1.0) * 1000, 2),
            "note": "估算：Z=Vripple/Itransient，I=1A，需按datasheet校正"
        }
    return {
        "power_nets": power_nets,
        "voltage_domains": domains,
        "gnd_signal_count": gnd_count,
        "pdn_targets": pdn,
        "ripple_assumption_mv": ripple * 1000,
    }


def extract_power_net_capacitance(netlist_data):
    """从 netlist 提取每个电源网络的总电容(法拉)。

    只统计位号以 C 开头、且值能被 parse_capacitance 解析的电容元件。
    返回: {net_name: total_c_farad}
    """
    ref_values = {c.get("ref"): c.get("value", "") for c in netlist_data.get("components", [])}
    result = {}
    for net in netlist_data.get("nets", []):
        name = net.get("name", "")
        if not is_power_net(name):
            continue
        total = 0.0
        for node in net.get("nodes", []):
            ref = node.get("ref", "")
            if ref.upper().startswith(("C", "EC")):
                val = ref_values.get(ref, "")
                # 先试单位字符串（100nF），再试 OrCAD EIA 代码（104/33PF）
                f = parse_capacitance(val)
                if f is None:
                    f = parse_capacitance_code(val)
                if f:
                    total += f
        result[name] = total
    return result


def extract_power_net_caps_detail(netlist_data):
    """提取每个电源网络的电容明细（位号 + footprint + 值法拉）。

    只统计位号以 C/EC 开头、且值能被 parse_capacitance/parse_capacitance_code
    解析的电容元件。用于后续按封装查 ESR/ESL。

    返回: {net_name: [{"ref", "footprint", "value", "farad"}]}
    """
    comps = {}
    for c in netlist_data.get("components", []):
        comps[c.get("ref", "")] = c
    result = {}
    for net in netlist_data.get("nets", []):
        name = net.get("name", "")
        if not is_power_net(name):
            continue
        caps = []
        for node in net.get("nodes", []):
            ref = node.get("ref", "")
            if not ref.upper().startswith(("C", "EC")):
                continue
            comp = comps.get(ref, {})
            val = comp.get("value", "")
            f = parse_capacitance(val)
            if f is None:
                f = parse_capacitance_code(val)
            if not f:
                continue
            caps.append({
                "ref": ref,
                "footprint": comp.get("footprint", ""),
                "value": val,
                "farad": f,
            })
        result[name] = caps
    return result


def analyze_transient_droop(netlist_result, params):
    """母线瞬态掉压估算：接入 calculators 公式，对每个电源网络出数字。

    params: dict(istep, delta_t_s, esr_ohm, esl_henry, di_dt_a_s, ripple_v)
            esr_ohm / esl_henry 为"用户显式典型值"（兜底值）。
    返回: {
        "params": params,
        "cap_map": {net: total_c_uf},
        "net_droop": {net: {...bus_droop 结果 + total_c_uf + z_target_mohm
                             + esr_eq_mohm + esl_eq_nh + cap_count}},
    }

    ESR/ESL 取值优先级（遗留问题 3 的实现）：
        1. params["esr_ohm"]/["esl_henry"] 为显式数值（非 None）→ 直接用（用户/旧测试显式给值）
        2. 为 None（未指定）→ 对该网络每个电容按 footprint 查表（lookup_cap_esr_esl）
           并联等效（parallel_esr_esl）得 esr_eq/esl_eq
        3. 查表可得（≥1 电容命中）→ 用 esr_eq/esl_eq
        4. 查表全未命中 → 回退默认 10mΩ / 1nH
    """
    netlist_data = netlist_result.get("netlist_data", {})
    caps_detail = extract_power_net_caps_detail(netlist_data)
    cap_map = {net: sum(c["farad"] for c in caps) for net, caps in caps_detail.items()}
    i_step = params["istep"]
    ripple = params["ripple_v"]
    default_esr = 0.01   # 10mΩ 兜底
    default_esl = 1e-9   # 1nH 兜底
    net_droop = {}
    for net, caps in caps_detail.items():
        c_farad = cap_map.get(net, 0.0)

        # 查表 + 并联等效（无论是否使用，都算出来供报告透明展示）
        cap_params = []
        for c in caps:
            # EC 位号前缀 = 电解电容（OrCAD 语义级标志，比 footprint 命名更可靠）
            if c["ref"].upper().startswith("EC"):
                cap_params.append((0.30, 15e-9))
            else:
                hit = lookup_cap_esr_esl(c["footprint"])
                if hit is not None:
                    cap_params.append(hit)
        esr_eq, esl_eq = parallel_esr_esl(cap_params)

        # 决定最终用的 ESR/ESL
        if params.get("esr_ohm") is not None:
            use_esr = params["esr_ohm"]
        elif esr_eq is not None:
            use_esr = esr_eq
        else:
            use_esr = default_esr

        if params.get("esl_henry") is not None:
            use_esl = params["esl_henry"]
        elif esl_eq is not None:
            use_esl = esl_eq
        else:
            use_esl = default_esl

        r = bus_droop(c_farad, i_step, params["delta_t_s"],
                      use_esr, use_esl, params["di_dt_a_s"])
        r["total_c_uf"] = round(c_farad * 1e6, 2) if c_farad else 0
        r["z_target_mohm"] = round((ripple / i_step) * 1000, 2) if i_step else float("inf")
        r["esr_eq_mohm"] = round(esr_eq * 1000, 2) if esr_eq is not None else None
        r["esl_eq_nh"] = round(esl_eq * 1e9, 3) if esl_eq is not None else None
        r["esr_used_mohm"] = round(use_esr * 1000, 2)
        r["esl_used_nh"] = round(use_esl * 1e9, 3)
        r["cap_count"] = len(caps)
        r["cap_hit_count"] = len(cap_params)
        net_droop[net] = r
    return {
        "params": params,
        "cap_map": {k: round(v * 1e6, 2) for k, v in cap_map.items()},
        "net_droop": net_droop,
    }


def estimate_loop_esl_by_xy(netlist_data, xy_components, per_mm_nh=0.8, via_count=2,
                             coord_in_mil=True):
    """用 xy.xlsx 坐标算每个电源网络的"安装环路 ESL"（ESL 缺失的大头）。

    物理背景：去耦电容的有效 ESL = 电容自身 ESL + 安装环路电感。环路电感
    由"电容→IC"的物理距离决定，距离越远环路电感越大。本函数用 xy.xlsx 的
    精确坐标算出每个电源网络上"IC 与其最近电容的最坏距离"，再套
    loop_esl_from_distance 得到该网络的安装环路 ESL。

    参数:
        netlist_data: 已解析的 netlist（含 components/nets）
        xy_components: pcb_deliverables.parse_xy_xlsx 的返回值
                       （list，每项 vals[0]=PartType, vals[1]=RefDes,
                        vals[6]=X, vals[7]=Y）
        per_mm_nh: 每 mm 回路电感（见 loop_esl_from_distance）
        via_count: 回路过孔数
        coord_in_mil: True 表示 xy 坐标单位是 mil（PADS 默认），会 ×0.0254 转 mm；
                      False 表示坐标已是 mm（KiCad/Altium 某些导出）

    返回:
        {net_name: loop_esl_nh}；无坐标/无 IC 的网络返回 None 值。

    重要：PADS 的 xy.xlsx 坐标默认是 mil（密尔），1 mil = 0.0254 mm。若直接
    当 mm 用会把距离放大 39.37 倍，环路 ESL 严重失真。
    """
    import math

    def to_mm(v):
        return v * 0.0254 if coord_in_mil else v

    # 1. xy 坐标：ref → (x, y)，单位归一为 mm
    pos = {}
    is_ic = set()
    is_cap = set()
    for c in xy_components:
        ref = c[1] if len(c) > 1 else ""
        if not ref:
            continue
        try:
            x, y = to_mm(float(c[6])), to_mm(float(c[7]))
        except (ValueError, IndexError):
            continue
        pos[ref] = (x, y)
        pref = ""
        m = re.match(r"^([A-Za-z]+)", ref)
        if m:
            pref = m.group(1).upper()
        if pref == "U":
            is_ic.add(ref)
        elif pref in ("C", "EC"):
            is_cap.add(ref)

    cap_xy = [(pos[r][0], pos[r][1], r) for r in is_cap if r in pos]

    # 2. netlist：电源网络 → 该网络上的 IC ref 集合
    net_ics = {}
    for net in netlist_data.get("nets", []):
        name = net.get("name", "")
        if not is_power_net(name):
            continue
        ics = set()
        for node in net.get("nodes", []):
            ref = node.get("ref", "")
            if ref in is_ic:
                ics.add(ref)
        net_ics[name] = ics

    # 3. 对每个电源网络，取"最近电容距离最大"的 IC 的环路 ESL（最坏路径）
    result = {}
    for net, ics in net_ics.items():
        worst_dist = None
        for ref in ics:
            p = pos.get(ref)
            if not p or not cap_xy:
                continue
            dmin = min(math.hypot(p[0] - cx, p[1] - cy) for cx, cy, _ in cap_xy)
            if worst_dist is None or dmin > worst_dist:
                worst_dist = dmin
        if worst_dist is None:
            result[net] = None
        else:
            result[net] = loop_esl_from_distance(worst_dist, per_mm_nh, via_count)
    return result




def analyze_ipc2581_data(xml_path):
    """解析 IPC-2581 并用公式库计算过孔电感、差分阻抗等（接入公式库）。

    返回: dict（含 components/nets/vias/diff_pairs/stackup + calculations）
    """
    if not GERBER_IPC_SUPPORT:
        return {"error": "IPC-2581 解析器不可用"}
    result = parse_ipc2581(xml_path)
    if "error" in result:
        return result
    if CALC_SUPPORT:
        via_l_nh = via_inductance(1.6, 0.3)  # 典型：1.6mm 板厚 / 0.3mm 过孔
        z0 = microstrip_impedance(0.25, 0.2, 0.035, 4.5)  # 典型微带线
        z_diff = differential_impedance(z0, 0.1)
        result["calculations"] = {
            "via_inductance_nh": round(via_l_nh, 2),
            "microstrip_z0_ohm": round(z0, 1),
            "differential_z_ohm": round(z_diff, 1),
            "note": "过孔电感/阻抗为典型参数估算（1.6mm板厚/0.3mm过孔/0.25mm走线/4.5εr），需按实际叠层校正",
        }
    return result


def analyze_gerber_data(gerber_dir):
    """解析 Gerber 走线并用公式库计算走线电感、传播延迟等（接入公式库）。

    返回: dict（含 traces/total_length/layer_count + calculations）
    """
    if not GERBER_IPC_SUPPORT:
        return {"error": "Gerber 解析器不可用"}
    result = parse_gerber_traces(gerber_dir)
    if "error" in result:
        return result
    if CALC_SUPPORT:
        total = result.get("total_length", 0)
        l_nh = trace_inductance(total, 1.0) if total > 0 else 0
        t_pd = propagation_delay(total, 4.5) if total > 0 else 0
        result["calculations"] = {
            "trace_inductance_nh": round(l_nh, 2),
            "propagation_delay_ps": round(t_pd, 1),
            "note": "走线电感/延迟按总长度 + 典型参数估算（±20~30%），需按实际走线校正",
        }
    return result


def analyze_power_signal_calc(args):
    """用公式库做电源/信号完整性估算（基于 CLI 参数 + 典型值）。

    返回: dict（各项计算结果，标注假设）
    """
    if not CALC_SUPPORT:
        return {"error": "公式库不可用"}
    istep = args.istep
    ripple_v = args.ripple_mv / 1000.0
    trise_ns = args.trise_us * 1000.0  # us -> ns
    calc = {}

    # 电源完整性（PDN 目标阻抗 + 去耦电容）
    z_target = pdn_target_impedance(ripple_v, istep)
    calc["pdn_target_impedance_mohm"] = round(z_target, 2)
    calc["decoupling_cap_1MHz_uf"] = round(decoupling_capacitor_value(z_target, 1e6), 3)

    # 信号完整性（无端接最大走线长度）
    calc["max_trace_no_term_mm"] = round(max_trace_length_no_termination(trise_ns, 4.5), 1)

    # 走线载流（1A / 10°C 温升 / 1oz）
    _, w_mm = trace_width_for_current(1.0, 10, 1.0)
    calc["trace_width_1A_mm"] = round(w_mm, 2)

    # 走线压降（50mm / 1mm / 1oz / 1A）
    _, r_mohm = trace_resistance(50, 1.0, 1.0)
    _, v_mv = voltage_drop(1.0, r_mohm)
    calc["trace_50mm_1A_drop_mv"] = round(v_mv, 1)

    # 走线温升（1A / 50mm / 1mm / 1oz）
    calc["trace_temp_rise_c"] = round(temperature_rise(1.0, 50, 1.0, 1.0), 1)

    # PCB 平面电容（100mm² / 0.2mm / 4.5）
    calc["pcb_plane_cap_pf"] = round(pcb_capacitance(100, 0.2, 4.5), 1)

    # 晶振负载电容（18pF + 18pF + 5pF 寄生）
    calc["crystal_load_cap_pf"] = round(crystal_load_capacitance(18, 18, 5), 1)

    # EMI 估算（100mA / 100mm² 环路 / 13.56MHz / 3m）
    calc["emi_13p56MHz_dBuv"] = round(emi_radiation_estimate(0.1, 100, 13.56e6, 3), 1)

    calc["note"] = "以上为典型参数估算（1A/1oz铜/4.5εr），需按实际设计校正"
    return calc


def analyze_signals(classified):
    """信号完整性分析：USB/显示/存储/通信信号网络分类统计。"""
    signal_cats = ["usb", "display", "storage", "comm"]
    result = {}
    for cat in signal_cats:
        nets = classified.get(cat, {})
        result[cat] = {
            "count": sum(nets.values()),
            "net_names": sorted(nets.keys())
        }
    return result


def analyze_clocks(classified, devices):
    """时钟分析：时钟网络 + 晶振/振荡器器件。"""
    clock_nets = classified.get("clock", {})
    return {
        "clock_net_count": sum(clock_nets.values()),
        "clock_nets": sorted(clock_nets.keys()),
        "crystal_count": devices.get("Crystal", 0),
        "crystal_names": sorted(devices.get("Crystal_names", set()))[:10],
    }


def analyze_interfaces(classified, devices):
    """接口分析：USB/SATA/HDMI/以太网等接口信号与连接器。"""
    interfaces = {
        "USB":     sum(classified.get("usb", {}).values()),
        "显示":     sum(classified.get("display", {}).values()),
        "存储":     sum(classified.get("storage", {}).values()),
        "通信":     sum(classified.get("comm", {}).values()),
        "以太网":   devices.get("Ethernet", 0),
    }
    return {
        "interface_signals": interfaces,
        "connector_count": devices.get("Connector", 0),
        "connector_names": sorted(devices.get("Connector_names", set()))[:10],
    }


def generate_risks(classified, devices, comp_refs):
    """风险提示引擎：基于通用设计检查表的启发式检查。
    仅依据可扫描信息给出提示，并注明推断性质。"""
    risks = []
    # 1. ESD/TVS 保护
    if devices.get("ESD", 0) == 0:
        risks.append({"severity": "high",
                      "item": "ESD/TVS保护",
                      "desc": "未在原理图中发现ESD/TVS保护器件（可能漏检或缺失），建议核查所有外部接口"})
    # 2. 保险丝
    if devices.get("Fuse", 0) == 0:
        risks.append({"severity": "medium",
                      "item": "保险丝/FUSE",
                      "desc": "未发现保险丝（可能漏检或使用可恢复保险），建议核查电源输入保护"})
    # 3. 时钟器件
    if devices.get("Crystal", 0) == 0:
        risks.append({"severity": "medium",
                      "item": "晶振/时钟",
                      "desc": "未发现晶振/振荡器（可能漏检或使用外部时钟源）"})
    # 4. 电源使能
    en_nets = classified.get("control", {})
    en_count = sum(1 for n in en_nets if "EN" in n.upper())
    if en_count == 0:
        risks.append({"severity": "info",
                      "item": "电源使能控制",
                      "desc": "未发现电源使能(EN)信号，多路电源可能无法独立控制"})
    # 5. 电源域数量
    power_count = len(classified.get("power", {}))
    ldo_dcdc = devices.get("LDO", 0) + devices.get("DCDC", 0)
    if power_count > 0 and ldo_dcdc == 0:
        risks.append({"severity": "info",
                      "item": "电源转换器件",
                      "desc": f"识别到{power_count}个电源网络但未发现LDO/DCDC器件（可能漏检），请核查电源树"})
    # 6. 电池
    if devices.get("Battery", 0) == 0 and "VBAT" in str(classified.get("power", {})):
        risks.append({"severity": "info",
                      "item": "RTC电池",
                      "desc": "检测到VBAT网络但未发现电池器件，如需要RTC掉电保持请核查"})
    # 汇总统计
    total_refs = len(comp_refs)
    if total_refs == 0:
        risks.append({"severity": "critical",
                      "item": "元件识别",
                      "desc": "未能识别到任何元件，文件可能不是有效的原理图或格式不支持"})
    return risks


def build_report(analysis, output_dir, mode):
    """生成HTML报告到工具自己的 reports 目录。绝不写硬件目录。"""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    src_name = Path(analysis.get("source", "unknown")).name
    report_path = out / f"analysis_{src_name}_{mode}_{ts}.html"

    # 各区块HTML
    power_rows = "".join(
        f"<tr><td>{n}</td><td>{c}</td></tr>"
        for n, c in list(analysis.get("power_nets", {}).items())[:40])
    domain_rows = ""
    for dom, info in analysis.get("voltage_domains", {}).items():
        nets = "、".join(list(info["nets"].keys())[:6])
        domain_rows += (f"<tr><td><b>{dom}</b></td><td>{info['count']}</td>"
                        f"<td>{nets}{'...' if len(info['nets'])>6 else ''}</td></tr>")
    pdn_rows = "".join(
        f"<tr><td>{n}</td><td>{i.get('target_impedance_mohm')} mΩ</td>"
        f"<td>{i.get('note','')}</td></tr>"
        for n, i in analysis.get("pdn_targets", {}).items())
    sig_rows = ""
    for cat, info in analysis.get("signal_analysis", {}).items():
        nets = "、".join(info.get("net_names", [])[:8])
        sig_rows += (f"<tr><td>{cat}</td><td>{info.get('count',0)}</td>"
                     f"<td>{nets}{'...' if len(info.get('net_names',[]))>8 else ''}</td></tr>")
    clock_rows = f"<tr><td>时钟网络</td><td>{analysis.get('clock_analysis',{}).get('clock_net_count',0)}</td></tr>" \
                 f"<tr><td>晶振/振荡器</td><td>{analysis.get('clock_analysis',{}).get('crystal_count',0)}</td></tr>"
    iface_rows = "".join(
        f"<tr><td>{k}</td><td>{v}</td></tr>"
        for k, v in analysis.get("interface_analysis", {}).get("interface_signals", {}).items())
    val_rows = ""
    for cat in ["电容", "电阻", "电感"]:
        top = sorted(analysis.get("values", {}).get(cat, {}).items(),
                     key=lambda x: -x[1])[:10]
        val_rows += f"<tr><td>{cat}</td><td>{'、'.join(f'{v}({c})' for v,c in top) or '-'}</td></tr>"
    dev_rows = "".join(
        f"<tr><td>{cat}</td><td>{cnt}</td></tr>"
        for cat, cnt in analysis.get("devices", {}).items() if cnt > 0)
    risk_rows = "".join(
        f"<tr><td><span class='sev-{r.get('severity','info')}'>{r.get('severity','info')}</span></td>"
        f"<td>{r.get('item','')}</td><td>{r.get('desc','')}</td></tr>"
        for r in analysis.get("risks", []))
    
    # Netlist分析部分（如果有）
    netlist_section = ""
    if "netlist" in analysis and "error" not in analysis["netlist"]:
        nl = analysis["netlist"]
        
        # 去耦电容真实连接分析
        decoupling_rows = ""
        for ic_ref, caps in list(nl.get("decoupling_analysis", {}).items())[:15]:
            cap_list = "、".join([f"{c['cap_ref']}({c['net']})" for c in caps[:5]])
            decoupling_rows += f"<tr><td><b>{ic_ref}</b></td><td>{len(caps)}</td><td>{cap_list}</td></tr>"
        
        # 差分对
        diff_rows = ""
        for pair in nl.get("differential_pairs", [])[:20]:
            diff_rows += f"<tr><td>{pair['pair']}</td><td>{pair['p']}</td><td>{pair['n']}</td></tr>"
        
        # 电源网络连接
        power_net_rows = ""
        for pnet in nl.get("power_nets", [])[:10]:
            nodes = len(pnet.get("nodes", []))
            power_net_rows += f"<tr><td><b>{pnet['name']}</b></td><td>{nodes}</td></tr>"

        # 母线瞬态掉压（接入 calculators 公式库）
        droop_section = ""
        droop_info = nl.get("transient_droop", {})
        if droop_info.get("net_droop"):
            dp = droop_info.get("params", {})

            def _fmt(v):
                return "∞" if v == float("inf") else f"{v:.1f}"

            droop_rows = ""
            for net, r in droop_info["net_droop"].items():
                droop_rows += (f"<tr><td><b>{net}</b></td><td>{r.get('total_c_uf', '-')} uF</td>"
                               f"<td>{r.get('z_target_mohm', '-')} mΩ</td>"
                               f"<td>{_fmt(r.get('dv_c_mv'))} mV</td>"
                               f"<td>{_fmt(r.get('dv_esr_mv'))} mV</td>"
                               f"<td>{_fmt(r.get('dv_esl_mv'))} mV</td>"
                               f"<td><b>{_fmt(r.get('dv_total_mv'))} mV</b></td></tr>")
            droop_section = f"""
<h3>⚡ 母线瞬态掉压估算（ΔV_total = ΔV_C + ΔV_ESR + ΔV_ESL）</h3>
<table><tr><th>电源网络</th><th>总电容C</th><th>Z_target</th><th>ΔV_C</th><th>ΔV_ESR</th><th>ΔV_ESL</th><th>ΔV_total</th></tr>{droop_rows}</table>
<div class="warn"><b>参数假设：</b>I_step={dp.get('istep')}A、Δt={dp.get('delta_t_s')*1e6:.0f}us、ESR={"自动查表" if dp.get('esr_ohm') is None else f"{dp.get('esr_ohm')*1000:.0f}mΩ"}、ESL={"自动查表" if dp.get('esl_henry') is None else f"{dp.get('esl_henry')*1e9:.1f}nH"}、di/dt={dp.get('di_dt_a_s'):.0f}A/s。<br>
<b>说明：</b>总电容C来自 netlist 真实统计（位号C/EC开头且值可解析的电容求和）；ESR/ESL 未显式指定时按电容封装查表并并联等效（esr_eq/esl_eq），查不到用 10mΩ/1nH 兜底。ΔV_C 随 Δt 累积，ΔV_ESR 与电流大小成正比，ΔV_ESL 只在电流跳变瞬间产生尖峰。</div>"""

        netlist_section = f"""
<div class="card" style="border:2px solid #27ae60;"><h2>🔗 Netlist真实连接分析</h2>
<p style="color:#27ae60;"><b>✅ 基于{nl['format']}格式netlist的精确分析（非启发式）</b></p>
<table><tr><th>统计项</th><th>数值</th></tr>
<tr><td>元件总数</td><td>{nl['total_components']}</td></tr>
<tr><td>网络总数</td><td>{nl['total_nets']}</td></tr>
<tr><td>电源网络</td><td>{len(nl['power_nets'])}</td></tr>
<tr><td>地网络</td><td>{len(nl['gnd_nets'])}</td></tr>
<tr><td>分析IC数量</td><td>{len(nl['decoupling_analysis'])}</td></tr>
<tr><td>识别差分对</td><td>{len(nl['differential_pairs'])}</td></tr>
</table>

<h3>去耦电容精确匹配（真实连接）</h3>
<table><tr><th>IC位号</th><th>去耦电容数</th><th>电容列表（网络）</th></tr>{decoupling_rows}</table>
<div class="warn"><b>说明：</b>此表基于netlist真实连接关系，非坐标距离推测。</div>

<h3>差分对识别</h3>
<table><tr><th>差分对名称</th><th>正极网络</th><th>负极网络</th></tr>{diff_rows}</table>

<h3>电源网络连接数</h3>
<table><tr><th>电源网络</th><th>连接节点数</th></tr>{power_net_rows}</table>

{droop_section}

<h3>电源树拓扑可视化</h3>
<div class="warn"><b>电源转换器:</b> {nl.get('power_tree', {}).get('statistics', {}).get('total_converters', 0)} 个 | 
<b>电源轨道:</b> {nl.get('power_tree', {}).get('statistics', {}).get('total_power_rails', 0)} 个</div>
<div class="mermaid">{nl.get('mermaid_power_tree', '')}</div>
</div>"""

    # IPC-2581 分析部分（如果有）
    ipc2581_section = ""
    if analysis.get("ipc2581") and "error" not in analysis["ipc2581"]:
        ipc = analysis["ipc2581"]
        icalc = ipc.get("calculations", {})
        ipc_rows = (f"<tr><td>元件</td><td>{len(ipc.get('components', []))}</td></tr>"
                    f"<tr><td>网络</td><td>{len(ipc.get('nets', {}))}</td></tr>"
                    f"<tr><td>过孔</td><td>{len(ipc.get('vias', []))}</td></tr>"
                    f"<tr><td>差分对</td><td>{len(ipc.get('diff_pairs', []))}</td></tr>"
                    f"<tr><td>叠层</td><td>{len(ipc.get('stackup', []))}</td></tr>")
        icalc_rows = ""
        if icalc:
            icalc_rows = (f"<tr><td>过孔电感(典型)</td><td>{icalc.get('via_inductance_nh')} nH</td></tr>"
                          f"<tr><td>微带线阻抗(典型)</td><td>{icalc.get('microstrip_z0_ohm')} Ω</td></tr>"
                          f"<tr><td>差分阻抗(典型)</td><td>{icalc.get('differential_z_ohm')} Ω</td></tr>")
        ipc2581_section = f"""
<div class="card" style="border:2px solid #8e44ad;"><h2>📦 IPC-2581 完整设计数据分析</h2>
<table><tr><th>项目</th><th>数值</th></tr>{ipc_rows}</table>
<h3>公式库估算（典型参数）</h3>
<table><tr><th>项目</th><th>数值</th></tr>{icalc_rows}</table>
<div class="warn">{icalc.get('note', '')}</div>
</div>"""

    # Gerber 分析部分（如果有）
    gerber_section = ""
    if analysis.get("gerber") and "error" not in analysis["gerber"]:
        gb = analysis["gerber"]
        gcalc = gb.get("calculations", {})
        gerber_rows = (f"<tr><td>走线数量</td><td>{len(gb.get('traces', []))}</td></tr>"
                       f"<tr><td>总长度</td><td>{gb.get('total_length', 0)} mm</td></tr>"
                       f"<tr><td>层数</td><td>{gb.get('layer_count', 0)}</td></tr>")
        gcalc_rows = ""
        if gcalc:
            gcalc_rows = (f"<tr><td>走线电感(总长,典型)</td><td>{gcalc.get('trace_inductance_nh')} nH</td></tr>"
                          f"<tr><td>传播延迟(总长)</td><td>{gcalc.get('propagation_delay_ps')} ps</td></tr>")
        gerber_section = f"""
<div class="card" style="border:2px solid #f39c12;"><h2>🟧 Gerber 走线分析（±20% 估算）</h2>
<table><tr><th>项目</th><th>数值</th></tr>{gerber_rows}</table>
<h3>公式库估算</h3>
<table><tr><th>项目</th><th>数值</th></tr>{gcalc_rows}</table>
<div class="warn">{gcalc.get('note', '')}</div>
</div>"""

    # 电源/信号完整性计算摘要（公式库）
    calc_section = ""
    if analysis.get("calc_summary") and "error" not in analysis["calc_summary"]:
        cs = analysis["calc_summary"]
        cs_rows = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in cs.items() if k != "note")
        calc_section = f"""
<div class="card"><h2>📐 电源/信号完整性估算（公式库）</h2>
<table><tr><th>项目</th><th>数值</th></tr>{cs_rows}</table>
<div class="warn">{cs.get('note', '')}</div>
</div>"""

    html = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<title>硬件分析报告 - {src_name}</title>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
<script>mermaid.initialize({{startOnLoad:true}});</script>
<style>
body{{font-family:'Segoe UI',Arial,sans-serif;margin:0;background:#f0f2f5;color:#333}}
.container{{max-width:1200px;margin:0 auto;padding:20px}}
header{{background:linear-gradient(135deg,#1e3c72,#2a5298);color:#fff;padding:24px;border-radius:8px}}
h1{{margin:0}}h2{{color:#1e3c72;border-bottom:2px solid #1e3c72;padding-bottom:6px}}
.card{{background:#fff;padding:20px;margin:16px 0;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,.1)}}
table{{width:100%;border-collapse:collapse}}th,td{{padding:8px;text-align:left;border-bottom:1px solid #e3e6ea;font-size:14px}}
th{{background:#2a5298;color:#fff}}
.stat{{display:inline-block;margin:8px 24px 8px 0;font-size:14px}}.stat b{{font-size:26px;color:#1e3c72}}
.mermaid{{background:#fff;padding:20px;border:1px solid #e3e6ea;border-radius:8px;margin:16px 0}}
.sev-critical{{color:#fff;background:#d63031;padding:2px 8px;border-radius:10px}}
.sev-high{{color:#fff;background:#e17055;padding:2px 8px;border-radius:10px}}
.sev-medium{{color:#fff;background:#f39c12;padding:2px 8px;border-radius:10px}}
.sev-info{{color:#fff;background:#0984e3;padding:2px 8px;border-radius:10px}}
.warn{{background:#fff3cd;border-left:4px solid #ffc107;padding:10px;margin:8px 0}}
footer{{text-align:center;padding:16px;color:#888;font-size:13px}}
</style></head><body><div class="container">
<header><h1>🔧 硬件分析报告</h1>
<p>源文件：{analysis.get('source','-')}</p>
<p>生成：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ｜ 格式：{analysis.get('format','-')} ｜ 大小：{analysis.get('file_size',0)} 字节 ｜ 模式：{mode} ｜ 设计工具：{', '.join(analysis.get('tools',['未知']))}</p></header>
<div class="card"><h2>总览</h2>
<span class="stat"><b>{len(analysis.get('comp_refs',{}))}</b><br>元件引用</span>
<span class="stat"><b>{len(analysis.get('power_nets',{}))}</b><br>电源网络</span>
<span class="stat"><b>{analysis.get('gnd_signal_count',0)}</b><br>地网络引用</span>
<span class="stat"><b>{len(analysis.get('risks',[]))}</b><br>风险提示</span>
</div>
<div class="card"><h2>⚠️ 风险提示（启发式，需人工复核）</h2>
<table><tr><th>级别</th><th>检查项</th><th>说明</th></tr>{risk_rows}</table>
<div class="warn">风险基于字符串扫描的启发式推断，可能因二进制格式漏检而误报；请结合原理图人工复核。</div></div>
{netlist_section}
{ipc2581_section}
{gerber_section}
{calc_section}
<div class="card"><h2>🔋 电源分析</h2>
<h3>电压域分组</h3><table><tr><th>电压域</th><th>引用数</th><th>网络示例</th></tr>{domain_rows}</table>
<h3>PDN目标阻抗（估算）</h3><table><tr><th>电源网络</th><th>目标阻抗</th><th>说明</th></tr>{pdn_rows}</table></div>
<div class="card"><h2>📶 信号分析</h2><table><tr><th>类别</th><th>信号数</th><th>网络示例</th></tr>{sig_rows}</table></div>
<div class="card"><h2>⏱ 时钟分析</h2><table><tr><th>项目</th><th>数量</th></tr>{clock_rows}</table></div>
<div class="card"><h2>🔌 接口分析</h2><table><tr><th>接口类型</th><th>信号数</th></tr>{iface_rows}</table></div>
<div class="card"><h2>🔩 元件统计</h2>
<h3>元件值Top</h3><table><tr><th>类别</th><th>Top值</th></tr>{val_rows}</table>
<h3>关键器件</h3><table><tr><th>类型</th><th>出现次数</th></tr>{dev_rows}</table></div>
<div class="warn"><b>重要说明：</b>本文件为 {analysis.get('format','未知')}，工具已做<b>只读扫描分析</b>。
如需网表级完整DRC（去耦、时序、阻抗等），请在 OrCAD Capture 中导出 netlist 或 ASCII 原理图后再分析。</div>
<footer>由 Hardware Analyzer 生成 ｜ 只读分析，未修改任何硬件文件</footer>
</div></body></html>"""
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html)
    return report_path


def main():
    parser = argparse.ArgumentParser(
        description="硬件分析工具（只读，纯标准库）",
        epilog="示例: python main.py -s 'path/to/schematics/*.sch' -m full")
    parser.add_argument("--schematic", "-s", help="原理图路径，支持通配符")
    parser.add_argument("--netlist", "-n", help="Netlist文件路径（KiCad .net / Allegro .net / PADS2000 .asc，自动检测格式）")
    parser.add_argument("--mode", "-m", default="full",
                        choices=["full", "power", "signal", "clock", "interface", "diagnostic"],
                        help="分析模式（默认 full）")
    parser.add_argument("--output", "-o", default="reports/", help="报告输出目录（工具自身目录）")
    # 母线瞬态掉压估算参数（接入 calculators 公式库）
    parser.add_argument("--istep", type=float, default=1.0,
                        help="瞬态电流阶跃 I_step(A)，用于母线掉压估算（默认 1.0）")
    parser.add_argument("--dt-us", type=float, default=10.0,
                        help="负载持续时间 Δt(us)，用于 ΔV_C（默认 10.0）")
    parser.add_argument("--trise-us", type=float, default=1.0,
                        help="电流上升时间 t_rise(us)，di/dt = I_step/t_rise（默认 1.0）")
    parser.add_argument("--esr-mohm", type=float, default=None,
                        help="电容等效串联电阻 ESR(mΩ)；不填则按封装自动查表，查不到时用 10mΩ 兜底")
    parser.add_argument("--esl-nh", type=float, default=None,
                        help="电容等效串联电感 ESL(nH)；不填则按封装自动查表，查不到时用 1nH 兜底")
    parser.add_argument("--ripple-mv", type=float, default=50.0,
                        help="允许纹波/跌落 V_ripple(mV)，用于 Z_target（默认 50.0）")
    parser.add_argument("--ipc2581", type=str, default=None,
                        help="IPC-2581 XML 文件路径（元件坐标/引脚级网络/过孔层对/差分对/叠层）")
    parser.add_argument("--gerber", type=str, default=None,
                        help="Gerber 文件目录（走线长度估算）")
    parser.add_argument("--deliverables", "-d", type=str, default=None,
                        help="PCB交付件目录（自动递归查找 xy.xlsx、*.ipc、*.dxf 等文件）")
    args = parser.parse_args()
    
    # 至少需要原理图、netlist或PCB交付件之一
    if not args.schematic and not args.netlist and not args.deliverables:
        parser.error("必须提供 --schematic、--netlist 或 --deliverables 参数之一")

    print("=" * 66)
    print("  Hardware Analyzer - 硬件分析工具")
    print("  纯标准库 ｜ 只读模式")
    print("=" * 66)
    config = load_config()
    
    # Netlist分析（如果提供）
    netlist_result = None
    if args.netlist:
        netlist_result = analyze_netlist(args.netlist)
        if "error" in netlist_result:
            print(f"[错误] Netlist解析失败: {netlist_result['error']}")
            if not args.schematic:
                sys.exit(1)
        else:
            print(f"[Netlist] ✅ 解析成功")
            # 母线瞬态掉压估算（接入 calculators 公式库，对每个电源网络出数字）
            if CALC_SUPPORT:
                transient_params = {
                    "istep": args.istep,
                    "delta_t_s": args.dt_us * 1e-6,
                    "esr_ohm": (args.esr_mohm / 1000.0) if args.esr_mohm is not None else None,
                    "esl_henry": (args.esl_nh * 1e-9) if args.esl_nh is not None else None,
                    "di_dt_a_s": args.istep / (args.trise_us * 1e-6),
                    "ripple_v": args.ripple_mv / 1000.0,
                }
                netlist_result["transient_droop"] = analyze_transient_droop(netlist_result, transient_params)
                n_droop = len(netlist_result["transient_droop"]["net_droop"])
                print(f"[母线掉压] 已计算 {n_droop} 个电源网络的瞬态掉压（ΔV_C + ΔV_ESR + ΔV_ESL）")

    # IPC-2581 分析（如果提供）
    ipc2581_result = None
    if args.ipc2581:
        ipc2581_result = analyze_ipc2581_data(args.ipc2581)
        if "error" in ipc2581_result:
            print(f"[IPC-2581] ❌ {ipc2581_result['error']}")
        else:
            print(f"[IPC-2581] ✅ 元件{len(ipc2581_result.get('components', []))} | "
                  f"网络{len(ipc2581_result.get('nets', {}))} | "
                  f"过孔{len(ipc2581_result.get('vias', []))} | "
                  f"差分对{len(ipc2581_result.get('diff_pairs', []))}")

    # Gerber 分析（如果提供）
    gerber_result = None
    if args.gerber:
        gerber_result = analyze_gerber_data(args.gerber)
        if "error" in gerber_result:
            print(f"[Gerber] ❌ {gerber_result['error']}")
        else:
            print(f"[Gerber] ✅ 走线{len(gerber_result.get('traces', []))} | "
                  f"总长{gerber_result.get('total_length', 0)}mm | "
                  f"层数{gerber_result.get('layer_count', 0)}")
    
    # PCB交付件分析（如果提供）
    deliverables_result = None
    deliverables_report = None
    if args.deliverables:
        from pathlib import Path
        deliverables_path = Path(args.deliverables)
        if not deliverables_path.exists():
            print(f"[PCB交付件] ❌ 目录不存在: {args.deliverables}")
        else:
            print(f"\n[PCB交付件] 开始分析目录: {deliverables_path}")
            try:
                from pcb_deliverables import analyze_deliverables, build_pcb_report
                deliverables_result = analyze_deliverables(str(deliverables_path))

                # 汇总各交付件数量（key 名与 pcb_deliverables.analyze_deliverables 返回值一致）
                comp_list = deliverables_result.get("components") or []
                nets = deliverables_result.get("nets") or {}
                print(f"[PCB交付件] 元件: {len(comp_list)} | 网络: {len(nets)}")

                if deliverables_result.get("validation"):
                    v = deliverables_result["validation"]
                    if v.get("warnings"):
                        for warn in v["warnings"]:
                            print(f"[PCB交付件] ⚠️ {warn}")
                    if v.get("errors"):
                        for err in v["errors"]:
                            print(f"[PCB交付件] ❌ {err}")

                if deliverables_result.get("errors"):
                    for err in deliverables_result["errors"]:
                        print(f"[PCB交付件] ⚠️ {err}")

                # 生成 PCB 报告（写 Excel/HTML 到输出目录）
                deliverables_report = build_pcb_report(
                    deliverables_result, args.output, str(deliverables_path))
                print(f"[PCB交付件] ✅ 报告: {deliverables_report}")
            except ImportError as e:
                print(f"[PCB交付件] ❌ 缺少 pcb_deliverables 模块: {e}")
            except Exception as e:
                print(f"[PCB交付件] ❌ 分析失败: {type(e).__name__}: {e}")


    # 电源/信号完整性估算（公式库）
    calc_summary = analyze_power_signal_calc(args) if CALC_SUPPORT else None

    # 原理图分析（如果提供）
    if not args.schematic:
        # 仅netlist模式
        print("\n[模式] 仅Netlist分析（无原理图）")
        # 终端输出母线瞬态掉压（接入 calculators 公式库）
        droop_info = (netlist_result or {}).get("transient_droop", {})
        if droop_info.get("net_droop"):
            dp = droop_info.get("params", {})

            def _f(v):
                return "∞" if v == float("inf") else f"{v:.1f}"

            # ESR/ESL 显示：None = 自动查表；数值 = 用户显式
            esr_disp = "自动查表" if dp.get('esr_ohm') is None else f"{dp.get('esr_ohm')*1000:.0f}mΩ"
            esl_disp = "自动查表" if dp.get('esl_henry') is None else f"{dp.get('esl_henry')*1e9:.1f}nH"

            print("\n" + "=" * 70)
            print("⚡ 母线瞬态掉压估算（ΔV_total = ΔV_C + ΔV_ESR + ΔV_ESL）".center(64))
            print("=" * 70)
            print(f"参数: I_step={dp.get('istep')}A  Δt={dp.get('delta_t_s')*1e6:.0f}us  "
                  f"ESR={esr_disp}  ESL={esl_disp}  "
                  f"di/dt={dp.get('di_dt_a_s'):.0f}A/s  V_ripple={dp.get('ripple_v')*1000:.0f}mV")
            print("-" * 70)
            print(f"{'电源网络':<18}{'总电容C':>10}{'Z_target':>10}{'ESR@':>8}{'ESL@':>8}{'ΔV_C':>10}{'ΔV_ESR':>9}{'ΔV_ESL':>9}{'ΔV_total':>10}")
            for net, r in droop_info["net_droop"].items():
                esr_us = f"{r.get('esr_used_mohm', 0):.1f}m" if r.get('esr_used_mohm') is not None else "-"
                esl_us = f"{r.get('esl_used_nh', 0):.2f}n" if r.get('esl_used_nh') is not None else "-"
                print(f"{net:<18}{r.get('total_c_uf', 0):>9.2f}uF"
                      f"{r.get('z_target_mohm', 0):>9.0f}mΩ"
                      f"{esr_us:>8}"
                      f"{esl_us:>8}"
                      f"{_f(r.get('dv_c_mv')):>10}"
                      f"{_f(r.get('dv_esr_mv')):>9}"
                      f"{_f(r.get('dv_esl_mv')):>9}"
                      f"{_f(r.get('dv_total_mv')):>10}")
            print("-" * 70)
            print("说明: 总电容C来自netlist真实统计；ESR@/ESL@ 为本次计算实际采用的等效值。")
            print("      ESR/ESL 未显式指定时按封装查表并联等效（见 esr_eq/esl_eq），查不到用 10mΩ/1nH 兜底。")
            print("      ΔV_C随Δt累积，ΔV_ESR与电流大小成正比，ΔV_ESL只在电流跳变瞬间产生尖峰。")
        # 终端输出电源/信号完整性估算（公式库）
        if calc_summary and "error" not in calc_summary:
            print("\n" + "=" * 70)
            print("📐 电源/信号完整性估算（公式库）".center(64))
            print("=" * 70)
            for k, v in calc_summary.items():
                if k == "note":
                    print(f"  说明: {v}")
                else:
                    print(f"  {k}: {v}")
        print("[完成] Netlist分析完成")
        return
    
    files = resolve_schematic_paths(args.schematic)
    if not files:
        print(f"[错误] 未找到匹配的原理图文件: {args.schematic}")
        sys.exit(1)

    print(f"[输入] 匹配到 {len(files)} 个文件:")
    for f in files:
        print(f"       - {f}")

    for f in files:
        print(f"\n[分析] {f}")
        fmt = detect_format(f)
        print(f"[格式] {fmt}")
        strings, fsize = read_strings(f)
        print(f"[扫描] 提取 {len(strings)} 个字符串，文件 {fsize} 字节")

        # 基础提取
        comp_refs, values = extract_components(strings)
        classified = classify_nets(strings)
        devices, device_names, tools = identify_devices(strings)
        risks = generate_risks(classified, devices, comp_refs)

        # 组装分析结果
        analysis = {
            "source": f, "format": fmt, "file_size": fsize,
            "comp_refs": comp_refs, "values": values,
            "devices": devices, "tools": tools,
            "risks": risks,
            **analyze_power(classified, config),
            **{"signal_analysis": analyze_signals(classified),
               "clock_analysis": analyze_clocks(classified, devices),
               "interface_analysis": analyze_interfaces(classified, devices)},
        }
        
        # 集成netlist分析结果
        if netlist_result and "error" not in netlist_result:
            analysis["netlist"] = netlist_result
            print(f"[增强] Netlist数据已集成到报告")

        # 集成 IPC-2581 / Gerber / 计算摘要
        if ipc2581_result and "error" not in ipc2581_result:
            analysis["ipc2581"] = ipc2581_result
            print(f"[增强] IPC-2581数据已集成到报告")
        if gerber_result and "error" not in gerber_result:
            analysis["gerber"] = gerber_result
            print(f"[增强] Gerber数据已集成到报告")
        if calc_summary and "error" not in calc_summary:
            analysis["calc_summary"] = calc_summary
        
        # 执行方向分析（基于THEORY文档）
        if DIRECTION_ANALYZER_AVAILABLE and netlist_result and "error" not in netlist_result:
            print(f"[方向分析] 正在执行方向性诊断...")
            try:
                direction_analyzer = DirectionAnalyzer(
                    netlist_data={'netlist': netlist_result},
                    analysis_data=analysis
                )
                direction_result = direction_analyzer.analyze()
                
                # 集成到分析结果
                analysis['direction_analysis'] = direction_result
                
                # 终端输出方向分析报告
                print("\n")
                print(format_direction_report(direction_result))
                print("\n")
                
            except Exception as e:
                print(f"[警告] 方向分析失败: {e}")

        # 终端摘要
        print(f"[元件] {len(comp_refs)} 个引用 ｜ 类型分布: " +
              "、".join(f"{p}:{c}" for p, c in sorted(
                  {r[0]: sum(1 for x in comp_refs if x[0] == r[0])
                   for r in comp_refs}.items())))
        print(f"[电源] {len(analysis['power_nets'])} 个电源网络 ｜ "
              f"{len(analysis['voltage_domains'])} 个电压域 ｜ "
              f"地网络引用 {analysis['gnd_signal_count']}")
        print(f"[器件] " + "、".join(f"{k}={v}" for k, v in devices.items() if v > 0))
        print(f"[风险] {len(risks)} 条提示" +
              (f"（最高级别: {max(r['severity'] for r in risks)}）" if risks else ""))

        # 按模式输出侧重
        if args.mode in ("power",):
            print(f"[电源模式] PDN估算示例: " + "、".join(
                f"{n}:{i['target_impedance_mohm']}mΩ"
                for n, i in list(analysis["pdn_targets"].items())[:5]))
        if args.mode in ("signal",):
            print(f"[信号模式] " + "、".join(
                f"{cat}:{info['count']}" for cat, info in analysis["signal_analysis"].items()))
        if args.mode in ("clock",):
            ca = analysis["clock_analysis"]
            print(f"[时钟模式] 时钟网络 {ca['clock_net_count']} ｜ 晶振 {ca['crystal_count']}")
        if args.mode in ("interface",):
            ia = analysis["interface_analysis"]
            print(f"[接口模式] 连接器 {ia['connector_count']} ｜ " +
                  "、".join(f"{k}:{v}" for k, v in ia["interface_signals"].items()))
        if args.mode in ("diagnostic",):
            print("[诊断模式] 风险提示:")
            for r in risks:
                print(f"           [{r['severity']:>7}] {r['item']}: {r['desc']}")

        report = build_report(analysis, args.output, args.mode)
        print(f"[完成] 报告: {report}")

    print("\n" + "=" * 66)
    print("  分析完成。全部操作均为只读，未修改任何硬件文件。")
    print("=" * 66)


def main_pcb():
    """PCB交付件分析入口：python src/main.py --deliverables <目录>"""
    import argparse
    from pcb_deliverables import analyze_deliverables, build_pcb_report
    p = argparse.ArgumentParser(description="PCB交付件分析（xy.xlsx+IPC+DXF，只读）")
    p.add_argument("--deliverables", "-d", required=True,
                   help="投板交付件目录（含 xy.xlsx / .ipc / .dxf）")
    p.add_argument("--output", "-o", default="reports/", help="报告输出目录")
    args = p.parse_args()

    print("=" * 66)
    print("  PCB交付件分析 - 基于 EDA 交付文件（xy.xlsx + IPC-D-356 + DXF）")
    print("  只读分析，绝不修改被分析文件")
    print("=" * 66)
    results = analyze_deliverables(args.deliverables)
    if results["errors"]:
        print("\n[警告] " + "; ".join(results["errors"]))
    report = build_pcb_report(results, args.output, args.deliverables)
    print(f"\n[完成] PCB分析报告: {report}")
    print("=" * 66)


if __name__ == "__main__":
    # 兼容旧用法：只有 -d/--deliverables 且没有其他分析参数时，走 PCB 专用入口；
    # 否则统一走 main()（支持 -d 与原理图/netlist/模式/高级参数组合，供 Web GUI 调用）。
    _argv = sys.argv[1:]
    _pcb_only = (
        len(_argv) >= 1
        and _argv[0] in ("--deliverables", "-d")
        and not any(a in ("-s", "--schematic", "-n", "--netlist", "-m", "--mode",
                          "--istep", "--dt-us", "--trise-us", "--esr-mohm",
                          "--esl-nh", "--ripple-mv", "--ipc2581", "--gerber")
                    for a in _argv)
    )
    if _pcb_only:
        main_pcb()
    else:
        main()





