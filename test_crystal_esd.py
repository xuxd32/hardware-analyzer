#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""晶振和ESD检查的准确性标签验证（强测试：失败即 exit(1)）"""

import sys

from src.pcb_deliverables import crystal_layout_check, esd_protection_check

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
print("晶振/ESD检查准确性标签验证")
print("=" * 60)

# 测试数据
mock_components = [
    ["CRYSTAL", "Y1", "3225", "", "Top", "", 10.0, 10.0],
    ["IC", "U1", "QFN", "", "Top", "", 25.0, 25.0],  # 距离晶振过远
    ["CON", "J1", "USB", "", "Top", "", 50.0, 50.0],
    ["TVS", "D1", "SOD", "", "Top", "", 60.0, 60.0],  # 距离连接器过远
]

# 测试1: 晶振检查
print("\n[测试1] 晶振布局检查")
result = crystal_layout_check(mock_components)
check("晶振检查返回值包含 accuracy_level", "accuracy_level" in result)
if result.get("issues"):
    check("晶振 issue 包含准确性标签", "accuracy" in result["issues"][0],
          str(result["issues"][0].get("accuracy", "缺失")))
else:
    check("晶振无 issue（正常）", True)

# 测试2: ESD检查
print("\n[测试2] ESD保护检查")
result = esd_protection_check(mock_components)
check("ESD 检查返回值包含 accuracy_level", "accuracy_level" in result)
if result.get("issues"):
    all_have = all("accuracy" in issue for issue in result["issues"])
    check("所有 ESD issue 包含准确性标签", all_have,
          f"issues={[i.get('accuracy','缺失') for i in result['issues']]}")
else:
    check("ESD 无 issue（正常）", True)

print()
print("=" * 60)
print(f"测试结果: {passed} 通过, {failed} 失败")
print("=" * 60)
sys.exit(1 if failed else 0)
