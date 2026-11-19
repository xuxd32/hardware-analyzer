#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IPC-D-356B 支持（P0/P1/P2）强测试
=================================
覆盖：
P0 — parse_ipc_units 认 B 版显式 UNITS（MIL 1 DEG 0 / MM 3 RAD 2 / IN / MM）
P1 — 遇 B 版 op-code（427/013/027/033/350/367/099）不崩溃、正确跳过
P2 — parse_ipc357_complex_records 解析复杂记录（层对 L01LNN + 顶/底面区分）

⚠️ 金标准来源：IPC-D-356B 附录 F 逐字样例（盲孔专例）
  见 IPC-D-356B 附录 F 例 19（PAGE 55）。

运行：python test_ipc356b.py （失败即 exit(1)）
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'src'))

from pcb_deliverables import (
    parse_ipc_units,
    parse_ipc_netlist,
    parse_ipc357_coords_to_mm,
    parse_ipc357_complex_records,
    IPC356_MAP,
)

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


def approx(a, b, tol=1e-6):
    return abs(a - b) <= tol


def _make_ipc(body, units="P  UNITS MIL 1 DEG 0"):
    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, "test.ipc")
    with open(path, "w", encoding="ascii") as f:
        f.write("C test\n" + units + "\nP JOB test\nP VER IPC-D-356B\nP IMAGE PRIMARY\n")
        f.write(body)
        f.write("999\n")
    return path


print("=" * 70)
print("IPC-D-356B 支持（P0/P1/P2）强测试")
print("=" * 70)

# ========== P0：UNITS 显式语法 ==========
print("\n【P0：parse_ipc_units 认 B 版显式 UNITS】")
for units, expect in [
    ("P  UNITS MIL 1 DEG 0", "mil"),
    ("P  UNITS MIL 2 DEG 1", "mil"),
    ("P  UNITS IN 4 DEG 0", "mil"),
    ("P  UNITS MM 3 RAD 2", "mm"),
    ("P  UNITS MM 3", "mm"),
]:
    p = _make_ipc("", units=units)
    check(f"UNITS '{units.split('UNITS')[-1].strip()}' → {expect}",
          parse_ipc_units(p) == expect,
          f"实际={parse_ipc_units(p)!r}")

# A 版兼容性回归（CUST/SI/METR 仍要认）
p_a1 = _make_ipc("", units="P  UNITS CUST 0")
check("A 版 CUST 0 → mil（回归）", parse_ipc_units(p_a1) == "mil")
check("IPC356_MAP 含 B 版 op-code", "427" in IPC356_MAP and "013" in IPC356_MAP and "350" in IPC356_MAP)

# ========== P1：B 版 op-code 不崩溃 ==========
print("\n【P1：遇 B 版 op-code 不崩溃、正确跳过】")
# 含 B 版全谱系 op-code 的混合内容
body_p1 = (
    "317NET_A     U1  -1  D 100PA00X+064804Y+053254X0200Y0000\n"
    "427NET1      CE   E      L01X+014400Y+081000DO6000I4000\n"
    "013NET1      L01L08   X+016900Y+081000CD0250\n"
    "027NET1      E      L08X+014400Y+081000DO6000I4000\n"
    "033NET2      L08X+010000Y+010000CD0250\n"
    "350SIG_L02   L01 X+009550Y+062880 L02\n"
    "367          L01L08   X+014400Y+081000CD1420\n"
    "099NET1      L01X+009000Y+009000\n"
)
ipc_p1 = _make_ipc(body_p1)
# parse_ipc_netlist 只解析 3xx 位号，B 版 op-code 不崩溃
nets, comps = parse_ipc_netlist(ipc_p1)
check("parse_ipc_netlist 遇 B 版不崩溃（返回 dict）", isinstance(nets, dict) and isinstance(comps, dict))
check("parse_ipc_netlist 仍解析到 U1", "U1" in comps, f"实际={comps!r}")
# parse_ipc357_coords_to_mm 只解析 317/327 的坐标，427/013 等跳过不崩溃
coords = parse_ipc357_coords_to_mm(ipc_p1)
check("parse_ipc357_coords_to_mm 遇 B 版不崩溃", isinstance(coords, list))
# 只应解析 317 那条（327 没有），427/013 不以 '3' 开头被跳过
check("coords 只含 317 记录 = 1 条", len(coords) == 1, f"实际={len(coords)}")

# ========== P2：复杂记录解析（层对 + 顶/底面） ==========
print("\n【P2：parse_ipc357_complex_records 解析层对】")
# 金标准：附录 F 例 19（盲孔）——427 顶面 → 4×013 层对 L01L08 → 027 底面 → 367
body_p2 = (
    "427NET1          CE            E      L01X+014400Y+081000DO6000I4000\n"
    "013NET1                         L01L08   X+016900Y+081000CD0250\n"
    "013NET1                         L01L08   X+011900Y+081000CD0250\n"
    "013NET1                         L01L08   X+014400Y+078500CD0250\n"
    "013NET1                         L01L08   X+014400Y+083500CD0250\n"
    "027NET1                        E      L08X+014400Y+081000DO6000I4000\n"
    "367                             L01L08   X+014400Y+081000CD1420\n"
)
ipc_p2 = _make_ipc(body_p2)
groups = parse_ipc357_complex_records(ipc_p2)
check("解析出 1 个复杂记录组", len(groups) == 1, f"实际={len(groups)}")
g = groups[0]
check("组 net = NET1", g["net"] == "NET1", f"实际={g['net']!r}")
check("primary_side = True（427 顶面）", g["primary_side"] is True)
check("层对 layers = (1, 8)（L01L08）", g["layers"] == (1, 8), f"实际={g['layers']!r}")
# 记录数：427(1) + 013(4) + 027(1) = 6 条（367 应被跳过，不归入组）
check("组内记录数 = 6（427+4×013+027）", len(g["records"]) == 6, f"实际={len(g['records'])}")
opcodes = [r["opcode"] for r in g["records"]]
check("首记录 opcode=427", opcodes[0] == "427", f"实际={opcodes}")
check("含 4 条 013", opcodes.count("013") == 4, f"实际={opcodes}")
check("末记录 opcode=027（底面测试区）", opcodes[-1] == "027", f"实际={opcodes}")
# 坐标换算校验：X+014400 = 14400 × 0.00254 = 36.5760 mm
first = g["records"][0]
check("X+014400 → 36.576mm", approx(first["x_mm"], 36.576, 1e-3), f"实际={first['x_mm']}")
check("Y+081000 → 205.74mm", approx(first["y_mm"], 205.74, 1e-3), f"实际={first['y_mm']}")

# 空文件 / 文件不存在
print("\n【P2 边界：无复杂记录 → 空列表】")
ipc_empty = _make_ipc("317NET_A  U1 -1 D 100PA00X+064804Y+053254\n")
check("无复杂记录返回 []", parse_ipc357_complex_records(ipc_empty) == [])
check("文件不存在返回 []", parse_ipc357_complex_records(os.path.join(tempfile.mkdtemp(), "no.ipc")) == [])

print()
print("=" * 70)
print(f"测试结果: {passed} 通过, {failed} 失败")
print("=" * 70)
if failed:
    print("❌ 存在失败测试")
    sys.exit(1)
else:
    print("✅ IPC-D-356B 支持（P0/P1/P2）全部通过")
    sys.exit(0)
