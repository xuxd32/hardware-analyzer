#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OrCAD EXPANDED 网表解析器 + 容值代码解析 强测试（Golden Test）
================================================================
覆盖三个层次：
1. parse_capacitance_code   —— EIA 代码 / 显式单位(大小写) / NC-X7R 跳过 / 边界
2. parse_orcad_* 三函数      —— 用构造样本验证结构 + 字段映射
3. 真实文件端到端            —— 若提供可选样本，验证元件/网络/电容计数锚点

运行：python test_orcad_expanded.py  （失败即 exit(1)）
"""

import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'src'))

from calculators import parse_capacitance, parse_capacitance_code
from orcad_expanded_parser import (
    parse_orcad_partlist, parse_orcad_library, parse_orcad_netlist,
    parse_orcad_expanded, auto_detect_expanded,
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


def approx(a, b, tol):
    return abs(a - b) <= tol


# ========== 1. parse_capacitance_code ==========
print("=" * 70)
print("OrCAD EXPANDED 网表解析 + 容值代码解析 强测试")
print("=" * 70)
print("\n【1. parse_capacitance_code 容值代码解析】")

check("104 → 100nF (1e-7)", approx(parse_capacitance_code("104"), 1e-7, 1e-12))
check("105 → 1uF (1e-6)", approx(parse_capacitance_code("105"), 1e-6, 1e-9))
check("106 → 10uF (1e-5)", approx(parse_capacitance_code("106"), 1e-5, 1e-8))
check("226 → 22uF (2.2e-5)", approx(parse_capacitance_code("226"), 2.2e-5, 1e-9))
check("475 → 4.7uF (4.7e-6)", approx(parse_capacitance_code("475"), 4.7e-6, 1e-10))
check("103 → 10nF (1e-8)", approx(parse_capacitance_code("103"), 1e-8, 1e-12))
check("393 → 39nF (3.9e-8)", approx(parse_capacitance_code("393"), 3.9e-8, 1e-12))

check("33PF → 33pF", approx(parse_capacitance_code("33PF"), 3.3e-11, 1e-15))
check("22pF → 22pF", approx(parse_capacitance_code("22pF"), 2.2e-11, 1e-15))
check("100pF → 100pF", approx(parse_capacitance_code("100pF"), 1e-10, 1e-14))

# 带后缀的真实写法
check("470uF/50V → 470uF", approx(parse_capacitance_code("470uF/50V"), 4.7e-4, 1e-8))
check("100uF/10V → 100uF", approx(parse_capacitance_code("100uF/10V"), 1e-4, 1e-8))
check("100pF_0R → 100pF", approx(parse_capacitance_code("100pF_0R"), 1e-10, 1e-14))
check("27pF_NC → None(不焊接)", parse_capacitance_code("27pF_NC") is None)
check("103/NC → None(不焊接)", parse_capacitance_code("103/NC") is None)

check("NC → None", parse_capacitance_code("NC") is None)
check("X7R → None", parse_capacitance_code("X7R") is None)
check("空串 → None", parse_capacitance_code("") is None)
check("None → None", parse_capacitance_code(None) is None)
check("非字符串 → None", parse_capacitance_code(104) is None)

check("parse_capacitance('100nF') 仍正常", approx(parse_capacitance("100nF"), 1e-7, 1e-12))
check("parse_capacitance('222') 不识别→None", parse_capacitance("222") is None)

# ========== 2. 构造样本验证三函数 ==========
print("\n【2. parse_orcad_* 三函数结构验证（构造样本）】")

import tempfile

tmpdir = tempfile.mkdtemp()

prt_content = """FILE_TYPE = EXPANDEDPARTLIST;
{ Using PSTWRITER 25.1.0 }
PART_NAME
 C1 'CAP 0805_C0603_104':;

SECTION_NUMBER 1
 '@X.INS1@SIGMA.CAP 0805.NORMAL(CHIPS)':
  PRIM_FILE='.\\pstchip.dat',
  XY='(1029,99)',
  SECTION='';

PART_NAME
 EC2 'CAP 0805_ECAP-12_106':;

SECTION_NUMBER 1
 '@X.INS2@SIGMA.CAP.NORMAL(CHIPS)':
  PRIM_FILE='.\\pstchip.dat',
  XY='(500,600)',
  SECTION='';

PART_NAME
 R1 'RES-SMT_R0402_10K1%':;

SECTION_NUMBER 1
 '@X.INS3@SIGMA.RES.NORMAL(CHIPS)':
  XY='(100,100)',
  SECTION='';
"""

chip_content = """FILE_TYPE=LIBRARY_PARTS;
primitive 'CAP 0805_C0603_104';
  pin
    '1': PIN_NUMBER='(1)';
    '2': PIN_NUMBER='(2)';
  end_pin;
  body
    PART_NAME='CAP 0805';
    JEDEC_TYPE='C0603';
    VALUE='104';
  end_body;
