#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PADS2000 网表解析器

支持 PADS / PADS-Logic / PADS-View 导出的 `.asc` 网表（俗称 PADS2000 格式）。

格式示例（实测某 PADS `.asc` 网表，约 1300 行）:

    *PADS2000*
    *PART*
    BT1              BAT3.3
    C100             C0402
    ...
    *NET*
    *SIGNAL* 27M_IN
    U16.18 Y4.3 C116.2 R108.1
    *SIGNAL* DVR_AV_V12
    FB4.1 FB3.1 FB8.1 FB7.1 C3508.1 L49.1 TP108.1 C3512.1
    TC5.1 R262.2 C3514.1 C3509.1 C3513.1
    ...
    *END*

结构要点（都来自实测，不是猜的）:
  1. 首行 `*PADS2000*` 是格式标识
  2. `*PART*` 段：每行 "引用号  封装名"，两者之间是空格对齐
  3. `*NET*` 段：每条网络以 `*SIGNAL* 网络名` 起头，
     紧随其后的一行或多行是节点，节点写法是 "引用号.引脚号" 用空格分隔
     —— 一条网络可能跨多行（实测 DVR_AV_V12 就跨了 2 行）
  4. `*END*` 结束

注意:
  * 这里没有元件"值"（value），PADS 的 .asc 只有引用号+封装；
    为了与其它解析器返回结构一致，value 填封装名，footprint 也填封装名。
  * 引脚号在 PADS 里可能是字母（如 U1.A3、J1.S1），不能假设为数字。
"""

import re


_PART_HEADER = re.compile(r"^\*PART\*\s*$", re.IGNORECASE)
_NET_HEADER = re.compile(r"^\*NET\*\s*$", re.IGNORECASE)
_SIGNAL = re.compile(r"^\*SIGNAL\*\s*(.+?)\s*$", re.IGNORECASE)
_END = re.compile(r"^\*END\*\s*$", re.IGNORECASE)
# 节点：引用号.引脚号  —— 引用号字母+数字，引脚号可以是数字或字母
_NODE = re.compile(r"^([A-Za-z][A-Za-z0-9_]*)\.([A-Za-z0-9_]+)$")


def detect_pads2000(filepath):
    """只读文件头，判断是否为 PADS2000 网表。

    返回 True/False，不抛异常。
    """
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            head = f.read(4096)
    except OSError:
        return False
    if "*PADS2000*" in head.upper():
        return True
    # 有的导出不带首行标识，但一定同时有 *PART* 与 *NET*
    up = head.upper()
    return ("*PART*" in up) and ("*NET*" in up)


def parse_pads2000_netlist(filepath):
    """解析 PADS2000 (.asc) 网表。

    返回结构与其它解析器一致：
        {
            "components": [{"ref":..., "value":..., "footprint":...}, ...],
            "nets": [{"name":..., "nodes": [{"ref":..., "pin":...}, ...]}, ...]
        }
    """
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.read().splitlines()

    result = {"components": [], "nets": []}

    section = None            # None / "part" / "net"
    seen_refs = set()
    current_net = None        # 当前网络名
    current_nodes = []        # 当前网络的节点列表

    def _flush_net():
        """把当前累积的网络收尾入库。"""
        nonlocal current_net, current_nodes
        if current_net is not None:
            result["nets"].append({
                "name": current_net,
                "nodes": current_nodes,
            })
        current_net = None
        current_nodes = []

    for raw in lines:
        line = raw.strip()
        if not line:
            continue

        # 段切换
        if _PART_HEADER.match(line):
            section = "part"
            continue
        if _NET_HEADER.match(line):
            _flush_net()
            section = "net"
            continue
        if _END.match(line):
            _flush_net()
            section = None
            continue
        if line.startswith("*PADS2000*") or line.startswith("*PADS"):
            continue

        if section == "part":
            # "BT1              BAT3.3"  —— 空格分隔，取前两段
            parts = line.split()
            if len(parts) < 2:
                continue
            ref = parts[0]
            pkg = parts[1]
            if ref in seen_refs:
                continue
            seen_refs.add(ref)
            result["components"].append({
                "ref": ref,
                "value": pkg,        # PADS 网表无值字段，用封装名代替
                "footprint": pkg,
            })
            continue

        if section == "net":
            m = _SIGNAL.match(line)
            if m:
                _flush_net()
                current_net = m.group(1).strip()
                continue
            # 节点行：可能一行多个，也可能跨多行（都累加到当前网络）
            if current_net is None:
                continue
            for token in line.split():
                nm = _NODE.match(token)
                if nm:
                    current_nodes.append({
                        "ref": nm.group(1),
                        "pin": nm.group(2),
                    })

    _flush_net()
    return result


def build_component_pin_map_pads(netlist_data):
    """建立 元件 -> {引脚: 网络名} 的映射（PADS 格式）。"""
    pin_map = {}
    for net in netlist_data.get("nets", []):
        net_name = net["name"]
        for node in net["nodes"]:
            ref, pin = node["ref"], node["pin"]
            pin_map.setdefault(ref, {})[pin] = net_name
    return pin_map


def find_power_nets_pads(netlist_data):
    """识别电源网络（PADS 格式）。"""
    power_keywords = ["VCC", "VDD", "VIN", "VBAT", "V3V3", "V5V", "V12V", "PWR"]
    return [net for net in netlist_data.get("nets", [])
            if any(kw in net["name"].upper() for kw in power_keywords)]


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("用法: python pads_netlist_parser.py <file.asc>")
        sys.exit(1)
    fp = sys.argv[1]
    print("detect =", detect_pads2000(fp))
    data = parse_pads2000_netlist(fp)
    print("元件:", len(data["components"]))
    print("网络:", len(data["nets"]))
    for net in data["nets"][:5]:
        print("  %-24s %d 个节点" % (net["name"], len(net["nodes"])))
