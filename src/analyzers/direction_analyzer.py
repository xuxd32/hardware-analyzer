"""
方向分析引擎 - Direction Analysis Engine

基于THEORY_1/2/3理论文档，提供方向性诊断指导
定位：给出可能的方向和判断方法，不替代工程师判断
"""

from typing import Dict, List, Tuple, Optional
import re


class DirectionAnalyzer:
    """方向分析引擎 - 基于故障现象给出可能的方向"""
    
    def __init__(self, netlist_data: Dict, analysis_data: Dict):
        """
        初始化方向分析器
        
        Args:
            netlist_data: netlist解析数据
            analysis_data: 基础分析数据（电源/信号/时钟等）
        """
        self.netlist = netlist_data
        self.analysis = analysis_data
        self.directions = []
        self.detected_issues = []
    
    def analyze(self) -> Dict:
        """
        执行方向分析
        
        Returns:
            方向分析结果，包含：
            - detected_issues: 检测到的异常
            - possible_directions: 可能的方向（P0/P1/P2）
            - recommendations: 建议的下一步行动
        """
        # 1. 检测异常
        self._detect_power_timing_issues()
        self._detect_reset_issues()
        self._detect_ground_issues()
        self._detect_decoupling_issues()
        self._detect_signal_issues()
        
        # 2. 根据异常生成方向
        self._generate_directions()
        
        # 3. 优先级排序
        self._prioritize_directions()
        
        return {
            'detected_issues': self.detected_issues,
            'possible_directions': self.directions,
            'recommendations': self._generate_recommendations(),
            'theory_references': self._get_theory_references()
        }

    def _get_components(self):
        """兼容多种 netlist 结构，返回 components（list 或 dict）。

        真实结构（main.py 传入）：self.netlist['netlist']['netlist_data']['components'] 是 list。
        旧测试结构：self.netlist['netlist']['components'] 是 dict。
        """
        nl = self.netlist.get('netlist', {})
        comps = nl.get('netlist_data', {}).get('components')
        if comps is not None:
            return comps
        return nl.get('components')

    def _get_nets(self):
        """兼容多种 netlist 结构，返回 nets（list 或 dict）。"""
        nl = self.netlist.get('netlist', {})
        nets = nl.get('netlist_data', {}).get('nets')
        if nets is not None:
            return nets
        return nl.get('nets')

    def _detect_power_timing_issues(self):
        """检测电源时序问题 - 对应 THEORY_2 §2.1"""
        if 'power_nets' not in self.analysis:
            return
        
        power_nets = self.analysis['power_nets']
        
        # 查找核心电源和IO电源
        core_nets = [n for n in power_nets if self._is_core_power(n)]
        io_nets = [n for n in power_nets if self._is_io_power(n)]
        
        if core_nets and io_nets:
            # 检测是否有多电源域
            self.detected_issues.append({
                'type': 'multi_power_domain',
                'severity': 'warning',
                'description': f'检测到多电源域：核心域 {len(core_nets)}个，IO域 {len(io_nets)}个',
                'detail': {
                    'core_nets': core_nets[:3],  # 最多显示3个
                    'io_nets': io_nets[:3]
                },
                'risk': '如果时序不正确，可能导致Latch-up或启动失败',
                'check_method': '使用示波器测量VDD_CORE和VDD_IO上电顺序'
            })
    
    def _detect_reset_issues(self):
        """检测RESET相关问题 - 对应 THEORY_2 §2.2"""
        # 查找RESET网络
        reset_nets = []
        classified = self.analysis.get('classified_nets', {})
        
        for net in classified.get('control', []):
            if any(kw in net.upper() for kw in ['RESET', 'RST', 'NRST']):
                reset_nets.append(net)
        
        if reset_nets:
            # 查找RESET电路中的RC元件
            reset_caps = []
            reset_resistors = []
            
            nets = self._get_nets()
            if nets:
                for net in reset_nets:
                    if isinstance(nets, list):
                        for n in nets:
                            if n.get('name', '').upper() == net.upper():
                                for node in n.get('nodes', []):
                                    ref = node.get('ref', '')
                                    if ref.startswith('C'):
                                        reset_caps.append(ref)
                                    elif ref.startswith('R'):
                                        reset_resistors.append(ref)
                    else:
                        net_data = nets.get(net, {})
                        connections = net_data.get('connections', [])
                        for ref, pin in connections:
                            if ref.startswith('C'):
                                reset_caps.append(ref)
                            elif ref.startswith('R'):
                                reset_resistors.append(ref)
            
            self.detected_issues.append({
                'type': 'reset_circuit',
                'severity': 'info',
                'description': f'检测到RESET电路：{len(reset_nets)}个RESET网络',
                'detail': {
                    'reset_nets': reset_nets,
                    'caps': reset_caps,
                    'resistors': reset_resistors
                },
                'risk': 'RESET延迟不足可能导致启动失败或概率性重启',
                'check_method': '示波器测量RESET释放时刻vs电源稳定时间（应>10ms）'
            })
    
    def _detect_ground_issues(self):
        """检测地回流路径问题 - 对应 THEORY_2 §2.3"""
        if 'gnd_signal_count' not in self.analysis:
            return
        
        gnd_count = self.analysis['gnd_signal_count']
        
        if gnd_count > 10:
            # 多个地网络可能表示地分割
            self.detected_issues.append({
                'type': 'multiple_gnd_nets',
                'severity': 'warning',
                'description': f'检测到{gnd_count}个地网络',
                'detail': {
                    'gnd_count': gnd_count
                },
                'risk': '地平面分割可能导致回流路径过长，引起电源跌落或EMI问题',
                'check_method': 'PCB查看地平面完整性，检查是否有大面积分割'
            })
    
    def _detect_decoupling_issues(self):
        """检测去耦电容配置问题 - 对应 THEORY_2 §2.5"""
        comps = self._get_components()
        if not comps:
            return
        
        # 统计电容数量和容值分布
        caps = {}
        if isinstance(comps, list):
            for c in comps:
                ref = c.get('ref', '')
                if ref.startswith('C'):
                    caps[ref] = c.get('value', '').upper()
        else:
            for ref, comp in comps.items():
                if ref.startswith('C'):
                    caps[ref] = comp.get('value', '').upper()
        
        # 统计100nF和10uF电容
        cap_100nf = sum(1 for v in caps.values() if '100N' in v or '0.1U' in v)
        cap_10uf = sum(1 for v in caps.values() if '10U' in v)
        
        total_caps = len(caps)
        
        if total_caps > 0:
            self.detected_issues.append({
                'type': 'decoupling_capacitors',
                'severity': 'info',
                'description': f'去耦电容配置：总计{total_caps}个',
                'detail': {
                    'total': total_caps,
                    '100nF': cap_100nf,
                    '10uF': cap_10uf
                },
                'risk': '去耦电容不足或距离过远可能导致电源纹波过大',
                'check_method': '检查每个IC旁边是否有100nF+10uF，距离<5mm'
            })
    
    def _detect_signal_issues(self):
        """检测信号完整性相关问题"""
        # 检测电平转换器
        level_shifters = []
        
        comps = self._get_components()
        if comps:
            if isinstance(comps, list):
                for c in comps:
                    value = c.get('value', '').upper()
                    if any(kw in value for kw in ['TXS', 'TXB', 'LSF', 'GTL']):
                        level_shifters.append({'ref': c.get('ref', ''), 'value': c.get('value', '')})
            else:
                for ref, comp in comps.items():
                    value = comp.get('value', '').upper()
                    if any(kw in value for kw in ['TXS', 'TXB', 'LSF', 'GTL']):
                        level_shifters.append({'ref': ref, 'value': comp.get('value', '')})
        
        if level_shifters:
            self.detected_issues.append({
                'type': 'level_shifter',
                'severity': 'warning',
                'description': f'检测到电平转换器：{len(level_shifters)}个',
                'detail': {'shifters': level_shifters},
                'risk': '某些电平转换器（如TXS0108E）驱动能力弱，长时间传输可能失效',
                'check_method': '检查是否用于连续传输（如GPS UART），考虑更换为强驱动型号'
            })
    
    def _generate_directions(self):
        """根据检测到的异常生成方向"""
        p0_directions = []
        p1_directions = []
        
        for issue in self.detected_issues:
            if issue['type'] == 'multi_power_domain':
                p0_directions.append({
                    'priority': 'P0', 'direction': '电源时序检查',
                    'reason': issue['description'], 'check_method': issue['check_method'],
                    'theory_ref': 'THEORY_2_POWER_CHECKLIST.md §2.1',
                    'severity': issue['severity']
                })
            elif issue['type'] == 'reset_circuit':
                p0_directions.append({
                    'priority': 'P0', 'direction': 'RESET过早释放检查',
                    'reason': issue['description'], 'check_method': issue['check_method'],
                    'theory_ref': 'THEORY_2_POWER_CHECKLIST.md §2.2',
                    'severity': issue['severity']
                })
            elif issue['type'] == 'multiple_gnd_nets':
                p0_directions.append({
                    'priority': 'P0', 'direction': '地回流路径检查',
                    'reason': issue['description'], 'check_method': issue['check_method'],
                    'theory_ref': 'THEORY_2_POWER_CHECKLIST.md §2.3',
                    'severity': issue['severity']
                })
            elif issue['type'] == 'decoupling_capacitors':
                p1_directions.append({
                    'priority': 'P1', 'direction': '电源纹波检查',
                    'reason': issue['description'], 'check_method': issue['check_method'],
                    'theory_ref': 'THEORY_2_POWER_CHECKLIST.md §2.5',
                    'severity': issue['severity']
                })
            elif issue['type'] == 'level_shifter':
                p1_directions.append({
                    'priority': 'P1', 'direction': '电平转换器检查',
                    'reason': issue['description'], 'check_method': issue['check_method'],
                    'theory_ref': 'THEORY_1_FAULT_DIRECTION_MAP.md §3.1',
                    'severity': issue['severity']
                })
        
        self.directions = p0_directions + p1_directions
    
    def _prioritize_directions(self):
        """优先级排序"""
        priority_order = {'P0': 0, 'P1': 1, 'P2': 2}
        severity_order = {'critical': 0, 'warning': 1, 'info': 2}
        self.directions.sort(key=lambda x: (
            priority_order.get(x['priority'], 99),
            severity_order.get(x['severity'], 99)
        ))
    
    def _generate_recommendations(self) -> List[str]:
        """生成建议的下一步行动"""
        recommendations = []
        
        if not self.directions:
            recommendations.append("未检测到明显异常，建议：")
            recommendations.append("1. 如遇到问题，参考 THEORY_1_FAULT_DIRECTION_MAP.md 查找方向")
            recommendations.append("2. 使用示波器实测关键信号")
            return recommendations
        
        recommendations.append("建议按以下顺序检查：")
        for i, direction in enumerate(self.directions[:5], 1):
            recommendations.append(f"{i}. [{direction['priority']}] {direction['direction']}")
            recommendations.append(f"   验证方法：{direction['check_method']}")
            recommendations.append(f"   参考文档：{direction['theory_ref']}")
        
        if len(self.directions) > 5:
            recommendations.append(f"... 还有 {len(self.directions)-5} 个方向，详见完整报告")
        
        return recommendations
    
    def _get_theory_references(self) -> Dict:
        """获取理论文档引用"""
        return {
            'fault_direction_map': 'THEORY_1_FAULT_DIRECTION_MAP.md',
            'power_checklist': 'THEORY_2_POWER_CHECKLIST.md',
            'methodology': 'THEORY_3_METHODOLOGY.md',
            'description': '详细的检查方法和判断标准请参考理论文档'
        }
    
    def _is_core_power(self, net_name: str) -> bool:
        """判断是否为核心电源"""
        core_keywords = ['CORE', 'VDD_CORE', 'VDDCORE', '1V2', '1.2V', '0V9', '0.9V']
        return any(kw in net_name.upper() for kw in core_keywords)
    
    def _is_io_power(self, net_name: str) -> bool:
        """判断是否为IO电源"""
        io_keywords = ['VDD_IO', 'VDDIO', '3V3', '3.3V', '1V8', '1.8V', 'VCCIO']
        return any(kw in net_name.upper() for kw in io_keywords)


