#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KiCad Netlist 解析器
支持KiCad 5.x/6.x/7.x的原生netlist格式（S-expression）
"""

import re


def parse_kicad_netlist(filepath):
    """解析KiCad netlist文件（.net格式，S-expression）"""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    result = {"design": {}, "components": [], "nets": []}
    
    # 解析design信息
    design_match = re.search(r'\(design\s+(.*?)\n\s*\)', content, re.DOTALL)
    if design_match:
        design_str = design_match.group(1)
        result["design"]["source"] = _extract_field(design_str, "source")
        result["design"]["date"] = _extract_field(design_str, "date")
    
    # 解析components
    comp_section = re.search(r'\(components(.*?)(?:\(libparts|\(nets|$)', content, re.DOTALL)
    if comp_section:
        comp_str = comp_section.group(1)
        for comp_match in re.finditer(r'\(comp\s+\(ref\s+"?([^")\s]+)"?\)(.*?)\)\s*(?=\(comp|\(libparts|\(nets|$)', comp_str, re.DOTALL):
            ref = comp_match.group(1)
            comp_body = comp_match.group(2)
            result["components"].append({
                "ref": ref,
                "value": _extract_field(comp_body, "value"),
                "footprint": _extract_field(comp_body, "footprint")
            })
    
    # 解析nets
    nets_section = re.search(r'\(nets(.*?)(?:\)[\s]*$)', content, re.DOTALL)
    if nets_section:
        nets_str = nets_section.group(1)
        for net_match in re.finditer(r'\(net\s+\(code\s+(\d+)\)\s+\(name\s+"?([^")\n]+)"?\)(.*?)\)\s*(?=\(net|$)', nets_str, re.DOTALL):
            code = int(net_match.group(1))
            name = net_match.group(2)
            net_body = net_match.group(3)
            nodes = []
            for node_match in re.finditer(r'\(node\s+\(ref\s+"?([^")\s]+)"?\)\s+\(pin\s+"?([^")\s]+)"?\)', net_body):
                nodes.append({"ref": node_match.group(1), "pin": node_match.group(2)})
            result["nets"].append({"code": code, "name": name, "nodes": nodes})
    
    return result


def _extract_field(text, field_name):
    """从S-expression中提取字段值"""
    pattern = rf'\({field_name}\s+"?([^")\n]+)"?\)'
    match = re.search(pattern, text)
    return match.group(1) if match else ""


def build_component_pin_map(netlist_data):
    """建立元件引脚到网络的映射"""
    pin_map = {}
    for net in netlist_data["nets"]:
        net_name = net["name"]
        for node in net["nodes"]:
            ref, pin = node["ref"], node["pin"]
            if ref not in pin_map:
                pin_map[ref] = {}
            pin_map[ref][pin] = net_name
    return pin_map


def find_power_nets(netlist_data):
    """识别电源网络"""
    power_keywords = ["VCC", "VDD", "VIN", "VBAT", "V3V3", "V5V", "V12V", "V1V8", "PWR"]
    return [net for net in netlist_data["nets"] 
            if any(kw in net["name"].upper() for kw in power_keywords)]


def find_ground_nets(netlist_data):
    """识别地网络"""
    gnd_keywords = ["GND", "AGND", "DGND", "VSS"]
    return [net for net in netlist_data["nets"] 
            if any(kw in net["name"].upper() for kw in gnd_keywords)]


def find_decoupling_caps(netlist_data, target_ref):
    """查找指定IC的去耦电容（真实连接）"""
    # 获取IC的电源引脚
    ic_power_pins = {}
    for net in netlist_data["nets"]:
        if any(kw in net["name"].upper() for kw in ["VCC", "VDD", "VIN"]):
            for node in net["nodes"]:
                if node["ref"] == target_ref:
                    ic_power_pins[node["pin"]] = net["name"]
    
    # 查找连接到同一电源网络的电容
    decoupling_caps = []
    for pin, net_name in ic_power_pins.items():
        for net in netlist_data["nets"]:
            if net["name"] == net_name:
                for node in net["nodes"]:
                    if node["ref"].startswith("C"):
                        decoupling_caps.append({
                            "cap_ref": node["ref"],
                            "net": net_name,
                            "ic_pin": pin
                        })
                        break
    return decoupling_caps


def generate_netlist_report(netlist_data):
    """生成netlist统计报告"""
    report = {
        "total_components": len(netlist_data["components"]),
        "total_nets": len(netlist_data["nets"]),
        "power_nets": len(find_power_nets(netlist_data)),
        "ground_nets": len(find_ground_nets(netlist_data))
    }
    return report


if __name__ == "__main__":
    print("KiCad Netlist解析器 - 用法示例：")
    print("  netlist = parse_kicad_netlist('project.net')")
    print("  pin_map = build_component_pin_map(netlist)")
    print("  caps = find_decoupling_caps(netlist, 'U1')")
