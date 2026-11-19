#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""is_ic 误判修复验证测试（强测试：失败即 exit(1)）

背景：修复前 is_ic/is_esd 用裸子串匹配，导致 J16 SPD8、M1 LP3443LT1G
被误当 IC。本测试用真实反例锁定修复，防回归。
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

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


print("=" * 60)
print("Hardware Analyzer - is_ic 误判修复验证")
print("=" * 60)

from pcb_deliverables import _part_prefix, _ptype_tokens, decoupling_cap_check

# 测试1: 位号前缀提取
print("\n[测试1] 位号前缀 _part_prefix")
check("U3 -> U", _part_prefix(["x", "U3"]) == "U")
check("J16 -> J", _part_prefix(["x", "J16"]) == "J")
check("M1 -> M", _part_prefix(["x", "M1"]) == "M")
check("ZD2 -> ZD", _part_prefix(["x", "ZD2"]) == "ZD")
check("C12 -> C", _part_prefix(["x", "C12"]) == "C")

# 测试2: PartType 整词（杜绝子串误命中）
print("\n[测试2] PartType 整词 _ptype_tokens")
check("LP3443LT1G 不含 'LP' 子串",
      "LP" not in _ptype_tokens(["LP3443LT1G", "M1"]),
      str(_ptype_tokens(["LP3443LT1G", "M1"])))
check("SPD8 不含误命中（整词是 SPD8 本身）",
      _ptype_tokens(["SPD8", "J16"]) == {"SPD8"})

# 测试3: 去耦检查不再误判 J16/M1 为 IC
print("\n[测试3] decoupling_cap_check 排除连接器/安装孔")
mock = [
    # [PartType, RefDes, ...坐标 X Y]
    ["STM32F103VBT6", "U3", "LQFP", "", "Top", "", 10.0, 10.0],   # 真 IC
    ["CAP", "C39", "0805", "", "Top", "", 12.0, 10.0],            # 真电容
    ["SPD8", "J16", "CONN", "", "Top", "", 20.0, 20.0],           # 连接器（反例）
    ["LP3443LT1G", "M1", "SOT23", "", "Top", "", 30.0, 30.0],     # 安装孔（反例）
]
res = decoupling_cap_check(mock)
ic_refs = [r["ref"] for r in res["results"]]
check("U3 被识别为 IC", "U3" in ic_refs, str(ic_refs))
check("J16 被排除（不再误判为 IC）", "J16" not in ic_refs, str(ic_refs))
check("M1 被排除（不再误判为 IC）", "M1" not in ic_refs, str(ic_refs))
check("IC 数量正确（应=1）", len(ic_refs) == 1, f"实际 IC={ic_refs}")

print()
print("=" * 60)
print(f"测试结果: {passed} 通过, {failed} 失败")
print("=" * 60)
sys.exit(1 if failed else 0)