end_primitive;
primitive 'CAP 0805_ECAP-12_106';
  pin
    '1': PIN_NUMBER='(1)';
    '2': PIN_NUMBER='(2)';
  end_pin;
  body
    PART_NAME='CAP 0805';
    JEDEC_TYPE='ECAP-12';
    VALUE='106';
  end_body;
end_primitive;
"""

net_content = """FILE_TYPE = EXPANDEDNETLIST;
NET_NAME
 'VDD_3V3'
  C_SIGNAL='@vdd_3v3';
NODE_NAME\tC1 1
  '1':
SCH_LOC='(1,2)'
;
NODE_NAME\tEC2 1
  '1':
SCH_LOC='(3,4)'
;
NODE_NAME\tU1 5
  '3':
;
NET_NAME
 'GND'
NODE_NAME\tC1 2
  '2':
;
"""

prt_path = os.path.join(tmpdir, "pstxprt.dat")
chip_path = os.path.join(tmpdir, "pstchip.dat")
net_path = os.path.join(tmpdir, "pstxnet.dat")
with open(prt_path, "w", encoding="utf-8") as f:
    f.write(prt_content)
with open(chip_path, "w", encoding="utf-8") as f:
    f.write(chip_content)
with open(net_path, "w", encoding="utf-8") as f:
    f.write(net_content)

parts = parse_orcad_partlist(prt_path)
check("partlist 解析 3 个元件", len(parts) == 3, f"实际={len(parts)}")
check("partlist C1 复合名", parts[0]["part_name"] == "CAP 0805_C0603_104")
check("partlist C1 xy=(1029,99)", parts[0]["xy"] == (1029, 99))

lib = parse_orcad_library(chip_path)
check("library 解析 2 个 primitive", len(lib) == 2, f"实际={len(lib)}")
check("library C0603 value=104", lib["CAP 0805_C0603_104"]["value"] == "104")
check("library ECAP-12 jedec", lib["CAP 0805_ECAP-12_106"]["jedec_type"] == "ECAP-12")

nets = parse_orcad_netlist(net_path)
check("netlist 解析 2 个网络", len(nets) == 2, f"实际={len(nets)}")
check("VDD_3V3 有 3 个节点", len(nets[0]["nodes"]) == 3)
check("GND 有 1 个节点", len(nets[1]["nodes"]) == 1)
check("VDD_3V3 节点含 C1/1", any(n["ref"] == "C1" and n["pin"] == "1" for n in nets[0]["nodes"]))

merged = parse_orcad_expanded(prt_path, net_path, chip_path)
check("合并无 error", "error" not in merged)
check("合并 components=3", len(merged["components"]) == 3)
check("合并 nets=2", len(merged["nets"]) == 2)
c1 = [c for c in merged["components"] if c["ref"] == "C1"][0]
check("C1 value 映射=104", c1["value"] == "104")
check("C1 footprint 映射=C0603", c1["footprint"] == "C0603")
ec2 = [c for c in merged["components"] if c["ref"] == "EC2"][0]
check("EC2 footprint=ECAP-12", ec2["footprint"] == "ECAP-12")
check("auto_detect_expanded 真", auto_detect_expanded(prt_path) is True)

# ========== 3. 真实文件端到端（可选，存在才测） ==========
print("\n【3. 真实文件端到端（可选样本）】")
REAL_PRT = os.environ.get("HW_REAL_PRT", "")
if os.path.isfile(REAL_PRT):
    r = parse_orcad_expanded(REAL_PRT)
    check("真实文件解析无 error", "error" not in r)
    check("真实文件元件=715", len(r["components"]) == 715, f"实际={len(r['components'])}")
    check("真实文件网络=464", len(r["nets"]) == 464, f"实际={len(r['nets'])}")
    caps = [c for c in r["components"] if c["ref"].upper().startswith(("C", "EC"))]
    check("真实文件电容/电解=195", len(caps) == 195, f"实际={len(caps)}")
    unparsed = []
    for c in caps:
        v = c["value"]
        f = parse_capacitance_code(v)
        if f is None:
            # None 是预期（不焊接 NC / 材质占位），不放行才算"真未解析"
            up = v.strip().upper()
            is_placeholder = (up in ("NC", "X7R", "X5R", "C0G", "DNP", "N/A", "NA"))
            has_nc = ("NC" in up)
            if not (is_placeholder or has_nc):
                unparsed.append((c["ref"], v))
    check("电容 value 全部可解析或明确占位", not unparsed, f"真未解析={unparsed[:10]}")
    no_ft = [c["ref"] for c in caps if not c["footprint"]]
    check("电容 footprint 均非空", not no_ft, f"缺封装={no_ft[:10]}")
else:
    print("[跳过] 可选样本不存在，跳过真实文件端到端")

# ========== 总结 ==========
print()
print("=" * 70)
print(f"测试结果: {passed} 通过, {failed} 失败")
print("=" * 70)
if failed:
    print("❌ 存在失败测试")
    sys.exit(1)
else:
    print("✅ OrCAD EXPANDED 网表解析 + 容值代码解析 全部通过")
    sys.exit(0)
