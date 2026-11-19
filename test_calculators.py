#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
calculators.py 数值正确性测试（Golden Test）
=============================================
每个公式一个已知答案的验证，防止单位错误回归。

数据来源：
- IPC-2221B（PCB设计标准）
- Howard Johnson《高速数字设计》
- Henry Ott《电磁兼容工程》
- Eric Bogatin《信号完整性与电源完整性分析》

运行：python test_calculators.py
"""

print("=" * 70)
print("calculators.py 数值正确性测试（Golden Test）")
print("=" * 70)

from src.calculators import (
    trace_resistance, voltage_drop, trace_width_for_current, temperature_rise,
    via_inductance, trace_inductance, pcb_capacitance, crystal_load_capacitance, crystal_capacitor_value,
    microstrip_impedance, differential_impedance, pdn_target_impedance,
    decoupling_capacitor_value, propagation_delay, max_trace_length_no_termination,
    emi_radiation_estimate
)

passed = 0
failed = 0

def check(name, actual, expected, tolerance):
    """检查数值是否在容差范围内"""
    global passed, failed
    ok = abs(actual - expected) <= tolerance
    status = "PASS" if ok else "FAIL"
    if ok:
        passed += 1
    else:
        failed += 1
    print(f"[{status}] {name}: 实际={actual}, 期望={expected}±{tolerance}")

# ========== 走线电阻与压降 ==========
print("\n【走线电阻与压降】")

# 测试1: trace_resistance 10mm,1mm,1oz -> 5mΩ
_, r = trace_resistance(10, 1.0, 1.0)
check("trace_resistance(10mm,1mm,1oz)", r, 5.0, 0.5)

# 测试2: trace_resistance 50mm,1mm,1oz -> 25mΩ
_, r = trace_resistance(50, 1.0, 1.0)
check("trace_resistance(50mm,1mm,1oz)", r, 25.0, 1.0)

# 测试3: trace_resistance 10mm,2mm,2oz -> 约1.25mΩ
_, r = trace_resistance(10, 2.0, 2.0)
check("trace_resistance(10mm,2mm,2oz)", r, 1.25, 0.2)

# 测试4: voltage_drop 2A,5mΩ -> 10mV
_, v = voltage_drop(2.0, 5.0)
check("voltage_drop(2A,5mΩ)", v, 10.0, 0.1)

# 测试5: trace_width_for_current 2A,10C,1oz -> 约0.79mm
_, w = trace_width_for_current(2.0, 10, 1.0)
check("trace_width_for_current(2A,10C,1oz)", w, 0.79, 0.15)

# 测试6: trace_width_for_current 1A,10C,1oz -> 约0.33mm
_, w = trace_width_for_current(1.0, 10, 1.0)
check("trace_width_for_current(1A,10C,1oz)", w, 0.33, 0.10)

# ========== 电感与电容 ==========
print("\n【电感与电容】")

# 测试7: via_inductance 1.6mm,0.3mm -> 1.3nH
l = via_inductance(1.6, 0.3)
check("via_inductance(1.6mm,0.3mm)", l, 1.3, 0.2)

# 测试8: via_inductance 1.0mm,0.2mm -> 约0.87nH
l = via_inductance(1.0, 0.2)
check("via_inductance(1.0mm,0.2mm)", l, 0.87, 0.15)

# 测试9: pcb_capacitance 100mm2,0.2mm,4.5 -> 19.9pF
c = pcb_capacitance(100, 0.2, 4.5)
check("pcb_capacitance(100mm2,0.2mm,4.5)", c, 19.9, 2.0)

# 测试10: crystal_load_capacitance 18,18,5 -> 14pF
cl = crystal_load_capacitance(18, 18, 5)
check("crystal_load_capacitance(18,18,5)", cl, 14.0, 1.0)

# 测试11: crystal_capacitor_value 14,5 -> 18pF
cv = crystal_capacitor_value(14, 5)
check("crystal_capacitor_value(14,5)", cv, 18.0, 1.0)

# 测试11.5: trace_inductance 10mm,1mm -> 8-10nH
l = trace_inductance(10, 1.0)
check("trace_inductance(10mm,1mm)", l, 9.0, 2.0)

# 测试11.6: trace_inductance 5mm,0.5mm -> 4-5nH
l = trace_inductance(5, 0.5)
check("trace_inductance(5mm,0.5mm)", l, 4.5, 1.5)

# 测试11.7: trace_inductance 20mm,2mm -> 16-20nH
l = trace_inductance(20, 2.0)
check("trace_inductance(20mm,2mm)", l, 18.0, 3.0)

# ========== 阻抗计算 ==========
print("\n【阻抗计算】")

# 测试12: microstrip_impedance 0.25mm,0.2mm,4.5 -> 约58Ω
z0 = microstrip_impedance(0.25, 0.2, 0.035, 4.5)
check("microstrip_impedance(0.25mm,0.2mm,4.5)", z0, 58.0, 10.0)

# 测试13: differential_impedance 100,k=0.1 -> 约189.7Ω
zd = differential_impedance(100, 0.1)
check("differential_impedance(100,0.1)", zd, 189.7, 5.0)

# ========== 电源完整性 ==========
print("\n【电源完整性】")

# 测试14: pdn_target_impedance 50mV,100mA -> 500mΩ
z = pdn_target_impedance(0.05, 0.1)
check("pdn_target_impedance(50mV,100mA)", z, 500.0, 1.0)

# 测试15: decoupling_capacitor_value 500mΩ,13.56MHz -> 约0.0235uF
dc = decoupling_capacitor_value(500, 13.56e6)
check("decoupling_capacitor_value(500mΩ,13.56MHz)", dc, 0.0235, 0.005)

# ========== 信号完整性 ==========
print("\n【信号完整性】")

# 测试16: propagation_delay 100mm,4.5 -> 约707ps
t = propagation_delay(100, 4.5)
check("propagation_delay(100mm,4.5)", t, 707, 20)

# 测试17: max_trace_length_no_termination 2ns,4.5 -> 约47.1mm
lm = max_trace_length_no_termination(2, 4.5)
check("max_trace_length_no_termination(2ns,4.5)", lm, 47.1, 5.0)

# ========== EMI 估算 ==========
print("\n【EMI 估算】")

# 测试18: emi_radiation_estimate 100mA,100mm2,13.56MHz,3m -> 约-68.8dBuV/m
e = emi_radiation_estimate(0.1, 100, 13.56e6, 3)
check("emi_radiation_estimate(100mA,100mm2,13.56MHz,3m)", e, -68.8, 5.0)

# ========== 总结 ==========
print()
print("=" * 70)
print(f"测试结果: {passed} 通过, {failed} 失败")
print("=" * 70)

if failed > 0:
    print("❌ 存在失败的测试，请检查计算公式")
    exit(1)
else:
    print("✅ 所有数值测试通过，公式正确")
    exit(0)
