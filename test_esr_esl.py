#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ESR/ESL 电容类型/封装查表 + 并联等效 强测试（Golden Test）
================================================================
覆盖三层：
1. lookup_cap_esr_esl    —— 封装查表（MLCC/电解/钽、大小写、C前缀、未命中、边界）
2. parallel_esr_esl      —— 并联等效数值对账（1/Σ(1/x)）、空列表、单电容
3. analyze_transient_droop —— 显式值优先 / None 触发查表 / 查表兜底的集成

运行：python test_esr_esl.py  （失败即 exit(1)）
"""

import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'src'))

from calculators import (
    lookup_cap_esr_esl, parallel_esr_esl, CAP_ESR_ESL_TABLE,
)
from main import analyze_transient_droop, extract_power_net_caps_detail

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


# ========== 1. lookup_cap_esr_esl ==========
print("=" * 70)
print("ESR/ESL 查表 + 并联等效 强测试")
print("=" * 70)
print("\n【1. lookup_cap_esr_esl 封装查表】")

# MLCC 各封装
check("C0402 → (10mΩ, 0.45nH)", lookup_cap_esr_esl("C0402") == (0.010, 0.45e-9))
check("0402 → (10mΩ, 0.45nH)", lookup_cap_esr_esl("0402") == (0.010, 0.45e-9))
check("C0603 → (8mΩ, 0.55nH)", lookup_cap_esr_esl("C0603") == (0.008, 0.55e-9))
check("0805 → (5mΩ, 0.80nH)", lookup_cap_esr_esl("0805") == (0.005, 0.80e-9))
check("C1206 → (3mΩ, 1.2nH)", lookup_cap_esr_esl("C1206") == (0.003, 1.20e-9))

# 电解 / 钽
check("ECAP-12 → 电解 (0.30, 15nH)", lookup_cap_esr_esl("ECAP-12") == (0.30, 15e-9))
check("ECAPM → 电解", lookup_cap_esr_esl("ECAPM") == (0.30, 15e-9))
check("CP_ELEC → 电解", lookup_cap_esr_esl("CP_ELEC") == (0.30, 15e-9))
check("TANT → 钽 (0.10, 3nH)", lookup_cap_esr_esl("TANT_A") == (0.10, 3e-9))

# 大小写不敏感
check("小写 0402 → 命中", lookup_cap_esr_esl("0402") is not None)
check("c0402 → 命中", lookup_cap_esr_esl("c0402") == (0.010, 0.45e-9))

# 未命中 / 边界
check("未知封装 → None", lookup_cap_esr_esl("SOT23") is None)
check("空串 → None", lookup_cap_esr_esl("") is None)
check("None → None", lookup_cap_esr_esl(None) is None)
check("非字符串 → None", lookup_cap_esr_esl(402) is None)

# ========== 2. parallel_esr_esl ==========
print("\n【2. parallel_esr_esl 并联等效】")

# 两个 0402 并联：ESR 减半
e1 = (0.010, 0.45e-9)
r1 = parallel_esr_esl([e1, e1])
check("2×0402 ESR=5mΩ", approx(r1[0], 0.005, 1e-6), f"实际={r1[0]}")
check("2×0402 ESL=0.225nH", approx(r1[1], 0.225e-9, 1e-12), f"实际={r1[1]}")

# 0402 + 0805 并联
r2 = parallel_esr_esl([(0.010, 0.45e-9), (0.005, 0.80e-9)])
check("0402+0805 ESR≈3.33mΩ", approx(r2[0], 0.003333, 1e-6), f"实际={r2[0]}")
check("0402+0805 ESL≈0.288nH", approx(r2[1], 0.288e-9, 1e-12), f"实际={r2[1]}")

# 空列表
r3 = parallel_esr_esl([])
check("空列表 → (None,None)", r3 == (None, None))

# 单电容
r4 = parallel_esr_esl([(0.30, 15e-9)])
check("单电解 → (0.30,15nH)", approx(r4[0], 0.30, 1e-9) and approx(r4[1], 15e-9, 1e-10))

# 含 None 元素应跳过（调用方一般已过滤，但函数要健壮）
r5 = parallel_esr_esl([(0.010, 0.45e-9), (None, None)])
check("含 None 元素 → 只算有效项", approx(r5[0], 0.010, 1e-9) and approx(r5[1], 0.45e-9, 1e-12))

print("\n【表完整性】")
check("查表非空", len(CAP_ESR_ESL_TABLE) > 0)
keys = [k for k, _, _ in CAP_ESR_ESL_TABLE]
# 每个 key 都是大写且非空
check("key 全大写非空", all(k and k == k.upper() for k in keys))
# 每个 ESR/ESL 都是正数
check("ESR 全为正", all(esr > 0 for _, esr, _ in CAP_ESR_ESL_TABLE))
check("ESL 全为正", all(esl > 0 for _, _, esl in CAP_ESR_ESL_TABLE))


# ========== 3. analyze_transient_droop 查表集成 ==========
print("\n【3. analyze_transient_droop 查表集成】")

# 构造 netlist：两个电源网络，含不同封装电容
netlist_data = {
    "components": [
        {"ref": "C1", "value": "100nF", "footprint": "0402"},
        {"ref": "C2", "value": "10uF",  "footprint": "0603"},
        {"ref": "C3", "value": "100uF", "footprint": "ECAP-12"},
        {"ref": "U1", "value": "STM32",  "footprint": "QFP64"},
    ],
    "nets": [
        {"code": 1, "name": "VDD_A", "nodes": [
            {"ref": "C1", "pin": "1"}, {"ref": "C2", "pin": "1"}, {"ref": "U1", "pin": "1"}]},
        {"code": 2, "name": "VDD_B", "nodes": [
            {"ref": "C3", "pin": "1"}]},
        {"code": 3, "name": "GND", "nodes": [{"ref": "C1", "pin": "2"}]},
    ],
}

base = {"istep": 8.0, "delta_t_s": 10e-6, "di_dt_a_s": 8e6, "ripple_v": 0.05}

# 3a. 显式指定 ESR/ESL（数值）→ 查表被覆盖，用用户值
params_explicit = dict(base, esr_ohm=0.02, esl_henry=2e-9)
res_e = analyze_transient_droop({"netlist_data": netlist_data}, params_explicit)
rA = res_e["net_droop"]["VDD_A"]
check("显式 esr → esr_used=20mΩ", approx(rA["esr_used_mohm"], 20.0, 0.01), f"实际={rA['esr_used_mohm']}")
check("显式 esl → esl_used=2nH", approx(rA["esl_used_nh"], 2.0, 0.001), f"实际={rA['esl_used_nh']}")
check("显式 esr 时 ΔV_ESR=160mV (8A×20mΩ)", approx(rA["dv_esr_mv"], 160.0, 0.01))

# 3b. None → 触发查表 + 并联等效
params_auto = dict(base, esr_ohm=None, esl_henry=None)
res_a = analyze_transient_droop({"netlist_data": netlist_data}, params_auto)
rA2 = res_a["net_droop"]["VDD_A"]
# VDD_A 有 C1(0402,10mΩ/0.45nH) + C2(0603,8mΩ/0.55nH)
# esr_eq = 1/(1/0.010+1/0.008) = 1/(100+125) = 1/225 = 4.444mΩ
# esl_eq = 1/(1/0.45+1/0.55) = 1/(2.2222+1.8182) = 1/4.0404 = 0.2475nH
check("None → 触发查表 esr_used≈4.44mΩ", approx(rA2["esr_used_mohm"], 4.44, 0.01), f"实际={rA2['esr_used_mohm']}")
check("None → esl_used≈0.248nH", approx(rA2["esl_used_nh"], 0.2475, 0.001), f"实际={rA2['esl_used_nh']}")
check("VDD_A cap_hit_count=2", rA2["cap_hit_count"] == 2)
check("VDD_A cap_count=2", rA2["cap_count"] == 2)

# VDD_B 只有电解 ECAP-12 → 0.30Ω/15nH
rB = res_a["net_droop"]["VDD_B"]
check("电解 esr_used=300mΩ", approx(rB["esr_used_mohm"], 300.0, 0.1), f"实际={rB['esr_used_mohm']}")
check("电解 esl_used=15nH", approx(rB["esl_used_nh"], 15.0, 0.001), f"实际={rB['esl_used_nh']}")

# 3c. None 且电容 footprint 全部未命中 → 兜底 10mΩ/1nH
netlist_unknown = {
    "components": [
        {"ref": "C1", "value": "100nF", "footprint": "MYSOT"},
    ],
    "nets": [
        {"code": 1, "name": "VDD_X", "nodes": [{"ref": "C1", "pin": "1"}]},
    ],
}
res_u = analyze_transient_droop({"netlist_data": netlist_unknown}, dict(base, esr_ohm=None, esl_henry=None))
rX = res_u["net_droop"]["VDD_X"]
check("全未命中 → esr 兜底 10mΩ", approx(rX["esr_used_mohm"], 10.0, 0.01), f"实际={rX['esr_used_mohm']}")
check("全未命中 → esl 兜底 1nH", approx(rX["esl_used_nh"], 1.0, 0.001), f"实际={rX['esl_used_nh']}")
check("未命中 cap_hit_count=0", rX["cap_hit_count"] == 0)

# ========== 4. extract_power_net_caps_detail ==========
print("\n【4. extract_power_net_caps_detail 电容明细】")
detail = extract_power_net_caps_detail(netlist_data)
check("detail 含 VDD_A", "VDD_A" in detail)
check("VDD_A 有 2 个电容", len(detail["VDD_A"]) == 2)
check("VDD_A 电容含 footprint", all("footprint" in c for c in detail["VDD_A"]))
check("VDD_B 有 1 个电解", len(detail["VDD_B"]) == 1)

# ========== 5. 真实文件端到端 ==========
print("\n【5. 真实文件端到端（可选样本）】")
REAL_PRT = os.environ.get("HW_REAL_PRT", "")
if os.path.isfile(REAL_PRT):
    from orcad_expanded_parser import parse_orcad_expanded
    netlist_data = parse_orcad_expanded(REAL_PRT)
    res = analyze_transient_droop({"netlist_data": netlist_data}, dict(base, esr_ohm=None, esl_henry=None))
    nd = res["net_droop"]
    check("真实文件有电源网络", len(nd) > 0, f"实际={len(nd)}")
    # 找到 PWR_IN1（大电容网络），验证查表命中
    if "PWR_IN1" in nd:
        rp = nd["PWR_IN1"]
        check("PWR_IN1 esr_used 已算出", rp.get("esr_used_mohm") is not None)
        # 因为含电解（ECAP，高 ESR）和大量 MLCC，等效 ESR 应在 mΩ 量级
        check("PWR_IN1 esr_used 为正值", rp["esr_used_mohm"] > 0)
        print(f"    [信息] PWR_IN1: 电容{ rp['cap_count']}个(命中{rp['cap_hit_count']}个) "
              f"ESR_eq={rp['esr_eq_mohm']}mΩ ESL_eq={rp['esl_eq_nh']}nH")
    else:
        print("    [跳过] 无 PWR_IN1 网络")
else:
    print("[跳过] 可选样本不存在（设置环境变量 HW_REAL_PRT 后启用）")

# ========== 总结 ==========
print()
print("=" * 70)
print(f"测试结果: {passed} 通过, {failed} 失败")
print("=" * 70)
if failed:
    print("❌ 存在失败测试")
    sys.exit(1)
else:
    print("✅ ESR/ESL 查表 + 并联等效 全部通过")
    sys.exit(0)

