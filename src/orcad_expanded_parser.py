#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OrCAD PSPICE EXPANDED 展开网表解析器。

解析 OrCAD Capture 用 PSTWRITER 导出的三份展开文本网表：
  - pstxprt.dat  (FILE_TYPE = EXPANDEDPARTLIST)  元件清单（位号→复合名/坐标）
  - pstxnet.dat  (FILE_TYPE = EXPANDEDNETLIST)   网络连接（网络名→引脚/坐标）
  - pstchip.dat  (FILE_TYPE = LIBRARY_PARTS)     库封装（复合名→JEDEC_TYPE/VALUE）

输出结构对齐现有其它 parser 的契约，便于 main.py 无缝接入：
  {
    "design": {...},
    "components": [{"ref", "value", "footprint", "part_name", "xy"}],
    "nets": [{"code", "name", "nodes": [{"ref", "pin"}]}],
  }

字段映射：
  - ref        = PART_NAME 下一行的位号（如 "C1"、"EC2"、"U1"）
  - part_name  = 复合名（如 "CAP 0805_C0402_104"）
  - value      = pstchip.dat 里的 VALUE（三位 EIA 代码如 "104"，或 "33PF"）
                 —— 注意：这是"值代码"，需经 calculators.parse_capacitance_code()
                    归一为法拉，不能直接喂 parse_capacitance()。
  - footprint  = pstchip.dat 里的 JEDEC_TYPE（如 "C0402"、"ECAP-12"）
  - xy         = 原理图坐标 (x, y)，来自 XY='(x,y)'

