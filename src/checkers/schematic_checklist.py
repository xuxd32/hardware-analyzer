"""
原理图审查清单检查器 - Part 1
实现通用设计检查清单
"""

from typing import Dict, List


class SchematicChecker:
    """原理图审查清单检查器"""
    
    def __init__(self, components, nets, config):
        self.components = components
        self.nets = nets
        self.config = config
        self.issues = []
    
    def run_full_checklist(self):
        """运行完整检查清单"""
        results = {
            'power_checks': self.check_power_section(),
            'clock_checks': self.check_clock_section(),
            'interface_checks': self.check_interface_section(),
            'summary': self._generate_summary()
        }
        return results
    
    def check_power_section(self):
        """电源部分检查"""
        checks = []
        checks.append(self._check_decoupling_caps())
        checks.append(self._check_cap_proximity())
        checks.append(self._check_input_protection())
        return checks
    
    def check_clock_section(self):
        """时钟部分检查"""
        checks = []
        checks.append(self._check_crystal_caps())
        checks.append(self._check_clock_fanout())
        return checks
    
    def check_interface_section(self):
        """接口部分检查"""
        checks = []
        checks.append(self._check_esd_protection())
        checks.append(self._check_common_mode_choke())
        return checks

    
    
    # 具体检查实现
    
    def _check_decoupling_caps(self):
        """检查去耦电容配置"""
        rule_name = "所有芯片电源管脚都有去耦电容（100nF+10uF标配）"
        issues = []
        
        # 获取所有IC
        ics = [comp for ref, comp in self.components.items() if ref.startswith('U')]
        
        for ic in ics:
            nearby_caps = self._find_caps_for_ic(ic)
            if len(nearby_caps) == 0:
                issues.append({
                    'component': ic.ref,
                    'issue': '缺少去耦电容',
                    'severity': 'critical'
                })
        
        return {
            'rule': rule_name,
            'status': 'pass' if len(issues) == 0 else 'fail',
            'issues': issues,
            'checked': len(ics),
            'failed': len(issues)
        }
    
    def _check_cap_proximity(self):
        """检查去耦电容放置距离"""
        return {
            'rule': "去耦电容距离芯片 < 10mm",
            'status': 'not_applicable',
            'note': '需要PCB layout数据'
        }
    
    def _check_input_protection(self):
        """检查输入保护电路"""
        rule_name = "输入保护电路完整（TVS、保险丝、防反接）"
        issues = []
        
        tvs_count = len([c for ref, c in self.components.items() 
                        if 'TVS' in c.value.upper()])
        fuse_count = len([c for ref, c in self.components.items() 
                         if 'FUSE' in c.value.upper()])
        
        if tvs_count == 0:
            issues.append({'issue': '未发现TVS保护器件', 'severity': 'high'})
        if fuse_count == 0:
            issues.append({'issue': '未发现保险丝', 'severity': 'medium'})

        return {
            'rule': rule_name,
            'status': 'pass' if len(issues) == 0 else 'warning',
            'issues': issues,
            'tvs_count': tvs_count,
            'fuse_count': fuse_count
        }
        
    
    def _check_crystal_caps(self):
        """检查晶振负载电容"""
        crystals = [c for ref, c in self.components.items() if ref.startswith('Y')]
        return {
            'rule': "晶振负载电容计算正确",
            'status': 'not_implemented',
            'crystals_found': len(crystals)
        }
    
    def _check_clock_fanout(self):
        """检查时钟扇出"""
        return {
            'rule': "时钟扇出的负载数量 < 驱动能力",
            'status': 'not_implemented'
        }
    
    def _check_esd_protection(self):
        """检查ESD保护"""
        return {
            'rule': "ESD保护器件离接口 < 5mm",
            'status': 'not_applicable',
            'note': '需要PCB layout数据'
        }
    
    def _check_common_mode_choke(self):
        """检查共模扼流圈"""
        rule_name = "USB/HDMI等高速接口有共模扼流圈"
        issues = []
        
        choke_count = len([c for ref, c in self.components.items() 
                          if 'CMC' in c.value.upper() or 'CHOKE' in c.value.upper()])
        usb_count = len([c for ref, c in self.components.items() if 'USB' in c.value.upper()])
        
        if usb_count > 0 and choke_count == 0:
            issues.append({'issue': '高速接口缺少共模扼流圈', 'severity': 'high'})
        
        return {
            'rule': rule_name,
            'status': 'pass' if len(issues) == 0 else 'warning',
            'issues': issues
        }
    
    def _find_caps_for_ic(self, ic):
        """查找IC附近的电容"""
        return []  # TODO: 实现
    
    def _generate_summary(self):
        """生成检查摘要"""
        return {
            'total_components': len(self.components),
            'total_nets': len(self.nets),
            'total_issues': len(self.issues)
        }


