#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Region（G36/G37）解析 强测试
============================
验证状态机对 region 的隔离 + 轮廓周长累加 + is_region 标记

运行：python test_gerber_region.py  （失败即 exit(1)）
"""

import sys
import tempfile
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'src'))

from gerber_parser import GerberParser

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


print("=" * 70)
print("Region（G36/G37）解析 强测试")
print("=" * 70)

# 构造 region 闭合矩形 10x10mm（周长 40mm），绝对坐标，单位 mm
# 起点(0,0)：X100000=10mm
content = """%MOMM*%
%FSLAX24Y24*%
%ADD10C,0.1*%
D10*
G36*
X0Y0D02*
G01*
X100000D01*
Y100000D01*
X0D01*
Y0D01*
G37*
M02*
"""
f = tempfile.NamedTemporaryFile(mode='w', suffix='.gbr', delete=False, encoding='utf-8')
f.write(content)
f.close()

p = GerberParser('.')
traces = p._parse_gerber_file(f.name)
os.unlink(f.name)

check("region 有 4 条轮廓段", len(traces) == 4, f"实际={len(traces)}")
check("region 段带 is_region 标记", all(t.get('is_region') for t in traces))
# 正方形 10x10，周长 40mm
total = sum(t['length_mm'] for t in traces)
check("region 轮廓周长 = 40mm", approx(total, 40.0, 0.01), f"实际={total}")

# ========== 总结 ==========
print()
print("=" * 70)
print(f"测试结果: {passed} 通过, {failed} 失败")
print("=" * 70)
if failed:
    print("❌ 存在失败测试")
    sys.exit(1)
else:
    print("✅ Region 解析 全部通过")
    sys.exit(0)
