#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
xy.xlsx 坐标单位处理 强测试（Golden Test）
==========================================
覆盖：
1. parse_ipc_units       —— IPC-356 UNITS CUST/SI/METR 三态（认识/无声明/未枚举）
2. parse_xy_xlsx 显式单位 —— mil→×0.0254、mm→原样
3. parse_xy_xlsx fail-fast —— 无 IPC 声明时抛 ValueError（不静默猜）
4. detect_unit_in_dir     —— 跨目录递归探测 + 未识别值抛 ValueError

运行：python test_xy_unit.py  （失败即 exit(1)）
"""

import sys
import os
import zipfile
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'src'))

from pcb_deliverables import parse_ipc_units, parse_xy_xlsx, detect_unit_in_dir

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


def _make_xy_xlsx(x, y):
    """构造最小 xlsx（含表头 + 一行数据），返回路径。"""
    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, "xy.xlsx")
    shared_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="12" uniqueCount="12">'
        '<si><t>PartType</t></si><si><t>RefDes</t></si><si><t>PartDecal</t></si>'
        '<si><t>Pins</t></si><si><t>Layer</t></si><si><t>Orient.</t></si>'
        '<si><t>X</t></si><si><t>Y</t></si><si><t>SMD</t></si><si><t>Glued</t></si>'
        '<si><t>CAP</t></si><si><t>C1</t></si><si><t>Top</t></si><si><t>No</t></si>'
        '</sst>'
    )
    # 表头行 A1..J1 用 sharedStrings 0..9；数据行 G/H 直接数值（X/Y）
    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetData>'
        '<row r="1">'
        '<c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c>'
        '<c r="C1" t="s"><v>2</v></c><c r="D1" t="s"><v>3</v></c>'
        '<c r="E1" t="s"><v>4</v></c><c r="F1" t="s"><v>5</v></c>'
        '<c r="G1" t="s"><v>6</v></c><c r="H1" t="s"><v>7</v></c>'
        '<c r="I1" t="s"><v>8</v></c><c r="J1" t="s"><v>9</v></c>'
        '</row>'
        '<row r="2">'
        '<c r="A2" t="s"><v>10</v></c><c r="B2" t="s"><v>11</v></c>'
        '<c r="C2" t="s"><v>10</v></c><c r="D2"><v>2</v></c>'
        '<c r="E2" t="s"><v>12</v></c><c r="F2"><v>0</v></c>'
        f'<c r="G2"><v>{x}</v></c><c r="H2"><v>{y}</v></c>'
        '<c r="I2" t="s"><v>13</v></c><c r="J2" t="s"><v>13</v></c>'
        '</row>'
        '</sheetData></worksheet>'
    )
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('xl/sharedStrings.xml', shared_xml)
        z.writestr('xl/worksheets/sheet1.xml', sheet_xml)
    return path


def _make_ipc(tmpdir, units_line):
    """在 tmpdir 写一个含单位声明的 .ipc 文件。"""
    path = os.path.join(tmpdir, "test.ipc")
    with open(path, "w", encoding="ascii") as f:
        f.write("C test\n" + units_line + "\nP JOB test\n")
    return path


# ========== 1. parse_ipc_units ==========
print("=" * 70)
print("xy.xlsx 坐标单位处理 强测试")
print("=" * 70)
print("\n【1. parse_ipc_units 单位声明探测】")

tmpdir = tempfile.mkdtemp()

ipc_cust = _make_ipc(tmpdir, "P  UNITS CUST 0")
check("UNITS CUST → mil", parse_ipc_units(ipc_cust) == "mil")

ipc_metr = _make_ipc(tmpdir, "P  UNITS METR 2")
check("UNITS METR → mm", parse_ipc_units(ipc_metr) == "mm")

# 有 UNITS 声明但值未枚举 → 应抛 ValueError（不是静默 None），P8 要求
ipc_unknown = _make_ipc(tmpdir, "P  UNITS XXX")
try:
    parse_ipc_units(ipc_unknown)
    check("未识别声明值 → 抛 ValueError", False, "未抛异常")
except ValueError as e:
    check("未识别声明值 → 抛 ValueError", True, str(e)[:50])

# 完全没有 UNITS 声明 → None（无声明，与"未识别值"区分）
ipc_nounits = _make_ipc(tmpdir, "P  TITLE x")  # 无 UNITS 行
check("无 UNITS 声明 → None", parse_ipc_units(ipc_nounits) is None)

check("文件不存在 → None", parse_ipc_units(os.path.join(tmpdir, "no.ipc")) is None)

# ========== 2. parse_xy_xlsx 显式单位 ==========
print("\n【2. parse_xy_xlsx 显式单位】")

xy_path = _make_xy_xlsx(5259.93, 5660.0)

# mil → ×0.0254
comps_mil = parse_xy_xlsx(xy_path, coord_unit="mil")
c1 = comps_mil[0]
check("mil → X=5259.93→133.602", approx(float(c1[6]), 133.602, 0.001), f"实际={c1[6]}")
check("mil → Y=5660→143.764", approx(float(c1[7]), 143.764, 0.001), f"实际={c1[7]}")

# mm → 原样
comps_mm = parse_xy_xlsx(xy_path, coord_unit="mm")
c1mm = comps_mm[0]
check("mm → X 原样=5259.93", approx(float(c1mm[6]), 5259.93, 0.001), f"实际={c1mm[6]}")
check("mm → Y 原样=5660.0", approx(float(c1mm[7]), 5660.0, 0.001), f"实际={c1mm[7]}")

# 非法 unit
try:
    parse_xy_xlsx(xy_path, coord_unit="foo")
    check("非法 unit → 抛 ValueError", False)
except ValueError:
    check("非法 unit → 抛 ValueError", True)

# ========== 3. fail-fast ==========
print("\n【3. fail-fast：无 IPC 声明时不静默猜】")

# xy 目录里只有 xy.xlsx，没有 .ipc（tmp 目录里没放 .ipc）
try:
    parse_xy_xlsx(xy_path)  # coord_unit=None，同目录无 .ipc
    check("无 .ipc → 抛 ValueError fail-fast", False, "未抛异常")
except ValueError as e:
    check("无 .ipc → 抛 ValueError fail-fast", True, str(e)[:60])

# 真实目录有 .ipc（在同一目录放一个 CUST 的 ipc，名字非 test.ipc 也能被 glob *.ipc 命中）
real_ipc = os.path.join(os.path.dirname(xy_path), "real.ipc")
with open(real_ipc, "w", encoding="ascii") as f:
    f.write("P  UNITS CUST 0\n")
comps_auto = parse_xy_xlsx(xy_path)  # 自动探测
check("自动探测(同目录 .ipc CUST) → mil 归一",
      approx(float(comps_auto[0][6]), 133.602, 0.001), f"实际={comps_auto[0][6]}")

# ========== 4. detect_unit_in_dir 跨目录递归探测 ==========
print("\n【4. detect_unit_in_dir 跨目录递归探测】")

# 构造 PADS 投板结构：CAM/CAM/*.ipc（SI=mm）
board_dir = tempfile.mkdtemp()
cam_dir = os.path.join(board_dir, "X-CAM", "X-CAM")
os.makedirs(cam_dir)
# 在 CAM 目录放一个 SI（mm）的 .ipc
ipc_path = os.path.join(cam_dir, "board.ipc")
with open(ipc_path, "w", encoding="ascii") as f:
    f.write("C x\nP  UNITS SI\nP JOB x\n")
check("detect_unit_in_dir 找到 CAM 下的 SI → mm", detect_unit_in_dir(board_dir) == "mm")

# P8：detect_unit_in_dir 遇到"有声明但值未枚举"→ 抛 ValueError（不是静默 None）
board_dir2 = tempfile.mkdtemp()
cam_dir2 = os.path.join(board_dir2, "X-CAM", "X-CAM")
os.makedirs(cam_dir2)
ipc_unknown2 = os.path.join(cam_dir2, "board.ipc")
with open(ipc_unknown2, "w", encoding="ascii") as f:
    f.write("C x\nP  UNITS FOO\nP JOB x\n")
try:
    detect_unit_in_dir(board_dir2)
    check("detect_unit_in_dir 未识别值 → 抛 ValueError", False, "未抛异常")
except ValueError as e:
    check("detect_unit_in_dir 未识别值 → 抛 ValueError", True, str(e)[:50])

# detect_unit_in_dir 目录完全没有 .ipc → None
board_dir3 = tempfile.mkdtemp()
check("detect_unit_in_dir 无 .ipc → None", detect_unit_in_dir(board_dir3) is None)

# 构造 xy.xlsx 在 ASM 目录（无同目录 .ipc）→ parse_xy_xlsx 同目录探测应 fail-fast，
# 但通过 detect_unit_in_dir + coord_unit 传参应成功
xy_asm = _make_xy_xlsx(100.0, 200.0)  # 这个在另一个 tmpdir，坐标 mm
# 用 detect_unit_in_dir 拿到 mm，再显式传给 parse_xy_xlsx（模拟 analyze_deliverables 行为）
unit = detect_unit_in_dir(board_dir)
comps = parse_xy_xlsx(xy_asm, coord_unit=unit)  # 显式 mm
check("coord_unit=mm(来自detect) → X 原样=100", approx(float(comps[0][6]), 100.0, 0.001))

print()
print("=" * 70)
print(f"测试结果: {passed} 通过, {failed} 失败")
print("=" * 70)
if failed:
    print("❌ 存在失败测试")
    sys.exit(1)
else:
    print("✅ xy.xlsx 坐标单位处理 全部通过")
    sys.exit(0)
