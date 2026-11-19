#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OrCAD/Allegro Netlist 解析器
支持Allegro格式的netlist（文本格式）
"""

import re


def parse_allegro_netlist(filepath):
    """
    解析OrCAD Allegro netlist文件
    
    格式示例:
    $PACKAGES
    U1  STM32F103  QFP-100
    C1  CAP        0402
    
    $NETS
    VCC:
      U1-1
      C1-1
    GND:
      U1-100
      C1-2
    """
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
    
    result = {"components": [], "nets": []}
    
    # 解析$PACKAGES段
    packages_match = re.search(r'\$PACKAGES\s+(.*?)(?:\$NETS|\$END|$)', content, re.DOTALL | re.IGNORECASE)
    if packages_match:
        packages_str = packages_match.group(1)
        for line in packages_str.strip().split('\n'):
            line = line.strip()
            if not line or line.startswith('!') or line.startswith('#'):
                continue
            parts = line.split()
            if len(parts) >= 2:
                result["components"].append({
                    "ref": parts[0],
                    "value": parts[1],
                    "footprint": parts[2] if len(parts) > 2 else ""
                })
    
    # 解析$NETS段
    nets_match = re.search(r'\$NETS\s+(.*?)(?:\$END|$)', content, re.DOTALL | re.IGNORECASE)
    if nets_match:
        nets_str = nets_match.group(1)
        current_net = None
        current_nodes = []
        
        for line in nets_str.split('\n'):
            line = line.strip()
            if not line or line.startswith('!') or line.startswith('#'):
                continue
            
            # 网络名行（以:结尾）
            if ':' in line and not line.startswith(' '):
                if current_net:
                    result["nets"].append({
                        "name": current_net,
                        "nodes": current_nodes
                    })
                current_net = line.rstrip(':').strip()
                current_nodes = []
            # 节点行（缩进或以空格开头）
            elif current_net and '-' in line:
                parts = line.split('-')
                if len(parts) == 2:
                    current_nodes.append({
                        "ref": parts[0].strip(),
                        "pin": parts[1].strip()
                    })
        
        # 添加最后一个网络
        if current_net:
            result["nets"].append({
                "name": current_net,
                "nodes": current_nodes
            })
    
    return result


def build_component_pin_map_allegro(netlist_data):
    """建立元件引脚到网络的映射（Allegro格式）"""
    pin_map = {}
    for net in netlist_data["nets"]:
        net_name = net["name"]
        for node in net["nodes"]:
            ref, pin = node["ref"], node["pin"]
            if ref not in pin_map:
                pin_map[ref] = {}
            pin_map[ref][pin] = net_name
    return pin_map


def find_power_nets_allegro(netlist_data):
    """识别电源网络（Allegro格式）"""
    power_keywords = ["VCC", "VDD", "VIN", "VBAT", "V3V3", "V5V", "V12V", "PWR"]
    return [net for net in netlist_data["nets"] 
            if any(kw in net["name"].upper() for kw in power_keywords)]


def find_decoupling_caps_allegro(netlist_data, target_ref):
    """查找指定IC的去耦电容（Allegro格式）"""
    ic_power_pins = {}
    for net in netlist_data["nets"]:
        if any(kw in net["name"].upper() for kw in ["VCC", "VDD", "VIN"]):
            for node in net["nodes"]:
                if node["ref"] == target_ref:
                    ic_power_pins[node["pin"]] = net["name"]
    
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


def auto_detect_netlist_format(filepath):
    """自动检测netlist格式（KiCad或Allegro）"""
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        first_lines = f.read(1000)
    
    if '(export' in first_lines or '(design' in first_lines:
        return 'kicad'
    elif '$PACKAGES' in first_lines or '$NETS' in first_lines:
        return 'allegro'
    else:
        return 'unknown'


def parse_netlist_auto(filepath):
    """自动检测格式并解析netlist"""
    from . import kicad_netlist_parser
    
    format_type = auto_detect_netlist_format(filepath)
    
    if format_type == 'kicad':
        return kicad_netlist_parser.parse_kicad_netlist(filepath), 'kicad'
    elif format_type == 'allegro':
        return parse_allegro_netlist(filepath), 'allegro'
    else:
        raise ValueError(f"未知的netlist格式: {filepath}")


if __name__ == "__main__":
    print("OrCAD/Allegro Netlist解析器 - 用法示例：")
    print("  netlist = parse_allegro_netlist('design.net')")
    print("  pin_map = build_component_pin_map_allegro(netlist)")
    print("  或使用自动检测：")
    print("  netlist, format = parse_netlist_auto('design.net')")
