"""
电源链路分析器（⚠️ 已废弃 / 未接入主流程）

>>> 重要状态声明（2026-09-17）<<<
本模块是**旧框架残留（stub）**，未被主流程 `src/main.py` 引用（全项目仅
`test_demo.py` 引用它，而 test_demo 本身也是"测旧框架、待迁移/废弃"的）。
本模块多处是空实现/占位：
  - `build_power_tree()` 无 return
  - `analyze_voltage_drop()` 里 `estimated_drop = 0  # TODO`
  - `_get_power_pins()` 返回 `[]  # TODO`
  - `_estimate_load_current()` 硬编码 `1.0A`（魔法数，不代表工具行为）

>>> 活跃实现请看 <<<
真正的电源/母线掉压分析在 `src/main.py`：
  - `analyze_power`（PDN 目标阻抗，用 `--istep` 显式传瞬态电流）
  - `analyze_transient_droop`（母线掉压三段式，真实 netlist 电容 + 显式 I_step）
  - `calculators.py` 的 `bus_droop` / `pdn_target_impedance`
且电流是**显式参数**（`--istep`），不是硬编码魔法数。

>>> 为什么保留本文件 <<<
保守起见不删除（避免 test_demo 导入断裂），但标注弃用，禁止当作活跃功能误用。
禁止"看起来能用实则不能"的误导。
"""

from typing import Dict, List, Tuple


class PowerAnalyzer:
    """电源链路分析器"""
    
    def __init__(self, components, nets, config):
        self.components = components
        self.nets = nets
        self.config = config
        self.issues = []

    
    def analyze(self):
        """执行完整的电源分析"""
        results = {
            'power_tree': self.build_power_tree(),
            'voltage_drop': self.analyze_voltage_drop(),
            'decoupling': self.check_decoupling_caps(),
            'pdn_impedance': self.calculate_pdn_impedance(),
            'issues': self.issues
        }
        return results
    
    def build_power_tree(self):
        """构建电源树"""
        power_tree = {}
        
        # 识别电源IC（DCDC, LDO）
        power_ics = []
        for ref, comp in self.components.items():
            if self._is_power_ic(comp):
                power_ics.append(comp)
        
        # 构建树状结构
        for ic in power_ics:
            input_net = self._get_input_net(ic)
            output_net = self._get_output_net(ic)
            
            if output_net:
                power_tree[output_net] = {
                    'source': ic.ref,
                    'type': self._get_power_ic_type(ic),
                    'input': input_net,
                    'loads': self._find_loads(output_net)
                }
        
    
    def analyze_voltage_drop(self):
        """直流压降分析"""
        voltage_drops = {}
        
        rules = self.config['power_rules']['voltage_drop']
        tolerance = rules['tolerance_percent']
        
        for net_name, net in self.nets.items():
            if self._is_power_net(net_name):
                total_current = self._estimate_load_current(net_name)
                
                voltage_drops[net_name] = {
                    'current': total_current,
                    'estimated_drop': 0,  # TODO: 需要PCB数据
                    'tolerance': tolerance,
                    'status': 'unknown'
                }
        
        return voltage_drops
    
    def check_decoupling_caps(self):
        """去耦电容配置检查"""
        decoupling_issues = []
        
        ics = [comp for ref, comp in self.components.items() if ref.startswith('U')]
        
        for ic in ics:
            power_pins = self._get_power_pins(ic)
            
            for pin in power_pins:
                net = ic.pins.get(pin, None)
                if net:
                    caps = self._find_nearby_caps(ic, net)
                    
                    has_100nF = any(self._is_cap_value(c, "100nF") for c in caps)
                    has_10uF = any(self._is_cap_value(c, "10uF") for c in caps)
                    
                    if not has_100nF:
                        decoupling_issues.append({
                            'component': ic.ref,
                            'net': net,
                            'issue': 'missing_100nF',
                            'severity': 'critical'
                        })
        
    
    def calculate_pdn_impedance(self):
        """PDN 目标阻抗计算"""
        pdn_targets = {}
        
        rules = self.config['power_rules']['pdn_impedance']
        default_ripple = rules['default_ripple_mv'] / 1000
        
        for net_name in self.nets:
            if self._is_power_net(net_name):
                transient_current = self._estimate_transient_current(net_name)
                
                if transient_current > 0:
                    z_target = default_ripple / transient_current
                    
                    pdn_targets[net_name] = {
                        'ripple_max_v': default_ripple,
                        'transient_current_a': transient_current,
                        'target_impedance_mohm': z_target * 1000
                    }
        
        return pdn_targets
    
    # 辅助方法
    
    def _is_power_ic(self, component):
        """判断是否为电源IC"""
        power_keywords = ['LDO', 'DCDC', 'BUCK', 'REGULATOR', 'TPS']
        return any(kw in component.value.upper() for kw in power_keywords)
    
    def _is_power_net(self, net_name):
        """判断是否为电源网络"""
        power_keywords = ['+', 'VCC', 'VDD', 'VBAT', 'V3V3', 'V5V']
        return any(kw in net_name.upper() for kw in power_keywords)
    
    def _get_power_ic_type(self, component):
        """获取电源IC类型"""
        if 'LDO' in component.value.upper():
            return 'LDO'
        elif 'DCDC' in component.value.upper():
            return 'DCDC'
        return 'Unknown'
    
    def _get_input_net(self, component):
        """获取电源IC输入网络"""
        for pin, net in component.pins.items():
            if 'VIN' in pin.upper():
                return net
        return None
    
    def _get_output_net(self, component):
        """获取电源IC输出网络"""
        for pin, net in component.pins.items():
            if 'VOUT' in pin.upper():
                return net
        return None
    
    def _find_loads(self, net_name):
        """查找电源网络的负载"""
        loads = []
        net = self.nets.get(net_name)
        if net:
            for ref, pin in net.connections:
                loads.append(ref)
        return loads
    
    def _get_power_pins(self, component):
        """获取IC的电源管脚"""
        return []  # TODO: 实现
    
    def _find_nearby_caps(self, ic, net_name):
        """查找网络上的电容"""
        caps = []
        net = self.nets.get(net_name)
        if net:
            for ref, pin in net.connections:
                if ref.startswith('C'):
                    comp = self.components.get(ref)
                    if comp:
                        caps.append(comp)
        return caps
    
    def _is_cap_value(self, cap, target_value):
        """判断电容值是否匹配"""
        return target_value.lower() in cap.value.lower()
    
    def _estimate_load_current(self, net_name):
        """估算负载电流（⚠️ 废弃占位：旧框架魔法数，未被主流程调用）。

        本方法硬编码 1.0A，不代表工具实际行为。主流程用 `--istep` 显式传瞬态
        电流（见 src/main.py analyze_transient_droop），不经过这里。
        """
        return 1.0  # 默认1A —— 魔法数，仅旧框架占位，禁止当活跃估算值用

    def _estimate_transient_current(self, net_name):
        """估算瞬态电流（⚠️ 废弃占位：×1.2 是旧框架假设，未被主流程调用）。"""
        return self._estimate_load_current(net_name) * 1.2  # 魔法数，见上