只读解析，绝不修改输入文件。
"""

import os
import re


def _parse_kv_block(text, keys):
    """在给定文本里提取 KEY='VALUE' 形式的字段，返回 {key: value}。"""
    result = {}
    for key in keys:
        m = re.search(r"%s='([^']*)'" % re.escape(key), text)
        if m:
            result[key] = m.group(1)
    return result


def _coord_from(s):
    """从 '(x,y)' 或 '(x,y,w,h)' 提取前两个坐标为 (int,int)，失败返回 None。"""
    if not s:
        return None
    nums = re.findall(r"-?\d+", s)
    if len(nums) >= 2:
        return (int(nums[0]), int(nums[1]))
    return None


def parse_orcad_partlist(prt_path):
    """解析 pstxprt.dat（元件清单）。

    返回 list[dict]，每项 {ref, part_name, xy, orient, mirror, bbox}。
    """
    if not os.path.isfile(prt_path):
        return []
    with open(prt_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    components = []
    # PART_NAME 后单独一行是位号，再一行是 '复合名':;
    # 例：
    #   PART_NAME
    #    C1 'CAP 0805_C0603_104':;
    pattern = re.compile(
        r"PART_NAME\s*\n\s*(\S+)\s+'([^']*)':;\s*"
        r"(.*?)(?=PART_NAME\s*\n|$)",
        re.DOTALL,
    )
    for m in pattern.finditer(content):
        ref = m.group(1)
        part_name = m.group(2)
        body = m.group(3)
        kv = _parse_kv_block(body, ["XY", "SCH_ORIENT", "SCH_MIRROR", "SCH_BBOX"])
        components.append({
            "ref": ref,
            "part_name": part_name,
            "xy": _coord_from(kv.get("XY")),
            "orient": kv.get("SCH_ORIENT"),
            "mirror": kv.get("SCH_MIRROR"),
            "bbox": kv.get("SCH_BBOX"),
        })
    return components


def parse_orcad_library(chip_path):
    """解析 pstchip.dat（库封装）。

    返回 {part_name: {"part_name", "jedec_type", "value"}}。
    """
    result = {}
    if not os.path.isfile(chip_path):
        return result
    with open(chip_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    pattern = re.compile(r"primitive '([^']*)';(.*?)end_primitive;", re.DOTALL)
    for m in pattern.finditer(content):
        name = m.group(1)
        body = m.group(2)
        kv = _parse_kv_block(body, ["PART_NAME", "JEDEC_TYPE", "VALUE"])
        result[name] = {
            "part_name": kv.get("PART_NAME", ""),
            "jedec_type": kv.get("JEDEC_TYPE", ""),
            "value": kv.get("VALUE", ""),
        }
    return result


def parse_orcad_netlist(net_path):
    """解析 pstxnet.dat（网络连接）。

    返回 list[dict]，每项 {name, nodes: [{ref, pin}]}。
    """
    if not os.path.isfile(net_path):
        return []
    with open(net_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    nets = []
    # NET_NAME
    # '网络名'
    #  ... 里面若干 NODE_NAME\t位号 引脚
    # （直到下一个 NET_NAME）
    pattern = re.compile(
        r"NET_NAME\s*\n\s*'([^']*)'\s*(.*?)(?=NET_NAME\s*\n|$)",
        re.DOTALL,
    )
    code = 0
    for m in pattern.finditer(content):
        code += 1
        name = m.group(1)
        body = m.group(2)
        nodes = []
        for nm in re.finditer(r"NODE_NAME\s+(\S+)\s+(\S+)", body):
            nodes.append({"ref": nm.group(1), "pin": nm.group(2)})
        nets.append({"code": code, "name": name, "nodes": nodes})
    return nets


def parse_orcad_expanded(prt_path, net_path=None, chip_path=None):
    """解析整套 OrCAD EXPANDED 展开网表，合并成 main.py 契约结构。

    参数:
        prt_path: pstxprt.dat 路径（必填）
        net_path: pstxnet.dat 路径；缺省在同目录按 pstxnet.dat 推断
        chip_path: pstchip.dat 路径；缺省在同目录按 pstchip.dat 推断

    返回:
        {"design", "components", "nets"}；prt_path 不存在返回 {"error": "..."}。
    """
    if not os.path.isfile(prt_path):
        return {"error": f"元件清单文件不存在: {prt_path}"}

    d = os.path.dirname(prt_path) or "."
    if net_path is None:
        net_path = os.path.join(d, "pstxnet.dat")
    if chip_path is None:
        chip_path = os.path.join(d, "pstchip.dat")

    parts = parse_orcad_partlist(prt_path)
    lib = parse_orcad_library(chip_path) if os.path.isfile(chip_path) else {}
    raw_nets = parse_orcad_netlist(net_path) if os.path.isfile(net_path) else []

    components = []
    for p in parts:
        info = lib.get(p["part_name"], {})
        components.append({
            "ref": p["ref"],
            "value": info.get("value", ""),
            "footprint": info.get("jedec_type", ""),
            "part_name": p["part_name"],
            "xy": p.get("xy"),
        })

    nets = [{"code": n["code"], "name": n["name"], "nodes": n["nodes"]}
            for n in raw_nets]

    return {
        "design": {"source": "OrCAD EXPANDED (PSTWRITER)"},
        "components": components,
        "nets": nets,
    }


def auto_detect_expanded(prt_path):
    """检测 pstxprt.dat 是否为 OrCAD EXPANDED 格式。"""
    if not os.path.isfile(prt_path):
        return False
    with open(prt_path, "r", encoding="utf-8", errors="ignore") as f:
        head = f.read(200)
    return "EXPANDEDPARTLIST" in head.upper()


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("用法: python orcad_expanded_parser.py <pstxprt.dat> [pstxnet.dat] [pstchip.dat]")
        sys.exit(1)
    prt = sys.argv[1]
    net = sys.argv[2] if len(sys.argv) > 2 else None
    chip = sys.argv[3] if len(sys.argv) > 3 else None
    r = parse_orcad_expanded(prt, net, chip)
    if "error" in r:
        print(r["error"])
        sys.exit(1)
    print(f"元件: {len(r['components'])} | 网络: {len(r['nets'])}")
    caps = [c for c in r["components"] if c["ref"].upper().startswith(("C", "EC"))]
    print(f"电容/电解: {len(caps)}")
    for c in caps[:10]:
        print(f"  {c['ref']:>6}  {c['part_name']:<30}  ft={c['footprint']:<8}  val={c['value']}")

