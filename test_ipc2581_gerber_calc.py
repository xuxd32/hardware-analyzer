#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""IPC-2581 / Gerber / 公式库接入测试（强测试：失败即 exit(1)）"""

import sys
import tempfile
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'src'))

import main

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


class Args:
    pass


print("=" * 70)
print("IPC-2581 / Gerber / 公式库接入测试")
print("=" * 70)

# 测试1: analyze_power_signal_calc（公式库 9 项）
print("\n【测试1】公式库电源/信号完整性估算")
args = Args()
args.istep = 8.0
args.ripple_mv = 50.0
args.trise_us = 1.0
calc = main.analyze_power_signal_calc(args)
check("PDN 目标阻抗 = 6.25mΩ", abs(calc.get("pdn_target_impedance_mohm", 0) - 6.25) < 0.1,
      f"实际={calc.get('pdn_target_impedance_mohm')}")
check("去耦电容(1MHz) = 25.465uF", abs(calc.get("decoupling_cap_1MHz_uf", 0) - 25.465) < 0.1,
      f"实际={calc.get('decoupling_cap_1MHz_uf')}")
check("无端接最大走线 > 0", calc.get("max_trace_no_term_mm", 0) > 0)
check("走线宽度(1A) > 0", calc.get("trace_width_1A_mm", 0) > 0)
check("走线压降(50mm/1A) = 25mV", abs(calc.get("trace_50mm_1A_drop_mv", 0) - 25.0) < 0.5,
      f"实际={calc.get('trace_50mm_1A_drop_mv')}")
check("走线温升 > 0", calc.get("trace_temp_rise_c", 0) > 0)
check("PCB平面电容 = 19.9pF", abs(calc.get("pcb_plane_cap_pf", 0) - 19.9) < 0.5,
      f"实际={calc.get('pcb_plane_cap_pf')}")
check("晶振负载电容 = 14.0pF", abs(calc.get("crystal_load_cap_pf", 0) - 14.0) < 0.5,
      f"实际={calc.get('crystal_load_cap_pf')}")
check("EMI(13.56MHz) ≈ -68.8dBμV/m", abs(calc.get("emi_13p56MHz_dBuv", 0) - (-68.8)) < 0.5,
      f"实际={calc.get('emi_13p56MHz_dBuv')}")

# 测试2: analyze_ipc2581_data
print("\n【测试2】IPC-2581 接入")
test_ipc_xml = """<?xml version="1.0" encoding="UTF-8"?>
<IPC-2581 version="C">
    <Bom>
        <Assembly>
            <Component refDes="U1" packageRef="QFN32" part="STM32F103">
                <Location x="10.0" y="20.0" layerRef="TOP"/>
            </Component>
        </Assembly>
    </Bom>
    <LogicalNets>
        <Net name="VCC">
            <PinRef componentRef="U1" pin="1"/>
        </Net>
    </LogicalNets>
</IPC-2581>
"""
with tempfile.NamedTemporaryFile(mode='w', suffix='.xml', delete=False) as f:
    f.write(test_ipc_xml)
    xml_path = f.name
ipc = main.analyze_ipc2581_data(xml_path)
os.unlink(xml_path)
check("IPC-2581 解析成功", "error" not in ipc, str(ipc.get('error', '')[:50]))
if "error" not in ipc:
    check("IPC-2581 含计算公式", "calculations" in ipc)
    if "calculations" in ipc:
        check("IPC-2581 过孔电感 > 0", ipc["calculations"].get("via_inductance_nh", 0) > 0)

# 测试3: analyze_gerber_data
print("\n【测试3】Gerber 接入")
with tempfile.TemporaryDirectory() as tmpdir:
    with open(os.path.join(tmpdir, 'test.gtl'), 'w') as f:
        f.write("%FSLAX36Y36*%\n%MOMM*%\n%ADD10C,0.1524*%\nG75*\nD10*\n"
                "X1000000Y2000000D02*\nX3000000Y4000000D01*\nM02*\n")
    gb = main.analyze_gerber_data(tmpdir)
check("Gerber 解析成功", "error" not in gb, str(gb.get('error', '')[:50]))
if "error" not in gb:
    check("Gerber 含计算公式", "calculations" in gb)
    check("Gerber 走线长度 > 0", gb.get("total_length", 0) > 0)
    if "calculations" in gb:
        check("Gerber 走线电感 > 0", gb["calculations"].get("trace_inductance_nh", 0) > 0)

print()
print("=" * 70)
print(f"测试结果: {passed} 通过, {failed} 失败")
print("=" * 70)
sys.exit(1 if failed else 0)
