#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
母线瞬态掉压功能测试（Golden Test）
=============================================
覆盖本次接入的 4 个层次：
1. parse_capacitance            —— 电容值字符串解析（各单位/非法输入）
2. bus_droop                    —— 三段式掉压公式 ΔV_C + ΔV_ESR + ΔV_ESL 数值对账
3. extract_power_net_capacitance —— 从 netlist 提取各电源网络总电容（识别/求和/排除）
4. analyze_transient_droop      —— 端到端：结构 + 数值 + C=0 边界

运行：python test_bus_droop.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from calculators import parse_capacitance, bus_droop
from main import extract_power_net_capacitance, analyze_transient_droop

passed = 0
failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"[PASS] {name}")
    else:
        failed += 1
        print(f"[FAIL] {name}  {detail}")


def approx(a, b, tol):
    return abs(a - b) <= tol


# ========== 1. parse_capacitance ==========
print("=" * 70)
print("母线瞬态掉压功能测试")
print("=" * 70)
print("\n【1. parse_capacitance 电容值解析】")
check("100nF → 1e-7 F", approx(parse_capacitance("100nF"), 1e-7, 1e-12))
check("10uF → 1e-5 F", approx(parse_capacitance("10uF"), 1e-5, 1e-9))
check("4.7uF → 4.7e-6 F", approx(parse_capacitance("4.7uF"), 4.7e-6, 1e-10))
check("470pF → 4.7e-10 F", approx(parse_capacitance("470pF"), 4.7e-10, 1e-14))
check("1000uF → 1e-3 F", approx(parse_capacitance("1000uF"), 1e-3, 1e-7))
check("10mF → 0.01 F", approx(parse_capacitance("10mF"), 0.01, 1e-6))
check("1F → 1.0 F", approx(parse_capacitance("1F"), 1.0, 1e-9))
check("非法值 X7R → None", parse_capacitance("X7R") is None)
check("空串 → None", parse_capacitance("") is None)
check("None 输入 → None", parse_capacitance(None) is None)

# ========== 2. bus_droop 三段式掉压 ==========
print("\n【2. bus_droop 三段式掉压数值对账】")
# 已知例子: C=160uF, I=8A, Δt=10us, ESR=10mΩ, ESL=1nH, di/dt=8e6 A/s
r = bus_droop(160e-6, 8.0, 10e-6, 0.01, 1e-9, 8e6)
check("ΔV_C = 500mV", approx(r["dv_c_mv"], 500.0, 0.1), f"实际={r['dv_c_mv']}")
check("ΔV_ESR = 80mV", approx(r["dv_esr_mv"], 80.0, 0.01), f"实际={r['dv_esr_mv']}")
check("ΔV_ESL = 8mV", approx(r["dv_esl_mv"], 8.0, 0.01), f"实际={r['dv_esl_mv']}")
check("ΔV_total = 588mV", approx(r["dv_total_mv"], 588.0, 0.1), f"实际={r['dv_total_mv']}")

r2 = bus_droop(0, 8.0, 10e-6, 0.01, 1e-9, 8e6)
check("C=0 → ΔV_C=inf", r2["dv_c_mv"] == float("inf"))

r3 = bus_droop(160e-6, 8.0, 10e-6, 0.0, 0.0, 0.0)
check("ESR=0 且 ESL=0 → 仅剩 ΔV_C", r3["dv_esr_mv"] == 0 and r3["dv_esl_mv"] == 0)

# ========== 3. extract_power_net_capacitance ==========
print("\n【3. extract_power_net_capacitance 电源网络电容提取】")
netlist_data = {
    "components": [
        {"ref": "C1", "value": "100nF", "footprint": "0402"},
        {"ref": "C2", "value": "10uF", "footprint": "0805"},
        {"ref": "C3", "value": "47uF", "footprint": "CP_ELEC"},
        {"ref": "C4", "value": "X7R", "footprint": "0402"},   # 值无法解析，应跳过
        {"ref": "U1", "value": "STM32", "footprint": "QFP"},  # 非电容，应排除
    ],
    "nets": [
        {"code": 1, "name": "VDD_3V3",
         "nodes": [{"ref": "C1", "pin": "1"}, {"ref": "C2", "pin": "1"}, {"ref": "U1", "pin": "1"}]},
        {"code": 2, "name": "GND", "nodes": [{"ref": "C1", "pin": "2"}]},
        {"code": 3, "name": "VDD_1V8",
         "nodes": [{"ref": "C3", "pin": "1"}, {"ref": "C4", "pin": "1"}]},
        {"code": 4, "name": "SIG_A", "nodes": [{"ref": "C2", "pin": "2"}]},  # 非电源网络，应排除
    ],
}
cap_map = extract_power_net_capacitance(netlist_data)
check("识别 VDD_3V3", "VDD_3V3" in cap_map)
check("识别 VDD_1V8", "VDD_1V8" in cap_map)
check("排除 GND", "GND" not in cap_map)
check("排除非电源网络 SIG_A", "SIG_A" not in cap_map)
check("VDD_3V3 = 10.1uF（100nF+10uF）", approx(cap_map.get("VDD_3V3", 0) * 1e6, 10.1, 0.01),
      f"实际={cap_map.get('VDD_3V3')}")
check("VDD_1V8 = 47uF（X7R跳过）", approx(cap_map.get("VDD_1V8", 0) * 1e6, 47.0, 0.01),
      f"实际={cap_map.get('VDD_1V8')}")

# ========== 4. analyze_transient_droop 端到端 ==========
print("\n【4. analyze_transient_droop 端到端】")
netlist_result = {"netlist_data": netlist_data}
params = {"istep": 8.0, "delta_t_s": 10e-6, "esr_ohm": 0.01,
          "esl_henry": 1e-9, "di_dt_a_s": 8e6, "ripple_v": 0.05}
res = analyze_transient_droop(netlist_result, params)
check("返回结构含 params/cap_map/net_droop",
      all(k in res for k in ["params", "cap_map", "net_droop"]))
nd = res["net_droop"]
check("net_droop 含 VDD_3V3", "VDD_3V3" in nd)
check("net_droop 含 VDD_1V8", "VDD_1V8" in nd)
r33 = nd.get("VDD_3V3", {})
check("VDD_3V3 total_c_uf = 10.1", approx(r33.get("total_c_uf", 0), 10.1, 0.01))
check("VDD_3V3 z_target = 6.25mΩ（50mV/8A）", approx(r33.get("z_target_mohm", 0), 6.25, 0.1),
      f"实际={r33.get('z_target_mohm')}")
check("VDD_3V3 ΔV_ESR = 80mV", approx(r33.get("dv_esr_mv", 0), 80.0, 0.01))
check("VDD_3V3 ΔV_ESL = 8mV", approx(r33.get("dv_esl_mv", 0), 8.0, 0.01))

# ========== 总结 ==========
print()
print("=" * 70)
print(f"测试结果: {passed} 通过, {failed} 失败")
print("=" * 70)
if failed:
    print("❌ 存在失败的测试，请检查母线掉压实现")
    sys.exit(1)
else:
    print("✅ 母线掉压功能测试全部通过")
    sys.exit(0)
