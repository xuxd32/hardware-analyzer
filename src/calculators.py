#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
硬件分析工具 - 计算器工具集
实现 PCB 工程经验核心计算公式
"""

import math
import re

# ========== 走线电阻与压降 ==========

def trace_resistance(length_mm, width_mm, thickness_oz=1.0, rho=0.0175):
    """计算 PCB 走线电阻
    公式: R(Ω) = ρ × L / (W × T)
    参数: length_mm走线长度, width_mm宽度, thickness_oz铜厚(1oz=0.035mm)
    返回: (R_ohm, R_mohm)

    准确性: ⭐⭐⭐⭐ 公式精确，误差来自 ρ 假设。
    ⚠️ 假设/边界（精确性红线）:
        - ρ=0.0175 Ω·mm²/m 是**纯铜 20°C** 电阻率；走线若含杂质/温度升高，ρ 会偏大
          （铜温升 100°C 时 ρ 约 +39%，电阻同步上升）。
        - 未计趋肤效应（高频时有效截面减小，电阻上升）。
        - 仅为直流欧姆阻值，非阻抗。
    """
    thickness_mm = thickness_oz * 0.035
    R_ohm = rho * (length_mm / 1000) / (width_mm * thickness_mm)
    return R_ohm, R_ohm * 1000

def voltage_drop(current_a, resistance_mohm):
    """计算压降
    公式: V_drop = I × R
    返回: (V_drop_v, V_drop_mv)"""
    V_drop_v = current_a * (resistance_mohm / 1000.0)
    return V_drop_v, V_drop_v * 1000

def trace_width_for_current(current_a, temp_rise_c=10, thickness_oz=1.0):
    """根据电流计算所需走线宽度
    公式: I(A) = 0.048 × ΔT^0.44 × A^0.725（IPC-2221A外层，A=W×T截面积）
    返回: (width_mil, width_mm)

    准确性: ⭐⭐⭐ 经验公式（IPC-2221A），典型 ±15% 误差。
    ⚠️ 假设/边界（精确性红线）:
        - k=0.048 是 IPC-2221A **外层走线** 的经验系数；内层走线散热差，需更宽
          （IPC-2221A 内层系数约 0.024，即同电流内层宽约加倍）。
        - 只考虑温升限流，未考虑压降限流（需另查 voltage_drop）。
        - 结果是最小宽度，实际设计应留余量。
    """
    k = 0.048  # IPC-2221A外层系数
    thickness_mil = thickness_oz * 1.37  # 1oz = 1.37mil
    area_mil2 = (current_a / (k * (temp_rise_c ** 0.44))) ** (1 / 0.725)
    width_mil = area_mil2 / thickness_mil
    width_mm = width_mil * 0.0254
    return width_mil, width_mm

def temperature_rise(current_a, length_mm, width_mm, thickness_oz=1.0):
    """计算走线温升
    返回: ΔT(°C)

    准确性: ⭐⭐ 数量级估算（±50% 或更大）。
    ⚠️ 假设/边界（精确性红线）:
        - thermal_resistance = 50 / area_cm2 是**极粗略的经验值**，依赖散热环境
          （内层/多层/通风/覆铜面积都会大幅改变），不可当精确温升。
        - 未计邻近走线互热、铜皮散热、过孔散热。
        - 仅用于趋势判断，精确温升需热仿真。
    """
    R_ohm, _ = trace_resistance(length_mm, width_mm, thickness_oz)
    P_watts = current_a ** 2 * R_ohm
    area_cm2 = (length_mm * width_mm) / 100
    thermal_resistance = 50 / area_cm2 if area_cm2 > 0 else 100
    delta_T = P_watts * thermal_resistance
    return delta_T

# ========== 电感与电容 ==========

def via_inductance(via_height_mm, via_diameter_mm):
    """计算过孔电感
    公式: L ≈ 5.08 × h(inch) × [ln(4h/d) + 1] (nH)

    准确性: ⭐⭐⭐ 经验近似（±30%）。
    ⚠️ 假设/边界（精确性红线）:
        - 5.08 系数是孤立圆柱过孔的电感经验近似，未计回流路径、邻近过孔互感。
        - 实际回路电感取决于电流回流地的位置，孤立过孔电感 ≠ 回路电感。
        - 仅趋势值，精确值需场求解器（PowerSI/SIwave）。
    """
    h = via_height_mm / 25.4  # mm -> inch
    d = via_diameter_mm / 25.4  # mm -> inch
    if d <= 0: return 0
    return 5.08 * h * (math.log(4 * h / d) + 1)

def pcb_capacitance(area_mm2, thickness_mm, epsilon_r=4.5):
    """计算 PCB 平面间电容
    公式: C = ε₀ × εᵣ × A / d
    返回: C(pF)"""
    epsilon_0 = 8.854e-12
    area_m2 = area_mm2 / 1e6
    thickness_m = thickness_mm / 1000
    C_f = epsilon_0 * epsilon_r * area_m2 / thickness_m
    return C_f * 1e12

def crystal_load_capacitance(c1_pf, c2_pf, c_stray_pf=5):
    """计算晶振负载电容
    公式: CL = C1 × C2 / (C1 + C2) + Cstray"""
    if c1_pf + c2_pf == 0: return c_stray_pf
    return c1_pf * c2_pf / (c1_pf + c2_pf) + c_stray_pf

def crystal_capacitor_value(cl_spec_pf, c_stray_pf=5):
    """反推晶振外接电容值（已知CL规格）
    公式: C = (CL - Cstray) × 2（假设C1=C2=C）

    准确性: 公式精确；误差来自 Cstray 假设（默认 5pF，实际按 PCB 寄生校正）。
    """
    return max((cl_spec_pf - c_stray_pf) * 2, 0)

def trace_inductance(length_mm, width_mm, height_mm=0.2):
    """计算 PCB 走线寄生电感
    
    公式: L(nH) ≈ 0.2 × L × [ln(2L/(W+T)) + 0.5 + 0.2235×(W+T)/L]
    简化经验公式: L ≈ 1.0 nH/mm（保守估计，适用于大多数情况）
    
    参数:
        length_mm: 走线长度(mm)
        width_mm: 走线宽度(mm)
        height_mm: 介质厚度(mm)，默认0.2mm（典型表层走线）
    
    返回:
        L(nH)
    
    准确性: ⭐⭐⭐ 趋势准确（±30%误差）
    约束:
        - 假设微带线结构（表层走线）
        - 铜厚按1oz(0.035mm)估算
        - 不考虑邻近走线互感
        - 适用于length >> width的情况
    
    来源: Howard Johnson "High Speed Digital Design", Eq 3-1
    典型值: 1 nH/mm (保守), 0.7-1.2 nH/mm (实测范围)
    
    应用场景: 射频地回流路径分析、高速信号反射计算、交流压降估算
    
    示例:
        >>> trace_inductance(10, 1.0)  # 10mm走线
        10.0  # nH (简化公式)
        
        >>> # 13.56MHz NFC地路径分析
        >>> L_trace = trace_inductance(10, 1.0)  # 10mm地回流
        >>> L_via = via_inductance(1.6, 0.3)     # 1.30 nH
        >>> L_total = L_trace + L_via            # 11.3 nH
        >>> di_dt = 0.1 * 2 * 3.14159 * 13.56e6  # 8.5×10⁶ A/s
        >>> V_noise = L_total * 1e-9 * di_dt     # 96 mV
    """
    # 边界检查
    if length_mm <= 0 or width_mm <= 0:
        return 0.0
    
    # 简化保守公式：1 nH/mm（工程常用经验值）
    # 这个值在大多数情况下偏保守（高估电感）
    L_simple = length_mm * 1.0
    
    # 如果长度远大于宽度，使用更精确的平面导体公式
    # 但仍保持简化，避免复杂的耦合计算
    if length_mm > 5 * width_mm:
        # Wheeler近似公式（平面导体）
        # L ≈ 0.2 × length(mm) × [ln(2×length/(width+thickness)) + 0.5]
        # 假设1oz铜厚0.035mm
        thickness_mm = 0.035
        ratio = 2 * length_mm / (width_mm + thickness_mm)
        if ratio > 1:
            L_accurate = 0.2 * length_mm * (math.log(ratio) + 0.5)
            # 取简化值和精确值的平均（折中）
            return (L_simple + L_accurate) / 2
    
    # 短走线或宽走线，使用简化公式
    return L_simple

# ========== 阻抗计算 ==========

def microstrip_impedance(w_mm, h_mm, t_mm, epsilon_r=4.5):
    """微带线特性阻抗（Wheeler 近似公式）

    准确性: ⭐⭐⭐ 解析近似（Wheeler 公式，典型 ±2~5% 误差，取决于 w/h 比值）。
    ⚠️ 假设/边界（精确性红线）:
        - 假设均匀介质、理想微带（无限大参考平面）；实际边缘场、铜箔粗糙度、
          阻焊层会引入偏差。
        - 精确阻抗需场求解器或按 PCB 厂叠层表校正 ε_r。
    """
    w_eff = w_mm + (t_mm / math.pi) * (1 + math.log(2 * h_mm / t_mm))
    epsilon_eff = (epsilon_r + 1) / 2 + (epsilon_r - 1) / 2 * (1 + 10 * h_mm / w_eff) ** (-0.5)
    if w_eff / h_mm < 1:
        Z0 = 60 / math.sqrt(epsilon_eff) * math.log(8 * h_mm / w_eff + w_eff / (4 * h_mm))
    else:
        Z0 = 120 * math.pi / (math.sqrt(epsilon_eff) * (w_eff / h_mm + 1.393 + 0.667 * math.log(w_eff / h_mm + 1.444)))
    return Z0

def differential_impedance(z0_single, coupling_factor=0.1):
    """差分阻抗
    公式: Z_diff ≈ 2 × Z0 × √(1 - k)

    准确性: ⭐⭐⭐ 近似（默认耦合系数 k=0.1 是经验值，实际 k 取决于线间距/介质）。
    ⚠️ 假设/边界（精确性红线）:
        - coupling_factor 默认 0.1 是**经验近似**；真实差分耦合随线距减小而增强，
          精确值需按实际差分对间距用场求解器。
    """
    return 2 * z0_single * math.sqrt(1 - coupling_factor)

# ========== 电源完整性 ==========

def pdn_target_impedance(v_ripple_max, i_transient):
    """PDN 目标阻抗
    公式: Z_target = V_ripple_max / I_transient
    返回: Z(mΩ)"""
    if i_transient == 0: return float('inf')
    return (v_ripple_max / i_transient) * 1000

def decoupling_capacitor_value(z_target_mohm, frequency_hz):
    """估算所需去耦电容值
    公式: C = 1 / (2π × f × Z)
    返回: C(uF)

    准确性: ⭐⭐⭐ 单频点估算（仅在该频率点严格成立）。
    ⚠️ 假设/边界（精确性红线）:
        - 只算了**单一频率点**的所需电容；真实 PDN 需跨频率段（DC~几十MHz）阻抗
          都低于 Z_target，本公式是理想电容的下限近似。
        - 理想电容模型，未计 ESL/ESR 导致的高频阻抗回升（见 bus_droop 的 ESL 项）。
        - 结果用于量级估算，精确选型需频域阻抗仿真（PowerSI）。
    """
    z_ohm = z_target_mohm / 1000
    C_f = 1 / (2 * math.pi * frequency_hz * z_ohm)
    return C_f * 1e6

# ========== 信号完整性 ==========

def propagation_delay(length_mm, epsilon_r=4.5):
    """信号传播延迟
    公式: t_pd = L / (c/√εᵣ)
    返回: t_pd(ps)

    准确性: 公式精确；误差来自 ε_r 假设（默认 4.5，实际按叠层材料定）。
    """
    c = 299792458
    v = c / math.sqrt(epsilon_r)
    t_s = (length_mm / 1000) / v
    return t_s * 1e12

def max_trace_length_no_termination(rise_time_ns, epsilon_r=4.5):
    """无端接时的最大走线长度
    公式（经验法则）: L_max = t_rise × c / (6 × √εᵣ)
    返回: L_max(mm)

    准确性: ⭐⭐⭐ 经验法则（÷6 是工程近似，非绝对上限；精确值需 SI 仿真）。
    """
    c = 299792458
    v = c / math.sqrt(epsilon_r)
    L_m = (rise_time_ns * 1e-9) * v / 6
    return L_m * 1000

# ========== EMI 估算 ==========

def emi_radiation_estimate(current_a, loop_area_mm2, frequency_hz, distance_m):
    """EMI 辐射强度估算
    公式: E ≈ (I × A × f²) / (6π × r × c²)
    返回: E(dBμV/m)

    准确性: ⭐⭐ 数量级估算（误差可达 ±10dB 或更大）。
    ⚠️ 假设/边界（精确性红线）:
        - 是小环天线远场近似，假设理想小环、自由空间、无屏蔽/无参考平面。
        - 实际 PCB 有地平面、屏蔽罩、邻近走线，真实辐射与估算可差 10dB 以上。
        - 仅用于"哪条回路辐射风险高"的相对比较，**不可当实测 dBμV/m**；精确值需
          近场扫描或全波仿真。
    """
    c = 3e8
    A_m2 = loop_area_mm2 / 1e6
    E = (current_a * A_m2 * frequency_hz ** 2) / (6 * math.pi * distance_m * c ** 2)
    return 20 * math.log10(E * 1e6) if E > 0 else -float('inf')


# ========== 母线瞬态掉压（三段式：ΔV_C + ΔV_ESR + ΔV_ESL）==========

def parse_capacitance(value_str):
    """解析电容值字符串为法拉(F)。

    支持常见写法: 100nF / 10uF / 4.7uF / 0.1uF / 470pF / 1000uF / 10mF 等。
    解析失败返回 None（调用方据此跳过无法识别的值）。
    """
    if not isinstance(value_str, str):
        return None
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*([pnum]?[fF])\s*$", value_str.strip())
    if not m:
        return None
    num = float(m.group(1))
    unit = m.group(2).lower()
    factors = {"pf": 1e-12, "nf": 1e-9, "uf": 1e-6, "mf": 1e-3, "f": 1.0}
    return num * factors[unit]


def parse_capacitance_code(value_str):
    """解析 OrCAD 展开网表的电容"值代码"为法拉(F)。

    与 parse_capacitance()（解析 "100nF"/"10uF" 单位字符串）不同，本函数额外处理
    OrCAD 网表 pstchip.dat 里 VALUE 字段的几种真实写法：

    1. 三位 EIA 代码：104 → 100nF、105 → 1uF、106 → 10uF、226 → 22uF、475 → 4.7uF
       规则：前两位 × 10^第三位 pF（104 = 10 × 10^4 pF = 100nF）
    2. 显式单位：33PF / 22pF / 100pF / 470uF（大小写不敏感）
    3. 带后缀：470uF/50V（容值+耐压）、100pF_0R（容值+串联0欧）→ 截取主值解析
    4. 不焊接标记：NC / X7R / *NC / */NC（后缀缀有 NC）→ 返回 None（调用方跳过）

    返回: float 法拉；无法解析（含不焊接）返回 None。
    """
    if not isinstance(value_str, str):
        return None
    s = value_str.strip()
    if not s:
        return None

    # 纯占位符（不焊接/未指定/材质）直接跳过
    if s.upper() in ("NC", "X7R", "X5R", "C0G", "DNP", "N/A", "NA"):
        return None

    # 含"不焊接"标记（_NC、/NC）→ 跳过（该电容未上板，不应计入总电容）
    if re.search(r"(?:_NC|/NC|_NIC|/NIC)\b", s, re.IGNORECASE):
        return None

    # 剥掉耐压 /50V、串联 0 欧 _0R 等"非容值"后缀，得到主值片段
    # 例：470uF/50V → 470uF；100pF_0R → 100pF；475/6.3V → 475
    main = s
    main = re.sub(r"[/_]\d+(?:\.\d+)?\s*[vV]\b.*$", "", main)   # 去掉 /50V 等耐压
    main = re.sub(r"_0?[rR]\b.*$", "", main)                    # 去掉 _0R 串联电阻
    main = re.sub(r"[/_].*$", "", main)                          # 其余 /xxx、_xxx 一律去掉
    main = main.strip()
    if not main:
        return None

    # 显式单位（大小写不敏感）：33PF / 22pF / 100pF / 470uF ...
    m = re.match(r"^(\d+(?:\.\d+)?)\s*([pnum]?[fF])$", main, re.IGNORECASE)
    if m:
        num = float(m.group(1))
        unit = m.group(2).lower()
        factors = {"pf": 1e-12, "nf": 1e-9, "uf": 1e-6, "mf": 1e-3, "f": 1.0}
        return num * factors[unit]

    # 三位 EIA 代码：纯数字（含 103/104/105/106/226/475/393 等）
    m = re.match(r"^(\d{3})$", main)
    if m:
        code = m.group(1)
        mantissa = int(code[0:2])
        exp = int(code[2])
        return mantissa * (10 ** exp) * 1e-12

    return None




def bus_droop(c_total_farad, i_step_a, delta_t_s, esr_ohm, esl_henry, di_dt_a_s):
    """母线瞬态掉压三段式估算（真实电容等效模型 = C + ESR + ESL 三者串联）。

    公式:
        ΔV_C    = I_step × Δt / C           （电容充放电，随持续时间 Δt 累积）
        ΔV_ESR  = I_step × ESR              （欧姆压降，与电流大小成正比）
        ΔV_ESL  = ESL × di/dt               （电感尖峰，与电流变化率成正比）
        ΔV_total = ΔV_C + ΔV_ESR + ΔV_ESL

    参数:
        c_total_farad: 电源网络总电容(F)，<=0 时 ΔV_C 记为 inf（无电容）
        i_step_a:      瞬态电流阶跃(A)
        delta_t_s:     负载持续时间(s)
        esr_ohm:       电容等效串联电阻 ESR(Ω)
        esl_henry:     电容等效串联电感 ESL(H)
        di_dt_a_s:     电流变化率(A/s)

    返回: dict(每项含 V 和 mV 两套单位)
    """
    if c_total_farad and c_total_farad > 0:
        dv_c = i_step_a * delta_t_s / c_total_farad
    else:
        dv_c = float("inf")
    dv_esr = i_step_a * esr_ohm
    dv_esl = esl_henry * di_dt_a_s
    dv_total = dv_c + dv_esr + dv_esl

    def _mv(v):
        return round(v * 1000, 2) if v != float("inf") else float("inf")

    return {
        "dv_c_v": dv_c, "dv_esr_v": dv_esr, "dv_esl_v": dv_esl, "dv_total_v": dv_total,
        "dv_c_mv": _mv(dv_c), "dv_esr_mv": _mv(dv_esr),
        "dv_esl_mv": _mv(dv_esl), "dv_total_mv": _mv(dv_total),
    }


# ========== 电容类型 / 封装 → ESR / ESL 典型值查表（遗留问题 3）==========

# 典型值表：key 为"类型或封装"关键词，值为 (ESR_ohm, ESL_henry)。
# 数据来源：行业典型值（需按实际 datasheet 校正），精度仅用于量级判断。
# 顺序即匹配优先级（放前面的优先命中）。
CAP_ESR_ESL_TABLE = [
    # 铝电解（Electrolytic）：高 ESR / 高 ESL，ESL 大头来自卷绕结构
    ("ECAP",    0.30,   15e-9),   # 通孔/贴片铝电解典型值（100~500mΩ ESR / 10~30nH ESL）
    ("ELEC",    0.30,   15e-9),
    ("CP_ELEC", 0.30,   15e-9),
    ("RADIAL",  0.30,   15e-9),
    ("ECA",     0.30,   15e-9),   # EC cap 缩写（OrCAD 常见）
    ("AEC",     0.30,   15e-9),   # 铝电解 SMD（AEC-SM-*）
    ("CSMD",    0.30,   15e-9),   # 贴片电解（CSMD-*）
    ("16X25",   0.30,   15e-9),   # 通孔电解（直径×高度）
    # 钽 / 聚合物钽（Tantalum / Polymer）：ESR 居中，ESL 低
    ("TANT",    0.10,   3e-9),
    ("POLYMER", 0.06,   2e-9),
    ("TAJ",     0.10,   3e-9),
    # MLCC 多介质陶瓷：低 ESR / 低 ESL，按封装尺寸递增
    # （ESL 主要由封装尺寸决定：0508/0612 反串结构最低，标准件随尺寸变大）
    ("0508",    0.005,  0.25e-9),  # 反串低 ESL MLCC
    ("0612",    0.005,  0.30e-9),  # 反串低 ESL MLCC
    ("0402",    0.010,  0.45e-9),
    ("C0402",   0.010,  0.45e-9),
    ("0603",    0.008,  0.55e-9),
    ("C0603",   0.008,  0.55e-9),
    ("0805",    0.005,  0.80e-9),
    ("C0805",   0.005,  0.80e-9),
    ("1206",    0.003,  1.20e-9),
    ("C1206",   0.003,  1.20e-9),
    ("1210",    0.003,  1.50e-9),
    ("1212",    0.003,  1.80e-9),
    ("1812",    0.002,  2.50e-9),
    ("2220",    0.002,  3.00e-9),
]


def lookup_cap_esr_esl(footprint):
    """按电容 footprint/类型 查 ESR/ESL 典型值。

    参数:
        footprint: 封装字符串（如 "C0402"、"CP_ELEC"、"ECAP-12"、"0805"）

    返回:
        (esr_ohm, esl_henry) 元组；查不到返回 None。

    准确性: ⭐⭐⭐ 典型值（行业经验，非 datasheet 精确值，需按实际料号校正）。
    ⚠️ 假设/边界（精确性红线）:
        - 查表值是"封装/类型"级别的典型值，同一封装不同厂商/材质差异可达数倍。
        - 精确 ESR/ESL 需查具体电容料号的 datasheet（或 BOM 级型号表）。

    匹配规则:
        - 大小写不敏感
        - 子串匹配（"ECAP-12" 命中 "ECAP"，"C0402" 命中 "C0402"）
        - 按 CAP_ESR_ESL_TABLE 顺序优先命中
    """
    if not isinstance(footprint, str):
        return None
    fp = footprint.strip().upper()
    if not fp:
        return None
    for key, esr, esl in CAP_ESR_ESL_TABLE:
        if key in fp:
            return (esr, esl)
    return None


def parallel_esr_esl(cap_params):
    """计算一组并联电容的等效 ESR / ESL。

    公式（并联等效，精确）：
        ESR_eq = 1 / Σ(1/esr_i)
        ESL_eq = 1 / Σ(1/esl_i)
    准确性: 公式精确（并联电阻/电感的数学等效）；误差来自输入的 esr_i/esl_i
            本身（见 lookup_cap_esr_esl 的典型值局限）。

    参数:
        cap_params: list[(esr_ohm, esl_henry)]，每个元素是单个电容的 (ESR, ESL)。
                    未识别的电容不要放进列表（调用方已过滤）。

    返回:
        (esr_eq_ohm, esl_eq_henry)；空列表返回 (None, None)。
    """
    if not cap_params:
        return (None, None)
    sum_inv_esr = 0.0
    sum_inv_esl = 0.0
    for esr, esl in cap_params:
        if esr is not None and esr > 0:
            sum_inv_esr += 1.0 / esr
        if esl is not None and esl > 0:
            sum_inv_esl += 1.0 / esl
    esr_eq = (1.0 / sum_inv_esr) if sum_inv_esr > 0 else None
    esl_eq = (1.0 / sum_inv_esl) if sum_inv_esl > 0 else None
    return (esr_eq, esl_eq)


def loop_esl_from_distance(distance_mm, per_mm_nh=0.8, via_count=2, via_nh=0.6):
    """估算去耦电容的"安装环路电感"（ESL 的大头，常被忽略）。

    物理背景：
        真实去耦电容的有效 ESL = 电容自身 ESL（封装决定，几 nH 量级）
                                + 安装环路电感（布局决定，往往才是大头）。
        安装环路电感来自"电容→IC 电源引脚→地引脚"的电流回路。回路越长、
        面积越大，环路电感越大。工程上用"回路路径长度 × 单位长度电感"
        就近似估算，再叠加过孔电感。

    公式（工程近似，保守）：
        L_loop(nH) = 2 × distance_mm × per_mm_nh + via_count × via_nh
        （2×距离 = 来回路径；per_mm_nh 默认 0.8 nH/mm，综合表层微带+回流；
         每个过孔约 0.5~1.0 nH，默认 0.6 nH）

    参数:
        distance_mm: 电容到 IC 的直线距离(mm)；<=0 时只返回过孔电感
        per_mm_nh:   每 mm 回路路径的电感(nH/mm)，默认 0.8（保守）
        via_count:   回路中的过孔数，默认 2（电容端 1 + IC 端 1）
        via_nh:      单个过孔电感(nH)，默认 0.6

    返回:
        环路电感(nH)。仅作量级判断（±50%），不替代 PI 仿真。

    准确性: ⭐⭐⭐ 趋势准确（±50%，取决于叠层/回流路径是否理想）
    """
    if distance_mm < 0:
        distance_mm = 0
    round_trip = 2.0 * distance_mm * per_mm_nh
    via_total = via_count * via_nh
    return round_trip + via_total


# ========== 工具函数 ==========

def print_calculator_help():
    """打印计算器帮助信息"""
    print("""
