"""
KiCad原理图解析器
支持KiCad 5.x (.sch) 和 KiCad 6+ (.kicad_sch)格式
"""

import re
from pathlib import Path
from typing import Dict, List, Tuple
import json


class Component:
    """元件对象"""
    def __init__(self, ref, value, footprint, library=""):
        self.ref = ref  # 参考编号，如 U1, R1, C1
        self.value = value  # 值，如 10K, 100nF
        self.footprint = footprint
        self.library = library
        self.pins = {}  # {pin_number: net_name}
        self.properties = {}
    
    def __repr__(self):
        return f"Component({self.ref}, {self.value}, {self.footprint})"


class Net:
    """网络对象"""
    def __init__(self, name):
        self.name = name
        self.connections = []  # [(ref, pin), ...]
    
    def add_connection(self, ref, pin):
        self.connections.append((ref, pin))
    
    def __repr__(self):
        return f"Net({self.name}, {len(self.connections)} connections)"


class KiCadParser:
    """KiCad原理图解析器"""
    
    def __init__(self, schematic_path):
        self.schematic_path = Path(schematic_path)
        self.components = {}  # {ref: Component}
        self.nets = {}  # {net_name: Net}
        self.format_version = None
        
    def parse(self):
        """解析原理图"""
        if not self.schematic_path.exists():
            raise FileNotFoundError(f"原理图文件不存在: {self.schematic_path}")
        
        # 判断文件格式
        with open(self.schematic_path, 'r', encoding='utf-8') as f:
            first_line = f.readline().strip()
            
        if first_line.startswith('EESchema'):
            self.format_version = 5
            self._parse_kicad5()
        elif first_line.startswith('(kicad_sch'):
            self.format_version = 6
            self._parse_kicad6()
        else:
            raise ValueError(f"不支持的文件格式: {first_line}")
        
        return self.components, self.nets
    
    def _parse_kicad5(self):
        """解析KiCad 5.x格式 (.sch)"""
        with open(self.schematic_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            
            # 解析元件
            if line.startswith('$Comp'):
                comp_lines = []
                i += 1
                while i < len(lines) and not lines[i].strip().startswith('$EndComp'):
                    comp_lines.append(lines[i].strip())
                    i += 1
                
                self._parse_kicad5_component(comp_lines)
            
            i += 1
    
    def _parse_kicad5_component(self, lines):
        """解析KiCad 5.x格式的元件"""
        ref = value = footprint = library = ""
        
        for line in lines:
            if line.startswith('L '):
                parts = line.split()
                if len(parts) >= 3:
                    library = parts[1]
                    ref = parts[2]
            elif line.startswith('F 0'):
                ref = self._extract_quoted_value(line)
            elif line.startswith('F 1'):
                value = self._extract_quoted_value(line)
            elif line.startswith('F 2'):
                footprint = self._extract_quoted_value(line)
        
        if ref:
            comp = Component(ref, value, footprint, library)
            self.components[ref] = comp
    
    def _parse_kicad6(self):
        """解析KiCad 6+ S-expression格式 (.kicad_sch)"""
        with open(self.schematic_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 简化版解析（实际需要完整的S-expression解析器）
        # TODO: 实现完整的KiCad 6+解析
        pass
    
    def _extract_quoted_value(self, line):
        """提取引号中的值"""
        match = re.search(r'"([^"]*)"', line)
        return match.group(1) if match else ""
    
    def get_power_nets(self):
        """获取电源网络"""
        power_keywords = ['+', 'VCC', 'VDD', 'VBAT', 'V3V3', 'V5V', 'V12V', 
                         'GND', 'DGND', 'AGND', 'PWR']
        power_nets = {}
        
        for net_name, net in self.nets.items():
            if any(keyword in net_name.upper() for keyword in power_keywords):
                power_nets[net_name] = net
        
        return power_nets
    
    def get_component_by_type(self, component_type):
        """根据类型获取元件列表"""
        result = []
        for ref, comp in self.components.items():
            if ref.startswith(component_type):
                result.append(comp)
        return result
