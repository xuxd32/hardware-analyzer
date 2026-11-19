#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gerber 圆弧弧长 _arc_length 强测试（Golden Test）
================================================
验证 G02（顺时针）/G03（逆时针）圆弧弧长算法的精确性：
  整圆、1/4圆(ccw/cw)、半圆、半径0退化直线

运行：python test_gerber_arc.py  （失败即 exit(1)）
"""

import sys
import math
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


arc = GerberParser._arc_length
print("=" * 70)
print("Gerber 圆弧弧长 _arc_length 强测试")
print("=" * 70)

# 1. 整圆 ccw：起点(10,0) 终点(10,0) 圆心偏移(-10,0)→圆心(0,0) R=10
check("整圆 R=10 → 2πR=62.832",
      approx(arc(10, 0, 10, 0, -10, 0, 'ccw'), 2 * math.pi * 10, 1e-3))

# 2. 1/4 圆 ccw：起点(10,0) 圆心(0,0) 终点(0,10)，90°
check("1/4圆 ccw → 15.708", approx(arc(10, 0, 0, 10, -10, 0, 'ccw'), math.pi / 2 * 10, 1e-3))

# 3. 1/4 圆 cw：起点(10,0) 圆心(0,0) 终点(0,-10)
check("1/4圆 cw → 15.708", approx(arc(10, 0, 0, -10, -10, 0, 'cw'), math.pi / 2 * 10, 1e-3))

# 4. 半圆 ccw：起点(10,0) 终点(-10,0) 圆心(0,0)
check("半圆 ccw → 31.416", approx(arc(10, 0, -10, 0, -10, 0, 'ccw'), math.pi * 10, 1e-3))

# 5. 半径 0 → 退化直线（起点(0,0)终点(5,0)，I=0 J=0）
check("半径0退化 → 直线5.0", approx(arc(0, 0, 5, 0, 0, 0, 'ccw'), 5.0, 1e-9))

# 6. 非整圆但扫角恰为 0（终点在起点同一方向但不同位置，如起点(10,0)终点(20,0)圆心(0,0)）
#    起点角 0，终点角 0 → sweep 应为 2π（绕整圈的退化情况，实际是半圆以上的弧）
#    这里验证 R=10 但终点(20,0)在圆外(距离圆心20>R)，属于非法输入，仅验证不崩溃
check("异常输入不崩溃(终点超半径)", arc(10, 0, 20, 0, -10, 0, 'ccw') >= 0)


# ========== G74 单象限圆弧（规范 §4.10，4 候选圆心） ==========
print("\n【G74 单象限圆弧（4 候选圆心）】")
# 规范第 89 页例：起点(11,6) 终点(7,10) I=4 J=0，G03 ccw → 圆心(7,6)，1/4圆
check("G74 1/4圆(规范例) → 6.2832",
      approx(arc(11, 6, 7, 10, 4, 0, 'ccw', 'G74'), math.pi / 2 * 4, 1e-3))
# 第二个：起点(7,10) 终点(3,6) I=0 J=4 → 圆心(7,6)，1/4圆
check("G74 1/4圆2 → 6.2832", approx(arc(7, 10, 3, 6, 0, 4, 'ccw', 'G74'), math.pi / 2 * 4, 1e-3))
# 顺时针 G74：起点(11,6) 圆心(7,6) 终点(7,2)，cw 90°
check("G74 1/4圆 cw → 6.2832", approx(arc(11, 6, 7, 2, 4, 0, 'cw', 'G74'), math.pi / 2 * 4, 1e-3))
# 45°弧 G74：圆心(0,0) 半径4，起点(4,0)，终点在逆时针45°方向，ccw 45°
import math as _m
_e = 4 * _m.cos(_m.pi / 4)
check("G74 45°弧 → 3.1416",
      approx(arc(4, 0, _e, _e, 4, 0, 'ccw', 'G74'), _m.pi / 4 * 4, 1e-3))

# ========== 总结 ==========
print()
print("=" * 70)
print(f"测试结果: {passed} 通过, {failed} 失败")
print("=" * 70)
if failed:
    print("❌ 存在失败测试")
    sys.exit(1)
else:
    print("✅ Gerber 圆弧弧长算法 全部通过")
    sys.exit(0)