硬件分析工具 - 计算器工具集
====================================
走线电阻与压降: trace_resistance, voltage_drop, trace_width_for_current, temperature_rise
电感与电容: via_inductance, pcb_capacitance, crystal_load_capacitance, crystal_capacitor_value
阻抗计算: microstrip_impedance, differential_impedance
电源完整性: pdn_target_impedance, decoupling_capacitor_value
信号完整性: propagation_delay, max_trace_length_no_termination
EMI 估算: emi_radiation_estimate
""")


if __name__ == "__main__":
    print_calculator_help()
    print("=== 实例计算（公式验证）===\n")
    
    # 实例: 3.3V电源轨，50mm长，1mm宽，1oz铜，2A负载
    print("【压降实例】")
    R_ohm, R_mohm = trace_resistance(50, 1.0, 1.0)
    V_drop_v, V_drop_mv = voltage_drop(2.0, R_mohm)
    print(f"走线电阻: {R_mohm:.1f} mΩ")
    print(f"2A时压降: {V_drop_mv:.1f} mV ({V_drop_v/3.3*100:.2f}%)")
    
    # 走线宽度计算
    print("\n【走线宽度计算】")
    width_mil, width_mm = trace_width_for_current(2.0, 10, 1.0)
    print(f"2A电流需要走线宽度: {width_mil:.1f} mil ({width_mm:.2f} mm)")
    
    # 过孔电感
    print("\n【过孔电感】")
    L_nh = via_inductance(1.6, 0.3)
    print(f"1.6mm厚PCB，0.3mm过孔电感: {L_nh:.2f} nH")
    
    # 晶振负载电容
    print("\n【晶振负载电容】")
    CL = crystal_load_capacitance(18, 18, 5)
    print(f"18pF + 18pF + 5pF寄生 = {CL:.1f} pF")
    C_needed = crystal_capacitor_value(12, 5)
    print(f"若晶振要求CL=12pF，需配置 {C_needed:.1f} pF电容")
    
    # 微带线阻抗
    print("\n【微带线阻抗】")
    Z0 = microstrip_impedance(0.25, 0.2, 0.035, 4.5)
    print(f"0.25mm宽微带线(0.2mm介质): {Z0:.1f} Ω")
    Z_diff = differential_impedance(Z0, 0.15)
    print(f"差分阻抗(k=0.15): {Z_diff:.1f} Ω")
    
    # PDN目标阻抗
    print("\n【PDN目标阻抗】")
    Z_target = pdn_target_impedance(0.05, 2.0)
    print(f"1.8V电源，50mV纹波，2A瞬态: {Z_target:.1f} mΩ")
    C_uf = decoupling_capacitor_value(Z_target, 1e6)
    print(f"1MHz时需要去耦电容: {C_uf:.2f} uF")
    
    # 信号延迟
    print("\n【信号延迟】")
    t_pd = propagation_delay(100, 4.5)
    print(f"100mm走线延迟: {t_pd:.1f} ps")
    L_max = max_trace_length_no_termination(2, 4.5)
    print(f"2ns上升时间，无端接最大长度: {L_max:.1f} mm")

