#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""约束实施验证测试（强测试：失败即 exit(1)）"""

import sys
import inspect

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
print("Hardware Analyzer - 约束实施验证测试")
print("=" * 60)

# 测试1: 导入检查
print("\n[测试1] 函数导入")
try:
    from src.pcb_deliverables import (
        validate_input_data,
        decoupling_cap_check,
        ir_drop_estimate,
        analyze_deliverables
    )
    check("所有函数导入成功", True)
except ImportError as e:
    check("所有函数导入成功", False, str(e))

# 测试2: 压降估算误差范围
print("\n[测试2] 压降估算误差范围计算")
mock_components = [
    ["LDO", "U1", "SOT23", "", "Top", "", 10.0, 10.0],
    ["CAP", "C1", "0805", "", "Top", "", 12.0, 12.0],
    ["CAP", "C2", "0805", "", "Top", "", 50.0, 50.0]
]
result = ir_drop_estimate(mock_components)
if result["results"]:
    first_result = result["results"][0]
    drop = first_result['drop_avg_1A_mv']
    range_str = first_result['drop_avg_range']
    min_val, max_val = map(lambda x: float(x.split()[0]), range_str.split('-'))
    expected_min = drop * 0.7
    expected_max = drop * 1.3
    check("误差范围计算正确（±30%）",
          abs(min_val - expected_min) < 0.1 and abs(max_val - expected_max) < 0.1,
          f"期望{expected_min:.1f}-{expected_max:.1f}, 实际{min_val:.1f}-{max_val:.1f}")
else:
    check("识别到电源器件", False, "ir_drop_estimate 返回空 results")

check("返回值包含 accuracy_level", "accuracy_level" in result,
      str(result.get('accuracy_level', '缺失')))
check("返回值包含 validation_required", "validation_required" in result,
      str(result.get('validation_required', '缺失')))

# 测试3: 去耦电容检查准确性标签
print("\n[测试3] 去耦电容检查准确性标签")
result = decoupling_cap_check(mock_components)
check("去耦检查包含 accuracy_level", "accuracy_level" in result)
if result.get("issues"):
    check("去耦 issue 包含准确性标签", "accuracy" in result["issues"][0],
          str(result["issues"][0].get("accuracy", "缺失")))
else:
    check("去耦无 issue（正常）", True)

# 测试4: 输入检查函数
print("\n[测试4] 输入数据验证")
import tempfile
with tempfile.TemporaryDirectory() as tmpdir:
    is_valid, errors, warnings = validate_input_data(tmpdir)
    check("空目录正确检测到缺失文件", (not is_valid) and len(errors) >= 1,
          f"is_valid={is_valid}, errors={len(errors)}")

# 测试5: analyze_deliverables 集成
print("\n[测试5] 主入口集成验证")
source = inspect.getsource(analyze_deliverables)
check("analyze_deliverables 已集成输入检查",
      "validate_input_data" in source and "validation" in source)

print()
print("=" * 60)
print(f"测试结果: {passed} 通过, {failed} 失败")
print("=" * 60)
sys.exit(1 if failed else 0)
