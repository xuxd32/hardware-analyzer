#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
parse_ipc357_coords_to_mm 强测试（Golden Test）
=============================================
覆盖 IPC-D-356 3xx 记录坐标解析（本轮新增能力）：
1. 换算正确性 —— UNITS CUST 0 = 0.1 mil，坐标整数 × 0.00254 → mm
2. 字段解析 —— net（去 3+F+A 三字符）/ ref（位号）/ pin（引脚号）
3. 过孔 VIA —— ref 应为空串（无位号）
4. 缺坐标 / 非 3xx 记录 —— 静默跳过
5. 文件不存在 —— 返回空列表（不抛异常）

运行：python test_ipc_coords.py （失败即 exit(1)）

⚠️ 0.1 mil 换算系数由 nc drill 刀具表与 IPC 过孔记录双向对应锁定。
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'src'))

from pcb_deliverables import parse_ipc357_coords_to_mm, parse_ipc_units

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


def approx(a, b, tol=1e-9):
    return abs(a - b) <= tol


def _make_ipc(body):
    """写一个最小 IPC 文件（含 UNITS CUST 0 + 指定 3xx 记录体），返回路径。"""
    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, "test.ipc")
    with open(path, "w", encoding="ascii") as f:
        f.write("C test\nP  UNITS CUST 0\nP JOB test\nP IMAGE PRIMARY\n")
        f.write(body)
        f.write("999\n")
    return path


print("=" * 70)
print("parse_ipc357_coords_to_mm 强测试")
print("=" * 70)

# ========== 1. 换算正确性（0.1 mil） ==========
print("\n【1. 换算正确性：0.1 mil = ×0.00254 mm】")
# 100000 单位 = 100000 * 0.00254 = 254.0 mm；200000 单位 = 508.0 mm
ipc1 = _make_ipc("317NET_A     VIA    D 100PA00X+100000Y+200000X0200Y0000\n")
res1 = parse_ipc357_coords_to_mm(ipc1)
check("解析出 1 条记录", len(res1) == 1, f"实际={len(res1)}")
check("X=100000 → 254.0mm", approx(res1[0]["x_mm"], 254.0, 1e-6), f"实际={res1[0]['x_mm']}")
check("Y=200000 → 508.0mm", approx(res1[0]["y_mm"], 508.0, 1e-6), f"实际={res1[0]['y_mm']}")

# ========== 2. 字段解析 net/ref/pin ==========
print("\n【2. 字段解析：net（去 3+F+A）/ ref / pin】")
# 317AUDIO_PA_EN  → net=AUDIO_PA_EN（317 = 3+1(通孔)+7(访问码)）
# U1 -58 → ref=U1, pin=-58
ipc2 = _make_ipc("317AUDIO_PA_EN U1 -58 D 100PA00X+064804Y+053254X0200Y0000\n")
res2 = parse_ipc357_coords_to_mm(ipc2)
check("net = AUDIO_PA_EN", res2[0]["net"] == "AUDIO_PA_EN", f"实际={res2[0]['net']!r}")
check("ref = U1", res2[0]["ref"] == "U1", f"实际={res2[0]['ref']!r}")
check("pin = -58", res2[0]["pin"] == "-58", f"实际={res2[0]['pin']!r}")

# 327 记录（SMD，FeatureType=2）
ipc3 = _make_ipc("327GSM_PWR U3 -12 A04X+045513Y+075104X0256Y0787R360\n")
res3 = parse_ipc357_coords_to_mm(ipc3)
check("327 net = GSM_PWR", res3[0]["net"] == "GSM_PWR", f"实际={res3[0]['net']!r}")
check("327 ref = U3", res3[0]["ref"] == "U3", f"实际={res3[0]['ref']!r}")

# ========== 3. 过孔 VIA —— ref 应为空 ==========
print("\n【3. 过孔 VIA：ref 应为空串】")
ipc4 = _make_ipc("317AV_PWR2_V50 VIA D 100PA00X+065950Y+083700X0200Y0000\n")
res4 = parse_ipc357_coords_to_mm(ipc4)
check("VIA ref 为空串", res4[0]["ref"] == "", f"实际={res4[0]['ref']!r}")
check("VIA net = AV_PWR2_V50", res4[0]["net"] == "AV_PWR2_V50", f"实际={res4[0]['net']!r}")
check("VIA pin 为空串", res4[0]["pin"] == "", f"实际={res4[0]['pin']!r}")

# ========== 4. 缺坐标 / 非 3xx 记录 → 跳过 ==========
print("\n【4. 缺坐标 / 非 3xx 记录 → 静默跳过】")
ipc5 = _make_ipc(
    "C comment line should be skipped\n"
    "P  NNAME0001 TEST_NET\n"          # P 行，非 3xx
    "317NOCOORD U5 -1 D 100PA00\n"     # 3xx 但无 X/Y 坐标
    "317HASCOORD U6 -2 D 100PA00X+001000Y+001000\n"  # 有效
)
res5 = parse_ipc357_coords_to_mm(ipc5)
check("只解析出 1 条有效坐标记录", len(res5) == 1, f"实际={len(res5)}")
check("有效记录 ref = U6", res5[0]["ref"] == "U6", f"实际={res5[0]['ref']!r}")

# ========== 5. 文件不存在 → [] ==========
print("\n【5. 文件不存在 → 空列表（不抛异常）】")
res6 = parse_ipc357_coords_to_mm(os.path.join(tempfile.mkdtemp(), "no.ipc"))
check("文件不存在返回 []", res6 == [], f"实际={res6!r}")

# ========== 6. 回归：parse_ipc_units 语义澄清（CUST 仍返回 mil，不被误改） ==========
print("\n【6. 回归：parse_ipc_units 返回语义（CUST 仍 = 'mil'，勿误改系数）】")
ipc6 = _make_ipc("")
check("CUST 0 → 'mil'（坐标系统=英制）", parse_ipc_units(ipc6) == "mil",
      f"实际={parse_ipc_units(ipc6)!r}")

print()
print("=" * 70)
print(f"测试结果: {passed} 通过, {failed} 失败")
print("=" * 70)
if failed:
    print("❌ 存在失败测试")
    sys.exit(1)
else:
    print("✅ parse_ipc357_coords_to_mm 全部通过")
    sys.exit(0)