def format_direction_report(direction_result: Dict) -> str:
    """格式化方向分析报告（终端输出）"""
    lines = []
    lines.append("=" * 80)
    lines.append("方向分析诊断结果".center(76))
    lines.append("=" * 80)
    lines.append("")
    
    # 1. 检测到的异常
    issues = direction_result.get('detected_issues', [])
    if issues:
        lines.append("【检测到的异常】")
        lines.append("")
        for i, issue in enumerate(issues, 1):
            lines.append(f"{i}. [{issue['severity'].upper()}] {issue['description']}")
            lines.append(f"   风险：{issue['risk']}")
            lines.append(f"   验证方法：{issue['check_method']}")
            lines.append("")
    else:
        lines.append("【检测到的异常】未检测到明显异常")
        lines.append("")
    
    # 2. 可能的方向
    directions = direction_result.get('possible_directions', [])
    if directions:
        lines.append("【可能的方向】（按优先级排序）")
        lines.append("")
        
        p0_dirs = [d for d in directions if d['priority'] == 'P0']
        p1_dirs = [d for d in directions if d['priority'] == 'P1']
        
        if p0_dirs:
            lines.append("P0 - 优先检查（必须验证）：")
            for i, d in enumerate(p0_dirs, 1):
                lines.append(f"  {i}. {d['direction']}")
                lines.append(f"     原因：{d['reason']}")
                lines.append(f"     验证：{d['check_method']}")
                lines.append(f"     参考：{d['theory_ref']}")
                lines.append("")
        
        if p1_dirs:
            lines.append("P1 - 次要检查（如P0无异常再查）：")
            for i, d in enumerate(p1_dirs, 1):
                lines.append(f"  {i}. {d['direction']}")
                lines.append(f"     原因：{d['reason']}")
                lines.append(f"     验证：{d['check_method']}")
                lines.append(f"     参考：{d['theory_ref']}")
                lines.append("")
    else:
        lines.append("【可能的方向】当前数据未发现明显方向，建议实测验证")
        lines.append("")
    
    # 3. 建议
    recommendations = direction_result.get('recommendations', [])
    if recommendations:
        lines.append("【建议的下一步】")
        lines.append("")
        for rec in recommendations:
            lines.append(rec)
        lines.append("")
    
    # 4. 理论文档引用
    theory_refs = direction_result.get('theory_references', {})
    lines.append("【理论文档】")
    lines.append("")
    lines.append(f"故障方向地图：{theory_refs.get('fault_direction_map', 'N/A')}")
    lines.append(f"电源检查清单：{theory_refs.get('power_checklist', 'N/A')}")
    lines.append(f"参考依据：  {theory_refs.get('methodology', 'N/A')}")
    lines.append("")
    lines.append(theory_refs.get('description', ''))
    lines.append("")
    
    # 5. 重要提醒
    lines.append("=" * 80)
    lines.append("【重要提醒】")
    lines.append("")
    lines.append("✓ 本工具给出方向性指导，不替代工程师判断")
    lines.append("✓ 请结合实际测量验证（示波器/万用表/PCB查看）")
    lines.append("✓ 实测结果为准，不要先入为主")
    lines.append("✓ 详细的判断标准和方法请参考理论文档")
    lines.append("")
    lines.append("=" * 80)
    
    return "\n".join(lines)


