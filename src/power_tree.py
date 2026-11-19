#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
电源树拓扑生成器
基于netlist真实连接关系构建电源分配网络（PDN）拓扑
"""


def build_power_tree(netlist_data):
    """构建电源树拓扑"""
    components = netlist_data["components"]
    nets = netlist_data["nets"]
    
    # 识别电源转换器
    converters = []
    for comp in components:
        value_upper = comp["value"].upper()
        ref = comp["ref"]
        
        if any(kw in value_upper for kw in ["LDO", "AMS1117", "TLV", "LP29", "REG", "LM1117"]):
            converters.append({"ref": ref, "value": comp["value"], "type": "LDO"})
        elif any(kw in value_upper for kw in ["DCDC", "BUCK", "BOOST", "TPS", "SY8", "MP"]):
            converters.append({"ref": ref, "value": comp["value"], "type": "DCDC"})
    
    # 识别电源输入源
    input_sources = []
    for comp in components:
        ref = comp["ref"]
        if ref.startswith(("J", "P", "CON")):
            input_sources.append({"ref": ref, "value": comp["value"], "type": "Connector"})
    
    # 构建电源网络映射
    power_rails = {}
    for net in nets:
        net_name = net["name"]
        if any(kw in net_name.upper() for kw in ["VCC", "VDD", "VIN", "VBAT", "V3V3", "V5V", "V12V"]):
            loads = [{"ref": node["ref"], "pin": node["pin"]} for node in net["nodes"]]
            power_rails[net_name] = {"net_name": net_name, "node_count": len(loads), "loads": loads}
    
    # 识别转换器输入输出
    for converter in converters:
        ref = converter["ref"]
        converter["input_rail"] = None
        converter["output_rail"] = None
        
        connected_rails = []
        for net_name, rail_info in power_rails.items():
            if any(load["ref"] == ref for load in rail_info["loads"]):
                connected_rails.append(net_name)
        
        for rail in connected_rails:
            if any(kw in rail.upper() for kw in ["VIN", "VBAT", "INPUT"]):
                converter["input_rail"] = rail
            elif any(kw in rail.upper() for kw in ["VOUT", "V3V3", "V5V", "VCC", "VDD"]):
                converter["output_rail"] = rail
    
    return {
        "input_sources": input_sources,
        "converters": converters,
        "power_rails": power_rails,
        "statistics": {
            "total_power_rails": len(power_rails),
            "total_converters": len(converters),
            "total_input_sources": len(input_sources)
        }
    }


def generate_mermaid_power_tree(power_tree):
    """生成电源树Mermaid图表"""
    lines = ["graph TD"]
    
    # 输入源
    for source in power_tree["input_sources"]:
        lines.append(f"    {source['ref']}[\"{source['ref']}<br/>{source['value']}\"]:::input")
    
    # 转换器
    for conv in power_tree["converters"]:
        ref = conv["ref"]
        style = "ldo" if conv["type"] == "LDO" else "dcdc"
        lines.append(f"    {ref}[\"{ref}<br/>{conv['value']}<br/>({conv['type']})\"]:::{style}")
        
        if conv.get("input_rail") and conv.get("output_rail"):
            lines.append(f"    {conv['input_rail']} -->|{conv['type']}| {ref}")
            lines.append(f"    {ref} --> {conv['output_rail']}")
    
    # 电源轨道
    for rail_name, rail_info in list(power_tree["power_rails"].items())[:10]:
        lines.append(f"    {rail_name}[[\"{rail_name}<br/>{rail_info['node_count']} nodes\"]]:::rail")
    
    lines.append("")
    lines.append("    classDef input fill:#e74c3c,stroke:#c0392b,color:#fff")
    lines.append("    classDef ldo fill:#3498db,stroke:#2980b9,color:#fff")
    lines.append("    classDef dcdc fill:#9b59b6,stroke:#8e44ad,color:#fff")
    lines.append("    classDef rail fill:#2ecc71,stroke:#27ae60,color:#fff")
    
    return "\n".join(lines)


if __name__ == "__main__":
    print("电源树拓扑生成器")
