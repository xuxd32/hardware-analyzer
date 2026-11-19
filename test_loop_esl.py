#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
安装环路 ESL 估算 强测试（Golden Test）
========================================
覆盖：
1. loop_esl_from_distance    —— 公式数值对账 + 边界（0/负距离/自定义参数）
2. estimate_loop_esl_by_xy   —— xy 坐标 → 每电源网络最坏环路 ESL（集成）

运行：python test_loop_esl.py  （失败即 exit(1)）
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'src'))

from calculators import loop_esl_from_distance
from main import estimate_loop_esl_by_xy

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
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= tol


# ========== 1. loop_esl_from_distance ==========
print("=" * 70)
print("安装环路 ESL 估算 强测试")
print("=" * 70)
print("\n【1. loop_esl_from_distance 公式对账】")

check("distance=5 → 9.2nH (2×5×0.8+2×0.6)",
      approx(loop_esl_from_distance(5), 9.2, 1e-9), f"实际={loop_esl_from_distance(5)}")
check("distance=0 → 1.2nH (仅过孔)", approx(loop_esl_from_distance(0), 1.2, 1e-9))
check("负距离 → 等同 0 距离", approx(loop_esl_from_distance(-3), 1.2, 1e-9))
check("distance=10, per_mm=1.0, via=0 → 20nH",
      approx(loop_esl_from_distance(10, per_mm_nh=1.0, via_count=0), 20.0, 1e-9))
check("distance=10, 默认参数 → 17.2nH",
      approx(loop_esl_from_distance(10), 17.2, 1e-9), f"实际={loop_esl_from_distance(10)}")
check("via_count=4 → 加 4×0.6", approx(loop_esl_from_distance(0, via_count=4), 2.4, 1e-9))

# ========== 2. estimate_loop_esl_by_xy ==========
print("\n【2. estimate_loop_esl_by_xy 集成】")

# 构造 netlist：U1 连 VDD_A，U2 连 VDD_B
netlist_data = {
    "components": [
        {"ref": "U1", "value": "MCU", "footprint": "QFP"},
        {"ref": "U2", "value": "PMIC", "footprint": "QFN"},
        {"ref": "C1", "value": "100nF", "footprint": "0402"},
        {"ref": "C2", "value": "10uF", "footprint": "0805"},
    ],
    "nets": [
        {"code": 1, "name": "VDD_A", "nodes": [
            {"ref": "U1", "pin": "1"}, {"ref": "C1", "pin": "1"}]},
        {"code": 2, "name": "VDD_B", "nodes": [
            {"ref": "U2", "pin": "1"}]},  # U2 无电容直接连接
        {"code": 3, "name": "GND", "nodes": [{"ref": "C1", "pin": "2"}]},
    ],
}

# xy.xlsx 组件（vals[0]=PartType, vals[1]=RefDes, vals[6]=X, vals[7]=Y）
# U1 在 (0,0)，C1 在 (5,0) → 最近电容距离 5mm
# U2 在 (100,100)，最近的电容 C1(5,0) → 距离约 134.5mm
xy = [
    ["IC",  "U1", "", "", "Top", "", 0.0, 0.0],
    ["IC",  "U2", "", "", "Top", "", 100.0, 100.0],
    ["CAP", "C1", "", "", "Top", "", 5.0, 0.0],
    ["CAP", "C2", "", "", "Top", "", 200.0, 200.0],
]

res = estimate_loop_esl_by_xy(netlist_data, xy, coord_in_mil=False)

check("结果含 VDD_A", "VDD_A" in res)
check("结果含 VDD_B", "VDD_B" in res)

# VDD_A：U1 最近电容 C1(5,0) 距离 5mm → loop=9.2nH
check("VDD_A loop_esl≈9.2nH", approx(res.get("VDD_A"), 9.2, 0.01), f"实际={res.get('VDD_A')}")

# VDD_B：U2 只有最近电容是 C1(5,0)，距离 hypot(95,100)=137.9mm → 大环路 ESL
d = (95**2 + 100**2) ** 0.5
expected_b = 2 * d * 0.8 + 1.2
check("VDD_B loop_esl = 2×137.9×0.8+1.2", approx(res.get("VDD_B"), expected_b, 0.1),
      f"实际={res.get('VDD_B')}, 期望={expected_b}")

# mil 单位转换：同样的物理距离，坐标写成 mil，coord_in_mil=True 应得到相同结果
# C1 在 5mm = 5/0.0254 ≈ 196.85 mil
xy_mil = [
    ["IC",  "U1", "", "", "Top", "", 0.0, 0.0],
    ["CAP", "C1", "", "", "Top", "", 5.0 / 0.0254, 0.0],
]
res_mil = estimate_loop_esl_by_xy(netlist_data, xy_mil, coord_in_mil=True)
check("mil 坐标(默认转mm) → VDD_A 仍≈9.2nH",
      approx(res_mil.get("VDD_A"), 9.2, 0.01), f"实际={res_mil.get('VDD_A')}")

# ========== 3. 空输入边界 ==========
print("\n【3. 空输入边界】")
empty = estimate_loop_esl_by_xy({"nets": [], "components": []}, [])
check("空输入返回空 dict", empty == {})

# 无坐标组件（xy 里没有 X/Y 数字）
bad_xy = [["IC", "U1", "", "", "Top", "", "abc", "def"]]
r2 = estimate_loop_esl_by_xy(netlist_data, bad_xy)
check("无有效坐标 → 网络值为 None 或缺失", r2.get("VDD_A") is None or "VDD_A" not in r2)

# ========== 总结 ==========
print()
print("=" * 70)
print(f"测试结果: {passed} 通过, {failed} 失败")
print("=" * 70)
if failed:
    print("❌ 存在失败测试")
    sys.exit(1)
else:
    print("✅ 安装环路 ESL 估算 全部通过")
    sys.exit(0)
